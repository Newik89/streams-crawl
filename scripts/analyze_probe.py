"""
Второй проход: анализ УЖЕ СКАЧАННЫХ html-файлов из recon/raw_quick/
(новых запросов к сайтам не делает).

Заполняет в recon/sources.csv колонки:
    http_status, parse_level, needs_js, protection, notes

url_pattern не трогает (следующий этап).
Строки 10 "чужих" доменов не трогает.
"""

import csv
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_CSV = ROOT / "recon" / "sources.csv"
RAW_DIR = ROOT / "recon" / "raw_quick"

SKIP_DOMAINS = {
    "nova.bg",
    "tv.nova.cz",
    "teleman.pl",
    "sporttv.pt",
    "polsatsport.pl",
    "digisport.ro",
    "tvarenasport.hr",
    "beinsports.com.tr",
    "cosmotetv.gr",
    "livesoccertv.com",
}

TIME_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")
# ISO-таймстамп вида 2026-08-28T19:30:00+03:00 (datePublished/dateModified/
# postDate и т.п.) даёт 2-3 ложных совпадения ЧЧ:ММ обычному TIME_RE сразу
# на нескольких участках строки (HH:MM, потом MM:SS, потом таймзона ЧЧ:ММ).
# Поэтому перед подсчётом меток времени сначала вырезаем целиком все такие
# ISO-таймстампы - остаются только "настоящие" отдельно стоящие ЧЧ:ММ.
ISO_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")

INLINE_SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.I | re.S)
SRC_ATTR_RE = re.compile(r"\bsrc\s*=", re.I)
VAR_ASSIGN_RE = re.compile(r"\s*(?:window\.|var\s+|let\s+|const\s+)([A-Za-z_$][\w$]*)\s*=")

# Признак вызова api-эндпоинта с расписанием прямо в коде страницы.
API_HINT_RE = re.compile(
    r"""(?ix)
    (?:
        https?://[^\s"'<>]*?
        (?:
            /api[^\s"'<>]*(?:schedule|program|epg|guide|listing|events?)[^\s"'<>]*
            |
            (?:schedule|program|epg|guide)[^\s"'<>]*\.json
        )
    )
    """
)
# URL, которые формально попадают под API_HINT_RE, но на деле не имеют
# отношения к расписанию (PWA-манифест, аналитика/трекинг и т.п.).
API_HINT_EXCLUDE = [
    "manifest.json", "webmanifest", "gtm/", "/ga/", "google-analytics",
    "gtag", "sitemap", "service-worker", "sw.js", "favicon", "/collect",
]

# Типы schema.org, которые однозначно говорят о расписании эфира,
# в отличие от общих Organization/WebSite/BreadcrumbList/WebPage.
SCHEDULE_TYPE_MARKERS = [
    "broadcastevent", "sportsevent", "tvepisode", "tvseason", "tvseries",
]
MIN_TIME_MATCHES_IN_BLOB = 6
MIN_DISTINCT_TIMES_IN_BLOB = 4

# Пары полей start/stop (или startTime/endTime и т.п.) с ISO-таймстампами -
# характерная сигнатура готового EPG-JSON. В отличие от JSON_MARKERS ищем
# по ВСЕЙ странице, не только внутри <script> - иногда такие данные лежат
# прямо в теле HTML (не внутри <script>), например у programetv.ro.
SCHEDULE_FIELD_PAIR_RE = re.compile(
    r'"(?:start|startTime|start_time|startDate)"\s*:\s*"[^"]{5,40}"\s*,\s*'
    r'"(?:stop|end|endTime|end_time|endDate)"\s*:\s*"[^"]{5,40}"',
    re.I,
)
MIN_FIELD_PAIRS = 3

CLOUDFLARE_MARKERS = [
    "just a moment", "checking your browser", "cf-browser-verification",
    "cloudflare-challenge", "__cf_chl", "challenges.cloudflare.com",
    "attention required! | cloudflare", "id=\"challenge-running\"",
]
# Явные фразы "докажи, что ты человек" - настоящая блокировка, а не просто
# виджет recaptcha в форме обратной связи где-то на странице.
HUMAN_CHECK_PHRASES = [
    "verify you are human", "are you a robot", "unusual traffic",
    "prove you are not a robot", "checking if the site connection is secure",
    "one more step", "select all images", "let us know you're not a robot",
]
CAPTCHA_WIDGET_MARKERS = [
    "g-recaptcha", "recaptcha", "h-captcha", "hcaptcha", "captcha-delivery.com",
    "px-captcha", "datadome", "perimeterx", "incapsula",
]
WAF_ACCESS_DENIED_MARKERS = [
    ("errors.edgesuite.net", "Akamai (Access Denied)"),
    ("web application firewall", "WAF (Access Denied)"),
]
COOKIE_MARKERS = [
    "we use cookies", "accept cookies", "accept all cookies", "this website uses cookies",
    "manage cookies", "cookie settings", "тільки з увімкненими cookie", "cookies must be enabled",
]


def load_status(domain: str):
    status_path = RAW_DIR / f"{domain}.status.txt"
    if not status_path.exists():
        return None, None
    lines = status_path.read_text(encoding="utf-8", errors="replace").splitlines()
    status_text = lines[0].strip() if lines else ""
    url = lines[1].strip() if len(lines) > 1 else ""
    return status_text, url


def visible_text(text: str) -> str:
    """Текст страницы без содержимого <script>/<style> и без тегов."""
    no_script = SCRIPT_STYLE_RE.sub(" ", text)
    no_tags = TAG_RE.sub(" ", no_script)
    return re.sub(r"\s+", " ", no_tags).strip()


def count_times(s: str) -> int:
    """Кол-во меток времени ЧЧ:ММ, ISO-таймстампы (datePublished и т.п.) не считаются."""
    return len(TIME_RE.findall(ISO_DATETIME_RE.sub(" ", s)))


def schedule_like(blob: str):
    """
    (bool, кол-во меток времени внутри блока) - похож ли JSON-блок на расписание.

    Два независимых признака (любого достаточно):
    - явный schema.org-тип вроде BroadcastEvent/SportsEvent/TVEpisode - этому
      верим сразу, даже если меток времени рядом мало (они там в ISO-формате);
    - много (>=6) меток времени ЧЧ:ММ, из них >=4 РАЗНЫХ значений - защита от
      случайных совпадений вроде повторяющегося "00:00:00 UTC" в коде
      трекинг-скриптов/куки (одно и то же значение много раз - не расписание).
    """
    if not blob:
        return False, 0
    bl = blob.lower()
    if any(k in bl for k in SCHEDULE_TYPE_MARKERS):
        return True, count_times(blob)
    times = TIME_RE.findall(ISO_DATETIME_RE.sub(" ", blob))
    tcount = len(times)
    if tcount >= MIN_TIME_MATCHES_IN_BLOB and len(set(times)) >= MIN_DISTINCT_TIMES_IN_BLOB:
        return True, tcount
    return False, tcount


def label_for_script(attrs: str, content: str) -> str:
    al = attrs.lower()
    cl = content.lower()
    if "application/ld+json" in al:
        return "ld+json"
    if "__next_data__" in al or "__next_data__" in cl:
        return "__NEXT_DATA__ (Next.js)"
    if "__nuxt__" in cl:
        return "__NUXT__ (Nuxt.js)"
    if "__initial_state__" in cl:
        return "__INITIAL_STATE__"
    if "__preloaded_state__" in cl:
        return "__PRELOADED_STATE__"
    if "__apollo_state__" in cl:
        return "__APOLLO_STATE__ (Apollo/GraphQL)"
    m = VAR_ASSIGN_RE.match(content)
    if m:
        return f"инлайн-переменная {m.group(1)}"
    if "application/json" in al:
        return "инлайн <script type=\"application/json\">"
    return "инлайн <script> с JSON-подобными данными"


def check_json_markers(text: str):
    """
    Сканирует ВСЕ инлайн <script>-блоки страницы (ld+json, __NEXT_DATA__,
    __NUXT__, произвольные `window.XXX = {...}` и т.п.) и ищет среди них
    такой, что реально похож на расписание (schedule_like).

    Возвращает (found: bool, label, time_in_blob, generic_hits: list[str]).
    generic_hits - какие маркеры встретились, но оказались generic
    (SEO/навигация/пустой каркас), чтобы честно упомянуть их в notes.
    """
    generic_hits = []
    best = None  # (label, tcount)
    for m in INLINE_SCRIPT_RE.finditer(text):
        attrs, content = m.group(1), m.group(2)
        if SRC_ATTR_RE.search(attrs):
            continue  # внешний скрипт, содержимого нет
        if not content.strip():
            continue
        ok, tcount = schedule_like(content)
        if ok:
            if best is None or tcount > best[1]:
                best = (label_for_script(attrs, content), tcount)
        else:
            cl = content.lower()
            al = attrs.lower()
            if "application/ld+json" in al:
                generic_hits.append("ld+json есть, но похоже на SEO/оргданные (не расписание)")
            elif "__next_data__" in al or "__next_data__" in cl:
                generic_hits.append("__NEXT_DATA__ есть, но похоже на пустой каркас/навигацию (не расписание)")
            elif "__nuxt__" in cl:
                generic_hits.append("__NUXT__ есть, но похоже на пустой каркас/навигацию (не расписание)")
            elif "__initial_state__" in cl:
                generic_hits.append("__INITIAL_STATE__ есть, но похоже на пустой каркас (не расписание)")
    # убрать дубликаты, сохранив порядок
    generic_hits = list(dict.fromkeys(generic_hits))
    if best:
        return True, best[0], best[1], generic_hits
    return False, None, 0, generic_hits


def classify(domain: str):
    """Возвращает dict с http_status, parse_level, needs_js, protection, notes."""
    status_text, _url = load_status(domain)
    html_path = RAW_DIR / f"{domain}.html"

    if status_text is None:
        return {
            "http_status": "?",
            "parse_level": "?",
            "needs_js": "",
            "protection": "",
            "notes": "не скачано (probe не запускался для этого домена)",
        }

    if status_text in ("timeout", "dns", "ssl") or status_text.startswith("error:"):
        return {
            "http_status": status_text,
            "parse_level": "?",
            "needs_js": "",
            "protection": "",
            "notes": "запрос не удался, тело не получено",
        }

    try:
        http_code = int(status_text)
    except ValueError:
        http_code = None

    body = b""
    if html_path.exists():
        body = html_path.read_bytes()
    text = body.decode("utf-8", errors="replace")
    text_lower = text.lower()

    notes_bits = []

    # --- Сначала определяем parse_level/needs_js (по содержимому) ---
    if not html_path.exists() or len(body) == 0:
        parse_level = "?"
        notes_bits.append("тело страницы пустое/не сохранено")
        needs_js = ""
        vis = ""
        vis_len = 0
    else:
        time_count_full = count_times(text)
        vis = visible_text(text)
        vis_len = len(vis)
        vis_time_count = count_times(vis)

        json_ok, json_label, json_tcount, generic_hits = check_json_markers(text)

        if not json_ok:
            pairs = SCHEDULE_FIELD_PAIR_RE.findall(text)
            if len(pairs) >= MIN_FIELD_PAIRS:
                json_ok = True
                json_label = f"JSON с полями start/stop (пар в исходнике: {len(pairs)})"
                json_tcount = len(pairs)

        api_hint = None
        if not json_ok:
            for m in API_HINT_RE.finditer(text):
                candidate = m.group(0)
                cl = candidate.lower()
                if any(bad in cl for bad in API_HINT_EXCLUDE):
                    continue
                api_hint = candidate[:120]
                break

        if json_ok:
            parse_level = "A"
            needs_js = "no"
            notes_bits.append(f"найден JSON с расписанием: {json_label} (меток времени в блоке: {json_tcount})")
        elif api_hint:
            parse_level = "A"
            needs_js = "no"
            notes_bits.append(f"в коде виден вызов API с расписанием: {api_hint}")
        elif vis_time_count >= 5:
            parse_level = "B"
            needs_js = "no"
            notes_bits.append(f"меток времени ЧЧ:ММ в видимом тексте HTML: {vis_time_count}")
        else:
            parse_level = "D"
            needs_js = "yes"
            notes_bits.append(
                f"меток времени в видимом тексте: {vis_time_count} (видимого текста ~{vis_len} симв., "
                f"всего меток времени в исходнике вкл. скрипты: {time_count_full}) - похоже, расписание рисует JS"
            )

        if generic_hits:
            notes_bits.append("; ".join(generic_hits))

    # --- Затем защита. Если контент (A/B) уже реально получен обычным GET,
    # слабые сигналы (просто виджет recaptcha где-то на странице) не считаем
    # блокировкой - раз данные пришли, значит защита нас не остановила. ---
    protection = ""
    protection_note = ""

    for marker in CLOUDFLARE_MARKERS:
        if marker in text_lower:
            protection = "cloudflare"
            protection_note = "Cloudflare challenge (Just a moment / cf_chl)"
            break

    if not protection:
        for marker, label in WAF_ACCESS_DENIED_MARKERS:
            if marker in text_lower:
                protection = "403"
                protection_note = label
                break

    if not protection:
        for phrase in HUMAN_CHECK_PHRASES:
            if phrase in text_lower:
                protection = "captcha"
                protection_note = "страница проверки человека"
                break

    # Виджет recaptcha/hcaptcha - считаем защитой, только если реального
    # контента мы всё равно не нашли (parse_level D) и страница почти пустая.
    # Иначе это просто форма где-то на обычной работающей странице.
    if not protection and parse_level == "D" and vis_len < 3000:
        for marker in CAPTCHA_WIDGET_MARKERS:
            if marker in text_lower:
                protection = "captcha"
                protection_note = f"виджет {marker}, страница почти пустая"
                break

    if not protection and http_code == 403:
        protection = "403"
        protection_note = "HTTP 403 без явных маркеров cloudflare/captcha в теле"

    # cookie-wall - экран согласия ВМЕСТО контента. Проверяем по видимому
    # тексту (без скриптов/атрибутов), иначе почти любой сайт с баннером
    # cookiebot/onetrust в <script src> ложно попадёт сюда.
    if not protection and vis_len < 1200:
        vis_lower = vis.lower()
        for marker in COOKIE_MARKERS:
            if marker in vis_lower:
                protection = "cookie-wall"
                protection_note = "похоже на экран согласия на cookie вместо контента"
                break

    if protection:
        notes_bits.append(f"защита: {protection} ({protection_note})" if protection_note else f"защита: {protection}")

    return {
        "http_status": status_text,
        "parse_level": parse_level,
        "needs_js": needs_js,
        "protection": protection,
        "notes": "; ".join(notes_bits),
    }


def main():
    with open(SOURCES_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        fieldnames = reader.fieldnames
        rows = list(reader)

    results = {}
    for row in rows:
        domain = (row.get("domain") or "").strip()
        if not domain or domain in SKIP_DOMAINS:
            continue
        res = classify(domain)
        results[domain] = res
        row["http_status"] = res["http_status"]
        row["parse_level"] = res["parse_level"]
        row["needs_js"] = res["needs_js"]
        row["protection"] = res["protection"]
        row["notes"] = res["notes"]
        # url_pattern не трогаем

    with open(SOURCES_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    levels = Counter(r["parse_level"] for r in results.values())
    print("Итого по уровням:", dict(levels))
    prot = Counter(r["protection"] for r in results.values() if r["protection"])
    print("Защита:", dict(prot))

    out_path = ROOT / "recon" / "_analyze_debug.csv"
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["domain", "http_status", "parse_level", "needs_js", "protection", "notes"])
        for domain, r in results.items():
            w.writerow([domain, r["http_status"], r["parse_level"], r["needs_js"], r["protection"], r["notes"]])
    print(f"Отладочная копия результатов: {out_path}")


if __name__ == "__main__":
    main()

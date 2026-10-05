# -*- coding: utf-8 -*-
"""Кто заходит на сайт и сколько был (владелец 05.10.2026).

Владелец: «понимать, кто заходит: люди, поисковики — каждый отдельно, роботы
ИИ, сервисы, сканеры, свои, друзья; у людей — глубина и время; подробности
хранить 10 дней, суммы — бессрочно, к переезду на домен иметь статистику».

Как устроено:
- `classify()` — чистая функция: строки журнала + маячки → визиты. Посетитель —
  метка `vid` из куки, а без метки — пара «IP + подпись браузера». Пауза
  больше 30 минут — новый визит. Группа ставится на посетителя целиком.
- Робот «представился как…» — по подписи; подлинность по DNS не проверяем
  (сеть не трогаем), но явную подделку ловим: один адрес за час сменил три и
  больше разных «роботных» подписей → сканер (34.40.89.x 05.10 за 6 секунд
  назвался Google, Bing, ChatGPT, Claude, Perplexity… и полез в `/.env`).
- Человек — по маячку витрины (сканеры скрипт не выполняют). У старых строк
  (до 05.10) маячков нет: человеком «вероятно» считаем браузерную подпись,
  открывшую витрину и не искавшую ничего несуществующего; время у таких —
  «не видно».
- Суточные суммы — таблица `visit_days`: закрытый день считается и пишется
  один раз (метка в `visit_days_done`), сегодняшний считается на лету.
  Неделя/месяц/год — сложением дней; уникальные посетители — объединением
  обезличенных меток дня (хеш с солью из `settings`, не IP).
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
from functools import lru_cache

from . import db, visits

GAP = 30 * 60                   # пауза больше 30 минут — новый визит
FORGERY_WINDOW = 3600           # «сменил подписи роботов» — в пределах часа
FORGERY_NAMES = 3               # …три и больше разных имён

GROUPS = (
    ("human", "Люди"),
    ("friend", "Друзья"),
    ("own", "Свои"),
    ("search", "Поисковые роботы"),
    ("ai", "Роботы ИИ-сервисов"),
    ("service", "Сервисы (SEO, мониторинги, превью ссылок)"),
    ("scanner", "Сканеры и мусор"),
)
GROUP_NAMES = dict(GROUPS)
GROUP_SHORT = {k: v.split(" (")[0] for k, v in GROUPS}

SUB_BEACON = "видно по маячку"
SUB_PROBABLE = "вероятно человек"

# ── роботы по подписи ────────────────────────────────────────────────────────
# Порядок важен: ИИ раньше поисковиков (у OAI-SearchBot в подписи Chrome, у
# Applebot-Extended — Applebot), поисковики раньше сервисов.
_ROBOTS = [(re.compile(rx, re.I), grp, name) for rx, grp, name in (
    (r"GPTBot", "ai", "GPTBot (OpenAI)"),
    (r"ChatGPT-User", "ai", "ChatGPT-User (OpenAI)"),
    (r"OAI-SearchBot", "ai", "OAI-SearchBot (OpenAI)"),
    (r"Claude-SearchBot", "ai", "Claude-SearchBot (Anthropic)"),
    (r"Claude-User", "ai", "Claude-User (Anthropic)"),
    (r"ClaudeBot|anthropic-ai|Claude-Web", "ai", "ClaudeBot (Anthropic)"),
    (r"Perplexity-User", "ai", "Perplexity-User"),
    (r"PerplexityBot", "ai", "PerplexityBot"),
    (r"Google-Extended", "ai", "Google-Extended"),
    (r"GoogleOther|Google-CloudVertexBot", "ai", "GoogleOther"),
    (r"CCBot", "ai", "CCBot (Common Crawl)"),
    (r"Bytespider", "ai", "Bytespider (ByteDance)"),
    (r"Amazonbot", "ai", "Amazonbot"),
    (r"Applebot-Extended", "ai", "Applebot-Extended"),
    (r"Meta-External(?:Agent|Fetcher)|FacebookBot", "ai", "Meta AI"),
    (r"MistralAI-User", "ai", "MistralAI-User"),
    (r"DeepSeekBot", "ai", "DeepSeekBot"),
    (r"cohere-ai|cohere-training", "ai", "Cohere"),
    (r"xAI-Grok|GrokBot", "ai", "Grok (xAI)"),
    (r"YouBot", "ai", "YouBot (You.com)"),
    (r"Qwenbot", "ai", "Qwenbot (Alibaba)"),
    (r"KimiBot|Kimi-SearchBot|MoonshotBot", "ai", "Kimi (Moonshot)"),
    (r"PanguBot", "ai", "PanguBot (Huawei)"),
    (r"ChatGLM-Spider", "ai", "ChatGLM (Zhipu)"),
    (r"YiBot", "ai", "YiBot (01.ai)"),
    (r"Hunyuan", "ai", "Hunyuan (Tencent)"),
    (r"DuckAssistBot", "ai", "DuckAssistBot"),
    (r"Diffbot", "ai", "Diffbot"),
    (r"Timpibot", "ai", "Timpibot"),
    (r"ImagesiftBot", "ai", "ImagesiftBot"),
    (r"AI2Bot", "ai", "AI2Bot"),
    (r"Googlebot|Google-InspectionTool|Storebot-Google|AdsBot-Google|"
     r"Mediapartners-Google|APIs-Google|FeedFetcher-Google", "search", "Google"),
    (r"bingbot|BingPreview|msnbot|adidxbot", "search", "Bing"),
    (r"Yandex(?:\w*Bot|Images|Metrika)", "search", "Яндекс"),
    (r"DuckDuckBot", "search", "DuckDuckGo"),
    (r"Applebot", "search", "Apple"),
    (r"Baiduspider", "search", "Baidu"),
    (r"Bravebot", "search", "Brave"),
    (r"PetalBot", "search", "Petal (Huawei)"),
    (r"SeznamBot", "search", "Seznam"),
    (r"Yeti/", "search", "Naver"),
    (r"Sogou", "search", "Sogou"),
    (r"Slurp", "search", "Yahoo"),
    (r"MojeekBot", "search", "Mojeek"),
    (r"Qwantbot|Qwantify", "search", "Qwant"),
    (r"coccocbot", "search", "Coc Coc"),
    (r"360Spider", "search", "360"),
    (r"YisouSpider", "search", "Yisou"),
    (r"DotBot", "service", "DotBot (Moz)"),
    (r"AhrefsBot|AhrefsSiteAudit", "service", "Ahrefs"),
    (r"SemrushBot|SiteAuditBot", "service", "Semrush"),
    (r"MJ12bot", "service", "Majestic (MJ12bot)"),
    (r"UptimeRobot", "service", "UptimeRobot"),
    (r"Censys", "service", "Censys"),
    (r"internet-?measurement", "service", "internet-measurement"),
    (r"BLEXBot", "service", "BLEXBot"),
    (r"DataForSeoBot", "service", "DataForSEO"),
    (r"serpstatbot", "service", "Serpstat"),
    (r"Barkrowler", "service", "Barkrowler"),
    (r"SeekportBot", "service", "Seekport"),
    (r"Screaming Frog", "service", "Screaming Frog"),
    (r"Expanse", "service", "Expanse (Palo Alto)"),
    (r"ModatScanner", "service", "Modat"),
    (r"Pingdom", "service", "Pingdom"),
    (r"StatusCake", "service", "StatusCake"),
    (r"Better ?Uptime", "service", "Better Uptime"),
    (r"facebookexternalhit|facebookcatalog", "service", "превью ссылок: Facebook"),
    (r"Twitterbot", "service", "превью ссылок: X (Twitter)"),
    (r"TelegramBot", "service", "превью ссылок: Telegram"),
    (r"WhatsApp", "service", "превью ссылок: WhatsApp"),
    (r"Slackbot", "service", "превью ссылок: Slack"),
    (r"Discordbot", "service", "превью ссылок: Discord"),
    (r"LinkedInBot", "service", "превью ссылок: LinkedIn"),
    (r"Viber", "service", "превью ссылок: Viber"),
)]
#: прочие самоназванные роботы — в «сервисы» под своим именем
_GENERIC_BOT_RE = re.compile(r"bot\b|bot/|crawler|spider|slurp", re.I)
#: программы, а не браузеры: curl, python, сканеры уязвимостей
_TOOL_RE = re.compile(
    r"curl|wget|python|go-http|zgrab|masscan|nmap|nikto|sqlmap|httpx|java/|"
    r"okhttp|libwww|axios|node-fetch|undici|aiohttp|httpclient|powershell|"
    r"l9explore|l9scan|l9tcpid|leakix|libredtail|nuclei|wpscan|gobuster|"
    r"dirbuster|fasthttp|headless|phantomjs|scrapy|hello world|werkzeug|"
    r"mechanize|guzzle|reqwest|winhttp|^php|ruby|perl/|postman|insomnia|"
    r"odin|genomecrawler|keydrop|fuzz|cortex|xpanse", re.I)
#: настоящий браузер: «Mozilla/5.0 (система…)» и имя браузера с версией
_BROWSER_RE = re.compile(
    r"^Mozilla/5\.0 \(.*\b(?:Chrome|CriOS|Firefox|FxiOS|Safari|Edg|EdgA|"
    r"EdgiOS|OPR|YaBrowser|SamsungBrowser)/\d")
#: адреса, которые ищут только сканеры уязвимостей
_JUNK_PATH_RE = re.compile(
    r"\.(?:env|git|svn|hg|aws|ssh|htaccess|htpasswd|DS_Store|bash_history|"
    r"bashrc|npmrc|docker)|\.(?:php\d?|asp|aspx|jsp|cgi|sql|bak|old|swp|pem|"
    r"key|ini|cfg|conf)\b|wp-|wordpress|xmlrpc|cgi-bin|\.\./|\.\.%2f|%2e%2e|"
    r"/etc/passwd|/proc/self|credentials|phpmyadmin|/actuator|/vendor/|"
    r"/boaform|/owa/|/geoserver|/solr/|/druid/|/manager/html|/HNAP1|id_rsa|"
    r"/@fs/|/server-status|/telescope|/_profiler|/_debugbar|service-account|"
    r"gcp-key|/\.vscode|/\.idea|/config\.(?:json|js|py|ya?ml)", re.I)
#: несуществующие адреса, которые спрашивают и честные роботы и браузеры
_BENIGN_MISSING_RE = re.compile(
    r"^/(?:robots\.txt|favicon\.ico|sitemap[\w.-]*\.xml|apple-touch-icon"
    r"[\w.-]*\.png|ads\.txt|app-ads\.txt|humans\.txt|security\.txt|"
    r"\.well-known/security\.txt|manifest\.json|site\.webmanifest|"
    r"browserconfig\.xml)$", re.I)

_EPOCH = datetime(2000, 1, 1)


@lru_cache(maxsize=8192)
def robot(agent: str) -> tuple[str, str] | None:
    """(группа, имя) робота, которым подпись представилась; иначе None."""
    for rx, grp, name in _ROBOTS:
        if rx.search(agent):
            return grp, name
    return None


@lru_cache(maxsize=8192)
def agent_kind(agent: str) -> tuple[str, str]:
    """Что за подпись, если не известный робот: ('empty'|'tool'|'bot'|
    'browser'|'odd', имя)."""
    if not agent.strip():
        return "empty", ""
    if _TOOL_RE.search(agent):
        return "tool", ""
    if _GENERIC_BOT_RE.search(agent):
        found = visits._BOT_NAME_RE.search(agent)
        return "bot", (found.group(1) if found else agent[:30])
    if _BROWSER_RE.search(agent) and "MSIE" not in agent:
        return "browser", ""
    return "odd", ""


def path_kind(row: dict) -> str:
    """'junk' — искал уязвимость; 'missing' — несуществующий адрес не из
    безобидных; '' — обычный запрос."""
    if row["method"] == "SKIP":
        return ""
    return _path_kind(row["path"], bool(row["endpoint"]))


@lru_cache(maxsize=16384)
def _path_kind(path: str, known: bool) -> str:
    if _JUNK_PATH_RE.search(path):
        return "junk"
    if not known and not _BENIGN_MISSING_RE.match(path):
        return "missing"
    return ""


def self_ips() -> set[str]:
    """Сам сервер: 127.0.0.1 и адреса из `STREAMS_SELF_IPS` (через запятую —
    внешний адрес сервера; в код не зашиваем, репозиторий публичный)."""
    extra = os.environ.get("STREAMS_SELF_IPS", "")
    return {"127.0.0.1", "::1"} | {x.strip() for x in extra.split(",")
                                   if x.strip()}


def _secs(when: str) -> float:
    return (datetime.fromisoformat(when) - _EPOCH).total_seconds()


def _forged_ips(rows: list[dict]) -> set[str]:
    """Адреса, сменившие за час три и больше разных «роботных» подписей."""
    seen: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for r in rows:
        found = robot(r["agent"])
        if found:
            seen[r["ip"]].append((r["_t"], found[1]))
    forged = set()
    for ip, marks in seen.items():
        if len({n for _, n in marks}) < FORGERY_NAMES:
            continue
        marks.sort()
        win: deque = deque()
        names: Counter = Counter()
        for t, n in marks:
            win.append((t, n))
            names[n] += 1
            while t - win[0][0] > FORGERY_WINDOW:
                old = win.popleft()[1]
                names[old] -= 1
                if not names[old]:
                    del names[old]
            if len(names) >= FORGERY_NAMES:
                forged.add(ip)
                break
    return forged


def _group(rs: list[dict], has_beacons: bool, admin_ips: set[str],
           forged: set[str], own_ips: set[str]) -> tuple[str, str]:
    """Группа и подгруппа посетителя по всем его строкам."""
    ips = {r["ip"] for r in rs}
    if any(r["who"] == "admin" for r in rs):
        return "own", "вход в админку"
    if any(r["who"] == "friend" for r in rs):
        return "friend", ""
    if ips & own_ips:
        return "own", "сервер"
    if ips & admin_ips:
        # с этого адреса работали под паролем админки — это владелец
        return "own", "вход в админку"
    if all(r["endpoint"] == "crawl_hook_in" for r in rs):
        return "own", "GitHub (стук обхода)"
    if ips & forged:
        return "scanner", "подделка под роботов"
    kinds = {path_kind(r) for r in rs}
    if "junk" in kinds:
        return "scanner", "ищет уязвимости (/.env, wp-login…)"
    agent = Counter(r["agent"] for r in rs).most_common(1)[0][0]
    found = robot(agent)
    if found:
        return found
    kind, name = agent_kind(agent)
    if kind == "empty":
        return "scanner", "без подписи"
    if kind == "tool":
        return "scanner", "программы (curl, python…)"
    if kind == "bot":
        return "service", f"прочие: {name}"
    if kind == "odd":
        return "scanner", "странная подпись"
    if has_beacons:
        return "human", SUB_BEACON
    opened = any(r["endpoint"] in visits.PUBLIC_PAGES and r["status"] == "200"
                 for r in rs)
    if opened and "missing" not in kinds:
        return "human", SUB_PROBABLE
    return "scanner", "браузерная подпись, витрину не открывал"


def classify(rows: list[dict], beacons: list[dict],
             own_ips: set[str] | frozenset = frozenset()) -> list[dict]:
    """Строки журнала + маячки → визиты (по времени начала). Чистая функция:
    ни файлов, ни базы, ни часов (только служебное поле `_t` у строк).
    Строки — словари из `visits.parse_line`."""
    rows = sorted((r for r in rows if len(r.get("when", "")) == 19),
                  key=lambda r: r["when"])
    for r in rows:
        r["_t"] = _secs(r["when"])
    # метка «настоящая», если браузер её вернул (кука сохранилась) или прислал
    # с ней маячок. Метку, выданную роботу и не вернувшуюся, не считаем — иначе
    # каждый запрос робота стал бы отдельным посетителем
    known = {b["vid"] for b in beacons}
    known |= {r["vid"] for r in rows if r["vid"] and r["vid"][0] != "+"}

    def key(r: dict) -> str:
        vid = r["vid"].lstrip("+")
        return f"v:{vid}" if vid and vid in known else f"a:{r['ip']}\t{r['agent']}"

    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_key[key(r)].append(r)
    beacons_by_key: dict[str, list[dict]] = defaultdict(list)
    for b in beacons:
        k = f"v:{b['vid']}"
        if k in by_key:             # маячок без единой строки — не к чему
            b = dict(b, _t=_secs(b["when"]))
            beacons_by_key[k].append(b)
    admin_ips = {r["ip"] for r in rows if r["who"] == "admin"}
    forged = _forged_ips(rows)
    own_ips = set(own_ips)

    out: list[dict] = []
    for k, rs in by_key.items():
        bs = beacons_by_key.get(k, [])
        grp, sub = _group(rs, bool(bs), admin_ips, forged, own_ips)
        events = [(r["_t"], 0, r) for r in rs] + [(b["_t"], 1, b) for b in bs]
        events.sort(key=lambda e: (e[0], e[1]))
        first = rs[0]
        cur: dict | None = None
        last_t = None
        for t, is_beacon, item in events:
            if cur is None or t - last_t > GAP:
                cur = {"key": k, "ip": first["ip"], "agent": first["agent"],
                       "vid": k[2:] if k.startswith("v:") else "",
                       "group": grp, "sub": sub, "start": item["when"],
                       "end": item["when"], "rows": [], "beacons": []}
                out.append(cur)
            last_t = t
            cur["end"] = item["when"]
            (cur["beacons"] if is_beacon else cur["rows"]).append(item)
    for v in out:
        _measure(v)
    out.sort(key=lambda v: v["start"])
    return out


def _measure(v: dict) -> None:
    """Глубина, действия, длительность, источник, язык визита."""
    rs, bs = v["rows"], v["beacons"]
    if rs:
        v["ip"], v["agent"] = rs[0]["ip"], rs[0]["agent"]
    v["day"] = v["start"][:10]
    v["pages"] = sum(1 for r in rs if r["method"] == "GET"
                     and r["status"] == "200" and r["endpoint"]
                     and r["endpoint"] != "static")
    v["actions"] = (sum(1 for r in rs if r["method"] == "POST")
                    + sum(b["acts"] for b in bs))
    v["hits"] = sum(visits.skipped(r) for r in rs)
    # длительность — только по маячкам: без них время «не видно», а не ноль
    v["seconds"] = sum(b["secs"] for b in bs) if bs else None
    v["source"] = next((r["src"] or r["ref"] for r in rs
                        if r["src"] or r["ref"]), "")
    v["lang"] = next((r["lang"] for r in rs if r["lang"]), "")
    v["device"] = visits.device(v["agent"])


# ── суммы ────────────────────────────────────────────────────────────────────

def _hash(salt: str, key: str) -> str:
    """Обезличенная метка посетителя для подсчёта уникальных за период."""
    return hashlib.blake2b((salt + key).encode("utf-8"),
                           digest_size=5).hexdigest()


def _blank() -> dict:
    return {"visits": 0, "ids": set(), "hits": 0, "pages": 0, "actions": 0,
            "seconds": 0, "timed": 0}


def aggregate(visits_: list[dict], salt: str) -> dict[tuple, dict]:
    """Визиты → суммы: (день, группа, подгруппа) → визитов, метки
    посетителей, запросов, страниц, действий, секунд, визитов с временем."""
    out: dict[tuple, dict] = {}
    hashed: dict[str, str] = {}
    for v in visits_:
        a = out.setdefault((v["day"], v["group"], v["sub"]), _blank())
        a["visits"] += 1
        h = hashed.get(v["key"])
        if h is None:
            h = hashed[v["key"]] = _hash(salt, v["key"])
        a["ids"].add(h)
        a["hits"] += v["hits"]
        a["pages"] += v["pages"]
        a["actions"] += v["actions"]
        if v["seconds"] is not None:
            a["seconds"] += v["seconds"]
            a["timed"] += 1
    return out


def salt(conn) -> str:
    value = db.get_setting(conn, "visits_salt")
    if not value:
        value = secrets.token_hex(16)
        db.set_setting(conn, "visits_salt", value)
    return value


def done_days(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT day FROM visit_days_done")}


def closable_before(now: datetime | None = None) -> str:
    """Дни раньше этого — закрыты. Первый час суток вчерашний день ещё не
    закрываем: визит, начатый до полуночи, может длиться."""
    now = now or datetime.now(visits.KYIV)
    return f"{now - timedelta(hours=1):%Y-%m-%d}"


def ensure_days(conn, aggr: dict[tuple, dict], before: str) -> set[str]:
    """Записать в суммы закрытые дни, которых там ещё нет. Записанный день
    больше не пересчитывается. Возвращает все записанные дни."""
    have = done_days(conn)
    days = sorted({k[0] for k in aggr} - have)
    for day in days:
        if day >= before:
            continue
        with conn:                      # день целиком или ничего
            got = conn.execute(
                "INSERT OR IGNORE INTO visit_days_done (day) VALUES (?)",
                (day,)).rowcount
            if not got:                 # соседний процесс успел раньше
                continue
            for (d, grp, sub), a in aggr.items():
                if d != day:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO visit_days (day, grp, sub, visits,"
                    " visitors, hits, pages, actions, seconds, timed, ids)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (d, grp, sub, a["visits"], len(a["ids"]), a["hits"],
                     a["pages"], a["actions"], a["seconds"], a["timed"],
                     " ".join(sorted(a["ids"]))))
        have.add(day)
    return have


def stored(conn, since: str) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for r in conn.execute("SELECT * FROM visit_days WHERE day >= ?", (since,)):
        out[(r["day"], r["grp"], r["sub"])] = {
            "visits": r["visits"], "ids": set((r["ids"] or "").split()),
            "hits": r["hits"], "pages": r["pages"], "actions": r["actions"],
            "seconds": r["seconds"], "timed": r["timed"]}
    return out


TOTAL = "*"                     # подгруппа-«итого» группы в `periods()`
PERIODS = (("day", "Сегодня", 1), ("week", "7 дней", 7),
           ("month", "30 дней", 30), ("year", "Год", 365))


def _add(dst: dict, src: dict) -> None:
    for f in ("visits", "hits", "pages", "actions", "seconds", "timed"):
        dst[f] += src[f]
    dst["ids"] |= src["ids"]


def _finish(a: dict) -> dict:
    """Сумма → то, что видит владелец: посетителей, визитов, глубина, время."""
    n = a["visits"]
    return {"visits": n, "visitors": len(a["ids"]), "hits": a["hits"],
            "pages": a["pages"], "actions": a["actions"],
            "depth": (a["pages"] / n) if n else None,
            "avg_time": (a["seconds"] / a["timed"]) if a["timed"] else None,
            "timed": a["timed"]}


def periods(daily: dict[tuple, dict], today: str) -> dict:
    """Суммы по периодам «сегодня / 7 / 30 / 365 дней»: по группам целиком и
    по подгруппам. Ключ — (группа, подгруппа; TOTAL — вся группа) → период →
    цифры."""
    base = datetime.strptime(today, "%Y-%m-%d")
    starts = {p: f"{base - timedelta(days=n - 1):%Y-%m-%d}"
              for p, _, n in PERIODS}
    acc: dict[tuple, dict[str, dict]] = defaultdict(
        lambda: {p: _blank() for p, _, _ in PERIODS})
    for (day, grp, sub), a in daily.items():
        if day > today:
            continue
        for p, start in starts.items():
            if day >= start:
                _add(acc[(grp, sub)][p], a)
                _add(acc[(grp, TOTAL)][p], a)
    return {k: {p: _finish(a) for p, a in v.items()} for k, v in acc.items()}


def by_month(daily: dict[tuple, dict], grp: str = "human") -> list[dict]:
    """Люди по месяцам — для истории к переезду на домен."""
    acc: dict[str, dict] = defaultdict(_blank)
    for (day, g, _), a in daily.items():
        if g == grp:
            _add(acc[day[:7]], a)
    return [dict(_finish(a), month=m) for m, a in sorted(acc.items(),
                                                         reverse=True)]


def refresh(conn=None, now: datetime | None = None) -> dict:
    """Прочитать журнал, разложить визиты, дописать закрытые дни в суммы и —
    раз в сутки — убрать старые строки. Сбой базы не мешает показу: тогда
    суммы считаются на лету, а уборка ждёт (без записи дня строки не уходят)."""
    now = now or datetime.now(visits.KYIV)
    today = f"{now:%Y-%m-%d}"
    rows = visits.read(days=None, newest_first=False)
    beacons = visits.read_beacons()
    found = classify(rows, beacons, self_ips())
    own = conn is None
    conn = conn or db.connect()
    try:
        the_salt = salt(conn)
        aggr = aggregate(found, the_salt)
        try:
            done = ensure_days(conn, aggr, closable_before(now))
        except Exception as e:                               # noqa: BLE001
            print(f"посещения: суммы дня не записаны ({type(e).__name__}: {e})")
            done = done_days(conn)
        if visits.claim_daily(today):
            visits.purge(done, today)
        since = f"{now - timedelta(days=400):%Y-%m-%d}"
        daily = stored(conn, since)
    finally:
        if own:
            conn.close()
    # чего нет в базе (сегодня; или запись дня не удалась) — на лету
    for k, a in aggr.items():
        if k[0] not in done:
            daily[k] = a
    return {"rows": rows, "beacons": beacons, "visits": found,
            "daily": daily, "today": today, "done": done}


def duration(sec: float | None) -> str:
    """Секунды → «2 мин 05 с»; None — «не видно»."""
    if sec is None:
        return "не видно"
    sec = int(round(sec))
    if sec < 60:
        return f"{sec} с"
    if sec < 3600:
        return f"{sec // 60} мин {sec % 60:02d} с"
    return f"{sec // 3600} ч {sec % 3600 // 60:02d} мин"

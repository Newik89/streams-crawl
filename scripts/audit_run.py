# -*- coding: utf-8 -*-
r"""Самопроверка прогона: ищет ИЗВЕСТНЫЕ классы наших ошибок и печатает
список «подозрительно» по сайтам — чтобы их находил скрипт, а не владелец
глазами на витрине (просьба владельца 06.10: «чтобы не ходить кругами»).

Только чтение: к сайтам не ходит, базу не открывает. Работает по папке
артефакта прогона (`scripts/github_run.py fetch --run N`): страницы,
`report.json` и `games.json` — его пишет `parse_live.py` (без него
проверки 3, 4, 6, 7, 8 молчат).

Запуск:
    python scripts/audit_run.py --dir <папка прогона>
    python scripts/audit_run.py --dir <папка> --prev <папка прошлого прогона> --md audit.md

Что ищет (номер — класс ошибки; в скобках — где на него уже наступали):
  1. ПРИЗНАК НЕ ЧИТАЕТСЯ. В сырых страницах сайта есть поле/класс/значок
     эфира или повтора (`is_live_mp`, `"live": true`, `emissionType`,
     `class="repeat"`, `data-live="1"`), а разбор его не читает: честного
     эфира 0 или сайт угадывается (`REPEAT_GUESS_DOMAINS`, `live_guess`).
     (port.hu 06.10: DVSC пропал; tv2.no, sport1.de, programetv.ro — 06.10)
  2. СЛОВО НЕ В СЛОВАРЕ. Слово эфира на странице или в `live_raw` разбора,
     которого нет в `data/markers.json` (err.ee `otseülekanne`, 03.10).
  3. ПУСТО. «Расписание есть», а игр 0 — или резко меньше, чем в прошлом
     прогоне (cosmotetv.gr: 11 дней «есть» и 0 игр, 22.09–03.10).
  4. ЭТАЛОН ДВОИТСЯ. Один fs_id эталона flashscore с двумя временами.
  5. СДВИГ ДНЯ. Передачи страницы дня легли не на её день, или время в
     сетке канала пошло назад (страница начинается с вечера: sport1tv,
     digisport «Marți 06» 06.10). Страница «сегодня» без даты, отдавшая
     вчера (ночью — tv.orf.at, programetv.ro), подозрительна, только если
     сам день у этого канала не скачан другой страницей.
  6. ПОТЕРЯ. Строка с парой и нашим видом спорта, которую сайт пометил
     эфиром сам, прошла отсев — и не оказалась ни в играх, ни «на разбор»,
     ни в журнале «снято». Снятая фильтром «повтор по flashscore» — в
     подозрения, только если время эталона похоже на заглушку тура
     (`ROUND_SAME_TIME`): тогда сайт, скорее всего, прав (WWIN liga BiH).
  7. КЛИЧКА. Команда сайта не сводится с эталоном в ±30 мин, хотя вторая
     команда совпала твёрдо (DVSC ↔ Debrecen, PSG ↔ Paris SG).
  8. ПОЯС. Время сайта отличается от эталона на целые часы (tvpassport).
  9. УГАДЫВАЕТ БЕЗ СВЕРКИ. Разбор угадывает эфир (`repeat_guess`), а сверка
     с эталоном у строк выключена: домена нет в `REPEAT_GUESS_DOMAINS` и
     нет `live_guess` (tvheute.at до 06.10).
 10. ОДНА СТРАНИЦА. Разные адреса сайта (дни или каналы) дали файл слово в
     слово: параметр дня сайт не слышит (kolla.tv `?dat=` — шесть дат, один
     файл, 06.10) или адрес канала отдаёт чужую страницу (diemaxtra
     `/schedule` = Diema Sport; movistarplus `multi6` — страница La 1).

Правила:
  * подозрение — строка «сайт: что не так — пример»; решение принимает
    человек, скрипт ничего не правит;
  * пороги — именованные константы ниже, менять только там;
  * проверенный ложный признак (не эфир, а «идёт сейчас», пометка у всех
    строк, закомментированный блок) — в `KNOWN_NOT_FLAGS` с датой и
    причиной: он печатается одной строкой «проверено» и не всплывает
    подозрением каждый раз.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import html as _html
import json
import re
import sys
import types
from datetime import date as _date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app import leagues, live, names, pipeline, sport   # noqa: E402
from app.canon import _pair_score, _script                # noqa: E402
from app.canon import _sides as _local_sides              # noqa: E402
from app.parsers import SITE_FLAG, SITE_LIVE, SITE_REPEAT, Program  # noqa: E402
from app.parsers import get as parser_for                 # noqa: E402
from app.parsers.flashscore_mobi import LOCALES as FS_LOCALES  # noqa: E402
import parse_live                                         # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
PLAN = ROOT / "data" / "crawl_plan.json"

# ---- пороги ---------------------------------------------------------------
#: меньше стольких пометок эфира на сайт — признаком не считаем
MIN_FLAGS = 3
#: в среднем не больше стольких пометок «эфир» на страницу — похоже на «идёт
#: сейчас» (одна передача на канал), а не на признак прямой трансляции
NOW_PLAYING_PER_PAGE = 1.5
#: слово эфира, встреченное у сайта реже, не показываем
MIN_WORD_HITS = 3
#: `live_raw` длиннее стольких слов — заметка сайта, а не маркер разбора
MARKER_WORDS = 3
#: игр меньше этой доли от прошлого прогона (в пересчёте на сутки) — «резко»
DROP_SHARE = 0.3
#: прошлый прогон должен был дать хотя бы столько игр в сутки, чтобы сравнивать
MIN_PREV_PER_DAY = 1.0
#: страница, чьи передачи укладываются в столько часов, — страница одного дня
DAY_PAGE_SPAN_H = 36
#: время в сетке канала откатилось больше чем на столько часов — сбой
TIME_BACK_H = 2
#: страницу дня с меньшим числом передач не судим (ночной канал из 7 строк
#: законно живёт больше «после полуночи»)
DAY_SHIFT_MIN_ROWS = 20
#: страница без даты в адресе подозрительна, если такая доля передач —
#: вчерашние
DAY_SHIFT_SHARE = 0.75
#: одна сторона пары совпала не хуже — «твёрдо» (кличка, проверка 7)
ALIAS_SURE = 95
#: допуск по времени для клички: сетка ставит блок чуть раньше матча
ALIAS_WINDOW = timedelta(minutes=30)
#: окно поиска сдвига на целые часы (проверка 8) и допуск «целого часа»
TZ_WINDOW = timedelta(hours=13)
TZ_TOLERANCE = timedelta(minutes=5)
#: строк с одним и тем же сдвигом у сайта — не меньше стольких
TZ_MIN_ROWS = 2
#: и не меньше такой доли от всех строк сайта, сошедшихся с эталоном: сбой
#: пояса сдвигает ВСЁ (tvpassport), а пара повторов через 8 часов — нет
TZ_SHARE = 0.5
#: страниц одного сайта с одинаковым содержимым — с этого числа подозрение
#: «сайт отдаёт одно и то же» (kolla.tv: шесть дат окна — один файл, 06.10)
SAME_PAGE_MIN = 2
#: время эталона — «заглушка тура», если у лиги в этот день столько матчей
#: ровно в одну минуту: WWIN liga BiH 10.10 — все пять в 18:00, а Arena
#: (tvarenasport.ba) ставит их на пт 18:00, сб 18:30, вс 16:00 и 18:30.
#: По такому времени «матч уже сыгран» доказать нельзя (проверка 6)
ROUND_SAME_TIME = 5
#: примеров на одно подозрение
EXAMPLES = 4
#: клубная обвязка имени — для первой буквы в проверке 7
CLUB_FORMS = {"FC", "FK", "SK", "AS", "AC", "CF", "CD", "SC", "SV", "VFL",
              "VFB", "TSG", "NK", "HNK", "KS", "GKS", "1", "AFC", "SSC",
              "RC", "RCD", "UD", "CA", "SL", "FCSB", "AEK", "PAE"}

#: справочники: их строки на витрину не идут, проверки 3 и 6 их не касаются
REFERENCE_DOMAINS = {"flashscore.mobi", "sporteventz.com", "livesoccertv.com",
                     "liveonsat.com", *FS_LOCALES}

#: Проверенные «ложные признаки» — (домен, подпись признака): почему это не
#: пометка эфира. Подпись — как её печатает проверка 1.
KNOWN_NOT_FLAGS = {
    ("kanal1sport.sk", "class:live"):
        "«Vysielame» у всех строк подряд (kanal1sport_sk.py, 01.09)",
    ("skai.gr", "class:live-img"):
        "LIVE — эфир канала в этот час, не матч (skai_gr.py)",
    ("skai.gr", "class:live"):
        "пункт меню «Live» сайта (06.10)",
    ("mediaklikk.hu", "class:live"):
        "плеер прямого эфира канала, не передача (06.10)",
    ("mediaklikk.hu", "attr:data-live=true"):
        "кнопки радио-плеера; «Élő» видна только у идущей сейчас (06.10)",
    ("mediaklikk.hu", "class:elo"):
        "«Élő» спрятана (`display:none`) у всех, кроме идущей сейчас (06.10)",
    ("ipko.tv", "json:is_live=true"):
        "«идёт сейчас»; в #205 false у всех 614 (06.10)",
    ("kolla.tv", "json:live=true"):
        "флаги live/repeat пустые у всех строк (kolla_tv.py)",
    ("dagenstv.com", "json:live=true"):
        "флаги live/repeat пустые у всех строк (kolla_tv.py)",
    ("flashscore.mobi", "class:live"):
        "справочник: «идёт сейчас» у счёта матча",
    ("unian.tv", "class:tv-item__now"):
        "«Зараз в ефірі» — идёт сейчас (unian_tv.py)",
}

#: Проверенные клички (проверка 7), которые в словарь НЕ кладём — написание
#: двусмысленно: (имя сайта, имя эталона) → почему. Печатаются в справке.
KNOWN_NOT_ALIASES = {
    ("BSK 1926", "Bacevac"):
        "BSK — ещё Borča и Banja Luka, а год чистка снимает (06.10)",
    ("DINAMO B", "Dinamo Bucuresti"):
        "«B» — метка второго состава (Dinamo Zagreb B), не Бухарест (06.10)",
    ("Trabzon", "Trabzonspor"):
        "есть и «1461 Trabzon» — одно слово сводило бы оба клуба (06.10)",
}

#: Слова эфира на языках наших сайтов — кандидаты для проверки 2. Есть в
#: `markers.json` → молчим; нет → подозрение. Двусмысленные слова
#: (`AMBIGUOUS`) сознательно не в словаре — их не показываем.
LIVE_WORD_CANDIDATES = [
    "live", "élő", "élőben", "élő közvetítés", "egyenes adás", "direto",
    "em direto", "ao vivo", "na żywo", "transmisja na żywo", "uživo", "u živo",
    "uzivo", "živo", "v živo", "živě", "naživo", "přímý přenos",
    "priamy prenos", "priamo", "canlı", "canli", "canlı yayın", "ζωντανά",
    "ζωντανή", "ζωντανη μεταδοση", "en directo", "en vivo", "directo",
    "en direct", "în direct", "transmisiune directă", "в прямом эфире",
    "прямой эфир", "прямая трансляция", "наживо", "прямий ефір",
    "пряма трансляція", "tiesiogiai", "tiesioginė", "tiesioginė transliacija",
    "otse", "otseülekanne", "otsesaade", "suora", "suorana", "suora lähetys",
    "direkte", "direkt", "direktsänt", "direktsändning", "diretta",
    "in diretta", "live-übertragung", "liveübertragung", "rechtstreeks",
    "prenos", "prijenos", "izravno", "izravni prijenos", "ישיר", "שידור חי",
    "пряко", "директно", "директан пренос", "drejtpërdrejt", "тікелей эфир",
    "тікелей", "уживо", "пренос уживо",
]
#: слова, которые сознательно НЕ кладём в словарь (`ГРАБЛИ.md`, 03.10)
AMBIGUOUS = {"direct", "repriza", "tekrar", "επανάληψη"}

#: кавычки JSON бывают экранированы (`\"isLive\":true` внутри строки)
_Q = r'\\?"'
#: «да» в JSON: true, 1, "1", "Y", "yes", "true" (кавычки тоже бывают экранированы)
JSON_BOOL = re.compile(_Q + r"(\w{2,40})" + _Q + r"\s*:\s*(true|1|"
                       + _Q + r"(?:1|Y|yes|true)" + _Q + r")(?=[\s,}\]\\])")
JSON_STR = re.compile(_Q + r"(\w{2,40})" + _Q + r"\s*:\s*" + _Q + r"([^\"\\]{1,30})" + _Q)
LIVE_KEY = re.compile(r"^(?:is_?)?live(?:_?(?:mp|broadcast|event|flag|now))?$"
                      r"|^livebroadcast$|^islive\w*$", re.I)
REPEAT_KEY = re.compile(r"^(?:is_?)?(?:repeat|replay|rerun|reprise|reply|"
                        r"rebroadcast)$|^automaticreplay$", re.I)
TYPE_KEY = re.compile(r"^(?:emission_?type|tipoemissao|broadcast_?type|"
                      r"type|kind|status|label|badge|tag|flag)$", re.I)
CLASS_ATTR = re.compile(r"class\s*=\s*\\?[\"']([^\"'\\]{1,300})")
LIVE_CLASSES = {"live", "is-live", "live-now", "onair", "on-air", "attr-live",
                "epgart_live", "elo", "uzivo", "direct", "direto", "canli",
                "zivo", "live-img", "live-tag", "live-badge", "live-label",
                "tv-item__now"}
REPEAT_CLASSES = {"repeat", "rerun", "replay", "reprise", "wdh", "epgart_wdh",
                  "repriza", "is-repeat", "rebroadcast"}
DATA_FLAG = re.compile(r"data-(live|repeat|rerun|replay)\s*=\s*\\?\"(1|true|yes)\\?\"",
                       re.I)
#: подпись значка: `title="Živě"`, `alt="ישיר"`. Берём, только если подпись
#: — ровно слово словаря: «Mezzo Live», «TV uživo», «Jetzt live auf RTL+» —
#: это имена каналов и ссылки, не пометки передач
WORD_ATTR = re.compile(r"(?:title|alt|aria-label)\s*=\s*\\?\"([^\"\\]{1,40})\\?\"")
#: значки в видимом тексте: `(Ζ)`/`(Z)` — «ζωντανά» (cosmote, cyta), `(R)` —
#: повтор (BBC, HRT). Ищем только вне скриптов: в JS `J(L)`, `fj(Z)` повсюду
LIVE_TAGS = ("(Ζ)", "(Z)")
REPEAT_TAGS = ("(R)", "(Wh.)", "(Wdh.)", "(повтор)")
_EDGE = " .:!-()[]"

COMMENT = re.compile(r"<!--.*?-->", re.S)
SCRIPT_STYLE = re.compile(r"<script\b.*?</script>|<style\b.*?</style>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")


def visible(text: str) -> str:
    """Текст, который видит человек: без скриптов, стилей, комментариев и
    тегов. JSON отдаём как есть — там всё «видимо»."""
    head = text.lstrip()[:1]
    if head in "[{":
        return text
    return _html.unescape(TAG.sub(" ", SCRIPT_STYLE.sub(" ", COMMENT.sub(" ", text))))


def raw_flags(text: str, markers) -> collections.Counter:
    """Пометки эфира и повтора в сырой странице: Counter((вид, подпись)).
    Закомментированные блоки не считаем: у oneplaysport.cz `<!--<div
    class="live">Živě</div>-->` стоит у каждой строки и ничего не значит."""
    out: collections.Counter = collections.Counter()
    text = COMMENT.sub(" ", text)
    for key, _ in JSON_BOOL.findall(text):
        if LIVE_KEY.match(key):
            out[("live", f"json:{key}=true")] += 1
        elif REPEAT_KEY.match(key):
            out[("repeat", f"json:{key}=true")] += 1
    for key, value in JSON_STR.findall(text):
        if not TYPE_KEY.match(key):
            continue
        if markers.found(markers.live, value):
            out[("live", f"json:{key}={value.strip().lower()}")] += 1
        elif markers.found(markers.not_live, value):
            out[("repeat", f"json:{key}={value.strip().lower()}")] += 1
    for classes in CLASS_ATTR.findall(text):
        for token in classes.lower().split():
            if token in LIVE_CLASSES:
                out[("live", f"class:{token}")] += 1
            elif token in REPEAT_CLASSES:
                out[("repeat", f"class:{token}")] += 1
    for kind, value in DATA_FLAG.findall(text):
        verdict = "live" if kind.lower() == "live" else "repeat"
        out[(verdict, f"attr:data-{kind.lower()}={value.lower()}")] += 1
    for value in WORD_ATTR.findall(text):
        plain = live.greek_plain(value.strip(_EDGE).casefold())
        if not plain:
            continue
        if markers.found(markers.live, plain).casefold() == plain:
            out[("live", f"attr:{plain}")] += 1
        elif markers.found(markers.not_live, plain).casefold() == plain:
            out[("repeat", f"attr:{plain}")] += 1
    seen = visible(text)
    for tag in LIVE_TAGS:
        if tag in seen:
            out[("live", f"text:{tag}")] += seen.count(tag)
    for tag in REPEAT_TAGS:
        if tag in seen:
            out[("repeat", f"text:{tag}")] += seen.count(tag)
    return out


def bare(domain: str) -> str:
    return (domain or "").removeprefix("www.")


class Site:
    """Всё, что прогон знает об одном сайте."""

    def __init__(self, domain: str):
        self.domain = domain
        self.pages = 0
        self.pages_ok = 0
        self.flags: collections.Counter = collections.Counter()
        self.words: collections.Counter = collections.Counter()
        self.word_example: dict[str, str] = {}
        self.programs = 0
        self.honest_live = 0       # эфир сказал сайт (пометка, честный домен)
        self.site_repeat = 0       # повтор сказал сайт или слово записи
        self.guessed_live = 0      # эфир угадан
        self.repeat_guess = 0      # угадыванием снято как повтор
        self.unknown_raw: collections.Counter = collections.Counter()
        self.rows: list = []       # (Row, page_name) прошедшие отсев, F/B/T
        self.errors: list[str] = []
        self.day_shift: list[str] = []
        self.time_back: list[str] = []
        # страница без даты отдала вчера: (канал, день страницы, строка)
        self.undated_yesterday: list[tuple[str, _date, str]] = []
        # (канал, день), которые хоть одна страница держит целиком
        self.days_held: set[tuple[str, _date]] = set()
        # содержимое страницы → [(день, канал, файл)] (проверка 10)
        self.by_content: dict[str, list[tuple[str, str, str]]] = \
            collections.defaultdict(list)


#: сколько символов вокруг слова смотрим, чтобы понять, не часть ли оно
#: словарного выражения («živo» внутри «v živo»)
WORD_CONTEXT = 20


_UNCOVERED: dict[int, re.Pattern | None] = {}


def _uncovered_pattern(markers) -> re.Pattern | None:
    """Одна регулярка из кандидатов, которых словарь сам по себе не знает
    (слово в словаре покрыто всегда — его искать незачем)."""
    key = id(markers)
    if key not in _UNCOVERED:
        words = [w for w in LIVE_WORD_CANDIDATES if w not in AMBIGUOUS
                 and markers.found(markers.live, w).casefold()
                 != live.greek_plain(w.casefold())]
        words.sort(key=len, reverse=True)
        _UNCOVERED[key] = re.compile(
            r"(?<!\w)(?:" + "|".join(re.escape(w) for w in words) + r")(?!\w)",
            re.I) if words else None
    return _UNCOVERED[key]


def uncovered_words(seen: str, markers, site: "Site") -> None:
    """Слова-кандидаты эфира, которые словарь НЕ узнаёт ни сами, ни в составе
    выражения рядом: «živo» в «v živo» покрыто, одинокое «otseülekanne» —
    нет."""
    rx = _uncovered_pattern(markers)
    if rx is None:
        return
    for m in rx.finditer(seen):
        around = seen[max(0, m.start() - WORD_CONTEXT):m.end() + WORD_CONTEXT]
        if markers.found(markers.live, around) or \
                markers.found(markers.not_live, around):
            continue
        word = m.group(0).casefold()
        site.words[word] += 1
        site.word_example.setdefault(word, " ".join(
            seen[max(0, m.start() - 40):m.end() + 40].split()))


def load_plan_settings() -> dict:
    return parse_live.source_settings(PLAN)


def parse_page(text: str, row: dict, setting: dict):
    parse = parser_for(row["domain"], setting.get("parser") or "")
    if parse is None:
        return None
    day = _date.fromisoformat(row["day"]) if row.get("day") else None
    extra = {"channels": setting["include"]} if setting.get("include") else {}
    try:
        return parse(text, day=day, tz=setting.get("tz"), url=row["url"], **extra)
    except TypeError:
        return parse(text, day=day, tz=setting.get("tz"), url=row["url"])


def check_day_page(site: Site, programs: list, row: dict, tz: str | None,
                   name: str) -> None:
    """Проверка 5 на одной странице: передачи легли на свой день?"""
    timed = [p for p in programs if p.start is not None]
    if not timed or not row.get("day"):
        return
    starts = [p.start for p in timed]
    if max(starts) - min(starts) > timedelta(hours=DAY_PAGE_SPAN_H):
        return                                 # неделя или сетка — не день
    zone = ZoneInfo(tz) if tz else None
    dates = collections.Counter(
        (p.start.astimezone(zone) if zone else p.start).date() for p in timed)
    main_day, count = dates.most_common(1)[0]
    page_day = _date.fromisoformat(row["day"])
    # страница с датой в адресе обязана лечь на свой день; без даты в адресе
    # («сегодня» канала, список «sport live» постранично) подозрительно только
    # одно — сайт отдал ВЧЕРА (programetv.ro, tv.orf.at ночью)
    dated = any(f in (row.get("url") or "") for f in (
        page_day.isoformat(), page_day.strftime("%d-%m-%Y"),
        page_day.strftime("%d.%m.%Y"), page_day.strftime("%Y/%m/%d"),
        page_day.strftime("%d%%2F%m%%2F%Y"), page_day.strftime("%d/%m/%Y")))
    share = count / len(timed)
    channel = row.get("channel") or ""
    if count >= DAY_SHIFT_MIN_ROWS:
        site.days_held.add((channel, main_day))
    line = (f"{name}: страница {page_day:%d.%m}, а {count} из {len(timed)} "
            f"передач — {main_day:%d.%m}")
    if len(timed) >= DAY_SHIFT_MIN_ROWS and main_day != page_day:
        if dated and share > 0.5:
            site.day_shift.append(line)
        elif not dated and main_day < page_day and share >= DAY_SHIFT_SHARE:
            # судим в check_days: если сам день скачан другой страницей
            # (ссылкой дня ночью — ORF), это не потеря
            site.undated_yesterday.append((channel, page_day, line))
    last: dict[str, datetime] = {}
    for p in timed:
        prev = last.get(p.channel_raw)
        # назад и при этом на другой день: передача «уехала» через полночь
        # (наложение передач внутри одного дня — не наш случай)
        if prev is not None and p.start < prev - timedelta(hours=TIME_BACK_H) \
                and p.start.date() != prev.date():
            site.time_back.append(
                f"{name}: {p.channel_raw} {prev:%d.%m %H:%M} → "
                f"{p.start:%d.%m %H:%M} «{(p.title or '')[:40]}»")
            break
        last[p.channel_raw] = p.start


def collect(folder: Path, markers, sports) -> dict[str, Site]:
    settings = load_plan_settings()
    league_sports = leagues.sports_map()
    pair_sports = leagues.pair_sports()
    rows = json.loads((folder / "report.json").read_text(encoding="utf-8"))["строки"]
    sites: dict[str, Site] = {}
    for row in rows:
        domain = bare(row["domain"])
        site = sites.setdefault(domain, Site(domain))
        site.pages += 1
        if row.get("итог") == "расписание есть":
            site.pages_ok += 1
        name = row.get("файл")
        if not name or not (folder / name).exists():
            continue
        text = (folder / name).read_text(encoding="utf-8", errors="replace")
        site.by_content[hashlib.md5(text.encode("utf-8")).hexdigest()].append(
            (row.get("day") or "", row.get("channel") or "", name))
        site.flags.update(raw_flags(text, markers))
        if domain not in REFERENCE_DOMAINS:
            uncovered_words(visible(text), markers, site)
        setting = settings.get(row["domain"], {})
        try:
            programs = parse_page(text, row, setting)
        except Exception as e:                       # noqa: BLE001
            site.errors.append(f"{name}: {type(e).__name__}: {e}"[:160])
            continue
        if programs is None:
            site.errors.append("своего парсера нет")
            continue
        site.programs += len(programs)
        if domain not in REFERENCE_DOMAINS:
            check_day_page(site, programs, row, setting.get("tz"), name)
        guess_domain = domain in parse_live.REPEAT_GUESS_DOMAINS
        for p in programs:
            extra = p.extra or {}
            # слово-маркер разбора (до трёх слов; длинное — это заметка
            # сайта, как у nova.bg, её отсев читает целиком)
            if p.live_raw and len(p.live_raw.split()) <= MARKER_WORDS \
                    and not markers.found(markers.live, p.live_raw) \
                    and not markers.found(markers.not_live, p.live_raw):
                site.unknown_raw[p.live_raw[:30]] += 1
            if extra.get(SITE_FLAG) == SITE_LIVE or (
                    p.live_raw and not extra.get("live_guess")
                    and not guess_domain):
                site.honest_live += 1
            elif p.live_raw and extra.get(SITE_FLAG) != SITE_REPEAT:
                site.guessed_live += 1
            if extra.get(SITE_FLAG) == SITE_REPEAT \
                    or markers.found(markers.not_live, p.signals()):
                site.site_repeat += 1
            if extra.get("repeat_guess"):
                site.repeat_guess += 1
        if domain in REFERENCE_DOMAINS:
            continue
        for r in pipeline.run(programs, markers, sports, league_sports,
                              pair_sports):
            if r.ok and r.sport in ("F", "B", "T") and r.start_kyiv:
                site.rows.append((r, name))
    return sites


# ---- проверки ---------------------------------------------------------------

def site_flag_is_guess(domain: str) -> bool:
    """Считает ли `parse_live.guessed` угаданной строку, которую пометил сам
    сайт (`site_says`). Да — значит, домен из `REPEAT_GUESS_DOMAINS` гонит
    честные строки через сверку с эталоном (как port.hu до 06.10)."""
    probe = types.SimpleNamespace(program=Program(
        channel_raw="", title="", start=None, extra={SITE_FLAG: SITE_LIVE}))
    return bool(parse_live.guessed(domain, probe))


def check_flags(sites: dict[str, Site]) -> tuple[list[str], list[str]]:
    """1 и 9: признак сайта есть — читаем ли его; угадываем ли без сверки."""
    out, known = [], []
    for domain, s in sorted(sites.items()):
        if domain in REFERENCE_DOMAINS or not s.programs:
            continue
        in_guess_list = domain in parse_live.REPEAT_GUESS_DOMAINS
        guessing = in_guess_list or s.guessed_live
        for kind in ("live", "repeat"):
            sigs = [(sig, n) for (k, sig), n in s.flags.items() if k == kind]
            fresh = []
            for sig, n in sorted(sigs, key=lambda x: -x[1]):
                why = KNOWN_NOT_FLAGS.get((domain, sig))
                if why:
                    known.append(f"{domain} {sig} ×{n} — проверено: {why}")
                elif n >= MIN_FLAGS:
                    fresh.append((sig, n))
            if not fresh:
                continue
            per_page = max(n for _, n in fresh) / max(1, s.pages)
            shown = ", ".join(f"{sig} ×{n}" for sig, n in fresh[:3])
            if kind == "live":
                if s.honest_live == 0 and per_page > NOW_PLAYING_PER_PAGE:
                    out.append(f"{domain}: в данных {shown} (страниц {s.pages}), "
                               f"а честного эфира у разбора 0, угадано "
                               f"{s.guessed_live} — признак не читается")
                elif s.honest_live == 0:
                    out.append(f"{domain}: в данных {shown} (~{per_page:.1f} на "
                               f"страницу — похоже на «идёт сейчас»), честного "
                               f"эфира 0 — проверить и внести в KNOWN_NOT_FLAGS")
                elif in_guess_list and per_page > NOW_PLAYING_PER_PAGE \
                        and site_flag_is_guess(domain):
                    out.append(f"{domain}: разбор читает признак ({shown}; "
                               f"честного эфира {s.honest_live}), а домен всё ещё "
                               f"в REPEAT_GUESS_DOMAINS — честные строки "
                               f"сверяются с эталоном как угаданные и теряются "
                               f"на кличках (DVSC)")
            elif guessing and s.site_repeat == 0:
                out.append(f"{domain}: сайт помечает повтор ({shown}), а разбор "
                           f"не отличает его, и эфир угадывается — повтор "
                           f"может стать «первым показом»")
    for domain, s in sorted(sites.items()):
        if s.repeat_guess and domain not in parse_live.REPEAT_GUESS_DOMAINS \
                and not s.guessed_live:
            out.append(f"{domain}: разбор угадывает эфир ({s.repeat_guess} "
                       f"строк сняты как повтор), а сверки с эталоном нет — "
                       f"ни REPEAT_GUESS_DOMAINS, ни live_guess у строк")
    return out, known


def check_words(sites: dict[str, Site], markers) -> list[str]:
    """2: слово эфира, которого нет в словаре — на странице и в `live_raw`."""
    out = []
    for domain, s in sorted(sites.items()):
        for raw, n in s.unknown_raw.most_common(3):
            out.append(f"{domain}: разбор кладёт в live_raw «{raw}» ({n} строк), "
                       f"а в markers.json этого слова нет — отсев его не видит")
        for word, n in s.words.most_common():
            if n < MIN_WORD_HITS:
                continue
            out.append(f"{domain}: на странице «{word}» ×{n}, в markers.json нет — "
                       f"«…{s.word_example.get(word, '')[:90]}…»")
    return out


def games_by_source(games: dict) -> collections.Counter:
    per: collections.Counter = collections.Counter()
    for g in games.get("games") or []:
        for src in {bare(e.get("source", "")) for e in g.get("entries") or []}:
            per[src] += 1
    return per


def window_days(games: dict) -> float:
    return float(games.get("окно") or 1) or 1.0


def check_empty(sites: dict[str, Site], games: dict | None,
                prev: dict | None) -> list[str]:
    """3: «расписание есть», а игр 0 или резко меньше прошлого прогона."""
    if games is None:
        return []
    out = []
    now = games_by_source(games)
    before = games_by_source(prev) if prev else collections.Counter()
    days_now, days_prev = window_days(games), window_days(prev or {})
    parsed = {bare(k): v for k, v in (games.get("разобрано") or {}).items()}
    days = run_window(games)
    for domain, s in sorted(sites.items()):
        if domain in REFERENCE_DOMAINS or not s.pages_ok:
            continue
        n = now.get(domain, 0)
        # строки окна витрины, прошедшие отсев: честные и угаданные отдельно —
        # угаданные законно снимаются сверкой с эталоном
        window = [r for r, _ in s.rows if r.start_kyiv.date() in days]
        honest = [r for r in window if not parse_live.guessed(domain, r)
                  or (r.program.extra or {}).get(SITE_FLAG) == SITE_LIVE]
        if n == 0 and (honest or not parsed.get(domain)):
            why = ("строк разбор не дал вовсе — разметка или настройка "
                   "источника?" if not parsed.get(domain) else
                   f"честно помеченных эфиром строк спорта в окне {len(honest)}, "
                   f"в игры не попало ни одной")
            out.append(f"{domain}: расписание есть ({s.pages_ok} стр.), игр 0 — {why}")
            continue
        # сравниваем только прогоны с ОДНИМ окном: у скана даты (окно 0, один
        # день) и полного обхода на 6 суток разная глубина сайтов — skysports
        # публикует 2 дня, и «17 за 6 суток против 17 за сутки» не просадка
        if prev and (prev.get("окно") or 0) == (games.get("окно") or 0):
            rate_prev = before.get(domain, 0) / days_prev
            rate_now = n / days_now
            if rate_prev >= MIN_PREV_PER_DAY and rate_now < DROP_SHARE * rate_prev:
                out.append(f"{domain}: игр {n} за {days_now:g} сут. против "
                           f"{before.get(domain, 0)} за {days_prev:g} сут. в прошлом "
                           f"прогоне — меньше {int(DROP_SHARE * 100)} %")
    return out


def check_reference(games: dict | None) -> list[str]:
    """4: один fs_id эталона с двумя временами."""
    if games is None:
        return []
    times: dict[str, set] = collections.defaultdict(set)
    who: dict[str, str] = {}
    for r in games.get("эталон") or []:
        if r.get("fs_id"):
            times[r["fs_id"]].add(r.get("start_kyiv") or "")
            who[r["fs_id"]] = f"{r.get('home')} — {r.get('away')}"
    twins = {fs: sorted(t) for fs, t in times.items() if len(t) > 1}
    if not twins:
        return []
    # разница ровно в сутки — матч после полуночи лёг и на «свой», и на
    # соседний день страниц flashscore (класс «полночь эталона»)
    day_apart = 0
    for t in twins.values():
        try:
            gap = datetime.fromisoformat(t[-1]) - datetime.fromisoformat(t[0])
        except ValueError:
            continue
        day_apart += gap == timedelta(days=1)
    head = (f"всего {len(twins)} fs_id с двумя временами, из них ровно на сутки "
            f"разнесены {day_apart} — матч после полуночи лёг на два дня "
            f"страниц flashscore")
    return [head] + [f"{fs}: {who[fs]} — времена {', '.join(t)}"
                     for fs, t in sorted(twins.items())[:EXAMPLES * 2]]


def check_days(sites: dict[str, Site]) -> list[str]:
    """5: передачи страницы дня уехали на другой день / время пошло назад.
    Страница «сегодня» без даты, отдавшая вчера, — подозрение, только если
    этот день у канала не скачан другой страницей."""
    out = []
    for domain, s in sorted(sites.items()):
        if s.day_shift:
            out.append(f"{domain}: {len(s.day_shift)} стр. легли не на свой день — "
                       + "; ".join(s.day_shift[:2]))
        lost_day = [line for channel, day, line in s.undated_yesterday
                    if (channel, day) not in s.days_held]
        if lost_day:
            out.append(f"{domain}: {len(lost_day)} стр. «сегодня» без даты отдали "
                       f"ВЧЕРА, а сам день другой страницей не скачан — "
                       + "; ".join(lost_day[:2]))
        if s.time_back:
            out.append(f"{domain}: время в сетке пошло назад на {len(s.time_back)} "
                       f"стр. — " + "; ".join(s.time_back[:2]))
    return out


def check_same_pages(sites: dict[str, Site]) -> list[str]:
    """10: разные адреса сайта (день или канал) дали один и тот же файл —
    запросы впустую, а дни/каналы, которых ждали, не пришли вовсе."""
    out = []
    for domain, s in sorted(sites.items()):
        groups = [g for g in s.by_content.values() if len(g) >= SAME_PAGE_MIN]
        if not groups:
            continue
        wasted = sum(len(g) - 1 for g in groups)
        shown = []
        for g in sorted(groups, key=len, reverse=True)[:2]:
            days = sorted({d for d, _, _ in g if d})
            channels = sorted({c for _, c, _ in g if c})
            what = (f"дни {days[0]}…{days[-1]}" if len(days) > 1 else
                    f"каналы {', '.join(channels[:4])}" if len(channels) > 1 else
                    g[0][2])
            shown.append(f"{len(g)} одинаковых ({what}) — {g[0][2][:80]}")
        out.append(f"{domain}: {wasted} запрос(ов) впустую — " + "; ".join(shown)
                   + ". Параметр дня сайт не слышит или адрес канала отдаёт "
                     "чужую страницу")
    return out


def run_window(games: dict) -> set:
    """Киевские дни, которые прогон показывает на витрине."""
    if games.get("окно"):
        stamp = datetime.strptime(games["собрано"], "%Y-%m-%d %H:%M") \
            .replace(tzinfo=ZoneInfo("UTC")).astimezone(KYIV).date()
        return {stamp + timedelta(days=i) for i in range(7)}
    return {datetime.fromisoformat(g["start_kyiv"]).date()
            for g in games.get("games") or []}


def check_lost(sites: dict[str, Site], games: dict | None) -> tuple[list[str], list[str]]:
    """6: строку сайт сам назвал эфиром, она прошла отсев — и пропала."""
    if games is None:
        return [], []
    taken = set()
    for g in games.get("games") or []:
        for e in g.get("entries") or []:
            taken.add((bare(e.get("source", "")), e.get("channel", ""),
                       (e.get("raw_title") or "")[:200]))
    review = {(bare(x.get("домен", "")), x.get("канал", ""), (x.get("raw_title") or "")[:200])
              for x in games.get("на_разбор") or []}
    # журнал «снято»: строку убрал фильтр повторов — это не потеря, а решение
    removed = {(bare(x.get("домен", "")), x.get("канал", ""),
                (x.get("заголовок") or "")[:200]): x for x in games.get("снято") or []}
    placeholder = placeholder_times(games)
    days = run_window(games)
    out, info = [], []
    for domain, s in sorted(sites.items()):
        honest, doubtful, guessed = [], [], 0
        by_filter: collections.Counter = collections.Counter()
        seen = set()
        for r, _ in s.rows:
            if r.start_kyiv.date() not in days:
                continue
            key = (domain, r.program.channel_raw or "", (r.program.title or "")[:200])
            if key in taken or key in review or key in seen:
                continue
            seen.add(key)
            extra = r.program.extra or {}
            if parse_live.guessed(domain, r) and extra.get(SITE_FLAG) != SITE_LIVE:
                guessed += 1
            elif key in removed:
                why = removed[key]
                ref = placeholder.get(_fs_id(why.get("почему") or ""))
                if why.get("фильтр") == parse_live.СНЯТО_СЫГРАН and ref:
                    doubtful.append((r, ref))
                else:
                    by_filter[why.get("фильтр") or "?"] += 1
            else:
                honest.append(r)
        if honest:
            ex = "; ".join(f"{r.start_kyiv:%d.%m %H:%M} {r.program.channel_raw} "
                           f"«{r.home} — {r.away}»" for r in honest[:EXAMPLES])
            out.append(f"{domain}: {len(honest)} строк(и) с пометкой эфира прошли "
                       f"отсев и пропали — {ex}")
        if doubtful:
            ex = "; ".join(f"{r.start_kyiv:%d.%m %H:%M} {r.program.channel_raw} "
                           f"«{r.home} — {r.away}» (эталон {ref})"
                           for r, ref in doubtful[:EXAMPLES])
            out.append(f"{domain}: {len(doubtful)} строк(и) с пометкой эфира сняты "
                       f"«{parse_live.СНЯТО_СЫГРАН}», а время эталона — заглушка "
                       f"тура (≥{ROUND_SAME_TIME} матчей лиги в одну минуту): сайт, "
                       f"скорее всего, прав — {ex}")
        for name, n in by_filter.most_common():
            info.append(f"{domain}: помеченных эфиром снято фильтром «{name}» — {n}")
        if guessed:
            info.append(f"{domain}: угаданных эфиров снято {guessed} (повтор / нет в эталоне)")
    return out, info


_FS_ID = re.compile(r"fs_id\s+(\w+)")


def _fs_id(text: str) -> str:
    found = _FS_ID.search(text or "")
    return found.group(1) if found else ""


def placeholder_times(games: dict) -> dict[str, str]:
    """fs_id эталона, чьё время похоже на заглушку тура: у лиги в этот день
    `ROUND_SAME_TIME` и больше матчей ровно в одну минуту → «лига, время»."""
    by_slot: dict[tuple, list[str]] = collections.defaultdict(list)
    for r in games.get("эталон") or []:
        if r.get("fs_id") and r.get("league") and r.get("start_kyiv"):
            by_slot[(r["league"], r["start_kyiv"])].append(r["fs_id"])
    out: dict[str, str] = {}
    for (league, when), ids in by_slot.items():
        if len(ids) >= ROUND_SAME_TIME:
            for fs in ids:
                out[fs] = f"{league}: {len(ids)} матчей в {when[11:16]} {when[8:10]}.{when[5:7]}"
    return out


def _ref_index(games: dict) -> dict:
    by_hour: dict = collections.defaultdict(list)
    for r in games.get("эталон") or []:
        try:
            when = datetime.fromisoformat(r.get("start_kyiv") or "").replace(tzinfo=KYIV)
        except ValueError:
            continue
        by_hour[when.replace(minute=0)].append((r, when))
    return by_hour


def _near(index: dict, when: datetime, span: timedelta):
    base = when.replace(minute=0, second=0, microsecond=0)
    hours = int(span.total_seconds() // 3600) + 1
    for h in range(-hours, hours + 1):
        for r, t in index.get(base + timedelta(hours=h), []):
            if abs(t - when) <= span:
                yield r, t


def _score(home: str, away: str, sport_letter: str, ref: dict) -> int:
    game = {"home": home, "away": away, "sport": sport_letter}
    swapped = {"home": away, "away": home, "sport": sport_letter}
    return max(_pair_score(game, ref), _pair_score(swapped, ref))


def _ref_sides(ref: dict, script: str) -> list[tuple[str, str, str]]:
    """Написания сторон эталона той же письменности: (сторона, имя, чужое
    имя той же записи). Иврит с латиницей не сравниваем вовсе."""
    out = []
    if script == "lat":
        out += [("home", ref.get("home") or "", ref.get("away") or ""),
                ("away", ref.get("away") or "", ref.get("home") or "")]
    for h, a in _local_sides(ref, script):
        out += [("home", h, a), ("away", a, h)]
    return out


def _initial(name: str) -> str:
    """Первая буква имени без клубной обвязки (`FC`, `SK`, `AS`…): у
    сокращения и полного имени она общая — DVSC/Debrecen, PSG/Paris SG."""
    words = [w for w in re.split(r"[\s.\-]+", name.upper())
             if w and w not in CLUB_FORMS]
    return words[0][:1] if words else ""


def _sure_side(mine: str, ref: dict) -> str | None:
    """Имя `mine` твёрдо (≥ ALIAS_SURE, тот же пол и возраст) совпало с одной
    стороной эталона (любым написанием той же письменности) — какой:
    `home`/`away`."""
    for side, name, _ in _ref_sides(ref, _script(mine)):
        if name and names.same_team(mine, name, ALIAS_SURE):
            return side
    return None


def _strict_match(home: str, away: str, ref: dict) -> bool:
    """Сошлась ли пара так, как её сверяет `parse_live._in_reference`: обе
    команды `same_team`, у латиницы — только с АНГЛИЙСКИМИ именами эталона,
    местные написания — только для кириллицы, греческого, иврита. Канон
    (`canon._pair_score`) мягче: берёт и венгерские/румынские/чешские имена
    flashscore — «DVSC» он узнаёт через «Debreceni VSC», а сверка разбора
    видит только «Debrecen» и снимает угаданный эфир (port.hu, 06.10)."""
    script = _script(f"{home} {away}")
    sides = [(ref.get("home") or "", ref.get("away") or "")] if script == "lat" \
        else _local_sides(ref, script)
    for h, a in sides:
        if (names.same_team(home, h) and names.same_team(away, a)) \
                or (names.same_team(home, a) and names.same_team(away, h)):
            return True
    return False


def check_aliases_and_zones(sites: dict[str, Site], games: dict | None
                            ) -> tuple[list[str], list[str], list[str]]:
    """7 и 8 по строкам, прошедшим отсев: кличка и сдвиг на целые часы.
    Третий список — справка: честные строки, которые сведёт канон."""
    if games is None or not games.get("эталон"):
        return [], [], []
    index = _ref_index(games)
    days = run_window(games)
    aliases: dict = collections.defaultdict(list)
    zones: dict = collections.defaultdict(collections.Counter)
    zone_example: dict = {}
    matched: collections.Counter = collections.Counter()   # сошлись в ±3 ч
    canon_only: collections.Counter = collections.Counter()  # сведёт канон
    for domain, s in sorted(sites.items()):
        done = set()
        for r, _ in s.rows:
            if r.start_kyiv.date() not in days or r.sport == "T":
                continue
            if names.is_placeholder(r.home) or names.is_placeholder(r.away):
                continue
            key = (r.home, r.away, r.start_kyiv)
            if key in done:
                continue
            done.add(key)
            when = r.start_kyiv
            near = [(ref, t) for ref, t in _near(index, when, timedelta(hours=3))
                    if (ref.get("sport") or "F") == r.sport]
            if any(_strict_match(r.home, r.away, ref) for ref, _ in near):
                matched[domain] += 1
                continue                       # пара сошлась — всё хорошо
            # 7: одна сторона твёрдо, вторая с английским именем эталона не
            # сходится, время то же, и при этом либо канон узнаёт её через
            # местное написание (DVSC ↔ Debreceni VSC), либо первая буква
            # общая (сокращение или кличка: QPR, Barca). Чужой матч с тёзкой
            # («Wycombe Wanderers» ≠ уругвайские «Wanderers») так не пройдёт
            cands = []
            for ref, t in near:
                if abs(t - when) > ALIAS_WINDOW:
                    continue
                for mine, other in ((r.home, r.away), (r.away, r.home)):
                    side = _sure_side(mine, ref)
                    if side is None:
                        continue
                    theirs = ref.get("away" if side == "home" else "home") or ""
                    if names.same_team(other, theirs):
                        break
                    by_canon = _score(r.home, r.away, r.sport, ref) >= names.SIMILAR_ENOUGH
                    if by_canon or (_initial(other) and _initial(other) == _initial(theirs)):
                        cands.append((ref, other, theirs, by_canon))
                    break
            if len(cands) == 1:
                ref, other, theirs, by_canon = cands[0]
                will_drop = parse_live.guessed(domain, r)
                if by_canon and not will_drop:
                    # честная строка, канон на сервере сведёт её по местному
                    # имени flashscore — не подозрение, только счёт в справке
                    canon_only[domain] += 1
                    continue
                note = (" — канон узнаёт пару через местное имя flashscore, а "
                        "сверка разбора (английские имена) — нет"
                        if by_canon else "")
                if will_drop:
                    note += " — эфир угадан: сверка с эталоном СНИМЕТ строку"
                aliases[(domain, other, theirs)].append(
                    f"{when:%d.%m %H:%M} «{r.home} — {r.away}» ↔ эталон "
                    f"«{ref.get('home')} — {ref.get('away')}» ({ref.get('league')}; "
                    f"у сайта лига «{(r.program.league_raw or r.league or '')[:40]}»)"
                    + note)
            # 8: та же пара в эталоне ровно на N часов раньше/позже
            for ref, t in _near(index, when, TZ_WINDOW):
                if (ref.get("sport") or "F") != r.sport:
                    continue
                gap = when - t
                hours = round(gap.total_seconds() / 3600)
                if hours == 0 or abs(gap - timedelta(hours=hours)) > TZ_TOLERANCE:
                    continue
                if _score(r.home, r.away, r.sport, ref) >= names.SIMILAR_ENOUGH:
                    zones[domain][hours] += 1
                    zone_example.setdefault((domain, hours),
                                            f"«{r.home} — {r.away}» сайт {when:%d.%m %H:%M}, "
                                            f"эталон {t:%d.%m %H:%M}")
                    break
    alias_out, skipped = [], []
    for (domain, other, theirs), seen in sorted(aliases.items()):
        why = KNOWN_NOT_ALIASES.get((other, theirs))
        if why:
            skipped.append(f"{domain}: «{other}» ≠ «{theirs}» — проверено, в словарь "
                           f"не кладём: {why}")
            continue
        alias_out.append(f"{domain}: «{other}» ≠ «{theirs}»? — {seen[0]}"
                         + (f" (и ещё {len(seen) - 1})" if len(seen) > 1 else ""))
    zone_out = []
    for domain, per in sorted(zones.items()):
        for hours, n in per.most_common():
            if n >= TZ_MIN_ROWS and n >= TZ_SHARE * (n + matched[domain]):
                zone_out.append(f"{domain}: {n} строк(и) на {hours:+d} ч от эталона — "
                                f"{zone_example[(domain, hours)]}")
    canon_info = [f"{domain}: {n} честн. строк(и) не сходятся с английскими именами "
                  f"эталона, но канон сведёт их по местным (не подозрение)"
                  for domain, n in sorted(canon_only.items())]
    return alias_out, zone_out, skipped + canon_info


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="папка артефакта прогона")
    ap.add_argument("--prev", default="", help="папка прошлого прогона (для проверки 3)")
    ap.add_argument("--games", default="",
                    help="другой games.json (локальный разбор той же папки); "
                         "по умолчанию — <dir>/games.json")
    ap.add_argument("--md", default="", help="куда записать отчёт")
    args = ap.parse_args()

    folder = Path(args.dir)
    if not (folder / "report.json").exists():
        print(f"нет {folder / 'report.json'} — это не папка прогона")
        return 1
    markers, sports = live.load(), sport.load()

    def read_games(path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    games = read_games(Path(args.games) if args.games else folder / "games.json")
    prev = read_games(Path(args.prev) / "games.json") if args.prev else None
    sites = collect(folder, markers, sports)

    flags, known = check_flags(sites)
    lost, lost_info = check_lost(sites, games)
    alias, zones, canon_info = check_aliases_and_zones(sites, games)
    sections = [
        ("1/9. Признак эфира или повтора есть, а разбор его не читает", flags),
        ("2. Слово эфира не в словаре markers.json", check_words(sites, markers)),
        ("3. Расписание есть, а игр нет (или резко меньше)", check_empty(sites, games, prev)),
        ("4. Эталон: один fs_id — два времени", check_reference(games)),
        ("5. Передачи легли не на свой день", check_days(sites)),
        ("6. Помеченный эфир прошёл отсев и пропал", lost),
        ("7. Кличка: вторая команда сошлась, эта — нет", alias),
        ("8. Время сайта отличается от эталона на целые часы", zones),
        ("10. Одна страница на разные дни или каналы", check_same_pages(sites)),
    ]
    errors = [f"{d}: {e}" for d, s in sorted(sites.items()) for e in s.errors[:2]]
    if errors:
        sections.append(("Разбор упал", errors))

    head = (f"Самопроверка прогона {folder.name}: "
            + (f"собрано {games.get('собрано')}, окно {games.get('окно')}, "
               f"игр {games.get('игр')}" if games else "games.json нет — "
               "проверки 3, 4, 6–8 пропущены"))
    total = sum(len(lines) for _, lines in sections)
    suspicious = {line.split(":", 1)[0] for _, lines in sections for line in lines}
    lines = [f"# {head}", "", f"Подозрений: **{total}**, сайтов (и меток эталона): "
             f"{len(suspicious)}.", ""]
    for title, items in sections:
        lines.append(f"## {title} — {len(items) or 'нет'}")
        lines += [f"- {x}" for x in items]
        lines.append("")
    if known or lost_info or canon_info:
        lines.append("## Справка (не подозрения)")
        lines += [f"- {x}" for x in known + lost_info + canon_info]
    text = "\n".join(lines) + "\n"
    print(text)
    if args.md:
        Path(args.md).write_text(text, encoding="utf-8")
        print(f"отчёт: {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

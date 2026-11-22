"""Запасное чтение страницы с НЕСКОЛЬКИМИ каналами (книга 171; вопрос
владельца 19.11: «какой-то ещё запасной вариант … может быть написан, чтоб
обошло другим способом?», слово 21.11 «Да, делаем»).

Случай: запасное чтение книги 125 (`app/fallback_read.py`) умеет только
страницу с ОДНИМ каналом — канал страницы оно помнит из прошлых сборов. На
странице с несколькими каналами канал строки взять было неоткуда: сайт
сменил устройство такой страницы — свой разборщик даёт ноль строк, и сайт
молчит, пока разборщик не поправят.

Общий способ чтения такой страницы без знания её устройства (замер 20.11 на
сборе 18.11, 38 сайтов): на 9 сайтах он даёт те же строки, что свой
разборщик, на 5 — путает каналы, на 24 — не видит ничего. Поэтому способу
верим НЕ ПО СПИСКУ сайтов, а по проверке «в тени» на каждом сборе: пока свой
разборщик работает, он — правильный ответ, по которому запасное чтение
подбирает из своей копилки способ, читающий эту страницу так же (слова
владельца 22.11: «запасной вариант это то что копит в себе опыт и способы
которые могут подойти всем, проверяя поэтапно из своей базы знаний какой
метод подойдёт»).

ПРАВИЛА (что случилось → что делаем):
  М1. Свой разборщик страницу прочитал, каналов на ней два и больше, строк
      не меньше `MANY_MIN` — сбор читает её ещё и общим способом «в тени»
      (`shadow`) и сверяет В ОБЕ СТОРОНЫ (`differs`):
        а) каждая строка своего разборщика есть у общего способа — тот же
           канал, то же начало (день и время), то же название;
        б) у общего способа нет ЛИШНИХ строк знакомых каналов внутри окна
           времени страницы (от первой до последней строки своего
           разборщика). Лишняя строка — знак, что общий способ приписал
           каналу чужое: между знакомыми каналами на странице стоит
           незнакомый, и его строки ушли соседу (замер 20.11: sport5.co.il).
      Строки общего способа за окном (хвост следующего дня) не в счёт.
  М2. Сошлось — страница запоминается: ключ страницы (адрес без дат) →
      имена её каналов и окно времени в часах от начала дня страницы (ключ
      games.json `MANY_KEY`). У одного ключа в сборе несколько страниц (по
      дням): запоминаем, только если сошлись ВСЕ. Не сошлась хоть одна —
      ключ из памяти убирается: способу на этой странице верить нельзя.
      Имена каналов копятся из сбора в сбор, пока страница сходится: канал,
      у которого сегодня нет передач, завтра не должен стать незнакомым.
      К ним добавляются каналы сайта из списка владельца (`also` — `include`
      плана обхода): и в тени, и при чтении.
  М3. Общий способ, страница с разметкой (`_rows_html`): идём по странице
      сверху вниз. Подпись (текст, `alt`, `title`, `aria-label`, хвост
      адреса ссылки), равная имени знакомого канала, — дальше идут строки
      этого канала. Строка расписания — текст, начинающийся со времени:
      название — остаток текста либо следующий кусок текста. Время, ушедшее
      назад больше чем на 6 часов внутри одного канала, — следующие сутки.
  М4. Общий способ, служебный ответ без разметки (`_rows_json`): запись с
      полем начала и полем названия — передача; её канал — имя знакомого
      канала в её же полях, иначе — ближайшая сверху запись, в полях которой
      стоит имя знакомого канала.
  М5. Свой разборщик дал НОЛЬ строк на открывшейся странице, а она в памяти
      (М2) — читаем общим способом с именами каналов из памяти (`read`).
      Строки идут как у книги 125 (З4): без пометки эфира и без пары — в
      ленту попадут, только если пару из названия подтвердил эталон на это
      время. Строка до первой подписи канала (канал неизвестен) и строка
      за окном времени из памяти (М2) не берутся; одинаковые строки (сайт
      кладёт сетку дважды — для телефона и для компьютера) берутся раз.
  М6. Страницы в памяти нет — ничего не делаем: всё как до книги 171.

ПОМЕТКА ЭФИРА (книга 175; вопрос владельца 22.11 «почему не видит?», слово
«да, делаем оба»). Проба книги 171 на сборе 20.11: без пометки эфира
запасное чтение не вернуло игры, которых эталон не знает (имена на иврите
без перевода, sport5.co.il), и показ матча, подхваченный каналом с середины
(ziggosport.nl). Пометка у каждого сайта своя, поэтому способ её чтения тоже
подбирается в тени:
  К1. Общий способ у каждой строки смотрит пометку эфира несколькими
      способами (`WAYS_HTML`, `WAYS_JSON`). Слово эфира — из словаря
      (`data/markers.json`, live) на языке сайта; кусок, где рядом стоит
      слово записи, — не эфир (`_live_word`).
        страница с разметкой: «название» — слово эфира в самой строке
        (время и название); «после» — в кусках после времени до следующей
        строки или подписи канала (текст и подписи картинок), кроме самого
        названия; «до» — в кусках перед временем, после конца прошлой строки.
        служебный ответ: «название»; «поле» — в записи есть поле эфира
        (`LIVE_KEYS`) со значением «да»; «значение» — короткое значение
        любого другого поля — слово эфира.
  К2. Тень (М1) сошлась — у каждого способа проверяем: у ВСЕХ строк своего
      разборщика на странице пометка общего способа та же (эфир / не эфир),
      что поставил свой разборщик (`_live_ways`). В память страницы (М2)
      идут способы, сошедшиеся на ВСЕХ страницах ключа в этом сборе, и
      число строк с эфиром, на которых это проверено (`LIVE`).
  К3. Чтение (М5): в памяти есть сошедшийся способ и проверен он не меньше
      чем на `LIVE_MIN` строках с эфиром — строки читаются С ПОМЕТКОЙ ЭФИРА
      (первым из сошедшихся способов) и идут обычным путём, как строки
      сайта с честной пометкой: помеченная — эфир, непомеченная — как у
      такого сайта (эталон). Страница при этом не «слепая»
      (`fallback_read.blind`, книга 173). Способа нет — как раньше (М5, З4).
  К4. Пара у строки с пометкой эфира. Свой разборщик отдаёт пару отдельным
      полем, общий способ видит только название целиком («ליגה צרפתית:
      מונאקו - אוקזר, מחזור 11»). Как вынуть пару из названия, тоже
      подбирается в тени (`PAIR_WAYS`: как есть, без скобок в конце, после
      двоеточия, до запятой и их сочетания): способ годен, если у ВСЕХ строк
      своего разборщика с эфиром и парой он даёт ту же пару (`_pair_ways`).
      Сошёлся не меньше чем на `LIVE_MIN` строках — при чтении строка с
      пометкой эфира получает пару этим способом, а рубрика до двоеточия
      идёт в поле лиги. Не сошёлся — пары у строки нет, её ищет эталон
      (как у строки сайта, где пара не прочиталась).
"""
from __future__ import annotations

import html as _html
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import fallback_read
from .parsers import Program, label

#: ключ games.json: {ключ страницы: {`NAMES`: [имена каналов], `WINDOW`:
#: [с какого часа, по какой час от начала дня страницы], `LIVE`: {…}}} —
#: страницы с несколькими каналами, которые общий способ в тени прочитал так
#: же, как свой разборщик
MANY_KEY = "страницы_с_каналами"
NAMES = "каналы"
WINDOW = "окно"
#: К2: {`LIVE_WAYS`: [способы, которыми пометка эфира сошлась], `LIVE_ROWS`:
#: на скольких строках с эфиром проверено}
LIVE = "пометка"
LIVE_WAYS = "способы"
LIVE_ROWS = "эфиров"
#: К4: там же — [способы, которыми из названия вынимается пара] и на
#: скольких строках с эфиром и парой это проверено
PAIR = "пара"
PAIR_ROWS = "пар"
#: К3: на меньшем числе строк с эфиром способу пометки не верим
LIVE_MIN = 3
#: К1: способы чтения пометки эфира — по порядку предпочтения
WAYS_HTML = ("название", "после", "до")
WAYS_JSON = ("название", "поле", "значение")
#: К1: поля служебного ответа, которые значат «прямой эфир»
LIVE_KEYS = frozenset(("live", "islive", "direct", "isdirect", "directo", "endirecto", "endirect",
                       "direkt", "livebroadcast", "islivebroadcast"))
#: К1: значения поля эфира, которые значат «да»
_YES = frozenset(("1", "true", "yes", "y", "live", "да"))
#: К1: длиннее — не пометка, а текст
_MARK_MAX = 300
_VALUE_MAX = 40
#: М1: меньше строк своего разборщика на странице — сверять не с чем
MANY_MIN = 3
#: М3: содержимое этих узлов на странице не видно
_HIDDEN = frozenset(("script", "style", "noscript", "template"))
#: М3: где у узла лежит подпись
_LABEL_ATTRS = ("alt", "title", "aria-label")
#: М3: название стоит не дальше стольких кусков после времени
_TITLE_REACH = 5
#: М3: дальше стольких суток от дня страницы общий способ не читает
_MAX_SHIFT = 1

_PARENS = re.compile(r"\s*\([^()]*\)\s*$")
#: К4: двоеточие после рубрики — с пробелом и без («…בכדורגל:פאריס FC - אנז'ה»), но не в «21:45»
_COLON = re.compile(r"(?<!\d):(?!\d)\s*|(?<=\d):\s+")


def _after_colon(title: str) -> str:
    parts = _COLON.split(title, 1)
    return parts[1] if len(parts) == 2 and parts[1].strip() else title


def _to_comma(title: str) -> str:
    return title.split(", ", 1)[0]


def _no_parens(title: str) -> str:
    return _PARENS.sub("", title)


#: К4: способы вынуть пару из названия — по порядку предпочтения
PAIR_WAYS = {
    "как есть": lambda t: t,
    "без скобок": _no_parens,
    "после двоеточия": _after_colon,
    "после двоеточия, без скобок": lambda t: _no_parens(_after_colon(t)),
    "до запятой": _to_comma,
    "после двоеточия, до запятой": lambda t: _to_comma(_after_colon(t)),
}

_markers = None


def _live_word(domain: str):
    """К1: функция «слово эфира в куске текста» на языке сайта. Пусто — эфира
    в куске нет либо рядом стоит слово записи («повтор прямого эфира»)."""
    global _markers
    from . import live, site_lang
    if _markers is None:
        _markers = live.load()
    markers = _markers.for_langs(site_lang.of(domain)) if domain else _markers

    def word(text) -> str:
        if not isinstance(text, str) or not text or len(text) > _MARK_MAX:
            return ""
        if markers.found(markers.not_live, text):
            return ""
        return markers.found(markers.live, text)
    return word


def _tokens(page: str) -> list[tuple[bool, str]]:
    """М3: страница сверху вниз по кускам: (это видимый текст?, сам текст).
    Не текст — подпись узла (`_LABEL_ATTRS`) или хвост адреса ссылки."""
    tree = HTMLParser(page or "")
    root = tree.body or tree.root
    out: list[tuple[bool, str]] = []
    if root is None:
        return out
    for node in root.traverse(include_text=True):
        if node.tag == "-text":
            parent = node.parent
            if parent is not None and parent.tag in _HIDDEN:
                continue
            text = " ".join((node.text() or "").split())
            if text:
                out.append((True, text))
            continue
        attrs = node.attributes
        for attr in _LABEL_ATTRS:
            text = " ".join((attrs.get(attr) or "").split())
            if text:
                out.append((False, text))
        tail = label.tail_of(attrs.get("href"))
        if tail:
            out.append((False, tail))
    return out


def _known(names) -> dict[str, str]:
    """{имя для сверки: имя как у своего разборщика} — по списку имён каналов."""
    return {label.key(name): name for name in names or [] if label.key(name)}


def _channel_of(text: str, known: dict[str, str]) -> str:
    """Имя знакомого канала, если кусок текста — оно и есть; иначе пусто."""
    if len(text) > label.NAME_MAX:
        return ""
    return known.get(label.key(text), "")


def _first(words) -> str:
    return next((w for w in words if w), "")


def _rows_html(page: str, day: date, zone, known: dict[str, str], word=None) -> list[tuple]:
    """М3: [(канал или '', начало, название, пометки)] со страницы с
    разметкой. `пометки` — К1: {способ: слово эфира или ''}; `word` не дан —
    пометки не читаются (пустой словарь)."""
    tokens = _tokens(page)
    rows: list[tuple] = []
    spans: list[tuple[int, int, int]] = []           # К1: строка → (конец прошлой, время, название)
    channel, shift, last = "", 0, None
    end = -1                                         # где кончилась прошлая строка или подпись канала
    for i, (is_text, text) in enumerate(tokens):
        name = _channel_of(text, known)
        if name:
            if name != channel:                      # новый канал — сутки считаем заново
                channel, shift, last = name, 0, None
            end = i
            continue
        if not is_text:
            continue
        m = fallback_read._TIME.match(text)
        if not m:
            continue
        title, title_at = m["rest"].strip(), i
        if not title:
            at = next((j for j in range(i + 1, min(len(tokens), i + 1 + _TITLE_REACH)) if tokens[j][0]), None)
            nxt = tokens[at][1] if at is not None else ""
            if nxt and not fallback_read._TIME.match(nxt) and not _channel_of(nxt, known):
                title, title_at = nxt, at
        before, end = end, max(i, title_at)
        if len(title) < 3:
            continue
        minutes = int(m["h"]) * 60 + int(m["m"])
        if last is not None and minutes < last - 360:
            shift += 1
        last = minutes
        if shift > _MAX_SHIFT:
            continue
        start = datetime(day.year, day.month, day.day, int(m["h"]), int(m["m"]),
                         tzinfo=zone) + timedelta(days=shift)
        rows.append((channel, start, title))
        spans.append((before, i, title_at))
    if word is None:
        return [(*row, {}) for row in rows]
    # К1: где кончается «после» у строки — на следующем времени или подписи канала
    stops = sorted({i for i, (is_text, text) in enumerate(tokens)
                    if _channel_of(text, known) or (is_text and fallback_read._TIME.match(text))})
    out = []
    for row, (before, at, title_at) in zip(rows, spans):
        nxt = next((s for s in stops if s > at and s != title_at), len(tokens))
        marks = {
            "название": _first((word(tokens[at][1]), word(row[2]))),
            "после": _first(word(tokens[j][1]) for j in range(at + 1, nxt) if j != title_at),
            "до": _first(word(tokens[j][1]) for j in range(before + 1, at)),
        }
        out.append((*row, marks))
    return out


def _rows_json(page: str, zone, known: dict[str, str], word=None) -> list[tuple]:
    """М4: [(канал или '', начало, название, пометки)] из служебного ответа."""
    try:
        data = json.loads(page)
    except ValueError:
        return []
    rows: list[tuple] = []

    def marks_of(node: dict, keys: dict, title: str) -> dict:
        if word is None:
            return {}
        field = any(k in LIVE_KEYS and (node[keys[k]] is True or (
            isinstance(node[keys[k]], (int, float)) and not isinstance(node[keys[k]], bool) and node[keys[k]] == 1) or (
            isinstance(node[keys[k]], str) and node[keys[k]].strip().lower() in _YES)) for k in keys)
        value = _first(word(v) for k, v in node.items()
                       if isinstance(v, str) and v != title and len(v) <= _VALUE_MAX
                       and fallback_read._plain_key(k) not in LIVE_KEYS)
        return {"название": word(title), "поле": "live" if field else "", "значение": value}

    def walk(node, channel: str, depth: int) -> None:
        if depth > fallback_read.JSON_DEPTH or len(rows) >= fallback_read.JSON_ROWS * 4:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, channel, depth + 1)
            return
        if not isinstance(node, dict):
            return
        keys = {fallback_read._plain_key(k): k for k in node}
        start = next((fallback_read.moment(node[keys[k]], zone) for k in keys
                      if k in fallback_read.START_KEYS and fallback_read.moment(node[keys[k]], zone)), None)
        title = next((node[keys[k]] for k in keys if k in fallback_read.TITLE_KEYS
                      and isinstance(node[keys[k]], str) and len(node[keys[k]].strip()) >= 3), "")
        if start and title:
            # запись-передача: канал — из её же полей (кроме названия), иначе — сверху
            own = next((_channel_of(str(v), known) for v in node.values()
                        if isinstance(v, (str, int)) and not isinstance(v, bool)
                        and str(v) != title and _channel_of(str(v), known)), "")
            rows.append((own or channel, start.astimezone(zone), " ".join(title.split()),
                         marks_of(node, keys, title)))
        else:
            # запись-канал: в её полях стоит знакомое имя — ниже идут его передачи
            channel = next((_channel_of(v, known) for v in node.values()
                            if isinstance(v, str) and _channel_of(v, known)), channel)
        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value, channel, depth + 1)

    walk(data, "", 0)
    return rows


def _is_json(page: str) -> bool:
    return (page or "").lstrip("﻿ \t\r\n")[:1] in ("{", "[")


def rows_marked(page: str, day: date | None, tz: str | None, names, word=None) -> list[tuple]:
    """М3, М4, К1: строки страницы общим способом — [(канал или '', начало,
    название, пометки эфира по способам)]. `names` — имена знакомых каналов,
    `word` — слово эфира в куске текста (`_live_word`); не дано — пометки не
    читаются. Пояс задан криво либо у страницы с разметкой неизвестен день —
    пусто."""
    known = _known(names)
    if not known:
        return []
    try:
        zone = ZoneInfo(tz or "UTC")
    except Exception:                                  # noqa: BLE001 — пояс задан криво
        return []
    if _is_json(page):
        return _rows_json(page, zone, known, word)
    if day is None or not tz:
        return []
    return _rows_html(page, day, zone, known, word)


def rows(page: str, day: date | None, tz: str | None, names) -> list[tuple[str, datetime, str]]:
    """М3, М4: строки страницы общим способом без пометок — [(канал или '',
    начало, название)]."""
    return [row[:3] for row in rows_marked(page, day, tz, names)]


def _title_key(title: str) -> str:
    """Название для сверки: без служебной записи знаков (`&#039;`, `\\'`),
    только буквы и цифры."""
    return label.key(_html.unescape(title or "").replace("\\", ""))


def same_title(a: str, b: str) -> bool:
    """Одно ли название: начало одного (первые 8 букв и цифр) стоит в другом."""
    x, y = _title_key(a), _title_key(b)
    if not x or not y:
        return False
    return x[:8] in y or y[:8] in x


def _own(programs: list) -> list:
    """Строки своего разборщика, годные для сверки: с каналом и началом."""
    return [p for p in programs or [] if p.start is not None and (p.channel_raw or "").strip()]


def _index(triples) -> dict[tuple[str, datetime], list[str]]:
    """{(канал, начало по UTC): [названия]} — для сверки строк."""
    out: dict[tuple[str, datetime], list[str]] = {}
    for channel, start, title in triples:
        if channel:
            out.setdefault((channel, start.astimezone(timezone.utc)), []).append(title or "")
    return out


def differs(programs: list, got: list[tuple[str, datetime, str]]) -> tuple[int, int]:
    """М1: (сколько строк своего разборщика общий способ не дал, сколько
    лишних строк знакомых каналов он дал внутри окна времени страницы)."""
    own = [((p.channel_raw or "").strip(), p.start, p.title or "") for p in _own(programs)]
    if not own:
        return 0, 0
    theirs, mine = _index(got), _index(own)
    missing = sum(1 for channel, start, title in own
                  if not any(same_title(title, t)
                             for t in theirs.get((channel, start.astimezone(timezone.utc)), [])))
    first, last = min(s for _, s, _ in own), max(s for _, s, _ in own)
    extra = sum(1 for channel, start, title in got
                if channel and first <= start <= last
                and not any(same_title(title, t)
                            for t in mine.get((channel, start.astimezone(timezone.utc)), [])))
    return missing, extra


def _live_ways(own: list, got: list[tuple], word, ways) -> tuple[list[str], int]:
    """К2: (способы, которыми пометка эфира общего способа совпала с пометкой
    своего разборщика у ВСЕХ его строк; сколько у него строк с эфиром)."""
    index: dict[tuple[str, datetime], list[tuple[str, dict]]] = {}
    for channel, start, title, marks in got:
        if channel:
            index.setdefault((channel, start.astimezone(timezone.utc)), []).append((title, marks))
    good, live_rows = set(ways), 0
    for p in own:
        live = bool(word(p.live_raw or ""))
        live_rows += live
        # на странице бывает две строки одного канала и времени (сетка для
        # телефона и для компьютера) — сверяем с любой из них
        same = [m for t, m in index.get(((p.channel_raw or "").strip(), p.start.astimezone(timezone.utc)), [])
                if same_title(p.title or "", t)]
        if not same:
            return [], live_rows
        good = {way for way in good if any(bool(marks.get(way)) == live for marks in same)}
        if not good:
            break
    return [way for way in ways if way in good], live_rows


def _pair_key(text: str):
    """К4: пара из текста для сверки — (сторона, сторона) буквами и цифрами; пары нет — None."""
    from . import live
    pair = live.split_teams(text or "")
    if not pair:
        return None
    return tuple(label.key(side) for side in pair)


def _pair_ways(own: list, got: list[tuple], word) -> tuple[list[str], int]:
    """К4: (способы, которыми пара из названия общего способа совпала с
    парой своего разборщика у ВСЕХ его строк с эфиром и парой; сколько таких
    строк). Пара своего разборщика — из поля пары, а если оно пусто — из
    названия, как её читает отсев (`live.check`)."""
    index: dict[tuple[str, datetime], list[str]] = {}
    for channel, start, title, _marks in got:
        if channel:
            index.setdefault((channel, start.astimezone(timezone.utc)), []).append(title)
    good, pair_rows = list(PAIR_WAYS), 0
    for p in own:
        if not word(p.live_raw or ""):
            continue
        target = _pair_key((p.match_raw or "").strip() or p.title or "")
        if target is None:
            continue
        titles = [t for t in index.get(((p.channel_raw or "").strip(), p.start.astimezone(timezone.utc)), [])
                  if same_title(p.title or "", t)]
        if not titles:
            return [], pair_rows
        pair_rows += 1
        good = [way for way in good if any(_pair_key(PAIR_WAYS[way](title)) == target for title in titles)]
        if not good:
            break
    return good, pair_rows


def _hours(start: datetime, day: date, zone) -> float:
    """Сколько часов от начала дня страницы (в поясе сайта) до начала передачи."""
    midnight = datetime(day.year, day.month, day.day, tzinfo=zone)
    return (start - midnight).total_seconds() / 3600


def shadow(memory: dict, verdicts: dict, domain: str, url: str, page: str,
           day: date | None, tz: str | None, programs: list, also=None) -> bool | None:
    """М1, М2, К2: сверка в тени страницы, которую свой разборщик прочитал.
    `memory` — память страниц (ключ games.json `MANY_KEY`, переходит из
    сбора в сбор), `verdicts` — {ключ: сошлось ли} по страницам ЭТОГО сбора,
    `also` — каналы сайта из списка владельца.
    Возвращает: True — сошлось, False — нет, None — сверять нечего (канал
    один, строк мало, день страницы неизвестен)."""
    own = _own(programs)
    names = {p.channel_raw.strip() for p in own}
    if len(names) < 2 or len(own) < MANY_MIN or day is None:
        return None
    key = fallback_read.page_key(domain, url)
    old = memory.get(key) if isinstance(memory.get(key), dict) else {}
    names |= set(old.get(NAMES) or [])                 # М2: имена копятся
    got: list[tuple] = []
    try:
        word = _live_word(domain)
        got = rows_marked(page, day, tz, names | set(also or []), word)
        ok = differs(own, [row[:3] for row in got]) == (0, 0)
    except Exception:                                  # noqa: BLE001 — тень сбор не роняет
        ok = False
    if not ok or verdicts.get(key) is False:
        verdicts[key] = False
        memory.pop(key, None)
        return ok
    zone = ZoneInfo(tz or "UTC")                       # пояс верный: `rows_marked` выше с ним отработал
    hours = [_hours(p.start, day, zone) for p in own]
    window = [math.floor(min(hours)), math.ceil(max(hours))]
    ways, live_rows = _live_ways(own, got, word, WAYS_JSON if _is_json(page) else WAYS_HTML)   # К2
    pairs, pair_rows = _pair_ways(own, got, word)                                              # К4
    if verdicts.get(key):
        # вторая и следующие страницы ключа в этом сборе — окно расширяется,
        # способ пометки обязан сойтись на всех страницах
        if isinstance(old.get(WINDOW), list) and len(old[WINDOW]) == 2:
            window = [min(window[0], old[WINDOW][0]), max(window[1], old[WINDOW][1])]
        before = old.get(LIVE) if isinstance(old.get(LIVE), dict) else {}
        ways = [way for way in ways if way in (before.get(LIVE_WAYS) or [])]
        live_rows += int(before.get(LIVE_ROWS) or 0)
        pairs = [way for way in pairs if way in (before.get(PAIR) or [])]
        pair_rows += int(before.get(PAIR_ROWS) or 0)
    memory[key] = {NAMES: sorted(names), WINDOW: window,
                   LIVE: {LIVE_WAYS: ways, LIVE_ROWS: live_rows, PAIR: pairs, PAIR_ROWS: pair_rows}}
    verdicts[key] = True
    return True


def live_way(remembered) -> str:
    """К3: способ пометки эфира, которому на этой странице можно верить; пусто — нет такого."""
    mark = remembered.get(LIVE) if isinstance(remembered, dict) else None
    if not isinstance(mark, dict) or not mark.get(LIVE_WAYS) or int(mark.get(LIVE_ROWS) or 0) < LIVE_MIN:
        return ""
    return str(mark[LIVE_WAYS][0])


def pair_way(remembered) -> str:
    """К4: способ вынуть пару из названия, которому на этой странице можно верить; пусто — нет."""
    mark = remembered.get(LIVE) if isinstance(remembered, dict) else None
    if not live_way(remembered) or not mark.get(PAIR) or int(mark.get(PAIR_ROWS) or 0) < LIVE_MIN:
        return ""
    way = str(mark[PAIR][0])
    return way if way in PAIR_WAYS else ""


def read(page: str, day: date | None, tz: str | None, remembered, url: str = "",
         also=None, domain: str = "") -> list[Program]:
    """М5, К3: строки страницы общим способом — как строки запасного чтения
    книги 125, с пометкой `fallback_read.MARK` и без пары. `remembered` —
    запись памяти страницы (`NAMES`, `WINDOW`, `LIVE`), `also` — каналы сайта
    из списка владельца, `domain` — сайт (язык слов эфира). Пометка эфира
    читается, только если её способ сошёлся в тени (`live_way`): тогда у
    каждой строки стоит `fallback_read.LIVE_SEEN`. Строка без канала, за
    окном времени и повтор той же строки не берутся."""
    if not isinstance(remembered, dict) or day is None:
        return []
    window = remembered.get(WINDOW)
    way = live_way(remembered)
    by_pair = pair_way(remembered)
    try:
        got = rows_marked(page, day, tz, set(remembered.get(NAMES) or []) | set(also or []),
                          _live_word(domain) if way else None)
        zone = ZoneInfo(tz or "UTC")
    except Exception:                                  # noqa: BLE001 — страница не читается
        return []
    out: list[Program] = []
    taken = set()
    for channel, start, title, marks in got:
        if not channel:
            continue
        if isinstance(window, list) and len(window) == 2 and not (
                window[0] <= _hours(start, day, zone) <= window[1]):
            continue
        same = (channel, start.astimezone(timezone.utc), _title_key(title))
        if same in taken:
            continue
        taken.add(same)
        live_mark = (marks.get(way) or "") if way else ""
        pair = " "                                         # З4: пары нет — её ищет эталон
        whole = title
        title, league = fallback_read.cut_tail(title)
        if live_mark and by_pair:                          # К4
            found = PAIR_WAYS[by_pair](whole).strip()
            if _pair_key(found) is not None:
                pair = found
                if "двоеточия" in by_pair and _after_colon(whole) != whole:
                    league = _COLON.split(whole, 1)[0].strip()
        extra = {fallback_read.MARK: True, "day": start.date().isoformat()}
        if way:
            extra[fallback_read.LIVE_SEEN] = way
        out.append(Program(channel_raw=channel, title=title[:300], start=start,
                           raw_time=start.strftime("%H:%M"), match_raw=pair[:200],
                           live_raw=live_mark,
                           league_raw=league[:120], source_url=url, extra=extra))
    return out

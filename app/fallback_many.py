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
верим НЕ ПО СПИСКУ сайтов, а по проверке «в тени» на каждом сборе.

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
"""
from __future__ import annotations

import html as _html
import json
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import fallback_read
from .parsers import Program, label

#: ключ games.json: {ключ страницы: {`NAMES`: [имена каналов], `WINDOW`:
#: [с какого часа, по какой час от начала дня страницы]}} — страницы с
#: несколькими каналами, которые общий способ в тени прочитал так же, как
#: свой разборщик
MANY_KEY = "страницы_с_каналами"
NAMES = "каналы"
WINDOW = "окно"
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


def _rows_html(page: str, day: date, zone, known: dict[str, str]) -> list[tuple[str, datetime, str]]:
    """М3: [(канал или '', начало, название)] со страницы с разметкой."""
    tokens = _tokens(page)
    rows: list[tuple[str, datetime, str]] = []
    channel, shift, last = "", 0, None
    for i, (is_text, text) in enumerate(tokens):
        name = _channel_of(text, known)
        if name:
            if name != channel:                      # новый канал — сутки считаем заново
                channel, shift, last = name, 0, None
            continue
        if not is_text:
            continue
        m = fallback_read._TIME.match(text)
        if not m:
            continue
        title = m["rest"].strip()
        if not title:
            nxt = next((t for is_t, t in tokens[i + 1:i + 1 + _TITLE_REACH] if is_t), "")
            if nxt and not fallback_read._TIME.match(nxt) and not _channel_of(nxt, known):
                title = nxt
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
    return rows


def _rows_json(page: str, zone, known: dict[str, str]) -> list[tuple[str, datetime, str]]:
    """М4: [(канал или '', начало, название)] из служебного ответа."""
    try:
        data = json.loads(page)
    except ValueError:
        return []
    rows: list[tuple[str, datetime, str]] = []

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
            rows.append((own or channel, start.astimezone(zone), " ".join(title.split())))
        else:
            # запись-канал: в её полях стоит знакомое имя — ниже идут его передачи
            channel = next((_channel_of(v, known) for v in node.values()
                            if isinstance(v, str) and _channel_of(v, known)), channel)
        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value, channel, depth + 1)

    walk(data, "", 0)
    return rows


def rows(page: str, day: date | None, tz: str | None, names) -> list[tuple[str, datetime, str]]:
    """М3, М4: строки страницы общим способом — [(канал или '', начало,
    название)]. `names` — имена знакомых каналов. Пояс задан криво либо у
    страницы с разметкой неизвестен день — пусто."""
    known = _known(names)
    if not known:
        return []
    try:
        zone = ZoneInfo(tz or "UTC")
    except Exception:                                  # noqa: BLE001 — пояс задан криво
        return []
    if (page or "").lstrip("﻿ \t\r\n")[:1] in ("{", "["):
        return _rows_json(page, zone, known)
    if day is None or not tz:
        return []
    return _rows_html(page, day, zone, known)


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


def _hours(start: datetime, day: date, zone) -> float:
    """Сколько часов от начала дня страницы (в поясе сайта) до начала передачи."""
    midnight = datetime(day.year, day.month, day.day, tzinfo=zone)
    return (start - midnight).total_seconds() / 3600


def shadow(memory: dict, verdicts: dict, domain: str, url: str, page: str,
           day: date | None, tz: str | None, programs: list, also=None) -> bool | None:
    """М1, М2: сверка в тени страницы, которую свой разборщик прочитал.
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
    try:
        ok = differs(own, rows(page, day, tz, names | set(also or []))) == (0, 0)
    except Exception:                                  # noqa: BLE001 — тень сбор не роняет
        ok = False
    if not ok or verdicts.get(key) is False:
        verdicts[key] = False
        memory.pop(key, None)
        return ok
    zone = ZoneInfo(tz or "UTC")                       # пояс верный: `rows` выше с ним отработал
    hours = [_hours(p.start, day, zone) for p in own]
    window = [math.floor(min(hours)), math.ceil(max(hours))]
    if verdicts.get(key) and isinstance(old.get(WINDOW), list) and len(old[WINDOW]) == 2:
        # вторая и следующие страницы ключа в этом сборе — окно расширяется
        window = [min(window[0], old[WINDOW][0]), max(window[1], old[WINDOW][1])]
    memory[key] = {NAMES: sorted(names), WINDOW: window}
    verdicts[key] = True
    return True


def read(page: str, day: date | None, tz: str | None, remembered, url: str = "",
         also=None) -> list[Program]:
    """М5: строки страницы общим способом — как строки запасного чтения
    книги 125: без пометки эфира и без пары, с пометкой `fallback_read.MARK`.
    `remembered` — запись памяти страницы (`NAMES`, `WINDOW`), `also` —
    каналы сайта из списка владельца. Строка без
    канала, за окном времени и повтор той же строки не берутся."""
    if not isinstance(remembered, dict) or day is None:
        return []
    window = remembered.get(WINDOW)
    try:
        got = rows(page, day, tz, set(remembered.get(NAMES) or []) | set(also or []))
        zone = ZoneInfo(tz or "UTC")
    except Exception:                                  # noqa: BLE001 — страница не читается
        return []
    out: list[Program] = []
    taken = set()
    for channel, start, title in got:
        if not channel:
            continue
        if isinstance(window, list) and len(window) == 2 and not (
                window[0] <= _hours(start, day, zone) <= window[1]):
            continue
        same = (channel, start.astimezone(timezone.utc), _title_key(title))
        if same in taken:
            continue
        taken.add(same)
        title, league = fallback_read.cut_tail(title)
        out.append(Program(channel_raw=channel, title=title[:300], start=start,
                           raw_time=start.strftime("%H:%M"), match_raw=" ", live_raw="",
                           league_raw=league[:120], source_url=url,
                           extra={fallback_read.MARK: True, "day": start.date().isoformat()}))
    return out

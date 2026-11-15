"""Запасное чтение страницы (книга 125, этап 3 плана «сайт не перестаёт
разбираться», слова владельца 14.11: «это никак не предвидеть, чтоб даже в
таких ситуациях сайт смог разбирать?»).

Случай: сайт сменил устройство страницы, свой разборщик возвращает ноль
строк, хотя страница открывается и расписание на ней видно глазами
(football-tv.ru в сборе 14.11: 64 строки «время — матч», разборщик дал 0).

ПРАВИЛА (что случилось → что делаем):
  З1. Зовём, только когда страница открылась («расписание есть»), а свой
      разборщик вернул ноль строк. Разборщик работает — запасное чтение молчит.
  З2. Читаем страницу «глазами»: убираем разметку, ищем строки, начинающиеся
      со времени («21:45 Испания — Англия» либо время и подпись соседними
      строками). День и часовой пояс известны из запроса страницы.
  З3. Канал страницы берём из ПАМЯТИ: пока разборщик работал, сбор
      запоминал, какой канал лежит на какой странице (`remember`, ключ
      `PAGES_KEY` в games.json). Канал неизвестен (в памяти нет, в запросе
      не назван) — строки на витрину не идут, только в счёт (З5).
  З4. Строка запасного чтения идёт дальше БЕЗ пометки эфира и без пары:
      в ленту она попадёт, только если пару из подписи подтвердил эталон на
      это время (`pipeline.ask_reference`). Мусор со страницы не пройдёт.
  З5. Счёт по сайтам — в games.json (`COUNT_KEY`): сколько страниц не
      прочитал свой разборщик, сколько строк увидело запасное чтение, знали
      ли канал. Сервер пишет об этом ОДНУ строку на сайт в сутки (`after_import`):
      разборщик пора поправить. Мелочь (меньше `MIN_ROWS` строк) не в счёт:
      пустая страница канала без матчей — обычное дело.
  З6. Уведомление — только по делу (проверка на сборе 14.11: у bbc.co.uk,
      movistarplus.es, tv3.lt, poverkhnost.tv часть страниц разборщик не
      читает НАМЕРЕННО — это каналы, которых нет в списке владельца).
      Сообщаем, когда верно одно из двух: свой разборщик не дал ни одной
      строки по ВСЕМУ сайту (`свой_разборщик` = 0) либо замолчала страница,
      которая раньше читалась (канал известен из памяти). Иначе — только счёт.
  З8. Страница без разметки (служебный ответ — список записей с полями):
      в каждой записи ищем поле начала и поле названия (`read_json`).
  З9. Свой разборщик УПАЛ на странице (сайт сменил устройство ответа) —
      это тот же случай, что «ноль строк»: причина идёт в «Не разобрано»,
      а страницу читает запасное чтение (`parse_live`).
  З7. Сайт с ОДНИМ каналом может назвать его сам: константа `CHANNEL` в
      модуле своего разборщика (и `TZ` — пояс), `declared`. Тогда запасное
      чтение для него — штатный второй способ, а не признак поломки: канал
      известен сразу, в счёт и в уведомления такие страницы не идут.
      Случай: football-tv.ru — разборщик читает только карточки анонсов
      прямых эфиров; когда анонсов нет, на странице остаётся суточная сетка
      с повторами (66 строк в сборе 14.11) — эфир в ней отличит эталон.
"""
from __future__ import annotations

import html as _html
import sys
import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .parsers import Program

#: ключ games.json: {ключ страницы: канал} — память «какой канал на странице»
PAGES_KEY = "каналы_страниц"
#: ключ games.json: {сайт: {страниц, строк, канал_известен}}
COUNT_KEY = "запасное_чтение"
#: пометка строки: её дало запасное чтение
MARK = "запасное_чтение"
#: З5: меньше строк со временем на сайт — не сообщаем
MIN_ROWS = 5
#: настройка базы: {сайт: день} — о ком и когда уже сообщили
NOTED_KEY = "fallback_noted"
WHO = "запасное чтение"

_SCRIPT = re.compile(r"(?is)<(script|style|noscript)\b.*?</\1>")
_TAG = re.compile(r"<[^>]+>")
#: время в начале строки: «21:45», «9.30»; дальше — подпись или конец строки
#: после минут не идёт «.цифра» или «:цифра»: «14.11.2026 в 22:30» — дата, а
#: «21:45:00» — время с секундами, строкой расписания их не считаем (проверка
#: на странице football-tv.ru 15.11: даты анонсов читались как время «14:11»)
_TIME = re.compile(r"^(?P<h>[01]?\d|2[0-3])[:.](?P<m>[0-5]\d)(?![\d]|[.:]\d)\s*[-–—|]?\s*(?P<rest>.*)$")
#: даты и длинные числа в адресе — день и метки времени: у одной и той же
#: страницы канала они меняются каждый сбор
_VARIABLE = re.compile(r"\d{4}[-/.]\d{2}[-/.]\d{2}|\d{8,}")


def page_key(domain: str, url: str) -> str:
    """Ключ страницы для памяти каналов: сайт + адрес без дат и меток времени."""
    return f"{(domain or '').lower()}|{_VARIABLE.sub('#', url or '')}"


def remember(memory: dict, domain: str, url: str, programs: list) -> None:
    """З3: разборщик страницу прочитал — запоминаем её канал, если он на
    странице ОДИН (на общей странице с несколькими каналами помнить нечего)."""
    channels = {(p.channel_raw or "").strip() for p in programs or []}
    channels.discard("")
    if len(channels) == 1:
        memory[page_key(domain, url)] = channels.pop()


def declared(parse) -> tuple[str, str]:
    """З7: (канал, пояс), которые назвал модуль своего разборщика сайта —
    константы `CHANNEL` и `TZ`; не назвал — пустые строки."""
    module = sys.modules.get(getattr(parse, "__module__", "") or "")
    channel = getattr(module, "CHANNEL", "") if module else ""
    zone = getattr(module, "TZ", "") if module else ""
    return (channel if isinstance(channel, str) else "",
            zone if isinstance(zone, str) else "")


def lines_of(page: str) -> list[str]:
    """Видимый текст страницы по строкам — без скриптов, стилей и разметки."""
    text = _TAG.sub("\n", _SCRIPT.sub(" ", page or ""))
    return [line for line in (" ".join(x.split()) for x in _html.unescape(text).splitlines())
            if line]


#: З8 (книга 128): поля записи служебного ответа, в которых лежит НАЧАЛО
#: передачи и её НАЗВАНИЕ. Имя поля сравнивается без регистра, «_» и «-».
#: Списки собраны по ответам наших же сайтов (ipko.tv `show_start`, azam
#: `eventStartUtc`, tvtid `start`, cyta `startTime` …); новое имя — сюда
START_KEYS = frozenset((
    "start", "starttime", "startdate", "startdatetime", "starttimeutc", "startutc", "utcstart",
    "starts", "startsat", "begin", "begintime", "from", "fromtime", "showstart", "eventstartutc",
    "eventstart", "broadcaststart", "airtime", "airdate", "datetime", "timestamp", "time",
    "datestart", "starttimestamp", "pocetak", "anfang", "inicio", "debut"))
TITLE_KEYS = frozenset((
    "title", "name", "programname", "programtitle", "programme", "showname", "showtitle",
    "eventname", "eventtitle", "headline", "label", "originaltitle", "naziv", "titel", "titulo"))
ABOUT_KEYS = frozenset(("description", "summary", "subtitle", "synopsis", "shortdescription",
                        "episodetitle", "opis", "info"))
#: предел записей из одного ответа и глубины обхода — защита от огромных ответов
JSON_ROWS = 5000
JSON_DEPTH = 12


def _plain_key(key) -> str:
    return re.sub(r"[_\-\s]", "", str(key)).lower()


def moment(value, zone) -> datetime | None:
    """З8: начало передачи из значения поля. Число (или строка из цифр):
    секунды эпохи (10 знаков) либо миллисекунды (13 знаков). Строка — дата
    и время в записи ISO («2026-11-15T21:45:00Z»); без пояса — пояс сайта.
    Не похоже на время — None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, (int, float)):
        if 1_000_000_000 <= value < 5_000_000_000:
            return datetime.fromtimestamp(value, tz=ZoneInfo("UTC"))
        if 1_000_000_000_000 <= value < 5_000_000_000_000:
            return datetime.fromtimestamp(value / 1000, tz=ZoneInfo("UTC"))
        return None
    if not isinstance(value, str) or len(value) < 16 or not re.match(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", value):
        return None
    try:
        got = datetime.fromisoformat(value.strip().replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return None
    return got if got.tzinfo else got.replace(tzinfo=zone)


def read_json(page: str, tz: str | None, channel: str, url: str = "") -> list[Program]:
    """З8: служебный ответ без разметки — список записей с полями. В каждой
    записи (на любой глубине) ищем поле начала (`START_KEYS`) и поле
    названия (`TITLE_KEYS`); есть оба — это передача. Описание
    (`ABOUT_KEYS`) идёт следом: в нём бывает пара команд. Дальше — как у
    обычной страницы (З4): без пометки эфира, в ленту — только через эталон."""
    try:
        data = json.loads(page)
        zone = ZoneInfo(tz or "UTC")
    except Exception:                                  # noqa: BLE001 — не JSON или кривой пояс
        return []
    out: list[Program] = []

    def walk(node, depth: int) -> None:
        if depth > JSON_DEPTH or len(out) >= JSON_ROWS:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return
        if not isinstance(node, dict):
            return
        keys = {_plain_key(k): k for k in node}
        start = next((moment(node[keys[k]], zone) for k in keys
                      if k in START_KEYS and moment(node[keys[k]], zone)), None)
        title = next((node[keys[k]] for k in keys if k in TITLE_KEYS
                      and isinstance(node[keys[k]], str) and len(node[keys[k]].strip()) >= 3), "")
        if start and title:
            about = next((node[keys[k]] for k in keys if k in ABOUT_KEYS
                          and isinstance(node[keys[k]], str)), "")
            title, league = cut_tail(" ".join(title.split()))
            local = start.astimezone(zone)
            out.append(Program(channel_raw=channel, title=title[:300], start=start,
                               raw_time=local.strftime("%H:%M"), match_raw=" ", live_raw="",
                               league_raw=league[:120], description=" ".join(about.split())[:300],
                               source_url=url, extra={MARK: True, "day": local.date().isoformat()}))
        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value, depth + 1)

    walk(data, 0)
    return out


def read(page: str, day: date | None, tz: str | None, channel: str,
         url: str = "") -> list[Program]:
    """З2, З4: строки «время — подпись» со страницы. Подпись — остаток строки
    после времени, а если его нет — следующая строка (не время). Время,
    ушедшее назад больше чем на 6 часов, — уже следующие сутки (ночная часть
    сетки). Без дня или пояса читать не из чего — пусто.
    З8: страница — служебный ответ без разметки (начинается с «{» или «[»)
    — её читает `read_json`: время там полное, день не нужен."""
    if (page or "").lstrip("﻿ \t\r\n")[:1] in ("{", "["):
        return read_json(page, tz, channel, url)
    if day is None or not tz:
        return []
    try:
        zone = ZoneInfo(tz)
    except Exception:                                  # noqa: BLE001 — пояс задан криво
        return []
    lines = lines_of(page)
    out: list[Program] = []
    shift, last = 0, None
    for i, line in enumerate(lines):
        m = _TIME.match(line)
        if not m:
            continue
        title = m["rest"].strip()
        if not title and i + 1 < len(lines) and not _TIME.match(lines[i + 1]):
            title = lines[i + 1]
        if len(title) < 3:
            continue
        minutes = int(m["h"]) * 60 + int(m["m"])
        if last is not None and minutes < last - 360:
            shift += 1
        last = minutes
        start = datetime(day.year, day.month, day.day, int(m["h"]), int(m["m"]),
                         tzinfo=zone) + timedelta(days=shift)
        title, league = cut_tail(title)
        out.append(Program(channel_raw=channel, title=title[:300], start=start,
                           raw_time=f"{int(m['h']):02d}:{m['m']}", match_raw=" ",
                           league_raw=league[:120],
                           live_raw="", source_url=url,
                           extra={MARK: True, "day": start.date().isoformat()}))
    return out


#: знак между командами в подписи — для `cut_tail`
_PAIR_SIGN = re.compile(r"\s[-–—]\s|\s(?:vs\.?|v|x)\s", re.I)
#: точка, после которой идёт новая часть подписи (турнир, сезон)
_DOT = re.compile(r"(?<=\w)\.\s+(?=\S)")


def cut_tail(title: str) -> tuple[str, str]:
    """Подпись «Асколи – Палермо. Итальянская серия Б. Сезон 26/27» →
    («Асколи – Палермо», «Итальянская серия Б. Сезон 26/27»): хвост после
    точки — турнир, а не часть имени второй команды. Правила:
      1. режем только подпись, где до точки уже стоит знак пары;
      2. точка после короткого слова (до трёх букв: «St.», «FC.», инициал
         «G.») — сокращение, не конец: ищем следующую;
      3. подходящей точки нет — подпись остаётся целой, хвост пустой."""
    sign = _PAIR_SIGN.search(title or "")
    if not sign:
        return title, ""
    for dot in _DOT.finditer(title, sign.end()):
        word = re.split(r"\s", title[:dot.start()])[-1]
        if len(word) > 3:
            return title[:dot.start()].strip(), title[dot.end():].strip()
    return title, ""


def count(counts: dict, site: str, rows: int, channel: str) -> None:
    """З5: страница сайта, не прочитанная своим разборщиком, — в счёт."""
    rec = counts.setdefault(site, {"страниц": 0, "строк": 0, "канал_известен": 0})
    rec["страниц"] += 1
    rec["строк"] += rows
    rec["канал_известен"] += 1 if channel else 0


def own_rows(counts: dict, parsed: dict) -> None:
    """З6: дописать в счёт, сколько строк дал СВОЙ разборщик по всему сайту
    (`parsed` — «разобрано» сбора)."""
    for site, rec in (counts or {}).items():
        rec["свой_разборщик"] = int((parsed or {}).get(site) or 0)


def words(counts: dict) -> dict[str, str]:
    """З5: {сайт: строка уведомления} — только где строк не меньше `MIN_ROWS`."""
    out = {}
    for site, rec in sorted((counts or {}).items()):
        if not isinstance(rec, dict) or int(rec.get("строк") or 0) < MIN_ROWS:
            continue
        if int(rec.get("свой_разборщик") or 0) > 0 and not rec.get("канал_известен"):
            continue                                              # З6
        if rec.get("канал_известен"):
            tail = ("канал страницы известен из прошлых сборов — матчи, которые подтвердил "
                    "эталон, на витрину идут")
        else:
            tail = "канал страницы неизвестен — на витрину эти строки не идут"
        out[site] = (f"{site}: свой разборщик не прочитал {rec['страниц']} стр. (они "
                     f"открываются), запасное чтение видит на них {rec['строк']} строк "
                     f"расписания; {tail}. Сайт сменил устройство страницы — разборщик "
                     f"нужно поправить")
    return out


def after_import(conn, data: dict, today: str) -> list[str]:
    """З5 на сервере (зовёт `games_import.py`): строка в «Прогоны» — одна на
    сайт в сутки (`today` — день по Киеву). Возвращает написанные строки."""
    from . import db, watch
    lines = words(data.get(COUNT_KEY) or {})
    if not lines:
        return []
    try:
        noted = json.loads(db.get_setting(conn, NOTED_KEY) or "{}")
    except ValueError:
        noted = {}
    said = []
    for site, line in lines.items():
        if noted.get(site) == today:
            continue
        watch.note(conn, line, who=WHO)
        noted[site] = today
        said.append(line)
    if said:
        db.set_setting(conn, NOTED_KEY, json.dumps(noted, ensure_ascii=False))
    return said

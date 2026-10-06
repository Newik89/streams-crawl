# -*- coding: utf-8 -*-
"""flashscore.mobi — ЭТАЛОН: весь мировой футбол дня одной страницей.

Владелец назвал flashscore лучшим справочником имён и времени (02–02.09).
Полноценный фид (`…flashscore.ninja/…/x/feed/…`) пускает только жилые IP —
даже с верным ключом `x-fsign` дата-центрам отвечает 401. Зато упрощённая
версия `www.flashscore.mobi` отдаётся серверу обычным запросом: ~370 матчей
дня, лиги заголовками, время, статус и ID матча.

    <h4>AUSTRIA: Bundesliga …</h4>
    <span>20:30</span>Salzburg - SK Rapid <a href="/match/YmWtmp0k/" class="sched">-</a>
    <span class="live">8'</span>… <a … class="live">0-1</a>   — идёт сейчас
    <a … class="fin">7-2</a>                                  — закончен

Пояс — CET/CEST (`Europe/Paris`): летом +2 (сверено по Зальцбург — Рапид
с нашей базой 02.09, страница показывала 20:30 = 21:30 Киева), зимой +1 —
перевод стрелок ZoneInfo делает сам (C1 аудита, 12.09). День листается `/?d=1`.

Роль на разборе особая: строки НЕ идут на витрину — `parse_live.py`
складывает их в эталонный набор (пары + время + канонические английские
написания), которым подтверждается «угаданный» live и сверяются имена.

**Дата строки (07.10, сбор #205).** Страница дня захватывает края соседних
суток: «09.10» в блоке Аргентины даёт `19:30, 23:00, 00:30` — последний
матч (Instituto — Boca Juniors) уже 10.10; «10.10» начинает тот же блок с
`23:00` (это ещё 09.10) и кончает `00:15` (уже 11.10). Раньше всем строкам
ставилась дата страницы — в эталоне у одного `fs_id` выходило два времени
с разницей в сутки, и живой эфир 10.10 снимался «повтором уже сыгранного
матча 09.10». Правила теперь такие:

1. Внутри блока лиги матчи идут строго по времени начала: любой шаг
   назад — переход через полночь (`daytime.walk_day`, `overlap=1`).
2. Страница дня D показывает матчи с `ОКНО_С` накануне до `ОКНО_ДО`
   следующих суток (сверено по общим матчам соседних страниц #205).
   Блок, начатый хвостом прошлого вечера, узнаётся по окну
   (`walk_day(window=…)`): берётся прочтение, при котором больше строк
   в окне; поровну — блок начат в день страницы.
3. Один матч на двух соседних страницах — одно время (`settle`): он
   стоит у полуночи между ними. Так решаются и блоки, которых правило 2
   не различает (одинокое `00:30` — это ночь дня страницы или следующей?).

Локали (`LOCALES`) размечены так же и идут тем же разбором; их время
эталону не нужно, но даты они получают по тем же правилам.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .. import daytime
from . import Program, register

DOMAIN = "flashscore.mobi"
TZ = "Europe/Paris"                     # CET/CEST — см. шапку

#: языковые версии эталона (этап 6е, A2): те же матчи и те же `fs_id`, а
#: имена — как их пишет местная пресса: `Τζένοα`, `Дженоа`, `Genova`. По
#: `fs_id` словарь учит «местное → английское» без угадывания по буквам.
#: Проба 03.09 из GitHub (12 адресов): открылись эти 9; `m.flashscore.co.il`
#: и `m.flashscore.rs` не существуют — иврит и сербский идут таблицами
#: экзонимов. Значение — язык, если страница его не назвала в `<html lang>`.
#: Время у локалей местное и нам не нужно — берём только имена.
LOCALES = {
    "m.flashscore.gr": "el", "m.flashscore.bg": "bg", "m.eredmenyek.com": "hu",
    "m.flashscore.ro": "ro", "m.flashscore.com.tr": "tr", "m.flashscore.pl": "pl",
    "m.flashscore.ru": "ru", "m.flashscore.ua": "uk", "m.livesport.cz": "cs",
    # вторая проба 03.09: сербохорватский — арена-сетки, mojtv, rtcg, rtrs
    # пишут именно так; иврита и сербской кириллицы у livesport в mobi нет
    "m.rezultati.com": "hr",
    # третья проба 25.09 (идея владельца: «языки источников знаем — пусть
    # словарь заполняется сам»): проверены с сервера, все отдали расписание.
    # Норвежского, албанского и ивритского у flashscore в mobi нет вовсе —
    # `flashscore.co.il` уводит на международную версию, их написания
    # по-прежнему ведём руками в `data/aliases.json`
    "m.flashscore.sk": "sk", "m.flashscore.de": "de", "m.flashscore.pt": "pt",
    "m.flashscore.it": "it", "m.flashscore.fr": "fr", "m.flashscore.es": "es",
    "m.flashscore.nl": "nl", "m.flashscore.se": "sv", "m.flashscore.dk": "da",
}

_ZONE = ZoneInfo(TZ)
#: окно страницы дня D, минуты (шапка, правило 2): с `ОКНО_С` дня D-1 до
#: `ОКНО_ДО` дня D+1. По #205 оно 23:00 … 01:00: общие матчи соседних
#: страниц стоят в 23:00–00:45, блок «10.10» уже не показывает 01:00
#: 11.10 (MEXICO: Primera Premier). Окно шире (22:00 … 02:00) проверено и
#: хуже: блок «12.10» `23:00, 01:15` (Гондурас, Панама) читается в обе
#: стороны, и 01:15 уезжало на 13.10. Замерено летом (CEST) — после
#: перевода часов 25.10 сверить заново (`scripts/test_reference.py`)
ОКНО_С = 23 * 60
ОКНО_ДО = 1 * 60
#: полдень (часы страницы): матч, стоящий на страницах двух соседних дней,
#: идёт у полуночи между ними — раньше полудня это ночь второго дня,
#: позже — вечер первого (правило 3, `settle`)
ПОЛДЕНЬ = 12
#: шаг назад по времени внутри блока, который уже считается полуночью:
#: сайт сортирует матчи лиги по началу, наложений у него не бывает
ПОЛНОЧЬ_ЛЮБОЙ_ШАГ = 1
#: что срезать с краёв пары: пробел, дефис и неразрывный пробел (`&nbsp;`
#: у некоторых локалей приходит самим символом)
_PAIR_EDGE = " - "
#: блок матча: время (или живая минута), пара, ссылка со статусом
#: у ссылки матча бывает хвост запроса (`/match/pdmRhdwH/?s=1` — появился
#: 02.09 и сломал разбор, поймано обкаткой) — берём id до слэша, хвост не важен
_ROW = re.compile(
    r"<span(?: class=\"(?P<live>live)\")?>(?P<time>[^<]{1,7})</span>"
    r"(?P<pair>[^<]{3,120}?)"
    # у языковых версий слово в пути своё: `/match/` (en, el, bg),
    # `/meci/` (ro), `/mac/` (tr) — само слово не важно, важен id за ним
    r"<a href=\"/[a-z\-]+/(?P<id>[^/\"?]+)/(?:\?[^\"]*)?\" "
    r"class=\"(?P<status>sched|live|fin)\"")
_LANG = re.compile(r"<html[^>]* lang=.([A-Za-z-]+).")   # <html lang="el">
_H4 = re.compile(r"<h4>(?P<league>[^<]{3,120})")
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
#: у тенниса и баскетбола к имени приклеен код страны: `Monfils G. (Fra)`,
#: `Liaoning (Chn)`, `Medvedev D. (Wrl)` — сравнению имён он только мешает
_COUNTRY_TAG = re.compile(r"\s*\([A-Za-z]{2,3}\)\s*$")


def _sport_from_url(url: str) -> str:
    """Раздел сайта в адресе — вид спорта (этап 6б: баскет и теннис в
    эталоне). У локалей раздел зовётся по-своему: `basketbol` (tr),
    `kosarka` (hr), `basketbal` (cs), `kosarlabda` (hu)."""
    if any(w in url for w in ("/basketball", "/basketbol", "/kosarka",
                              "/basketbal", "/kosarlabda")):
        return "Basketball"
    if any(w in url for w in ("/tennis", "/tenis", "/tenisz")):
        return "Tennis"
    return "Soccer"


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    day = day or daytime.today(tz or TZ)
    sport = _sport_from_url(url)
    # язык страницы (этап 6е, A2): у локалей `m.flashscore.gr` те же fs_id,
    # что у английской, — по нему словарь учит «Τζένοα» = «Genoa» без
    # угадывания по буквам. Английская отдаёт `en`
    lm = _LANG.search(html[:2000])
    lang = (lm.group(1).split("-")[0].lower() if lm
            else LOCALES.get(urlsplit(url).netloc, "en"))
    # идём по документу: заголовки лиг перемежаются строками матчей;
    # строки собираем блоками лиг — порядок времени живёт внутри блока
    blocks: list[tuple[str, list]] = []
    events = sorted(
        [(m.start(), "h4", m) for m in _H4.finditer(html)] +
        [(m.start(), "row", m) for m in _ROW.finditer(html)])
    for _, kind, m in events:
        if kind == "h4":
            blocks.append((" ".join(m.group("league").split()).strip(), []))
        elif blocks:
            blocks[-1][1].append(m)
        else:
            blocks.append(("", [m]))          # строки до первой лиги
    out: list[Program] = []
    for league, rows in blocks:
        out += _block(league, rows, day, sport, url, lang)
    return out


def _block(league: str, rows: list, day: _date, sport: str, url: str,
           lang: str) -> list[Program]:
    """Строки одного блока лиги; дата каждой — по правилам 1–2 шапки."""
    # у идущего матча вместо времени минута (`8'`): в счёт полуночей она
    # не идёт — пустое время walk_day пропускает, оставляя место в списке
    clock = [m.group("time").strip() if _TIME.match(m.group("time").strip())
             else "" for m in rows]
    moments = daytime.walk_day(clock, day, TZ, overlap=ПОЛНОЧЬ_ЛЮБОЙ_ШАГ,
                               window=(ОКНО_С, ОКНО_ДО))
    out: list[Program] = []
    for m, raw, begin in zip(rows, clock, moments):
        pair = " ".join(m.group("pair").split()).strip(_PAIR_EDGE)
        if " - " not in pair:
            continue
        home, _, away = pair.partition(" - ")
        status = m.group("status")
        if begin is None and status == "live":
            # старт восстанавливать не из чего, ставим «сейчас», допуска
            # эталона (±3 часа) этого достаточно
            begin = datetime.now(tz=_ZONE)
        elif begin is None:
            continue
        home = _COUNTRY_TAG.sub("", home.strip())
        away = _COUNTRY_TAG.sub("", away.strip())
        out.append(Program(
            channel_raw="flashscore", title=pair,
            start=begin,
            raw_time=begin.strftime("%H:%M"),
            league_raw=league[:120],
            sport_raw=sport,
            live_raw="live" if status == "live" else "",
            match_raw=f"{home} - {away}",
            source_url=url,
            extra={"day": begin.date().isoformat(),
                   # день самой страницы и было ли у строки время (а не
                   # живая минута) — для `settle`, правило 3 шапки
                   "page_day": day.isoformat(), "clock": bool(raw),
                   "fs_id": m.group("id"), "status": status, "lang": lang},
        ))
    return out


def settle(programs: list[Program]) -> list[Program]:
    """Один матч (`fs_id`) — одна запись и одно время (правило 3 шапки).

    Страницы соседних дней показывают матчи у полуночи дважды, и прочтения
    могут разойтись на сутки; верхний блок «топ-лиг» повторяет матч ещё раз
    на той же странице. Остаётся первая запись матча (порядок сохраняется),
    время ей ставится по правилам:

    1. Матч на страницах двух СОСЕДНИХ дней D и D+1 стоит у полуночи между
       ними: время страницы раньше `ПОЛДЕНЬ` — это D+1, позже — D.
    2. Иначе — время, которое дало больше записей; поровну — то, что
       совпало с днём своей страницы; дальше — более раннее.
    3. Живая минута вместо времени («сейчас», `clock=False`) в выбор не
       идёт, если у матча есть настоящее время с другой строки.

    Записи без `fs_id` проходят как есть.
    """
    by_id: dict[str, list[Program]] = {}
    for prg in programs:
        fs_id = (prg.extra or {}).get("fs_id") or ""
        if fs_id:
            by_id.setdefault(fs_id, []).append(prg)
    out: list[Program] = []
    for prg in programs:
        fs_id = (prg.extra or {}).get("fs_id") or ""
        if not fs_id:
            out.append(prg)
            continue
        same = by_id.pop(fs_id, None)
        if same is None:
            continue                          # матч уже взят первой записью
        keep = same[0]
        begin = _one_moment(same)
        if begin != keep.start:
            keep.start = begin
            keep.raw_time = begin.strftime("%H:%M")
            keep.extra = {**keep.extra, "day": begin.date().isoformat()}
        out.append(keep)
    return out


def _one_moment(same: list[Program]) -> datetime:
    """Время матча по правилам `settle`."""
    timed = [p for p in same if p.extra.get("clock", True)] or same
    starts = {p.start for p in timed}
    if len(starts) == 1:
        return timed[0].start
    pages = sorted({p.extra.get("page_day") or "" for p in timed})
    # правило 1: две соседние страницы — матч у полуночи между ними
    if len(pages) == 2 and all(pages):
        first, second = (_date.fromisoformat(x) for x in pages)
        if (second - first).days == 1:
            wall = timed[0].start.astimezone(_ZONE)
            on = second if wall.hour < ПОЛДЕНЬ else first
            return datetime(on.year, on.month, on.day, wall.hour, wall.minute,
                            tzinfo=_ZONE)

    # правило 2: большинство; поровну — своя страница; дальше — раньше
    def rank(start: datetime) -> tuple:
        votes = sum(1 for p in timed if p.start == start)
        own = any(p.start == start and p.extra.get("page_day")
                  == start.astimezone(_ZONE).date().isoformat() for p in timed)
        return (-votes, not own, start)
    return min(starts, key=rank)


# у языковых версий разметка та же — тот же разбор под их доменами
for _domain in LOCALES:
    register(_domain)(parse)

# -*- coding: utf-8 -*-
r"""Метки пола и возраста из эталона (слово владельца 24.10.2026, книга 003
и 079): строка без пометки возраста/пола, совпавшая по времени с U19- или
W-матчем эталона («Man City – Psg» у programetv ↔ «Manchester City U19 –
PSG U19» Юношеской ЛЧ), — эфир этого матча, метка дописывается из эталона.
Раньше такая строка упиралась в стену по полу и возрасту, эталон молчал, и
фильтр обхода снимал её как запись.

Что сторожится (по проверке на правило):

1. `Reference.confirm`, правило 5 «метки из эталона» (`reference.MARKS_HOW`):
   метка у записи одна и та же у обеих команд, у строки меток нет, имена без
   меток сходятся на `canon.SURE`, тот же вид спорта, окно эфира, кандидат
   один; кандидат без меток главнее; два с метками — None; метка у одной
   стороны строки или записи — стена как была;
2. `pipeline.classify`: метка эталона дописана к именам пары
   (`Confirmed.marks` → `leagues.with_category`), вид спорта — эталона;
3. `app/parsers/programetv_ro.py`: подзаголовок «Meci <вид> <турнир>» →
   `sport_raw` и `league_raw`, и Юношеская ЛЧ даёт U19 уже на сайте.

Эталоны маленькие и собраны прямо здесь (времена — киевские). В сеть не
ходит, база не нужна:

    python scripts/test_metki_etalona.py

Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
# базу не открываем, но на всякий случай — не боевая
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.gettempdir()) / "metki-etalona-none.db"))

from app import leagues, live, pipeline, sport  # noqa: E402
from app.parsers import Program, get  # noqa: E402
from app.reference import MARKS_HOW, Reference  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
MARKERS = live.load()
#: словарь команд пустой — сценарии не зависят от data/dictionaries.json
SPORTS = sport.load(teams=())
зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✗ {имя}: вышло {вышло!r}, ждали {ждём!r}")


def матч(вид: str, дом: str, гость: str, когда: str, **написания) -> dict:
    """Запись эталона в том виде, в каком её кладёт сбор (`games.json`)."""
    return {"sport": вид, "home": дом, "away": гость, "league": "",
            "fs_id": (дом[:4] + гость[:4]).replace(" ", ""),
            "start_kyiv": когда, "names": написания}


def момент(когда: str) -> datetime:
    return datetime.fromisoformat(когда)


def ответ(эталон: Reference, дом: str, гость: str, когда: str, вид: str = ""):
    """Что сказал эталон: (хозяева эталона, гости, как сошлось, обратный ли
    порядок, метки) — или None."""
    got = эталон.confirm(дом, гость, момент(когда), вид)
    if got is None:
        return None
    return (got.entry["home"], got.entry["away"], got.how, got.swapped, got.marks)


# ── эталоны ──────────────────────────────────────────────────────────────────
#: Юношеская ЛЧ 14.10 (книга 003): эталон знает пару только с U19
ЮНОШИ = Reference([матч("F", "Manchester City U19", "PSG U19", "2026-10-14T16:55")])
#: женский отбор: английское с W, итальянское написание flashscore — с «D»
ЖЕНЩИНЫ = Reference([матч("F", "Italy W", "Belarus W", "2026-10-13T19:05",
                          it=["Italia D", "Bielorussia D"])])
#: EFL Trophy: возраст у одной стороны — не наш случай
ОДНА_СТОРОНА = Reference([матч("F", "Chelsea U21", "Wycombe", "2026-10-14T21:00")])
#: взрослый и женский матч одной пары в одну минуту — взрослый главнее
ОБА = Reference([матч("F", "Poland W", "Belgium W", "2026-10-24T19:00"),
                 матч("F", "Poland", "Belgium", "2026-10-24T19:00")])
#: U19 и U21 одной пары в одну минуту — не гадаем
ДВА_ВОЗРАСТА = Reference([матч("F", "Serbia U19", "Bulgaria U19", "2026-10-24T19:00"),
                          матч("F", "Serbia U21", "Bulgaria U21", "2026-10-24T19:00")])
#: вторые составы — не пол и не возраст
ДУБЛИ = Reference([матч("F", "Benfica B", "Porto B", "2026-10-24T19:00")])
#: U17 и W вместе — метка составная
ЮНИОРКИ = Reference([матч("F", "Spain U17 W", "France U17 W", "2026-10-24T19:00")])

# ═════════════════════════════════════════════════════════════════════════════
print("1. Reference.confirm — правило 5 «метки из эталона»")
проверка("U19 у обеих команд эталона, строка без возраста → «метки из эталона», U19",
         ответ(ЮНОШИ, "Man City", "Psg", "2026-10-14T17:00"),
         ("Manchester City U19", "PSG U19", MARKS_HOW, False, "U19"))
проверка("обратный порядок сторон → swapped",
         ответ(ЮНОШИ, "Psg", "Man City", "2026-10-14T17:00")[3], True)
проверка("W у обеих, строка без пола → «метки из эталона», W",
         ответ(ЖЕНЩИНЫ, "Italy", "Belarus", "2026-10-13T19:00"),
         ("Italy W", "Belarus W", MARKS_HOW, False, "W"))
проверка("местное написание («Italia D») тоже сходится без меток",
         ответ(ЖЕНЩИНЫ, "Italia", "Bielorussia", "2026-10-13T19:00")[2:5],
         (MARKS_HOW, False, "W"))
проверка("составная метка «U17 W» — целиком",
         ответ(ЮНИОРКИ, "Spain", "France", "2026-10-24T19:00")[4], "U17 W")
проверка("строка со своими метками против той же записи — как раньше, «пара»",
         ответ(ЖЕНЩИНЫ, "Italy W", "Belarus W", "2026-10-13T19:00")[2:5], ("пара", False, ""))
проверка("метка у одной стороны записи (Chelsea U21 — Wycombe) → None",
         ответ(ОДНА_СТОРОНА, "Chelsea", "Wycombe", "2026-10-14T21:00"), None)
# стена `canon._pair_score` считает метки по паре ЦЕЛИКОМ (как и раньше):
# «Man City U19 — Psg» уже возрастная пара, правило 5 ей не нужно
проверка("метка у одной стороны строки — стена по паре целиком, как раньше: «пара», "
         "правило 5 молчит",
         ответ(ЮНОШИ, "Man City U19", "Psg", "2026-10-14T17:00")[2:5], ("пара", False, ""))
проверка("строка с меткой против записи без меток → None (стена как была)",
         ответ(ОБА, "Poland U19", "Belgium U19", "2026-10-24T19:00"), None)
проверка("кандидат без меток есть — он главнее: «пара», меток нет",
         ответ(ОБА, "Poland", "Belgium", "2026-10-24T19:00"),
         ("Poland", "Belgium", "пара", False, ""))
проверка("два кандидата с метками (U19 и U21) в одно время → None, не гадаем",
         ответ(ДВА_ВОЗРАСТА, "Serbia", "Bulgaria", "2026-10-24T19:00"), None)
проверка("второй состав (B) — не метка пола/возраста: Benfica — Porto → None",
         ответ(ДУБЛИ, "Benfica", "Porto", "2026-10-24T19:00"), None)
проверка("другой вид спорта назван → None",
         ответ(ЮНОШИ, "Man City", "Psg", "2026-10-14T17:00", "B"), None)
проверка("тот же вид назван → «метки из эталона»",
         ответ(ЮНОШИ, "Man City", "Psg", "2026-10-14T17:00", "F")[2], MARKS_HOW)
проверка("показ за 2 ч до матча — вне окна эфира → None",
         ответ(ЮНОШИ, "Man City", "Psg", "2026-10-14T15:00"), None)
проверка("показ через 20 мин после начала — запись → None",
         ответ(ЮНОШИ, "Man City", "Psg", "2026-10-14T17:15"), None)
проверка("показ за час до матча — ещё эфир (как у правила 3)",
         ответ(ЮНОШИ, "Man City", "Psg", "2026-10-14T15:55")[2], MARKS_HOW)
проверка("имена без меток не сходятся («Man City — Arsenal») → None",
         ответ(ЮНОШИ, "Man City", "Arsenal", "2026-10-14T17:00"), None)


# ═════════════════════════════════════════════════════════════════════════════
def строка(заголовок: str, когда: str, *, пара: str = "", эфир: str = "",
           лига: str = "", вид: str = "", эталон: Reference | None = ЮНОШИ):
    program = Program(channel_raw="Prima Sport 4", title=заголовок,
                      start=момент(когда).replace(tzinfo=KYIV),
                      league_raw=лига, sport_raw=вид,
                      live_raw=эфир, match_raw=пара)
    return pipeline.classify(program, MARKERS, SPORTS, {}, {}, эталон)


print("2. pipeline.classify — метка эталона дописана к именам")
row = строка("Man City – Psg", "2026-10-14T17:00", пара="Man City - Psg",
             эфир="live", вид="fotbal")
проверка("эфир с сайта: ok, имена с U19, вид — эталона (правило 2)",
         (row.ok, row.home, row.away, row.sport, row.sport_rule),
         (True, "Man City U19", "Psg U19", "F", 2))
проверка("by_reference = «метки из эталона»", row.by_reference, MARKS_HOW)
row = строка("Man City – Psg", "2026-10-14T17:00", пара="Man City - Psg")
проверка("без пометки эфира: эталон спасает (правило (в)) и дописывает U19",
         (row.ok, row.home, row.away, row.live_marker, row.by_reference),
         (True, "Man City U19", "Psg U19", pipeline.REFERENCE_MARKER, MARKS_HOW))
проверка("…эфир угаданный (live_guess) — его проверят фильтры повторов",
         row.program.extra.get("live_guess"), True)
row = строка("Italy - Belarus", "2026-10-13T19:00", пара="Italy - Belarus",
             эфир="live", эталон=ЖЕНЩИНЫ)
проверка("W из эталона: «Italy W — Belarus W»", (row.home, row.away), ("Italy W", "Belarus W"))
row = строка("Chelsea - Wycombe", "2026-10-14T21:00", пара="Chelsea - Wycombe",
             эфир="live", вид="football", эталон=ОДНА_СТОРОНА)
проверка("возраст у одной стороны эталона не переносится: имена как на сайте",
         (row.home, row.away, row.by_reference), ("Chelsea", "Wycombe", ""))
row = строка("Man City – Psg", "2026-10-14T17:00", пара="Man City - Psg",
             эфир="live", вид="fotbal", лига="Uefa Youth League")
# вид спорта тут даёт `sport_of` (пара с меткой турнира уже в эталоне), до
# `confirm` дело не доходит — `by_reference` пустое, как и раньше
проверка("метка турнира уже есть — U19 не удваивается, правило 5 не нужно",
         (row.home, row.away, row.sport_rule, row.by_reference),
         ("Man City U19", "Psg U19", 2, ""))
row = строка("Man City – Psg", "2026-10-14T17:00", пара="Man City - Psg",
             эфир="live", вид="fotbal", эталон=None)
проверка("без эталона — имена как на сайте", (row.home, row.away), ("Man City", "Psg"))


# ═════════════════════════════════════════════════════════════════════════════
def запись(start: str, title: str, sub: str, **поля) -> dict:
    return {"id": "1", "start": start, "stop": start[:11] + "23:59:59" + start[19:],
            "stationId": "483", "replay": False, "live": False,
            "categories": ["Sport"], "title": title, "subTitle": sub,
            "desc": "", **поля}


def страница(*записи: dict) -> str:
    return ('<script>window.__DATA__={"shows":' + json.dumps(list(записи), ensure_ascii=False)
            + ',"nextDayShows":[]}</script>')


URL = "https://www.programetv.ro/program-tv/prima-sport-4/"
разбор = get("programetv.ro")

print("3. programetv.ro — подзаголовок «Meci <вид> <турнир>»")
out = разбор(страница(
    запись("2026-10-14T17:00:00+03:00", "Man City – Psg", "Meci Fotbal Uefa Youth League"),
    запись("2026-10-14T19:00:00+03:00", "Dinamo – Steaua", "Meci Handbal Masculin European League"),
    запись("2026-10-14T21:00:00+03:00", "U-BT Cluj – Oradea", "Meci Baschet Liga Nationala"),
    запись("2026-10-14T23:00:00+03:00", "Prima Sport News",
           "Cele mai importante informații din lumea sportului."),
    запись("2026-10-14T15:00:00+03:00", "Rapid – FCSB", ""),
), url=URL)
по_заголовку = {p.title: p for p in out}
p = по_заголовку["Man City – Psg"]
проверка("«Meci Fotbal Uefa Youth League» → sport_raw «Fotbal», league_raw «Uefa Youth League»",
         (p.sport_raw, p.league_raw), ("Fotbal", "Uefa Youth League"))
проверка("…и турнир даёт U19 уже на сайте (leagues.category)",
         leagues.category(p.league_raw), "U19")
проверка("вид спорта — с сайта, не угадан", p.extra.get("sport_guess"), None)
проверка("гандбол: sport_raw «Handbal» — дальше его срежет вид спорта",
         по_заголовку["Dinamo – Steaua"].sport_raw, "Handbal")
проверка("баскетбол: «Baschet», турнир «Liga Nationala»",
         (по_заголовку["U-BT Cluj – Oradea"].sport_raw, по_заголовку["U-BT Cluj – Oradea"].league_raw),
         ("Baschet", "Liga Nationala"))
проверка("общая фраза передачи без матча не читается: лиги нет",
         по_заголовку["Prima Sport News"].league_raw, "")
проверка("пара без подзаголовка — как раньше: лиги нет, вид угадан «fotbal»",
         (по_заголовку["Rapid – FCSB"].league_raw, по_заголовку["Rapid – FCSB"].sport_raw,
          по_заголовку["Rapid – FCSB"].extra.get("sport_guess")),
         ("", "fotbal", True))
out = разбор(страница(
    запись("2026-10-14T20:30:00+03:00", "LIVE Liga 1: FCSB - Rapid", "Meci Fotbal Superliga"),
), url="https://www.programetv.ro/program-tv/digi-sport-1/")
проверка("лига в заголовке (Digi) главнее подзаголовка",
         (out[0].league_raw, out[0].sport_raw), ("Liga 1", ""))
# настоящая страница Prima Sport 2 из обхода #205 (scripts/testdata/live_flags)
страница_205 = (ROOT / "scripts" / "testdata" / "live_flags" / "programetv_prima-sport-2.html")
if страница_205.exists():
    out = разбор(страница_205.read_text(encoding="utf-8"),
                 url="https://www.programetv.ro/program-tv/prima-sport-2/")
    cipru = next(p for p in out if "Cipru" in p.title)
    проверка("страница обхода #205: «MECI FOTBAL UEFA NATIONS LEAGUE» → вид и турнир",
             (cipru.sport_raw, cipru.league_raw), ("FOTBAL", "UEFA NATIONS LEAGUE"))

print("3+2. строка programetv от сайта до имён: U19 с сайта, вид — эталона")
p = по_заголовку["Man City – Psg"]
row = pipeline.classify(p, MARKERS, SPORTS, {}, {}, ЮНОШИ)
проверка("имена с U19 (метка турнира с сайта), вид F от эталона (правило 2, sport_of)",
         (row.ok, row.home, row.away, row.sport, row.sport_rule, row.by_reference),
         (True, "Man City U19", "Psg U19", "F", 2, ""))
row = pipeline.classify(по_заголовку["Dinamo – Steaua"], MARKERS, SPORTS, {}, {}, ЮНОШИ)
проверка("гандбольный матч по подзаголовку — другой вид спорта",
         (row.ok, row.reason.startswith("другой вид спорта")), (False, True))

print()
print(f"проверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

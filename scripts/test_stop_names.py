# -*- coding: utf-8 -*-
r"""Стоп-слово внутри имени (11.10.2026): «conference» снимал всю Лигу
конференций, «studio» — клуб Studio Zagreb. Имена со стоп-словом внутри
лежат в `keep_names` (`data/markers.json`) и вырезаются перед поиском
(`live.Markers.found`).

Что держит:
  1. Настоящие строки сайтов с такими именами проходят отсев.
  2. Студия и конференц-трансляция по-прежнему снимаются — и рядом с
     вырезанным именем тоже.
  3. ДЕТЕКТОР по словарю: ни одно название турнира (`leagues`) не ловится
     стоп-словом, словом записи или стоп-жанром; у команд (`teams`) — только
     признанный мусор из `JUNK` (имена передач, попавшие в словарь). Новое
     совпадение — красная проверка: имя в `keep_names` или слово поправить.
  4. Самопроверка прогона (проверка 11) замечает эфир с парой из эталона,
     снятый стоп-словом.

В сеть не ходит, базу не открывает:
    python scripts/test_stop_names.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import live  # noqa: E402
from app.parsers import Program  # noqa: E402

BUC = ZoneInfo("Europe/Bucharest")
M = live.load()
зелёных = красных = 0

#: «команды» и «лиги» словаря, которые на деле — имена передач (словарь
#: выучил их из заголовков): стоп-слово снимает их правильно, в keep_names
#: их класть нельзя. Найдены детектором 11.10.2026
JUNK = {
    "Pre Game Show", "Pre Game Show (Ζ)",            # передача перед игрой
    "לקראת הפועל פ\"ת", "לקראת מכבי חיפה",           # «накануне …» — студия
    "אולפן לקראת ליגת ווינר",                        # «студия перед лигой»
}
#: начала таких имён: «Resúmenes LALIGA HyperMotion (T26/27): Valladolid» —
#: обзор тура movistarplus.es, не команда и не лига
JUNK_PREFIXES = ("Resúmenes ",)


def мусор(имя: str) -> bool:
    return имя in JUNK or имя.startswith(JUNK_PREFIXES)


def проверка(имя: str, ok: bool, extra="") -> None:
    global зелёных, красных
    if ok:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя} {extra}")


def строка(title: str, live_raw: str = "live", league: str = "",
           pair: str = "") -> Program:
    return Program(channel_raw="Digi Sport 1", title=title,
                   start=datetime(2026, 10, 15, 19, 40, tzinfo=BUC),
                   raw_time="19:40", league_raw=league, live_raw=live_raw,
                   match_raw=pair, source_url="https://www.digisport.ro/program-tv/digisport-1")


def stopped(p: Program) -> str:
    v = live.check(p, M)
    return "" if v.ok else v.reason


print("1. имена со стоп-словом внутри проходят")
p = строка("Conference League: Universitatea Craiova-Getafe",
           league="digisport Conference League", pair="Universitatea Craiova - Getafe")
проверка("digisport 15.10: «Conference League: Universitatea Craiova-Getafe» — эфир, пара видна",
         live.check(p, M).ok and live.check(p, M).home == "Universitatea Craiova", stopped(p))
p = строка("UEFA Europa Conference League: Rapid Wien - Chelsea", pair="Rapid Wien - Chelsea")
проверка("«UEFA Europa Conference League» — тоже проходит", live.check(p, M).ok, stopped(p))
p = строка("CONFERENCE LEAGUE - Fiorentina - Legia", pair="Fiorentina - Legia")
проверка("заглавными — тоже", live.check(p, M).ok, stopped(p))
p = строка("Košarka (Ž): Studio Zagreb W - Ragusa W", pair="Studio Zagreb W - Ragusa W")
проверка("клуб «Studio Zagreb W» — не студия", live.check(p, M).ok, stopped(p))

print("2. студия и конференц-трансляция снимаются как раньше")
for title in ("Studio: Conference League", "Conference League studio",
              "Press conference: Getafe", "Bundesliga Conference",
              "Studio Zagreb: studio poslije utakmice"):
    p = строка(title, pair="")
    проверка(f"«{title}» — снята", bool(stopped(p)), "прошла отсев")
проверка("слово «studio» в паре рядом с клубом — снята",
         bool(stopped(строка("Studio Zagreb - Dinamo studio", pair="Studio Zagreb - Dinamo studio"))))

print("3. детектор: названия словаря и стоп-слова")
d = json.loads((ROOT / "data" / "dictionaries.json").read_text(encoding="utf-8"))


def имена(записи) -> set[str]:
    out = set()
    for x in записи:
        for s in [x.get("name")] + list(x.get("aliases") or []):
            if isinstance(s, str) and s:
                out.add(s)
    return out


def ловится(имя: str) -> str:
    return (M.found(M.stop_title, имя) or M.found(M.not_live, имя)
            or M.found(M.stop_genre, имя))


лиги = {n: ловится(n) for n in имена(d.get("leagues") or [])}
плохие = {n: w for n, w in лиги.items() if w and not мусор(n)}
проверка(f"ни одно из {len(лиги)} названий турниров не ловится стоп-словом / словом записи / "
         f"стоп-жанром", not плохие, sorted(плохие.items())[:8])
команды = {n: ловится(n) for n in имена(d.get("teams") or [])}
новые = {n: w for n, w in команды.items() if w and not мусор(n)}
проверка(f"у {len(команды)} имён команд стоп-слово только у признанного мусора",
         not новые, sorted(новые.items())[:8])
games = ROOT / "results" / "games.json"
if games.exists():
    ref = json.loads(games.read_text(encoding="utf-8")).get("эталон") or []
    плохие = sorted({r.get("league") for r in ref
                     if r.get("league") and ловится(r["league"])})
    проверка(f"лиги эталона последнего сбора ({len(ref)} матчей) не ловятся стоп-словом",
             not плохие, плохие[:8])

print("4. самопроверка прогона, проверка 11")
import audit_run  # noqa: E402

site = audit_run.Site("digisport.ro")
p = строка("Conference League: Universitatea Craiova-Getafe", pair="Universitatea Craiova - Getafe")
site.stopped.append((p, "conference"))
site.stopped.append((строка("Studio: Rapid - Dinamo", pair="Rapid - Dinamo"), "studio"))
# настоящая студия про матч из эталона (allente.no 15.10, сбор #241)
site.stopped.append((строка("UEFA Europa League: Studio før Sparta Praha - Lillestrøm",
                            pair="Sparta Praha - Lillestrøm"), "studio"))
игры = {"эталон": [
    {"home": "Univ. Craiova", "away": "Getafe", "start_kyiv": "2026-10-15T19:45",
     "league": "EUROPE: Conference League - League phase", "sport": "F"},
    {"home": "Sparta Prague", "away": "Lillestrom", "start_kyiv": "2026-10-15T19:45",
     "league": "EUROPE: Europa League - League phase", "sport": "F"}]}
out = audit_run.check_stopped({"digisport.ro": site}, игры)
проверка("эфир с парой из эталона, а стоп-слово есть в имени турнира эталона, — подозрение",
         len(out) == 1 and "«conference»" in out[0] and "Univ. Craiova" in out[0], out)
проверка("студия без пары в эталоне — не подозрение", all("studio" not in x for x in out), out)
проверка("студия ПРО матч из эталона (слова «studio» в эталоне нет) — не подозрение",
         all("Sparta" not in x for x in out), out)
проверка("без games.json проверка молчит", audit_run.check_stopped({"digisport.ro": site}, None) == [])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

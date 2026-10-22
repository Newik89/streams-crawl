# -*- coding: utf-8 -*-
"""Мультикаст — не канал игры (`parse_live.drop_multicast`, правила 1–4) и
«samenvatting» — обзор, не эфир (владелец 22.10.2026: #7453/#7452/#7274 —
OneSoccer у четырёх матчей CPL 25.10 в одно время).

Игры собраны здесь. В сеть не ходит, база не нужна:

    venv\\Scripts\\python.exe scripts/test_multicast.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.gettempdir()) / "multicast-test-none.db"))

import parse_live  # noqa: E402
from app import broadcast  # noqa: E402
from app.merge import Entry, Game  # noqa: E402

зелёных = красных = 0


def проверка(имя, вышло, ждём):
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✗ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def игра(home, away, hh, mm, *rows):
    when = datetime(2026, 10, 25, hh, mm)
    return Game(entries=[Entry(source=s, channel=c, home=home, away=away,
                               start=when, sport="F") for s, c in rows])


def каналы(games):
    return {f"{g.first.home} - {g.first.away}": sorted(f"{e.channel}/{e.source}" for e in g.entries)
            for g in games}


print("правила 1–4 мультикаста")
игры = [
    игра("HFX Wanderers", "Supra du Québec", 22, 0,
         ("canpl.ca", "OneSoccer"), ("canpl.ca", "TVA Sports 2"), ("tvpassport.com", "TVA Sports 2")),
    игра("Pacific", "Forge", 22, 0, ("canpl.ca", "OneSoccer")),
    игра("Cavalry", "Vancouver FC", 22, 0,
         ("canpl.ca", "OneSoccer"), ("canpl.ca", "TSN"), ("canpl.ca", "CBC")),
    игра("Inter Toronto", "Atlético Ottawa", 22, 10, ("canpl.ca", "OneSoccer")),
    # тот же канал, но через 2 часа — обычный вечер канала, не мультикаст
    игра("Forge", "Cavalry", 0, 30, ("canpl.ca", "OneSoccer")),
    # другой сайт дал тому же каналу другую игру в то же время — спор сайтов
    игра("Valour", "York United", 22, 0, ("livesoccertv.com", "OneSoccer")),
    # трансляции турниров без пары — канал тенниса меняет корты
    игра("ATP Lyon", broadcast.SESSION, 15, 0, ("sporttv.pt", "SPORT.TV5")),
    игра("ATP Brussels", broadcast.SESSION, 15, 0, ("sporttv.pt", "SPORT.TV5")),
]
осталось, снято = parse_live.drop_multicast(игры)
вышло = каналы(осталось)
проверка("правило 2: OneSoccer у canpl снят у всех четырёх игр в 22:00–22:10",
         sorted(e.home for g, e, n in снято if e.channel == "OneSoccer"),
         ["Cavalry", "HFX Wanderers", "Inter Toronto", "Pacific"])
проверка("правило 2: сколько игр разом — 4", {n for _, _, n in снято}, {4})
проверка("правило 4: у HFX остались TVA Sports 2 от двух сайтов",
         вышло.get("HFX Wanderers - Supra du Québec"),
         ["TVA Sports 2/canpl.ca", "TVA Sports 2/tvpassport.com"])
проверка("правило 4: у Cavalry остались CBC и TSN",
         вышло.get("Cavalry - Vancouver FC"), ["CBC/canpl.ca", "TSN/canpl.ca"])
проверка("правило 4: игра без строк уходит целиком (Pacific, Inter Toronto)",
         ("Pacific - Forge" in вышло, "Inter Toronto - Atlético Ottawa" in вышло), (False, False))
проверка("правило 2: та же пара каналов через 2 часа — остаётся",
         вышло.get("Forge - Cavalry"), ["OneSoccer/canpl.ca"])
проверка("правило 1: другой сайт с тем же каналом в то же время — не мультикаст",
         вышло.get("Valour - York United"), ["OneSoccer/livesoccertv.com"])
проверка("правило 3: две трансляции турниров на одном канале — не мультикаст",
         (вышло.get(f"ATP Lyon - {broadcast.SESSION}"), вышло.get(f"ATP Brussels - {broadcast.SESSION}")),
         (["SPORT.TV5/sporttv.pt"], ["SPORT.TV5/sporttv.pt"]))
одна = [игра("A", "B", 20, 0, ("x.tv", "K1")), игра("C", "D", 22, 0, ("x.tv", "K1"))]
проверка("одна игра в окне — ничего не снято", len(parse_live.drop_multicast(одна)[1]), 0)

print("«samenvatting» — обзор (ziggosport.nl 27.10: «FC Barcelona - Real Madrid (samenvatting)»)")
import json  # noqa: E402
data = json.loads((ROOT / "data" / "markers.json").read_text(encoding="utf-8"))
все = [w for group in data["not_live"].values() if isinstance(group, list) for w in group]
проверка("samenvatting в словаре «запись/повтор»", "samenvatting" in все, True)

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

# -*- coding: utf-8 -*-
r"""Женские лиги, у которых пол в названии не пишут (владелец 12.10.2026:
«Liga BPI — это лига на flashscore, PORTUGAL: Liga BPI Women»).

canal11.pt пишет «Liga BPI», movistarplus — «Liga F»: без слова «женская»
команды шли мужскими, с эталоном «Rio Ave W — Porto W» не сводились и
оставались без перевода. Список таких турниров — `leagues._WOMEN_LEAGUES`;
новую такую лигу находит самопроверка сбора (`audit_run`, проверка 12).

В сеть не ходит:
    python scripts/test_women_leagues.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import leagues  # noqa: E402
import audit_run  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


print("1. женские лиги без слова «женская»")
for лига, ждём in (("Liga BPI", "W"), ("LIGA BPI", "W"), ("Liga F", "W"), ("LIGA F MOEVE", "W"),
                   ("Toppserien", "W"),
                   ("Liga Futsal", ""), ("Liga Portugal Betclic", ""), ("LaLiga EA Sports", ""),
                   ("Liga BPI Sub-19", "U19 W"), ("Spartak Subotica", "")):
    проверка(f"«{лига}» → «{ждём}»", leagues.category(лига), ждём)


def строка(home: str, away: str, league: str, hhmm: str) -> SimpleNamespace:
    return SimpleNamespace(home=home, away=away, sport="F", league=league,
                           start_kyiv=datetime.fromisoformat(f"2026-10-17T{hhmm}").replace(tzinfo=KYIV),
                           program=SimpleNamespace(league_raw=league))


print("2. самопроверка, проверка 12: лига, которой нет в списке")
site = audit_run.Site("canal11.pt")
site.rows = [(строка("RIO AVE FC", "FC PORTO", "Liga Nova", "13:00"), "p"),
             (строка("Benfica", "Sporting", "Liga Nova", "15:00"), "p"),        # мужской матч
             (строка("Arouca", "Estrela", "Liga Portugal", "17:00"), "p")]
игры = {"эталон": [
    {"home": "Rio Ave W", "away": "Porto W", "start_kyiv": "2026-10-17T13:00",
     "league": "PORTUGAL: Liga Nova Women", "sport": "F"},
    {"home": "Benfica", "away": "Sporting CP", "start_kyiv": "2026-10-17T15:00",
     "league": "PORTUGAL: Liga Portugal", "sport": "F"},
    {"home": "Arouca W", "away": "Estrela W", "start_kyiv": "2026-10-17T17:00",
     "league": "PORTUGAL: Taça Women", "sport": "F"}]}
out = audit_run.check_women_leagues({"canal11.pt": site}, игры)
проверка("женский матч эталона, лига сайта — ядро женской лиги → подсказка с названием",
         len(out) == 1 and "«liga nova»" in out[0] and "RIO AVE FC" in out[0], True)
проверка("мужской матч эталона — не подозрение", any("Benfica" in x for x in out), False)
проверка("женский матч другой лиги (ядро не совпало) — не подозрение", any("Arouca" in x for x in out), False)
проверка("без эталона молчит", audit_run.check_women_leagues({"canal11.pt": site}, {"эталон": []}), [])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

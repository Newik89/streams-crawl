# -*- coding: utf-8 -*-
r"""Книга 143 (15.11.2026): на месте лиги — одно название вида спорта.

ipko.tv кладёт в поле лиги жанр передачи («futbolli», «basketboll»),
digisport.ro — «tenis Tenis». У матча, который эталон знает, лига приходит из
эталона; у остальных на витрине на месте лиги стояло слово «футбол». Замер по
всем сайтам сбора 15.11: 7 игр из 482.

Правило: `leagues.clean` отдаёт пусто, если после чистки в названии остались
только слова вида спорта (`leagues.only_sport`, правила 1–3).
В сеть не ходит, базу не открывает. Запуск: python scripts/test_liga_ne_zhanr.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import leagues, live, pipeline, sport  # noqa: E402
from app.parsers import Program  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


print("Одно название вида спорта — не лига (`leagues.only_sport`, `leagues.clean`)")
проверка("правило 1: слово вида спорта на языках сайтов — албанский, румынский, чешский, русский, греческий, иврит",
         [leagues.clean(x) for x in ("futbolli", "basketboll", "tenis Tenis", "Fotbal", "Футбол", "Μπάσκετ", "כדורגל",
                                     "Piłka nożna", "Sport", "FUTBOLL - Sport")],
         [""] * 10)
проверка("правило 2: название турнира, записанное в словаре видов спорта целиком, — лига, как и была",
         [leagues.clean(x) for x in ("ליגת האלופות בכדורסל", "NCAA Basketball", "Euroliga de baloncesto")],
         ["ליגת האלופות בכדורסל", "NCAA Basketball", "Euroliga de baloncesto"])
проверка("правило 3: кроме вида спорта есть ещё слово — лига как была",
         [leagues.clean(x) for x in ("כדורגל איטלקי", "Fotbal ženy", "PGE Basket Liga", "NBA Basketball",
                                     "superliga Superliga", "Basketligaen", "Liga e Pare")],
         ["כדורגל איטלקי", "Fotbal ženy", "PGE Basket Liga", "NBA Basketball", "superliga Superliga",
          "Basketligaen", "Liga e Pare"])
проверка("прежняя чистка цела: вид спорта спереди через двоеточие и сзади через дефис, сезон",
         [leagues.clean(x) for x in ("Piłka nożna: Liga angielska", "EFL CHAMPIONSHIP - FUTEBOL", "Serie A 2026/2027")],
         ["Liga angielska", "EFL CHAMPIONSHIP", "Serie A"])
проверка("пустое и не название — не «один вид спорта»",
         [leagues.only_sport(x) for x in ("", "   ", "2026", "futbolli", "Liga")], [False, False, True, True, False])

print("Разбор строки")
M, виды = live.load(), sport.load()
p = Program(channel_raw="Sport 1", title="Prishtina e Re - Liria", start=datetime(2026, 11, 22, 14, 0, tzinfo=KYIV),
            live_raw="live", league_raw="futbolli", match_raw="Prishtina e Re - Liria")
row = pipeline.classify(p, M, виды)
проверка("у игры ipko.tv с жанром «futbolli» в поле лиги лига пустая, а вид спорта по этому слову определён",
         (row.ok, row.league, row.sport), (True, "", "F"))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

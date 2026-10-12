# -*- coding: utf-8 -*-
r"""Автоперевод названий лиг, которых нет в словаре лиг (решение владельца
12.10.2026: «переводить спортивные слова в названиях лиг по словарю:
«Кубок» → Cup, «плей-офф» → Playoff»). Примеры — настоящие строки витрины
12.10, у которых перевода не было. Словарь — `data/league_words.json`,
правила — `app/league_words.py`.

В сеть не ходит:
    python scripts/test_league_words.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import league_words  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


print("1. настоящие строки витрины 12.10")
for сайт, ждём in (
        ("Кубок Германии. 1/8 финала", "Germany Cup. Round of 16"),     # ntvplus, правило 1
        ("WNBA - פלייאוף", "WNBA - Playoff"),                            # sport5, правило 2
        ("ליגת האלופות אסיה", "Champions League Asia"),
        ("среща от груповата фаза на FIBA Europe Cup", "Group stage: FIBA Europe Cup"),
        ("Náš fotbal živě", "Czech amateur football (Náš fotbal živě)"),  # #5865
        ("SUPERLIGA Ž", "SUPERLIGA Women"),
        ("VM-Kval Dam", "World Cup qualification Women"),
        ("Košarka", "Basketball"),                                       # правило 3: с заглавной
        ("Тур 14 Прямая трансляция", "Round 14"),
        ("EHF LIGA ŠAMPIONA (Ž)", "EHF Champions League (Women)")):
    проверка(f"«{сайт}» → «{ждём}»", league_words.auto_english(сайт), ждём)

print("2. латиницу без совпадений не трогаем, остальное — транслит")
for сайт in ("Liga BPI", "Livesport Superliga", "WTA TOUR", "Arena Karavan", "Amsterdam Cup"):
    проверка(f"«{сайт}» — как есть", league_words.auto_english(сайт), сайт)
проверка("незнакомое кириллицей — транслит", league_words.auto_english("Чемпионат Испании Сегунда"),
         "Championship Spain Segunda")
проверка("пустое — пустое", league_words.auto_english(""), "")
проверка("целыми словами: «тур» не режется в «Турции»", league_words.auto_english("Кубок Турции"),
         "Cup Turkey")

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

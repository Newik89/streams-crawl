# -*- coding: utf-8 -*-
r"""Книга 161 (16.11.2026): у игры с меткой эталона команда берётся с пометкой
пола эталона — как уже бралась с пометкой возраста (#3037).

Витрина 16.11: встреча Кубка Билли Джин Кинг стояла «France vs Australia W» —
у одной стороны W, у другой нет. Эталон пишет обе сборные с W; написание
«Polska», «FRANÇA» закреплено в словаре за командой без пометки, и сверка её
держала, а незакреплённое «AUSTRÁLIA» получало команду эталона. Правило —
`canon_backfill.only_marks_differ`, 1–3.
В сеть не ходит, базу не трогает. Запуск: python scripts/test_pol_iz_etalona.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import canon_backfill  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


отличие = canon_backfill.only_marks_differ
print("Команда эталона отличается только пометкой (`canon_backfill.only_marks_differ`)")
проверка("правила 1–2: пол — «Poland» → «Poland W», «France» → «France W»",
         [отличие("Poland", "Poland W"), отличие("France", "France W"), отличие("australia", "Australia W")],
         [True, True, True])
проверка("правила 1–2: возраст — как раньше («Serbia» → «Serbia U19», #3037), и возраст с полом вместе",
         [отличие("Serbia", "Serbia U19"), отличие("Spain", "Spain U19 W")], [True, True])
проверка("правило 1: у эталона пометки нет — закреплённое написание держим",
         [отличие("Racing Club", "Racing Santander"), отличие("Poland", "Poland")], [False, False])
проверка("правило 2: без пометок имена разные — это другая команда",
         [отличие("Austria", "Australia W"), отличие("Racing Club", "Racing Santander W")], [False, False])
проверка("правило 3: нынешняя команда сама с пометкой — другая команда, не трогаем",
         [отличие("Poland U19", "Poland W"), отличие("Poland W", "Poland U19")], [False, False])
проверка("пустые имена — правило молчит", [отличие("", "Poland W"), отличие("Poland", "")], [False, False])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

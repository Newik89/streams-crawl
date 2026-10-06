# -*- coding: utf-8 -*-
"""Проверки сравнения планов (`scripts/plan_diff.py`) — по правилу на случай.

Запуск: venv\\Scripts\\python.exe scripts/test_plan_diff.py
К сети и базе не обращается.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import plan_diff  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def план(*сайты: dict) -> dict[str, dict]:
    return {s["domain"]: s for s in сайты}


def сайт(домен: str, **поля) -> dict:
    карточка = {"domain": домен, "include": [], "parser": "", "channels": []}
    карточка.update(поля)
    return карточка


def отличий(старый: dict, новый: dict) -> int:
    """Код возврата сравнения: 1 — отличия есть, 0 — нет."""
    тихо = io.StringIO()
    было, sys.stdout = sys.stdout, тихо
    try:
        return plan_diff.сравнить(старый, новый)
    finally:
        sys.stdout = было


def текст(старый: dict, новый: dict) -> str:
    тихо = io.StringIO()
    было, sys.stdout = sys.stdout, тихо
    try:
        plan_diff.сравнить(старый, новый)
    finally:
        sys.stdout = было
    return тихо.getvalue()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("Сравнение планов обхода")

    один = план(сайт("a.tv"), сайт("b.tv"))
    проверка("одинаковые планы — отличий нет", отличий(один, один), 0)

    без_b = план(сайт("a.tv"))
    проверка("сайт пропал — отличие", отличий(один, без_b), 1)
    проверка("сайт пропал — назван",
             "ПРОПАЛИ сайты (1): b.tv" in текст(один, без_b), True)

    с_c = план(сайт("a.tv"), сайт("b.tv"), сайт("c.tv"))
    проверка("новый сайт — отличие", отличий(один, с_c), 1)
    проверка("новый сайт — назван", "новые сайты (1): c.tv" in текст(один, с_c),
             True)

    поле = план(сайт("a.tv", include=["Sport 1"]), сайт("b.tv"))
    проверка("поле сайта изменилось — отличие", отличий(один, поле), 1)
    проверка("поле названо", "include" in текст(один, поле), True)

    стр = план(сайт("a.tv", channels=[{"name": "X", "pattern": "u1"}]),
               сайт("b.tv"))
    проверка("страница добавилась — отличие", отличий(один, стр), 1)
    проверка("адрес страницы показан", "u1" in текст(один, стр), True)
    проверка("страница ушла — отличие", отличий(стр, один), 1)

    порядок_а = план(сайт("a.tv", channels=[{"name": "X", "pattern": "u1"},
                                            {"name": "Y", "pattern": "u2"}]))
    порядок_б = план(сайт("a.tv", channels=[{"name": "Y", "pattern": "u2"},
                                            {"name": "X", "pattern": "u1"}]))
    проверка("переставленные страницы — не отличие",
             отличий(порядок_а, порядок_б), 0)

    # план бывает и словарём «домен → карточка», и списком под ключом sources
    with tempfile.TemporaryDirectory() as d:
        п = Path(d) / "plan.json"
        io.open(п, "w", encoding="utf-8").write(json.dumps(
            {"days": 6, "sources": [сайт("a.tv")]}, ensure_ascii=False))
        проверка("читает план с ключом sources",
                 sorted(plan_diff.прочитать(str(п))), ["a.tv"])
        io.open(п, "w", encoding="utf-8").write(json.dumps(
            [сайт("a.tv"), сайт("b.tv")], ensure_ascii=False))
        проверка("читает план списком",
                 sorted(plan_diff.прочитать(str(п))), ["a.tv", "b.tv"])

    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, "
          f"красных: {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

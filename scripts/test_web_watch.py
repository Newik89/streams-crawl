# -*- coding: utf-8 -*-
"""Сторож витрины (`scripts/web_watch.py`): правила В1–В4 — сценарий на каждое.

В сеть не ходит, службу не трогает: пробы и перезапуск подменены. Запуск:

    venv\\Scripts\\python.exe scripts/test_web_watch.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import web_watch  # noqa: E402
from app import watch  # noqa: E402

зелёных = красных = 0


def проверка(имя, вышло, ждём, extra=""):
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r} {extra}")


NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
ОК = (True, "HTTP 200")
ВИСИТ = (False, "TimeoutError: timed out")
calls = []


def вторая(ответ):
    def f():
        calls.append("вторая")
        return ответ
    return f


def main() -> int:
    print("В1. открылась — молчим")
    calls.clear()
    what, words, st = web_watch.verdict({}, NOW, ОК, вторая(ВИСИТ))
    проверка("ok без второй пробы", (what, calls), ("ok", []))

    print("В2. первая не открылась, вторая открылась — молчим")
    calls.clear()
    what, words, st = web_watch.verdict({}, NOW, ВИСИТ, вторая(ОК))
    проверка("ok после второй пробы", (what, calls), ("ok", ["вторая"]))
    проверка("память не тронута", st, {})

    print("В3. дважды не открылась — перезапуск, счёт за час")
    what, words, st = web_watch.verdict({}, NOW, ВИСИТ, вторая(ВИСИТ))
    проверка("перезапуск", what, "restart")
    проверка("в словах — 1 из 3", "1 из 3" in words, True, words)
    проверка("перезапуск записан", len(st["restarts"]), 1)
    what2, words2, st2 = web_watch.verdict(st, NOW + timedelta(minutes=5), ВИСИТ, вторая(ВИСИТ))
    what3, words3, st3 = web_watch.verdict(st2, NOW + timedelta(minutes=10), ВИСИТ, вторая(ВИСИТ))
    проверка("второй и третий — тоже перезапуск", (what2, what3), ("restart", "restart"))
    проверка("в словах — 3 из 3", "3 из 3" in words3, True, words3)

    print("В4. три за час исчерпаны — ТРЕВОГА раз в час, не перезапуск")
    what4, words4, st4 = web_watch.verdict(st3, NOW + timedelta(minutes=15), ВИСИТ, вторая(ВИСИТ))
    проверка("тревога", what4, "alarm")
    проверка("слова начинаются с ТРЕВОГА", words4.startswith("ТРЕВОГА"), True, words4)
    проверка("перезапусков по-прежнему 3", len(st4["restarts"]), 3)
    what5, _, st5 = web_watch.verdict(st4, NOW + timedelta(minutes=20), ВИСИТ, вторая(ВИСИТ))
    проверка("повторная тревога в тот же час — молчим", what5, "quiet")
    what6, words6, _ = web_watch.verdict(st5, NOW + timedelta(minutes=80), ВИСИТ, вторая(ВИСИТ))
    проверка("прошёл час — старые перезапуски не в счёт, снова перезапуск 1 из 3",
             (what6, "1 из 3" in words6), ("restart", True), words6)

    print("Старые перезапуски не считаются")
    старое = {"restarts": [watch.when(NOW - timedelta(minutes=61)),
                           watch.when(NOW - timedelta(minutes=59))]}
    what7, words7, st7 = web_watch.verdict(старое, NOW, ВИСИТ, вторая(ВИСИТ))
    проверка("перезапуск: старше часа отброшен, остался один + новый",
             (what7, len(st7["restarts"]), "2 из 3" in words7), ("restart", 2, True), words7)

    print("Проба: ответ сервера → итог")
    проверка("5xx — не открылась", web_watch.probe("http://127.0.0.1:9/x", timeout=1)[0], False)

    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

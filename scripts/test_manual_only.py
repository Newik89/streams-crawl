# -*- coding: utf-8 -*-
"""Отбор сайтов в обход: «только по кнопке» и «качает сервер»
(`crawl_fetch.targets`).

08.10: владелец снял beinsports.com.tr с обхода «только по кнопке», а
пометка срабатывала лишь при cron самого GitHub (`--scheduled`) — сборы,
заказанные сервером, и кнопки «2 дня» / «6 дней» / скан даты сайт брали как
все. Правило: такой сайт идёт только когда назван по имени (`--only`).

Запуск: venv\\Scripts\\python.exe scripts/test_manual_only.py
К сети не обращается.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import crawl_fetch  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def сайт(домен: str, **поля) -> dict:
    s = {"domain": домен, "timezone": "Europe/Kyiv", "grid": True,
         "days_inline": False, "base_url": f"https://{домен}/", "marks": {},
         "pages_per_day": 0, "max_days": 0, "days_ahead": 0,
         "channels": [{"name": "", "pattern": f"https://{домен}/tv/{{YYYY-MM-DD}}"}]}
    s.update(поля)
    return s


ПЛАН = {"sources": [сайт("obychny.tv"),
                    сайт("knopka.tv", manual_only=True),
                    сайт("server.tv", by_server=True)]}


def домены(**kw) -> set[str]:
    return {t["domain"] for t in crawl_fetch.targets(
        ПЛАН, days=2, probe=False, start=date(2026, 10, 8), **kw)}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("Отбор сайтов: «только по кнопке» и «качает сервер»")
    проверка("заказанный сервером сбор (без флага): только обычный",
             домены(), {"obychny.tv"})
    проверка("cron GitHub (--scheduled): то же", домены(scheduled=True),
             {"obychny.tv"})
    проверка("скан даты: то же", домены(single=True), {"obychny.tv"})
    проверка("назван по имени — «только по кнопке» идёт",
             домены(only={"knopka.tv"}), {"knopka.tv", "obychny.tv"})
    проверка("назван по имени — «качает сервер» идёт",
             домены(only={"server.tv"}), {"server.tv", "obychny.tv"})
    проверка("обычный сайт без пометок идёт всегда",
             "obychny.tv" in домены(scheduled=True, single=True), True)
    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, "
          f"красных: {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

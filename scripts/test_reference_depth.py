# -*- coding: utf-8 -*-
r"""Справочник не мельче окна витрины (правило (а) починки самопроверки №13,
слово владельца 20.10.2026; разбор 15.10 по сбору #266: шесть зеркал
эталона — ru, ro, pl, tr, ua, cz — качались на 1 день при окне 6, у матчей
дальних дней не было местных написаний, и ~130 матчей за сбор терялись).

Правила (`app.crawl.depth`, и через него `scripts/crawl_fetch.targets`):
1. у справочника своя глубина — нижняя планка: окно обхода её поднимает
   (1 день при окне 6 → 6), но не опускает (7 при окне 6 → 7);
2. выше `MAX_DAYS_AHEAD` (7) не качаем;
3. окно 0 (сборка плана `crawl_plan.py`) оставляет свою глубину как есть —
   план в git не меняется, правило действует в день обхода;
4. обычный сайт расписания — как раньше: окно обхода, потолок `max_days`;
5. `crawl_fetch.targets` берёт число у `depth`, а не у плана напрямую:
   зеркало с `days_ahead: 1` при `--days 6` даёт шесть страниц на спорт.

В сеть не ходит:
    python scripts/test_reference_depth.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import crawl  # noqa: E402
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


print("правило 1: своя глубина справочника — нижняя планка")
проверка("зеркало на 1 день при окне 6 → 6",
         crawl.depth({"days_ahead": 1}, 6, "m.flashscore.ro"), 6)
проверка("зеркало на 1 день при окне 2 → 2",
         crawl.depth({"days_ahead": 1}, 2, "m.livesport.cz"), 2)
проверка("эталон на 7 при окне 6 остаётся 7",
         crawl.depth({"days_ahead": 7}, 6, "flashscore.mobi"), 7)
проверка("зеркало без своей глубины — по окну",
         crawl.depth({"days_ahead": 0}, 6, "m.flashscore.de"), 6)
проверка("с www. тоже справочник",
         crawl.depth({"days_ahead": 1}, 6, "www.flashscore.mobi"), 6)

print("правило 2: не выше MAX_DAYS_AHEAD")
проверка("окно 9 у зеркала на 1 день → 7",
         crawl.depth({"days_ahead": 1}, 9, "m.flashscore.pl"), crawl.MAX_DAYS_AHEAD)

print("правило 3: окно 0 (сборка плана) — своя глубина как есть")
проверка("план хранит 1", crawl.depth({"days_ahead": 1}, 0, "m.flashscore.ua"), 1)
проверка("план хранит 7", crawl.depth({"days_ahead": 7}, 0, "m.flashscore.gr"), 7)

print("правило 4: обычный сайт — окно обхода и потолок")
проверка("сайт расписания с days_ahead 5 при окне 2 → 2",
         crawl.depth({"days_ahead": 5}, 2, "teleman.pl"), 2)
проверка("потолок max_days 4 при окне 6 → 4",
         crawl.depth({"max_days": 4}, 6, "mojtv.hr"), 4)
проверка("кривая глубина не роняет",
         crawl.depth({"days_ahead": "семь"}, 6, "m.flashscore.ro"), 6)

print("правило 5: crawl_fetch.targets качает зеркало на всё окно")
ПЛАН = {"days": 6, "sources": [{
    "domain": "m.flashscore.ro", "timezone": "Europe/Bucharest", "grid": False,
    "marks": {}, "include": ["football"], "parser": "", "browser": False,
    "days_inline": False, "day_links": False, "pages_per_day": 0,
    "day_channels": [], "days_ahead": 1, "max_days": 0, "manual_only": False,
    "by_server": False, "channel_days": {}, "post_fields": None,
    "warmup_url": "", "post_json": None, "headers": None,
    "base_url": "https://m.flashscore.ro/",
    "channels": [{"name": "football",
                  "pattern": "https://m.flashscore.ro/?d={DAYNUM}"}]}]}
адреса = list(crawl_fetch.targets(ПЛАН, 6, probe=False, start=date(2026, 10, 20)))
проверка("при --days 6 — шесть страниц", len(адреса), 6)
проверка("дни идут подряд с «сегодня» сайта",
         [a["day"] for a in адреса][:3],
         ["2026-10-20", "2026-10-21", "2026-10-22"])
адреса = list(crawl_fetch.targets(ПЛАН, 2, probe=False, start=date(2026, 10, 20)))
проверка("при --days 2 — две страницы", len(адреса), 2)
адреса = list(crawl_fetch.targets(ПЛАН, 6, probe=False, start=date(2026, 10, 20),
                                  single=True))
проверка("скан одной даты — одна страница", len(адреса), 1)
адреса = list(crawl_fetch.targets(dict(ПЛАН, sources=[dict(ПЛАН["sources"][0],
                                                           max_days=3)]),
                                  6, probe=False, start=date(2026, 10, 20)))
проверка("потолок max_days 3 у справочника держит", len(адреса), 3)

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
raise SystemExit(1 if красных else 0)

"""Книга 122 (14.11): пара из заголовка главнее пары разборщика, которую
эталон не знает. Общее правило для всех сайтов (`pipeline.title_over_pair`).

Случай ipko.tv: сайт сменил запись, разборщик выдал «пару» из обрывка
описания, а настоящая пара стояла в заголовке («Spanje-Angli»).

Запуск: python scripts/test_para_iz_zagolovka.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import live, pipeline, sport  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import Reference  # noqa: E402

зелёных = красных = 0
MARKERS = live.load()
SPORTS = sport.load(teams=())
ЭТАЛОН = Reference([
    {"sport": "F", "home": "Spain", "away": "England", "league": "EUROPE: UEFA Nations League",
     "fs_id": "a1", "start_kyiv": "2026-11-15T21:45"},
    {"sport": "F", "home": "France", "away": "Turkey", "league": "EUROPE: UEFA Nations League",
     "fs_id": "a2", "start_kyiv": "2026-11-15T21:45"},
])
ОБРЫВОК = "UEFA Nations League - Shikoni ndeshjen e futbollit në të cilën Spanja përballon Angli."


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def строка(title: str, pair: str, час: int = 19, минута: int = 45, live_raw: str = "live"):
    """Строка, как её отдал бы разборщик сайта: заголовок, «пара», пометка эфира."""
    start = datetime(2026, 11, 15, час, минута, tzinfo=timezone.utc)      # 21:45 по Киеву
    return Program(channel_raw="SuperSport 1", title=title, start=start,
                   raw_time=start.strftime("%H:%M"), description="", league_raw="futbolli",
                   sport_raw="futbolli Sport", live_raw=live_raw, match_raw=pair,
                   source_url="https://example.test/x", extra={})


def разбор(p: Program, reference=ЭТАЛОН):
    return pipeline.classify(p, MARKERS, SPORTS, {}, {}, reference, None)


print("Правила 1–4: пара разборщика эталону незнакома, в заголовке — настоящая")
p = строка("Spain-England", ОБРЫВОК)
r = разбор(p)
проверка("случай ipko.tv: вместо обрывка описания взята пара из заголовка",
         (r.home, r.away), ("Spain", "England"))
проверка("…прежняя пара записана в пометку — для журнала разбора",
         "Shikoni" in (p.extra.get(pipeline.TITLE_PAIR) or ""), True)
проверка("…эфир остаётся словом сайта, а не «угадан»",
         (bool(r.live_marker), p.extra.get("live_guess")), (True, None))
p = строка("England-Spain", ОБРЫВОК)
r = разбор(p)
проверка("пара в заголовке наоборот — берётся в порядке сторон эталона",
         (r.home, r.away), ("Spain", "England"))
p = строка("Futboll: France - Turkey", "Liga e Kombeve - Ndeshja e javës")
r = разбор(p)
проверка("другой вид мусорной пары, заголовок с пробелами вокруг тире",
         (r.home, r.away), ("France", "Turkey"))

print("Правила 2 и 5: правило ничего не отнимает")
p = строка("Spain-England", "Spain - England")
r = разбор(p)
проверка("разборщик прочитал верно — пара его, пометки нет",
         ((r.home, r.away), p.extra.get(pipeline.TITLE_PAIR)), (("Spain", "England"), None))
p = строка("Ndeshja: France-Turkey", "Spain - Zzyzx Rovers")
r = разбор(p)
проверка("эталон знает хоть одну сторону пары разборщика — пару не трогаем",
         ((r.home, r.away), p.extra.get(pipeline.TITLE_PAIR)), (("Spain", "Zzyzx Rovers"), None))
p = строка("Qwerty Town-Asdfgh City", "Zzyzx Rovers - Xyzzy United")
r = разбор(p)
проверка("пару из заголовка эталон не подтвердил — остаётся пара разборщика",
         ((r.home, r.away), p.extra.get(pipeline.TITLE_PAIR)),
         (("Zzyzx Rovers", "Xyzzy United"), None))
p = строка("Spain-England", ОБРЫВОК, час=9)
r = разбор(p)
проверка("в заголовке настоящая пара, но матч у эталона в другое время — не трогаем",
         p.extra.get(pipeline.TITLE_PAIR), None)
p = строка("Spain-England", ОБРЫВОК)
r = разбор(p, reference=None)
проверка("эталона нет — всё как раньше", p.extra.get(pipeline.TITLE_PAIR), None)
p = строка("Klasika: Spain-England, 2003/04", ОБРЫВОК)
r = разбор(p)
проверка("в заголовке прошлый сезон (классика) — не трогаем", p.extra.get(pipeline.TITLE_PAIR), None)
проверка("отсев пару не принял — правило не зовётся (это путь `ask_reference`)",
         pipeline.title_over_pair(строка("Spain-England", " "), live.Verdict(False, "не видно пары команд"),
                                  ЭТАЛОН, datetime(2026, 11, 15, 21, 45)), None)

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

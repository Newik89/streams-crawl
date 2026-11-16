# -*- coding: utf-8 -*-
r"""Книга 145 (16.11.2026): сведённое имя трансляции турнира вытесняет сырой
заголовок, под которым игра попала в базу раньше.

После выкладки книги 138 разбор сводит трансляции турнира в «ATP Finals
Turin» + служебная сторона. Но игра базы, заведённая раньше под заголовком,
разрезанным по тире («ATP» — «Nitto ATP Finals»), находилась по каналам и
оставалась со старыми именами: каналы к ней прибавились (20 вместо 4), а на
витрине подпись прежняя. Правило — `store.tournament_renamed`, 1–3.
В сеть не ходит, база временная. Запуск: python scripts/test_turnir_imya_v_baze.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="turnir-imya-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import broadcast, db, store  # noqa: E402

зелёных = красных = 0
ДЕНЬ = (date.today() + timedelta(days=1)).isoformat()
ЧАСЫ = datetime.combine(date.today(), datetime.min.time()).replace(hour=12)


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def игра(home, away, строки, час="12:30", sport="T"):
    return {"sport": sport, "league": "", "home": home, "away": away,
            "start_kyiv": f"{ДЕНЬ}T{час}", "start_utc": f"{ДЕНЬ}T10:30",
            "entries": [{"source": сайт, "channel": канал, "url": "", "raw_title": заголовок}
                        for сайт, канал, заголовок in строки]}


db.init_db()
conn = db.connect()
for n, (домен, имя) in enumerate((("tvmatchen.nu", "TV-matchen"), ("ipko.tv", "IPKO"), ("teleman.pl", "Teleman")), 1):
    conn.execute("INSERT INTO sources (id, domain, name, base_url, country, enabled) VALUES (?, ?, ?, ?, 'XX', 1)",
                 (n, домен, имя, f"https://{домен}/"))
conn.commit()


def события():
    return [(r["team_home_auto"], r["team_away_auto"], r["n"]) for r in conn.execute(
        "SELECT e.team_home_auto, e.team_away_auto, COUNT(ec.id) AS n FROM events e "
        "LEFT JOIN event_channels ec ON ec.event_id = e.id GROUP BY e.id ORDER BY e.id")]


print("Сведённое имя вытесняет сырой заголовок (`store.tournament_renamed`), правила 1–3")
store.save_games(conn, [игра("ATP", "Nitto ATP Finals", [("tvmatchen.nu", "TV4 Tennis", "ATP: Nitto ATP Finals")])],
                 now=ЧАСЫ)
до = события()
store.save_games(conn, [игра("ATP Finals Turin", broadcast.SESSION,
                             [("tvmatchen.nu", "TV4 Tennis", "ATP: Nitto ATP Finals"),
                              ("ipko.tv", "SuperSport 4", "Tenis ATP Torino 2026")])], now=ЧАСЫ)
проверка("игра нашлась по каналу, второй канал прибавился, имена стали сведёнными — строка одна",
         (до, события()), ([("ATP", "Nitto ATP Finals", 1)], [("ATP Finals Turin", broadcast.SESSION, 2)]))
проверка("правило 2: уже сведённую игру другой заголовок не переименовывает",
         store.tournament_renamed(игра("Другой заголовок", broadcast.SESSION, []),
                                  {"team_home_auto": "ATP Finals Turin", "team_away_auto": broadcast.SESSION,
                                   "flags": None}), False)


class Строка(dict):
    """Игра базы для проверки правила без заливки."""


def нашлась(home, away, flags=None):
    return Строка(team_home_auto=home, team_away_auto=away, flags=flags)


сведённая = игра("ATP Finals Turin", broadcast.SESSION, [])
проверка("правило 1: пришла не сведённая трансляция (заголовок с тире, матч с игроками) — имён не трогаем",
         [store.tournament_renamed(игра("ATP 500 Tokyo", "1/4 Finale", []), нашлась("ATP", "Nitto ATP Finals")),
          store.tournament_renamed(игра("Alcaraz C.", "Tiafoe F.", []), нашлась("ATP", "Nitto ATP Finals"))],
         [False, False])
проверка("правило 2: игра базы — матч с игроками или с меткой эталона — трансляцией не становится",
         [store.tournament_renamed(сведённая, нашлась("Alcaraz C.", "Tiafoe F.")),
          store.tournament_renamed(сведённая, нашлась("ATP", "Nitto ATP Finals", "fs:abc")),
          store.tournament_renamed(сведённая, нашлась("ATP", "Nitto ATP Finals"))],
         [False, False, True])
проверка("не теннис — правило молчит",
         store.tournament_renamed(игра("ATP Finals Turin", broadcast.SESSION, [], sport="F"),
                                  нашлась("ATP", "Nitto ATP Finals")), False)
conn.close()

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

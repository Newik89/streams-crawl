# -*- coding: utf-8 -*-
r"""Книга 148 (16.11.2026): строка турнира в базе не раздваивается, двойники
вливаются в неё, подпись лиги — из сведённой игры файла.

Утро 16.11, витрина: рядом с новой «ATP Finals Turin» (22 канала) висели
старые «ATP — Nitto ATP Finals» и «ATP Finals — parovi» с одним каналом Sport
Klub 2, а под строкой турнира 20.11 стояла чужая лига «ATP - SINGLES:
Stockholm». Причины и правила:
  * точечный обход одного сайта приносил сведённую трансляцию с одной
    отметкой, прежняя строка по одной отметке не находилась — заводилась
    вторая (`store._title_event`, правила 1–4);
  * следующий полный сбор по имени садился во вторую, большая прежняя
    оставалась двойником (`store._fold_title_twins`, правила 1–3);
  * лига строки турнира оставалась той, с которой она когда-то пришла с
    первого сайта (`store.save_games`: у сведённой трансляции лига — из файла).
В сеть не ходит, база временная. Запуск: python scripts/test_stroka_turnira_v_baze.py
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
TMP = Path(tempfile.mkdtemp(prefix="stroka-turnira-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import broadcast, db, store  # noqa: E402

зелёных = красных = 0
ДЕНЬ = (date.today() + timedelta(days=1)).isoformat()
ЧАСЫ = datetime.combine(date.today(), datetime.min.time()).replace(hour=12)
ТУРИН = "ATP - SINGLES: Finals - Turin (World), hard (indoor)"
САЙТЫ = ("tvmatchen.nu", "ipko.tv", "teleman.pl", "sportklub.hr", "mojtv.hr")


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def игра(home, away, строки, час="12:30", sport="T", league=""):
    return {"sport": sport, "league": league, "home": home, "away": away,
            "start_kyiv": f"{ДЕНЬ}T{час}", "start_utc": f"{ДЕНЬ}T10:30",
            "entries": [{"source": сайт, "channel": канал, "url": "", "raw_title": заголовок}
                        for сайт, канал, заголовок in строки]}


def новая_база():
    """Чистая временная база с пятью сайтами."""
    path = TMP / f"t{len(list(TMP.glob('*.db')))}.db"
    os.environ["STREAMS_DB"] = str(path)
    db.init_db()
    conn = db.connect()
    for n, домен in enumerate(САЙТЫ, 1):
        conn.execute("INSERT INTO sources (id, domain, name, base_url, country, enabled) VALUES (?, ?, ?, ?, 'XX', 1)",
                     (n, домен, домен, f"https://{домен}/"))
    conn.commit()
    return conn


def события(conn):
    return [(r["team_home_auto"], r["team_away_auto"], r["n"]) for r in conn.execute(
        "SELECT e.team_home_auto, e.team_away_auto, COUNT(ec.id) AS n FROM events e "
        "LEFT JOIN event_channels ec ON ec.event_id = e.id GROUP BY e.id ORDER BY e.id")]


БОЛЬШАЯ = [("tvmatchen.nu", "TV4 Tennis", "Nitto ATP Finals"), ("ipko.tv", "SuperSport 4", "Tenis ATP Torino 2026"),
           ("teleman.pl", "Polsat Sport 1", "Tenis: Turniej ATP Finals w Turynie"),
           ("sportklub.hr", "Sport Klub 2", "ATP Finale (Torino): Parovi")]
ОДНА = [("sportklub.hr", "Sport Klub 2", "ATP Finale (Torino): Parovi")]

print("Точечный обход не заводит вторую строку турнира (`store._title_event`)")
conn = новая_база()
store.save_games(conn, [игра("ATP", "Nitto ATP Finals", БОЛЬШАЯ)], now=ЧАСЫ)
store.save_games(conn, [игра("ATP Finals Turin", broadcast.SESSION, ОДНА, league=ТУРИН)], now=ЧАСЫ, punish=False)
проверка("правила 1–3: сведённая трансляция с одной отметкой садится в прежнюю строку турнира и даёт ей имя",
         события(conn), [("ATP Finals Turin", broadcast.SESSION, 4)])
проверка("правило 3: отметки игры файла у кандидата нет (другой канал в ту же минуту) — это другая трансляция",
         store._title_event(conn, игра("WTA Finals Indian Wells", broadcast.SESSION,
                                       [("mojtv.hr", "Arena Tenis", "WTA Finals")]), store._sources_by_domain(conn)), None)
проверка("правило 1: игра файла — матч с игроками — правило молчит",
         store._title_event(conn, игра("Alcaraz C.", "Tiafoe F.", ОДНА), store._sources_by_domain(conn)), None)
проверка("правило 2: кандидат — только трансляция турнира той же минуты (в 15:30 её нет)",
         store._title_event(conn, игра("ATP Finals Turin", broadcast.SESSION, ОДНА, час="15:30"),
                            store._sources_by_domain(conn)), None)
conn.close()

print("Двойники сведённой трансляции вливаются в неё (`store._fold_title_twins`)")
conn = новая_база()
# состояние базы утром 16.11: большая прежняя строка, строка агрегатора и
# маленькая сведённая, которую завёл точечный обход старым кодом
store.save_games(conn, [игра("ATP", "Nitto ATP Finals", БОЛЬШАЯ)], now=ЧАСЫ)
store.save_games(conn, [игра("ATP Finals", "parovi", [("mojtv.hr", "Sport Klub 2", "ATP Finals (Torino) - parovi")])],
                 now=ЧАСЫ, punish=False)
conn.execute("INSERT INTO events (sport, league_auto, team_home_auto, team_away_auto, start_utc, start_kyiv, last_seen) "
             "VALUES ('T', 'tenis Tenis Ziua 6', 'ATP Finals Turin', ?, ?, ?, ?)",
             (broadcast.SESSION, f"{ДЕНЬ} 10:30:00", f"{ДЕНЬ} 12:30:00", f"{ДЕНЬ} 04:06:00"))
conn.commit()
проверка("до заливки в базе три строки одного турнира в одну минуту", len(события(conn)), 3)
stats = store.save_games(conn, [игра("ATP Finals Turin", broadcast.SESSION, БОЛЬШАЯ, league=ТУРИН)], now=ЧАСЫ,
                         punish=False)
проверка("правила 1–3: после полного сбора строка одна, отметки двойников переехали в неё (4 своих + агрегатор)",
         (события(conn), stats.titles_folded), ([("ATP Finals Turin", broadcast.SESSION, 5)], 2))
проверка("подпись лиги сведённой строки — из файла (название турнира у эталона), а не старая лига сайта",
         conn.execute("SELECT league_auto FROM events").fetchone()[0], ТУРИН)
store.save_games(conn, [игра("ATP Finals Turin", broadcast.SESSION, БОЛЬШАЯ, league="")], now=ЧАСЫ, punish=False)
проверка("турнира в эталоне нет — подпись пустая, прежняя не залипает",
         tuple(conn.execute("SELECT league_auto, league_id FROM events").fetchone()), ("", None))
conn.close()

conn = новая_база()
store.save_games(conn, [игра("ATP Finals Turin", broadcast.SESSION, БОЛЬШАЯ[:2])], now=ЧАСЫ)
store.save_games(conn, [игра("WTA", "WTA Finals", [("mojtv.hr", "Arena Tenis", "WTA Finals")])], now=ЧАСЫ, punish=False)
store.save_games(conn, [игра("Alcaraz C.", "Tiafoe F.", [("teleman.pl", "Polsat Sport 1", "Alcaraz - Tiafoe")])],
                 now=ЧАСЫ, punish=False)
stats = store.save_games(conn, [игра("ATP Finals Turin", broadcast.SESSION, БОЛЬШАЯ)], now=ЧАСЫ, punish=False)
проверка("правило 2: трансляция другого турнира на другом канале и матч с игроками в ту же минуту — не двойники",
         (sorted(события(conn)), stats.titles_folded),
         (sorted([("ATP Finals Turin", broadcast.SESSION, 4), ("WTA", "WTA Finals", 1), ("Alcaraz C.", "Tiafoe F.", 1)]), 0))
conn.close()

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

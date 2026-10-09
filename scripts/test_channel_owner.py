# -*- coding: utf-8 -*-
"""Проверки правила «свой сайт канала важнее агрегатора» — по одной на правило.

Запуск: venv\\Scripts\\python.exe scripts/test_channel_owner.py
К сети не обращается, база — временная в памяти.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="owner-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test0.db")

from app import channel_owner, db, store  # noqa: E402

#: своя база на каждый вызов `база()` — миграции накатывает `db.connect`
_счёт = [0]

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def день(n: int) -> str:
    """Дата заливки от сегодняшнего дня: `save_games(now=None)` смотрит на
    настоящие часы, и зашитые «2026-10-08» назавтра ушли в прошлое — 09.10
    тест покраснел сам по себе. 0 — сегодня, 3 — через три дня."""
    return (date.today() + timedelta(days=n)).isoformat()


def база() -> sqlite3.Connection:
    _счёт[0] += 1
    os.environ["STREAMS_DB"] = str(TMP / f"test{_счёт[0]}.db")
    conn = db.connect()
    db.init_db(conn)
    conn.execute(
        "INSERT INTO sources (id, domain, name, base_url, country, enabled, "
        "selector_config) VALUES (1, 'sportklub.hr', 'Sport Klub', "
        "'https://sportklub.hr/', 'HR', 1, ?)",
        (json.dumps({channel_owner.ФЛАГ: True}),))
    conn.execute(
        "INSERT INTO sources (id, domain, name, base_url, country, enabled) "
        "VALUES (2, 'mojtv.hr', 'MojTV', 'https://mojtv.hr/', 'HR', 1)")
    conn.execute(
        "INSERT INTO channels (id, canonical_name, slug, country) "
        "VALUES (51, 'Sport Klub 1', 'sport-klub-1-hr', 'HR')")
    conn.execute(
        "INSERT INTO channels (id, canonical_name, slug, country) "
        "VALUES (52, 'MAX Sport 1', 'max-sport-1-hr', 'HR')")
    conn.commit()
    return conn


def прошлый_сбор(conn, день: str, когда: str) -> None:
    """Как будто официальный сайт уже приносил этот день: алиас канала от
    него и отметка на игре с меткой «видели `когда`»."""
    conn.execute("INSERT OR IGNORE INTO channel_aliases (channel_id, alias, "
                 "source_id) VALUES (51, 'Sport Klub 1', 1)")
    cur = conn.execute(
        "INSERT INTO events (sport, league_auto, team_home_auto, "
        "team_away_auto, start_utc, start_kyiv, last_seen) "
        "VALUES ('F', 'Liga', 'C', 'D', ?, ?, ?)",
        (f"{день} 17:00", f"{день} 20:00", когда))
    conn.execute("INSERT INTO event_channels (event_id, channel_id, "
                 "source_id, source_url, raw_title, last_seen, miss_count) "
                 "VALUES (?, 51, 1, '', '', ?, 0)", (cur.lastrowid, когда))
    conn.commit()


def игра(день: str, строки: list[tuple[str, str]]) -> dict:
    return {"sport": "F", "league": "Liga", "home": "A", "away": "B",
            "start_kyiv": f"{день}T20:00", "start_utc": f"{день}T17:00",
            "entries": [{"source": сайт, "channel": канал, "url": "",
                         "raw_title": f"{канал}: A - B"}
                        for сайт, канал in строки]}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("Правило «свой сайт канала важнее агрегатора»")

    conn = база()
    проверка("официальным помечен один источник",
             sorted(channel_owner.официальные(conn).values()), ["sportklub.hr"])

    # глубина своего сайта в этом сборе: 08 и 09 октября
    х = channel_owner.Хозяева(conn)
    х.учесть(1, 51, "2026-10-08")
    х.учесть(1, 51, "2026-10-09")
    проверка("правило 1: строка своего сайта — берём", х.почему(1, 51, "2026-10-09"), 1)
    проверка("правило 2: у канала нет своего сайта — берём",
             х.почему(2, 52, "2026-10-08"), 2)
    проверка("правило 3: день в глубине своего сайта — не берём",
             х.почему(2, 51, "2026-10-09"), 3)
    проверка("правило 3: и более близкий день тоже не берём",
             х.почему(2, 51, "2026-10-07"), 3)
    проверка("правило 4: день дальше глубины — берём",
             х.почему(2, 51, "2026-10-10"), 4)
    проверка("пропустить считает строки", (х.пропустить(2, 51, "2026-10-09", "mojtv.hr"),
                                           х.пропустить(2, 51, "2026-10-10", "mojtv.hr"),
                                           х.пропущено),
             (True, False, {"mojtv.hr": 1}))
    проверка("в отчёте видно сайт", "mojtv.hr: 1" in х.отчёт(), True)

    # свой сайт в сборе молчит целиком — агрегатор берём весь
    пусто = channel_owner.Хозяева(conn)
    проверка("свой сайт не дал ничего — агрегатор берём",
             пусто.почему(2, 51, "2026-10-09"), 2)
    проверка("без официальных источников отчёт пуст", пусто.отчёт(), "")

    # глубина по БАЗЕ: сбор без своего сайта вовсе (так сервер качает mojtv)
    сейчас = datetime(2026, 10, 7, 9, 0)
    conn3 = база()
    прошлый_сбор(conn3, "2026-10-09", "2026-10-07 08:15")
    из_базы = channel_owner.Хозяева(conn3, сейчас)
    проверка("база: канал признан своим у официального сайта",
             из_базы.хозяин.get(51), {1})
    проверка("база: глубина взята из отметок",
             из_базы.глубина.get(1), "2026-10-09")
    проверка("база: день в глубине — строку агрегатора не берём",
             из_базы.почему(2, 51, "2026-10-08"), 3)
    проверка("база: дальний день — берём", из_базы.почему(2, 51, "2026-10-10"), 4)

    conn4 = база()
    прошлый_сбор(conn4, "2026-10-09", "2026-10-05 08:15")      # старше 30 ч
    старое = channel_owner.Хозяева(conn4, сейчас)
    проверка("база: устаревшую отметку за глубину не считаем",
             старое.глубина.get(1), None)
    проверка("база: тогда строку агрегатора берём",
             старое.почему(2, 51, "2026-10-08"), 4)

    # сквозная заливка: «сегодня» (день(0)) есть у своего сайта, +3 дня — только у mojtv
    conn2 = база()
    stats = store.save_games(conn2, [
        игра(день(0), [("sportklub.hr", "Sport Klub 1"),
                            ("mojtv.hr", "Sport Klub 1"),
                            ("mojtv.hr", "MAX Sport 1")]),
        игра(день(3), [("mojtv.hr", "Sport Klub 1")]),
    ], now=None)
    отметки = {(r["domain"], r["canonical_name"], r["start_kyiv"][:10])
               for r in conn2.execute(
                   "SELECT s.domain, c.canonical_name, e.start_kyiv "
                   "FROM event_channels ec JOIN sources s ON s.id = ec.source_id "
                   "JOIN channels c ON c.id = ec.channel_id "
                   "JOIN events e ON e.id = ec.event_id")}
    проверка("заливка: свой сайт записан",
             ("sportklub.hr", "Sport Klub 1", день(0)) in отметки, True)
    проверка("заливка: агрегатор по этому каналу и дню НЕ записан",
             ("mojtv.hr", "Sport Klub 1", день(0)) in отметки, False)
    проверка("заливка: чужой канал агрегатора записан",
             ("mojtv.hr", "MAX Sport 1", день(0)) in отметки, True)
    проверка("заливка: дальний день агрегатора записан",
             ("mojtv.hr", "Sport Klub 1", день(3)) in отметки, True)
    проверка("заливка: счётчик непринятых строк", stats.not_own, 1)

    # прежняя отметка агрегатора снимается: иначе висела бы вечно — гашение
    # её не возьмёт (у сайта «пропала» разом вся линейка, правило 6 miss.py)
    # у игры есть и чужой канал агрегатора — значит пустой она не останется
    conn5 = база()
    строки5 = [("mojtv.hr", "Sport Klub 1"), ("mojtv.hr", "MAX Sport 1")]
    без_правила = store.save_games(conn5, [игра(день(0), строки5)],
                                   now=None)
    conn5.execute("UPDATE sources SET selector_config = ? WHERE id = 1",
                  (json.dumps({channel_owner.ФЛАГ: True}),))
    conn5.commit()
    прошлый_сбор(conn5, день(1), datetime.now().strftime("%Y-%m-%d %H:%M"))
    с_правилом = store.save_games(conn5, [игра(день(0), строки5)],
                                  now=None)
    осталось = {r["canonical_name"] for r in conn5.execute(
        "SELECT c.canonical_name FROM event_channels ec "
        "JOIN channels c ON c.id = ec.channel_id "
        "JOIN sources s ON s.id = ec.source_id JOIN events e "
        "ON e.id = ec.event_id WHERE s.domain = 'mojtv.hr' "
        f"AND e.start_kyiv LIKE '{день(0)}%'")}
    проверка("прежняя отметка агрегатора снята",
             (без_правила.not_own, с_правилом.not_own_dropped, осталось),
             (0, 1, {"MAX Sport 1"}))
    проверка("в отчёте видно, сколько снято",
             "снято прежних отметок: 1" in с_правилом.not_own_note, True)

    # у игры только строка агрегатора и других каналов нет — берём её:
    # пустая запись на витрине хуже канала с агрегатора
    conn6 = база()
    прошлый_сбор(conn6, день(1), datetime.now().strftime("%Y-%m-%d %H:%M"))
    один = store.save_games(conn6, [
        игра(день(0), [("mojtv.hr", "Sport Klub 1")])], now=None)
    есть = conn6.execute(
        "SELECT COUNT(*) FROM event_channels ec JOIN sources s "
        "ON s.id = ec.source_id JOIN events e ON e.id = ec.event_id "
        f"WHERE s.domain = 'mojtv.hr' AND e.start_kyiv LIKE '{день(0)}%'"
    ).fetchone()[0]
    проверка("единственную строку игры правило не отбирает",
             (один.not_own, есть), (0, 1))

    # а когда у той же игры есть и свой канал — строку агрегатора не берём
    conn7 = база()
    прошлый_сбор(conn7, день(1), datetime.now().strftime("%Y-%m-%d %H:%M"))
    пара = store.save_games(conn7, [
        игра(день(0), [("sportklub.hr", "Sport Klub 1"),
                            ("mojtv.hr", "Sport Klub 1")])], now=None)
    проверка("рядом со своим каналом строка агрегатора не берётся",
             пара.not_own, 1)

    # хвосты: отметки агрегатора, которых в файле уже нет, за дни в глубине
    # хозяина снимаются; за дни дальше — остаются; единственный канал игры —
    # остаётся
    conn8 = база()
    # хвосты рождаются ДО того, как у канала появился хозяин: сначала
    # заливка без отметки official, потом она ставится
    conn8.execute("UPDATE sources SET selector_config = NULL WHERE id = 1")
    conn8.commit()
    store.save_games(conn8, [
        игра(день(0), [("mojtv.hr", "Sport Klub 1"),
                            ("mojtv.hr", "MAX Sport 1")]),   # хвост с соседом
        игра(день(4), [("mojtv.hr", "Sport Klub 1"),
                            ("mojtv.hr", "MAX Sport 1")]),   # дальше глубины
    ], now=None)
    conn8.execute("UPDATE sources SET selector_config = ? WHERE id = 1",
                  (json.dumps({channel_owner.ФЛАГ: True}),))
    conn8.commit()
    прошлый_сбор(conn8, день(1), datetime.now().strftime("%Y-%m-%d %H:%M"))
    хвосты = store.save_games(conn8, [
        игра(день(2), [("mojtv.hr", "Sport Klub 1")])], now=None)  # одиночка
    остались = sorted((r["start_kyiv"][:10], r["canonical_name"]) for r in conn8.execute(
        "SELECT e.start_kyiv, c.canonical_name FROM event_channels ec "
        "JOIN channels c ON c.id = ec.channel_id JOIN sources s "
        "ON s.id = ec.source_id JOIN events e ON e.id = ec.event_id "
        "WHERE s.domain = 'mojtv.hr' AND ec.miss_count = 0"))
    проверка("хвост в глубине снят, дальний и одиночка остались",
             остались, [(день(0), "MAX Sport 1"),
                        (день(2), "Sport Klub 1"),
                        (день(4), "MAX Sport 1"),
                        (день(4), "Sport Klub 1")])
    проверка("снятый хвост посчитан", хвосты.not_own_dropped, 1)
    проверка("заливка: строка для журнала есть",
             "mojtv.hr: 1" in stats.not_own_note, True)

    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, "
          f"красных: {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

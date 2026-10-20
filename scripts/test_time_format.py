# -*- coding: utf-8 -*-
r"""Время игры в базе — один формат; подтягивание к эталону — по сайтам
(разбор владельца 12.10.2026, дубль Lokomotiv Moscow — Krasnodar #5904/#6039).

Что случилось: ночная чистка (`canon_backfill.py`) записала время #5904 как
«2026-10-17T19:30» (через «T»), а заливка ищет игру в окне по ТЕКСТУ
«2026-10-17 16:00 … 21:00» (через пробел): «T» по алфавиту дальше пробела —
#5904 выпал из окна, скан даты 17.10 завёл дубль #6039, каналы #5904 погасли.
Второе: время 18:30 у игры не подтянулось к эталонному 19:30, потому что
`canon.retime` считал строки (4), а не сайты (2) — «большинство» за 18:30
было одним каналом «Матч ТВ» под двумя именами.

Что держит:
  1. `store.db_time` — к виду базы; `normalize_times` чинит записи с «T».
  2. Заливка находит игру, чьё время в базе записано с «T»: дубля нет,
     каналы прежней игры живы.
  3. `canon.retime` считает сайты: 4 строки с двух сайтов — время подтянуто;
     три сайта — нет.
  4. `canon.stamp` ставит метку flashscore игре, хотя в файле время с «T».
  5. Все места, что пишут время игры в базу, идут через `db_time`/`_iso`.

В сеть не ходит, база — временная:
    python scripts/test_time_format.py
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="time-test-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import canon, db, store  # noqa: E402

зелёных = красных = 0
ДЕНЬ = (date.today() + timedelta(days=5)).isoformat()
ЧАСЫ = datetime.combine(date.today(), datetime.min.time()).replace(hour=12)


def utc(kyiv_hhmm: str) -> str:
    """Киевское «ЧЧ:ММ» дня ДЕНЬ → «ДЕНЬ ЧЧ:ММ» по UTC — часами зоны, а не
    «+3 летом»: 25.10.2026 — день перевода часов, и угадывание по месяцу
    красило тест (20.10)."""
    from zoneinfo import ZoneInfo
    when = datetime.fromisoformat(f"{ДЕНЬ}T{kyiv_hhmm}").replace(
        tzinfo=ZoneInfo("Europe/Kyiv"))
    return when.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def база() -> sqlite3.Connection:
    conn = db.connect()
    db.init_db(conn)
    conn.execute("INSERT INTO sources (id, domain, name, base_url, country, enabled) "
                 "VALUES (1, 'ntvplus.tv', 'НТВ+', 'https://ntvplus.tv/', 'RU', 1)")
    conn.execute("INSERT INTO sources (id, domain, name, base_url, country, enabled) "
                 "VALUES (2, 'tvarenasport.com', 'Arena', 'https://www.tvarenasport.com/', 'RS', 1)")
    for cid, name, src in ((51, "Матч ТВ", 1), (52, "МАТЧ ПРЕМЬЕР HD", 1), (53, "Arena Sport 6", 2)):
        conn.execute("INSERT INTO channels (id, canonical_name, slug, country) VALUES (?, ?, ?, 'RU')",
                     (cid, name, f"ch-{cid}"))
        conn.execute("INSERT INTO channel_aliases (channel_id, alias, source_id) VALUES (?, ?, ?)",
                     (cid, name, src))
    conn.commit()
    return conn


def игра(home: str, hhmm: str, строки) -> dict:
    return {"sport": "F", "league": "RUSSIA: Premier League", "home": home,
            "away": "Krasnodar", "start_kyiv": f"{ДЕНЬ}T{hhmm}", "start_utc": "",
            "entries": [{"source": s, "channel": c, "url": "", "raw_title": f"{c}: {home} - Krasnodar"}
                        for s, c in строки]}


СТРОКИ = [("ntvplus.tv", "Матч ТВ"), ("ntvplus.tv", "МАТЧ ПРЕМЬЕР HD"),
          ("tvarenasport.com", "Arena Sport 6")]


def main() -> int:
    print("1. один вид времени в базе")
    проверка("db_time: «T» → пробел", store.db_time("2026-10-17T19:30"), "2026-10-17 19:30")
    проверка("db_time: секунды и Z срезаны", store.db_time("2026-10-17T16:30:00Z"), "2026-10-17 16:30")
    проверка("db_time: уже в виде базы — как есть", store.db_time("2026-10-17 19:30"), "2026-10-17 19:30")

    print("2. заливка находит игру, чьё время записано с «T» (дубль #5904/#6039)")
    conn = база()
    store.save_games(conn, [игра("Lokomotiv Moscow", "19:30", СТРОКИ)], now=ЧАСЫ)
    (eid,) = conn.execute("SELECT id FROM events").fetchone()
    # так писала ночная чистка до 12.10: время из файла, через «T»
    conn.execute("UPDATE events SET start_kyiv = ? WHERE id = ?", (f"{ДЕНЬ}T19:30", eid))
    conn.commit()
    проверка("до заливки: поиск в окне находит игру с «T»",
             (store._find_event(conn, игра("Lokomotiv", "18:30", [])) or {"id": None})["id"], eid)
    stats = store.save_games(conn, [игра("Lokomotiv", "19:30", СТРОКИ)], now=ЧАСЫ)
    events = conn.execute("SELECT id, start_kyiv FROM events").fetchall()
    проверка("скан даты той же игры — дубля нет", len(events), 1)
    проверка("время в базе приведено к виду с пробелом", events[0]["start_kyiv"], f"{ДЕНЬ} 19:30")
    проверка("заливка посчитала починку времени", stats.times_fixed, 1)
    живые = conn.execute("SELECT COUNT(*) FROM event_channels WHERE event_id = ? "
                         "AND COALESCE(miss_count, 0) = 0", (eid,)).fetchone()[0]
    проверка("каналы прежней игры живы", живые, 3)
    conn.close()

    print("3. подтягивание к эталону считает сайты, а не строки")
    ref = {"home": "Lokomotiv Moscow", "away": "Krasnodar", "start_kyiv": f"{ДЕНЬ}T19:30", "fs_id": "E3Nc1pbS"}
    четыре = игра("Lokomotiv", "18:30", [("ntvplus.tv", "Матч ТВ"), ("ntvplus.tv", "Телеканал «Матч ТВ»"),
                                          ("ntvplus.tv", "МАТЧ ПРЕМЬЕР HD"), ("tvarenasport.com", "Arena Sport 6")])
    проверка("4 строки с двух сайтов — время подтянуто к эталону",
             (canon.retime({"sure": [(четыре, ref, 100)]}), четыре["start_kyiv"]), (1, f"{ДЕНЬ}T19:30"))
    три = игра("Lokomotiv", "18:30", [("ntvplus.tv", "Матч ТВ"), ("tvarenasport.com", "Arena Sport 6"),
                                       ("sportklub.hr", "Sport Klub 1")])
    проверка("три сайта за своё время — эталон не перебивает",
             (canon.retime({"sure": [(три, ref, 100)]}), три["start_kyiv"]), (0, f"{ДЕНЬ}T18:30"))

    print("4. метка flashscore — хотя в файле время через «T»")
    os.environ["STREAMS_DB"] = str(TMP / "t2.db")
    conn = база()
    файл = игра("Lokomotiv Moscow", "19:30", СТРОКИ)
    store.save_games(conn, [файл], now=ЧАСЫ)
    проверка("stamp нашёл игру", canon.stamp(conn, {"sure": [(файл, ref, 100)]}), 1)
    проверка("метка записана", conn.execute("SELECT flags FROM events").fetchone()[0], "fs:E3Nc1pbS")
    conn.close()

    print("6. игра с меткой flashscore находится по метке, а не по именам")
    os.environ["STREAMS_DB"] = str(TMP / "t3.db")
    conn = база()
    conn.execute("INSERT INTO sources (id, domain, name, base_url, country, enabled) "
                 "VALUES (3, 'nova.bg', 'Nova', 'https://nova.bg/', 'BG', 1)")
    conn.execute("INSERT INTO channels (id, canonical_name, slug, country) VALUES (54, 'Diema Sport 2', 'ch-54', 'BG')")
    conn.execute("INSERT INTO channel_aliases (channel_id, alias, source_id) VALUES (54, 'diemasport 2', 3)")
    conn.commit()
    англ = игра("Newcastle United FC", "19:30", [("tvarenasport.com", "Arena Sport 6")])
    англ["away"] = "Aston Villa FC"
    store.save_games(conn, [англ], now=ЧАСЫ)
    (eid,) = conn.execute("SELECT id FROM events").fetchone()
    conn.execute("UPDATE events SET flags = 'fs:KdQz25Ic' WHERE id = ?", (eid,))
    conn.commit()
    болг = {"sport": "F", "league": "Висша лига", "home": "Нюкасъл Юнайтед", "away": "Астън Вила",
            "start_kyiv": f"{ДЕНЬ}T19:30", "start_utc": "", "fs_id": "KdQz25Ic",
            "entries": [{"source": "nova.bg", "channel": "diemasport 2", "url": "", "raw_title": "Нюкасъл - Астън Вила"}]}
    stats = store.save_games(conn, [болг], now=ЧАСЫ)
    проверка("болгарские имена + метка — дубля нет", (stats.new, conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]), (0, 1))
    проверка("канал болгарского сайта лёг на игру с меткой",
             conn.execute("SELECT COUNT(*) FROM event_channels WHERE event_id = ? AND channel_id = 54", (eid,)).fetchone()[0], 1)
    проверка("имена игры остались латиницей",
             tuple(conn.execute("SELECT team_home_auto, team_away_auto FROM events").fetchone()),
             ("Newcastle United FC", "Aston Villa FC"))
    без_метки = dict(болг, fs_id="", home="Нюкасъл Юнайтед", entries=[])
    проверка("без метки поиск идёт как раньше (по именам и времени)",
             store._fs_event(conn, без_метки), None)
    # flashscore перенёс матч на 20:00 — игра, найденная по метке, встаёт на
    # время эталона, а не замирает на прежнем (независимая проверка 12.10)
    перенос = dict(болг, start_kyiv=f"{ДЕНЬ}T20:00", fs_start=f"{ДЕНЬ}T20:00")
    store.save_games(conn, [перенос], now=ЧАСЫ)
    проверка("по метке: время игры — эталонное (перенос на 20:00)",
             tuple(conn.execute("SELECT start_kyiv, start_utc FROM events WHERE id = ?", (eid,)).fetchone()),
             (f"{ДЕНЬ} 20:00", utc("20:00")))
    # две игры с одной меткой (дубль уже есть) — поиск по метке молчит,
    # дальше обычный путь; ничего не падает
    conn.execute("INSERT INTO events (sport, team_home_auto, team_away_auto, start_utc, start_kyiv, "
                 "last_seen, flags) VALUES ('F', 'X', 'Y', ?, ?, ?, 'fs:KdQz25Ic')",
                 (f"{ДЕНЬ} 16:30", f"{ДЕНЬ} 19:30", f"{ДЕНЬ} 10:00"))
    conn.commit()
    проверка("одна метка у двух игр — поиск по метке не выбирает наугад", store._fs_event(conn, болг), None)
    conn.close()

    print("8. витрина и время UTC (#5904 в конце дня, 12.10)")
    os.environ["STREAMS_DB"] = str(TMP / "t4.db")
    conn = база()
    store.save_games(conn, [игра("Lokomotiv Moscow", "19:30", СТРОКИ),
                            dict(игра("Spartak", "23:30", СТРОКИ), away="Zenit")], now=ЧАСЫ)
    ids = dict(conn.execute("SELECT team_home_auto, id FROM events").fetchall())
    conn.execute("UPDATE events SET start_kyiv = ?, start_utc = ? WHERE id = ?",
                 (f"{ДЕНЬ}T19:30", f"{ДЕНЬ} 15:30", ids["Lokomotiv Moscow"]))
    conn.commit()
    порядок = [g["id"] for g in store.schedule(conn) if g["date"].isoformat() == ДЕНЬ]
    проверка("витрина: игра с «T» стоит на своё время, а не в конце дня",
             порядок.index(ids["Lokomotiv Moscow"]) < порядок.index(ids["Spartak"]), True)
    проверка("самопочинка: «T» и разошедшееся UTC — две правки", store.normalize_times(conn), 2)
    проверка("UTC пересчитан из киевского",
             conn.execute("SELECT start_kyiv, start_utc FROM events WHERE id = ?",
                          (ids["Lokomotiv Moscow"],)).fetchone()[1],
             utc("19:30"))
    проверка("повторная самопочинка ничего не трогает", store.normalize_times(conn), 0)
    conn.close()

    print("7. возраст «Sub» и мелочи")
    from app import leagues, names
    проверка("«Sub 19.30» (время рядом) — не возраст", (leagues.category("MTV Sub 19.30"), names.category("MTV Sub 19:30")), ("", ""))
    проверка("«Benfica Sub-19» + U19 — метка не дописана второй раз",
             leagues.with_category("Benfica Sub-19", "U19"), "Benfica Sub-19")

    print("5. кто пишет время игры в базу — только через db_time/_iso")
    плохие = []
    for path in list((ROOT / "app").glob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        if path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"UPDATE events SET start_kyiv", text):
            # запрос и его значения — в ближайших строках после него
            рядом = text[m.end():m.end() + 450]
            if not re.search(r"db_time|_iso\(|%Y-%m-%d %H:%M", рядом):
                плохие.append(f"{path.name}:{text.count(chr(10), 0, m.start()) + 1}")
    проверка("все записи времени игры в базу — в виде базы", плохие, [])

    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""Бейдж «new» у канала: владельцу — до клика, гостю — по часам.

Слово владельца 08.10: «нужно, чтоб метки новых каналов не пропадали через
какое-то время, а исчезала тогда, если я клацнул на канал».

Запуск: venv\\Scripts\\python.exe scripts/test_fresh_marks.py
К сети не обращается, база — временная.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="fresh-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")

from app import db, store  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def utc(часов_назад: float) -> str:
    миг = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=часов_назад)
    return миг.strftime("%Y-%m-%d %H:%M:%S")


def готовим(conn, канал: str, игра_назад: float, канал_назад: float,
            seen: int) -> int:
    """Игра с одним каналом: когда появилась игра, когда — её канал."""
    cur = conn.execute(
        "INSERT INTO events (sport, league_auto, team_home_auto, "
        "team_away_auto, start_utc, start_kyiv, first_seen, last_seen) "
        "VALUES ('F', 'Liga', ?, 'Гости', ?, ?, ?, ?)",
        (канал, "2026-12-01 17:00", "2026-12-01 20:00",
         utc(игра_назад), utc(0)))
    event_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO channels (canonical_name, slug, country) "
        "VALUES (?, ?, 'XX')", (канал, канал.lower().replace(" ", "-")))
    channel_id = cur.lastrowid
    conn.execute(
        "INSERT INTO event_channels (event_id, channel_id, source_id, "
        "source_url, raw_title, first_seen, last_seen, miss_count, seen) "
        "VALUES (?, ?, 1, '', '', ?, ?, 0, ?)",
        (event_id, channel_id, utc(канал_назад), utc(0), seen))
    conn.commit()
    return event_id


def бейджи(admin: bool) -> dict[str, bool]:
    """Что увидит на витрине владелец (admin=True) или гость."""
    conn = db.connect()
    try:
        игры = store.schedule(conn)
    finally:
        conn.close()
    out = {}
    for g in игры:
        for c in g.get("channels", []):
            # то же условие, что в шаблоне `schedule.html`
            out[c["name"]] = bool((c["new_ever"] and not c["seen"]) if admin
                                  else c["new"])
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("Бейдж «new» у канала")
    conn = db.connect()
    db.init_db(conn)
    conn.execute("INSERT INTO sources (id, domain, name, base_url, country) "
                 "VALUES (1, 'test.tv', 'Тест', 'https://test.tv/', 'XX')")
    conn.commit()
    # канал добавился к игре 10 часов назад — свежий для всех
    готовим(conn, "Свежий", игра_назад=40, канал_назад=10, seen=0)
    # канал добавился 100 часов назад — по часам уже не новый
    готовим(conn, "Давний", игра_назад=200, канал_назад=100, seen=0)
    # давний, но владелец его уже кликнул
    готовим(conn, "Кликнутый", игра_назад=200, канал_назад=100, seen=1)
    # приехал вместе с игрой — не «добавился», бейджа нет ни у кого
    готовим(conn, "Вместе с игрой", игра_назад=10, канал_назад=10, seen=0)
    conn.close()

    владелец, гость = бейджи(admin=True), бейджи(admin=False)
    проверка("владелец: свежий канал — бейдж есть", владелец["Свежий"], True)
    проверка("владелец: давний некликнутый — бейдж ОСТАЁТСЯ",
             владелец["Давний"], True)
    проверка("владелец: кликнутый — бейджа нет", владелец["Кликнутый"], False)
    проверка("владелец: приехал вместе с игрой — бейджа нет",
             владелец["Вместе с игрой"], False)
    проверка("гость: свежий — бейдж есть", гость["Свежий"], True)
    проверка("гость: давний — бейдж погас по часам", гость["Давний"], False)
    проверка("гость: клик владельца ему не важен", гость["Кликнутый"], False)

    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, "
          f"красных: {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

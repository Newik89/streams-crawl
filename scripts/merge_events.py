# -*- coding: utf-8 -*-
r"""Слить две записи одной игры: каналы дубля переезжают в главную, дубль
удаляется. Время и имена остаются у главной — её выбирает владелец (правило
«время по flashscore»).

Кейс 07.09 (#994/#1442, ЖЧМ по баскетболу Япония — Испания): movistarplus
написал «Epaña», команда осталась без канона, строка не склеилась и не
получила метку flashscore — жила дублем со своим временем. Пока пакет B
аудита не научил склейку таким случаям, дубли сводятся этой командой.

    venv\Scripts\python.exe scripts/merge_events.py 994 1442            # показать, что будет
    venv\Scripts\python.exe scripts/merge_events.py 994 1442 --apply    # сделать
    … --apply --alias "Epaña W=Spain W"   # заодно закрепить имя, из-за которого
                                         # дубль возник, иначе следующий забор
                                         # заведёт его снова

Для той же пары канал+источник у обеих записей главной достаётся более
свежее состояние (меньший miss_count, поздний last_seen): иначе канал,
который последние заборы относили к дублю, у главной «пропал бы» и вскоре
спрятался по MISS_LIMIT.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402


def show(conn: sqlite3.Connection, event_id: int) -> dict | None:
    row = conn.execute("SELECT id, sport, start_kyiv, team_home_auto, "
                       "team_away_auto, team_home_id, team_away_id, flags "
                       "FROM events WHERE id=?", (event_id,)).fetchone()
    if row is None:
        print(f"#{event_id}: нет такой записи")
        return None
    channels = conn.execute(
        "SELECT ec.id, ec.channel_id, ec.source_id, ec.miss_count, ec.last_seen "
        "FROM event_channels ec WHERE ec.event_id=? ORDER BY ec.id",
        (event_id,)).fetchall()
    print(f"#{row['id']}: {row['start_kyiv']}  {row['team_home_auto']} — "
          f"{row['team_away_auto']}  [{row['sport']}] канон "
          f"{row['team_home_id']}/{row['team_away_id']}, метка {row['flags']}")
    for c in channels:
        print(f"    канал {c['channel_id']} источник {c['source_id']} "
              f"(miss {c['miss_count']}, видели {c['last_seen']})")
    return dict(row)


def merge(conn: sqlite3.Connection, main: int, dup: int, apply: bool) -> int:
    print("главная:")
    if show(conn, main) is None:
        return 1
    print("дубль:")
    if show(conn, dup) is None:
        return 1
    conflicts = conn.execute(
        "SELECT d.id AS did, m.id AS mid, d.miss_count AS dm, m.miss_count AS mm, "
        "d.last_seen AS dl, m.last_seen AS ml FROM event_channels d "
        "JOIN event_channels m ON m.channel_id=d.channel_id AND m.source_id=d.source_id "
        "WHERE d.event_id=? AND m.event_id=?", (dup, main)).fetchall()
    moving = conn.execute("SELECT COUNT(*) FROM event_channels WHERE event_id=?",
                          (dup,)).fetchone()[0] - len(conflicts)
    print(f"\nпереедут каналов: {moving}; уже есть у главной (обновим свежесть): "
          f"{len(conflicts)}; запись #{dup} будет удалена")
    if not apply:
        print("это был показ; чтобы сделать — добавьте --apply")
        return 0
    for r in conflicts:
        conn.execute("UPDATE event_channels SET miss_count=?, last_seen=? WHERE id=?",
                     (min(r["dm"], r["mm"]), max(r["dl"] or "", r["ml"] or ""),
                      r["mid"]))
    conn.execute("UPDATE OR IGNORE event_channels SET event_id=? WHERE event_id=?",
                 (main, dup))
    conn.execute("DELETE FROM event_channels WHERE event_id=?", (dup,))
    conn.execute("DELETE FROM events WHERE id=?", (dup,))
    conn.commit()
    print("\nготово. главная после слияния:")
    show(conn, main)
    print(f"#{dup} остался в базе: "
          f"{'да' if conn.execute('SELECT 1 FROM events WHERE id=?', (dup,)).fetchone() else 'нет'}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("main", type=int, help="id записи, которая остаётся")
    ap.add_argument("dup", type=int, help="id дубля, который вливается и удаляется")
    ap.add_argument("--apply", action="store_true", help="без него — только показ")
    ap.add_argument("--db", default="", help="другая база (проверка на копии)")
    ap.add_argument("--alias", default="",
                    help="закрепить «сырое имя=канон» (например \"Epaña W=Spain W\"), "
                         "чтобы дубль не возник снова; только с --apply")
    args = ap.parse_args()
    alias = ()
    if args.alias:
        raw, _, canon = args.alias.partition("=")
        if not raw.strip() or not canon.strip():
            print("--alias ждёт «сырое имя=канон»")
            return 1
        alias = (raw.strip(), canon.strip())
    if args.main == args.dup:
        print("это одна и та же запись")
        return 1
    if args.db:
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    else:
        conn = db.connect()
    try:
        code = merge(conn, args.main, args.dup, args.apply)
        if code == 0 and alias:
            if args.apply:
                team_id = dictionary.remember_team(conn, alias[0], alias[1])
                print(f"алиас «{alias[0]}» → {alias[1]} закреплён (team_id {team_id})")
            else:
                print(f"алиас «{alias[0]}» → {alias[1]} — закрепится с --apply")
        return code
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

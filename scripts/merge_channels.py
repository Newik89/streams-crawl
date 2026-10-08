# -*- coding: utf-8 -*-
r"""Слить две записи одного канала: всё, что есть у дубля, переезжает к
главному, дубль удаляется. Имя, страна, пометка и «правил владелец» остаются
у главного — его выбирает владелец.

Кейс 08.10 (#496/#498): норвежский TV 2 Direkte жил двумя строками —
«NO TV 2 Direkte» (переименовал владелец; с allente.no пришёл как «TV 2
Direkte HD») и «TV 2 Direkte» (с tv2.no). Канал опознаётся парой (имя,
страна), и чужое написание с другого сайта завело вторую строку; у каждой
было по две отметки, на витрине это выглядело как два канала. Слово
владельца: склеить под «NO TV 2 Direkte».

    venv\Scripts\python.exe scripts/merge_channels.py 496 498           # показать
    venv\Scripts\python.exe scripts/merge_channels.py 496 498 --apply   # сделать
    … --db /tmp/proba.db                                  # сперва на копии

Что переезжает: написания с сайтов (`channel_aliases`), строки карточек
источников (`source_channels`), ссылки справочников (`directory_channels`)
и отметки игр (`event_channels`). Если у игры этот канал уже есть от того же
сайта и у главного, и у дубля — остаётся запись главного с более свежим
состоянием (меньший `miss_count`, поздний `last_seen`), как при слиянии игр
(`merge_events.py`). Дальше заливка сама ведёт новые написания к главному:
алиас дубля теперь указывает на него.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def show(conn: sqlite3.Connection, channel_id: int) -> sqlite3.Row | None:
    row = conn.execute(
        "SELECT id, canonical_name, country, custom_name, note "
        "FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if row is None:
        print(f"#{channel_id}: нет такого канала")
        return None
    алиасы = [f"«{a['alias']}» ({a['source_id']})" for a in conn.execute(
        "SELECT alias, source_id FROM channel_aliases WHERE channel_id = ?",
        (channel_id,))]
    отметок = conn.execute("SELECT COUNT(*) FROM event_channels "
                           "WHERE channel_id = ?", (channel_id,)).fetchone()[0]
    карточек = conn.execute("SELECT COUNT(*) FROM source_channels "
                            "WHERE channel_id = ?", (channel_id,)).fetchone()[0]
    print(f"#{row['id']} «{row['canonical_name']}» ({row['country']})"
          f"{' — имя правил владелец' if row['custom_name'] else ''}"
          f"{', пометка «' + row['note'] + '»' if row['note'] else ''}: "
          f"написаний {len(алиасы)}, отметок игр {отметок}, "
          f"строк в карточках источников {карточек}")
    for a in алиасы:
        print(f"    написание {a}")
    return row


def merge(conn: sqlite3.Connection, main: int, dup: int, apply: bool) -> int:
    if main == dup:
        print("главный и дубль — одна и та же запись")
        return 1
    print("главный:")
    главный = show(conn, main)
    print("дубль:")
    дубль = show(conn, dup)
    if главный is None or дубль is None:
        return 1
    if (главный["country"] or "") != (дубль["country"] or ""):
        print(f"\nразные страны ({главный['country']} и {дубль['country']}) — "
              "это не один канал, не сливаю")
        return 1
    конфликты = conn.execute(
        "SELECT d.id AS did, m.id AS mid, d.miss_count AS dm, m.miss_count AS mm, "
        "d.last_seen AS dl, m.last_seen AS ml FROM event_channels d "
        "JOIN event_channels m ON m.event_id = d.event_id "
        "AND m.source_id = d.source_id "
        "WHERE d.channel_id = ? AND m.channel_id = ?", (dup, main)).fetchall()
    переедут = conn.execute("SELECT COUNT(*) FROM event_channels "
                            "WHERE channel_id = ?", (dup,)).fetchone()[0] \
        - len(конфликты)
    print(f"\nпереедут отметок игр: {переедут}; уже есть у главного от того же "
          f"сайта (обновим свежесть): {len(конфликты)}; написания и строки "
          f"карточек — все к главному; запись #{dup} будет удалена")
    if not apply:
        print("это был показ; чтобы сделать — добавьте --apply")
        return 0
    for r in конфликты:
        conn.execute("UPDATE event_channels SET miss_count = ?, last_seen = ? "
                     "WHERE id = ?",
                     (min(r["dm"], r["mm"]), max(r["dl"] or "", r["ml"] or ""),
                      r["mid"]))
        conn.execute("DELETE FROM event_channels WHERE id = ?", (r["did"],))
    conn.execute("UPDATE event_channels SET channel_id = ? WHERE channel_id = ?",
                 (main, dup))
    # написание с тем же сайтом могло быть и у главного — тогда его копия
    # у дубля лишняя (UNIQUE alias+source_id)
    conn.execute("UPDATE OR IGNORE channel_aliases SET channel_id = ? "
                 "WHERE channel_id = ?", (main, dup))
    conn.execute("DELETE FROM channel_aliases WHERE channel_id = ?", (dup,))
    conn.execute("UPDATE source_channels SET channel_id = ? WHERE channel_id = ?",
                 (main, dup))
    conn.execute("UPDATE directory_channels SET matched_channel_id = ? "
                 "WHERE matched_channel_id = ?", (main, dup))
    conn.execute("DELETE FROM channels WHERE id = ?", (dup,))
    conn.commit()
    print("\nготово. главный после слияния:")
    show(conn, main)
    остался = conn.execute("SELECT 1 FROM channels WHERE id = ?",
                           (dup,)).fetchone()
    print(f"#{dup} остался в базе: {'да' if остался else 'нет'}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("main", type=int, help="id канала, который остаётся")
    ap.add_argument("dup", type=int, help="id дубля, который вливается и удаляется")
    ap.add_argument("--apply", action="store_true", help="без него — только показ")
    ap.add_argument("--db", default="", help="другая база (проверка на копии)")
    args = ap.parse_args()
    if args.db:
        os.environ["STREAMS_DB"] = args.db
    from app import db  # noqa: E402  (после STREAMS_DB)
    conn = db.connect()
    try:
        return merge(conn, args.main, args.dup, args.apply)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

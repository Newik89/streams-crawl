# -*- coding: utf-8 -*-
r"""Каналы-двойники: одно имя, одна страна, две записи.

Владелец 09.09 увидел на `/channels` по две строки «MAX Sport 1…4» (BG) —
одна с сайтом и галочкой «в обходе», вторая пустая. Такие пустышки попали в
базу из справочника каналов: у них нет ни одной отметки игры и ни одного
имени с сайта, но в списке они мешают и заставляют думать, что канал
задвоился по-настоящему.

Убираем только **пустые** двойники: 0 отметок игр и 0 алиасов. Двойник, у
которого что-то есть, не трогаем — его сливать должен человек, решив, какое
имя главное.

    venv\Scripts\python.exe scripts/dedupe_channels.py            # показать
    venv\Scripts\python.exe scripts/dedupe_channels.py --apply    # удалить
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def empty_twins(conn: sqlite3.Connection) -> list[dict]:
    """Пустые двойники: та же пара (имя, страна), ни отметок, ни алиасов."""
    out = []
    rows = conn.execute(
        "SELECT canonical_name AS name, IFNULL(country,'') AS country, "
        "COUNT(*) AS n, GROUP_CONCAT(id) AS ids FROM channels "
        "GROUP BY canonical_name, IFNULL(country,'') HAVING n > 1").fetchall()
    for row in rows:
        ids = [int(x) for x in row["ids"].split(",")]
        loaded, empty = [], []
        for cid in ids:
            marks = conn.execute("SELECT COUNT(*) FROM event_channels "
                                 "WHERE channel_id=?", (cid,)).fetchone()[0]
            aliases = conn.execute("SELECT COUNT(*) FROM channel_aliases "
                                   "WHERE channel_id=?", (cid,)).fetchone()[0]
            (empty if marks == 0 and aliases == 0 else loaded).append(cid)
        # хоть одна живая запись должна остаться — иначе это не двойник,
        # а единственный (пусть и пустой) канал
        if loaded and empty:
            out.append({"name": row["name"], "country": row["country"],
                        "keep": loaded, "drop": empty})
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="без него — только показ")
    ap.add_argument("--db", default="", help="другая база (проверка на копии)")
    args = ap.parse_args()
    if args.db:
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
    else:
        conn = db.connect()
    try:
        twins = empty_twins(conn)
        if not twins:
            print("пустых двойников нет")
            return 0
        for t in twins:
            print(f"  {t['name']} ({t['country'] or '—'}): оставляем "
                  f"{', '.join('#' + str(i) for i in t['keep'])}, убираем "
                  f"{', '.join('#' + str(i) for i in t['drop'])}")
        total = sum(len(t["drop"]) for t in twins)
        if not args.apply:
            print(f"\nпустых двойников: {total}; чтобы удалить — --apply")
            return 0
        for t in twins:
            for cid in t["drop"]:
                conn.execute("DELETE FROM channels WHERE id=?", (cid,))
        conn.commit()
        print(f"\nудалено: {total}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

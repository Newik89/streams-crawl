# -*- coding: utf-8 -*-
r"""Вид спорта у лиги словаря (`leagues.sport`): посмотреть и поменять.
Пустой вид — лига ничего не говорит о спорте (товарищеские матчи сборных
бывают и футбольными, и баскетбольными: «WORLD: Friendly International»
с 13.09 держала B и делала баскетболом все «Partido amistoso» — 02.10).

    venv/bin/python scripts/league_sport.py --find Friendly                      показать лиги с этим текстом
    venv/bin/python scripts/league_sport.py "WORLD: Friendly International" --set none          показать, что изменится
    venv/bin/python scripts/league_sport.py "WORLD: Friendly International" --set none --apply  записать (F|B|T|none)

Лига — точное каноническое имя. Без `--apply` ничего не пишется.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("league", nargs="?", default="", help="каноническое имя лиги")
    ap.add_argument("--find", default="", help="показать лиги с этим текстом")
    ap.add_argument("--set", dest="sport", default="",
                    help="новый вид спорта: F, B, T или none (пусто)")
    ap.add_argument("--apply", action="store_true", help="записать")
    args = ap.parse_args()
    conn = db.connect()
    try:
        if args.find:
            rows = conn.execute(
                "SELECT id, canonical_name, sport, "
                "(SELECT COUNT(*) FROM league_aliases a WHERE a.league_id = l.id) AS aliases, "
                "(SELECT COUNT(*) FROM events e WHERE e.league_id = l.id) AS games "
                "FROM leagues l WHERE canonical_name LIKE ? ORDER BY canonical_name",
                (f"%{args.find}%",)).fetchall()
            print(f"лиг с «{args.find}»: {len(rows)}")
            for r in rows:
                print(f"   #{r['id']:>5}  {r['sport'] or '-'}  {r['canonical_name']}  "
                      f"алиасов {r['aliases']}, игр {r['games']}")
        if not args.league:
            return 0
        row = conn.execute("SELECT id, canonical_name, sport FROM leagues "
                           "WHERE canonical_name = ?", (args.league,)).fetchone()
        if row is None:
            print(f"нет лиги «{args.league}»")
            return 1
        print(f"лига #{row['id']} {row['canonical_name']}: вид спорта сейчас "
              f"{row['sport'] or 'пусто'}")
        if not args.sport:
            return 0
        new = args.sport.strip().upper()
        if new == "NONE":
            new = None
        elif new not in ("F", "B", "T"):
            print("вид спорта — F, B, T или none")
            return 2
        print(f"   станет: {new or 'пусто'}")
        if not args.apply:
            print("добавьте --apply, чтобы записать")
            return 0
        conn.execute("UPDATE leagues SET sport = ? WHERE id = ?", (new, row["id"]))
        conn.commit()
        print("записано")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

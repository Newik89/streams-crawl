# -*- coding: utf-8 -*-
"""Снятие игр с витрины поимённым списком — ТОЛЬКО по слову владельца.

Обычный путь смерти игры — срок жизни (`store.purge_expired`); этот скрипт
для случаев, когда владелец велел убрать конкретные записи руками (прецеденты:
4 записи NOS 20.09, 10 записей-самозванцев #3373 и родня 22.09). Без
`--apply` — только показывает, что будет снято. Отметки каналов уходят
каскадом (FK ON DELETE CASCADE).

    venv/bin/python scripts/remove_events.py --ids 3373,3367 [--apply]

⚠️ После снятия не гонять `games_import --reimport` по старому results-файлу,
в котором эти игры ещё есть, — воскресит. Обычный забор безопасен: повторную
заливку того же файла он пропускает по метке «собрано».
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "channel_schedule.db"),
                    help="база (по умолчанию — база сайта)")
    ap.add_argument("--ids", required=True,
                    help="id событий через запятую, поимённо от владельца")
    ap.add_argument("--apply", action="store_true",
                    help="без него — только показ")
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.replace(" ", "").split(",") if x]
    if not ids:
        print("пустой список — нечего снимать")
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, sport, start_kyiv, team_home_auto, team_away_auto, "
        f"league_auto FROM events WHERE id IN ({marks})", ids).fetchall()
    found = {r["id"] for r in rows}
    for r in rows:
        print(f"  #{r['id']}  {r['start_kyiv']}  [{r['sport'] or '?'}]  "
              f"{r['team_home_auto']} — {r['team_away_auto']}  "
              f"| {r['league_auto'] or ''}")
    for missing in sorted(set(ids) - found):
        print(f"  #{missing}  — в базе уже нет")
    if not args.apply:
        print(f"ПОКАЗ: снялось бы {len(found)} из {len(ids)}. "
              "Для снятия добавить --apply")
        conn.close()
        return 0
    n = conn.execute(f"DELETE FROM events WHERE id IN ({marks})",
                     ids).rowcount
    conn.commit()
    conn.close()
    print(f"СНЯТО: {n} (отметки каналов ушли каскадом)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
r"""Вернуть на витрину каналы, погашенные по ошибке (`event_channels.miss_count`).

Счётчик пропусков сбрасывается в 0 только у перечисленных отметок — список
готовит разбор (06.10.2026: скан даты #204 погасил 30 живых отметок, см.
правила `app/miss.py`). Без `--apply` скрипт только показывает, что
сделал бы; база не меняется.

    python scripts/miss_repair.py --ids 13069,13064            # показать
    python scripts/miss_repair.py --ids 13069,13064 --apply    # записать

Запускать ПОСЛЕ выкладки починки гашения: старый код следующим же сбором
погасит их снова.
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
    ap.add_argument("--ids", required=True,
                    help="id отметок (event_channels.id) через запятую")
    ap.add_argument("--apply", action="store_true",
                    help="записать в базу; без него — только показать")
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.replace(" ", "").split(",") if x]

    conn = db.connect()
    try:
        found = {r["id"]: r for r in conn.execute(
            "SELECT ec.id, ec.miss_count, ec.last_seen, e.id AS event_id, "
            "e.start_kyiv, e.team_home_auto, e.team_away_auto, s.domain, "
            "c.canonical_name AS channel "
            "FROM event_channels ec JOIN events e ON e.id = ec.event_id "
            "JOIN sources s ON s.id = ec.source_id "
            "JOIN channels c ON c.id = ec.channel_id "
            f"WHERE ec.id IN ({','.join('?' * len(ids))})", ids)}
        back = []
        for mark_id in ids:
            r = found.get(mark_id)
            if r is None:
                print(f"  {mark_id}: нет в базе (игра уже прошла и убрана)")
                continue
            state = "погашена" if r["miss_count"] else "и так жива"
            print(f"  {mark_id}: #{r['event_id']} {r['start_kyiv']} "
                  f"{r['team_home_auto']} - {r['team_away_auto']} | {r['domain']} "
                  f"{r['channel']} | пропусков {r['miss_count']}, видели "
                  f"{r['last_seen']} — {state}")
            if r["miss_count"]:
                back.append(mark_id)
        print(f"вернуть на витрину: {len(back)} из {len(ids)}")
        if not args.apply:
            print("только показ — для записи добавьте --apply")
            return 0
        if back:
            conn.execute("UPDATE event_channels SET miss_count = 0 WHERE id IN ("
                         + ",".join("?" * len(back)) + ")", back)
            conn.commit()
        print(f"записано: {len(back)}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

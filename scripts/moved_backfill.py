# -*- coding: utf-8 -*-
r"""Пометка «перенесён с …» играм, перенесённым ДО появления триггера.

Триггер `events_moved_from_v1` (`app/db.py`) ставит пометку только при
будущих сдвигах; а Toulouse — Troyes (#6792) и PSG — Lyon (#7042) эталон
перенёс в ночь на 24.10 (разбор владельца 24.10, #7836). Этот скрипт
восстанавливает пометку по снимкам базы теми же правилами, что триггер:

1. Самое раннее известное время игры — из снимков по порядку (`--from`,
   от старого к новому; игра берётся из первого снимка, где она есть).
2. Текущее время дальше `db.MOVED_HOURS` от него — перенос: `moved_from` =
   то самое раннее время.
3. Ближе порога (поправка, перевод часов, вернули назад) — не перенос.
4. Пометка уже стоит — не трогаем; прошедшие игры не трогаем.
5. Без `--apply` — только показ.

    venv/bin/python scripts/moved_backfill.py --from /root/backups/db-7.db \
        /root/backups/db-1.db … /root/backups/db-6.db [--apply]
К сайтам не обращается. Тест: `scripts/test_perenos.py`, раздел D.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def _dt(text: str) -> datetime:
    return datetime.strptime((text or "").replace("T", " ")[:16], "%Y-%m-%d %H:%M")


def earliest(snapshots: list[str]) -> dict[int, str]:
    """Правило 1: id игры → время из самого раннего снимка, где она есть."""
    out: dict[int, str] = {}
    for path in snapshots:
        snap = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            for event_id, start in snap.execute("SELECT id, start_kyiv FROM events"):
                if event_id not in out and start:
                    out[event_id] = start.replace("T", " ")[:16]
        finally:
            snap.close()
    return out


def plan(conn, first: dict[int, str], now: datetime) -> list[tuple[int, str, str, str]]:
    """Правила 2–4: [(id, было, стало, игра)] — кому ставить пометку."""
    out = []
    for r in conn.execute("SELECT id, start_kyiv, moved_from, team_home_auto, "
                          "team_away_auto FROM events WHERE moved_from IS NULL"):
        was = first.get(r["id"])
        if not was or not r["start_kyiv"]:
            continue
        now_start = _dt(r["start_kyiv"])
        if now_start < now:
            continue                                            # правило 4
        if abs((now_start - _dt(was)).total_seconds()) / 3600 < db.MOVED_HOURS:
            continue                                            # правило 3
        out.append((r["id"], was, r["start_kyiv"][:16],
                    f"{r['team_home_auto']} — {r['team_away_auto']}"))
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="пометка «перенесён с …» по снимкам базы")
    ap.add_argument("--from", dest="snapshots", nargs="+", required=True,
                    help="снимки базы от старого к новому")
    ap.add_argument("--apply", action="store_true", help="записать (без него — показ)")
    args = ap.parse_args()
    conn = db.connect()
    try:
        db.init_db(conn)                    # колонка moved_from и триггер
        todo = plan(conn, earliest(args.snapshots), datetime.now())
        for event_id, was, now_start, title in todo:
            print(f"  #{event_id} {title}: {was} → {now_start}")
        if args.apply:
            conn.executemany("UPDATE events SET moved_from = ? WHERE id = ?",
                             [(was, event_id) for event_id, was, _, _ in todo])
            conn.commit()
        print(f"перенесённых игр: {len(todo)}" + ("" if args.apply else "  (только показ)"))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

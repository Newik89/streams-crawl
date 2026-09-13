# -*- coding: utf-8 -*-
r"""Снимок базы БЕЗ остановки сайта: sqlite-backup + проверка целостности.

Появился 13.09.2026 (пачка «поехали», пункт 6): прежний ежедневный бэкап
делал `cp` живого файла — при журнале WAL такая копия может выйти «рваной»,
и заметно это станет только в день аварии. Здесь копию снимает сам SQLite
(Connection.backup — честный снимок даже под записью), затем по копии
гоняется `PRAGMA integrity_check`, и провал проверки роняет скрипт красным.

Запуск (одинаково локально и на сервере):
    venv/bin/python scripts/db_backup.py --out /root/backups/BACKUP-2026-09-13
    venv\Scripts\python.exe scripts/db_backup.py --out backup_2026-09-13

База по умолчанию — data/channel_schedule.db рядом с репозиторием
(как у сайта); другую указывать через --db. К сети не обращается.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "channel_schedule.db"),
                    help="какую базу снимать (по умолчанию — базу сайта)")
    ap.add_argument("--out", required=True,
                    help="папка снимка (создастся) или готовый путь *.db")
    args = ap.parse_args()

    src = Path(args.db)
    if not src.exists():
        print(f"базы нет: {src}")
        return 1
    out = Path(args.out)
    if out.suffix != ".db":
        out.mkdir(parents=True, exist_ok=True)
        out = out / "channel_schedule.db"

    live = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    snap = sqlite3.connect(out)
    with snap:
        live.backup(snap)          # честный снимок, WAL не страшен
    live.close()

    check = snap.execute("PRAGMA integrity_check").fetchone()[0]
    tables = snap.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    events = channels = "-"
    try:
        events = snap.execute("SELECT count(*) FROM events").fetchone()[0]
        channels = snap.execute("SELECT count(*) FROM channels").fetchone()[0]
    except sqlite3.Error:
        pass                        # чужая база без наших таблиц — не беда
    snap.close()

    size_mb = out.stat().st_size / 1024 / 1024
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"{stamp}  снимок: {out}  ({size_mb:.1f} МБ, таблиц {tables}, "
          f"событий {events}, каналов {channels})")
    print(f"integrity_check: {check}")
    if check != "ok":
        print("ПРОВАЛ: копия битая, использовать нельзя")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

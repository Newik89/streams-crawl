# -*- coding: utf-8 -*-
r"""Каналы, которые берём страницами livesoccertv (механика этапа 6в).

Идемпотентно дописывает недостающие строки в `source_channels` источника
`livesoccertv.com`. Новая пачка 03.09 (задание владельца): Косово —
Суперлигу показывает пакет ArtMotion (ART Sport 1–6, слаги проверены пробой
#215/#216, art-sport-7 не существует); Нидерланды — гид `espn.nl` закрыт
защитой (HTTP 202, проба #213), ESPN 1–4 берём тоже страницами каналов.

Гонять на обеих базах:
    venv\Scripts\python.exe scripts/lstv_channels.py
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/lstv_channels.py"
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

BASE = "https://www.livesoccertv.com/channels/"
CHANNELS = [
    ("ART Sport 1", "artsport1"),
    ("ART Sport 2", "art-sport-2"),
    ("ART Sport 3", "art-sport-3"),
    ("ART Sport 4", "art-sport-4"),
    ("ART Sport 5", "art-sport-5"),
    ("ART Sport 6", "art-sport-6"),
    ("ESPN Netherlands", "espn-netherlands"),
    ("ESPN 2 Netherlands", "espn-2-netherlands"),
    ("ESPN 3 Netherlands", "espn-3-netherlands"),
    ("ESPN 4 Netherlands", "espn-4-netherlands"),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = db.connect()
    try:
        row = conn.execute("SELECT id FROM sources WHERE domain=?",
                           ("livesoccertv.com",)).fetchone()
        if not row:
            print("источника livesoccertv.com в базе нет")
            return 1
        added = 0
        for raw_name, slug in CHANNELS:
            have = conn.execute(
                "SELECT id FROM source_channels WHERE source_id=? AND raw_name=?",
                (row["id"], raw_name)).fetchone()
            if have:
                continue
            conn.execute(
                "INSERT INTO source_channels (source_id, raw_name, page_url, "
                "include) VALUES (?,?,?,1)",
                (row["id"], raw_name, f"{BASE}{slug}/"))
            added += 1
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM source_channels "
                             "WHERE source_id=? AND include=1", (row["id"],)).fetchone()[0]
        print(f"добавлено {added}, всего страниц каналов {total} (база {db.db_path()})")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

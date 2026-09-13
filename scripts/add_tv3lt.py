# -*- coding: utf-8 -*-
r"""Завести источник tv3.lt и 16 каналов, выбранных владельцем 06.09.2026.

Идемпотентен: повторный запуск ничего не дублирует. Гонять в ОБЕИХ базах:
    venv\Scripts\python.exe scripts/add_tv3lt.py
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_tv3lt.py"
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402

DOMAIN = "tv3.lt"
BASE = "https://www.tv3.lt/programos/btv"
PATTERN = "https://www.tv3.lt/programos/{slug}?d={YYYY-MM-DD}"

#: слаг на сайте → имя канала (выбор владельца 06.09: спортивные все + 8)
CHANNELS = [
    ("go3_sport_1", "Go3 Sport 1"),
    ("go3_sport_2", "Go3 Sport 2"),
    ("go3_sport_3", "Go3 Sport 3"),
    ("go3_sport_open", "Go3 Sport Open"),
    ("nba", "NBA TV"),
    ("sport_1", "Sport 1"),
    ("courtside_1891_tv", "Courtside 1891 TV"),
    ("eurosport_1", "Eurosport 1"),
    ("btv", "BTV"),
    ("lnk", "LNK"),
    ("tv3", "TV3"),
    ("tv6", "TV6"),
    ("tv8", "TV8"),
    ("tv3plus", "TV3 Plus"),
    ("lrt", "LRT"),
    ("lrt_plius", "LRT Plius"),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = db.connect()
    row = conn.execute("SELECT id FROM sources WHERE domain = ?",
                       (DOMAIN,)).fetchone()
    if row:
        source_id = row["id"]
        print(f"источник уже есть: id {source_id}")
    else:
        cur = conn.execute(
            "INSERT INTO sources (domain, name, base_url, country, timezone, "
            "role, access, url_pattern, parse_level, enabled, status, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'ok', ?)",
            (DOMAIN, "TV3.lt — Lietuvos TV programa", BASE, "LT",
             "Europe/Vilnius", "schedule", "open", "",
             "A", "канал × день, дата параметром ?d=; день целиком "
             "00:00–24:00; маркера эфира нет — первый показ пары "
             "(разведка 06.09.2026, вопрос владельца про BTV)"))
        source_id = cur.lastrowid
        print(f"источник заведён: id {source_id}")

    added = 0
    for slug, name in CHANNELS:
        channel_id = dictionary.remember_channel(
            conn, name, name, "LT", source_id=source_id)
        page = PATTERN.replace("{slug}", slug)
        have = conn.execute(
            "SELECT id FROM source_channels WHERE source_id = ? "
            "AND raw_name = ?", (source_id, name)).fetchone()
        if have:
            conn.execute(
                "UPDATE source_channels SET channel_id = ?, page_url = ?, "
                "include = 1 WHERE id = ?", (channel_id, page, have["id"]))
        else:
            conn.execute(
                "INSERT INTO source_channels (source_id, raw_name, "
                "channel_id, page_url, include) VALUES (?, ?, ?, ?, 1)",
                (source_id, name, channel_id, page))
            added += 1
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM source_channels "
                         "WHERE source_id = ?", (source_id,)).fetchone()[0]
    print(f"каналов у источника: {total} (новых {added})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

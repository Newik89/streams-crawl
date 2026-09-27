# -*- coding: utf-8 -*-
r"""Завести start.sportdigital.de и его 6 каналов (слово владельца 28.09:
«подбери для него парсер» — автоподбор 23.09 сайт не взял, разбор свой).

Идемпотентен: повторный запуск ничего не дублирует. Гонять в ОБЕИХ базах:
    venv\Scripts\python.exe scripts/add_sportdigital.py
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_sportdigital.py"

Канальная сетка: страница `/tvprogramm/<код>` держит 21 день канала одним
запросом (`CHANNEL_GRID_DOMAINS`). Эфир сайт метит честно — классом
`epgArt_live`; разбор — `app/parsers/sportdigital_de.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402

DOMAIN = "start.sportdigital.de"
BASE = "https://start.sportdigital.de/tvprogramm"

#: код в адресе → имя канала. Все немецкой линейки Sportdigital;
#: каналы не отсеиваем — полный список показан владельцу (правило)
CHANNELS = [
    ("sdf", "Sportdigital FUSSBALL"),
    ("sdf2", "Sportdigital FUSSBALL2"),
    ("sd1p", "Sportdigital1+"),
    ("edge", "Sportdigital EDGE"),
    ("esportsone", "eSportsONE"),
    ("scooorefast", "scooore"),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = db.connect()
    notes = ("канальная сетка: /tvprogramm/<код> отдаёт 21 день канала одним "
             "запросом; эфир — класс epgArt_live (честный), повтор — "
             "epgArt_wdh; свой парсер sportdigital_de (28.09.2026)")
    row = conn.execute("SELECT id FROM sources WHERE domain = ?",
                       (DOMAIN,)).fetchone()
    if row:
        source_id = row["id"]
        conn.execute(
            "UPDATE sources SET base_url = ?, country = 'DE', "
            "timezone = 'Europe/Berlin', role = 'schedule', access = 'open', "
            "url_pattern = '', parse_strategy = 'selectors', "
            "parse_level = 'B', enabled = 1, status = 'ok', notes = ? "
            "WHERE id = ?", (BASE, notes, source_id))
        print(f"источник обновлён: id {source_id}")
    else:
        cur = conn.execute(
            "INSERT INTO sources (domain, name, base_url, country, timezone, "
            "role, access, url_pattern, parse_strategy, parse_level, "
            "enabled, status, notes) "
            "VALUES (?, ?, ?, 'DE', 'Europe/Berlin', 'schedule', 'open', "
            "'', 'selectors', 'B', 1, 'ok', ?)",
            (DOMAIN, "Sportdigital (Германия)", BASE, notes))
        source_id = cur.lastrowid
        print(f"источник заведён: id {source_id}")

    added = 0
    for slug, name in CHANNELS:
        channel_id = dictionary.remember_channel(
            conn, name, name, "DE", source_id=source_id)
        page = f"{BASE}/{slug}"
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

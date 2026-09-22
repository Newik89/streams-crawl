# -*- coding: utf-8 -*-
r"""Завести канал RTP2 у источника rtp.pt (жалоба владельца 22.09.2026).

Женский матч Лиги чемпионов Juventus — SL Benfica шёл на RTP2, а у нас
канала не было вовсе: при разведке ручка `…/list-grid/tv/2/…` отвечала
`HTTP 500`, и канал молча выпал. Верный номер RTP2 — **8** (взят из
разметки самой страницы `https://www.rtp.pt/rtp2/`), ручка отдаёт 45 КБ и
тот самый матч с пометкой `Direto`.

Идемпотентен: повторный запуск ничего не дублирует. Гонять в ОБЕИХ базах:
    venv\Scripts\python.exe scripts/add_rtp2.py
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_rtp2.py"
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402

DOMAIN = "rtp.pt"
NAME = "RTP2"
PAGE = "https://www.rtp.pt/EPG/json/rtp-channels-page/list-grid/tv/8/{YYYY-MM-DD}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = db.connect()
    row = conn.execute("SELECT id FROM sources WHERE domain = ?",
                       (DOMAIN,)).fetchone()
    if not row:
        print(f"источника {DOMAIN} нет в этой базе — заводить нечего")
        return 1
    source_id = row["id"]

    channel_id = dictionary.remember_channel(
        conn, NAME, NAME, "PT", source_id=source_id)
    have = conn.execute(
        "SELECT id FROM source_channels WHERE source_id = ? AND raw_name = ?",
        (source_id, NAME)).fetchone()
    if have:
        conn.execute(
            "UPDATE source_channels SET channel_id = ?, page_url = ?, "
            "include = 1 WHERE id = ?", (channel_id, PAGE, have["id"]))
        print(f"страница RTP2 обновлена (канал id {channel_id})")
    else:
        conn.execute(
            "INSERT INTO source_channels (source_id, raw_name, channel_id, "
            "page_url, include) VALUES (?, ?, ?, ?, 1)",
            (source_id, NAME, channel_id, PAGE))
        print(f"RTP2 заведён (канал id {channel_id})")
    conn.commit()

    print(f"каналов у {DOMAIN}:")
    for r in conn.execute(
            "SELECT raw_name, page_url, include FROM source_channels "
            "WHERE source_id = ? ORDER BY raw_name", (source_id,)):
        print(f"  {r['raw_name']:14} include={r['include']}  {r['page_url']}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

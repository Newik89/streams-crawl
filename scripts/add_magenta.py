# -*- coding: utf-8 -*-
r"""Вернуть источнику cosmotetv.gr рабочий адрес и каналы Magenta Sport
(вопрос владельца 03.10.2026: «вот почему я не вижу его в расписаниях»).

Сайт (теперь Magenta TV) с 11.09 не кладёт сетку в HTML — данные берём с его
же ручки EPG (`app/parsers/cosmotetv_gr.py`). Эта настройка жила только в
плане обхода, собранном с ЛОКАЛЬНОЙ базы; 22.09 план пересобрали на сервере,
а в серверной карточке стоял старый адрес страницы и ни одного канала — и
источник с тех пор отдавал пустышку: 190 передач, игр 0.

Скрипт кладёт настройку в саму базу, чтобы пересборка плана её больше не
теряла: `url_pattern` → ручка EPG, 16 каналов Magenta Sport с `include=1`
(из ответа ручки на ~114 каналов берём только их). Идемпотентен. Гонять в
ОБЕИХ базах, затем пересобрать и отправить план:
    venv\Scripts\python.exe scripts/add_magenta.py
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_magenta.py"
    …crawl_plan.py --json data/crawl_plan.json → сверить домены → push_plan.py
`--dry-run` — только показать, что изменится.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

DOMAIN = "cosmotetv.gr"
PATTERN = ("https://mwapi-prod.cosmotetvott.gr/api/v3.4/epg/listings/el"
           "?from={UNIXDAY}&to={UNIXDAYEND}&endingIncludedInRange=false")
CHANNELS = [
    "Magenta Sport 1", "Magenta Sport 2", "Magenta Sport 3", "Magenta Sport 4",
    "Magenta Sport 5", "Magenta Sport 6", "Magenta Sport 7", "Magenta Sport 8",
    "Magenta Sport 9", "Magenta Sport 4K", "Magenta Sport 1 League",
    "Magenta Sport 2 League", "Magenta Sport 3 League", "Magenta Sport 4 League",
    "Magenta Sport Start", "Magenta Sport Highlights",
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    dry = "--dry-run" in sys.argv
    conn = db.connect()
    row = conn.execute("SELECT id, url_pattern FROM sources WHERE domain = ?",
                       (DOMAIN,)).fetchone()
    if not row:
        print(f"источника {DOMAIN} нет в этой базе — чинить нечего")
        return 1
    source_id = row["id"]

    if row["url_pattern"] == PATTERN:
        print("адрес уже верный (ручка EPG)")
    else:
        print(f"адрес был:   {row['url_pattern']}")
        print(f"адрес будет: {PATTERN}")
        if not dry:
            conn.execute("UPDATE sources SET url_pattern = ? WHERE id = ?",
                         (PATTERN, source_id))

    added = updated = 0
    for name in CHANNELS:
        # канал в картотеке уже есть с тех недель, когда источник работал
        # (имя мог править владелец: «Magenta Sport 7» → «cosmote sport 7») —
        # берём его по написанию этого источника, нового не заводим
        alias = conn.execute(
            "SELECT channel_id FROM channel_aliases WHERE alias = ? "
            "AND source_id = ?", (name, source_id)).fetchone()
        channel_id = alias["channel_id"] if alias else None
        have = conn.execute(
            "SELECT id, include FROM source_channels WHERE source_id = ? "
            "AND raw_name = ?", (source_id, name)).fetchone()
        if have:
            if not have["include"]:
                updated += 1
                if not dry:
                    conn.execute("UPDATE source_channels SET include = 1 "
                                 "WHERE id = ?", (have["id"],))
        else:
            added += 1
            if not dry:
                conn.execute(
                    "INSERT INTO source_channels (source_id, raw_name, "
                    "channel_id, page_url, include) VALUES (?, ?, ?, '', 1)",
                    (source_id, name, channel_id))
    if not dry:
        conn.commit()
    print(f"каналов заведено: {added}, включено заново: {updated}"
          + (" (проба, база не тронута)" if dry else ""))
    print(f"каналов у {DOMAIN} с include=1: " + str(conn.execute(
        "SELECT COUNT(*) FROM source_channels WHERE source_id = ? "
        "AND include = 1", (source_id,)).fetchone()[0]))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

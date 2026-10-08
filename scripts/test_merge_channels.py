# -*- coding: utf-8 -*-
"""Слияние двух записей одного канала (`scripts/merge_channels.py`).

Запуск: venv\\Scripts\\python.exe scripts/test_merge_channels.py
База — временная, к сети не обращается.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

TMP = Path(tempfile.mkdtemp(prefix="merge-ch-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")

from app import db  # noqa: E402
import merge_channels  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def тихо(fn, *a):
    было, sys.stdout = sys.stdout, io.StringIO()
    try:
        return fn(*a)
    finally:
        sys.stdout = было


def база():
    conn = db.connect()
    db.init_db(conn)
    conn.executescript("""
    INSERT INTO sources (id, domain, name, base_url, country) VALUES
      (2, 'allente.no', 'Allente', 'https://allente.no/', 'NO'),
      (68, 'tv2.no', 'TV 2', 'https://tv2.no/', 'NO'),
      (9, 'other.cz', 'Чужой', 'https://other.cz/', 'CZ');
    INSERT INTO channels (id, canonical_name, slug, country, custom_name, note)
      VALUES (496, 'NO TV 2 Direkte', 'no-tv-2-direkte', 'NO', 1, 'NO'),
             (498, 'TV 2 Direkte', 'tv-2-direkte', 'NO', 0, NULL),
             (7, 'Sport 1', 'sport-1-cz', 'CZ', 0, NULL);
    INSERT INTO channel_aliases (channel_id, alias, source_id) VALUES
      (496, 'TV 2 Direkte HD', 2), (498, 'TV 2 Direkte', 68),
      (496, 'Общее', 68);
    INSERT INTO source_channels (source_id, raw_name, channel_id, page_url)
      VALUES (68, 'TV 2 Direkte', 498, '');
    INSERT INTO events (id, sport, league_auto, team_home_auto, team_away_auto,
      start_utc, start_kyiv, last_seen) VALUES
      (1, 'F', 'L', 'A', 'B', '2026-12-01 17:00', '2026-12-01 20:00', '2026-10-08 10:00'),
      (2, 'F', 'L', 'C', 'D', '2026-12-02 17:00', '2026-12-02 20:00', '2026-10-08 10:00');
    INSERT INTO event_channels (event_id, channel_id, source_id, source_url,
      raw_title, last_seen, miss_count) VALUES
      (1, 496, 2, '', '', '2026-10-07 10:00', 1),
      (1, 498, 2, '', '', '2026-10-08 10:00', 0),
      (2, 498, 68, '', '', '2026-10-08 10:00', 0);
    """)
    conn.commit()
    return conn


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("Слияние записей канала")
    conn = база()

    код = тихо(merge_channels.merge, conn, 496, 498, False)
    проверка("показ ничего не меняет",
             (код, conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]),
             (0, 3))
    проверка("разные страны — отказ",
             тихо(merge_channels.merge, conn, 496, 7, True), 1)
    проверка("сам с собой — отказ", тихо(merge_channels.merge, conn, 496, 496, True), 1)

    код = тихо(merge_channels.merge, conn, 496, 498, True)
    проверка("слияние прошло", код, 0)
    проверка("дубль удалён",
             conn.execute("SELECT 1 FROM channels WHERE id = 498").fetchone(), None)
    проверка("имя и пометка главного целы",
             tuple(conn.execute("SELECT canonical_name, custom_name, note "
                                "FROM channels WHERE id = 496").fetchone()),
             ("NO TV 2 Direkte", 1, "NO"))
    алиасы = sorted((r[0], r[1]) for r in conn.execute(
        "SELECT alias, source_id FROM channel_aliases WHERE channel_id = 496"))
    проверка("написания переехали, копия не задвоилась",
             алиасы, [("TV 2 Direkte", 68), ("TV 2 Direkte HD", 2), ("Общее", 68)])
    проверка("чужих написаний у дубля не осталось",
             conn.execute("SELECT COUNT(*) FROM channel_aliases "
                          "WHERE channel_id = 498").fetchone()[0], 0)
    отметки = sorted((r[0], r[1], r[2], r[3]) for r in conn.execute(
        "SELECT event_id, source_id, miss_count, last_seen FROM event_channels "
        "WHERE channel_id = 496"))
    проверка("отметки: конфликт слит свежестью, остальное переехало",
             отметки, [(1, 2, 0, "2026-10-08 10:00"), (2, 68, 0, "2026-10-08 10:00")])
    проверка("карточка источника указывает на главного",
             conn.execute("SELECT channel_id FROM source_channels "
                          "WHERE raw_name = 'TV 2 Direkte'").fetchone()[0], 496)
    conn.close()
    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, "
          f"красных: {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

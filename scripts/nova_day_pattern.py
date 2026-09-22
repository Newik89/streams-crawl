# -*- coding: utf-8 -*-
r"""Перевести novasports.gr на дневную ручку с датой (22.09.2026).

Владелец показал: будущие дни размечены пометками эфира (Ζ)/LIVE, а любой
день отдаёт `admin-ajax.php` (ручка из инлайн-скрипта страницы). Раньше
качали одной страницей только текущий день.

Идемпотентен. Гонять в ОБЕИХ базах:
    venv\Scripts\python.exe scripts/nova_day_pattern.py
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/nova_day_pattern.py"
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

PATTERN = ("https://www.novasports.gr/wp-admin/admin-ajax.php"
           "?action=nova_get_template&template=tv-program/broadcast"
           "&dt={YYYY-MM-DD}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = db.connect()
    row = conn.execute("SELECT id, url_pattern FROM sources "
                       "WHERE domain = 'novasports.gr'").fetchone()
    if not row:
        print("источника novasports.gr в этой базе нет")
        return 1
    if row["url_pattern"] == PATTERN:
        print("шаблон уже стоит — менять нечего")
        return 0
    conn.execute("UPDATE sources SET url_pattern = ? WHERE id = ?",
                 (PATTERN, row["id"]))
    conn.commit()
    print(f"шаблон обновлён (id {row['id']}): {PATTERN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
r"""mojtv.hr: неделя вместо двух дней.

Владелец 09.09: «у сайта есть расписание на 5 дней, а не на 2» — и прислал
адреса с днями недели. Проба #270 показала лучшее: сайт понимает дату прямо
в адресе (`/sportski/2026-09-13.aspx` отдаёт сетку 13.9.2026), а это не
зависит от дня недели и работает дальше недели. Раньше в обходе стояли ровно
две страницы (danas и sutra), поэтому MAXSport 1–2 и Sport Klub были видны
только на два дня.

Заменяем их одной строкой-шаблоном с датой: обход сам развернёт её по дням
окна. Идемпотентен, гонять на ОБЕИХ базах:

    venv\Scripts\python.exe scripts/mojtv_week.py --apply
    ssh -i ~/.ssh/streams_schedule root@157.245.77.140 \
        "cd /root/streams-schedule && venv/bin/python scripts/mojtv_week.py --apply"

Прежние значения (на случай отката):
    danas → https://mojtv.hr/tv-program/-2/sportski/danas.aspx
    sutra → https://mojtv.hr/tv-program/-2/sportski/sutra.aspx
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

DOMAIN = "mojtv.hr"
PATTERN = "https://mojtv.hr/tv-program/-2/sportski/{YYYY-MM-DD}.aspx"
KEEP = "сетка спортканалов"          # имя строки, которая остаётся


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="без него — только показ")
    ap.add_argument("--db", default="", help="другая база (проверка на копии)")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db) if args.db else db.connect()
    conn.row_factory = sqlite3.Row
    try:
        src = conn.execute("SELECT id FROM sources WHERE domain=?",
                           (DOMAIN,)).fetchone()
        if src is None:
            print(f"источника {DOMAIN} нет")
            return 1
        rows = conn.execute("SELECT id, raw_name, page_url, include FROM "
                            "source_channels WHERE source_id=? ORDER BY id",
                            (src["id"],)).fetchall()
        print("сейчас в обходе:")
        for r in rows:
            print(f"   #{r['id']} {r['raw_name']}: {r['page_url']}")
        if any(r["raw_name"] == KEEP and r["page_url"] == PATTERN for r in rows):
            print("\nуже переведён на неделю")
            return 0
        if not args.apply:
            print(f"\nстанет одной строкой «{KEEP}» → {PATTERN}"
                  f"\n(остальные строки этого источника уйдут)"
                  "\nчтобы сделать — добавьте --apply")
            return 0
        first = rows[0]
        conn.execute("UPDATE source_channels SET raw_name=?, page_url=?, "
                     "include=1 WHERE id=?", (KEEP, PATTERN, first["id"]))
        for r in rows[1:]:
            conn.execute("DELETE FROM source_channels WHERE id=?", (r["id"],))
        conn.commit()
        print(f"\nготово: одна строка «{KEEP}» → {PATTERN}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

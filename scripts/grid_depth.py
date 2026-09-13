# -*- coding: utf-8 -*-
r"""Дешёвые дневные сетки: глубина 5 → 7 дней («сегодня + 6»).

Кейсы 07.09 (#1348, #1349): Дерби — Бирмингем и Расинг — Алавес идут в
субботу 12.09, Cosmote и Ziggo их уже показывают, а обход с глубиной 5 до
субботы не дотягивался — владелец спрашивал, куда делись каналы. Аудит
07.09 принят с требованием «видно на 6 дней», поэтому сетки, где день стоит
один запрос, углубляются до 7 (как у эталона flashscore). Цена: +28 запросов
на полный прогон. Дорогие «страница на канал и день» (movistarplus, bbc,
tv3.lt…) не трогаем — по ним отдельное решение владельца (ТЗ-АУДИТ, A8).

Идемпотентен; гонять на ОБЕИХ базах:
    venv\Scripts\python.exe scripts/grid_depth.py
    ssh -i ~/.ssh/streams_schedule root@157.245.77.140 \
        "cd /root/streams-schedule && venv/bin/python scripts/grid_depth.py"
После — пересобрать план: scripts/crawl_plan.py --json data/crawl_plan.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

#: сетки «один дешёвый запрос на день»: было 5 (решение 03.09 до аудита)
DOMAINS = ["atv.com.tr", "cosmotetv.gr", "dr.dk", "raspored.hrt.hr",
           "skai.gr", "sport1tv.hu", "teleman.pl", "trtavaz.com.tr",
           "tv2.no", "ziggosport.nl"]
DEPTH = 7


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = db.connect()
    try:
        for domain in DOMAINS:
            row = conn.execute("SELECT id, selector_config FROM sources "
                               "WHERE domain=?", (domain,)).fetchone()
            if row is None:
                print(f"  {domain}: источника нет — пропуск")
                continue
            config = json.loads(row["selector_config"] or "{}") or {}
            old = config.get("days_ahead")
            if old == DEPTH:
                print(f"  {domain}: уже {DEPTH}")
                continue
            config["days_ahead"] = DEPTH
            conn.execute("UPDATE sources SET selector_config=? WHERE id=?",
                         (json.dumps(config, ensure_ascii=False), row["id"]))
            print(f"  {domain}: {old} → {DEPTH}")
        conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
r"""dagenstv.com (kolla.tv) — день в адресе номером, а не датой.

Самопроверка сбора #205 (06.10): все шесть страниц окна
`…/listWithPrograms?dat=2026-10-06` … `dat=2026-10-11` пришли ОДНИМ файлом
(md5 одинаковый) — ручка параметр `dat` не знает и всегда отдаёт сегодня.
Пять запросов из шести шли впустую, дальних дней у 16 шведских каналов не
было вовсе. Так с начала сентября: в `recon/raw_live` 04.09 и 12.09 страницы
на разные даты тоже одинаковые.

Как сайт берёт другой день — из его бандла (`static/js/main.*.chunk.js`):
`C.set("day", (неделя - 1) * 7 + номер_дня)` — номер дня от СЕГОДНЯ, 0 —
сегодня (`dat` есть только у адреса страницы сайта, в ручку он не идёт).
Проба #209 (GitHub, 06.10): `?day=1` — передачи 07.10, `?day=5` — 11.10.

Обход подставляет номер дня меткой `{DAYNUM}` (0 — сегодня по часам сайта,
`scripts/crawl_fetch.py`); этот скрипт меняет шаблон адреса в карточке.
Идемпотентен. Без `--apply` только показывает. К сайтам не обращается.

Порядок на сервере (`ГРАБЛИ.md`, строка про `crawl_plan.py`):

    1. код ветки с {DAYNUM} у дневных сеток (`app/crawl.py`) на сервере
       (streams-update.sh);
    2. ssh root@157.245.77.140 "cd streams-schedule && \
           venv/bin/python scripts/add_kolla_days.py --apply"
       и то же локально: venv\Scripts\python.exe scripts/add_kolla_days.py --apply
    3. пересобрать план: venv/bin/python scripts/crawl_plan.py --json data/crawl_plan.json
    4. сверить старый и новый план по ВСЕМ полям каждого сайта — измениться
       должен один dagenstv.com (pattern `…?day={DAYNUM}`);
    5. venv/bin/python scripts/push_plan.py 'dagenstv.com: день номером'

Откат карточки:
    venv/bin/python scripts/source_config.py dagenstv.com \
        --pattern "https://www.kolla.tv/api/es/channels/listWithPrograms?dat={YYYY-MM-DD}"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

DOMAIN = "dagenstv.com"

#: ручка данных сайта; `day` — номер дня от сегодня (0 — сегодня)
URL = "https://www.kolla.tv/api/es/channels/listWithPrograms?day={DAYNUM}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="записать в базу (без флага — только показ)")
    args = ap.parse_args()

    conn = db.connect()
    try:
        row = conn.execute("SELECT id, url_pattern FROM sources WHERE domain = ?",
                           (DOMAIN,)).fetchone()
        if not row:
            print(f"источника {DOMAIN} в базе нет — заводить с нуля этот скрипт "
                  f"не умеет")
            return 1
        print(f"{DOMAIN} (id {row['id']}, база {db.db_path()})")
        print(f"   адрес: {row['url_pattern']}\n       → {URL}")
        if row["url_pattern"] == URL:
            print("   уже стоит — менять нечего")
            return 0
        if not args.apply:
            print("это показ; записать — с флагом --apply")
            return 0
        conn.execute("UPDATE sources SET url_pattern = ? WHERE id = ?",
                     (URL, row["id"]))
        conn.commit()
        print("   записано")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

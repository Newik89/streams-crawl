# -*- coding: utf-8 -*-
r"""mediaklikk.hu (M4 Sport) — с одной страницы «сегодня» на адрес на день.

Страница `/musorujsag/` отдаёт сетку MTVA только на сегодня, и матч
Ferencváros — DVSC 10.10 на M4 Sport в обход 06.10 не попал вовсе. Другие дни
сайт берёт POST-ом на ручку программы (`ProgramGuide.js`, функция
`getChanelGuides`; пробы #207, #208 — шапка `app/parsers/mediaklikk_hu.py`).
В коде сайт уже стоит «дневной сеткой» (`DAY_GRID_DOMAINS`, `app/crawl.py`);
этот скрипт кладёт в карточку источника адрес ручки и поля формы с меткой
даты, и добавляет второй канал ручки — M4 Sport+ (номер 34).

Идемпотентен: повторный запуск ничего не дублирует. Без `--apply` только
показывает, что сделает. К сайтам не обращается.

Порядок на сервере (`ГРАБЛИ.md`, строка про `crawl_plan.py`):

    1. код с `DAY_GRID_DOMAINS` уже на сервере (streams-update.sh);
    2. ssh root@157.245.77.140 "cd streams-schedule && \
           venv/bin/python scripts/add_mediaklikk_days.py --apply"
       и то же локально: venv\Scripts\python.exe scripts/add_mediaklikk_days.py --apply
    3. пересобрать план: venv/bin/python scripts/crawl_plan.py --json data/crawl_plan.json
    4. сверить старый и новый план по ВСЕМ полям каждого сайта (не только
       список доменов) — изменился должен один mediaklikk.hu;
    5. venv/bin/python scripts/push_plan.py 'mediaklikk.hu: адрес на день'

Откат карточки:
    venv/bin/python scripts/source_config.py mediaklikk.hu \
        --pattern "https://mediaklikk.hu/musorujsag/" --unset post_fields
(канал M4 Sport+ при откате можно оставить: страница «сегодня» его тоже
держит, разбор знает номер 34).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402

DOMAIN, COUNTRY = "mediaklikk.hu", "HU"

#: ручка программы MTVA: POST, день и каналы — в полях формы
URL = ("https://mediaklikk.hu/wp-content/plugins/hms-global-widgets/widgets/"
       "programGuide/programGuideInterface.php")

#: (номер канала у MTVA, короткий код, имя на сайте, имя в разборе = на витрине)
CHANNELS = [("30", "m4", "M4 Sport", "M4 Sport"),
            ("34", "m4p", "M4 Sport +", "M4 Sport+")]

#: поля формы, как их шлёт сам сайт (`getChanelGuides`): номера и коды через
#: запятую С хвостовой запятой, дата — меткой, её подставит обход
POST_FIELDS = {
    "ChannelIds": "".join(f"{n}," for n, _, _, _ in CHANNELS),
    "ShortCodes": "".join(f"{c}," for _, c, _, _ in CHANNELS),
    "Names": "".join(f"{s}," for _, _, s, _ in CHANNELS),
    "Date": "{YYYY-MM-DD}",
    "Type": "0",
    "buttonType": "text_type",
    "newDesign": "true",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="записать в базу (без флага — только показ)")
    args = ap.parse_args()

    conn = db.connect()
    try:
        row = conn.execute("SELECT id, url_pattern, selector_config FROM sources "
                           "WHERE domain = ?", (DOMAIN,)).fetchone()
        if not row:
            print(f"источника {DOMAIN} в базе нет — заводить с нуля этот скрипт "
                  f"не умеет")
            return 1
        config = json.loads(row["selector_config"] or "{}") or {}
        have = {r["raw_name"] for r in conn.execute(
            "SELECT raw_name FROM source_channels WHERE source_id = ? "
            "AND include = 1", (row["id"],))}
        print(f"{DOMAIN} (id {row['id']}, база {db.db_path()})")
        print(f"   адрес: {row['url_pattern']}\n       → {URL}")
        print(f"   поля формы: {config.get('post_fields')}\n       → {POST_FIELDS}")
        print(f"   каналы в обходе: {sorted(have)} → "
              f"{sorted(have | {raw for _, _, _, raw in CHANNELS})}")
        if not args.apply:
            print("это показ; записать — с флагом --apply")
            return 0
        config["post_fields"] = POST_FIELDS
        conn.execute("UPDATE sources SET url_pattern = ?, selector_config = ? "
                     "WHERE id = ?",
                     (URL, json.dumps(config, ensure_ascii=False), row["id"]))
        for _, _, _, raw in CHANNELS:
            channel_id = dictionary.remember_channel(
                conn, raw, raw, COUNTRY, source_id=row["id"])
            got = conn.execute("SELECT id FROM source_channels WHERE source_id = ? "
                               "AND raw_name = ?", (row["id"], raw)).fetchone()
            if got:
                conn.execute("UPDATE source_channels SET channel_id = ?, "
                             "include = 1 WHERE id = ?", (channel_id, got["id"]))
            else:
                conn.execute("INSERT INTO source_channels (source_id, raw_name, "
                             "channel_id, page_url, include) VALUES (?, ?, ?, '', 1)",
                             (row["id"], raw, channel_id))
        conn.commit()
        print("   записано")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

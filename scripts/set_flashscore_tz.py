# -*- coding: utf-8 -*-
r"""Пояс в карточках эталона flashscore — по часам самого сайта.

Проверка пачки 06.10: в карточках источников у flashscore.mobi стоял
`Etc/GMT-2` (летнее время Парижа, навсегда), у 19 языковых версий — `UTC`.
По этому поясу обход считал «сегодня» сайта и номер дня `?d=`, и в часы у
полуночи (22:00–24:00 UTC) версии просили не тот день; после перевода часов
25.10 mobi в 22:00–23:00 UTC получил бы вчерашнюю страницу под меткой
сегодняшней (повтор #204).

С этой же пачкой обход берёт пояс flashscore из разбора
(`app/parsers/flashscore_mobi.py`, `SITE_TZ`) и от карточки больше не
зависит. Скрипт нужен, чтобы и карточка не врала: её видно в админке, она
едет в план обхода (`data/crawl_plan.json`) и в разбор. Пояса скрипт
берёт из того же `SITE_TZ` — двух списков нет.

Без `--apply` только показывает, что сделает. Повторный запуск ничего не
меняет (пишет только те карточки, где пояс другой). К сайтам не обращается.

Порядок на сервере (`ГРАБЛИ.md`, строка про `crawl_plan.py`):

    1. код пачки уже на сервере (streams-update.sh);
    2. ssh root@157.245.77.140 "cd streams-schedule && \
           venv/bin/python scripts/set_flashscore_tz.py"            — показ
       ssh root@157.245.77.140 "cd streams-schedule && \
           venv/bin/python scripts/set_flashscore_tz.py --apply"    — запись
       и то же локально: venv\Scripts\python.exe scripts/set_flashscore_tz.py --apply
    3. пересобрать план: venv/bin/python scripts/crawl_plan.py --json data/crawl_plan.json
    4. сверить старый и новый план по ВСЕМ полям каждого сайта — меняется
       только `timezone` у 20 сайтов flashscore;
    5. venv/bin/python scripts/push_plan.py 'flashscore: пояс по часам сайта'

Откат карточек (вернуть то, что стояло до 06.10):
    venv/bin/python scripts/set_flashscore_tz.py --undo --apply
и снова шаги 3–5. Обход при этом всё равно пойдёт по `SITE_TZ` — откат
кода пачки нужен отдельно.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.parsers.flashscore_mobi import DOMAIN, SITE_TZ  # noqa: E402

#: что стояло в карточках серверной базы до правки (копия 06.10) — для отката
OLD_TZ = {domain: "UTC" for domain in SITE_TZ}
OLD_TZ[DOMAIN] = "Etc/GMT-2"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="записать в базу (без флага — только показ)")
    ap.add_argument("--undo", action="store_true",
                    help="вернуть пояса, что стояли до 06.10 (откат)")
    args = ap.parse_args()
    wanted = OLD_TZ if args.undo else SITE_TZ

    conn = db.connect()
    try:
        print(f"база {db.db_path()}")
        changes = []
        for domain, tz in wanted.items():
            row = conn.execute("SELECT id, timezone FROM sources WHERE domain = ?",
                               (domain,)).fetchone()
            if row is None:
                print(f"   {domain}: карточки нет — пропуск")
                continue
            if (row["timezone"] or "") == tz:
                print(f"   {domain}: {tz} — уже так")
                continue
            print(f"   {domain}: {row['timezone']} → {tz}")
            changes.append((tz, row["id"]))
        if not changes:
            print("менять нечего")
            return 0
        if not args.apply:
            print(f"это показ ({len(changes)} карточек); записать — с флагом --apply")
            return 0
        conn.executemany("UPDATE sources SET timezone = ? WHERE id = ?", changes)
        conn.commit()
        print(f"записано: {len(changes)} карточек; теперь пересобрать план "
              f"(scripts/crawl_plan.py --json data/crawl_plan.json)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

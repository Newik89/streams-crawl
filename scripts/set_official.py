# -*- coding: utf-8 -*-
r"""Пометить источник как официальный сайт своих каналов (или снять отметку).

Правило владельца 07.10.2026 (вопрос №2112): у канала, у которого есть свой
сайт, строки агрегаторов не берём, пока свой сайт этот день показывает.
Решает это `app/channel_owner.py`, а кто «свой» — говорит отметка
`selector_config.official` в карточке источника, которую ставит этот скрипт.

    venv\Scripts\python.exe scripts/set_official.py                 # кто помечен
    venv\Scripts\python.exe scripts/set_official.py sportklub.hr    # покажет, что сделает
    venv\Scripts\python.exe scripts/set_official.py sportklub.hr --apply
    venv\Scripts\python.exe scripts/set_official.py mojtv.hr --off --apply

Отметку ставим только сайтам самого канала или его оператора: официальный
гид TV 2 (`tvtid.tv2.dk`), `sportklub.hr`, `oneplay.cz`, `mediaklikk.hu`,
`dr.dk`. Агрегаторам (`mojtv.hr`, `port.hu`, `tvsporten.dk`, `teleman.pl`…)
— никогда: по 93 каналам из 316 они единственный источник.

К сайтам не обращается. Гонять в ОБЕИХ базах — локальной и серверной.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import channel_owner, db  # noqa: E402


def показать(conn) -> None:
    помечены = channel_owner.официальные(conn)
    print(f"официальными помечены {len(помечены)} источник(ов):")
    for source_id, домен in sorted(помечены.items(), key=lambda x: x[1]):
        каналов = conn.execute(
            "SELECT COUNT(*) FROM source_channels WHERE source_id = ?",
            (source_id,)).fetchone()[0]
        отметок = conn.execute(
            "SELECT COUNT(*) FROM event_channels WHERE source_id = ?",
            (source_id,)).fetchone()[0]
        print(f"   {домен} (id {source_id}): каналов в карточке {каналов}, "
              f"отметок {отметок}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("domain", nargs="?", default="",
                    help="домен источника; без него — список помеченных")
    ap.add_argument("--off", action="store_true", help="снять отметку")
    ap.add_argument("--apply", action="store_true",
                    help="записать (без флага — только показ)")
    args = ap.parse_args()

    conn = db.connect()
    try:
        if not args.domain:
            показать(conn)
            return 0
        row = conn.execute(
            "SELECT id, domain, selector_config FROM sources WHERE domain = ? "
            "OR domain = ?", (args.domain, f"www.{args.domain}")).fetchone()
        if row is None:
            print(f"источника «{args.domain}» в базе нет")
            return 1
        config = json.loads(row["selector_config"] or "{}") or {}
        было = bool(config.get(channel_owner.ФЛАГ))
        станет = not args.off
        print(f"{row['domain']} (id {row['id']}): официальный "
              f"{'да' if было else 'нет'} → {'да' if станет else 'нет'}")
        каналы = [r["raw_name"] for r in conn.execute(
            "SELECT raw_name FROM source_channels WHERE source_id = ? "
            "ORDER BY raw_name", (row["id"],))]
        print(f"   каналов в карточке {len(каналы)}: "
              f"{', '.join(каналы[:12])}{' …' if len(каналы) > 12 else ''}")
        if было == станет:
            print("   уже так — менять нечего")
            return 0
        if not args.apply:
            print("   это показ; записать — с флагом --apply")
            return 0
        if станет:
            config[channel_owner.ФЛАГ] = True
        else:
            config.pop(channel_owner.ФЛАГ, None)
        conn.execute("UPDATE sources SET selector_config = ? WHERE id = ?",
                     (json.dumps(config, ensure_ascii=False), row["id"]))
        conn.commit()
        print("   записано")
        показать(conn)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

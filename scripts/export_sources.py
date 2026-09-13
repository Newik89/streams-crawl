# -*- coding: utf-8 -*-
r"""Выгрузка технических полей из базы обратно в `recon/sources.csv`.

Зачем: браузерные проверки (`probe_browser.py`, `reanalyze_browser.py`) пишут
вердикты ТОЛЬКО в базу. Файл `sources.csv` при этом отстаёт, и запуск
`import_sources.py` откатывает разведку — 29.08.2026 так и вышло: уровни
A=22/B=47/D=6 превратились в A=13/B=32/D=32. Этот скрипт закрывает разрыв:
после любой проверки прогнать его, и файл снова совпадает с базой.

Строки, которых в базе нет, не трогаются и не удаляются: убирать источники —
только по слову владельца.

Запуск:
    venv\Scripts\python.exe scripts/export_sources.py
    venv\Scripts\python.exe scripts/export_sources.py --dry-run   (только показать)
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402

CSV_PATH = Path(__file__).resolve().parent.parent / "recon" / "sources.csv"

# колонка в файле -> колонка в базе
FIELDS = {
    "parse_level": "parse_level",
    "needs_js": "needs_js",
    "protection": "protection",
    "url_pattern": "url_pattern",
    "notes": "notes",
    "timezone": "timezone",
    "country": "country",
}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="только показать разницу")
    args = ap.parse_args()

    conn = db.connect()
    in_db = {r["domain"]: r for r in conn.execute("SELECT * FROM sources")}
    conn.close()

    with CSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        header = reader.fieldnames or []
        rows = list(reader)

    changed = missing = added = 0
    # источник, заведённый мимо csv (админкой или скриптом), дописывается в
    # файл — иначе свежая база (сервер) после import_sources его не узнает
    # (поймано 02.09: шесть доменов не доехали до сервера)
    in_csv = {row["domain"] for row in rows}
    for domain, src in sorted(in_db.items()):
        if domain in in_csv:
            continue
        fresh = {col: "" for col in header}
        fresh["domain"] = domain
        for col in ("name", "country", "timezone"):
            if col in header and src[col] is not None:
                fresh[col] = str(src[col])
        if "url_primary" in header:
            fresh["url_primary"] = src["base_url"] or ""
        for col, db_col in FIELDS.items():
            if col in header and src[db_col] is not None:
                fresh[col] = ("yes" if src[db_col] else "no") \
                    if col == "needs_js" else str(src[db_col])
        rows.append(fresh)
        print(f"  {domain:24} дописан в csv")
        added += 1
        changed += 1
    for row in rows:
        src = in_db.get(row["domain"])
        if not src:
            missing += 1
            continue
        for col, db_col in FIELDS.items():
            if col not in header:
                continue
            value = src[db_col]
            if col == "needs_js":
                # в файле это слово, в базе — 0/1; `import_sources.py` ждёт слово
                value = "yes" if value else "no"
            value = "" if value is None else str(value)
            if row[col] != value:
                print(f"  {row['domain']:24} {col}: «{row[col]}» -> «{value}»")
                row[col] = value
                changed += 1

    print(f"\nполей обновлено: {changed} (из них дописано строк: {added}); "
          f"строк без пары в базе: {missing}")
    if args.dry_run:
        print("(--dry-run: файл не тронут)")
        return 0
    if not changed:
        print("файл и база уже совпадают")
        return 0

    backup = CSV_PATH.with_suffix(".csv.bak")
    shutil.copy2(CSV_PATH, backup)
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    print(f"записано: {CSV_PATH}\nпрежний файл: {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

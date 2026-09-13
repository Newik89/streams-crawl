# -*- coding: utf-8 -*-
r"""Поправить карточку источника в базе — одинаково локально и на сервере.

База живёт в двух местах (локальная — черновик, серверная — витрина), и
правки карточек должны попадать в обе одной и той же командой, а не
руками через админку дважды. Скрипт меняет `selector_config`
(JSON с настройками разбора: `days_ahead`, `url_marks`, `headers`…)
и, по `--pattern`, колонку `url_pattern`; остальные поля карточки
не трогает. К сайтам не обращается.

Запуск:
    venv\Scripts\python.exe scripts/source_config.py flashscore.mobi --show
    venv\Scripts\python.exe scripts/source_config.py flashscore.mobi --set days_ahead=7
    venv\Scripts\python.exe scripts/source_config.py sport5.co.il --unset days_ahead
    venv\Scripts\python.exe scripts/source_config.py sporteventz.com --pattern "https://…{KYIVOFF}"

`--pattern` меняет колонку `url_pattern` (шаблон адреса с метками) — тоже
одинаково на обеих базах; понадобился для C1 (смещение Киева от даты).

На сервере — тем же файлом (база берётся из `STREAMS_DB`, как у сайта):
    scp scripts/source_config.py root@157.245.77.140:/root/streams-schedule/scripts/
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/source_config.py flashscore.mobi --set days_ahead=7"

Значение после `=` читается как JSON, если получается (`7` → число,
`true` → истина, `{"a":1}` → объект), иначе остаётся строкой.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def _value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("domain", help="домен источника, как в карточке")
    ap.add_argument("--set", action="append", default=[], metavar="КЛЮЧ=ЗНАЧЕНИЕ",
                    help="записать поле (можно несколько раз)")
    ap.add_argument("--unset", action="append", default=[], metavar="КЛЮЧ",
                    help="убрать поле")
    ap.add_argument("--pattern", default=None, metavar="ШАБЛОН",
                    help="записать url_pattern (шаблон адреса с метками)")
    ap.add_argument("--show", action="store_true", help="только показать")
    args = ap.parse_args()

    conn = db.connect()
    try:
        row = conn.execute("SELECT id, domain, selector_config, url_pattern "
                           "FROM sources WHERE domain=?",
                           (args.domain,)).fetchone()
        if not row:
            print(f"источника {args.domain} в базе нет")
            return 1
        if args.pattern is not None and not args.show \
                and args.pattern != (row["url_pattern"] or ""):
            conn.execute("UPDATE sources SET url_pattern=? WHERE id=?",
                         (args.pattern, row["id"]))
            conn.commit()
            print(f"{row['domain']}: url_pattern\n  было: {row['url_pattern']}"
                  f"\n  стало: {args.pattern}")
        config = json.loads(row["selector_config"] or "{}") or {}
        before = json.dumps(config, ensure_ascii=False, sort_keys=True)
        for pair in args.set:
            if "=" not in pair:
                print(f"ожидал КЛЮЧ=ЗНАЧЕНИЕ, получил {pair!r}")
                return 2
            key, _, text = pair.partition("=")
            config[key.strip()] = _value(text.strip())
        for key in args.unset:
            config.pop(key, None)
        after = json.dumps(config, ensure_ascii=False, sort_keys=True)
        if not args.show and after != before:
            conn.execute("UPDATE sources SET selector_config=? WHERE id=?",
                         (json.dumps(config, ensure_ascii=False), row["id"]))
            conn.commit()
        state = "без изменений" if after == before else "записано"
        print(f"{row['domain']} ({db.db_path() if hasattr(db, 'db_path') else 'база'}): "
              f"{after}  — {state}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

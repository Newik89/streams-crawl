# -*- coding: utf-8 -*-
r"""Каналы источника: показать и включить/выключить в обходе.

`source_channels.include=0` — канал остаётся в базе и на карточке источника,
но обход его страницу не качает (так 20.09 выключены Nova Sport 1–6 у
oneplaysport.cz). Ничего не удаляет. К сайтам не обращается.

Запуск (локально и на сервере — одним и тем же файлом):
    venv\Scripts\python.exe scripts/channel_include.py tv.orf.at
    venv\Scripts\python.exe scripts/channel_include.py tv.orf.at --off "ORF KIDS"
    venv\Scripts\python.exe scripts/channel_include.py tv.orf.at --on "ORF KIDS"

После переключения на сервере пересобрать план и доставить его в git
(порядок из грабли о пересборке: сверить домены → push_plan.py):
    venv/bin/python scripts/crawl_plan.py --json data/crawl_plan.json
    venv/bin/python scripts/push_plan.py "тексту коммита"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def _show(conn, source_id: int) -> None:
    for r in conn.execute(
            "SELECT raw_name, include, page_url FROM source_channels "
            "WHERE source_id=? ORDER BY raw_name", (source_id,)):
        mark = "вкл " if r["include"] else "ВЫКЛ"
        print(f"  {mark}  {r['raw_name']:20} {r['page_url'] or ''}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("domain", help="домен источника, как в карточке")
    ap.add_argument("--off", metavar="КАНАЛ", help="выключить канал (точное имя)")
    ap.add_argument("--on", dest="on_", metavar="КАНАЛ",
                    help="включить канал обратно")
    args = ap.parse_args()

    conn = db.connect()
    try:
        row = conn.execute("SELECT id FROM sources WHERE domain=?",
                           (args.domain,)).fetchone()
        if not row:
            print(f"источника {args.domain} в этой базе нет")
            return 1
        name, value = (args.off, 0) if args.off else (args.on_, 1)
        if name:
            cur = conn.execute(
                "UPDATE source_channels SET include=? "
                "WHERE source_id=? AND raw_name=?", (value, row["id"], name))
            if cur.rowcount == 0:
                print(f"канала «{name}» у {args.domain} нет; есть такие:")
                _show(conn, row["id"])
                return 1
            conn.commit()
            print(f"{args.domain}: «{name}» теперь "
                  f"{'в обходе' if value else 'НЕ обходится'}")
        print(f"каналы {args.domain}:")
        _show(conn, row["id"])
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

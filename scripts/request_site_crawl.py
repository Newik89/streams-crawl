# -*- coding: utf-8 -*-
r"""Заявка на точечный обход ОДНОГО сайта — с сервера, как кнопка «Обойти сайт».

Тот же путь, что у кнопки владельца (`app/web.crawl_site`): заявка уходит с
сервера, сайт обходит GitHub, по окончании GitHub стучит серверу и сервер сам
забирает и вливает результат (`results/site/`). Ассистенту нужен, когда сайт
надо пересобрать после починки, а кнопку нажимать некому.

    venv/bin/python scripts/request_site_crawl.py rtp.pt

Сбор уже заказан или идёт — заявка не шлётся (замок `crawl_hook.running`).
Сайты с пометкой «качает сервер» сюда не идут: им своя дорога
(`scripts/server_crawl.py --only`).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crawl_hook, db, trigger  # noqa: E402

SITE_DAYS = 6          # как у кнопки: сайт пересобирается целиком


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    domain = sys.argv[1].strip().lower()
    now = datetime.now(crawl_hook.KYIV)
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT enabled, status, selector_config FROM sources "
            "WHERE domain = ?", (domain,)).fetchone()
        if row is None:
            print(f"источника {domain} нет в базе")
            return 1
        if (json.loads(row["selector_config"] or "{}") or {}).get("by_server"):
            print(f"{domain} качает сам сервер — это scripts/server_crawl.py "
                  "--only, заявка на GitHub ему не нужна")
            return 1
        if not row["enabled"] or row["status"] in ("new", "deferred",
                                                   "closed", "parked"):
            print(f"{domain} сейчас не в плане обхода "
                  f"(enabled={row['enabled']}, статус «{row['status']}»)")
            return 1
        busy = crawl_hook.running(conn)
        if busy:
            print(f"{now:%d.%m %H:%M} заявка по {domain} не отправлена: сбор "
                  f"уже {busy['state']} с {busy['since']} ({busy['what']})")
            return 0

        ok, words = trigger.dispatch_crawl(SITE_DAYS, only=domain)
        if not ok:
            ok, words = trigger.push_request_tag(
                "site", trigger.encode_probe_url(domain))
        print(f"{now:%d.%m %H:%M} заявка «обойти {domain}»: {words}")
        if ok:
            crawl_hook.mark(conn, "заявка", f"сайт {domain}")
            db.set_setting(conn, "site_crawl_request",
                           f"{domain}|{now:%Y-%m-%d %H:%M}")
            conn.commit()
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

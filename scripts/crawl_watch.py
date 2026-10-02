# -*- coding: utf-8 -*-
r"""Сторож заказа обхода — cron сервера раз в 15 минут (владелец 02.10.2026).
Что делает и почему — в шапке `app/watch.py`.

    venv/bin/python scripts/crawl_watch.py            решить и сделать
    venv/bin/python scripts/crawl_watch.py --check    только сказать, что бы сделал

Действия: повторная заявка — `scripts/request_crawl.py days N --force --unlock`
(замок «сбор идёт» снимаем: по API видно, что прогон мёртв); забор —
`scripts/hook_pull.sh`, тот же путь, что по стуку GitHub.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import crawl_hook, db, trigger, watch  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    check = "--check" in sys.argv[1:]
    now = datetime.now(watch.KYIV)
    stamp = f"{now:%d.%m %H:%M}"
    conn = db.connect()
    try:
        order = watch.parse_order(db.get_setting(conn, "crawl_request"))
        if order is None:
            print(f"{stamp} заказов не было — нечего сторожить")
            return 0
        state = watch.load_state(conn, order)
        slug = trigger._repo_slug()
        runs = watch.github_runs(slug)
        if not runs:
            print(f"{stamp} GitHub не ответил на список прогонов — подожду следующего тика")
            return 0
        run = watch.run_for(order, runs)
        fresh = watch.new_on_github(ROOT)
        action, words = watch.decide(order, run, now, state, bool(fresh))
        print(f"{stamp} {action}: {words}" + (" (--check, ничего не делаю)" if check else ""))
        if check or action in ("wait", "none"):
            return 0
        if action == "done":
            state["done"] = True
            watch.note(conn, words)
        elif action == "alarm":
            state["alarmed"] = True
            watch.note(conn, "ТРЕВОГА — " + words)
        elif action == "pull":
            watch.note(conn, words)
            crawl_hook.clear(conn)
            r = subprocess.run(["/bin/sh", str(ROOT / "scripts" / "hook_pull.sh")],
                               capture_output=True, text=True, timeout=1800)
            state["done"] = r.returncode == 0
            print(f"{stamp} забор: код {r.returncode} {(r.stdout or r.stderr).strip()[:200]}")
        elif action == "reorder":
            watch.note(conn, words)
            r = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "request_crawl.py"),
                 "days", str(order["days"]), "--force", "--unlock"],
                capture_output=True, text=True, timeout=600)
            print((r.stdout or r.stderr).strip()[:400])
            # заявка переписала `crawl_request` — память сторожа переезжает
            # на новый заказ, помня, что повтор уже был
            new = watch.parse_order(db.get_setting(conn, "crawl_request"))
            state = {"order": (new or order)["stamp"], "reordered": True}
        watch.save_state(conn, state)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

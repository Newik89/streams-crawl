# -*- coding: utf-8 -*-
r"""Сторож заказа обхода — cron сервера раз в 15 минут (владелец 02.10.2026).
Что делает и почему — в шапке `app/watch.py`.

    venv/bin/python scripts/crawl_watch.py            решить и сделать
    venv/bin/python scripts/crawl_watch.py --check    только сказать, что бы сделал
    venv/bin/python scripts/crawl_watch.py --cron     строки cron плановых заявок (по watch.SCHEDULE)

Действия: повторная заявка — `scripts/request_crawl.py days N --force --unlock`
(замок «сбор идёт» снимаем: по API видно, что прогон мёртв); забор —
`scripts/hook_pull.sh`, тот же путь, что по стуку GitHub.
С 05.10 ещё: отмена зависшего прогона — тег-заявка `btn-cancel-<id>`
(исполняет `queue.yml`), память — настройка `crawl_cancel`; сорвавшийся
плановый (`crawl_missed`: заявка не ушла или упала и после повтора) —
досрочный заказ следующего планового, память — `crawl_early`.
Одна проверка — один запрос к API GitHub (список прогонов обхода).
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import crawl_hook, db, trigger, watch  # noqa: E402


def _now() -> datetime:
    """Часы сторожа отдельной функцией — проверки ставят нужное время."""
    return datetime.now(watch.KYIV)


def order_crawl(days: int) -> str:
    """Заказать полный обход сейчас — тот же путь, что повтор с 02.10:
    заявка снимает замок и пишет `crawl_request`; ждёт старта до 3 мин."""
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "request_crawl.py"),
         "days", str(days), "--force", "--unlock"],
        capture_output=True, text=True, timeout=600)
    return (r.stdout or r.stderr).strip()[:400]


def pull() -> tuple[int, str]:
    r = subprocess.run(["/bin/sh", str(ROOT / "scripts" / "hook_pull.sh")],
                       capture_output=True, text=True, timeout=1800)
    return r.returncode, (r.stdout or r.stderr).strip()[:200]


def say(conn, stamp: str, words: str, check: bool) -> None:
    """Решение сторожа — в терминал (журнал cron) и строкой в «Прогоны»."""
    print(f"{stamp} сторож: {words}" + (" (--check, ничего не делаю)" if check else ""))
    if not check:
        watch.note(conn, words)


def tick(conn, now: datetime, check: bool = False) -> None:
    """Одна проверка сторожа. Сеть — только `watch.github_runs` (один раз),
    `trigger.push_request_tag` (отмена), `order_crawl` и `pull`."""
    stamp = f"{now:%d.%m %H:%M}"
    slug = trigger._repo_slug()
    runs = watch.github_runs(slug, limit=watch.RUNS_LIMIT, workflow=watch.CRAWL_WORKFLOW)
    if not runs:
        print(f"{stamp} GitHub не ответил на список прогонов — подожду следующего тика")
        return

    order = watch.parse_order(db.get_setting(conn, "crawl_request"))
    state = watch.load_state(conn, order) if order else {}
    run = watch.run_for(order, watch.crawl_only(runs, slug)) if order else None
    if order and "slot" not in state:
        # плановый ли заказ (по таблице SCHEDULE) — только плановый сорвавшийся
        # сторож заказывает досрочно (05.10)
        slot = watch.slot_for(order["at"], order["days"])
        state["slot"] = watch.stamp(slot) if slot else ""

    # ── 6. зависшие прогоны: отменить, потом убедиться, что отменены ──────────
    cancels = watch.load_json(conn, "crawl_cancel")
    cancelling = []
    for action, rid, words in watch.cancel_decisions(
            runs, now, cancels, slug, order_run_id=(run or {}).get("id")):
        if action == "forget":
            cancels.pop(rid, None)
            continue
        if action == "confirmed":
            say(conn, stamp, words, check)
            cancels.pop(rid, None)
        elif action == "alarm":
            say(conn, stamp, words, check)
            cancels[rid]["alarmed"] = True
        elif action == "cancel":
            cancelling.append(rid)
            say(conn, stamp, words, check)
            if not check:
                ok, answer = trigger.push_request_tag("cancel", rid)
                print(f"{stamp} заявка отмены #{rid}: {answer}")
                if ok:
                    number = next((r.get("run_number") for r in runs
                                   if str(r.get("id")) == rid), "?")
                    cancels[rid] = {"at": watch.stamp(now), "number": number}
    if not check:
        watch.save_json(conn, "crawl_cancel", cancels)

    # ── 1–3. заказ: стартовал ли, дошёл ли, забран ли ────────────────────────
    early = watch.load_json(conn, "crawl_early")
    missed = watch.load_json(conn, "crawl_missed")
    if order is None:
        print(f"{stamp} заказов не было — следить не за чем")
    else:
        result = "unknown"
        if run is not None and (run.get("status") or "") not in watch.RUNNING:
            started = watch._utc(run.get("run_started_at") or run.get("created_at") or "") or now
            result = watch.result_state(ROOT, started)
        action, words = watch.decide(order, run, now, state, result)
        print(f"{stamp} {action}: {words}" + (" (--check, ничего не делаю)" if check else ""))
        is_early = bool(state.get("early"))
        why = ("обход не стартовал" if run is None else
               f"прогон #{run.get('run_number')} кончился «{run.get('conclusion') or '?'}»")
        if check or action in ("wait", "none"):
            pass
        elif action == "done":
            state["done"] = True
            watch.note(conn, words)
            if is_early:
                early["state"] = "done"
                watch.save_json(conn, "crawl_early", early)
        elif action == "alarm" and is_early:
            # 5.: досрочный — один на сорвавшийся плановый; сорвался и он —
            # тревога, дальше ждём планового (не крутим по кругу)
            state["alarmed"] = True
            early["state"] = "failed"
            watch.save_json(conn, "crawl_early", early)
            nxt = (early.get("replaces") or "?")[-5:]
            say(conn, stamp, f"ТРЕВОГА — досрочный обход тоже не прошёл ({why}). "
                             f"Больше не заказываю; плановый {nxt} пойдёт как обычно, "
                             f"проверьте GitHub", check)
        elif action == "alarm" and state.get("slot"):
            # 5.: плановый упал и после повтора — не тревога-и-тишина, а
            # досрочный заказ следующего планового (ниже, в этом же тике)
            state["alarmed"] = True
            say(conn, stamp, f"плановый обход {state['slot'][-5:]} не удался и после "
                             f"повтора ({why})", check)
            if missed.get("slot") != state["slot"]:
                missed = {"slot": state["slot"], "days": order["days"],
                          "at": watch.stamp(now), "why": why, "state": "missed"}
                watch.save_json(conn, "crawl_missed", missed)
        elif action == "alarm":
            state["alarmed"] = True
            watch.note(conn, "ТРЕВОГА — " + words)
        elif action == "pull":
            watch.note(conn, words)
            crawl_hook.clear(conn)
            code, out = pull()
            state["done"] = code == 0
            if is_early and code == 0:
                early["state"] = "done"
                watch.save_json(conn, "crawl_early", early)
            print(f"{stamp} забор: код {code} {out}")
        elif action == "reorder":
            watch.note(conn, words)
            print(order_crawl(order["days"]))
            # заявка переписала `crawl_request` — память сторожа переезжает
            # на новый заказ, помня, что повтор уже был
            new = watch.parse_order(db.get_setting(conn, "crawl_request"))
            state = {"order": (new or order)["stamp"], "reordered": True,
                     "slot": state.get("slot", ""), "early": is_early}
        if not check:
            watch.save_state(conn, state)

    # ── 5. сорвавшийся плановый: заказать следующий досрочно ─────────────────
    last = watch.parse_order(db.get_setting(conn, "crawl_request"))
    action, plan, words = watch.plan_early(missed, runs, now, early, last,
                                           skip_ids=cancelling + list(cancels), slug=slug)
    if action == "none":
        if missed.get("state") == "missed" and not check:
            missed["state"] = "handled"
            watch.save_json(conn, "crawl_missed", missed)
        return
    say(conn, stamp, words, check)
    if check:
        return
    if action != "order":
        missed["state"] = action
        watch.save_json(conn, "crawl_missed", missed)
        return
    # заявка сама снимет ложную отметку «идёт» (--unlock); зависшие прогоны
    # уже отменяются выше — новый встанет в очередь и пойдёт после них
    print(order_crawl(plan["days"]))
    new = watch.parse_order(db.get_setting(conn, "crawl_request"))
    if new is None or (last and new["stamp"] == last["stamp"]):
        # заявка не ушла — досрочный считаем сорвавшимся сразу
        missed["state"] = "failed"
        watch.save_json(conn, "crawl_missed", missed)
        watch.note(conn, "ТРЕВОГА — досрочный обход заказать не вышло (GitHub не "
                         "принял заявку). Больше не заказываю; плановый пойдёт как обычно")
        return
    early = dict(plan, ordered_at=new["stamp"], state="ordered")
    watch.save_json(conn, "crawl_early", early)
    missed["state"] = "handled"
    watch.save_json(conn, "crawl_missed", missed)
    # досрочный — уже второй заказ: повтора у него нет, сорвался — тревога
    watch.save_state(conn, {"order": new["stamp"], "reordered": True,
                            "slot": plan["for"], "early": True})


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if "--cron" in sys.argv[1:]:
        print("\n".join(watch.cron_lines(str(ROOT), sys.executable)))
        return 0
    check = "--check" in sys.argv[1:]
    conn = db.connect()
    try:
        tick(conn, _now(), check)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

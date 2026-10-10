# -*- coding: utf-8 -*-
"""Схема сбоев, шаг 3: причина провала — от шагов обхода до решения сторожа.

Цепочка: `scripts/fail_reason.py` (код по итогам шагов и report.json) →
стук с подписью, в которую входит причина (`crawl_hook.sign/verify`) →
память `crawl_fail_reasons` (`remember_failure`/`fail_reason`) →
`watch.failure_of` + `RECOVERY`. В сеть не ходит. Запуск:

    venv\\Scripts\\python.exe scripts/test_fail_reason.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="reason-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")
(TMP / "secret").write_text("слово\n", encoding="utf-8")
os.environ["STREAMS_HOOK_SECRET_FILE"] = str(TMP / "secret")

import fail_reason  # noqa: E402
from app import crawl_hook, db, watch  # noqa: E402

зелёных = красных = 0


def проверка(имя, вышло, ждём, extra=""):
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r} {extra}")


def папка(rows=None, games=None) -> Path:
    п = TMP / f"raw{len(list(TMP.iterdir()))}"
    п.mkdir()
    if rows is not None:
        (п / "report.json").write_text(json.dumps({"строки": rows}, ensure_ascii=False), encoding="utf-8")
    if games is not None:
        (п / "games.json").write_text(json.dumps(games, ensure_ascii=False), encoding="utf-8")
    return п


def стр(итог, почему="", domain="a.test"):
    return {"domain": domain, "итог": итог, "почему": почему, "url": f"https://{domain}/x"}


def main() -> int:
    print("1. код причины по шагам")
    ok = {"env": "success", "readers": "success", "fetch": "success", "parse": "success", "push": "success"}
    r = fail_reason.reason
    проверка("job отменён → timeout", r(ok, "cancelled"), "timeout")
    проверка("упало окружение → env", r({**ok, "env": "failure"}, "failure"), "env")
    проверка("упали читалки → env", r({**ok, "readers": "failure"}, "failure"), "env")
    пусто = папка(rows=[])
    проверка("обход без запросов → plan", r({**ok, "fetch": "failure"}, "failure", пусто), "plan")
    бан = папка(rows=[стр("заглушка защиты"), стр("не открылась", "HTTP 403"),
                      стр("не открылась", "timeout"), стр("расписание есть")])
    проверка("половина неоткрывшихся — защита → fetch-ban",
             r({**ok, "fetch": "failure"}, "failure", бан), "fetch-ban")
    лёг = папка(rows=[стр("не открылась", "HTTP 520"), стр("не открылась", "HTTP 503"),
                      стр("не открылась", "DNS"), стр("расписание есть")])
    проверка("половина — 5xx → fetch-down", r({**ok, "fetch": "failure"}, "failure", лёг), "fetch-down")
    сеть = папка(rows=[стр("не открылась", "timeout"), стр("не открылась", "DNS"),
                       стр("не открылась", "HTTP 403")])
    проверка("остальное → fetch-net", r({**ok, "fetch": "failure"}, "failure", сеть), "fetch-net")
    нет_отчёта = папка()
    проверка("обход упал, отчёта нет → plan", r({**ok, "fetch": "failure"}, "failure", нет_отчёта), "plan")
    мало = папка(rows=[стр("расписание есть")], games={"игр": 3, "games": []})
    проверка("разбор дошёл, игр мало → few", r({**ok, "parse": "failure"}, "failure", мало), "few")
    упал = папка(rows=[стр("расписание есть")])
    проверка("разбор упал без games.json → parse", r({**ok, "parse": "failure"}, "failure", упал), "parse")
    проверка("push → push", r({**ok, "push": "failure"}, "failure"), "push")
    # переразбор (шаг 4): страниц прежнего сбора нет — до разбора
    проверка("переразбор: прогон не найден → pages", r({**ok, "prior": "failure", "fetch": "skipped"}, "failure"), "pages")
    проверка("переразбор: артефакт истёк → pages", r({**ok, "pages": "failure", "fetch": "skipped"}, "failure"), "pages")
    проверка("переразбор: разбор упал → parse (обход пропущен — не причина)",
             r({**ok, "prior": "success", "pages": "success", "fetch": "skipped", "parse": "failure"}, "failure", упал), "parse")
    проверка("слова причины pages", "артефакт" in watch.reason_words("pages"), True)
    проверка("шаг пропущен (skipped) — не провал", r({**ok, "readers": "skipped", "push": "skipped"}, "failure"), "unknown")

    print("2. подпись стука с причиной")
    conn = db.connect(); db.init_db(conn)
    secret = "слово".encode()
    stamp = str(int(datetime.now(timezone.utc).timestamp()))
    s = crawl_hook.sign(secret, stamp, "done-fail", "full-6", "fetch-ban")
    проверка("с причиной — принят", crawl_hook.verify(conn, stamp, "done-fail", "full-6", s, "fetch-ban")[0], True)
    stamp2 = str(int(stamp) + 1)
    s2 = crawl_hook.sign(secret, stamp2, "done-fail", "full-6", "fetch-ban")
    проверка("подменили причину — подпись не сошлась",
             crawl_hook.verify(conn, stamp2, "done-fail", "full-6", s2, "fetch-net"), (False, "подпись"))
    stamp3 = str(int(stamp) + 2)
    s3 = crawl_hook.sign(secret, stamp3, "done-ok", "full-6")
    проверка("без причины — прежняя подпись работает", crawl_hook.verify(conn, stamp3, "done-ok", "full-6", s3)[0], True)
    stamp4 = str(int(stamp) + 3)
    s4 = crawl_hook.sign(secret, stamp4, "done-fail", "full-6", "x;rm")
    проверка("кривая причина — отказ", crawl_hook.verify(conn, stamp4, "done-fail", "full-6", s4, "x;rm"), (False, "причина"))

    print("3. память причин и поиск по виду и времени")
    t0 = datetime(2026, 10, 9, 13, 50, tzinfo=timezone.utc)
    crawl_hook.remember_failure(conn, "full-2", "fetch-ban", now=t0)
    crawl_hook.remember_failure(conn, "full-6", "parse", now=t0 + timedelta(minutes=3))
    crawl_hook.remember_failure(conn, "full-2", "bad reason!", now=t0)
    проверка("нашли свою по виду и времени", crawl_hook.fail_reason(conn, "full-2", t0 + timedelta(minutes=5)), "fetch-ban")
    проверка("другой вид — своя причина", crawl_hook.fail_reason(conn, "full-6", t0), "parse")
    проверка("далеко по времени — пусто", crawl_hook.fail_reason(conn, "full-2", t0 + timedelta(hours=2)), "")
    проверка("кривая причина не запомнена", json.loads(db.get_setting(conn, crawl_hook.FAIL_MEMORY)).__len__(), 2)
    for i in range(40):
        crawl_hook.remember_failure(conn, "date-x", "env", now=t0 + timedelta(minutes=i))
    проверка("память не растёт бесконечно", len(json.loads(db.get_setting(conn, crawl_hook.FAIL_MEMORY))), crawl_hook.FAIL_KEEP)
    conn.close()

    print("4. таблица сторожа по причине")
    st = {"what": "full-6", "slot": "2026-10-09 16:15"}   # плановый — пришёл в слот
    проверка("planned + fetch-ban → ключ с причиной", watch.failure_of(st, "failed", "fetch-ban"), "planned-failed-fetch-ban")
    проверка("… и это ТРЕВОГА", watch.recovery(watch.failure_of(st, "failed", "fetch-ban")), "alarm")
    проверка("planned + fetch-net → общий ключ (досрочный)",
             (watch.failure_of(st, "failed", "fetch-net"), watch.recovery("planned-failed")), ("planned-failed", "early"))
    проверка("site + fetch-ban → ТРЕВОГА, не повтор", watch.recovery(watch.failure_of({"what": "site-x.test"}, "failed", "fetch-ban")), "alarm")
    # схема сбоев, шаг 4: parse / few / push у полного → переразбор без обхода
    проверка("manual + parse → переразбор", watch.recovery(watch.failure_of({"what": "full-2"}, "failed", "parse")), "reparse")
    проверка("planned + few → переразбор", watch.recovery(watch.failure_of(st, "failed", "few")), "reparse")
    проверка("planned + push → переразбор", watch.recovery(watch.failure_of(st, "failed", "push")), "reparse")
    проверка("early + parse → переразбор", watch.recovery(watch.failure_of({"what": "full-6", "early": True, "slot": "x"}, "failed", "parse")), "reparse")
    проверка("date + parse → ТРЕВОГА (переразбор только полного)", watch.recovery(watch.failure_of({"what": "date-2026-10-09"}, "failed", "parse")), "alarm")
    проверка("переразбор сорвался → ТРЕВОГА", watch.recovery(watch.failure_of({"what": "reparse-123"}, "failed", "parse")), "alarm")
    проверка("переразбор остановил владелец → close", watch.recovery(watch.failure_of({"what": "reparse-123"}, "stopped")), "close")
    проверка("без причины — как было", watch.failure_of(st, "failed"), "planned-failed")
    проверка("слова причины", watch.reason_words("fetch-ban"), "сайты закрыли доступ (защита, 403/429)")

    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
r"""Книга 101: пока сервер забирает результат обхода, строка статуса над
витриной не краснеет «итог так и не доехал».

11.11.2026 владелец открыл витрину в 21:59 — через минуту после стука
«закончил» (21:58) и за минуту до конца заливки (22:00). Отметка «идёт» уже
была снята, метка сбора ещё прежняя, с заказа 20:30 прошло больше получаса —
строка покраснела, хотя обход прошёл и вливался. Правила (`app/crawl_hook.py`):

  З1. стук «закончил — удачно» и забор запущен → отметка забора; провал,
      проба, забор не запустился — отметки нет;
  З2. отметка свежая → «закончен в ЧЧ:ММ, сервер забирает результат» у
      полного обхода, скана даты и «Обойти сайт»;
  З3. отметка старше 20 минут, итога нет → краснеет как раньше;
  З4. забор раньше заказа — к заказу не относится;
  З5. забор другого вида (сайт, дозабор) строку полного обхода не прикрывает.

В сеть не ходит, забор подменён заглушкой. База — пустая, во временной папке.

Запуск: venv\Scripts\python.exe scripts\test_status_zabor.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="status-zabor-"))
(TMP / "visits").mkdir()
(TMP / "secret").write_text("слово\n", encoding="utf-8")
os.environ.update(STREAMS_DB=str(TMP / "test.db"), STREAMS_ADMIN_PASSWORD="adm-test-1",
                  STREAMS_FRIEND_PASSWORD="fr-test-1", SECRET_KEY="k" * 32,
                  STREAMS_VISITS_DIR=str(TMP / "visits"),
                  STREAMS_HOOK_SECRET_FILE=str(TMP / "secret"))
os.environ.pop("STREAMS_LOCAL", None)

from app import crawl_hook, db, visits, web  # noqa: E402

PULL = {"said": crawl_hook.PULL_STARTED}          # что ответит заглушка забора
crawl_hook.start_pull = lambda: PULL["said"]
visits.write = lambda *a, **k: None               # журнал в тесте не пишем

db.init_db()
app = web.create_app()
status_lines = app.jinja_env.globals["crawl_status_lines"]
RED = "итог так и не доехал"
TAKING = "сервер забирает результат"

total = green = 0


def check(name: str, ok: bool, got=None) -> None:
    global total, green
    total += 1
    green += bool(ok)
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"   ← {got!r}"))


def setting(key: str, value: str | None = None):
    conn = db.connect()
    try:
        if value is None:
            return db.get_setting(conn, key) or ""
        db.set_setting(conn, key, value)
    finally:
        conn.close()


def ago(minutes: int) -> str:
    """Время заказа «минут назад» — как его пишут кнопки: часами машины."""
    return (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")


def pull(minutes_ago: int, what: str) -> None:
    setting("crawl_pull", f"{int(time.time()) - minutes_ago * 60}|{what}")


def reset() -> None:
    for key in ("crawl_running", "crawl_request", "crawl_pull", "last_crawl", "last_import",
                "date_scan_request", "site_crawl_request", "site_crawl_result"):
        setting(key, "")


def texts() -> list[str]:
    return [line["text"] for line in status_lines()]


def classes() -> list[str]:
    return [line["cls"] for line in status_lines()]


STAMP = [int(time.time())]


def knock(event: str, what: str):
    """Стук GitHub с настоящей подписью (время каждого стука — новее прежнего)."""
    STAMP[0] += 1
    stamp = str(STAMP[0])
    sign = crawl_hook.sign(crawl_hook._secret(), stamp, event, what)
    return app.test_client().post("/hook/crawl", headers={
        "X-Event": event, "X-What": what, "X-Stamp": stamp, "X-Sign": sign})


print("прежнее: забора нет — строка краснеет")
reset()
setting("crawl_request", f"обход 6 сут.|{ago(88)}")
check("заказ 88 минут назад, итога нет, забора нет → красное",
      classes() == ["error"] and RED in texts()[0], texts())

print("З1: отметку забора ставит только удачный стук с запущенным забором")
reset()
setting("crawl_running", f"идёт|{int(time.time()) - 88 * 60}|20:30|full-6")
r = knock("done-ok", "full-6")
check("стук «закончил — удачно»: принят, отметка «идёт» снята",
      r.status_code == 200 and setting("crawl_running") == "", (r.status_code, setting("crawl_running")))
check("…и стоит отметка забора этого обхода", setting("crawl_pull").endswith("|full-6"), setting("crawl_pull"))
reset()
r = knock("done-fail", "full-6")
check("стук «закончил — провал»: отметки забора нет",
      r.status_code == 200 and setting("crawl_pull") == "", setting("crawl_pull"))
PULL["said"] = "забор не запустился: OSError"
r = knock("done-ok", "full-6")
check("забор не запустился: отметки забора нет",
      r.status_code == 200 and setting("crawl_pull") == "", setting("crawl_pull"))
PULL["said"] = crawl_hook.PULL_STARTED
r = knock("done-ok", "probeurl-ok")
check("проба адреса: отметки забора нет",
      r.status_code == 200 and setting("crawl_pull") == "", setting("crawl_pull"))

print("З2: пока сервер забирает — не краснеет")
reset()
setting("crawl_request", f"обход 6 сут.|{ago(88)}")
pull(1, "full-6")
check("полный обход: «закончен…, сервер забирает результат», зелёным",
      classes() == ["ok"] and TAKING in texts()[0] and RED not in texts()[0]
      and texts()[0].startswith("Обход 6 сут.: закончен в "), texts())
check("…время в строке — когда пришёл стук, по Киеву",
      datetime.fromtimestamp(int(setting("crawl_pull").split("|")[0]), crawl_hook.KYIV)
      .strftime("%H:%M") in texts()[0], texts())
reset()
setting("crawl_request", f"обход 2 сут.|{ago(40)}")
pull(2, "days-2")
check("полный обход кнопкой (`days-2`): тоже «забирает»",
      classes() == ["ok"] and TAKING in texts()[0], texts())
reset()
setting("date_scan_request", f"2026-11-12|{ago(40)}")
pull(1, "date-2026-11-12")
check("скан даты: «забирает», зелёным",
      classes() == ["ok"] and TAKING in texts()[0] and texts()[0].startswith("Скан даты 12.11"), texts())
reset()
setting("site_crawl_request", f"sportklub.hr|{ago(40)}")
pull(1, "site-sportklub.hr")
check("«Обойти сайт»: «забирает», зелёным",
      classes() == ["ok"] and TAKING in texts()[0] and "sportklub.hr" in texts()[0], texts())

print("З3: забор старше 20 минут, итога нет — краснеет как раньше")
reset()
setting("crawl_request", f"обход 6 сут.|{ago(110)}")
pull(21, "full-6")
check("полный обход: красное", classes() == ["error"] and RED in texts()[0], texts())
pull(19, "full-6")
check("…а 19 минут — ещё «забирает»", classes() == ["ok"] and TAKING in texts()[0], texts())

print("З4: забор раньше заказа к заказу не относится")
reset()
setting("crawl_request", f"обход 6 сут.|{ago(5)}")
pull(10, "full-6")
check("заказ 5 минут назад, забор прошлого обхода 10 минут назад → «ждём прогона»",
      classes() == ["ok"] and "ждём прогона" in texts()[0] and TAKING not in texts()[0], texts())

print("З5: забор другого вида чужую строку не прикрывает")
reset()
setting("crawl_request", f"обход 6 сут.|{ago(40)}")
pull(1, "site-sportklub.hr")
check("полный обход не дошёл, забирается точечный сайт → красное",
      classes() == ["error"] and RED in texts()[0], texts())
pull(1, "redo-123456")
check("…дозабор упавших адресов → красное", classes() == ["error"] and RED in texts()[0], texts())
reset()
setting("date_scan_request", f"2026-11-12|{ago(40)}")
pull(1, "date-2026-11-13")
check("скан даты 12.11 не дошёл, забирается скан 13.11 → красное",
      classes() == ["error"] and RED in texts()[0], texts())

print("итог доехал и сбор идёт — как раньше")
reset()
setting("crawl_request", f"обход 6 сут.|{ago(88)}")
pull(3, "full-6")
setting("last_crawl", (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M"))
check("метка сбора новее заказа → «✅ ВЫПОЛНЕН», хотя отметка забора ещё свежая",
      classes() == ["ok"] and "ВЫПОЛНЕН" in texts()[0] and TAKING not in texts()[0], texts())
reset()
setting("crawl_request", f"обход 6 сут.|{ago(40)}")
setting("crawl_running", f"идёт|{int(time.time()) - 39 * 60}|20:31|full-6")
check("обход идёт → одна строка «идёт», без красного",
      len(texts()) == 1 and "идёт" in texts()[0] and RED not in texts()[0], texts())
check("отметка забора с мусором — не падает, строки нет",
      crawl_hook.pulling("мусор", "full", ago(40)) == "" and crawl_hook.pulling("", "full", "") == "")

print(f"\n{green}/{total} зелёных")
raise SystemExit(0 if green == total else 1)

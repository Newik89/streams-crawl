# -*- coding: utf-8 -*-
r"""Проверки сторожа обхода (владелец 05.10.2026): заявка не верит отметке
«идёт» на слово, сорвавшийся плановый заказывается досрочно, зависший прогон
отменяется заявкой-тегом. Сценарии — по дыре 05.10 (проба провисела «идёт»,
заявка 16:15 молча не ушла) и по примерам владельца.

В сеть не ходит и ничего не заказывает: список прогонов GitHub, тег-заявка,
ожидание старта, заказ обхода и забор подменены заглушками; часы заявки и
сторожа ставятся нужные (16:15, 20:30 …). База — КОПИЯ во временной папке:

    python scripts/test_watch.py
    python scripts/test_watch.py --db ..\streams-crawl\data\channel_schedule.db

Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

ARGS = argparse.ArgumentParser()
ARGS.add_argument("--db", help="база, копию которой взять")
OPTS = ARGS.parse_args()

TMP = Path(tempfile.mkdtemp(prefix="watch-test-"))
src = Path(OPTS.db) if OPTS.db else ROOT / "data" / "channel_schedule.db"
if src.exists():
    shutil.copy(src, TMP / "test.db")
os.environ["STREAMS_DB"] = str(TMP / "test.db")

from app import crawl_hook, db, trigger, watch  # noqa: E402

SLUG = "Newik89/streams-crawl"
KYIV = watch.KYIV
DAY = "2026-11-10"            # вторник; реальных обходов в копии на эту дату нет

# ── заглушки: ни GitHub, ни тегов, ни заказов ───────────────────────────────
API = {"runs": [], "calls": 0}
TAGS: list[tuple] = []
ORDERS: list[int] = []
PUSH_OK = [True]
RESULT = ["picked"]
NOW = [datetime(2026, 11, 10, 16, 15, tzinfo=KYIV)]


def fake_runs(slug, limit=12, workflow=""):
    API["calls"] += 1
    return [dict(r) for r in API["runs"]]


watch.github_runs = fake_runs
trigger.push_request_tag = lambda kind, value: (TAGS.append((kind, value)) or (PUSH_OK[0], "тест"))
trigger._repo_slug = lambda: SLUG
watch.wait_for_start = lambda order, slug, **k: {"run_number": 0}
watch.result_state = lambda root, started: RESULT[0]

db.init_db()


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rc = load("request_crawl")
cw = load("crawl_watch")
rc._now = lambda: NOW[0]


def fake_order(days: int) -> str:
    """Как `request_crawl.py days N --force --unlock`: снять замок, записать
    заказ и отметку «заявка»."""
    ORDERS.append(days)
    conn = db.connect()
    try:
        crawl_hook.clear(conn)
        db.set_setting(conn, "crawl_request", f"обход {days} сут.|{watch.stamp(NOW[0])}")
        crawl_hook.mark(conn, "заявка", f"days-{days}")
    finally:
        conn.close()
    return "тест: заказ ушёл"


cw.order_crawl = fake_order
cw.pull = lambda: (0, "тест")

passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def K(hhmm: str, day: str = DAY) -> datetime:
    return datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=KYIV)


def Z(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_ids = [37400000000]


def mkrun(created: datetime, status="completed", conclusion="success",
          title="Обход full-6", ended: datetime | None = None,
          event="workflow_dispatch", path=".github/workflows/crawl.yml",
          repo=SLUG, rid=None):
    _ids[0] += 1
    rid = rid or _ids[0]
    return {"id": rid, "run_number": rid % 1000 if isinstance(rid, int) else 0, "event": event, "status": status,
            "conclusion": conclusion if status == "completed" else None,
            "display_title": title, "name": watch.CRAWL_NAME, "path": path,
            "repository": {"full_name": repo},
            "created_at": Z(created), "run_started_at": Z(created),
            "updated_at": Z(ended or created)}


def setting(key, value=None):
    conn = db.connect()
    try:
        if value is None:
            return db.get_setting(conn, key)
        db.set_setting(conn, key, value)
    finally:
        conn.close()


def jset(key, value: dict):
    setting(key, json.dumps(value, ensure_ascii=False))


def jget(key) -> dict:
    try:
        return json.loads(setting(key) or "{}")
    except ValueError:
        return {}


def mark(state, minutes_ago, what):
    setting("crawl_running", f"{state}|{int(time.time()) - minutes_ago * 60}|00:00|{what}")


def last_id() -> int:
    conn = db.connect()
    try:
        return conn.execute("SELECT COALESCE(MAX(id), 0) FROM runs").fetchone()[0]
    finally:
        conn.close()


def notes_after(edge: int) -> list[str]:
    conn = db.connect()
    try:
        rows = conn.execute("SELECT log FROM runs WHERE id > ? ORDER BY id", (edge,)).fetchall()
    finally:
        conn.close()
    return [(json.loads(r["log"] or "{}") or {}).get("режим", "") for r in rows]


def reset(now: datetime, runs=()):
    TAGS.clear()
    ORDERS.clear()
    API["calls"] = 0
    API["runs"] = list(runs)
    PUSH_OK[0] = True
    RESULT[0] = "picked"
    NOW[0] = now
    for key in ("crawl_running", "crawl_request", "crawl_watch", "crawl_missed",
                "crawl_early", "crawl_cancel"):
        setting(key, "")


def planned(days: int, *flags) -> list[tuple]:
    """Плановая заявка из cron в момент NOW: какие теги ушли."""
    TAGS.clear()
    saved = sys.argv
    sys.argv = ["request_crawl.py", "days", str(days), *flags]
    try:
        rc.main()
    finally:
        sys.argv = saved
    return list(TAGS)


def tick(now: datetime, check_only=False) -> int:
    """Одна проверка сторожа в `now`: сколько запросов к API она сделала."""
    NOW[0] = now
    before = API["calls"]
    conn = db.connect()
    try:
        cw.tick(conn, now, check_only)
    finally:
        conn.close()
    return API["calls"] - before


def order_of(stamp_: str, days: int):
    setting("crawl_request", f"обход {days} сут.|{stamp_}")


# ── 0. расписание и разбор ──────────────────────────────────────────────────
print("0. расписание, вид прогона, потолки")
check("16:20 заявка на 2 дня — это плановый 16:15", watch.slot_for(K("16:20"), 2) == K("16:15"))
check("16:20 заявка на 6 дней — не плановый", watch.slot_for(K("16:20"), 6) is None)
check("06:14 на 6 дней — плановый 06:15", watch.slot_for(K("06:14"), 6) == K("06:15"))
check("после 16:30 следующий плановый — 20:30 на 6", watch.next_slot(K("16:30")) == (K("20:30"), 6))
check("после 06:30 следующий — 16:15 на 2", watch.next_slot(K("06:30")) == (K("16:15"), 2))
check("после 20:45 следующий — 06:15 завтра на 6",
      watch.next_slot(K("20:45")) == (K("06:15", "2026-11-11"), 6))
cron = watch.cron_lines("/srv/x", "py")
check("cron-строки из той же таблицы",
      cron[:3] == ["15 6 * * * cd /srv/x && py scripts/request_crawl.py days 6 >> /var/log/streams-request.log 2>&1",
                   "15 16 * * * cd /srv/x && py scripts/request_crawl.py days 2 >> /var/log/streams-request.log 2>&1",
                   "30 20 * * * cd /srv/x && py scripts/request_crawl.py days 6 >> /var/log/streams-request.log 2>&1"]
      and "crawl_watch.py" in cron[3], cron)
check("вид прогона по названию",
      [watch.run_kind({"display_title": t}) for t in
       ("Обход full-6", "Обход proba-2", "Обход site-nova.bg", "Обход date-2026-11-11",
        "Обход телесайтов")]
      == [("full", 6), ("probe", 0), ("site", 0), ("date", 0), ("unknown", 0)])
check("плановый cron GitHub — свой вид, полным не считается",
      watch.run_kind({"event": "schedule"}) == ("schedule", 0))
check("потолки: проба 20, сайт 45, 2 дня 75, 6 дней 140, не узнан 140",
      [watch.ceiling(*k) for k in (("probe", 0), ("site", 0), ("full", 2), ("full", 6), ("unknown", 0))]
      == [20, 45, 75, 140, 140])
a = mkrun(K("13:15"), ended=K("13:52"), title="Обход full-2")
b = mkrun(K("13:17"), status="in_progress", title="Обход proba-2")
check("старт прогона, ждавшего в очереди, — конец предыдущего (#118 за #117)",
      watch.effective_start(b, [a, b]) == K("13:52"))
c = mkrun(K("13:20"), status="pending", title="Обход full-6")
check("ждёт за идущим — не завис (старта нет)", watch.effective_start(c, [a, b, c]) is None)

# ── 1. сегодняшний случай ───────────────────────────────────────────────────
print("1. 05.10: ложная отметка пробы, плановый 16:15")
probe = mkrun(K("13:44"), ended=K("13:47"), title="Обход proba-2")
reset(K("16:15"), [probe])
mark("идёт", 15, "proba-2")
edge = last_id()
sent = planned(2)
notes = notes_after(edge)
check("заявка на 2 дня ушла", sent == [("days", "2")], sent)
check("отметка «идёт proba-2» снята, стоит своя «заявка days-2»",
      setting("crawl_running").startswith("заявка|") and setting("crawl_running").endswith("|days-2"),
      setting("crawl_running"))
check("в «Прогонах» строка «сторож: отметка … снята — на GitHub прогонов нет»",
      any(n.startswith("сторож: отметка") and "снята" in n and "прогонов нет" in n for n in notes), notes)
check("заказ записан для сторожа", setting("crawl_request") == f"обход 2 сут.|{DAY} 16:15")
check("к API — один запрос", API["calls"] == 1, API["calls"])
reset(K("16:15"), [probe])
mark("идёт", 160, "full-6")      # то же с отметкой полного обхода (3 ч не прошло)
check("ложная отметка «идёт full-6» без прогонов → тоже снята, заявка ушла",
      planned(2) == [("days", "2")] and setting("crawl_running").endswith("|days-2"))

# ── 2. все ветки А ──────────────────────────────────────────────────────────
print("2. заявка сверяет отметку с GitHub")
full6 = mkrun(K("15:40"), status="in_progress", title="Обход full-6")
reset(K("16:15"), [full6])
mark("идёт", 35, "full-6")
edge = last_id()
check("идёт полный на 6 → плановый на 2 пропущен", planned(2) == [])
check("…строка «не нужен — на GitHub уже идёт обход … на 6 сут.»",
      any("не нужен" in n and "6 сут." in n for n in notes_after(edge)), notes_after(edge))
check("…отметку идущего не трогает", setting("crawl_running").endswith("|full-6"))
check("…и сорвавшимся его не считает", jget("crawl_missed") == {})
pr = mkrun(K("16:05"), status="in_progress", title="Обход proba-2")
wait6 = mkrun(K("16:08"), status="pending", title="Обход full-6")
reset(K("16:15"), [pr, wait6])
mark("идёт", 10, "proba-2")
edge = last_id()
check("идёт проба, за ней ждёт полный на 6 → плановый на 2 пропущен (не вытесняем ждущего)",
      planned(2) == [] and any("ждёт очереди" in n for n in notes_after(edge)), notes_after(edge))
reset(K("16:15"), [mkrun(K("16:00"), status="in_progress", title="Обход date-2026-11-12")])
mark("идёт", 15, "date-2026-11-12")
edge = last_id()
check("идёт скан даты → плановый заказан, встанет в очередь", planned(2) == [("days", "2")])
check("…отметку скана не перетирает", setting("crawl_running").endswith("|date-2026-11-12"))
check("…строка «встанет в очередь»", any("в очередь" in n for n in notes_after(edge)))
reset(K("16:15"), [mkrun(K("16:00"), status="in_progress", title="Обход site-nova.bg")])
mark("идёт", 15, "site-nova.bg")
check("идёт обход одного сайта → плановый заказан", planned(2) == [("days", "2")])
reset(K("20:30"), [mkrun(K("20:00"), status="in_progress", title="Обход full-2")])
mark("идёт", 30, "full-2")
check("идёт полный на 2 → плановый на 6 заказан в очередь", planned(6) == [("days", "6")])
reset(K("16:15"), [mkrun(K("15:40"), status="in_progress", title="Обход full-2")])
mark("идёт", 35, "full-2")
check("идёт полный на 2 → плановый на 2 пропущен (не меньшей глубины)", planned(2) == [])
reset(K("16:15"), [probe])
mark("заявка", 1, "days-6")
check("заявку на 6 подали минуту назад, GitHub её ещё не показал → плановый на 2 пропущен",
      planned(2) == [] and setting("crawl_running").endswith("|days-6"))
reset(K("16:15"), [mkrun(K("15:40"), status="in_progress", title="Обход телесайтов")])
mark("идёт", 35, "full-6")
check("прогон без названия вида (до правки) → вид берём из отметки: full-6, пропуск",
      planned(2) == [])
reset(K("16:15"), [mkrun(K("16:14"), status="in_progress", title="Обход по расписанию",
                         event="schedule")])
mark("идёт", 35, "full-6")
check("идёт запуск по расписанию GitHub (сразу выходит) → плановый на 2 заказан в очередь",
      planned(2) == [("days", "2")])
reset(K("16:15"), [])            # GitHub не ответил
mark("идёт", 35, "full-6")
edge = last_id()
check("GitHub молчит, отметка «идёт full-6» → заявка отложена", planned(2) == [])
missed = jget("crawl_missed")
check("…сторожу оставлено «плановый 16:15 на 2 дня не ушёл»",
      missed.get("slot") == f"{DAY} 16:15" and missed.get("days") == 2
      and missed.get("state") == "missed", missed)
check("…строка «отложен … сторож сверится»",
      any("отложен" in n and "Сторож" in n for n in notes_after(edge)), notes_after(edge))
reset(K("16:15"), [])
mark("идёт", 5, "proba-2")
check("GitHub молчит, отметка пробы → заявка уходит в очередь (как было)",
      planned(2) == [("days", "2")] and setting("crawl_running").endswith("|proba-2"))
reset(K("16:15"), [probe])
check("отметки нет → к API не ходит, заявка уходит", planned(2) == [("days", "2")]
      and API["calls"] == 0, API["calls"])
reset(K("16:15"), [probe])
mark("идёт", 15, "proba-2")
check("--check ничего не меняет", planned(2, "--check") == []
      and setting("crawl_running").endswith("|proba-2"))
reset(K("16:15"), [probe])
PUSH_OK[0] = False
edge = last_id()
check("тег не ушёл → плановый запомнен для сторожа",
      planned(2) == [("days", "2")] and jget("crawl_missed").get("slot") == f"{DAY} 16:15"
      and any("не ушла" in n for n in notes_after(edge)))
reset(K("13:00"), [probe])
PUSH_OK[0] = False
planned(2)
check("ручной заказ не по расписанию не ушёл → сторож его не перезаказывает",
      jget("crawl_missed") == {})

# ── 3. примеры Б: досрочный ─────────────────────────────────────────────────
print("3. сорвался 16:15 (2 дня) → досрочный на 6 вместо 20:30")
reset(K("16:15"), [])
mark("идёт", 35, "full-6")
planned(2)                                   # GitHub молчит — отложено
API["runs"] = [probe]                        # к 16:30 GitHub ответил, прогонов нет
edge = last_id()
calls = tick(K("16:30"))
early = jget("crawl_early")
check("в 16:30 сторож заказал обход на 6 дней", ORDERS == [6], ORDERS)
check("память: за плановый 16:15, вместо 20:30, глубина 6, заказан в 16:30",
      early.get("for") == f"{DAY} 16:15" and early.get("replaces") == f"{DAY} 20:30"
      and early.get("days") == 6 and early.get("ordered_at") == f"{DAY} 16:30"
      and early.get("state") == "ordered", early)
check("ложная отметка снята, стоит «заявка days-6»", setting("crawl_running").endswith("|days-6"))
check("строка «не состоялся — заказываю сейчас обход на 6 сут. вместо … 20:30»",
      any("не состоялся" in n and "на 6 сут." in n and "20:30" in n for n in notes_after(edge)),
      notes_after(edge))
check("один запрос к API за проверку", calls == 1, calls)
run6 = mkrun(K("16:31"), status="in_progress", title="Обход full-6")
API["runs"] = [probe, run6]
calls = tick(K("16:45"))
check("вторая проверка подряд — второго заказа нет", ORDERS == [6] and calls == 1, (ORDERS, calls))
tick(K("17:00"))
check("и третья — тоже", ORDERS == [6])
API["runs"] = [probe, mkrun(K("16:31"), ended=K("18:00"), title="Обход full-6", rid=run6["id"])]
tick(K("18:15"))
check("досрочный дошёл и забран → память «done»", jget("crawl_early").get("state") == "done")
NOW[0] = K("20:30")
setting("crawl_running", "")          # стук «закончил» снял отметку
edge = last_id()
check("20:30: плановый на 6 пропущен", planned(6) == [])
check("…строка «выполнен досрочно в 16:31»",
      any("выполнен досрочно в 16:31" in n for n in notes_after(edge)), notes_after(edge))

print("   досрочный не дошёл → плановый идёт как обычно")
reset(K("20:30"), [probe, mkrun(K("16:31"), ended=K("17:10"), conclusion="failure",
                                title="Обход full-6")])
jset("crawl_early", {"for": f"{DAY} 16:15", "for_days": 2, "days": 6,
                     "replaces": f"{DAY} 20:30", "replaces_days": 6,
                     "ordered_at": f"{DAY} 16:30", "state": "ordered"})
edge = last_id()
check("досрочный упал → в 20:30 плановый на 6 ушёл", planned(6) == [("days", "6")])
check("…строка «досрочный … кончился «failure» — плановый идёт как обычно»",
      any("failure" in n and "как обычно" in n for n in notes_after(edge)), notes_after(edge))
reset(K("20:30"), [probe, mkrun(K("16:31"), status="in_progress", title="Обход full-6")])
jset("crawl_early", {"for": f"{DAY} 16:15", "days": 6, "replaces": f"{DAY} 20:30",
                     "replaces_days": 6, "ordered_at": f"{DAY} 16:30", "state": "ordered"})
check("досрочный ещё идёт → 20:30 пропущен", planned(6) == [])
reset(K("20:30"), [probe])
jset("crawl_early", {"for": f"{DAY} 16:15", "days": 6, "replaces": f"{DAY} 20:30",
                     "replaces_days": 6, "ordered_at": f"{DAY} 16:30", "state": "ordered"})
check("досрочный так и не стартовал → 20:30 идёт", planned(6) == [("days", "6")])

print("   досрочный сорвался → ТРЕВОГА, без нового заказа")
reset(K("16:15"), [])
jset("crawl_missed", {"slot": f"{DAY} 16:15", "days": 2, "at": f"{DAY} 16:15",
                      "why": "тест", "state": "missed"})
API["runs"] = [probe]
tick(K("16:30"))
API["runs"] = [probe, mkrun(K("16:31"), ended=K("16:50"), conclusion="failure",
                            title="Обход full-6")]
edge = last_id()
tick(K("17:00"))
check("досрочный упал → строка «ТРЕВОГА — досрочный обход тоже не прошёл»",
      any(n.startswith("сторож: ТРЕВОГА — досрочный") for n in notes_after(edge)), notes_after(edge))
check("…нового заказа нет", ORDERS == [6], ORDERS)
check("…память «failed»", jget("crawl_early").get("state") == "failed")
edge = last_id()
tick(K("17:15")); tick(K("17:30"))
check("…и на следующих проверках тихо (тревога один раз, заказов нет)",
      ORDERS == [6] and not any("ТРЕВОГА" in n for n in notes_after(edge)), notes_after(edge))
NOW[0] = K("20:30")
setting("crawl_running", "")
check("…а в 20:30 плановый на 6 идёт как обычно", planned(6) == [("days", "6")])

print("   досрочную заявку GitHub не принял → ТРЕВОГА, без круга")
reset(K("16:30"), [probe])
jset("crawl_missed", {"slot": f"{DAY} 16:15", "days": 2, "at": f"{DAY} 16:15",
                      "why": "тест", "state": "missed"})
cw.order_crawl = lambda days: (ORDERS.append(days) or "заявка не прошла")
edge = last_id()
tick(K("16:30")); tick(K("16:45"))
cw.order_crawl = fake_order
check("одна попытка, строка ТРЕВОГА", ORDERS == [6]
      and any("ТРЕВОГА — досрочный обход заказать не вышло" in n for n in notes_after(edge)),
      (ORDERS, notes_after(edge)))

print("3б. сорвался 06:15 (6 дней) → досрочный на 6 вместо 16:15")
reset(K("06:15"), [])
mark("идёт", 35, "full-6")
planned(6)
API["runs"] = [probe]
tick(K("06:30"))
early = jget("crawl_early")
check("в 06:30 заказ на 6 дней вместо 16:15 (2 дня)",
      ORDERS == [6] and early.get("replaces") == f"{DAY} 16:15" and early.get("days") == 6, early)
API["runs"] = [probe, mkrun(K("06:31"), ended=K("08:00"), title="Обход full-6")]
tick(K("08:15"))
NOW[0] = K("16:15")
setting("crawl_running", "")
edge = last_id()
check("в 16:15 плановый на 2 НЕ пропущен — досрочный начался раньше 11:15",
      planned(2) == [("days", "2")])
check("…строка «раньше, чем за 5 ч … как обычно»",
      any("раньше, чем за 5 ч" in n for n in notes_after(edge)), notes_after(edge))
reset(K("16:15"), [probe, mkrun(K("11:31"), ended=K("13:00"), title="Обход full-6")])
jset("crawl_early", {"for": f"{DAY} 06:15", "days": 6, "replaces": f"{DAY} 16:15",
                     "replaces_days": 2, "ordered_at": f"{DAY} 11:30", "state": "done"})
check("досрочный в 11:30 (06:15 сорвался поздно) дошёл → 16:15 пропущен «досрочно»",
      planned(2) == [])
reset(K("16:15"), [probe, mkrun(K("15:46"), status="in_progress", title="Обход full-6")])
order_of(f"{DAY} 15:45", 6)
jset("crawl_early", {"for": f"{DAY} 06:15", "days": 6, "replaces": f"{DAY} 16:15",
                     "replaces_days": 2, "ordered_at": f"{DAY} 15:45", "state": "ordered"})
check("досрочный в 15:45 ещё идёт → 16:15 пропущен", planned(2) == [])
reset(K("16:15"), [probe])
order_of(f"{DAY} 15:45", 6)
check("свежий заказ на 6 дней 30 мин назад → 16:15 отменён правилом «1 час» (как было)",
      planned(2) == [])

print("3в. сорвался 20:30 → досрочный на 6 вместо утреннего, утренний идёт")
reset(K("20:30"), [])
mark("идёт", 35, "full-6")
planned(6)
API["runs"] = [probe]
tick(K("20:45"))
early = jget("crawl_early")
check("в 20:45 заказ на 6 дней вместо 06:15 завтра",
      ORDERS == [6] and early.get("replaces") == "2026-11-11 06:15", early)
API["runs"] = [probe, mkrun(K("20:46"), ended=K("22:10"), title="Обход full-6")]
tick(K("22:30"))
NOW[0] = K("06:15", "2026-11-11")
setting("crawl_running", "")
check("утром 06:15 плановый на 6 идёт как обычно", planned(6) == [("days", "6")])

print("3г. плановый упал и после повтора → досрочный, не тишина")
reset(K("17:30"), [probe, mkrun(K("16:16"), ended=K("16:30"), conclusion="failure", title="Обход full-2"),
                   mkrun(K("16:46"), ended=K("17:05"), conclusion="failure", title="Обход full-2")])
order_of(f"{DAY} 16:45", 2)
jset("crawl_watch", {"order": f"{DAY} 16:45", "reordered": True, "slot": f"{DAY} 16:15"})
edge = last_id()
tick(K("17:30"))
early = jget("crawl_early")
check("повтор 16:45 упал → сразу заказ на 6 вместо 20:30",
      ORDERS == [6] and early.get("for") == f"{DAY} 16:15"
      and early.get("replaces") == f"{DAY} 20:30", (ORDERS, early))
check("…строки «не удался» и «заказываю сейчас»",
      any("не удался" in n for n in notes_after(edge))
      and any("заказываю сейчас" in n for n in notes_after(edge)), notes_after(edge))
tick(K("17:45"))
check("…следующая проверка второго заказа не делает", ORDERS == [6])
reset(K("14:00"), [probe, mkrun(K("13:01"), ended=K("13:10"), conclusion="failure", title="Обход full-6")])
order_of(f"{DAY} 13:00", 6)
jset("crawl_watch", {"order": f"{DAY} 13:00", "reordered": True})
edge = last_id()
tick(K("14:00"))
check("ручной заказ 13:00 упал после повтора → ТРЕВОГА, как было, без досрочного",
      ORDERS == [] and any(n.startswith("сторож: ТРЕВОГА") for n in notes_after(edge)),
      (ORDERS, notes_after(edge)))

print("3д. когда досрочно не нужно")
reset(K("16:30"), [probe, mkrun(K("16:20"), status="in_progress", title="Обход full-6")])
jset("crawl_missed", {"slot": f"{DAY} 16:15", "days": 2, "at": f"{DAY} 16:15",
                      "why": "тест", "state": "missed"})
tick(K("16:30"))
check("на GitHub уже идёт полный на 6 → не заказываем",
      ORDERS == [] and jget("crawl_missed").get("state") == "covered")
reset(K("16:30"), [probe])
jset("crawl_missed", {"slot": f"{DAY} 16:15", "days": 2, "at": f"{DAY} 16:15",
                      "why": "тест", "state": "missed"})
order_of(f"{DAY} 16:20", 6)
API["runs"] = [probe, mkrun(K("16:21"), status="in_progress", title="Обход full-6")]
tick(K("16:30"))
check("после сорвавшегося уже заказан обход на 6 → не заказываем",
      ORDERS == [] and jget("crawl_missed").get("state") == "drop")
reset(K("15:00"), [probe])
jset("crawl_missed", {"slot": f"{DAY} 06:15", "days": 6, "at": f"{DAY} 06:15",
                      "why": "тест", "state": "missed"})
edge = last_id()
tick(K("15:00"))
check("сорвался 9 ч назад (GitHub лежал) → только ТРЕВОГА",
      ORDERS == [] and jget("crawl_missed").get("state") == "late"
      and any("ТРЕВОГА" in n for n in notes_after(edge)))
reset(K("16:30"), [])
jset("crawl_missed", {"slot": f"{DAY} 16:15", "days": 2, "at": f"{DAY} 16:15",
                      "why": "тест", "state": "missed"})
tick(K("16:30"))
check("GitHub не ответил сторожу → ждём, ничего не заказываем",
      ORDERS == [] and jget("crawl_missed").get("state") == "missed")

# ── 4. В: зависшие прогоны ──────────────────────────────────────────────────
print("4. зависший прогон: отмена и перезаказ")
yday = mkrun(K("13:44", "2026-11-09"), ended=K("13:47", "2026-11-09"), title="Обход proba-2")
hung = mkrun(K("06:16"), status="in_progress", title="Обход full-6")
reset(K("08:40"), [yday, hung])
order_of(f"{DAY} 06:15", 6)
edge = last_id()
calls = tick(K("08:40"))
check("обход на 6 дней идёт 144 мин (> 140) → заявка отмены с номером прогона",
      TAGS == [("cancel", str(hung["id"]))], TAGS)
check("…строка «завис … отменяю его, на следующей проверке закажу его заново»",
      any("завис" in n and "закажу его заново" in n for n in notes_after(edge)), notes_after(edge))
check("…память отмены", str(hung["id"]) in jget("crawl_cancel"))
check("…один запрос к API", calls == 1, calls)
tick(K("08:45"))
check("следующая проверка, прогон ещё идёт → вторую отмену не шлём, тревоги нет (5 мин)",
      TAGS == [("cancel", str(hung["id"]))])
API["runs"] = [yday, mkrun(K("06:16"), ended=K("08:42"), conclusion="cancelled",
                            title="Обход full-6", rid=hung["id"])]
edge = last_id()
tick(K("08:55"))
check("GitHub подтвердил отмену → строка «остановлен», память отмены чиста",
      any("остановлен" in n for n in notes_after(edge)) and jget("crawl_cancel") == {},
      notes_after(edge))
check("…и обход перезаказан (повтор, как у упавшего)", ORDERS == [6], ORDERS)

reset(K("08:40"), [yday, hung])
order_of(f"{DAY} 06:15", 6)
tick(K("08:40"))
edge = last_id()
tick(K("08:55"))
check("отмена не подтвердилась за 15 мин → ТРЕВОГА",
      any("ТРЕВОГА" in n and "не остановился" in n for n in notes_after(edge)), notes_after(edge))
edge = last_id()
tick(K("09:10"))
check("…один раз, и отмену не повторяем",
      not any("ТРЕВОГА" in n for n in notes_after(edge)) and len(TAGS) == 1, (TAGS, notes_after(edge)))

print("   что не отменяется")


def cancels_for(runs, now) -> list[str]:
    return [rid for act, rid, _ in watch.cancel_decisions(runs, now, {}, SLUG) if act == "cancel"]


old = mkrun(K("06:16"), ended=K("07:40"), title="Обход full-6")
check("завершённый прогон — не трогаем", cancels_for([old], K("12:00")) == [])
alien = mkrun(K("06:16"), status="in_progress", title="Обход full-6", repo="someone/fork")
check("прогон чужого репозитория — не трогаем", cancels_for([alien], K("12:00")) == [])
other = mkrun(K("06:16"), status="in_progress", title="AI-слой",
              path=".github/workflows/ai_check.yml")
check("прогон другого workflow — не трогаем", cancels_for([other], K("12:00")) == [])
badid = mkrun(K("06:16"), status="in_progress", title="Обход full-6", rid="123;echo")
check("номер прогона не из цифр — не трогаем", cancels_for([badid], K("12:00")) == [])
p25 = mkrun(K("11:35"), status="in_progress", title="Обход proba-2")
p15 = mkrun(K("11:45"), status="in_progress", title="Обход proba-2")
check("проба 25 мин — отменить, 15 мин — нет",
      cancels_for([p25], K("12:00")) == [str(p25["id"])] and cancels_for([p15], K("12:00")) == [])
prev = mkrun(K("10:00"), ended=K("11:30"), title="Обход full-6")
d2 = mkrun(K("10:30"), status="in_progress", title="Обход full-2")
check("обход на 2 дня «идёт» 90 мин, но 60 из них ждал очереди → не завис",
      cancels_for([prev, d2], K("12:00")) == [])
q25 = mkrun(K("11:35"), status="queued", title="Обход full-2")
q10 = mkrun(K("11:50"), status="queued", title="Обход full-2")
check("в очереди 25 мин, впереди никого → отменить; 10 мин — нет",
      cancels_for([q25], K("12:00")) == [str(q25["id"])] and cancels_for([q10], K("12:00")) == [])
run2 = mkrun(K("10:00"), status="in_progress", title="Обход full-2")
wait2 = mkrun(K("10:10"), status="pending", title="Обход full-6")
check("ждущий за зависшим не отменяется — только сам зависший",
      cancels_for([run2, wait2], K("12:00")) == [str(run2["id"])])

print("   сорвался плановый, а на GitHub висит зависший")
hung6 = mkrun(K("13:50"), status="in_progress", title="Обход full-6")
reset(K("16:30"), [hung6])
jset("crawl_missed", {"slot": f"{DAY} 16:15", "days": 2, "at": f"{DAY} 16:15",
                      "why": "тест", "state": "missed"})
calls = tick(K("16:30"))
check("за одну проверку: отмена зависшего И досрочный заказ (зависший полный — не в счёт)",
      TAGS == [("cancel", str(hung6["id"]))] and ORDERS == [6], (TAGS, ORDERS))
check("…один запрос к API", calls == 1, calls)

# ── 5. прежнее поведение сторожа ────────────────────────────────────────────
print("5. прежнее: не стартовал → повтор, готов → забор, забран → done")
reset(K("06:25"), [yday])
order_of(f"{DAY} 06:15", 6)
tick(K("06:25"))
check("заказ 06:15 не стартовал за 10 мин → повтор той же глубины", ORDERS == [6])
check("…память: повтор был, плановый слот помнит",
      jget("crawl_watch").get("reordered") is True
      and jget("crawl_watch").get("slot") == f"{DAY} 06:15", jget("crawl_watch"))
reset(K("08:00"), [yday, mkrun(K("06:16"), ended=K("07:40"), title="Обход full-6")])
order_of(f"{DAY} 06:15", 6)
RESULT[0] = "pending"
pulled = []
cw.pull = lambda: (pulled.append(1) or (0, "тест"))
tick(K("08:00"))
check("готов, стука нет → забирает сам", pulled == [1] and jget("crawl_watch").get("done") is True)
cw.pull = lambda: (0, "тест")
reset(K("08:00"), [yday, mkrun(K("06:16"), ended=K("07:40"), title="Обход full-6")])
order_of(f"{DAY} 06:15", 6)
edge = last_id()
tick(K("08:00"))
check("готов и забран по стуку → done, без заказов",
      ORDERS == [] and any("забран по стуку" in n for n in notes_after(edge)))
reset(K("08:40"), [yday, hung])
order_of(f"{DAY} 06:15", 6)
edge = last_id()
tick(K("08:40"), check_only=True)
check("--check: ни тегов, ни заказов, ни строк", TAGS == [] and ORDERS == []
      and notes_after(edge) == [])

# ── 6. workflow: защита и вид прогона ───────────────────────────────────────
print("6. queue.yml и crawl.yml")
queue = (ROOT / ".github" / "workflows" / "queue.yml").read_text(encoding="utf-8")
crawl = (ROOT / ".github" / "workflows" / "crawl.yml").read_text(encoding="utf-8")
exprs = set(re.findall(r"\$\{\{\s*([^}]*?)\s*\}\}", queue))
check("в queue.yml в команды подставляются только ключ и имя репозитория",
      exprs <= {"secrets.GITHUB_TOKEN", "github.repository"}, exprs)
check("заявка cancel: номер — только цифры", '[[ "$RUN_ID" =~ ^[0-9]{1,20}$ ]]' in queue)
check("заявка cancel: отменяет только прогон crawl.yml",
      '!= ".github/workflows/crawl.yml"' in queue)
check("в queue.yml по-прежнему 3 шага-имени", len(re.findall(r"name: ", queue)) == 3)
check("crawl.yml называет прогон видом сбора", "run-name:" in crawl and "Обход proba-{0}" in crawl)
tag_value = "123;echo${IFS}INJECTED_$((1+1))"
check("«ядовитый» номер не проходит проверку формата",
      re.fullmatch(r"[0-9]{1,20}", tag_value) is None)

print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, красных: {len(failed)}")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)

# -*- coding: utf-8 -*-
r"""Проверки сторожа обхода (владелец 05.10 и 06.10.2026). Разделы идут по
правилам из шапки `app/watch.py`: З1–З7 — заявка, С1–С6 — сторож. Имя каждой
проверки начинается с номера правила, которое она держит: `[С4г] плановый
упал → …`. В конце файл сам сверяет, что на каждое правило шапки есть хотя
бы одна проверка.

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
import subprocess
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
NEXT = "2026-11-11"

# ── заглушки: ни GitHub, ни тегов, ни заказов ───────────────────────────────
API = {"runs": [], "queue": [], "calls": 0}   # пустой runs — «GitHub не ответил»
TAGS: list[tuple] = []
ORDERS: list[int] = []
PUSH_OK = [True]
RESULT = ["picked"]
NOW = [datetime(2026, 11, 10, 16, 15, tzinfo=KYIV)]


def fake_runs(slug, limit=0, workflow=""):
    """Список прогонов: `crawl.yml` — API["runs"], пересылки `queue.yml` —
    API["queue"]. GitHub молчит (runs пуст) — молчит про оба."""
    API["calls"] += 1
    if not API["runs"]:
        return watch.Runs.silent()
    source = API["queue"] if workflow == watch.QUEUE_WORKFLOW else API["runs"]
    return watch.Runs(dict(r) for r in source)


def fake_wait(order, slug, kinds, **k):
    """Ожидание старта: прогон «появился» сразу, GitHub ответил."""
    return {"run_number": 0}, True


REAL_WAIT = watch.wait_for_start          # настоящее ожидание — для правила З7
watch.github_runs = fake_runs
watch.wait_for_start = fake_wait
REAL_RESULT = watch.result_state              # настоящая сверка — для правила С4в
RESULT_ASKED: list[tuple] = []                # с чем сторож спрашивал судьбу результата
watch.result_state = lambda root, start, end, what, imported, cache=None: (
    RESULT_ASKED.append((what, imported[-1] if imported else "")) or RESULT[0])
trigger.push_request_tag = lambda kind, value: (TAGS.append((kind, value)) or (PUSH_OK[0], "тест"))
trigger._repo_slug = lambda: SLUG

db.init_db()


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rc = load("request_crawl")
cw = load("crawl_watch")
rc._now = lambda: NOW[0]
cw._now = lambda: NOW[0]


def fake_order(kind: str, value: str, mark: str = "") -> str:
    """Как `request_crawl.py <kind> <value> --force --unlock --locked <mark>`:
    снять отметку, записать заказ (полный — и в `crawl_request`), положить
    его в книгу с пометкой сторожа и поставить отметку «заявка». В ORDERS —
    глубина полного (число) или слово короткого (`date-…`)."""
    ORDERS.append(int(value) if kind == "days" else f"{kind}-{value}")
    conn = db.connect()
    try:
        crawl_hook.clear(conn)
        stamp_ = watch.stamp(NOW[0])
        what = f"full-{value}" if kind == "days" else f"{kind}-{value}"
        if kind == "days":
            db.set_setting(conn, "crawl_request", f"обход {value} сут.|{stamp_}")
        name, _, arg = mark[2:].partition("=")
        if name == "retry-of":
            watch.add_order(conn, what, stamp_, "", "сторож: повтор",
                            retry_of=arg, reordered=True)
        elif name == "early-for":
            watch.add_order(conn, what, stamp_, arg, "сторож: досрочный", early=True)
        else:
            watch.add_order(conn, what, stamp_, "", "сторож")
        crawl_hook.mark(conn, "заявка", f"{kind}-{value}")
    finally:
        conn.close()
    return "тест: заказ ушёл"


def refused_order(kind: str, value: str, mark: str = "") -> str:
    """Заявка сторожа не ушла: ни заказа, ни записи в книге."""
    ORDERS.append(int(value) if kind == "days" else f"{kind}-{value}")
    return "тест: заявка не прошла"


REAL_ORDER = cw.order_crawl               # настоящий заказ сторожа — для правила З1
import inspect  # noqa: E402
REAL_PULL_SRC = inspect.getsource(cw.pull)  # настоящий забор — для правила С4б
cw.order_crawl = fake_order
cw.pull = lambda: "тест: забор запущен"

passed, failed = 0, []
TAG = ["основа"]
COVERED: set[str] = set()


def rule(tag: str, title: str) -> None:
    """Дальше идут проверки правила `tag` из шапки app/watch.py."""
    TAG[0] = tag
    print(f"\n{tag}. {title}")


def check(name, cond, extra=""):
    global passed
    COVERED.add(TAG[0])
    name = f"[{TAG[0]}] {name}"
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
    """Прогон, как его отдаёт API GitHub (поля сверены с настоящим ответом
    06.10: `name` равен названию прогона, `run_started_at` — времени создания)."""
    _ids[0] += 1
    rid = rid or _ids[0]
    return {"id": rid, "run_number": rid % 1000 if isinstance(rid, int) else 0, "event": event,
            "status": status, "conclusion": conclusion if status == "completed" else None,
            "display_title": title, "name": title, "path": path,
            "repository": {"full_name": repo},
            "created_at": Z(created), "run_started_at": Z(created),
            "updated_at": Z(ended or created)}


def finished(run: dict, ended: datetime, conclusion="success") -> dict:
    """Тот же прогон, но уже закончившийся."""
    return dict(run, status="completed", conclusion=conclusion, updated_at=Z(ended))


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


def state_set(state: dict):
    """Запись книги заказов о полном заказе из `crawl_request` (то, что
    раньше было единственной памятью `crawl_watch`): дополнить полями `state`."""
    order = watch.parse_order(setting("crawl_request"))
    conn = db.connect()
    try:
        rec = watch.full_order_record(conn, order)
        watch.save_order(conn, dict(rec, **state))
    finally:
        conn.close()


def state_get() -> dict:
    """Запись книги о текущем полном заказе (`crawl_request`), без id и
    подписи «кто» — их проверки не сверяют."""
    order = watch.parse_order(setting("crawl_request"))
    conn = db.connect()
    try:
        rec = watch.full_order_record(conn, order, save=False) if order else {}
    finally:
        conn.close()
    return {k: v for k, v in rec.items() if k not in ("id", "who", "at")}


def book() -> list[dict]:
    conn = db.connect()
    try:
        return watch.load_orders(conn)
    finally:
        conn.close()


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


def alarms_after(edge: int) -> list[str]:
    return [n for n in notes_after(edge) if "ТРЕВОГА" in n]


MEMORY = ("crawl_running", "crawl_request", "crawl_order", "crawl_bad", "crawl_missed",
          "crawl_early", "crawl_cancel", "crawl_queue", "crawl_slot", "crawl_silent")


def reset(now: datetime, runs=()):
    """Чистый лист: память сторожа пуста, заглушки в исходном положении."""
    TAGS.clear()
    ORDERS.clear()
    API["calls"] = 0
    API["queue"] = []
    API["runs"] = list(runs)
    PUSH_OK[0] = True
    RESULT[0] = "picked"
    NOW[0] = now
    cw.order_crawl = fake_order
    cw.pull = lambda: "тест: забор запущен"
    watch.wait_for_start = fake_wait
    for key in MEMORY:
        setting(key, "")
    conn = db.connect()
    try:                                     # книга заказов — по строке на заказ
        for prefix in (watch.ORDER_PREFIX, watch.BAD_PREFIX, "import_stamps:"):
            conn.execute("DELETE FROM settings WHERE substr(key, 1, ?) = ?",
                         (len(prefix), prefix))
        conn.commit()
    finally:
        conn.close()


def planned(days: int, *flags) -> list[tuple]:
    """Заявка из cron в момент NOW: какие теги ушли."""
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


def ticks(*times: str) -> None:
    for hhmm in times:
        tick(K(hhmm))


def order_of(stamp_: str, days: int):
    setting("crawl_request", f"обход {days} сут.|{stamp_}")


def gap(slot="16:15", days=2, at=None) -> dict:
    """Запись `crawl_missed`: плановый слот сорвался и ждёт решения С6."""
    return {"slot": f"{DAY} {slot}", "days": days, "at": f"{DAY} {at or slot}",
            "why": "тест", "state": "missed"}


def early_mem(for_="16:15", replaces="20:30", ordered="16:30", state="ordered", **more) -> dict:
    """Запись `crawl_early`: досрочный на 6 суток за слот `for_` вместо `replaces`."""
    return dict({"for": f"{DAY} {for_}", "for_days": 2, "days": 6,
                 "replaces": f"{DAY} {replaces}", "replaces_days": 6,
                 "begun": f"{DAY} {ordered}", "ordered_at": f"{DAY} {ordered}",
                 "state": state}, **more)


yday = mkrun(K("13:44", "2026-11-09"), ended=K("13:47", "2026-11-09"), title="Обход proba-2")
probe = mkrun(K("13:44"), ended=K("13:47"), title="Обход proba-2")

# ── основа: расписание, вид прогона, потолки ────────────────────────────────
rule("основа", "расписание, вид прогона, потолки, список прогонов")
check("16:20 заявка на 2 дня — это плановый 16:15", watch.slot_for(K("16:20"), 2) == K("16:15"))
check("16:20 заявка на 6 дней — не плановый", watch.slot_for(K("16:20"), 6) is None)
check("08:14 на 6 дней — плановый 08:15", watch.slot_for(K("08:14"), 6) == K("08:15"))
check("после 16:30 следующий плановый — 20:30 на 6", watch.next_slot(K("16:30")) == (K("20:30"), 6))
check("после 08:30 следующий — 16:15 на 2", watch.next_slot(K("08:30")) == (K("16:15"), 2))
check("после 20:45 следующий — 08:15 завтра на 6",
      watch.next_slot(K("20:45")) == (K("08:15", NEXT), 6))
check("последний прошедший слот: в 16:20 — 16:15, в 16:14 — 08:15, в 07:00 — вчерашний 20:30",
      watch.last_slot(K("16:20")) == (K("16:15"), 2) and watch.last_slot(K("16:14")) == (K("08:15"), 6)
      and watch.last_slot(K("07:00")) == (K("20:30", "2026-11-09"), 6))
check("утренний слот — 08:15 (владелец 06.10: programetv.ro и tv.orf.at до ~07:00 отдают "
      "вчерашние телесутки); промежутки 8 ч, 4 ч 15 мин, 11 ч 45 мин",
      watch.SCHEDULE == (("08:15", 6), ("16:15", 2), ("20:30", 6))
      and watch.next_slot(K("08:15")) == (K("16:15"), 2)
      and watch.next_slot(K("20:30")) == (K("08:15", NEXT), 6))
cron = watch.cron_lines("/srv/x", "py")
check("cron-строки из той же таблицы",
      cron[:3] == ["15 8 * * * cd /srv/x && py scripts/request_crawl.py days 6 >> /var/log/streams-request.log 2>&1",
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
c = mkrun(K("13:20"), status="pending", title="Обход full-6")
check("старт прогона, ждавшего в очереди, — конец предыдущего (#118 за #117)",
      watch.effective_start(b, [a, b]) == K("13:52"))
check("ждёт за идущим — не завис (старта нет)", watch.effective_start(c, [a, b, c]) is None)
check("имя репозитория сверяется без учёта регистра (origin `newik89/STREAMS-crawl`)",
      watch.crawl_only([a, b], "newik89/STREAMS-crawl") == [a, b]
      and watch.crawl_only([a], "someone/fork") == [])
old_title = mkrun(K("13:32"), title="Обход телесайтов")
check("ответ на заказ полного обхода — только полный: проба, сайт и дата не в счёт",
      watch.full_runs([a, b, c, mkrun(K("13:30"), title="Обход site-nova.bg"),
                       mkrun(K("13:31"), title="Обход date-2026-11-11"), old_title], SLUG)
      == [a, c, old_title])
check("окно «досрочно»: 4 часа + запас 20 мин (от 16:15 до 20:30 — 4 ч 15 мин)",
      watch.covers_from(K("20:30")) == K("16:10") and watch.EARLY_COVERS_HOURS == 4)
check("GitHub «не ответил» отличим от «ответил»: у списка пометка ok",
      watch.Runs.silent().ok is False and watch.Runs([a]).ok is True
      and watch.Runs.silent() == [])
check("чей заказ: досрочный / плановый / ручной / дата / сайт / сайт на сервере",
      [watch.order_kind(s) for s in ({"early": True, "slot": "x"}, {"slot": "x"}, {"slot": ""}, {},
                                     {"what": "date-2026-11-11"}, {"what": "site-nova.bg"},
                                     {"what": "server-mojtv.hr"})]
      == ["early", "planned", "manual", "manual", "date", "site", "server"])
# сценарий проверяющего 06.10 №2: ручной на 2 дня минутой раньше — не ответ на плановый на 6
d2_early = mkrun(K("06:14", NEXT), title="Обход full-2")
d6_late = mkrun(K("06:16", NEXT), status="pending", title="Обход full-6")
check("ответ на заказ на 6 дней — прогон с окном не меньше: ручной на 2 дня в 06:14 НЕ ответ на 06:15",
      watch.run_for({"at": K("06:15", NEXT), "days": 6}, [d2_early]) is None
      and watch.run_for({"at": K("06:15", NEXT), "days": 6}, [d2_early, d6_late]) is d6_late)
check("отметка заказа округлена вниз до минуты: прогон, созданный за минуту до неё, — чужой",
      watch.run_for({"at": K("06:15", NEXT), "days": 2},
                    [mkrun(K("06:14", NEXT), title="Обход full-2")]) is None)
# окно дней (решение владельца 06.10, «добор дней» — следующий пакет)
check("окно дней: full-6 → 1…6, full-6-from3 → 3…6, days-2 → 1…2, проба — не полный",
      watch.window("full-6") == (1, 6) and watch.window("full-6-from3") == (3, 6)
      and watch.window("days-2") == (1, 2) and watch.window("proba-2") is None
      and watch.run_kind({"display_title": "Обход full-6-from3"}) == ("full", 6))
check("«2 дня» и «6 дней с 3-го» вместе накрывают слот на 6; по отдельности — нет; с дырой — нет",
      watch.covered((1, 6), [(1, 2), (3, 6)]) and not watch.covered((1, 6), [(3, 6)])
      and not watch.covered((1, 6), [(1, 2), (4, 6)]))
part = mkrun(K("06:16", NEXT), status="in_progress", title="Обход full-6-from3")
check("будущий «6 дней с 3-го» — ответ на заказ full-6-from3, но не на full-6",
      watch.run_for({"at": K("06:15", NEXT), "what": "full-6-from3"}, [part]) is part
      and watch.run_for({"at": K("06:15", NEXT), "days": 6}, [part]) is None)
# перевод часов 25.10.2026: 04:00 летнего = 03:00 зимнего
OCT = "2026-10-25"
check("перевод часов: окно досрочного считается настоящими часами (08:15 зимнего − 4 ч 20 мин = 01:55 UTC)",
      watch.covers_from(K("08:15", OCT)) == datetime(2026, 10, 25, 1, 55, tzinfo=timezone.utc))
check("перевод часов: заказ 01:30, сейчас 06:45 — прошло 6 ч 15 мин настоящих (а не 5 ч 15 мин) → «состарился»",
      watch.decide({"at": watch.kyiv_at(f"{OCT} 01:30"), "stamp": f"{OCT} 01:30", "days": 6},
                   None, K("06:45", OCT), {}, "unknown")[0] == "expired")

# ── З1. общий замок заявки и сторожа ────────────────────────────────────────
rule("З1", "заявка и сторож в одну минуту — общий замок")
with watch.order_lock(1) as lock_a:
    with watch.order_lock(0.3) as lock_b:
        pass
with watch.order_lock(0.3) as lock_c:
    pass
check("пока первый держит замок, второй не входит; первый отпустил — замок свободен",
      lock_a is True and lock_b is False and lock_c is True, (lock_a, lock_b, lock_c))
reset(K("20:30"), [probe])
jset("crawl_missed", gap())                  # 16:15 сорвался, GitHub молчал до 20:30
tick(K("20:30"))                             # первым успел сторож
first = list(ORDERS)
sent = planned(6)                            # заявка 20:30 — второй, видит его заказ
check("гонка, первым сторож: он заказал досрочный на 6 → плановая 20:30 второй обход не заказывает",
      first == [6] and sent == [] and ORDERS == [6], (first, sent, ORDERS))
reset(K("20:30"), [probe])
jset("crawl_missed", gap())
sent = planned(6)                            # первой успела заявка
tick(K("20:30"))
check("гонка, первой заявка: плановая на 6 ушла → сторож досрочный не заказывает",
      sent == [("days", "6")] and ORDERS == []
      and jget("crawl_missed").get("state") == "drop", (sent, ORDERS, jget("crawl_missed")))
waits = (watch.LOCK_WAIT_REQUEST, watch.LOCK_WAIT_WATCH)
watch.LOCK_WAIT_REQUEST = watch.LOCK_WAIT_WATCH = 0.3
reset(K("16:15"), [probe])
edge = last_id()
argv = sys.argv
with watch.order_lock(1) as stuck_holder:    # «зависший» процесс держит замок
    sent = planned(2)
    before = API["calls"]
    sys.argv = ["crawl_watch.py"]
    code = cw.main()
    sys.argv = argv
    during = API["calls"] - before
check("замок держит зависший сторож → плановая заявка ждёт срок и УХОДИТ без замка",
      stuck_holder is True and sent == [("days", "2")], (stuck_holder, sent))
check("…со строкой «общий замок … занят … иду без замка»",
      any("иду без замка" in n for n in notes_after(edge)), notes_after(edge))
check("…а сторож при занятом замке проверку пропускает (к GitHub не ходит, не падает)",
      code == 0 and during == 0, (code, during))
watch.LOCK_WAIT_REQUEST = watch.LOCK_WAIT_WATCH = 30
reset(K("13:00"), [probe])
began = time.monotonic()
with watch.order_lock(1):
    sent = planned(6, "--force", "--unlock", "--locked")
check("заявка сторожа (--locked) замок не берёт: уходит сразу, себя не ждёт",
      sent == [("days", "6")] and time.monotonic() - began < 10, time.monotonic() - began)
watch.LOCK_WAIT_REQUEST, watch.LOCK_WAIT_WATCH = waits
seen = {}


def fake_run(cmd, **k):
    seen["cmd"], seen["timeout"] = list(cmd[-5:]), k.get("timeout")
    raise subprocess.TimeoutExpired(cmd, k.get("timeout"))


real_run, cw.subprocess.run = cw.subprocess.run, fake_run
try:
    said = REAL_ORDER("days", "6", "--early-for=x")
finally:
    cw.subprocess.run = real_run
check("сторож зовёт заявку с ключом --locked; заявка не уложилась в срок — проверка не падает",
      seen.get("cmd") == ["6", "--force", "--unlock", "--locked", "--early-for=x"]
      and seen.get("timeout") == watch.ORDER_TIMEOUT_SECONDS and "не уложилась" in said,
      (seen, said))
reset(K("06:30"), [yday])
order_of(f"{DAY} 06:15", 6)
sys.argv = ["crawl_watch.py"]
code = cw.main()
sys.argv = argv
check("сторож через main (под замком) делает то же, что одна проверка: один заказ",
      code == 0 and ORDERS == [6], (code, ORDERS))

# ── З2. отметка «заявка пришла на слот» ─────────────────────────────────────
rule("З2", "заявка отмечается «пришла на слот» и пишет итог")
reset(K("16:15"), [probe])
planned(2)
check("плановая ушла → запись слота 16:15 с итогом ordered",
      jget("crawl_slot").get("slot") == f"{DAY} 16:15"
      and jget("crawl_slot").get("state") == "ordered", jget("crawl_slot"))
reset(K("16:15"), [probe, mkrun(K("15:40"), status="in_progress", title="Обход full-6")])
mark("идёт", 35, "full-6")
planned(2)
check("плановая решила не заказывать → итог skipped", jget("crawl_slot").get("state") == "skipped")
reset(K("16:15"), [])
mark("идёт", 35, "full-6")
planned(2)
check("плановую отложили (GitHub молчит) → итог missed", jget("crawl_slot").get("state") == "missed")
reset(K("16:15"), [probe])
planned(2, "--check")
check("«только сказать» записи не оставляет", jget("crawl_slot") == {})
reset(K("16:15"), [probe])
planned(6, "--force", "--unlock", "--locked")
check("заявка сторожа (--force) — не плановая, записи не оставляет", jget("crawl_slot") == {})
reset(K("13:00"), [probe])
planned(2)
check("ручной заказ не в слот записи не оставляет", jget("crawl_slot") == {})

# ── З3. слот уже заменён досрочным ──────────────────────────────────────────
rule("З3", "слот заменён досрочным сбором сторожа")
e_ok = mkrun(K("16:31"), ended=K("18:00"), title="Обход full-6")
reset(K("20:30"), [probe, e_ok])
jset("crawl_early", early_mem())
edge = last_id()
check("досрочный дошёл до конца → плановый 20:30 пропущен", planned(6) == [])
check("…строка «выполнен досрочно в 16:31»",
      any("выполнен досрочно в 16:31" in n for n in notes_after(edge)), notes_after(edge))
reset(K("20:30"), [probe, finished(e_ok, K("17:10"), "failure")])
jset("crawl_early", early_mem())
edge = last_id()
check("досрочный упал → в 20:30 плановый на 6 ушёл", planned(6) == [("days", "6")])
check("…строка «досрочный … кончился «failure» — плановый идёт как обычно»",
      any("failure" in n and "как обычно" in n for n in notes_after(edge)), notes_after(edge))
reset(K("20:30"), [probe])
jset("crawl_early", early_mem())
check("досрочный так и не стартовал → 20:30 идёт", planned(6) == [("days", "6")])
e_run = mkrun(K("19:46"), status="in_progress", title="Обход full-6")
reset(K("20:30"), [probe, e_run])
jset("crawl_early", early_mem(ordered="19:45"))
edge = last_id()
check("досрочный ещё идёт в минуту слота → плановый не заказан", planned(6) == [])
check("…но «выполнен досрочно» не сказано: строка «ещё идёт … будет тревога»",
      any("ещё идёт" in n and "будет тревога" in n for n in notes_after(edge))
      and not any("выполнен досрочно" in n for n in notes_after(edge)), notes_after(edge))
check("…и в памяти помечено: слот пропущен ради идущего досрочного",
      jget("crawl_early").get("skipped") is True, jget("crawl_early"))
reset(K("16:15"), [probe, mkrun(K("06:31"), ended=K("08:00"), title="Обход full-6")])
jset("crawl_early", early_mem(for_="06:15", replaces="16:15", ordered="06:30", state="done"))
edge = last_id()
check("утренний досрочный (06:31) вечерний 16:15 не заменяет: начат раньше 11:55",
      planned(2) == [("days", "2")])
check("…строка «раньше, чем за 4 ч … как обычно»",
      any("раньше, чем за 4 ч" in n for n in notes_after(edge)), notes_after(edge))
reset(K("16:15"), [probe, mkrun(K("12:31"), ended=K("14:00"), title="Обход full-6")])
jset("crawl_early", early_mem(for_="06:15", replaces="16:15", ordered="12:30", state="done"))
check("досрочный в 12:30 (06:15 сорвался поздно) дошёл → 16:15 пропущен", planned(2) == [])
reset(K("20:30"), [probe])                   # прогон выпал из списка последних
jset("crawl_early", early_mem(state="done", started=f"{DAY} 16:31", run=205))
edge = last_id()
check("досрочный дошёл (память «done»), а в списке его уже нет → 20:30 всё равно пропущен",
      planned(6) == [] and any("выполнен досрочно в 16:31" in n and "по памяти сторожа" in n
                               and "#205" in n for n in notes_after(edge)), notes_after(edge))
reset(K("20:30"), [])                        # GitHub молчит
jset("crawl_early", early_mem(state="done", started=f"{DAY} 16:31", run=205))
check("GitHub молчит, память «done» → 20:30 пропущен", planned(6) == [])
reset(K("20:30"), [])
jset("crawl_early", early_mem())
check("GitHub молчит, досрочный не подтверждён → 20:30 идёт как обычно",
      planned(6) == [("days", "6")])

# ── З4. отметка «сбор идёт» ─────────────────────────────────────────────────
rule("З4", "стоит отметка «сбор идёт» — сверка с GitHub")
reset(K("16:15"), [probe])
mark("идёт", 15, "proba-2")
edge = last_id()
sent = planned(2)
notes = notes_after(edge)
check("случай 05.10: ложная отметка пробы, прогонов нет → заявка на 2 дня ушла",
      sent == [("days", "2")], sent)
check("…отметка «идёт proba-2» снята, стоит своя «заявка days-2»",
      setting("crawl_running").startswith("заявка|") and setting("crawl_running").endswith("|days-2"),
      setting("crawl_running"))
check("…строка «сторож: отметка … снята — на GitHub прогонов нет»",
      any(n.startswith("сторож: отметка") and "снята" in n and "прогонов нет" in n for n in notes), notes)
check("…к API — один запрос", API["calls"] == 1, API["calls"])
reset(K("16:15"), [probe])
mark("идёт", 160, "full-6")
check("ложная отметка «идёт full-6» без прогонов → тоже снята, заявка ушла",
      planned(2) == [("days", "2")] and setting("crawl_running").endswith("|days-2"))
full6 = mkrun(K("15:40"), status="in_progress", title="Обход full-6")
reset(K("16:15"), [full6])
mark("идёт", 35, "full-6")
edge = last_id()
check("идёт полный на 6 → плановый на 2 пропущен", planned(2) == [])
check("…строка «не нужен — на GitHub уже идёт обход … на 6 сут.»",
      any("не нужен" in n and "6 сут." in n for n in notes_after(edge)), notes_after(edge))
check("…отметку идущего не трогает", setting("crawl_running").endswith("|full-6"))
check("…и сорвавшимся слот не считает", jget("crawl_missed") == {})
pr = mkrun(K("16:05"), status="in_progress", title="Обход proba-2")
wait6 = mkrun(K("16:08"), status="pending", title="Обход full-6")
reset(K("16:15"), [pr, wait6])
mark("идёт", 10, "proba-2")
edge = last_id()
check("идёт проба, за ней ждёт полный на 6 → плановый на 2 пропущен (ждущего не вытесняем)",
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
check("ВРЕМЕННО: прогон без названия вида (до выкладки) → вид из отметки: full-6, пропуск",
      planned(2) == [])
reset(K("16:15"), [mkrun(K("16:14"), status="in_progress", title="Обход по расписанию",
                         event="schedule")])
mark("идёт", 35, "full-6")
check("идёт запуск по расписанию GitHub (сразу выходит) → плановый на 2 заказан в очередь",
      planned(2) == [("days", "2")])
reset(K("16:15"), [])                        # GitHub не ответил
mark("идёт", 35, "full-6")
edge = last_id()
check("GitHub молчит, отметка «идёт full-6» → заявка отложена", planned(2) == [])
check("…слот 16:15 записан сорвавшимся — им займётся сторож",
      jget("crawl_missed").get("slot") == f"{DAY} 16:15" and jget("crawl_missed").get("days") == 2
      and jget("crawl_missed").get("state") == "missed", jget("crawl_missed"))
check("…строка «отложен … сторож сверится»",
      any("отложен" in n and "Сторож" in n for n in notes_after(edge)), notes_after(edge))
reset(K("16:15"), [])
mark("идёт", 5, "proba-2")
check("GitHub молчит, отметка пробы → заявка уходит в очередь",
      planned(2) == [("days", "2")] and setting("crawl_running").endswith("|proba-2"))
reset(K("16:15"), [probe])
check("отметки нет → к API не ходит, заявка уходит", planned(2) == [("days", "2")]
      and API["calls"] == 0, API["calls"])
reset(K("16:15"), [probe])
mark("идёт", 15, "proba-2")
check("--check ничего не меняет", planned(2, "--check") == []
      and setting("crawl_running").endswith("|proba-2"))

# ── З5. правило «1 час» ─────────────────────────────────────────────────────
rule("З5", "правило «1 час» — и заказ, который не дошёл, в него не идёт")
reset(K("16:15"), [probe, mkrun(K("15:46"), status="in_progress", title="Обход full-6")])
order_of(f"{DAY} 15:45", 6)
edge = last_id()
check("заказ на 6 дней 30 мин назад, обход идёт → плановый на 2 отменён", planned(2) == [])
check("…строка «плановый обход 2 сут. отменён … правило «1 час»»",
      any("отменён" in n and "1 час" in n for n in notes_after(edge)), notes_after(edge))
reset(K("16:15"), [probe])
order_of(f"{DAY} 16:12", 6)
check("заказ 3 мин назад, GitHub его ещё не показал → в счёт (свежий), плановый отменён",
      planned(2) == [])
reset(K("16:15"), [])
order_of(f"{DAY} 15:45", 6)
check("GitHub молчит, сторож о срыве не писал → заказу верим, плановый отменён", planned(2) == [])
reset(K("16:15"), [probe])
order_of(f"{DAY} 15:45", 6)
edge = last_id()
check("заказ 30 мин назад так и не стартовал → не в счёт, плановый на 2 УХОДИТ",
      planned(2) == [("days", "2")])
check("…строки «отменён» нет", not any("отменён" in n for n in notes_after(edge)), notes_after(edge))
reset(K("16:15"), [probe, mkrun(K("15:46"), ended=K("15:50"), conclusion="failure",
                                title="Обход full-6")])
order_of(f"{DAY} 15:45", 6)
check("заказ 30 мин назад упал → не в счёт, плановый уходит", planned(2) == [("days", "2")])
reset(K("16:15"), [probe, mkrun(K("15:46"), ended=K("15:50"), conclusion="cancelled",
                                title="Обход full-6")])
order_of(f"{DAY} 15:45", 6)
check("заказ 30 мин назад отменён → не в счёт, плановый уходит", planned(2) == [("days", "2")])
reset(K("20:30"), [])                        # GitHub молчит, а сторож срыв записал
order_of(f"{DAY} 19:45", 6)
state_set({"order": f"{DAY} 19:45", "slot": f"{DAY} 16:15", "early": True,
                     "failed": True})
check("GitHub молчит, но в памяти сторожа заказ 19:45 сорвался → плановый на 6 уходит",
      planned(6) == [("days", "6")])
reset(K("20:30"), [probe, mkrun(K("19:46"), ended=K("19:50"), conclusion="failure",
                                title="Обход full-6")])
order_of(f"{DAY} 19:45", 6)
jset("crawl_early", early_mem(ordered="19:45", state="failed"))
edge = last_id()
check("досрочный заказан в 19:45 и упал → в 20:30 плановый на 6 УХОДИТ, а не отменяется молча",
      planned(6) == [("days", "6")] and not any("отменён" in n for n in notes_after(edge)),
      notes_after(edge))
# ночь перевода часов 25.10.2026: в 04:00 летнего стрелки — на 03:00 зимнего
reset(K("12:00"), [probe])
setting("crawl_request", "обход 6 сут.|2026-10-25 02:50")            # 23:50 UTC 24.10
late = datetime(2026, 10, 25, 3, 40, tzinfo=KYIV, fold=1)             # 01:40 UTC — 1 ч 50 мин спустя
soon = datetime(2026, 10, 25, 3, 20, tzinfo=KYIV, fold=0)             # 00:20 UTC — 30 мин спустя
conn = db.connect()
try:
    late_fresh = crawl_hook.fresh_full(conn, late)
    soon_fresh = crawl_hook.fresh_full(conn, soon)
finally:
    conn.close()
check("перевод часов: заказ 02:50, сейчас 03:40 зимнего — прошло 1 ч 50 мин настоящих, "
      "правило «1 час» его уже не считает (по настенным было бы 50 мин)",
      late_fresh == [] and len(soon_fresh) == 1, (late_fresh, soon_fresh))

# ── З6. тег-заявка и запись заказа ──────────────────────────────────────────
rule("З6", "тег-заявка: ушла — заказ записан, не ушла — слот сорвавшийся")
reset(K("16:15"), [probe])
planned(2)
check("тег ушёл → заказ записан для сторожа", setting("crawl_request") == f"обход 2 сут.|{DAY} 16:15")
reset(K("16:15"), [probe])
PUSH_OK[0] = False
edge = last_id()
check("тег не ушёл → слот записан сорвавшимся, строка «не ушла … сторож закажет»",
      planned(2) == [("days", "2")] and jget("crawl_missed").get("slot") == f"{DAY} 16:15"
      and any("не ушла" in n and "сторож" in n for n in notes_after(edge)), notes_after(edge))
reset(K("13:00"), [probe])
PUSH_OK[0] = False
planned(2)
check("ручной заказ не в слот не ушёл → сорвавшимся слотом не считается",
      jget("crawl_missed") == {})
reset(K("16:15"), [probe])
PUSH_OK[0] = None                            # git не ответил за 90 с (так было 29.09)
planned(2)
check("git не ответил вовремя («могла дойти») → не срыв: заказ записан как плановый, слот не сорвавшийся",
      setting("crawl_request") == f"обход 2 сут.|{DAY} 16:15" and jget("crawl_missed") == {}
      and state_get() == {"what": "full-2", "order": f"{DAY} 16:15", "slot": f"{DAY} 16:15"}
      and jget("crawl_slot").get("state") == "ordered", (jget("crawl_missed"), state_get()))
API["runs"] = [probe, mkrun(K("16:16"), status="in_progress", title="Обход full-2")]
tick(K("16:30"))
check("…тег всё-таки дошёл, обход идёт → сторож просто ждёт: ни заказов, ни тревог",
      ORDERS == [] and alarms_after(last_id() - 1) == [], ORDERS)

# ── З7. ждём старта ─────────────────────────────────────────────────────────
rule("З7", "ждём старта 3 минуты; тег не повторяем — замену закажет сторож")
nosleep = lambda s: None  # noqa: E731
real_wait = lambda order, slug, kinds, **k: REAL_WAIT(order, slug, kinds, sleep=nosleep, **k)  # noqa: E731
reset(K("16:15"), [probe, mkrun(K("16:15"), status="queued", title="Обход full-2")])
watch.wait_for_start = real_wait
edge = last_id()
check("прогон на заявку появился → один тег, строка «пошёл прогон»",
      planned(2) == [("days", "2")] and any("пошёл прогон" in n for n in notes_after(edge)),
      notes_after(edge))
reset(K("16:15"), [])                        # список прогонов не отвечает
watch.wait_for_start = real_wait
edge = last_id()
sent = planned(2)
check("GitHub не отвечает на список прогонов → тег ОДИН, повтора нет",
      sent == [("days", "2")], sent)
check("…строка «не отвечает … Тег не повторяю … следит сторож»",
      any("не отвечает" in n and "Тег не повторяю" in n and "сторож" in n
          for n in notes_after(edge)), notes_after(edge))
check("…опросов десять (0…180 с), второго круга ожидания нет", API["calls"] == 10, API["calls"])


def fwd_run(status="in_progress", conclusion=None, tag="btn-days-2-1789"):
    """Прогон пересылки тега (`queue.yml`), как его отдаёт API: имя тега — в
    `head_branch` (сверено вживую 06.10: «Кнопки сайта» #101 →
    `btn-cancel-37375152529-1791235179`)."""
    r = mkrun(K("16:15"), status=status, conclusion=conclusion or "success",
              title="tag", event="push", path=".github/workflows/queue.yml")
    return dict(r, head_branch=tag)


# сценарий проверяющего 06.10 №3 и все виды пересылки: тег не повторяется НИКОГДА
for queue_runs, said in (([], "не показал"),
                         ([fwd_run("queued")], "ждёт машину"),
                         ([fwd_run("completed", "success")], "переслан"),
                         ([fwd_run("completed", "failure")], "упала"),
                         ([fwd_run("queued", tag="btn-cancel-99-1789")], "не показал")):
    reset(K("16:15"), [probe])               # отвечает, но прогона на заявку нет
    API["queue"] = queue_runs
    watch.wait_for_start = real_wait
    edge = last_id()
    sent = planned(2)
    check(f"обхода нет 3 мин, пересылка тега — «{said}» → тег ОДИН, строка честно называет причину",
          sent == [("days", "2")] and alarms_after(edge) == []
          and any(said in n and "Тег не повторяю" in n for n in notes_after(edge)),
          (sent, notes_after(edge)))
check("…опросов одиннадцать: десять за 3 мин и сверка пересылки тега", API["calls"] == 11,
      API["calls"])
watch.wait_for_start = fake_wait
edge = last_id()
tick(K("16:20"))
check("…сторож через 5 мин ещё ждёт: тег мог опоздать (худший замер — 62 с, порог — 10 мин)",
      ORDERS == [] and notes_after(edge) == [], (ORDERS, notes_after(edge)))
API["runs"] = [probe, mkrun(K("16:21"), status="in_progress", title="Обход full-2")]
tick(K("16:22"))
check("…тег опоздал на 6 мин, но обход пошёл → ни замены, ни второго обхода",
      ORDERS == [] and TAGS == [("days", "2")], (ORDERS, TAGS))
reset(K("16:15"), [probe])
watch.wait_for_start = real_wait
planned(2)
watch.wait_for_start = fake_wait
edge = last_id()
tick(K("16:30"))
check("тег так и не дошёл за 10 мин → сторож закрывает заказ как сорвавшийся и заказывает досрочный на 6",
      ORDERS == [6] and jget("crawl_early").get("for") == f"{DAY} 16:15"
      and alarms_after(edge) == [], (ORDERS, notes_after(edge)))
reset(K("16:15"), [mkrun(K("16:14"), status="in_progress", title="Обход proba-2")])
watch.wait_for_start = real_wait
mark("идёт", 1, "proba-2")
edge = last_id()
check("в списке только проба минутой раньше — она не ответ на заявку по дням: «не стартовал»",
      planned(2) == [("days", "2")]
      and any("не стартовал за 3 мин" in n for n in notes_after(edge)), notes_after(edge))
watch.wait_for_start = fake_wait

# ── С1. GitHub не отвечает сторожу ──────────────────────────────────────────
rule("С1", "GitHub не отвечает на список прогонов")
reset(K("16:30"), [])
jset("crawl_missed", gap())
edge = last_id()
ticks("16:30", "16:45", "17:00", "17:15")
check("GitHub молчит 45 минут → сторож ждёт: ни заказов, ни тревоги, слот ждёт решения",
      ORDERS == [] and notes_after(edge) == [] and jget("crawl_missed").get("state") == "missed",
      (ORDERS, notes_after(edge)))
ticks("17:30", "17:45", "18:00")
check("молчит час → одна ТРЕВОГА «не отвечает сторожу», заказов по-прежнему нет",
      ORDERS == [] and len(alarms_after(edge)) == 1
      and "не отвечает сторожу" in alarms_after(edge)[0], notes_after(edge))
API["runs"] = [probe]
edge = last_id()
tick(K("18:15"))
check("GitHub ответил → строка «снова отвечает», память о тишине стёрта",
      any("снова отвечает" in n for n in notes_after(edge)) and jget("crawl_silent") == {},
      notes_after(edge))
check("…и сторож сразу берётся за слот, ждавший решения (досрочный на 6)", ORDERS == [6], ORDERS)
reset(K("16:30"), [])
edge = last_id()
tick(K("16:30"))
API["runs"] = [probe]
tick(K("16:45"))
check("короткая тишина (одна проверка) → ни тревоги, ни «отбоя»", notes_after(edge) == [],
      notes_after(edge))

# ── С2. проверку оборвали посреди заказа досрочного ─────────────────────────
rule("С2", "проверку оборвали посреди заказа досрочного (перезагрузка)")


def crash_after_push(kind, value, mark=""):
    fake_order(kind, value, mark)
    raise KeyboardInterrupt("перезагрузка")


def crash_before_push(kind, value, mark=""):
    ORDERS.append(int(value))
    raise KeyboardInterrupt("перезагрузка")


reset(K("16:30"), [probe])
jset("crawl_missed", gap())
cw.order_crawl = crash_after_push
try:
    tick(K("16:30"))
except KeyboardInterrupt:
    pass
cw.order_crawl = fake_order
check("намерение записано до заявки: в памяти досрочного «ordering»",
      jget("crawl_early").get("state") == "ordering" and jget("crawl_early").get("for") == f"{DAY} 16:15",
      jget("crawl_early"))
early_run = mkrun(K("16:31"), status="in_progress", title="Обход full-6")
API["runs"] = [probe, early_run]
edge = last_id()
tick(K("16:45"))
check("заявка успела уйти → сторож подхватывает её как досрочный, второго не заказывает",
      ORDERS == [6] and jget("crawl_early").get("state") == "ordered"
      and state_get().get("early") is True
      and any("оборвали" in n and "слежу" in n for n in notes_after(edge)),
      (ORDERS, jget("crawl_early"), notes_after(edge)))
API["runs"] = [probe, finished(early_run, K("16:50"), "failure")]
edge = last_id()
ticks("17:00", "17:15")
check("…подхваченный досрочный упал → одна ТРЕВОГА, заказов больше нет",
      ORDERS == [6] and len(alarms_after(edge)) == 1, (ORDERS, notes_after(edge)))
reset(K("16:30"), [probe])
jset("crawl_missed", gap())
cw.order_crawl = crash_before_push
try:
    tick(K("16:30"))
except KeyboardInterrupt:
    pass
cw.order_crawl = fake_order
edge = last_id()
ticks("16:45", "17:00")
check("заявка уйти не успела → одна ТРЕВОГА «заказать не удалось: проверку оборвали», без нового заказа",
      ORDERS == [6] and len(alarms_after(edge)) == 1
      and "проверку оборвали" in alarms_after(edge)[0] and "20:30" in alarms_after(edge)[0]
      and jget("crawl_early").get("state") == "failed", (ORDERS, notes_after(edge)))

# ── С3. зависшие прогоны ────────────────────────────────────────────────────
rule("С3", "зависший прогон — одна заявка отмены")


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
check("ждёт очереди 25 мин, впереди никого → НЕ отменяем (к сайтам он не ходил)",
      cancels_for([q25], K("12:00")) == [])
reset(K("11:50"), [yday, q25])
order_of(f"{DAY} 11:35", 2)
edge = last_id()
ticks("11:50", "12:00", "12:15", "12:30", "12:40", "12:45", "13:00")
lines = notes_after(edge)
check("очередь GitHub стоит: на 20-й мин одна строка-предупреждение, на 60-й одна ТРЕВОГА; "
      "ни отмен, ни заказов",
      TAGS == [] and ORDERS == [] and len(alarms_after(edge)) == 1
      and sum("ждёт очереди" in n and "Не отменяю" in n for n in lines) == 2
      and "очередь GitHub стоит" in alarms_after(edge)[0], (TAGS, ORDERS, lines))
API["runs"] = [yday, dict(q25, status="in_progress")]
ticks("13:15", "13:30")
check("…прогон наконец пошёл (создан 100 мин назад) → НЕ «завис»: ход считается от "
      "последнего раза, когда его видели в очереди; ни отмен, ни заказов",
      TAGS == [] and ORDERS == [] and str(q25["id"]) in jget("crawl_queue"), (TAGS, ORDERS))
API["runs"] = [yday, finished(q25, K("13:50"))]
tick(K("14:00"))
check("…прогон закончился → память очереди чиста", jget("crawl_queue") == {}, jget("crawl_queue"))
run2 = mkrun(K("10:00"), status="in_progress", title="Обход full-2")
wait2 = mkrun(K("10:10"), status="pending", title="Обход full-6")
check("ждущий за зависшим не отменяется — только сам зависший",
      cancels_for([run2, wait2], K("12:00")) == [str(run2["id"])])
stray = mkrun(K("11:30"), status="in_progress", title="Обход proba-2")
reset(K("12:00"), [yday, stray])             # чужая проба висит 30 мин, заказов нет
edge = last_id()
calls = tick(K("12:00"))
check("зависла чужая проба → заявка отмены с номером прогона, один запрос к API",
      TAGS == [("cancel", str(stray["id"]))] and calls == 1
      and str(stray["id"]) in jget("crawl_cancel"), (TAGS, calls))
tick(K("12:05"))
check("следующая проверка, прогон ещё идёт → вторую заявку отмены не шлём, тревоги нет (5 мин)",
      len(TAGS) == 1 and alarms_after(edge) == [], (TAGS, notes_after(edge)))
API["runs"] = [yday, finished(stray, K("12:07"), "cancelled")]
tick(K("12:15"))
check("GitHub подтвердил отмену → строка «остановлен», память отмены чиста, заказов нет",
      any("остановлен" in n for n in notes_after(edge)) and jget("crawl_cancel") == {}
      and ORDERS == [], notes_after(edge))
reset(K("12:00"), [yday, stray])
tick(K("12:00"))
edge = last_id()
ticks("12:15", "12:30", "12:45")
check("прогон не остановился за 15 мин → одна ТРЕВОГА «не остановился», отмену не повторяем",
      len(alarms_after(edge)) == 1 and "не остановился" in alarms_after(edge)[0]
      and len(TAGS) == 1, (TAGS, notes_after(edge)))
reset(K("12:00"), [yday, stray])
PUSH_OK[0] = False
edge = last_id()
ticks("12:00", "12:15", "12:30", "12:45")
check("тег отмены не ушёл → одна попытка на прогон, новых тегов нет",
      TAGS == [("cancel", str(stray["id"]))], TAGS)
check("…одна ТРЕВОГА «заявка отмены … не ушла», а не строка каждые 15 минут",
      len(alarms_after(edge)) == 1 and "не ушла" in alarms_after(edge)[0]
      and sum("завис" in n for n in notes_after(edge)) == 1, notes_after(edge))
reset(K("12:00"), [yday, stray])
PUSH_OK[0] = None                            # git не ответил за 90 с — могла дойти
edge = last_id()
tick(K("12:00"))
API["runs"] = [yday, finished(stray, K("12:03"), "cancelled")]
tick(K("12:15"))
check("git не ответил вовремя на тег отмены, а он дошёл → без ТРЕВОГИ, «остановлен»",
      alarms_after(edge) == [] and any("остановлен" in n for n in notes_after(edge)),
      notes_after(edge))
hung = mkrun(K("06:16"), status="in_progress", title="Обход full-6")
reset(K("08:40"), [yday, hung])
order_of(f"{DAY} 06:15", 6)
edge = last_id()
tick(K("08:40"), check_only=True)
check("--check: ни тегов, ни заказов, ни строк", TAGS == [] and ORDERS == []
      and notes_after(edge) == [])

# ── С4а. рано судить ────────────────────────────────────────────────────────
rule("С4а", "текущий заказ: рано судить — ждём")
reset(K("06:15"), [yday])
planned(6)                                   # плановая заявка 06:15 ушла
edge = last_id()
tick(K("06:17"))
check("заявка ушла 2 мин назад, прогона ещё нет → ждём старта", ORDERS == [] and notes_after(edge) == [])
good = mkrun(K("06:16"), status="in_progress", title="Обход full-6")
API["runs"] = [yday, good]
ticks("06:30", "06:45", "07:00")
check("обход идёт → ни отмен, ни заказов, ни строк",
      ORDERS == [] and TAGS == [("days", "6")] and notes_after(edge) == [],
      (ORDERS, TAGS, notes_after(edge)))
API["runs"] = [yday, finished(good, K("07:40"))]
RESULT[0] = "pending"
tick(K("07:45"))
check("готов 5 мин назад → даём стуку 10 минут, сами не забираем",
      notes_after(edge) == [] and not state_get().get("done"), notes_after(edge))
reset(K("06:15"), [yday, good])
order_of(f"{DAY} 06:15", 6)
trigger._repo_slug = lambda: "newik89/STREAMS-crawl"
edge = last_id()
ticks("06:30", "06:45", "07:00")
trigger._repo_slug = lambda: SLUG
check("origin записан в другом регистре → сторож всё равно видит идущий обход: ни заказов, ни строк",
      ORDERS == [] and TAGS == [] and notes_after(edge) == [], (ORDERS, TAGS, notes_after(edge)))
pr = mkrun(K("16:14"), ended=K("16:16"), title="Обход proba-2")
ours = mkrun(K("16:15"), status="in_progress", title="Обход full-2")
reset(K("16:15"), [pr, ours])
order_of(f"{DAY} 16:15", 2)
RESULT[0] = "none"
edge = last_id()
tick(K("16:30"))
check("проба за минуту до плановой заявки — не её прогон: сторож ждёт настоящий обход",
      not state_get().get("done") and notes_after(edge) == [],
      (state_get(), notes_after(edge)))

# ── С4б. готов, а стук не дошёл ─────────────────────────────────────────────
rule("С4б", "текущий заказ: готов, стук не дошёл — забираем сами")
done6 = mkrun(K("06:16"), ended=K("07:40"), title="Обход full-6")
reset(K("08:00"), [yday, done6])
order_of(f"{DAY} 06:15", 6)
RESULT[0] = "pending"
pulled = []
cw.pull = lambda: (pulled.append(1) or "тест: забор запущен")
tick(K("08:00"))
check("готов, результат на GitHub, на сервере нет → запускает забор (как по стуку) и не ждёт его",
      pulled == [1] and not state_get().get("done")
      and state_get().get("pulls") == 1, state_get())
RESULT[0] = "picked"
edge = last_id()
tick(K("08:15"))
check("…следующая проверка видит результат на сервере → заказ закрыт, «забран сторожем»",
      pulled == [1] and state_get().get("done") is True
      and any("забран сторожем" in n for n in notes_after(edge)), notes_after(edge))
reset(K("08:00"), [yday, done6])
order_of(f"{DAY} 06:15", 6)
RESULT[0] = "pending"
pulled = []
cw.pull = lambda: (pulled.append(1) or "тест: забор запущен")
edge = last_id()
ticks("08:00", "08:15", "08:30", "08:45")
check("заборы не приносят результат → после второго одна ТРЕВОГА, но пробовать продолжает",
      len(pulled) == 4 and len(alarms_after(edge)) == 1
      and "2 забора подряд" in alarms_after(edge)[0], (pulled, notes_after(edge)))
RESULT[0] = "picked"
tick(K("09:00"))
check("…забор наконец принёс результат → заказ закрыт", state_get().get("done") is True)
check("забор не держит проверку: его запускает отдельная служба, как по стуку",
      cw.pull.__code__ is not None and "start_pull" in REAL_PULL_SRC)

# ── С4в. готов и забран ─────────────────────────────────────────────────────
rule("С4в", "текущий заказ: готов и забран — закрываем")
reset(K("08:00"), [yday, done6])
order_of(f"{DAY} 06:15", 6)
edge = last_id()
ticks("08:00", "08:15")
check("готов и забран по стуку → одна строка, заказ закрыт, заказов нет",
      ORDERS == [] and [n for n in notes_after(edge) if "забран по стуку" in n] == notes_after(edge)
      and len(notes_after(edge)) == 1 and state_get().get("done") is True, notes_after(edge))

# ── С4г. заказ сорвался ─────────────────────────────────────────────────────
rule("С4г", "текущий заказ сорвался: плановый → досрочный, досрочный → ТРЕВОГА, ручной → один повтор")
fail2 = mkrun(K("16:16"), ended=K("16:25"), conclusion="failure", title="Обход full-2")
reset(K("16:30"), [probe, fail2])
order_of(f"{DAY} 16:15", 2)
edge = last_id()
tick(K("16:30"))
early = jget("crawl_early")
check("ПЛАНОВЫЙ 16:15 упал → НЕ повтор на 2 дня, а сразу досрочный на 6 вместо 20:30",
      ORDERS == [6] and early.get("for") == f"{DAY} 16:15"
      and early.get("replaces") == f"{DAY} 20:30", (ORDERS, early))
check("…строки «сорвался … не повторяю» и «заказываю сейчас»",
      any("сорвался" in n and "не повторяю" in n for n in notes_after(edge))
      and any("заказываю сейчас" in n for n in notes_after(edge)), notes_after(edge))
check("…память: новый заказ — досрочный за слот 16:15",
      state_get().get("early") is True
      and state_get().get("slot") == f"{DAY} 16:15", state_get())
API["runs"] = [probe, fail2, mkrun(K("16:31"), ended=K("16:50"), conclusion="failure",
                                   title="Обход full-6")]
edge = last_id()
ticks("17:00", "17:15", "17:30")
check("ДОСРОЧНЫЙ тоже упал → одна ТРЕВОГА и ни одного нового заказа (на слот — один заказ сторожа)",
      ORDERS == [6] and len(alarms_after(edge)) == 1, (ORDERS, notes_after(edge)))
check("…тревога называет плановый, который действительно пойдёт следующим (20:30)",
      "досрочный обход за плановый 16:15 сорвался" in alarms_after(edge)[0]
      and "Следующий плановый — 20:30 (6 сут.)" in alarms_after(edge)[0], notes_after(edge))
NOW[0] = K("20:30")
setting("crawl_running", "")
check("…а в 20:30 плановый на 6 идёт как обычно", planned(6) == [("days", "6")])
# что делать после сбоя — одна таблица: поменяли строку → поменялось поведение
saved_step = watch.RECOVERY["planned-failed"]
watch.RECOVERY["planned-failed"] = "alarm"
reset(K("16:30"), [probe, fail2])
order_of(f"{DAY} 16:15", 2)
edge = last_id()
tick(K("16:30"))
watch.RECOVERY["planned-failed"] = saved_step
check("таблица RECOVERY — единственное место решения: «planned-failed → alarm» даёт ТРЕВОГУ без досрочного",
      ORDERS == [] and len(alarms_after(edge)) == 1 and "плановый обход 16:15" in alarms_after(edge)[0],
      (ORDERS, notes_after(edge)))
# причина провала из стука (схема сбоев, шаг 3): сайты закрыли доступ →
# ТРЕВОГА без досрочного; сеть — как раньше, досрочный
reset(K("16:30"), [probe, fail2])
order_of(f"{DAY} 16:15", 2)
conn_r = db.connect()
crawl_hook.remember_failure(conn_r, "full-2", "fetch-ban", now=K("16:25"))
conn_r.close()
edge = last_id()
tick(K("16:30"))
check("причина fetch-ban → ТРЕВОГА с причиной словами, досрочного нет",
      ORDERS == [] and len(alarms_after(edge)) == 1
      and "сайты закрыли доступ" in alarms_after(edge)[0], (ORDERS, notes_after(edge)))
reset(K("16:30"), [probe, fail2])
order_of(f"{DAY} 16:15", 2)
conn_r = db.connect()
crawl_hook.remember_failure(conn_r, "full-2", "fetch-net", now=K("16:25"))
conn_r.close()
edge = last_id()
tick(K("16:30"))
check("причина fetch-net → как раньше, досрочный на 6; причина в строке",
      ORDERS == [6] and any("сеть: сайты не открылись" in n for n in notes_after(edge)),
      (ORDERS, notes_after(edge)))
setting(crawl_hook.FAIL_MEMORY, "")
check("в таблице только шаги early / retry / alarm / close; незнакомый вид сбоя — ТРЕВОГА",
      set(watch.RECOVERY.values()) <= {"early", "retry", "alarm", "close"}
      and watch.recovery("что-то-новое") == "alarm"
      and [watch.failure_of(s, "failed") for s in
           ({"slot": "x"}, {"early": True, "slot": "x"}, {"slot": ""}, {"slot": "", "reordered": True})]
      == ["planned-failed", "early-failed", "manual-failed", "manual-retry-failed"])
reset(K("16:30"), [probe])
order_of(f"{DAY} 16:15", 2)
tick(K("16:30"))
check("ПЛАНОВЫЙ 16:15 не стартовал → тоже сразу досрочный на 6, без повтора на 2",
      ORDERS == [6] and jget("crawl_early").get("for") == f"{DAY} 16:15", ORDERS)
edge = last_id()
ticks("16:45", "17:00")
check("…ДОСРОЧНЫЙ не стартовал → одна ТРЕВОГА, заказов больше нет",
      ORDERS == [6] and len(alarms_after(edge)) == 1, (ORDERS, notes_after(edge)))
hung = mkrun(K("08:16"), status="in_progress", title="Обход full-6")
hung_off = finished(hung, K("10:42"), "cancelled")
reset(K("10:40"), [yday, hung])
order_of(f"{DAY} 08:15", 6)
edge = last_id()
calls = tick(K("10:40"))
check("ПЛАНОВЫЙ на 6 дней идёт 144 мин (> 140) → заявка отмены с номером прогона",
      TAGS == [("cancel", str(hung["id"]))] and calls == 1, (TAGS, calls))
check("…и в той же проверке — досрочный на 6, а не повтор («отменить зависшее и СРАЗУ заказать»)",
      ORDERS == [6] and jget("crawl_early").get("for") == f"{DAY} 08:15"
      and state_get().get("early") is True, (ORDERS, jget("crawl_early")))
check("…строка «завис … отменяю его, вместо него … досрочно»",
      any("завис" in n and "отменяю его" in n and "досрочно" in n for n in notes_after(edge)),
      notes_after(edge))
early_run = mkrun(K("10:41"), status="pending", title="Обход full-6")
API["runs"] = [yday, hung, early_run]
edge = last_id()
tick(K("10:45"))
API["runs"] = [yday, hung_off, dict(early_run, status="in_progress")]
tick(K("10:55"))
check("…отмена подтверждена, досрочный, ждавший за зависшим, идёт → второго заказа и тревог нет",
      ORDERS == [6] and len(TAGS) == 1 and alarms_after(edge) == []
      and any("остановлен" in n for n in notes_after(edge)), (ORDERS, TAGS, notes_after(edge)))
hung_e = mkrun(K("10:41"), status="in_progress", title="Обход full-6")
reset(K("13:10"), [yday, hung_off, hung_e])
order_of(f"{DAY} 10:40", 6)
state_set({"order": f"{DAY} 10:40", "slot": f"{DAY} 08:15", "early": True})
jset("crawl_early", early_mem(for_="08:15", replaces="16:15", ordered="10:40"))
edge = last_id()
tick(K("13:10"))
check("ДОСРОЧНЫЙ идёт 148 мин → заявка отмены и сразу ТРЕВОГА, заказов нет",
      TAGS == [("cancel", str(hung_e["id"]))] and ORDERS == [] and len(alarms_after(edge)) == 1
      and "Следующий плановый — 16:15 (2 сут.)" in alarms_after(edge)[0],
      (TAGS, ORDERS, notes_after(edge)))
API["runs"] = [yday, hung_off, finished(hung_e, K("13:12"), "cancelled")]
ticks("13:25", "13:40", "13:55")
check("…дальше тихо: одна тревога на досрочный, ни заказов, ни новых отмен",
      ORDERS == [] and len(TAGS) == 1 and len(alarms_after(edge)) == 1, (ORDERS, TAGS, notes_after(edge)))
NOW[0] = K("16:15")
setting("crawl_running", "")
check("…а в 16:15 плановый на 2 идёт как обычно", planned(2) == [("days", "2")])
e_run = mkrun(K("19:46"), status="in_progress", title="Обход full-6")
reset(K("20:30"), [probe, e_run])
order_of(f"{DAY} 19:45", 6)
state_set({"order": f"{DAY} 19:45", "slot": f"{DAY} 16:15", "early": True})
jset("crawl_early", early_mem(ordered="19:45"))
mark("идёт", 44, "full-6")
planned(6)                                   # З3: слот пропущен, досрочный ещё идёт
API["runs"] = [probe, finished(e_run, K("20:50"), "failure")]
setting("crawl_running", "")
edge = last_id()
ticks("21:00", "21:15", "21:30")
check("ДОСРОЧНЫЙ упал уже ПОСЛЕ слота, который пропустили ради него → одна ТРЕВОГА, заказов нет",
      ORDERS == [] and len(alarms_after(edge)) == 1, (ORDERS, notes_after(edge)))
check("…тревога правдива: 20:30 остался без обхода, следующий плановый — 08:15",
      "Плановый 20:30 был пропущен" in alarms_after(edge)[0]
      and "Следующий плановый — 08:15 (6 сут.)" in alarms_after(edge)[0]
      and "20:30 пойдёт" not in alarms_after(edge)[0], notes_after(edge))
mfail = mkrun(K("13:01"), ended=K("13:10"), conclusion="failure", title="Обход full-6")
reset(K("13:15"), [probe, mfail])
order_of(f"{DAY} 13:00", 6)
tick(K("13:15"))
check("РУЧНОЙ заказ 13:00 упал → один повтор той же глубины, досрочного нет",
      ORDERS == [6] and jget("crawl_early") == {} and state_get().get("reordered") is True,
      (ORDERS, jget("crawl_early"), state_get()))
API["runs"] = [probe, mfail, mkrun(K("13:16"), ended=K("13:25"), conclusion="failure",
                                   title="Обход full-6")]
edge = last_id()
ticks("13:45", "14:00")
check("…повтор РУЧНОГО тоже упал → одна ТРЕВОГА, без досрочного и без новых заказов",
      ORDERS == [6] and len(alarms_after(edge)) == 1 and jget("crawl_early") == {},
      (ORDERS, notes_after(edge)))
reset(K("13:10"), [yday])
order_of(f"{DAY} 13:00", 6)
tick(K("13:10"))
check("РУЧНОЙ заказ 13:00 не стартовал за 10 мин → один повтор той же глубины",
      ORDERS == [6] and state_get().get("reordered") is True, (ORDERS, state_get()))
reset(K("13:15"), [probe, mfail])
order_of(f"{DAY} 13:00", 6)
cw.order_crawl = refused_order
edge = last_id()
ticks("13:15", "13:30")
check("повтор РУЧНОГО заказа не ушёл → одна ТРЕВОГА «повторить … не вышло», попытка одна",
      ORDERS == [6] and len(alarms_after(edge)) == 1 and "не вышло" in alarms_after(edge)[0],
      (ORDERS, notes_after(edge)))
hung_m = mkrun(K("10:01"), status="in_progress", title="Обход full-6")
reset(K("12:25"), [yday, hung_m])
order_of(f"{DAY} 10:00", 6)
edge = last_id()
tick(K("12:25"))
check("РУЧНОЙ заказ 10:00 идёт 144 мин → отмена и в той же проверке один повтор",
      TAGS == [("cancel", str(hung_m["id"]))] and ORDERS == [6]
      and any("сейчас закажу его заново" in n for n in notes_after(edge)), (TAGS, ORDERS, notes_after(edge)))
reset(K("17:30"), [probe, mkrun(K("16:16"), ended=K("16:30"), conclusion="failure", title="Обход full-2"),
                   mkrun(K("16:46"), ended=K("17:05"), conclusion="failure", title="Обход full-2")])
order_of(f"{DAY} 16:45", 2)
state_set({"order": f"{DAY} 16:45", "reordered": True, "slot": f"{DAY} 16:15"})
edge = last_id()
ticks("17:30", "17:45")
check("память прежней версии (плановому уже делали повтор, и он упал) → на слот уже было два "
      "обхода: одна ТРЕВОГА, досрочного нет",
      ORDERS == [] and len(alarms_after(edge)) == 1 and jget("crawl_early") == {},
      (ORDERS, notes_after(edge)))


def button(what: str, at: str):
    """Кнопка сбора (`web._dispatch`, «Обойти сайт»): заказ в книгу, полный —
    и в `crawl_request`."""
    conn = db.connect()
    try:
        if what.startswith("full-"):
            db.set_setting(conn, "crawl_request", f"обход {what[5:]} сут.|{DAY} {at}")
        watch.add_order(conn, what, f"{DAY} {at}", who="кнопка")
    finally:
        conn.close()


# сценарий проверяющего 06.10 №4: кнопка рядом со слотом — ручной заказ, а не плановый
reset(K("16:20"), [probe])
button("full-2", "16:20")
API["runs"] = [probe, mkrun(K("16:21"), ended=K("16:40"), conclusion="failure", title="Обход full-2")]
edge = last_id()
tick(K("16:45"))
check("кнопка «2 дня» в 16:20 (рядом со слотом 16:15) упала → один ПОВТОР, а не досрочный: "
      "сторож верит записи, а не времени",
      ORDERS == [2] and jget("crawl_early") == {} and any("ручной заказ" in n for n in notes_after(edge)),
      (ORDERS, notes_after(edge)))
# у каждого заказа свой id: свой повтор сторож находит по «повтор заказа <id>»
def friend_same_minute(kind, value, mark=""):
    """Заявка повтора сторожа НЕ ушла, а друг в ту же минуту нажал «2 дня»."""
    ORDERS.append(int(value))
    button("full-2", watch.stamp(NOW[0])[-5:])
    return "тест: заявка не прошла"


reset(K("16:00"), [probe])
button("full-2", "16:00")
API["runs"] = [probe, mkrun(K("16:01"), ended=K("16:20"), conclusion="failure", title="Обход full-2")]
cw.order_crawl = friend_same_minute
edge = last_id()
tick(K("16:30"))
cw.order_crawl = fake_order
recs = book()
check("друг нажал «2 дня» в ту же минуту, когда повтор сторожа не ушёл → чужой заказ НЕ принят "
      "за свой повтор: одна ТРЕВОГА «повторить не вышло»",
      len(alarms_after(edge)) == 1 and "повторить не вышло" in alarms_after(edge)[0]
      and len(recs) == 2 and len({r["id"] for r in recs}) == 2
      and not any(r.get("retry_of") for r in recs), (notes_after(edge), recs))
check("…а заказ друга той же минуты сторож ведёт своей записью",
      any(r["order"] == f"{DAY} 16:30" and watch.is_open(r) and not r.get("reordered")
          for r in recs), recs)
reset(K("16:00"), [probe])
button("full-2", "16:00")
API["runs"] = [probe, mkrun(K("16:01"), ended=K("16:20"), conclusion="failure", title="Обход full-2")]
tick(K("16:30"))
retry = [r for r in book() if r.get("retry_of")]
check("повтор ушёл → в книге запись «повтор заказа <id>» с id исходного заказа",
      ORDERS == [2] and len(retry) == 1 and retry[0]["retry_of"] == book()[0]["id"]
      and retry[0]["reordered"] is True, book())
# находка 7: досрочный ведётся своей записью, кнопка его не вытесняет
reset(K("16:30"), [probe])
jset("crawl_missed", gap())
tick(K("16:30"))                             # досрочный на 6 за 16:15
early6 = mkrun(K("16:31"), status="in_progress", title="Обход full-6")
API["runs"] = [probe, early6]
NOW[0] = K("17:00")
button("full-2", "17:00")                    # друг нажал «2 дня» — crawl_request уже про него
d2_btn = mkrun(K("17:01"), status="pending", title="Обход full-2")
API["runs"] = [probe, early6, d2_btn]
tick(K("17:15"))
API["runs"] = [probe, finished(early6, K("17:30"), "failure"), dict(d2_btn, status="in_progress")]
edge = last_id()
tick(K("17:45"))
check("досрочный упал уже ПОСЛЕ того, как кнопкой заказали «2 дня» → его срыв не потерян: одна ТРЕВОГА",
      ORDERS == [6] and len(alarms_after(edge)) == 1 and "досрочный" in alarms_after(edge)[0]
      and jget("crawl_early").get("state") == "failed", (ORDERS, notes_after(edge)))
check("…а заказ «2 дня» сторож ведёт дальше своей записью",
      any(r["what"] == "full-2" and watch.is_open(r) for r in book()), book())
# решение владельца А: сторож ведёт и короткие сборы
reset(K("12:00"), [probe])
button("date-2026-11-12", "12:00")
API["runs"] = [probe, mkrun(K("12:01"), ended=K("12:20"), conclusion="failure",
                            title="Обход date-2026-11-12")]
edge = last_id()
tick(K("12:30"))
check("скан даты (кнопка друга) упал → один повтор той же заявки",
      ORDERS == ["date-2026-11-12"] and any("скан даты 2026-11-12" in n for n in notes_after(edge)),
      (ORDERS, notes_after(edge)))
API["runs"] = [probe, mkrun(K("12:01"), ended=K("12:20"), conclusion="failure", title="Обход date-2026-11-12"),
               mkrun(K("12:31"), ended=K("12:50"), conclusion="failure", title="Обход date-2026-11-12")]
edge = last_id()
ticks("13:00", "13:15")
check("…повтор скана даты тоже упал → одна ТРЕВОГА, к сайтам больше не ходим",
      ORDERS == ["date-2026-11-12"] and len(alarms_after(edge)) == 1, (ORDERS, notes_after(edge)))
reset(K("12:00"), [probe])
button("date-2026-11-12", "12:00")
API["runs"] = [probe, mkrun(K("11:59"), ended=K("12:15"), title="Обход date-2026-11-13"),
               mkrun(K("12:01"), ended=K("12:20"), title="Обход date-2026-11-12")]
RESULT[0] = "pending"                        # прогон дошёл, а результат на сервер не влит
RESULT_ASKED.clear()
setting("last_import_stamp:day", "2026-11-10 08:00")
pulled = []
cw.pull = lambda: (pulled.append(1) or "тест: забор запущен")
tick(K("12:35"))
check("скан даты дошёл на GitHub, но результат НЕ влит на сервер → не «дошёл», а забор",
      ORDERS == [] and pulled == [1] and watch.is_open(book()[0])
      and RESULT_ASKED == [("date-2026-11-12", "2026-11-10 08:00")], (book(), RESULT_ASKED))
RESULT[0] = "picked"
tick(K("12:50"))
check("…забор влил результат (метка заливки results/day свежее старта) → закрыт, заказов нет",
      ORDERS == [] and book()[0].get("done") is True, book())
check("метка заливки — своя у каждой папки результата: полный, скан даты, сайт",
      [watch.import_key(w) for w in ("full-6", "date-2026-11-12", "site-nova.bg")]
      == ["last_import_stamp:results", "last_import_stamp:day", "last_import_stamp:site"]
      and watch.result_dir("site-nova.bg") == "results/site")
started = datetime(2026, 11, 10, 10, 1, tzinfo=timezone.utc)
ended = datetime(2026, 11, 10, 10, 40, tzinfo=timezone.utc)
check("«влит» — когда среди заливок папки есть метка ИЗ ОКНА прогона [старт, конец]; "
      "старая или более поздняя — не его (GitHub не спрашиваем: не репозиторий → «unknown»)",
      REAL_RESULT(TMP, started, ended, "date-2026-11-12", ["2026-11-10 10:30"]) == "picked"
      and REAL_RESULT(TMP, started, ended, "date-2026-11-12", ["2026-11-10 08:00"]) == "unknown"
      and REAL_RESULT(TMP, started, ended, "date-2026-11-12",
                      ["2026-11-10 10:30", "2026-11-10 11:20"]) == "picked"
      and REAL_RESULT(TMP, started, ended, "date-2026-11-12", ["2026-11-10 11:20"]) == "unknown")
for remote, verdict in (("2026-11-10 10:30", "pending"), ("2026-11-10 11:20", "lost"),
                        ("2026-11-10 09:50", "none")):
    cache = {"fetched": True, "results/day": (True, watch._stamp_utc(remote))}
    check(f"на GitHub «собрано» {remote[-5:]} UTC, прогон шёл 10:01–10:40 → «{verdict}»",
          REAL_RESULT(TMP, started, ended, "date-2026-11-12", [], cache) == verdict)
check("заливка пишет «собрано» в список папки; список не растёт дальше предела",
      (lambda c: ([watch.remember_import(c, "day", f"2026-11-10 {i:02d}:00")
                   for i in range(40)],
                  watch.imported_stamps(c, "date-2026-11-12"))[1])(db.connect())[-2:]
      == ["2026-11-10 39:00", setting("last_import_stamp:day")]
      and len(json.loads(setting("import_stamps:day"))) == watch.IMPORT_STAMPS_KEEP)
reset(K("12:00"), [probe])
button("site-nova.bg", "12:00")
API["runs"] = [probe, mkrun(K("12:01"), status="in_progress", title="Обход site-nova.bg")]
edge = last_id()
tick(K("12:50"))
check("обход сайта на GitHub идёт 49 мин (> 45) → отмена и один повтор той же заявки",
      ORDERS == ["site-nova.bg"] and TAGS and TAGS[0][0] == "cancel", (ORDERS, TAGS))
reset(K("12:00"), [probe])
button("server-mojtv.hr", "12:00")
setting("site_crawl_result", f"mojtv.hr|{DAY} 11:00|—")     # прошлый итог, старее заказа
edge = last_id()
ticks("12:30", "12:45", "13:00")
check("обход сайта на сервере без итога 60 мин (> 45) → одна ТРЕВОГА, без повтора",
      ORDERS == [] and len(alarms_after(edge)) == 1 and "mojtv.hr" in alarms_after(edge)[0],
      (ORDERS, notes_after(edge)))
reset(K("12:00"), [probe])
button("server-mojtv.hr", "12:00")
setting("site_crawl_result", f"mojtv.hr|{DAY} 12:10|—")
tick(K("12:15"))
check("…сервер обошёл сайт (итог свежее заказа) → заказ закрыт",
      book()[0].get("done") is True and ORDERS == [], book())
reset(K("12:00"), [probe])
button("date-2026-11-12", "12:00")
button("date-2026-11-13", "12:01")
check("два заказа подряд — две записи книги: второй не вытесняет первый",
      [r["what"] for r in book()] == ["date-2026-11-12", "date-2026-11-13"], book())
reset(K("14:00"), [yday, mkrun(K("06:16"), ended=K("07:40"), title="Обход full-6")])
order_of(f"{DAY} 06:15", 6)
setting("crawl_watch", json.dumps({"order": f"{DAY} 06:15", "slot": f"{DAY} 06:15",
                                   "done": True}))
edge = last_id()
tick(K("14:00"))
setting("crawl_watch", "")
check("день выкладки: заказ 06:15 прежняя версия уже закрыла → итог перенесён в книгу, без тревоги",
      state_get().get("done") is True and alarms_after(edge) == [], (state_get(), notes_after(edge)))
reset(K("12:00"), [probe])
button("date-2026-11-09", "09:00")
conn = db.connect()
try:
    watch.add_order(conn, "date-2026-11-08", "2026-11-08 09:00", who="кнопка", done=True)
    db.set_setting(conn, "crawl_request", "обход 6 сут.|2026-11-08 06:15")
    watch.add_order(conn, "full-6", "2026-11-08 06:15", who="cron", done=True)
    watch.prune_orders(conn, K("12:00"))
finally:
    conn.close()
check("книга: закрытые заказы старше суток уходят, а запись заказа из crawl_request остаётся",
      [(r["what"], r["order"]) for r in book()]
      == [("full-6", "2026-11-08 06:15"), ("date-2026-11-09", f"{DAY} 09:00")], book())

# ── С4д. заказ состарился ───────────────────────────────────────────────────
rule("С4д", "текущий заказ за 6 часов так и не закрыт")
reset(K("15:00"), [yday])
order_of(f"{DAY} 08:15", 6)
jset("crawl_slot", {"slot": f"{DAY} 08:15", "days": 6, "at": f"{DAY} 08:15", "state": "ordered"})
state_set({"order": f"{DAY} 08:15", "slot": f"{DAY} 08:15"})
edge = last_id()
ticks("15:00", "15:15")
check("заказу 6 ч 45 мин, он не закрыт, прогона в списке нет → одна ТРЕВОГА, заказов нет",
      ORDERS == [] and len(alarms_after(edge)) == 1 and "так и не дошёл" in alarms_after(edge)[0]
      and state_get().get("failed") is True, (ORDERS, notes_after(edge)))
done8 = mkrun(K("08:16"), ended=K("09:40"), title="Обход full-6")
reset(K("15:00"), [yday, done8])
order_of(f"{DAY} 08:15", 6)
jset("crawl_slot", {"slot": f"{DAY} 08:15", "days": 6, "at": f"{DAY} 08:15", "state": "ordered"})
state_set({"order": f"{DAY} 08:15", "slot": f"{DAY} 08:15"})
edge = last_id()
tick(K("15:00"))
check("заказ состарился, но результат на сервере → закрыт молча",
      notes_after(edge) == [] and state_get().get("done") is True, notes_after(edge))
reset(K("23:00"), [yday])
order_of(f"{DAY} 16:30", 6)
jset("crawl_slot", {"slot": f"{DAY} 20:30", "days": 6, "at": f"{DAY} 20:30", "state": "skipped"})
jset("crawl_early", early_mem(skipped=True))
state_set({"order": f"{DAY} 16:30", "slot": f"{DAY} 16:15", "early": True})
edge = last_id()
ticks("23:00", "23:15")
check("ДОСРОЧНЫЙ за 6 ч так и не закрыт → одна ТРЕВОГА, заказов нет, в памяти досрочный — сорвавшийся",
      ORDERS == [] and len(alarms_after(edge)) == 1
      and jget("crawl_early").get("state") == "failed", (ORDERS, notes_after(edge), jget("crawl_early")))

# ── С5. плановая заявка на слот не приходила ────────────────────────────────
rule("С5", "плановая заявка на слот не запускалась или оборвалась")
reset(K("16:30"), [probe])
edge = last_id()
tick(K("16:30"))
check("первая проверка после выкладки (памяти о слотах нет) → запоминает слот, ничего не заказывает",
      ORDERS == [] and notes_after(edge) == [] and jget("crawl_slot").get("state") == "init"
      and jget("crawl_slot").get("slot") == f"{DAY} 16:15", jget("crawl_slot"))
reset(K("16:15"), [probe])
planned(2)
edge = last_id()
API["runs"] = [probe, mkrun(K("16:16"), status="in_progress", title="Обход full-2")]
ticks("16:30", "16:45")
check("заявка на слот приходила → сверка молчит", ORDERS == [] and notes_after(edge) == [],
      (ORDERS, notes_after(edge)))
reset(K("16:30"), [probe])                   # сервер был выключен в 16:15
jset("crawl_slot", {"slot": f"{DAY} 06:15", "days": 6, "at": f"{DAY} 06:15", "state": "ordered"})
edge = last_id()
tick(K("16:30"))
check("в 16:15 заявка не запускалась (сервер был выключен) → сторож берёт слот на себя: досрочный на 6",
      ORDERS == [6] and jget("crawl_early").get("for") == f"{DAY} 16:15"
      and any("не запускалась" in n and "беру слот на себя" in n for n in notes_after(edge)),
      (ORDERS, notes_after(edge)))
ticks("16:45", "17:00")
check("…один раз: на следующих проверках второго заказа за тот же слот нет",
      ORDERS == [6] and jget("crawl_slot").get("state") == "audited", (ORDERS, jget("crawl_slot")))
reset(K("16:20"), [probe])
jset("crawl_slot", {"slot": f"{DAY} 06:15", "days": 6, "at": f"{DAY} 06:15", "state": "ordered"})
tick(K("16:20"))
check("через 5 минут после слота судить рано (заявка может ждать замок) → ничего", ORDERS == [])
reset(K("15:00"), [probe])                   # сервер лежал с ночи до 15:00
jset("crawl_slot", {"slot": "2026-11-09 20:30", "days": 6, "at": "2026-11-09 20:30",
                    "state": "ordered"})
edge = last_id()
ticks("15:00", "15:15")
check("слот 08:15 пропал, а узнали через 6 ч 45 мин → одна ТРЕВОГА «поздно», заказа нет",
      ORDERS == [] and len(alarms_after(edge)) == 1 and "08:15" in alarms_after(edge)[0]
      and jget("crawl_missed").get("state") == "late", (ORDERS, notes_after(edge)))
reset(K("16:30"), [probe])                   # заявку оборвали сразу после отметки
jset("crawl_slot", {"slot": f"{DAY} 16:15", "days": 2, "at": f"{DAY} 16:15", "state": "started"})
edge = last_id()
tick(K("16:30"))
check("заявка отметилась «пришла» 15 мин назад и молчит → ещё ждём (она укладывается в 20)",
      ORDERS == [] and notes_after(edge) == [])
tick(K("16:45"))
check("…молчит 30 мин — её оборвали → сторож берёт слот на себя: досрочный на 6",
      ORDERS == [6] and any("оборвалась" in n for n in notes_after(edge)), (ORDERS, notes_after(edge)))
cover2 = mkrun(K("16:16"), status="in_progress", title="Обход full-2")
reset(K("16:45"), [probe, cover2])
jset("crawl_slot", {"slot": f"{DAY} 16:15", "days": 2, "at": f"{DAY} 16:15", "state": "started"})
tick(K("16:45"))
check("заявку оборвали, но тег успел уйти и обход идёт → пока не заказываем, ждём его итога",
      ORDERS == [] and jget("crawl_missed").get("state") == "missed"
      and jget("crawl_missed").get("covered_by") == str(cover2["id"]), (ORDERS, jget("crawl_missed")))
API["runs"] = [probe, finished(cover2, K("16:52"), "failure")]
edge = last_id()
ticks("17:00", "17:15")
check("…покрывающий прогон упал → ОДИН досрочный на 6, не молчание",
      ORDERS == [6] and jget("crawl_early").get("for") == f"{DAY} 16:15", (ORDERS, notes_after(edge)))
reset(K("20:45"), [probe])                   # сервер был выключен в 20:30, слот уже выполнен досрочно
jset("crawl_slot", {"slot": f"{DAY} 16:15", "days": 2, "at": f"{DAY} 16:15", "state": "missed"})
jset("crawl_early", early_mem(state="done", started=f"{DAY} 16:31", run=205))
edge = last_id()
tick(K("20:45"))
check("слот 20:30 уже выполнен досрочно, заявка не понадобилась → сверка молчит",
      ORDERS == [] and notes_after(edge) == [] and jget("crawl_slot").get("state") == "early",
      (ORDERS, notes_after(edge), jget("crawl_slot")))
reset(K("20:45"), [probe])                   # 16:15 ждал решения (GitHub молчал), 20:30 cron не сработал
jset("crawl_slot", {"slot": f"{DAY} 16:15", "days": 2, "at": f"{DAY} 16:15", "state": "missed"})
jset("crawl_missed", gap("16:15", 2, at="16:15"))
edge = last_id()
ticks("20:45", "21:00")
mem = jget("crawl_missed")
check("два сорвавшихся слота подряд (16:15 ждал решения, 20:30 не запускался) → один досрочный на 6 за оба",
      ORDERS == [6] and mem.get("slot") == f"{DAY} 20:30" and mem.get("also") == f"{DAY} 16:15"
      and mem.get("days") == 6, (ORDERS, mem))
check("…прежний слот не потерян молча: строка называет и 16:15, и 20:30",
      any("16:15" in n and "20:30" in n and "заказываю" in n for n in notes_after(edge)),
      notes_after(edge))

# ── С6. сорвавшийся слот: досрочный ─────────────────────────────────────────
rule("С6", "сорвавшийся слот: один досрочный либо ТРЕВОГА")
reset(K("16:15"), [])
mark("идёт", 35, "full-6")
planned(2)                                   # GitHub молчит — заявка отложена
API["runs"] = [probe]                        # к 16:30 GitHub ответил, прогонов нет
edge = last_id()
calls = tick(K("16:30"))
early = jget("crawl_early")
check("пример владельца: сорвался 16:15 (2 дня) → в 16:30 сторож заказал обход на 6 дней",
      ORDERS == [6], ORDERS)
check("…память: за плановый 16:15, вместо 20:30, глубина 6, заказан в 16:30",
      early.get("for") == f"{DAY} 16:15" and early.get("replaces") == f"{DAY} 20:30"
      and early.get("days") == 6 and early.get("ordered_at") == f"{DAY} 16:30"
      and early.get("state") == "ordered", early)
check("…ложная отметка снята, стоит «заявка days-6»", setting("crawl_running").endswith("|days-6"))
check("…строка «не состоялся — заказываю сейчас обход на 6 сут. вместо … 20:30»",
      any("не состоялся" in n and "на 6 сут." in n and "20:30" in n and "повторять не буду" in n
          for n in notes_after(edge)), notes_after(edge))
check("…один запрос к API за проверку", calls == 1, calls)
run6 = mkrun(K("16:31"), status="in_progress", title="Обход full-6")
API["runs"] = [probe, run6]
calls = tick(K("16:45"))
tick(K("17:00"))
check("следующие проверки — второго заказа нет", ORDERS == [6] and calls == 1, (ORDERS, calls))
API["runs"] = [probe, finished(run6, K("18:00"))]
tick(K("18:15"))
mem = jget("crawl_early")
check("досрочный дошёл и забран → память «done» с его началом и номером",
      mem.get("state") == "done" and watch.moment(mem.get("started")) == K("16:31")
      and mem.get("run"), mem)
NOW[0] = K("20:30")
setting("crawl_running", "")                 # стук «закончил» снял отметку
edge = last_id()
check("…и в 20:30 плановый на 6 пропущен: «выполнен досрочно в 16:31»",
      planned(6) == [] and any("выполнен досрочно в 16:31" in n for n in notes_after(edge)),
      notes_after(edge))
reset(K("16:30"), [probe])
jset("crawl_missed", gap())
cw.order_crawl = refused_order
edge = last_id()
ticks("16:30", "16:45")
check("заявку досрочного GitHub не принял → одна попытка и ТРЕВОГА с верным следующим слотом",
      ORDERS == [6] and len(alarms_after(edge)) == 1
      and "заказать не вышло" in alarms_after(edge)[0] and "20:30" in alarms_after(edge)[0],
      (ORDERS, notes_after(edge)))
reset(K("08:15"), [])
edge = last_id()
mark("идёт", 35, "full-6")
planned(6)
API["runs"] = [probe]
tick(K("08:30"))
early = jget("crawl_early")
check("сорвался 08:15 (6 дней) → в 08:30 заказ на 6 дней; ближайший плановый — 16:15 (2 дня)",
      ORDERS == [6] and early.get("replaces") == f"{DAY} 16:15" and early.get("days") == 6, early)
check("…пропуск 16:15 сторож НЕ обещает: до него дальше окна «досрочно»",
      not any("повторять не буду" in n for n in notes_after(edge))
      and any("в 16:15 плановый пойдёт как обычно" in n for n in notes_after(edge)),
      notes_after(edge))
reset(K("20:30"), [])
mark("идёт", 35, "full-6")
planned(6)
API["runs"] = [probe]
tick(K("20:45"))
early = jget("crawl_early")
check("сорвался 20:30 → в 20:45 заказ на 6 дней; ближайший плановый — 08:15 завтра",
      ORDERS == [6] and early.get("replaces") == f"{NEXT} 08:15", early)
API["runs"] = [probe, mkrun(K("20:46"), ended=K("22:10"), title="Обход full-6")]
tick(K("22:30"))
NOW[0] = K("08:15", NEXT)
setting("crawl_running", "")
check("…утром 08:15 плановый на 6 идёт как обычно (досрочный был за 11 с половиной часов)",
      planned(6) == [("days", "6")])
cover6 = mkrun(K("16:20"), status="in_progress", title="Обход full-6")
reset(K("16:30"), [probe, cover6])
jset("crawl_missed", gap())
edge = last_id()
ticks("16:30", "16:45", "17:00")
check("на GitHub уже идёт полный на 6 → досрочный пока не заказываем (covered), строка одна",
      ORDERS == [] and jget("crawl_missed").get("state") == "missed"
      and sum("жду его итога" in n for n in notes_after(edge)) == 1, notes_after(edge))
API["runs"] = [probe, finished(cover6, K("17:50"))]
ticks("18:00")
check("…покрывающий дошёл → «collected», досрочного нет",
      ORDERS == [] and jget("crawl_missed").get("state") == "collected", jget("crawl_missed"))
# сценарий проверяющего 06.10: тег плановой ушёл, но git ответил позже 90 с
reset(K("16:15"), [probe])
PUSH_OK[0] = False                           # как было до правки: заявка «не ушла»
planned(2)
PUSH_OK[0] = True
cover_late = mkrun(K("16:16"), status="in_progress", title="Обход full-2")
API["runs"] = [probe, cover_late]
edge = last_id()
tick(K("16:30"))
API["runs"] = [probe, finished(cover_late, K("16:50"), "failure")]
ticks("17:00", "17:15")
check("слот «не ушёл», а обход по тегу шёл и упал в 16:50 → один досрочный (раньше: 0 заказов, 0 тревог)",
      ORDERS == [6], (ORDERS, notes_after(edge)))
reset(K("16:30"), [probe])
jset("crawl_missed", gap())
order_of(f"{DAY} 16:20", 6)
API["runs"] = [probe, mkrun(K("16:21"), status="in_progress", title="Обход full-6")]
tick(K("16:30"))
check("после сорвавшегося уже заказан обход на 6 → не заказываем (drop)",
      ORDERS == [] and jget("crawl_missed").get("state") == "drop")
reset(K("15:00"), [probe])
jset("crawl_missed", gap("06:15", 6))
edge = last_id()
tick(K("15:00"))
check("сорвался 8 ч 45 мин назад → только ТРЕВОГА «поздно» (late)",
      ORDERS == [] and jget("crawl_missed").get("state") == "late"
      and len(alarms_after(edge)) == 1)
reset(K("16:15"), [])                        # в 16:15 шёл обход на 6, API молчал
order_of(f"{DAY} 15:00", 6)
state_set({"order": f"{DAY} 15:00", "slot": ""})
mark("идёт", 74, "full-6")
planned(2)
API["runs"] = [probe, mkrun(K("15:01"), ended=K("16:25"), title="Обход full-6")]
setting("crawl_running", "")
edge = last_id()
tick(K("16:30"))
check("16:15 отложили, а шедший обход на 6 к 16:30 успешно закончился → второй не заказываем (collected)",
      ORDERS == [] and jget("crawl_missed").get("state") == "collected"
      and any("уже успешно собраны" in n for n in notes_after(edge)),
      (ORDERS, jget("crawl_missed"), notes_after(edge)))
reset(K("16:30"), [probe])                   # прогона уже нет в списке последних
order_of(f"{DAY} 15:30", 6)
state_set({"order": f"{DAY} 15:30", "slot": "", "done": True})
jset("crawl_missed", gap())
edge = last_id()
tick(K("16:30"))
check("обход на 6, заказанный в 15:30, по памяти сторожа дошёл и забран → досрочный не заказываем (collected)",
      ORDERS == [] and jget("crawl_missed").get("state") == "collected"
      and any("по памяти сторожа" in n for n in notes_after(edge)),
      (ORDERS, jget("crawl_missed"), notes_after(edge)))
reset(K("16:30"), [probe, mkrun(K("12:00"), ended=K("13:30"), title="Обход full-6")])
jset("crawl_missed", gap())
tick(K("16:30"))
check("обход на 6 закончился в 13:30 (раньше, чем за час до слота) → досрочный заказываем",
      ORDERS == [6], ORDERS)
hung6 = mkrun(K("13:50"), status="in_progress", title="Обход full-6")
reset(K("16:30"), [hung6])
jset("crawl_missed", gap())
calls = tick(K("16:30"))
check("сорвался плановый, а на GitHub висит зависший полный → отмена зависшего И досрочный, один запрос",
      TAGS == [("cancel", str(hung6["id"]))] and ORDERS == [6] and calls == 1, (TAGS, ORDERS, calls))
reset(K("20:45"), [probe])
order_of(f"{DAY} 20:20", 2)                  # кнопка, не слот
jset("crawl_missed", gap("20:30", 6))
edge = last_id()
tick(K("20:45"))
check("повтор ручного (2) и досрочный (6) в одной проверке → оба ушли, ложной ТРЕВОГИ нет",
      ORDERS == [2, 6] and jget("crawl_early").get("state") == "ordered"
      and alarms_after(edge) == [], (ORDERS, jget("crawl_early"), notes_after(edge)))
# «добор дней» (следующий пакет): только что прошёл «2 дня», идёт «6 дней с 3-го»
two = mkrun(K("16:00"), ended=K("16:20"), title="Обход full-2")
rest = mkrun(K("16:21"), status="in_progress", title="Обход full-6-from3")
check("будущий вид: 6-дневный слот сорвался, а «2 дня» прошёл и «6 дней с 3-го» идёт → ждём их итога",
      watch.plan_early(gap("16:15", 6), [probe, two, rest], K("16:45"), {}, None)[0] == "covered")
check("…«6 дней с 3-го» тоже дошёл → дни 1–6 собраны (collected)",
      watch.plan_early(gap("16:15", 6), [probe, two, finished(rest, K("17:40"))], K("17:45"),
                       {}, None)[0] == "collected")
check("…плановая заявка на 6 при идущем «с 3-го» и свежем «2 дня» — не нужна (skip)",
      watch.lock_verdict({"what": "full-6", "state": "идёт", "since": "16:21"}, 6,
                         [probe, two, rest], K("16:45"))[0] == "skip")
check("…без свежего «2 дня» один «6 дней с 3-го» слот на 6 не закрывает (behind)",
      watch.lock_verdict({"what": "full-6", "state": "идёт", "since": "16:21"}, 6,
                         [probe, rest], K("16:45"))[0] == "behind")


# ── сценарии независимой проверки 06.10 (S1–S6) и находки 5–8 ──────────────
rule("сценарии", "сценарии проверяющего 06.10 и его находки")
import subprocess as _sp  # noqa: E402


def _no_git(*a, **k):
    raise OSError("git в проверке запрещён")


REAL_SUBPROCESS = watch.subprocess
NO_GIT = type("S", (), {"run": staticmethod(_no_git), "SubprocessError": _sp.SubprocessError})


def utc_stamp(at):
    return at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


# S1. два скана дат подряд: второй ждал очереди за первым, его стук потерян
reset(K("10:00"), [probe])
watch.result_state, watch.subprocess = REAL_RESULT, NO_GIT
button("date-2026-11-12", "10:00")
button("date-2026-11-13", "10:05")
d1 = mkrun(K("10:00"), ended=K("10:20"), title="Обход date-2026-11-12")
d2 = mkrun(K("10:05"), ended=K("10:40"), title="Обход date-2026-11-13")   # run_started_at = создание
API["runs"] = [probe, d1, d2]
setting("last_import_stamp:day", utc_stamp(K("10:19")))   # влит только скан 12-го
tick(K("10:55"))
b = {r["what"]: r for r in book()}
check("S1: второй скан ждал очереди, влит только первый → второй НЕ «влит» (окно — от "
      "настоящего старта), первый — закрыт",
      not b["date-2026-11-13"].get("done") and b["date-2026-11-12"].get("done") is True,
      {k: (v.get("done"), v.get("failed")) for k, v in b.items()})
# S1b. плановый 6 дней в очереди за ручным 2 дня; стук планового потерян
reset(K("20:00"), [probe])
watch.result_state, watch.subprocess = REAL_RESULT, NO_GIT
button("full-2", "20:00")
fr = mkrun(K("20:00"), ended=K("20:40"), title="Обход full-2")
API["runs"] = [probe, mkrun(K("20:00"), status="in_progress", title="Обход full-2")]
mark("идёт", 30, "full-2")
NOW[0] = K("20:30")
planned(6)
p6 = mkrun(K("20:30"), ended=K("22:10"), title="Обход full-6")
API["runs"] = [probe, fr, p6]
setting("last_import_stamp:results", utc_stamp(K("20:39")))   # влит только ручной 2 дня
tick(K("22:30"))
rec6 = [r for r in book() if r["what"] == "full-6"]
check("S1b: плановый 6 дней ждал за ручным 2 дня, влит только ручной → плановый НЕ закрыт «дошёл»",
      rec6 and not rec6[0].get("done"), rec6)
watch.subprocess = REAL_SUBPROCESS
watch.result_state = lambda root, start, end, what, imported, cache=None: (
    RESULT_ASKED.append((what, imported[-1] if imported else "")) or RESULT[0])

# S2. перезагрузка сервера посреди повтора
reset(K("12:00"), [probe])
button("date-2026-11-12", "12:00")
API["runs"] = [probe, mkrun(K("12:01"), ended=K("12:20"), conclusion="failure",
                            title="Обход date-2026-11-12")]


def dying(kind, value, mark=""):
    fake_order(kind, value, mark)            # тег ушёл, запись повтора в книге
    raise KeyboardInterrupt("перезагрузка")  # …и процесс сторожа убит


cw.order_crawl = dying
try:
    tick(K("12:30"))
except KeyboardInterrupt:
    pass
cw.order_crawl = fake_order
API["runs"].append(mkrun(K("12:31"), status="in_progress", title="Обход date-2026-11-12"))
edge = last_id()
tick(K("12:45"))
check("S2: проверку оборвали посреди повтора, а повтор ушёл → второго повтора нет, тревоги нет",
      ORDERS.count("date-2026-11-12") == 1 and alarms_after(edge) == [], (ORDERS, notes_after(edge)))
reset(K("12:00"), [probe])
button("date-2026-11-12", "12:00")
API["runs"] = [probe, mkrun(K("12:01"), ended=K("12:20"), conclusion="failure",
                            title="Обход date-2026-11-12")]


def dying_before(kind, value, mark=""):
    ORDERS.append(f"{kind}-{value}")         # заявку начали, тег не ушёл
    raise KeyboardInterrupt("перезагрузка")


cw.order_crawl = dying_before
try:
    tick(K("12:30"))
except KeyboardInterrupt:
    pass
cw.order_crawl = fake_order
edge = last_id()
ticks("12:45", "13:00")
check("S2: оборвали ДО заявки повтора → одна ТРЕВОГА «повтор заказать не удалось», "
      "повтора больше нет",
      ORDERS == ["date-2026-11-12"] and len(alarms_after(edge)) == 1
      and "проверку оборвали" in alarms_after(edge)[0], (ORDERS, notes_after(edge)))

# S3. книга заказов: 1000 записей
reset(K("12:00"), [probe])
conn = db.connect()
try:
    for i in range(1000):
        day = "2026-11-08" if i < 500 else DAY
        oid = f"{day} 09:{i % 60:02d}:{i // 60:02d}|t{i}"
        db.set_setting(conn, f"{watch.ORDER_PREFIX}{oid}",
                       json.dumps({"id": oid, "what": "date-2026-11-12",
                                   "order": f"{day} 09:{i % 60:02d}", "who": "t", "done": True}))
finally:
    conn.close()
t0 = time.perf_counter()
tick(K("12:00"))
spent = time.perf_counter() - t0
check("S3: 1000 закрытых записей — старше суток ушли (500), свежие остались, проверка < 2 с",
      len(book()) == 500 and spent < 2, (len(book()), spent))
conn = db.connect()
try:
    for _ in range(200):
        watch.add_order(conn, "date-2026-11-12", f"{DAY} 12:00", who="t2")
finally:
    conn.close()
ids = [r["id"] for r in book() if r["who"] == "t2"]
check("S3: 200 заказов в одну секунду — 200 разных id", len(set(ids)) == 200, len(set(ids)))

# S4. перевод часов 25.10.2026
s = list(watch._slots(datetime(2026, 10, 25).date()))
check("S4: 08:15 Киева 25.10 = 06:15 UTC (зима), 24.10 = 05:15 UTC (лето)",
      s[0][0].strftime("%H:%M") == "06:15"
      and list(watch._slots(datetime(2026, 10, 24).date()))[0][0].strftime("%H:%M") == "05:15")
check("S4: после 20:30 24.10 следующий — 08:15 25.10 на 6",
      watch.next_slot(datetime(2026, 10, 24, 17, 31, tzinfo=timezone.utc))
      == (datetime(2026, 10, 25, 6, 15, tzinfo=timezone.utc), 6))
second_pass = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)      # 03:30 зимнего
conn = db.connect()
try:
    rec_dst = watch.add_order(conn, "full-6", "2026-10-25 03:30", who="t", at=second_pass)
finally:
    conn.close()
other = {"id": 1, "event": "workflow_dispatch", "status": "completed", "conclusion": "success",
         "display_title": "Обход full-6", "created_at": "2026-10-25T00:45:00Z",
         "run_started_at": "2026-10-25T00:45:00Z", "updated_at": "2026-10-25T01:20:00Z"}
mine = dict(other, id=2, status="in_progress", conclusion=None,
            created_at="2026-10-25T01:30:40Z", run_started_at="2026-10-25T01:30:40Z")
got = watch.run_for(watch.record_order(rec_dst), [other, mine])
check("S4: заказ во второй проход 03:30 — время в книге в UTC; ответом взят свой прогон, "
      "а не чужой часом раньше",
      rec_dst["at"] == "2026-10-25T01:30:00+00:00" and got["id"] == 2, (rec_dst, got["id"]))

# S5. настоящая заявка с id повтора (пробел и «|» в аргументе)
reset(K("12:30"), [probe])
rid = f"{DAY} 12:00:05|кнопка"
saved_argv = sys.argv
sys.argv = ["request_crawl.py", "date", "2026-11-12", "--force", "--unlock", "--locked",
            f"--retry-of={rid}"]
try:
    rc.main()
finally:
    sys.argv = saved_argv
conn = db.connect()
try:
    found = watch.find_order(conn, retry_of=rid)
finally:
    conn.close()
check("S5: настоящий request_crawl с --retry-of=<id> → запись повтора с retry_of и reordered",
      found.get("retry_of") == rid and found.get("reordered") is True
      and watch.order_who(found) == "date-retry", found)

# S6. 20 проб с GitHub, пока идёт плановый
reset(K("20:30"), [probe])
order_of(f"{DAY} 20:30", 6)
conn = db.connect()
try:
    watch.add_order(conn, "full-6", f"{DAY} 20:30", f"{DAY} 20:30", "cron")
finally:
    conn.close()
jset("crawl_slot", {"slot": f"{DAY} 20:30", "days": 6, "at": f"{DAY} 20:30", "state": "ordered"})
big = mkrun(K("20:30"), status="in_progress", title="Обход full-6")
probes = [mkrun(K(f"{20 + (40 + 2 * i) // 60}:{(40 + 2 * i) % 60:02d}"), conclusion="cancelled",
                title="Обход proba-2") for i in range(20)]
API["runs"] = sorted([big] + probes, key=lambda r: r["created_at"], reverse=True)[:watch.RUNS_LIMIT]
tick(K("21:30"))
check("S6: 20 проб за час не вытесняют идущий плановый из списка (берём 100) — досрочного нет",
      ORDERS == [], ORDERS)
reset(K("21:30"), [probe])
order_of(f"{DAY} 20:30", 6)
conn = db.connect()
try:
    watch.add_order(conn, "full-6", f"{DAY} 20:30", f"{DAY} 20:30", "cron")
finally:
    conn.close()
jset("crawl_slot", {"slot": f"{DAY} 20:30", "days": 6, "at": f"{DAY} 20:30", "state": "ordered"})
many = [mkrun(K("20:40") + timedelta(seconds=20 * i), conclusion="cancelled", title="Обход proba-2")
        for i in range(watch.RUNS_LIMIT)]
API["runs"] = many                           # плановый выпал даже из 100
edge = last_id()
tick(K("21:30"))
check("S6: прогон заказа выпал даже из 100 последних → «не стартовал» не выносится, ждём",
      ORDERS == [] and alarms_after(edge) == [] and watch.is_open(book()[0]), (ORDERS, book()))

# находка 5: одна ждущая очередь GitHub
pending6 = mkrun(K("12:05"), status="pending", title="Обход full-6")
running2 = mkrun(K("12:00"), status="in_progress", title="Обход full-2")
pend_date = mkrun(K("12:05"), status="pending", title="Обход date-2026-11-12")
pend_site = mkrun(K("12:05"), status="pending", title="Обход site-nova.bg")
check("очередь: ждущий заказанный сбор (полный, дата, сайт) виден, идущий — нет; ждущая проба "
      "— не повод",
      watch.waiting_crawl([running2, pending6], SLUG) is pending6
      and watch.waiting_crawl([running2, pend_date], SLUG) is pend_date
      and watch.waiting_crawl([running2, pend_site], SLUG) is pend_site
      and watch.waiting_crawl([running2], SLUG) is None
      and watch.waiting_crawl([mkrun(K("12:06"), status="queued", title="Обход proba-2")], SLUG)
      is None)
reset(K("12:10"), [probe, running2, pending6])
setting("crawl_running", "")
saved_argv = sys.argv
sys.argv = ["request_crawl.py", "date", "2026-11-12", "--manual"]
try:
    code = rc.main()
finally:
    sys.argv = saved_argv
check("очередь: в ней ждёт полный обход → заявка скана даты не уходит (вытеснила бы его), "
      "строка объясняет",
      code == 3 and TAGS == [] and any(watch.QUEUE_BUSY in n for n in notes_after(last_id() - 1)),
      (code, TAGS))
pending2 = mkrun(K("20:25"), status="pending", title="Обход full-2")
reset(K("20:30"), [probe, mkrun(K("20:00"), status="in_progress", title="Обход full-2"), pending2])
mark("идёт", 10, "full-2")
check("очередь: плановой заявке приоритет — в очереди ждёт «2 дня», плановый на 6 уходит "
      "(вытеснит ждущий, и сторож сочтёт его заменённым, а не сорвавшимся)",
      planned(6) == [("days", "6")])
reset(K("12:00"), [probe])
button("date-2026-11-12", "12:00")
API["runs"] = [probe, mkrun(K("12:01"), ended=K("12:20"), conclusion="failure",
                            title="Обход date-2026-11-12"),
               mkrun(K("12:21"), status="in_progress", title="Обход full-2"),
               mkrun(K("12:22"), status="pending", title="Обход full-6")]
edge = last_id()
tick(K("12:30"))
check("очередь: скан даты сорвался, а в очереди ждёт полный → повтор ОТЛОЖЕН, не вытесняет его",
      ORDERS == [] and any("повтор отложен" in n for n in notes_after(edge))
      and book()[0].get("retry_deferred"), (ORDERS, notes_after(edge)))
API["runs"][-1] = dict(API["runs"][-1], status="in_progress")
API["runs"][-2] = finished(API["runs"][-2], K("12:40"))
tick(K("12:45"))
check("…очередь освободилась (полный пошёл) → отложенный повтор ушёл, ровно один",
      ORDERS == ["date-2026-11-12"], ORDERS)
tick(K("13:00"))
check("…и на следующих проверках второго повтора нет", ORDERS == ["date-2026-11-12"], ORDERS)
# вытеснение в очереди — не срыв
reset(K("16:00"), [probe])
button("full-2", "16:00")
conn = db.connect()
try:                                         # плановый 16:15 — заказ книги
    watch.add_order(conn, "full-6", f"{DAY} 16:15", f"{DAY} 16:15", "cron", at=K("16:15"))
finally:
    conn.close()
d2_wait = mkrun(K("16:01"), ended=K("16:16"), conclusion="cancelled", title="Обход full-2")
p6_live = mkrun(K("16:15") + timedelta(seconds=20), status="in_progress", title="Обход full-6")
API["runs"] = [probe, mkrun(K("15:30"), ended=K("16:40"), title="Обход full-6"), d2_wait, p6_live]
edge = last_id()
tick(K("16:45"))
check("очередь: ручной «2 дня» ждал и был вытеснен плановым на 6 → не срыв, повтора нет, "
      "строка «вытеснен … соберёт и эти дни»",
      ORDERS == [] and alarms_after(edge) == [] and book()[0].get("replaced") is True
      and any("вытеснен" in n for n in notes_after(edge)), (ORDERS, notes_after(edge)))
check("очередь: скан даты 12.11, вытесненный обходом на 6 от 10.11, — накрыт; 20.11 — нет",
      watch.order_covered("date-2026-11-12", (1, 6), K("16:15"))
      and not watch.order_covered("date-2026-11-20", (1, 6), K("16:15")))
# отметку живого сбора не снимаем
live = mkrun(K("12:00"), status="in_progress", title="Обход full-6")
check("--unlock: живой сбор на GitHub → отметку не снимать; его отмена подана → можно; "
      "GitHub молчит → нельзя",
      "живой сбор" in watch.unlock_refusal([probe, live], {}, SLUG)
      and watch.unlock_refusal([probe, live], {str(live["id"]): {}}, SLUG) == ""
      and "не ответил" in watch.unlock_refusal(watch.Runs.silent(), {}, SLUG))
reset(K("12:30"), [probe, live])
mark("идёт", 30, "full-6")
saved_argv = sys.argv
sys.argv = ["request_crawl.py", "date", "2026-11-12", "--force", "--unlock", "--locked"]
try:
    rc.main()
finally:
    sys.argv = saved_argv
check("--unlock у заявки сторожа при живом сборе: отметка «идёт full-6» осталась, "
      "заявка встала в очередь за ним",
      setting("crawl_running").endswith("|full-6") and TAGS == [("date", "2026-11-12")],
      (setting("crawl_running"), TAGS))

# находка 7: битая запись книги
reset(K("12:00"), [probe])
button("date-2026-11-12", "12:00")
setting(f"{watch.ORDER_PREFIX}bad-1", json.dumps({"id": "bad-1", "what": "date-2026-11-13",
                                                  "order": "не время"}))
setting(f"{watch.ORDER_PREFIX}bad-2", "{не json")
API["runs"] = [probe, mkrun(K("12:01"), ended=K("12:20"), title="Обход date-2026-11-12")]
edge = last_id()
ticks("12:30", "12:45", "13:00")
check("битые записи книги → по одной ТРЕВОГЕ (не каждые 15 мин), в карантин; остальные "
      "заказы разобраны",
      len(alarms_after(edge)) == 2 and setting(f"{watch.BAD_PREFIX}{watch.ORDER_PREFIX}bad-1")
      and not setting(f"{watch.ORDER_PREFIX}bad-1") and book()[0].get("done") is True,
      (notes_after(edge), book()))

# находка 8: заявка сторожа старта не ждёт — замок не держит минутами
reset(K("12:30"), [probe])
waited = []
watch.wait_for_start = lambda *a, **k: (waited.append(1) or ({"run_number": 0}, True))
saved_argv = sys.argv
sys.argv = ["request_crawl.py", "days", "6", "--force", "--unlock", "--locked", "--early-for=x"]
try:
    rc.main()
finally:
    sys.argv = saved_argv
check("заявка сторожа (--locked) старта не ждёт: тег ушёл, ожидания нет — его судит С4",
      TAGS == [("days", "6")] and waited == [], (TAGS, waited))
reset(K("16:15"), [probe])
order = []


def wait_records_lock(*a, **k):
    # ожидание старта плановой заявки идёт уже БЕЗ общего замка
    with watch.order_lock(0) as held:
        order.append(held)
    return {"run_number": 0}, True


watch.wait_for_start = wait_records_lock
planned(2)
watch.wait_for_start = fake_wait
check("плановая заявка: решение и тег — под замком, ожидание старта — уже без него",
      order == [True], order)

# ── сценарии третьей проверки 06.10 (N1–N9) и её находки ───────────────────
rule("сценарии-3", "сценарии третьей проверки 06.10")

# N1. прогон старого crawl.yml (без run-name: «Обход телесайтов») в день выкладки
old_named = {"display_title": "Обход телесайтов", "event": "workflow_dispatch",
             "created_at": "2026-11-10T18:30:20Z"}
check("N1: прогон без вида — ответ на полный заказ (answers, run_for), пока «unknown» в FULL_KINDS",
      watch.answers("full-6", old_named)
      and watch.run_for({"at": K("20:30"), "days": 6}, [old_named]) is not None)
reset(K("20:30"), [probe])
setting("crawl_request", f"обход 6 сут.|{DAY} 20:30")
setting("crawl_watch", json.dumps({"order": f"{DAY} 20:30"}))
setting("crawl_running", f"идёт|{int(time.time()) - 600}|20:31|full-6")
old_live = mkrun(K("20:30") + timedelta(seconds=20), status="in_progress", title="Обход телесайтов")
API["runs"] = [probe, old_live]
jset("crawl_slot", {"slot": f"{DAY} 20:30", "days": 6, "at": f"{DAY} 20:30", "state": "ordered"})
edge = last_id()
tick(K("20:45"))
check("N1: выкладка во время идущего планового старого вида → лишнего обхода нет",
      ORDERS == [] and alarms_after(edge) == [], (ORDERS, notes_after(edge)))
API["runs"] = [probe, finished(old_live, K("22:00"))]
tick(K("22:15"))
check("N1: …он кончился → заказ закрыт «дошёл», без досрочного и без тревоги",
      ORDERS == [] and alarms_after(edge) == [] and book()[0].get("done") is True,
      (ORDERS, notes_after(edge), book()))
check("N1: С6 прогон без вида тоже засчитывает (идёт — «жду итога»)",
      watch.plan_early(gap("16:15", 6), [probe, dict(old_live, created_at=Z(K("16:20")))],
                       K("16:30"), {}, None)[0] == "covered")

# N2. день выкладки: заливка ДО выкладки есть только в last_import_stamp
reset(K("16:00"), [probe])
watch.result_state, watch.subprocess = REAL_RESULT, NO_GIT
setting("last_import_stamp:results", utc_stamp(K("16:38")))      # «2 дня» влит до выкладки
conn = db.connect()
try:                                         # заливка «6 дней» — уже новым games_import
    watch.remember_import(conn, "results", utc_stamp(K("21:58")))
    db.set_setting(conn, "last_import_stamp:results", utc_stamp(K("21:58")))
    imported = watch.imported_stamps(conn, "full-2")
finally:
    conn.close()
check("N2: первая заливка после выкладки кладёт в список и прежнюю метку → «2 дня» (16:00–16:40) "
      "считается влитым, лишнего повтора нет",
      REAL_RESULT(TMP, K("16:00"), K("16:40"), "full-2", imported) == "picked", imported)
gi = (ROOT / "scripts" / "games_import.py").read_text(encoding="utf-8")
check("N2: games_import пишет список заливок ДО того, как перепишет last_import_stamp",
      gi.index("watch.remember_import(") < gi.index("db.set_setting(conn, stamp_key, stamp)"))
watch.subprocess = REAL_SUBPROCESS
watch.result_state = lambda root, start, end, what, imported, cache=None: (
    RESULT_ASKED.append((what, imported[-1] if imported else "")) or RESULT[0])

# N3. два повтора в одну проверку вытеснили бы друг друга в очереди
reset(K("12:00"), [probe])
button("date-2026-11-12", "12:00")
button("site-nova.bg", "12:02")
running6 = mkrun(K("11:50"), status="in_progress", title="Обход full-6")
base3 = [probe, running6,
         mkrun(K("12:00") + timedelta(seconds=5), ended=K("12:10"), conclusion="failure",
               title="Обход date-2026-11-12"),
         mkrun(K("12:02") + timedelta(seconds=5), ended=K("12:12"), conclusion="failure",
               title="Обход site-nova.bg")]
API["runs"] = list(base3)
edge = last_id()
tick(K("12:30"))
first = list(ORDERS)
check("N3: два коротких сорвались при идущем полном → за проверку уходит ОДИН повтор, второй "
      "отложен со строкой «уже ушла другая заявка повтора»",
      len(first) == 1 and any("уже ушла другая заявка повтора" in n for n in notes_after(edge)),
      (first, notes_after(edge)))
API["runs"] = base3 + [mkrun(K("12:30") + timedelta(seconds=15), status="pending",
                             title=f"Обход {w}") for w in first]
tick(K("12:45"))
check("N3: пока первый повтор ждёт очереди, второй не уходит (вытеснил бы его); тревог нет",
      ORDERS == first and alarms_after(edge) == [], (ORDERS, alarms_after(edge)))

# N4. очередь бережёт любой ждущий заказанный сбор
check("N4: в очереди ждёт скан даты → новая заявка (не плановая) не уходит",
      watch.QUEUE_BUSY in watch.queue_refusal(
          [running6, mkrun(K("12:05"), status="pending", title="Обход date-2026-11-12")], SLUG))

# N5. дни ручного «2 дня» уже собрал успешный «6 дней»
reset(K("16:00"), [probe])
button("full-2", "16:00")
API["runs"] = [probe, mkrun(K("16:00") + timedelta(seconds=10), ended=K("16:40"), title="Обход full-2"),
               mkrun(K("16:15") + timedelta(seconds=10), ended=K("17:50"), title="Обход full-6")]
RESULT[0] = "lost"
edge = last_id()
tick(K("18:00"))
check("N5: результат «2 дня» перекрыт, но его дни собрал успешный «6 дней» → повтора нет, "
      "строка «повтор не нужен», тревоги нет",
      ORDERS == [] and alarms_after(edge) == []
      and any("повтор не нужен" in n for n in notes_after(edge)), (ORDERS, notes_after(edge)))

# N6. «стоп = стоп»: ручной сбор, остановленный владельцем кнопкой
for what, at in (("full-6", "16:00"), ("date-2026-11-12", "16:00"), ("site-nova.bg", "16:00")):
    reset(K("16:00"), [probe])
    button(what, at)
    live = mkrun(K("16:00") + timedelta(seconds=10), status="in_progress", title=f"Обход {what}")
    API["runs"] = [probe, live]
    jset("crawl_cancel", {str(live["id"]): {"at": watch.when(K("16:20")), "number": 1,
                                            "alarmed": False, "by": "владелец"}})
    API["runs"] = [probe, finished(live, K("16:21"), "cancelled")]
    edge = last_id()
    tick(K("16:30"))
    check(f"N6: {what}, остановленный владельцем, → без повтора и без тревоги, строка "
          f"«остановил владелец», заказ закрыт",
          ORDERS == [] and alarms_after(edge) == [] and book()[0].get("stopped") is True
          and any("остановил владелец" in n for n in notes_after(edge)), (ORDERS, notes_after(edge)))
reset(K("16:00"), [probe])
button("full-6", "16:00")
live = mkrun(K("16:00") + timedelta(seconds=10), status="in_progress", title="Обход full-6")
jset("crawl_cancel", {str(live["id"]): {"at": watch.when(K("16:20")), "number": 1,
                                        "alarmed": False, "by": "сторож"}})
API["runs"] = [probe, finished(live, K("16:21"), "cancelled")]
tick(K("16:30"))
check("N6: тот же ручной, но остановил СТОРОЖ (завис) → это срыв: один повтор", ORDERS == [6], ORDERS)
reset(K("16:15"), [probe])
conn = db.connect()
try:
    watch.add_order(conn, "full-2", f"{DAY} 16:15", f"{DAY} 16:15", "cron", at=K("16:15"))
finally:
    conn.close()
setting("crawl_request", f"обход 2 сут.|{DAY} 16:15")
live = mkrun(K("16:15") + timedelta(seconds=10), status="in_progress", title="Обход full-2")
jset("crawl_cancel", {str(live["id"]): {"at": watch.when(K("16:20")), "number": 1,
                                        "alarmed": False, "by": "владелец"}})
API["runs"] = [probe, finished(live, K("16:21"), "cancelled")]
edge = last_id()
tick(K("16:30"))
check("N6: ПЛАНОВЫЙ, остановленный владельцем, — «стоп = стоп» (владелец 06.10): досрочного "
      "нет, слот не сорвавшийся, тревоги нет, строка «остановил владелец»",
      ORDERS == [] and alarms_after(edge) == [] and jget("crawl_missed") == {}
      and any("остановил владелец" in n for n in notes_after(edge))
      and book()[0].get("stopped") is True, (ORDERS, notes_after(edge), jget("crawl_missed")))
ticks("16:45", "17:00")
NOW[0] = K("20:30")
setting("crawl_running", "")
check("N6: …и на следующих проверках ничего не заказано, а следующий плановый 20:30 идёт по "
      "расписанию",
      ORDERS == [] and planned(6) == [("days", "6")], ORDERS)
reset(K("16:30"), [probe])
jset("crawl_missed", gap())
tick(K("16:30"))                             # досрочный на 6 за 16:15 вместо 20:30
early_live = mkrun(K("16:31"), status="in_progress", title="Обход full-6")
jset("crawl_cancel", {str(early_live["id"]): {"at": watch.when(K("16:40")), "number": 1,
                                              "alarmed": False, "by": "владелец"}})
API["runs"] = [probe, finished(early_live, K("16:41"), "cancelled")]
edge = last_id()
ticks("16:45", "17:00")
check("N6: ДОСРОЧНЫЙ, остановленный владельцем, → без тревоги и без новых заказов, строка "
      "«остановил владелец»",
      ORDERS == [6] and alarms_after(edge) == [] and jget("crawl_early").get("state") == "stopped"
      and any("остановил владелец" in n for n in notes_after(edge)),
      (ORDERS, notes_after(edge), jget("crawl_early")))
NOW[0] = K("20:30")
setting("crawl_running", "")
check("N6: …а плановый 20:30, который он должен был заменить, идёт по расписанию",
      planned(6) == [("days", "6")])

# N7. лёгкий список для ожидания старта и кнопок
asked_limits = []
saved_runs = watch.github_runs
watch.github_runs = lambda slug, limit=0, workflow="": (asked_limits.append(limit)
                                                        or watch.Runs([probe]))
REAL_WAIT({"at": K("12:00"), "days": 6}, SLUG, watch.FULL_KINDS, sleep=lambda s: None)
watch.forwarding({"at": K("12:00")}, SLUG, "btn-days-6-")
watch.github_runs = saved_runs
check("N7: ожидание старта и сверка пересылки берут 20 последних прогонов, не 100 "
      "(11 запросов за ожидание: 10 опросов и пересылка)",
      set(asked_limits) == {watch.RUNS_LIMIT_QUICK} and len(asked_limits) == 11, asked_limits)

# N8. повторный час 25.10: «GitHub молчит» с 03:10 второго прохода
reset(datetime(2026, 10, 25, 1, 10, tzinfo=timezone.utc), [])
edge = last_id()
tick(datetime(2026, 10, 25, 1, 10, tzinfo=timezone.utc))      # 03:10 зимнего
tick(datetime(2026, 10, 25, 1, 25, tzinfo=timezone.utc))      # 03:25 зимнего
check("N8: повторный час — 15 мин молчания GitHub не превращаются в «75 мин»: тревоги нет, "
      "отметка «с какого времени» — в UTC",
      alarms_after(edge) == [] and jget("crawl_silent").get("since") == "2026-10-25T01:10:00+00:00",
      (alarms_after(edge), jget("crawl_silent")))

# N9. день выкладки: прежний сторож уже повторял плановый, и повтор сорвался
reset(K("16:30"), [probe])
setting("crawl_request", f"обход 2 сут.|{DAY} 16:31")
setting("crawl_watch", json.dumps({"order": f"{DAY} 16:31", "reordered": True, "alarmed": True}))
API["runs"] = [probe, mkrun(K("16:31") + timedelta(seconds=10), ended=K("17:05"),
                            conclusion="failure", title="Обход full-2")]
jset("crawl_slot", {"slot": f"{DAY} 16:15", "days": 2, "at": f"{DAY} 16:15", "state": "ordered"})
edge = last_id()
tick(K("17:30"))
check("N9: на слот уже ушли заявка и повтор прежнего сторожа → третьего (досрочного) нет, "
      "одна ТРЕВОГА",
      ORDERS == [] and len(alarms_after(edge)) == 1, (ORDERS, notes_after(edge)))

# Н8. замена засчитывается только прогоном заказа из книги
reset(K("16:00"), [probe])
button("full-2", "16:00")
API["runs"] = [probe, mkrun(K("16:01"), ended=K("16:16"), conclusion="cancelled", title="Обход full-2"),
               mkrun(K("16:15") + timedelta(seconds=20), status="in_progress", title="Обход full-6")]
tick(K("16:45"))
check("Н8: ждущий «2 дня» вытеснен полным, запущенным НЕ сервером (его нет в книге) → это срыв: "
      "один повтор",
      ORDERS == [2] and not book()[0].get("replaced"), (ORDERS, book()))

# Н9. занятая база: скриптам — 30 с, страницам — как было
conn_web, conn_script = db.connect(), db.connect(db.BUSY_TIMEOUT_SCRIPT)
try:
    web_ms = conn_web.execute("PRAGMA busy_timeout").fetchone()[0]
    script_ms = conn_script.execute("PRAGMA busy_timeout").fetchone()[0]
finally:
    conn_web.close()
    conn_script.close()
src = {n: (ROOT / "scripts" / f"{n}.py").read_text(encoding="utf-8")
       for n in ("crawl_watch", "request_crawl", "games_import")}
check("Н9: сторож, заявка и заливка ждут занятую базу 30 с, страницы сайта — 5 с",
      web_ms == 5000 and script_ms == 30000
      and all("db.connect(db.BUSY_TIMEOUT_SCRIPT)" in t and "db.connect()" not in t
              for t in src.values()), (web_ms, script_ms))
import threading  # noqa: E402
locked = threading.Event()


def long_import():
    """Как заливка игр: одна долгая транзакция на запись (≈1 с)."""
    holder = db.connect()
    try:
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('busy-test', '1')")
        locked.set()
        time.sleep(1.0)
        holder.commit()
    finally:
        holder.close()


worker = threading.Thread(target=long_import)
worker.start()
locked.wait()
conn = db.connect(db.BUSY_TIMEOUT_SCRIPT)
try:
    t0 = time.perf_counter()
    db.set_setting(conn, "busy-test", "2")       # ждёт, пока «заливка» закончит
    waited_s = time.perf_counter() - t0
finally:
    conn.close()
worker.join()
check("Н9: запись скрипта дождалась чужой долгой транзакции (≈1 с), а не упала «database is locked»",
      setting("busy-test") == "2" and waited_s >= 0.5, waited_s)

# Н10. отметки «когда» в памяти — UTC ISO
reset(K("12:00"), [yday, mkrun(K("11:30"), status="in_progress", title="Обход proba-2")])
tick(K("12:00"))                             # зависшая проба — заявка отмены
cancel_at = next(iter(jget("crawl_cancel").values()), {}).get("at", "")
reset(K("12:15"), [yday, mkrun(K("11:30"), status="queued", title="Обход full-2")])
tick(K("12:15"))                             # ждёт очереди 45 мин, впереди никого
queue_last = next(iter(jget("crawl_queue").values()), {}).get("last", "")
check("Н10: «подана отмена» и «последний раз видели в очереди» — UTC ISO",
      cancel_at.endswith("+00:00") and queue_last.endswith("+00:00"), (cancel_at, queue_last))
reset(K("16:15"), [])
mark("идёт", 35, "full-6")
planned(2)                                   # GitHub молчит — слот сорвался
check("Н10: «когда сорвался слот» и «заявка пришла» — UTC ISO",
      jget("crawl_missed").get("at", "").endswith("+00:00")
      and jget("crawl_slot").get("at", "").endswith("+00:00"), (jget("crawl_missed"), jget("crawl_slot")))
check("Н10: старые киевские отметки памяти по-прежнему читаются",
      watch.moment(f"{DAY} 16:15") == K("16:15")
      and watch.moment("2026-10-25T01:10:00+00:00") == datetime(2026, 10, 25, 1, 10,
                                                                  tzinfo=timezone.utc))

# ── ночь 20:30 → 08:15 и запасной запуск по расписанию GitHub (06.10) ───────
rule("ночь", "утренний слот 08:15: ночь без досрочных, запасной запуск GitHub после утра")
check("ночь для досрочных — с 22:30 до утреннего слота 08:15 по Киеву",
      [watch.in_night(K(h)) for h in ("22:29", "22:30", "23:59", "00:00", "03:00", "08:14", "08:15",
                                      "12:00", "20:45")]
      == [False, True, True, True, True, True, False, False, False])
reset(K("20:30"), [probe])
setting("crawl_request", f"обход 6 сут.|{DAY} 20:30")
conn = db.connect()
try:
    watch.add_order(conn, "full-6", f"{DAY} 20:30", f"{DAY} 20:30", "cron", at=K("20:30"))
finally:
    conn.close()
jset("crawl_slot", {"slot": f"{DAY} 20:30", "days": 6, "at": f"{DAY} 20:30", "state": "ordered"})
late_fail = mkrun(K("20:31"), ended=K("22:40"), conclusion="failure", title="Обход full-6")
API["runs"] = [probe, late_fail]
edge = last_id()
ticks("22:45", "23:00", "23:15")
check("ночь: вечерний 20:30 упал в 22:40 → досрочный НЕ заказан (сайты до утра отдают вчерашние "
      "телесутки), тревоги нет, строка «его дни соберёт утренний плановый 08:15»",
      ORDERS == [] and alarms_after(edge) == [] and jget("crawl_missed").get("state") == "night"
      and any("ночь" in n and "08:15" in n for n in notes_after(edge)), (ORDERS, notes_after(edge)))
NOW[0] = K("08:15", NEXT)
setting("crawl_running", "")
check("…а утром 08:15 плановый на 6 уходит как обычно", planned(6) == [("days", "6")])
reset(K("20:30"), [probe])
setting("crawl_request", f"обход 6 сут.|{DAY} 20:30")
conn = db.connect()
try:
    watch.add_order(conn, "full-6", f"{DAY} 20:30", f"{DAY} 20:30", "cron", at=K("20:30"))
finally:
    conn.close()
jset("crawl_slot", {"slot": f"{DAY} 20:30", "days": 6, "at": f"{DAY} 20:30", "state": "ordered"})
API["runs"] = [probe, mkrun(K("20:31"), ended=K("21:50"), conclusion="failure", title="Обход full-6")]
tick(K("22:00"))
check("вечер до 22:30: 20:30 упал в 21:50 → досрочный на 6 в 22:00, утренний 08:15 он не заменяет "
      "(10 ч 15 мин > 4 ч 20 мин)",
      ORDERS == [6] and jget("crawl_early").get("replaces") == f"{NEXT} 08:15"
      and watch.covers_from(K("08:15", NEXT)) > K("22:00"), (ORDERS, jget("crawl_early")))
crawl_yml = (ROOT / ".github" / "workflows" / "crawl.yml").read_text(encoding="utf-8")
gh_cron = re.search(r'cron:\s*"(\d+) (\d+) \* \* \*"', crawl_yml)
gh_at = datetime(2026, 7, 10, int(gh_cron.group(2)), int(gh_cron.group(1)), tzinfo=timezone.utc)
gh_winter = gh_at.replace(month=1)
check("запасной запуск GitHub — после утреннего планового 08:15 с его возможным досрочным "
      "(≥ 11:00 Киева и летом, и зимой) и до 16:15 с запасом на обход (≤ 14:30)",
      all("11:00" <= x.astimezone(KYIV).strftime("%H:%M") <= "14:30" for x in (gh_at, gh_winter)),
      (gh_at.astimezone(KYIV), gh_winter.astimezone(KYIV)))
gh_run = mkrun(K("12:17"), status="in_progress", title="Обход по расписанию", event="schedule")
check("запуск по расписанию GitHub — свой вид: заказом не считается, очередь его не бережёт",
      watch.run_kind(gh_run) == ("schedule", 0)
      and not watch.answers("full-6", gh_run)
      and watch.waiting_crawl([dict(gh_run, status="pending")], SLUG) is None)

# ── итог: сколько обходов за сутки при устойчивой поломке ───────────────────
def bad_day(hang: bool) -> tuple[list, list, int, list]:
    """Сутки, в которые не удаётся НИ ОДИН обход: каждый либо проходит целиком
    и краснеет (hang=False), либо виснет до отмены (hang=True). Заявки идут
    по cron в слоты, сторож — каждые 15 минут. Возвращает (теги плановых
    заявок, заказы сторожа, число заявок отмены, тревоги)."""
    reset(K("08:15"), [yday])
    edge = last_id()
    spawned: list[dict] = []     # {created, days, id, ended, conclusion}
    plan_tags, cancel_tags = [], 0

    def spawn(days: int, at: datetime) -> None:
        _ids[0] += 1
        long = timedelta(minutes=85 if days == 6 else 35)
        spawned.append({"created": at, "days": days, "id": _ids[0],
                        "ended": None if hang else at + long, "conclusion": "failure"})

    def world(now: datetime) -> list[dict]:
        out, busy = [yday], False
        for s in spawned:
            if s["created"] > now:
                continue
            over = s["ended"] is not None and s["ended"] <= now
            status = "completed" if over else ("pending" if busy else "in_progress")
            busy = busy or not over
            out.append(mkrun(s["created"], status=status, conclusion=s["conclusion"],
                             title=f"Обход full-{s['days']}", ended=s["ended"] if over else None,
                             rid=s["id"]))
        return out

    now = K("08:15")
    while now <= K("04:00", NEXT):
        API["runs"] = world(now)
        NOW[0] = now
        setting("crawl_running", "")         # стук «закончил» / срок отметки
        for hhmm, days in watch.SCHEDULE:
            if now.strftime("%H:%M") == hhmm:
                sent = [x for x in planned(days) if x[0] == "days"]
                plan_tags += sent
                for _ in sent:
                    spawn(days, now + timedelta(minutes=1))
        seen_orders = len(ORDERS)
        TAGS.clear()
        tick(now)
        for kind_, rid in TAGS:
            if kind_ == "cancel":
                cancel_tags += 1
                for s in spawned:
                    if str(s["id"]) == rid:
                        s["ended"], s["conclusion"] = now + timedelta(minutes=2), "cancelled"
        for days in ORDERS[seen_orders:]:
            spawn(days, now + timedelta(minutes=1))
        now += timedelta(minutes=15)
    return plan_tags, list(ORDERS), cancel_tags, alarms_after(edge), notes_after(edge)


rule("итог", "худшие сутки: не удаётся ни один обход")
plans, orders, cancels, alarms, lines = bad_day(hang=False)
check("каждый обход проходит и краснеет → за сутки 3 плановых + 3 досрочных = 6 обходов, не больше",
      plans == [("days", "6"), ("days", "2"), ("days", "6")] and orders == [6, 6, 6],
      (plans, orders))
check("…и три ТРЕВОГИ — по одной на сорвавшийся слот", len(alarms) == 3, alarms)
plans, orders, cancels, alarms, lines = bad_day(hang=True)
check("каждый обход виснет → 3 плановых + 2 досрочных, каждому одна отмена (5), две ТРЕВОГИ: "
      "вечерний 20:30 виснет до 22:50 — досрочный за него уже ночью не заказывается",
      plans == [("days", "6"), ("days", "2"), ("days", "6")] and orders == [6, 6]
      and cancels == 5 and len(alarms) == 2, (plans, orders, cancels, alarms))
check("…вместо ночного досрочного — строка «ночью досрочно не заказываю, соберёт утренний 08:15»",
      any("ночь" in n and "08:15" in n for n in lines), lines[-5:])

# ── workflow: защита и вид прогона ──────────────────────────────────────────
rule("workflow", "queue.yml и crawl.yml")
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

# ── на каждое правило шапки app/watch.py есть проверка ──────────────────────
rule("шапка", "правила в шапке app/watch.py и проверки сходятся")
head = watch.__doc__
top = re.findall(r"^  ([ЗС]\d)\. ", head, re.M)
sub = ["С4" + letter for letter in re.findall(r"^      ([а-я])\) ", head, re.M)]
rules = [r for r in top if r != "С4"] + sub
missing = [r for r in rules if r not in COVERED]
check("в шапке 7 правил заявки, 6 правил сторожа и 5 веток С4",
      [r for r in top if r[0] == "З"] == [f"З{i}" for i in range(1, 8)]
      and [r for r in top if r[0] == "С"] == [f"С{i}" for i in range(1, 7)]
      and sub == ["С4а", "С4б", "С4в", "С4г", "С4д"], (top, sub))
check("на каждое правило шапки есть проверка с его номером", missing == [], missing)
memory = re.findall(r"^  (crawl_[a-z]+) — ", head, re.M)
check("в шапке описана вся память сторожа — те же записи, что стирает reset()",
      sorted(memory) == sorted(MEMORY), (memory, MEMORY))

print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, красных: {len(failed)}")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)

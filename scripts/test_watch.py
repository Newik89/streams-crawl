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
API = {"runs": [], "calls": 0}      # пустой список — «GitHub не ответил»
TAGS: list[tuple] = []
ORDERS: list[int] = []
PUSH_OK = [True]
RESULT = ["picked"]
NOW = [datetime(2026, 11, 10, 16, 15, tzinfo=KYIV)]


def fake_runs(slug, limit=0, workflow=""):
    API["calls"] += 1
    if not API["runs"]:
        return watch.Runs.silent()
    return watch.Runs(dict(r) for r in API["runs"])


def fake_wait(order, slug, kinds, **k):
    """Ожидание старта: прогон «появился» сразу, GitHub ответил."""
    return {"run_number": 0}, True


REAL_WAIT = watch.wait_for_start          # настоящее ожидание — для правила З7
watch.github_runs = fake_runs
watch.wait_for_start = fake_wait
watch.result_state = lambda root, started: RESULT[0]
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


def fake_order(days: int) -> str:
    """Как `request_crawl.py days N --force --unlock --locked`: снять отметку,
    записать заказ и отметку «заявка»."""
    ORDERS.append(days)
    conn = db.connect()
    try:
        crawl_hook.clear(conn)
        db.set_setting(conn, "crawl_request", f"обход {days} сут.|{watch.stamp(NOW[0])}")
        crawl_hook.mark(conn, "заявка", f"days-{days}")
    finally:
        conn.close()
    return "тест: заказ ушёл"


def refused_order(days: int) -> str:
    """Заявка сторожа не ушла: запись заказа не меняется."""
    ORDERS.append(days)
    return "тест: заявка не прошла"


REAL_ORDER = cw.order_crawl               # настоящий заказ сторожа — для правила З1
cw.order_crawl = fake_order
cw.pull = lambda: (0, "тест")

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


MEMORY = ("crawl_running", "crawl_request", "crawl_watch", "crawl_missed",
          "crawl_early", "crawl_cancel", "crawl_slot", "crawl_silent")


def reset(now: datetime, runs=()):
    """Чистый лист: память сторожа пуста, заглушки в исходном положении."""
    TAGS.clear()
    ORDERS.clear()
    API["calls"] = 0
    API["runs"] = list(runs)
    PUSH_OK[0] = True
    RESULT[0] = "picked"
    NOW[0] = now
    cw.order_crawl = fake_order
    cw.pull = lambda: (0, "тест")
    watch.wait_for_start = fake_wait
    for key in MEMORY:
        setting(key, "")


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
check("06:14 на 6 дней — плановый 06:15", watch.slot_for(K("06:14"), 6) == K("06:15"))
check("после 16:30 следующий плановый — 20:30 на 6", watch.next_slot(K("16:30")) == (K("20:30"), 6))
check("после 06:30 следующий — 16:15 на 2", watch.next_slot(K("06:30")) == (K("16:15"), 2))
check("после 20:45 следующий — 06:15 завтра на 6",
      watch.next_slot(K("20:45")) == (K("06:15", NEXT), 6))
check("последний прошедший слот: в 16:20 — 16:15, в 16:14 — 06:15, в 05:00 — вчерашний 20:30",
      watch.last_slot(K("16:20")) == (K("16:15"), 2) and watch.last_slot(K("16:14")) == (K("06:15"), 6)
      and watch.last_slot(K("05:00")) == (K("20:30", "2026-11-09"), 6))
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
check("чей заказ: досрочный / плановый / ручной",
      [watch.order_kind(s) for s in ({"early": True, "slot": "x"}, {"slot": "x"}, {"slot": ""}, {})]
      == ["early", "planned", "manual", "manual"])

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
    said = REAL_ORDER(6)
finally:
    cw.subprocess.run = real_run
check("сторож зовёт заявку с ключом --locked; заявка не уложилась в срок — проверка не падает",
      seen.get("cmd") == ["days", "6", "--force", "--unlock", "--locked"]
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
jset("crawl_watch", {"order": f"{DAY} 19:45", "slot": f"{DAY} 16:15", "early": True,
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

# ── З7. ждём старта ─────────────────────────────────────────────────────────
rule("З7", "ждём старта: тег повторяем один раз и только если GitHub отвечает")
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
reset(K("16:15"), [probe])                   # отвечает, но прогона на заявку нет
watch.wait_for_start = real_wait
edge = last_id()
sent = planned(2)
check("GitHub отвечает, прогона нет → тег повторён один раз",
      sent == [("days", "2"), ("days", "2")], sent)
check("…не стартовал и после повтора → строка «заказ сорвался, дальше решает сторож», ТРЕВОГИ ещё нет",
      any("не стартовал и после повтора" in n and "решает сторож" in n for n in notes_after(edge))
      and alarms_after(edge) == [], notes_after(edge))
check("…опросов семнадцать: десять и ещё семь (120 с) после повтора",
      API["calls"] == 17, API["calls"])
watch.wait_for_start = fake_wait
edge = last_id()
tick(K("16:30"))
check("…сторож на ближайшей проверке закрывает его как сорвавшийся и заказывает досрочный на 6",
      ORDERS == [6] and jget("crawl_early").get("for") == f"{DAY} 16:15"
      and alarms_after(edge) == [], (ORDERS, notes_after(edge)))
reset(K("16:15"), [mkrun(K("16:14"), status="in_progress", title="Обход proba-2")])
watch.wait_for_start = real_wait
mark("идёт", 1, "proba-2")
check("в списке только проба минутой раньше — она не ответ на заявку по дням: тег повторён",
      planned(2) == [("days", "2"), ("days", "2")])
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


def crash_after_push(days):
    fake_order(days)
    raise KeyboardInterrupt("перезагрузка")


def crash_before_push(days):
    ORDERS.append(days)
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
      and jget("crawl_watch").get("early") is True
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
q10 = mkrun(K("11:50"), status="queued", title="Обход full-2")
check("в очереди 25 мин, впереди никого → отменить; 10 мин — нет",
      cancels_for([q25], K("12:00")) == [str(q25["id"])] and cancels_for([q10], K("12:00")) == [])
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
      notes_after(edge) == [] and not jget("crawl_watch").get("done"), notes_after(edge))
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
      not jget("crawl_watch").get("done") and notes_after(edge) == [],
      (jget("crawl_watch"), notes_after(edge)))

# ── С4б. готов, а стук не дошёл ─────────────────────────────────────────────
rule("С4б", "текущий заказ: готов, стук не дошёл — забираем сами")
done6 = mkrun(K("06:16"), ended=K("07:40"), title="Обход full-6")
reset(K("08:00"), [yday, done6])
order_of(f"{DAY} 06:15", 6)
RESULT[0] = "pending"
pulled = []
cw.pull = lambda: (pulled.append(1) or (0, "тест"))
tick(K("08:00"))
check("готов, результат на GitHub, на сервере нет → забирает сам и закрывает заказ",
      pulled == [1] and jget("crawl_watch").get("done") is True, jget("crawl_watch"))
reset(K("08:00"), [yday, done6])
order_of(f"{DAY} 06:15", 6)
RESULT[0] = "pending"
pulled = []
cw.pull = lambda: (pulled.append(1) or (1, "тест: не вышло"))
edge = last_id()
ticks("08:00", "08:15", "08:30", "08:45")
check("забор не удаётся → после второй неудачи одна ТРЕВОГА, но пробовать продолжает",
      len(pulled) == 4 and len(alarms_after(edge)) == 1
      and "забрать его не вышло" in alarms_after(edge)[0], (pulled, notes_after(edge)))
cw.pull = lambda: (pulled.append(1) or (0, "тест"))
tick(K("09:00"))
check("…забор наконец удался → заказ закрыт", jget("crawl_watch").get("done") is True)

# ── С4в. готов и забран ─────────────────────────────────────────────────────
rule("С4в", "текущий заказ: готов и забран — закрываем")
reset(K("08:00"), [yday, done6])
order_of(f"{DAY} 06:15", 6)
edge = last_id()
ticks("08:00", "08:15")
check("готов и забран по стуку → одна строка, заказ закрыт, заказов нет",
      ORDERS == [] and [n for n in notes_after(edge) if "забран по стуку" in n] == notes_after(edge)
      and len(notes_after(edge)) == 1 and jget("crawl_watch").get("done") is True, notes_after(edge))

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
      jget("crawl_watch").get("early") is True
      and jget("crawl_watch").get("slot") == f"{DAY} 16:15", jget("crawl_watch"))
API["runs"] = [probe, fail2, mkrun(K("16:31"), ended=K("16:50"), conclusion="failure",
                                   title="Обход full-6")]
edge = last_id()
ticks("17:00", "17:15", "17:30")
check("ДОСРОЧНЫЙ тоже упал → одна ТРЕВОГА и ни одного нового заказа (на слот — один заказ сторожа)",
      ORDERS == [6] and len(alarms_after(edge)) == 1, (ORDERS, notes_after(edge)))
check("…тревога называет плановый, который действительно пойдёт следующим (20:30)",
      "досрочный обход тоже не прошёл" in alarms_after(edge)[0]
      and "Следующий плановый — 20:30 (6 сут.)" in alarms_after(edge)[0], notes_after(edge))
NOW[0] = K("20:30")
setting("crawl_running", "")
check("…а в 20:30 плановый на 6 идёт как обычно", planned(6) == [("days", "6")])
reset(K("16:30"), [probe])
order_of(f"{DAY} 16:15", 2)
tick(K("16:30"))
check("ПЛАНОВЫЙ 16:15 не стартовал → тоже сразу досрочный на 6, без повтора на 2",
      ORDERS == [6] and jget("crawl_early").get("for") == f"{DAY} 16:15", ORDERS)
edge = last_id()
ticks("16:45", "17:00")
check("…ДОСРОЧНЫЙ не стартовал → одна ТРЕВОГА, заказов больше нет",
      ORDERS == [6] and len(alarms_after(edge)) == 1, (ORDERS, notes_after(edge)))
hung = mkrun(K("06:16"), status="in_progress", title="Обход full-6")
hung_off = finished(hung, K("08:42"), "cancelled")
reset(K("08:40"), [yday, hung])
order_of(f"{DAY} 06:15", 6)
edge = last_id()
calls = tick(K("08:40"))
check("ПЛАНОВЫЙ на 6 дней идёт 144 мин (> 140) → заявка отмены с номером прогона",
      TAGS == [("cancel", str(hung["id"]))] and calls == 1, (TAGS, calls))
check("…и в той же проверке — досрочный на 6, а не повтор («отменить зависшее и СРАЗУ заказать»)",
      ORDERS == [6] and jget("crawl_early").get("for") == f"{DAY} 06:15"
      and jget("crawl_watch").get("early") is True, (ORDERS, jget("crawl_early")))
check("…строка «завис … отменяю его, вместо него … досрочно»",
      any("завис" in n and "отменяю его" in n and "досрочно" in n for n in notes_after(edge)),
      notes_after(edge))
early_run = mkrun(K("08:41"), status="pending", title="Обход full-6")
API["runs"] = [yday, hung, early_run]
edge = last_id()
tick(K("08:45"))
API["runs"] = [yday, hung_off, dict(early_run, status="in_progress")]
tick(K("08:55"))
check("…отмена подтверждена, досрочный, ждавший за зависшим, идёт → второго заказа и тревог нет",
      ORDERS == [6] and len(TAGS) == 1 and alarms_after(edge) == []
      and any("остановлен" in n for n in notes_after(edge)), (ORDERS, TAGS, notes_after(edge)))
hung_e = mkrun(K("08:41"), status="in_progress", title="Обход full-6")
reset(K("11:10"), [yday, hung_off, hung_e])
order_of(f"{DAY} 08:40", 6)
jset("crawl_watch", {"order": f"{DAY} 08:40", "slot": f"{DAY} 06:15", "early": True})
jset("crawl_early", early_mem(for_="06:15", replaces="16:15", ordered="08:40"))
edge = last_id()
tick(K("11:10"))
check("ДОСРОЧНЫЙ идёт 148 мин → заявка отмены и сразу ТРЕВОГА, заказов нет",
      TAGS == [("cancel", str(hung_e["id"]))] and ORDERS == [] and len(alarms_after(edge)) == 1
      and "Следующий плановый — 16:15 (2 сут.)" in alarms_after(edge)[0],
      (TAGS, ORDERS, notes_after(edge)))
API["runs"] = [yday, hung_off, finished(hung_e, K("11:12"), "cancelled")]
ticks("11:25", "11:40", "11:55")
check("…дальше тихо: одна тревога на досрочный, ни заказов, ни новых отмен",
      ORDERS == [] and len(TAGS) == 1 and len(alarms_after(edge)) == 1, (ORDERS, TAGS, notes_after(edge)))
NOW[0] = K("16:15")
setting("crawl_running", "")
check("…а в 16:15 плановый на 2 идёт как обычно", planned(2) == [("days", "2")])
e_run = mkrun(K("19:46"), status="in_progress", title="Обход full-6")
reset(K("20:30"), [probe, e_run])
order_of(f"{DAY} 19:45", 6)
jset("crawl_watch", {"order": f"{DAY} 19:45", "slot": f"{DAY} 16:15", "early": True})
jset("crawl_early", early_mem(ordered="19:45"))
mark("идёт", 44, "full-6")
planned(6)                                   # З3: слот пропущен, досрочный ещё идёт
API["runs"] = [probe, finished(e_run, K("20:50"), "failure")]
setting("crawl_running", "")
edge = last_id()
ticks("21:00", "21:15", "21:30")
check("ДОСРОЧНЫЙ упал уже ПОСЛЕ слота, который пропустили ради него → одна ТРЕВОГА, заказов нет",
      ORDERS == [] and len(alarms_after(edge)) == 1, (ORDERS, notes_after(edge)))
check("…тревога правдива: 20:30 остался без обхода, следующий плановый — 06:15",
      "Плановый 20:30 был пропущен" in alarms_after(edge)[0]
      and "Следующий плановый — 06:15 (6 сут.)" in alarms_after(edge)[0]
      and "20:30 пойдёт" not in alarms_after(edge)[0], notes_after(edge))
mfail = mkrun(K("13:01"), ended=K("13:10"), conclusion="failure", title="Обход full-6")
reset(K("13:15"), [probe, mfail])
order_of(f"{DAY} 13:00", 6)
tick(K("13:15"))
check("РУЧНОЙ заказ 13:00 упал → один повтор той же глубины, досрочного нет",
      ORDERS == [6] and jget("crawl_early") == {} and jget("crawl_watch").get("reordered") is True,
      (ORDERS, jget("crawl_early"), jget("crawl_watch")))
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
      ORDERS == [6] and jget("crawl_watch").get("reordered") is True, (ORDERS, jget("crawl_watch")))
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
jset("crawl_watch", {"order": f"{DAY} 16:45", "reordered": True, "slot": f"{DAY} 16:15"})
ticks("17:30", "17:45")
check("память прежней версии (плановому уже делали повтор, и он упал) → один досрочный на 6, не больше",
      ORDERS == [6] and jget("crawl_early").get("replaces") == f"{DAY} 20:30", ORDERS)

# ── С4д. заказ состарился ───────────────────────────────────────────────────
rule("С4д", "текущий заказ за 6 часов так и не закрыт")
reset(K("13:00"), [yday])
order_of(f"{DAY} 06:15", 6)
jset("crawl_slot", {"slot": f"{DAY} 06:15", "days": 6, "at": f"{DAY} 06:15", "state": "ordered"})
jset("crawl_watch", {"order": f"{DAY} 06:15", "slot": f"{DAY} 06:15"})
edge = last_id()
ticks("13:00", "13:15")
check("заказу 6 ч 45 мин, он не закрыт, прогона в списке нет → одна ТРЕВОГА, заказов нет",
      ORDERS == [] and len(alarms_after(edge)) == 1 and "так и не дошёл" in alarms_after(edge)[0]
      and jget("crawl_watch").get("failed") is True, (ORDERS, notes_after(edge)))
reset(K("13:00"), [yday, done6])
order_of(f"{DAY} 06:15", 6)
jset("crawl_slot", {"slot": f"{DAY} 06:15", "days": 6, "at": f"{DAY} 06:15", "state": "ordered"})
jset("crawl_watch", {"order": f"{DAY} 06:15", "slot": f"{DAY} 06:15"})
edge = last_id()
tick(K("13:00"))
check("заказ состарился, но результат на сервере → закрыт молча",
      notes_after(edge) == [] and jget("crawl_watch").get("done") is True, notes_after(edge))
reset(K("23:00"), [yday])
order_of(f"{DAY} 16:30", 6)
jset("crawl_slot", {"slot": f"{DAY} 20:30", "days": 6, "at": f"{DAY} 20:30", "state": "skipped"})
jset("crawl_early", early_mem(skipped=True))
jset("crawl_watch", {"order": f"{DAY} 16:30", "slot": f"{DAY} 16:15", "early": True})
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
check("слот 06:15 пропал, а узнали через 8 ч 45 мин → одна ТРЕВОГА «поздно», заказа нет",
      ORDERS == [] and len(alarms_after(edge)) == 1 and "06:15" in alarms_after(edge)[0]
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
reset(K("16:45"), [probe, mkrun(K("16:16"), status="in_progress", title="Обход full-2")])
jset("crawl_slot", {"slot": f"{DAY} 16:15", "days": 2, "at": f"{DAY} 16:15", "state": "started"})
tick(K("16:45"))
check("заявку оборвали, но тег успел уйти и обход идёт → досрочный не нужен",
      ORDERS == [] and jget("crawl_missed").get("state") == "covered", (ORDERS, jget("crawl_missed")))
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
      mem.get("state") == "done" and mem.get("started") == f"{DAY} 16:31" and mem.get("run"), mem)
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
reset(K("06:15"), [])
edge = last_id()
mark("идёт", 35, "full-6")
planned(6)
API["runs"] = [probe]
tick(K("06:30"))
early = jget("crawl_early")
check("сорвался 06:15 (6 дней) → в 06:30 заказ на 6 дней; ближайший плановый — 16:15 (2 дня)",
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
check("сорвался 20:30 → в 20:45 заказ на 6 дней; ближайший плановый — 06:15 завтра",
      ORDERS == [6] and early.get("replaces") == f"{NEXT} 06:15", early)
API["runs"] = [probe, mkrun(K("20:46"), ended=K("22:10"), title="Обход full-6")]
tick(K("22:30"))
NOW[0] = K("06:15", NEXT)
setting("crawl_running", "")
check("…утром 06:15 плановый на 6 идёт как обычно (досрочный был за 9 часов)",
      planned(6) == [("days", "6")])
reset(K("16:30"), [probe, mkrun(K("16:20"), status="in_progress", title="Обход full-6")])
jset("crawl_missed", gap())
tick(K("16:30"))
check("на GitHub уже идёт полный на 6 → досрочный не заказываем (covered)",
      ORDERS == [] and jget("crawl_missed").get("state") == "covered")
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
jset("crawl_watch", {"order": f"{DAY} 15:00", "slot": ""})
mark("идёт", 74, "full-6")
planned(2)
API["runs"] = [probe, mkrun(K("15:01"), ended=K("16:25"), title="Обход full-6")]
setting("crawl_running", "")
edge = last_id()
tick(K("16:30"))
check("16:15 отложили, а шедший обход на 6 к 16:30 успешно закончился → второй не заказываем (collected)",
      ORDERS == [] and jget("crawl_missed").get("state") == "collected"
      and any("уже успешно завершился" in n for n in notes_after(edge)),
      (ORDERS, jget("crawl_missed"), notes_after(edge)))
reset(K("16:30"), [probe])                   # прогона уже нет в списке последних
order_of(f"{DAY} 15:30", 6)
jset("crawl_watch", {"order": f"{DAY} 15:30", "slot": "", "done": True})
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


# ── итог: сколько обходов за сутки при устойчивой поломке ───────────────────
def bad_day(hang: bool) -> tuple[list, list, int, list]:
    """Сутки, в которые не удаётся НИ ОДИН обход: каждый либо проходит целиком
    и краснеет (hang=False), либо виснет до отмены (hang=True). Заявки идут
    по cron в слоты, сторож — каждые 15 минут. Возвращает (теги плановых
    заявок, заказы сторожа, число заявок отмены, тревоги)."""
    reset(K("06:15"), [yday])
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

    now = K("06:15")
    while now <= K("02:00", NEXT):
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
    return plan_tags, list(ORDERS), cancel_tags, alarms_after(edge)


rule("итог", "худшие сутки: не удаётся ни один обход")
plans, orders, cancels, alarms = bad_day(hang=False)
check("каждый обход проходит и краснеет → за сутки 3 плановых + 3 досрочных = 6 обходов, не больше",
      plans == [("days", "6"), ("days", "2"), ("days", "6")] and orders == [6, 6, 6],
      (plans, orders))
check("…и три ТРЕВОГИ — по одной на сорвавшийся слот", len(alarms) == 3, alarms)
plans, orders, cancels, alarms = bad_day(hang=True)
check("каждый обход виснет → те же 3 плановых + 3 досрочных, каждому одна отмена (6), три ТРЕВОГИ",
      plans == [("days", "6"), ("days", "2"), ("days", "6")] and orders == [6, 6, 6]
      and cancels == 6 and len(alarms) == 3, (plans, orders, cancels, alarms))

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

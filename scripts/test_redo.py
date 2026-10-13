# -*- coding: utf-8 -*-
r"""Проверки дозабора упавших адресов — схема сбоев, шаг 5 (12.10.2026).

Правила Д1–Д9 — в шапке `app/redo.py`. Имя каждой проверки начинается с
номера правила: `[Д3] ночью не заказываем …`; в конце файл сам сверяет,
что на каждое правило шапки есть хотя бы одна проверка.

В сеть не ходит и ничего не заказывает: список прогонов GitHub, тег-заявка,
заказ обхода, забор и скачивание страниц подменены заглушками; часы сторожа
ставятся нужные. Базы — временные, в своей папке. Запуск:

    python scripts/test_redo.py

Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="redo-test-"))
WATCH_DB = TMP / "watch.db"
os.environ["STREAMS_DB"] = str(WATCH_DB)

from app import channel_owner, crawl_hook, db, fetch, miss, redo, store, trigger, watch  # noqa: E402
import fail_reason  # noqa: E402

SLUG = "Newik89/streams-crawl"
KYIV = watch.KYIV
DAY = "2026-11-10"            # вторник, как в test_watch.py
NEXT = "2026-11-11"

# ── заглушки: ни GitHub, ни тегов, ни заказов ───────────────────────────────
API = {"runs": []}            # пустой список — «GitHub не ответил»
TAGS: list[tuple] = []
ORDERS: list[str] = []
RESULT = ["picked"]
NOW = [datetime(2026, 11, 10, 10, 0, tzinfo=KYIV)]


def fake_runs(slug, limit=0, workflow=""):
    if not API["runs"]:
        return watch.Runs.silent()
    return watch.Runs(dict(r) for r in API["runs"])


watch.github_runs = fake_runs
watch.result_state = lambda root, start, end, what, imported, cache=None: RESULT[0]
trigger.push_request_tag = lambda kind, value: (TAGS.append((kind, value)) or (True, "тест"))
trigger._repo_slug = lambda: SLUG
db.init_db()


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cw = load("crawl_watch")
rc = load("request_crawl")
cf = load("crawl_fetch")
cw._now = lambda: NOW[0]
rc._now = lambda: NOW[0]
RESULTS_DIR = TMP / "results"
RESULTS_DIR.mkdir()
cw.RESULTS = RESULTS_DIR


def fake_order(kind: str, value: str, mark: str = "") -> str:
    """Как `request_crawl.py <kind> <value> --force --unlock --locked <mark>`:
    заказ — в книгу с пометкой сторожа. В ORDERS — `<kind>-<value>`."""
    ORDERS.append(f"{kind}-{value}")
    conn = db.connect()
    try:
        stamp_ = watch.stamp(NOW[0])
        what = f"full-{value}" if kind == "days" else f"{kind}-{value}"
        if kind == "days":
            db.set_setting(conn, "crawl_request", f"обход {value} сут.|{stamp_}")
        name, _, arg = mark[2:].partition("=")
        extra = {"redo-of": {"redo_of": arg}, "early-for": {"early": True},
                 "retry-of": {"retry_of": arg, "reordered": True},
                 "reparse-of": {"reparse_of": arg}}.get(name, {})
        watch.add_order(conn, what, stamp_, arg if name == "early-for" else "",
                        "сторож", at=NOW[0], **extra)
    finally:
        conn.close()
    return "тест: заказ ушёл"


def refused_order(kind: str, value: str, mark: str = "") -> str:
    """Заявка сторожа не ушла: ни заказа, ни записи в книге."""
    ORDERS.append(f"{kind}-{value}")
    return "тест: заявка не прошла"


cw.order_crawl = fake_order
cw.pull = lambda: "тест: забор запущен"

# ── проверки по правилам ────────────────────────────────────────────────────
passed, failed = 0, []
TAG = ["основа"]
COVERED: set[str] = set()


def rule(tag: str, title: str) -> None:
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


_ids = [38800000000]


def mkrun(created: datetime, status="completed", conclusion="success",
          title="Обход full-6", ended: datetime | None = None):
    """Прогон, как его отдаёт API GitHub (поля — как в test_watch.py)."""
    _ids[0] += 1
    rid = _ids[0]
    return {"id": rid, "run_number": rid % 1000, "event": "workflow_dispatch",
            "status": status, "conclusion": conclusion if status == "completed" else None,
            "display_title": title, "name": title, "path": ".github/workflows/crawl.yml",
            "repository": {"full_name": SLUG},
            "created_at": Z(created), "run_started_at": Z(created),
            "updated_at": Z(ended or created)}


def finished(run: dict, ended: datetime, conclusion="success") -> dict:
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


def book() -> list[dict]:
    conn = db.connect()
    try:
        return watch.load_orders(conn)
    finally:
        conn.close()


def record(rec_id: str) -> dict:
    return next((r for r in book() if r["id"] == rec_id), {})


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


MEMORY = ("crawl_running", "crawl_request", "crawl_missed", "crawl_early", "crawl_cancel",
          "crawl_queue", "crawl_slot", "crawl_silent", crawl_hook.FAIL_MEMORY)


def reset(runs=()):
    """Чистый лист: память и книга пусты, заглушки в исходном положении."""
    TAGS.clear()
    ORDERS.clear()
    API["runs"] = list(runs)
    RESULT[0] = "picked"
    cw.order_crawl = fake_order
    for key in MEMORY:
        setting(key, "")
    conn = db.connect()
    try:
        for prefix in (watch.ORDER_PREFIX, watch.BAD_PREFIX, "import_stamps:"):
            conn.execute("DELETE FROM settings WHERE substr(key, 1, ?) = ?",
                         (len(prefix), prefix))
        conn.commit()
    finally:
        conn.close()
    for name in ("report.json", "games.json"):
        (RESULTS_DIR / name).unlink(missing_ok=True)


def tick(now: datetime) -> None:
    """Одна проверка сторожа в `now`. Плановая заявка на последний слот
    «приходила» (С5 молчит): дозабор проверяется сам по себе."""
    NOW[0] = now
    at, days = watch.last_slot(now - timedelta(minutes=watch.SLOT_AUDIT_MINUTES))
    jset("crawl_slot", {"slot": watch.stamp(at), "days": days, "at": watch.when(now),
                        "state": "ordered"})
    conn = db.connect()
    try:
        cw.tick(conn, now)
    finally:
        conn.close()


def done_order(run: dict, at: str = "08:15", days: int = 6, slot: bool = True,
               day: str = DAY, **extra) -> dict:
    """Книга: полный заказ в `at` (плановый — со слотом), его прогон `run`
    дошёл и забран сервером (done)."""
    conn = db.connect()
    try:
        rec = watch.add_order(conn, f"full-{days}", f"{day} {at}",
                              f"{day} {at}" if slot else "", "cron" if slot else "кнопка",
                              at=K(at, day), **extra)
        rec["done"] = True
        watch.save_order(conn, rec)
    finally:
        conn.close()
    return rec


def server_has(run: dict, rows: list[dict], collected: datetime | None = None,
               run_field: bool = True) -> None:
    """На «сервере» лежит результат сбора `run`: results/report.json и
    games.json одного коммита (метка «собрано» — UTC, до минуты)."""
    report = {"строки": rows, "дозор": {"liveonsat.com": {}}}
    if run_field:
        report["прогон"] = str(run["id"])
    made = collected or (watch._utc(run["updated_at"]) - timedelta(minutes=10))
    (RESULTS_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False),
                                             encoding="utf-8")
    (RESULTS_DIR / "games.json").write_text(json.dumps(
        {"собрано": made.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")}),
        encoding="utf-8")


def row(n: int, verdict: str = "не открылась", why: str = "HTTP 503",
        domain: str = "") -> dict:
    domain = domain or f"s{n}.test"
    return {"domain": domain, "channel": f"Канал {n}", "day": DAY, "locale": "en-GB",
            "url": f"https://{domain}/tv?d={n}", "browser": False, "post": None,
            "warmup": "", "post_json": None, "headers": None,
            "итог": verdict, "почему": why, "байт": 0, "меток времени": 0, "чем": "requests"}


def ok(n: int) -> dict:
    return row(n, "расписание есть", "")


def down(n: int) -> dict:
    return row(n, why="HTTP 503; браузер: HTTP 502")


def net(n: int) -> dict:
    return row(n, why="ConnectTimeout: timed out; браузер: Timeout 60000ms exceeded")


def ban(n: int) -> dict:
    return row(n, why="HTTP 403; браузер: HTTP 403")


def redo_orders() -> list[str]:
    return [o for o in ORDERS if o.startswith("redo-")]


# ════════════════════════════════════════════════════════════════════════════
rule("Д1", "кто и после чего: только после ДОШЕДШЕГО полного сбора")
check("дозабор бывает после дошедшего планового, досрочного и ручного полного",
      [redo.eligible(k, {"done": True}) for k in ("planned", "early", "manual")] == [True] * 3)
check("…не после сорвавшегося, не после скана даты, сайта, сервера, переразбора и самого дозабора",
      not redo.eligible("planned", {"failed": True})
      and [redo.eligible(k, {"done": True}) for k in ("date", "site", "server", "reparse", "redo")]
      == [False] * 5)
check("…и не второй раз: у сбора уже есть пометка redo", not redo.eligible("planned", {"done": True, "redo": "заказан"}))
morning = mkrun(K("08:16"), ended=K("09:50"))
reset([morning])
failed_rec = done_order(morning)
jset(watch.order_key(failed_rec), dict(failed_rec, done=False, failed=True))
server_has(morning, [down(1), net(2), ok(3)])
tick(K("11:00"))
check("сорвавшийся сбор с упавшими адресами — дозабора нет (его ведёт таблица RECOVERY, как раньше)",
      redo_orders() == [], ORDERS)
reset([morning])
conn = db.connect()
date_rec = watch.add_order(conn, "date-2026-11-12", f"{DAY} 08:15", "", "кнопка", at=K("08:15"))
watch.save_order(conn, dict(date_rec, done=True))
conn.close()
server_has(morning, [down(1)])
tick(K("11:00"))
check("дошедший скан даты — дозабора нет", redo_orders() == [], ORDERS)

# ════════════════════════════════════════════════════════════════════════════
rule("Д2", "что дозабирать: только down/net этого сбора; закрывших — никогда")
check("класс строки: открылась — пусто; 403/429/заглушка — ban; 5xx — down; прочее — net",
      [redo.row_class(r) for r in (ok(1), ban(2), row(3, "заглушка защиты", "cloudflare"),
                                   row(4, why="HTTP 429"), row(5, why="HTTP 520"), down(6), net(7),
                                   row(8, why="NameResolutionError: DNS"))]
      == ["", "ban", "ban", "ban", "down", "down", "net", "net"])
check("не берём: страницу защиты с кодом 5xx, ответ 4xx (нет страницы), сайт дозора",
      [redo.skip_reason(r, {"liveonsat.com"}) for r in (
          row(1, why="HTTP 503, защита: cloudflare"), row(2, why="HTTP 404; браузер: HTTP 404"),
          row(3, why="ConnectTimeout", domain="www.liveonsat.com"), down(4), net(5))]
      == ["страница защиты", "ответ 4xx", "сайт дозора", "", ""])
rows_mix = [ok(1), down(2), ban(3), net(4), row(5, why="HTTP 503, защита: imperva"), down(6)]
choice = redo.pick({"строки": rows_mix})
check("отбор: по порядку отчёта только down/net, с номерами строк; не взятые — с причиной",
      choice.index == [1, 3, 5] and choice.total == 3 and not choice.mass
      and choice.skipped == {"закрыт (защита, 403/429)": 1, "страница защиты": 1}, choice)
check("причина провала (`fail_reason.classify_rows`) считает тем же классом строки — как и раньше",
      "redo.row_class" in inspect.getsource(fail_reason.classify_rows)
      and fail_reason.classify_rows([ban(1), ban(2), down(3)]) == "fetch-ban"
      and fail_reason.classify_rows([down(1), down(2), net(3)]) == "fetch-down"
      and fail_reason.classify_rows([net(1), net(2), ban(3)]) == "fetch-net"
      and fail_reason.classify_rows([]) == "plan")
check("битый отчёт отбор не роняет: не словарь, строки не списком, строка не словарь или без адреса",
      redo.pick([1, 2]).total == 0 and redo.pick({"строки": "x"}).total == 0
      and redo.pick({"строки": ["x", 5, None, dict(down(1), url=None), down(2)], "дозор": [1]}).index == [4]
      and redo.pick({"строки": ["x", 5, dict(down(1), url=None)]}).skipped == {"строка отчёта битая": 3}
      and redo.row_class("x") == "" and redo.pick(None).total == 0)
check("отбор — ОДНА функция на сервер и GitHub: её зовут и сторож, и crawl_fetch --redo",
      "redo.pick(" in inspect.getsource(cw.redo_facts)
      and "redo.pick(" in inspect.getsource(cf.redo_fetch))
lo, hi = K("08:16"), K("09:50")
games_ok = {"собрано": K("09:40").astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")}
check("отчёт на сервере — того ли прогона: номер прогона и «собрано» в окне хода",
      redo.same_run({"прогон": "5"}, games_ok, 5, lo, hi) == ""
      and "другого прогона" in redo.same_run({"прогон": "6"}, games_ok, 5, lo, hi)
      and "другим прогоном" in redo.same_run({}, {"собрано": "2026-11-10 09:30"}, 5, lo, hi)
      and "нет" in redo.same_run(None, None, 5, lo, hi)
      and redo.same_run({}, games_ok, 5, lo, hi) == "")       # старый отчёт без номера
reset([morning])
rec = done_order(morning)
other = mkrun(K("10:30"), ended=K("10:40"), title="Обход full-2")
server_has(other, [down(1), net(2)])
edge = last_id()
tick(K("11:00"))
check("на сервере отчёт ДРУГОГО прогона → дозабор не заказываю, молча; по сбору решено",
      redo_orders() == [] and notes_after(edge) == []
      and "другого прогона" in record(rec["id"]).get("redo", ""), (ORDERS, record(rec["id"])))
reset([morning])
rec = done_order(morning)
server_has(morning, [down(1), net(2)], run_field=False)
tick(K("11:00"))
check("старый отчёт без номера прогона, но «собрано» — его → дозабор заказан",
      redo_orders() == [f"redo-{morning['id']}"], ORDERS)

# ════════════════════════════════════════════════════════════════════════════
rule("Д3", "когда: через час после конца, не позже 6 ч; отказы и отсрочки")
P = redo.Pick(rows=[down(1)], index=[0], total=1)
base = dict(end=K("09:50"), choice=P, same="", night=False, next_slot=K("16:15"),
            collected="", going="", today=0, blocker="", deferred=False)
check("40 мин после конца — молча ждём; 70 — заказ",
      redo.plan(now=K("10:30"), **base)[0] == "wait" and redo.plan(now=K("11:00"), **base)[0] == "order")
check("больше 6 ч после конца — не нужен, молча; а если откладывали — строка",
      redo.plan(now=K("16:00"), **base)[0] == "quiet"
      and redo.plan(now=K("16:00"), **dict(base, deferred=True))[0] == "skip"
      and redo.REDO_LATE_HOURS == watch.ORDER_TTL_HOURS)
check("ночь, дни уже собраны, до слота меньше часа — строка без заказа; идёт накрывающий обход — молча ждём",
      redo.plan(now=K("11:00"), **dict(base, night=True))[0] == "skip"
      and redo.plan(now=K("11:00"), **dict(base, collected="#7 (full-6)"))[0] == "skip"
      and redo.plan(now=K("15:20"), **base)[0] == "skip"
      and redo.plan(now=K("11:00"), **dict(base, going="#8 (full-6)"))[0] == "wait")
check("очередь GitHub занята или заявка уже ушла — отложить",
      redo.plan(now=K("11:00"), **dict(base, blocker="очередь"))[0] == "defer")
evening = mkrun(K("20:31"), ended=K("21:50"))
reset([evening])
done_order(evening, at="20:30")
server_has(evening, [down(1), net(2)])
edge = last_id()
tick(K("23:00"))
check("сбор 20:30 кончился в 21:50 → в 23:00 ночь: дозабор не заказываю, строка про утренний 08:15",
      redo_orders() == [] and len(notes_after(edge)) == 1 and "ночь" in notes_after(edge)[0]
      and "08:15" in notes_after(edge)[0] and alarms_after(edge) == [], (ORDERS, notes_after(edge)))
afternoon = mkrun(K("12:31"), ended=K("14:10"))
reset([afternoon])
done_order(afternoon, at="12:30", slot=False)
server_has(afternoon, [down(1)])
edge = last_id()
tick(K("15:20"))
check("до планового 16:15 меньше часа → не заказываю, строка «он их и соберёт»",
      redo_orders() == [] and any("16:15" in n and "соберёт" in n for n in notes_after(edge)),
      (ORDERS, notes_after(edge)))
newer = mkrun(K("10:01"), ended=K("10:50"), title="Обход full-6")
reset([morning, newer])
done_order(morning)
server_has(morning, [down(1)])
edge = last_id()
tick(K("11:00"))
check("дни уже собрал более новый удачный полный → дозабор не нужен, строка",
      redo_orders() == [] and any("уже собрал обход" in n for n in notes_after(edge)),
      (ORDERS, notes_after(edge)))
going = mkrun(K("10:40"), status="in_progress", title="Обход full-6")
reset([morning, going])
rec = done_order(morning)
server_has(morning, [down(1)])
edge = last_id()
tick(K("11:00"))
check("идёт более новый полный на 6 → молча ждём его итога",
      redo_orders() == [] and notes_after(edge) == [] and not record(rec["id"]).get("redo"),
      (ORDERS, notes_after(edge)))
API["runs"] = [morning, finished(going, K("11:40"))]
tick(K("11:45"))
check("…он дошёл → дни собраны, дозабор не нужен",
      redo_orders() == [] and any("уже собрал обход" in n for n in notes_after(edge)), notes_after(edge))
ahead = mkrun(K("10:50"), status="in_progress", title="Обход full-2")
waiting = mkrun(K("10:55"), status="queued", title="Обход date-2026-11-12")
reset([morning, ahead, waiting])
rec = done_order(morning)
server_has(morning, [down(1), net(2)])
edge = last_id()
tick(K("11:00"))
tick(K("11:15"))
check("в очереди GitHub ждёт заказанный сбор → дозабор отложен, строка ОДИН раз",
      redo_orders() == [] and len([n for n in notes_after(edge) if "отложен" in n]) == 1
      and record(rec["id"]).get("redo_deferred"), (ORDERS, notes_after(edge)))
API["runs"] = [morning, finished(ahead, K("11:20")), finished(waiting, K("11:25"))]
tick(K("11:30"))
check("…очередь освободилась → дозабор заказан, пометка отсрочки снята",
      redo_orders() == [f"redo-{morning['id']}"] and not record(rec["id"]).get("redo_deferred"),
      (ORDERS, record(rec["id"])))
manual = mkrun(K("13:31"), ended=K("15:10"))
reset([manual])
done_order(manual, at="13:30", slot=False)
server_has(manual, [down(1)])
jset("crawl_missed", {"slot": f"{DAY} 16:15", "days": 2, "at": watch.when(K("16:20")),
                      "why": "тест", "state": "missed"})
edge = last_id()
tick(K("16:30"))
check("в эту проверку уже ушла заявка досрочного (С6) → дозабор отложен, второй тег не шлём",
      ORDERS == ["days-6"] and any("уже ушла другая заявка" in n for n in notes_after(edge)),
      (ORDERS, notes_after(edge)))

# ════════════════════════════════════════════════════════════════════════════
rule("Д4", "пределы: один на сбор, 3 в сутки, 40 адресов, больше 80 — массовый сбой")
reset([morning])
rec = done_order(morning)
rows45 = [down(i) if i % 2 else net(i) for i in range(1, 46)]
server_has(morning, rows45 + [ban(99)])
edge = last_id()
tick(K("11:00"))
check("45 упавших → один дозабор первых 40 по порядку отчёта (строка «первые 40 из 45»)",
      redo_orders() == [f"redo-{morning['id']}"]
      and any("первые 40 из 45" in n for n in notes_after(edge)), (ORDERS, notes_after(edge)))
check("…GitHub качает те же 40: первые по порядку отчёта",
      [r["url"] for r in redo.pick({"строки": rows45}).rows] == [r["url"] for r in rows45[:40]])
tick(K("11:15"))
tick(K("12:00"))
check("…второго дозабора по тому же сбору нет", redo_orders() == [f"redo-{morning['id']}"], ORDERS)
reset([morning])
done_order(morning)
server_has(morning, [down(i) for i in range(1, 82)])
edge = last_id()
tick(K("11:00"))
check("81 упавший → массовый сбой, не дозабор: строка, заказа нет, тревоги нет",
      redo_orders() == [] and any("массовый сбой" in n for n in notes_after(edge))
      and alarms_after(edge) == [], (ORDERS, notes_after(edge)))
check("…ровно 80 — ещё дозабор (40 адресов)",
      not redo.pick({"строки": [down(i) for i in range(80)]}).mass
      and len(redo.pick({"строки": [down(i) for i in range(80)]}).rows) == 40)
reset([morning])
rec = done_order(morning)
server_has(morning, [ok(1), ban(2), row(3, why="HTTP 404")])
edge = last_id()
tick(K("11:00"))
check("упавших down/net ноль (только 403 и 404) → ничего не делаем молча",
      redo_orders() == [] and notes_after(edge) == [] and record(rec["id"]).get("redo"),
      (ORDERS, notes_after(edge)))
reset([morning])
done_order(morning)
server_has(morning, [down(1)])
conn = db.connect()
for n in range(3):
    watch.add_order(conn, f"redo-{n}", f"{DAY} 0{n + 1}:00", "", "сторож: дозабор",
                    at=K(f"0{n + 1}:00"), done=True)
conn.close()
edge = last_id()
tick(K("11:00"))
check("за киевские сутки уже 3 дозабора → четвёртый не заказываю, строка про предел",
      redo_orders() == [] and any("предел 3" in n for n in notes_after(edge)), (ORDERS, notes_after(edge)))
recs = [{"what": "redo-1", "at": K("23:50", "2026-11-09").isoformat()},
        {"what": "redo-2", "at": K("00:10").isoformat()}, {"what": "full-6", "at": K("01:00").isoformat()}]
check("сутки — киевские: вчерашний 23:50 не в счёт, сегодняшний 00:10 — в счёт",
      redo.redo_today(recs, K("11:00"), watch.record_at) == 1)

# ════════════════════════════════════════════════════════════════════════════
rule("Д5", "заявка: тег btn-redo-<id>, crawl.yml с from_run и redo=1, запись книги redo-<id>")
reset([mkrun(K("09:00"), ended=K("09:30"), title="Обход proba-2")])
NOW[0] = K("11:00")
saved = sys.argv
sys.argv = ["request_crawl.py", "redo", "123456", "--force", "--unlock", "--locked",
            "--redo-of=2026-11-10 08:15:00|cron"]
try:
    code = rc.main()
finally:
    sys.argv = saved
rec5 = [r for r in book() if r["what"] == "redo-123456"]
check("request_crawl.py redo <id> --redo-of=<id записи>: тег redo, запись redo-<id> «дозабор заказа», отметка «заявка»",
      code == 0 and TAGS == [("redo", "123456")] and len(rec5) == 1
      and rec5[0].get("redo_of") == "2026-11-10 08:15:00|cron" and rec5[0].get("who") == "сторож: дозабор"
      and (setting("crawl_running") or "").endswith("|redo-123456"), (code, TAGS, rec5))
sys.argv = ["request_crawl.py", "redo", "12a", "--locked"]
try:
    bad = rc.main()
finally:
    sys.argv = saved
check("номер прогона не из цифр — заявка отвергнута", bad == 2)
reset([mkrun(K("10:50"), status="in_progress", title="Обход full-2"),
       mkrun(K("10:55"), status="queued", title="Обход date-2026-11-12")])
sys.argv = ["request_crawl.py", "redo", "123456", "--force", "--unlock", "--locked", "--redo-of=x"]
try:
    busy_code = rc.main()
finally:
    sys.argv = saved
check("в очереди GitHub ждёт заказанный сбор → заявка дозабора не уходит (З6)",
      busy_code == 3 and TAGS == [], (busy_code, TAGS))
queue_yml = (ROOT / ".github" / "workflows" / "queue.yml").read_text(encoding="utf-8")
crawl_yml = (ROOT / ".github" / "workflows" / "crawl.yml").read_text(encoding="utf-8")
redo_branch = queue_yml.split('elif [ "$KIND" = "redo" ]; then', 1)[-1].split("elif [", 1)[0]
check("queue.yml: ветка redo — номер только цифры, from_run=<id>, code_ref пуст (текущий main), redo=1",
      '[[ "$RUN_ID" =~ ^[0-9]{1,20}$ ]]' in redo_branch
      and '\\"from_run\\":\\"$RUN_ID\\",\\"code_ref\\":\\"\\",\\"redo\\":\\"1\\"' in redo_branch
      and "${{" not in redo_branch)
check("crawl.yml: вход redo — только «1», только с from_run и без code_ref; прогон зовётся «Обход redo-<id>»",
      '[[ "$IN_REDO" =~ ^1?$ ]]' in crawl_yml
      and '[ "$IN_REDO" = "1" ] && { [ -z "$IN_FROM_RUN" ] || [ -n "$IN_CODE_REF" ]; }' in crawl_yml
      and "inputs.from_run != '' && inputs.redo == '1' && format('Обход redo-{0}', inputs.from_run)" in crawl_yml)
check("сторож: вид redo-<id> узнаётся, потолок 60 мин, запись книги годна, итог — в results/partial",
      watch.run_kind({"display_title": "Обход redo-5"}) == ("redo", 0)
      and watch.ceiling("redo") == 60 and watch.record_problem(
          {"id": "x", "what": "redo-5", "order": f"{DAY} 11:00", "at": K("11:00").isoformat()}) == ""
      and watch.result_dir("redo-5") == "results/partial" and watch.describe("redo") == "дозабор упавших адресов")
check("потолок хода покрывает докачку: установка+артефакт+докачка+разбор < 60 мин",
      redo.REDO_FETCH_MINUTES + 20 <= watch.CEILING_MINUTES["redo"] < watch.CEILING_MINUTES["full-2"])

# ════════════════════════════════════════════════════════════════════════════
rule("Д6", "GitHub: качаем ТОЛЬКО отобранные, report.json — упавшие строки свежими")


class FakeFetcher:
    """Вместо сети: адрес → (html, ошибка); что спросили — в `asked`."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.asked: list[str] = []
        self.browser_only = False

    def get_with_fallback(self, url, local=None, locale="en-GB", post=None, warmup="",
                          post_json=None, extra=None):
        self.asked.append(url)
        html, error = self.answers.get(url, ("", "ConnectTimeout: timed out"))
        return fetch.Page(url, html, False, error)


OUT = TMP / "raw_live"
OUT.mkdir()
report6 = {"когда": DAY, "режим": "полный обход, окно 6 суток", "прогон": "555",
           "строки": [ok(1), down(2), ban(3), net(4), row(5, why="HTTP 404")],
           "дозор": {"liveonsat.com": {}}, "оценка": {"код": 0}}
page_html = "<html><body><p>20:45 Arsenal - Chelsea</p><p>22:00 Milan - Inter</p></body></html>"
fake = FakeFetcher({down(2)["url"]: (page_html, "")})
os.environ["GITHUB_RUN_ID"] = "777"
code6, merged, md = cf.redo_fetch(report6, OUT, fake, "555")
fresh2, fresh4 = merged["строки"][1], merged["строки"][3]
check("заново спрошены ТОЛЬКО down и net (403 и 404 — нет), по порядку отчёта",
      code6 == 0 and fake.asked == [down(2)["url"], net(4)["url"]], fake.asked)
check("выправившаяся строка — свежая: «расписание есть», файл страницы лёг под именем обхода",
      fresh2["итог"] == "расписание есть" and fresh2.get("файл") == fetch.cache_name(down(2)["url"]).name
      and (OUT / fresh2["файл"]).read_text(encoding="utf-8") == page_html
      and "(дозабор)" in fresh2["почему"], fresh2)
check("не выправившаяся — тоже свежая (новая причина); остальные строки как были",
      fresh4["итог"] == "не открылась" and fresh4["почему"].startswith("ConnectTimeout")
      and merged["строки"][0] == report6["строки"][0] and merged["строки"][2] == report6["строки"][2]
      and merged["строки"][4] == report6["строки"][4])
check("раздел «дозабор»: из прогона, адресов, выправилось; «прогон» — этот, «режим» с пометкой, окно цело",
      merged["дозабор"] == {"из прогона": "555", "адресов": 2, "выправилось": 1, "отобрано": 2, "упавших": 2}
      and merged["прогон"] == "777" and merged["режим"].startswith("дозабор")
      and "окно 6" in merged["режим"] and report6["прогон"] == "555", merged.get("дозабор"))
clock_values = iter([0, 0, 1700, 2000, 9999])
fake_slow = FakeFetcher({})
code_b, merged_b, _ = cf.redo_fetch({"строки": [down(1), down(2), down(3)]}, OUT, fake_slow, "1",
                                    budget_minutes=30, clock=lambda: next(clock_values))
check("не успели за 30 мин — оставшиеся строки остаются как были",
      code_b == 0 and len(fake_slow.asked) == 2 and merged_b["строки"][2] == down(3)
      and merged_b["дозабор"]["адресов"] == 2, fake_slow.asked)
fake_none = FakeFetcher({})
code_m, _, _ = cf.redo_fetch({"строки": [down(i) for i in range(81)]}, OUT, fake_none, "1")
code_z, _, _ = cf.redo_fetch({"строки": [ok(1), ban(2)]}, OUT, fake_none, "1")
check("массовый сбой или ноль упавших — код 1 и ни одного запроса (сервер такой и не закажет)",
      code_m == 1 and code_z == 1 and fake_none.asked == [])
made: list[dict] = []
real_fetcher = fetch.Fetcher


class RecordingFetcher(FakeFetcher):
    def __init__(self, **kwargs):
        made.append(kwargs)
        super().__init__({down(2)["url"]: (page_html, "")})


main_dir = TMP / "raw_main"
main_dir.mkdir()
(main_dir / "report.json").write_text(json.dumps(report6, ensure_ascii=False), encoding="utf-8")
(main_dir / "report.md").write_text("# Итог обхода\n\nстарое\n", encoding="utf-8")
fetch.Fetcher = RecordingFetcher
saved_delay = fetch.DELAY
try:
    code_main = cf.redo_main(argparse.Namespace(
        redo=str(main_dir / "report.json"), out=str(main_dir), delay=0.0,
        no_browser=False, browser=False, from_run="555"))
finally:
    fetch.Fetcher = real_fetcher
    fetch.DELAY = saved_delay
on_disk = json.loads((main_dir / "report.json").read_text(encoding="utf-8"))
check("--redo: отчёт переписан на месте, report.md дополнен, к сайтам — обычный путь с запасным браузером",
      code_main == 0 and on_disk["дозабор"]["выправилось"] == 1
      and "## Дозабор из прогона 555" in (main_dir / "report.md").read_text(encoding="utf-8")
      and "старое" in (main_dir / "report.md").read_text(encoding="utf-8")
      and made == [{"offline": False, "use_cache": False, "browser_fallback": True, "browser_only": False}],
      (code_main, made))
check("флаг offline в app/fetch.py не тронут: по умолчанию к сайтам не ходим",
      inspect.signature(fetch.Fetcher.__init__).parameters["offline"].default is True)
os.environ.pop("GITHUB_RUN_ID", None)


def crawl_steps(text: str) -> list[dict]:
    """Шаги crawl.yml: {name|uses, id, if} — ключи шага с отступом 8."""
    body = text.split("\n    steps:\n", 1)[1]
    out = []
    for chunk in re.split(r"^      - ", body, flags=re.M)[1:]:
        lines = chunk.split("\n")
        key, _, value = lines[0].partition(": ")
        step = {key: value.strip()}
        for line in lines[1:]:
            m = re.match(r"^        ([a-z-]+):(?: (.*))?$", line)
            if m and m.group(1) not in step:
                step[m.group(1)] = (m.group(2) or "").strip()
        out.append(step)
    return out


def step_runs(cond: str, outputs: dict, event: str, status: str) -> bool:
    """`if:` шага по правилам GitHub: без функции статуса — неявный success()."""
    expr = cond or "success()"
    has_status = re.search(r"\b(always|success|failure|cancelled)\(\)", expr)
    expr = re.sub(r"steps\.(\w+)\.outputs\.(\w+)",
                  lambda m: repr(outputs.get(m.group(1), {}).get(m.group(2), "")), expr)
    for name, value in (("github.event_name", event), ("inputs.readers", "no"),
                        ("vars.STREAMS_AI", "off")):
        expr = expr.replace(name, repr(value))
    for name, value in (("always()", True), ("success()", status == "success"),
                        ("failure()", status == "failure"), ("cancelled()", False)):
        expr = expr.replace(name, repr(value))
    expr = expr.replace("&&", " and ").replace("||", " or ")
    result = bool(eval(expr, {"__builtins__": {}}, {}))       # noqa: S307 — свой файл
    return result if has_status else result and status == "success"


def run_plan(mode: dict, event="workflow_dispatch", fail_at: str = "") -> list[str]:
    """Какие шаги crawl.yml пойдут: `mode` — выходы шага «Что запускаем»,
    `fail_at` — id шага, который краснеет (дальше статус failure)."""
    outputs = {"guard": {"run": "1"}, "what": dict(
        {"mode": "full", "days": "6", "delay": "3", "only": "", "urls": "", "date": "",
         "from_run": "", "code_ref": "", "redo": ""}, **mode)}
    status, went = "success", []
    for step in crawl_steps(crawl_yml):
        label = step.get("name") or step.get("uses")
        if step_runs(step.get("if", ""), outputs, event, status):
            went.append(label)
            if step.get("id") and step.get("id") == fail_at:
                status = "failure"
    return went


HEAD = ["Проверка параметров запуска", "actions/checkout@v4", "actions/setup-python@v5",
        "Поставить, что нужно", "Не ходили ли уже сегодня", "Что запускаем",
        "Стук серверу — начали", "Самопроверка окружения"]
TAIL = ["Разобрать скачанное", "Самопроверка прогона", "Показать итог прямо здесь"]
check("crawl.yml: шагов 25 (23 с именем + checkout и setup-python), шаг «Дозабор» один, имена шагов не повторяются",
      len(crawl_steps(crawl_yml)) == 25 and crawl_yml.count("      - name: ") == 23
      and crawl_yml.count("id: redo\n") == 1
      and len({s.get("name") for s in crawl_steps(crawl_yml) if s.get("name")}) == 23)
check("режим redo: страницы прежнего сбора → Дозабор → разбор → push_partial; обхода, results/, артефакта и дозора нет",
      run_plan({"from_run": "123", "redo": "1"}) == HEAD + [
          "Какой сбор переразбираем", "Страницы прежнего сбора", "Дозабор упавших адресов"] + TAIL
      + ["Положить переразбор в репозиторий", "Стук серверу — закончили"],
      run_plan({"from_run": "123", "redo": "1"}))
check("…упал «Дозабор» → разбор и стук идут, push_partial и issue владельцу — нет",
      run_plan({"from_run": "123", "redo": "1"}, fail_at="redo") == HEAD + [
          "Какой сбор переразбираем", "Страницы прежнего сбора", "Дозабор упавших адресов"] + TAIL
      + ["Стук серверу — закончили"])
check("переразбор — как раньше: без «Дозабора»; упал разбор — issue владельцу есть",
      run_plan({"from_run": "123"}) == HEAD + ["Какой сбор переразбираем", "Страницы прежнего сбора"]
      + TAIL + ["Положить переразбор в репозиторий", "Стук серверу — закончили"]
      and "Провал — issue владельцу" in run_plan({"from_run": "123"}, fail_at="parse"))
check("обычный полный обход — как раньше: Обход → results/ → артефакт → дозор; провал → issue",
      run_plan({}) == HEAD + ["Обход"] + TAIL + [
          "Положить результат в репозиторий", "Забрать страницы и отчёты",
          "Дозор — сайт снова пускает", "Стук серверу — закончили"]
      and "Провал — issue владельцу" in run_plan({}, fail_at="fetch"))
check("обход по расписанию и скан даты — без «Дозабора» и без push_partial",
      not {"Дозабор упавших адресов", "Положить переразбор в репозиторий"}
      & set(run_plan({}, event="schedule") + run_plan({"date": "2026-11-12"})))
check("стук: вид redo-<id>; у дозабора причина «fetch» — итог шага «Дозабор»",
      '[ -n "$W_FROM_RUN" ] && [ "$W_REDO" = "1" ] && WHAT="redo-$W_FROM_RUN"' in crawl_yml
      and 'export STEP_FETCH="$STEP_REDO"' in crawl_yml
      and fail_reason.reason({"fetch": "failure"}, "failure", TMP) == "plan")

# ════════════════════════════════════════════════════════════════════════════
rule("Д7", "заливка «только добавить»: пометка в файле, ничего не гасить")
check("разбор кладёт «режим»: «дозабор», только если в отчёте есть раздел «дозабор»",
      redo.games_mark({"дозабор": {"адресов": 1}}) == {"режим": "дозабор", "дозабор": {"адресов": 1}}
      and redo.games_mark({"строки": []}) == {} and redo.games_mark(None) == {}
      and redo.is_add_only({"режим": "дозабор"}) and not redo.is_add_only({"игр": 3}))
parse_src = (ROOT / "scripts" / "parse_live.py").read_text(encoding="utf-8")
check("parse_live.py кладёт пометку в games.json, push_partial без неё дозабор не кладёт",
      "payload.update(redo.games_mark(report_data))" in parse_src
      and "grep -q '\"режим\": \"дозабор\"' recon/raw_live/games.json" in crawl_yml)

IMPORT_DB = TMP / "import.db"
GRID, OTHER = "grid.test", "other.test"
GAME_DAY = (date.today() + timedelta(days=3)).isoformat()
URL = {GRID: f"https://grid.test/epg?date={GAME_DAY}", OTHER: f"https://other.test/tv?date={GAME_DAY}"}


def gm(home, away, hhmm, *entries):
    return {"sport": "F", "league": "", "home": home, "away": away,
            "start_kyiv": f"{GAME_DAY}T{hhmm}", "start_utc": "",
            "entries": [{"source": d, "channel": ch, "url": URL[d], "raw_title": ""}
                        for d, ch in entries]}


def import_file(folder: str, games: list, rows: list, mode: bool, who: str = "переразбор",
                minutes_ago: int = 0) -> str:
    """games.json + report.json в папке `folder` → `games_import.py --file …`
    отдельным процессом на временной базе (как на сервере). «Собрано» —
    `minutes_ago` минут назад (UTC)."""
    path = TMP / "imp" / folder
    path.mkdir(parents=True, exist_ok=True)
    made = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    payload = {"собрано": made.strftime("%Y-%m-%d %H:%M"), "игр": len(games), "games": games}
    if mode:
        payload.update(redo.games_mark({"дозабор": {"из прогона": "1", "адресов": 1}}))
    (path / "games.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (path / "report.json").write_text(json.dumps(
        {"режим": "полный обход, окно 6 суток", "строки": rows}, ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ, STREAMS_DB=str(IMPORT_DB))
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "games_import.py"),
                           "--file", str(path / "games.json"), "--who", who],
                          capture_output=True, text=True, env=env, encoding="utf-8")
    return done.stdout + done.stderr


def import_db():
    os.environ["STREAMS_DB"] = str(IMPORT_DB)
    return db.connect()


def miss_of(conn, channel: str) -> int | None:
    r = conn.execute("SELECT ec.miss_count FROM event_channels ec JOIN channel_aliases ca "
                     "ON ca.channel_id = ec.channel_id AND ca.source_id = ec.source_id "
                     "WHERE ca.alias = ?", (channel,)).fetchone()
    return r[0] if r else None


conn = import_db()
db.init_db(conn)
for d in (GRID, OTHER, "dead.test"):
    conn.execute("INSERT INTO sources (domain, name, base_url, country) VALUES (?, ?, ?, 'XX')",
                 (d, d, f"https://{d}/"))
conn.commit()
conn.close()
os.environ["STREAMS_DB"] = str(WATCH_DB)
A1 = ("Arsenal", "Chelsea", "21:45")
A2 = ("Liverpool", "Everton", "20:00")
A3 = ("Juventus", "Milan", "19:00")
good_rows = [{"domain": GRID, "channel": "", "day": GAME_DAY, "итог": "расписание есть", "url": URL[GRID]},
             {"domain": OTHER, "channel": "", "day": GAME_DAY, "итог": "расписание есть", "url": URL[OTHER]},
             {"domain": "dead.test", "channel": "", "day": GAME_DAY, "итог": "не открылась",
              "почему": "HTTP 503", "url": "https://dead.test/x"}]
first = [gm(*A1, (GRID, "Max 4"), (OTHER, "Other 1")), gm(*A2, (GRID, "Max 2"), (OTHER, "Other 2"))]
moved = [gm(*A1, (GRID, "Max 1"), (OTHER, "Other 1")), gm(*A2, (GRID, "Max 2"), (OTHER, "Other 2"))]
out1 = import_file("results", first, good_rows, mode=False, who="", minutes_ago=30)
conn = import_db()
crawl_before = db.get_setting(conn, "last_crawl")
fails_before = conn.execute("SELECT fail_count FROM sources WHERE domain = 'dead.test'").fetchone()[0]
conn.close()
out2 = import_file("partial", moved + [gm(*A3, (GRID, "Max 3"))], good_rows, mode=True,
                   minutes_ago=10)
conn = import_db()
log2 = json.loads(conn.execute("SELECT log FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0])
check("файл дозабора: Max 4 (его нет в файле) НЕ погашен, новый канал Max 1 и новая игра добавлены",
      miss_of(conn, "Max 4") == 0 and miss_of(conn, "Max 1") == 0 and miss_of(conn, "Max 3") == 0
      and "только добавляю" in out2, out2[-600:])
check("…«кто» — «дозабор» (хотя streams-update.sh пишет --who переразбор); метка сбора и счётчик сбоев сайта не сдвинулись",
      log2.get("кто") == "дозабор" and db.get_setting(conn, "last_crawl") == crawl_before
      and conn.execute("SELECT fail_count FROM sources WHERE domain = 'dead.test'").fetchone()[0]
      == fails_before and fails_before == 1, (log2.get("кто"), fails_before))
conn.close()
out3 = import_file("results2", moved, good_rows, mode=False)
conn = import_db()
check("обычная заливка (переразбор, без пометки) гасит как раньше: Max 4 погашен",
      miss_of(conn, "Max 4") == store.MISS_LIMIT and "только добавляю" not in out3, out3[-600:])
conn.close()
os.environ["STREAMS_DB"] = str(WATCH_DB)
check("правило 0 гашения: дозабор только дописывает — раньше всех прочих",
      "0. Файл — не дозабор" in miss.__doc__
      and inspect.getsource(miss.Гашение.почему_нельзя).index("self.дописать")
      < inspect.getsource(miss.Гашение.почему_нельзя).index("self.свежий"))


def owner_db(n: int):
    """База с официальным sportklub.hr и агрегатором mojtv.hr (как test_channel_owner)."""
    os.environ["STREAMS_DB"] = str(TMP / f"owner{n}.db")
    c = db.connect()
    db.init_db(c)
    c.execute("INSERT INTO sources (id, domain, name, base_url, country, enabled) "
              "VALUES (1, 'sportklub.hr', 'SK', 'https://sportklub.hr/', 'HR', 1)")
    c.execute("INSERT INTO sources (id, domain, name, base_url, country, enabled) "
              "VALUES (2, 'mojtv.hr', 'MojTV', 'https://mojtv.hr/', 'HR', 1)")
    c.commit()
    return c


def owner_game(day_: str, lines):
    return {"sport": "F", "league": "Liga", "home": "A", "away": "B",
            "start_kyiv": f"{day_}T20:00", "start_utc": f"{day_}T17:00",
            "entries": [{"source": s, "channel": ch, "url": "", "raw_title": ""} for s, ch in lines]}


NOON = datetime.combine(date.today(), datetime.min.time()).replace(hour=12)
today_, tomorrow_ = date.today().isoformat(), (date.today() + timedelta(days=1)).isoformat()
counts = []
for n, add_only in ((1, False), (2, True)):
    c = owner_db(n)
    lines = [("mojtv.hr", "Sport Klub 1"), ("mojtv.hr", "MAX Sport 1")]
    store.save_games(c, [owner_game(today_, lines)], now=NOON)
    c.execute("UPDATE sources SET selector_config = ? WHERE id = 1",
              (json.dumps({channel_owner.ФЛАГ: True}),))
    ch = c.execute("SELECT channel_id FROM channel_aliases WHERE alias = 'Sport Klub 1'").fetchone()[0]
    c.execute("INSERT OR IGNORE INTO channel_aliases (channel_id, alias, source_id) VALUES (?, 'Sport Klub 1', 1)", (ch,))
    ev = c.execute("INSERT INTO events (sport, team_home_auto, team_away_auto, start_utc, start_kyiv, last_seen) "
                   "VALUES ('F', 'C', 'D', ?, ?, ?)", (f"{tomorrow_} 17:00", f"{tomorrow_} 20:00",
                                                      datetime.now().strftime("%Y-%m-%d %H:%M"))).lastrowid
    c.execute("INSERT INTO event_channels (event_id, channel_id, source_id, source_url, raw_title, last_seen, miss_count) "
              "VALUES (?, ?, 1, '', '', ?, 0)", (ev, ch, datetime.now().strftime("%Y-%m-%d %H:%M")))
    c.commit()
    stats = store.save_games(c, [owner_game(today_, lines)], now=NOON, add_only=add_only)
    counts.append((stats.not_own_dropped, c.execute(
        "SELECT COUNT(*) FROM event_channels WHERE source_id = 2").fetchone()[0]))
    c.close()
os.environ["STREAMS_DB"] = str(WATCH_DB)
check("отметки агрегатора («свой сайт важнее»): обычная заливка снимает, дозабор — не снимает",
      counts == [(1, 1), (0, 2)], counts)

# ════════════════════════════════════════════════════════════════════════════
rule("Д8", "сбой дозабора — только строка (close); дозабор не «полный сбор»")
check("таблица RECOVERY: сорвался, состарился, не ушёл, оборвали, остановил владелец — close",
      [watch.recovery(watch.failure_of({"what": "redo-1"}, how, reason)) for how, reason in
       (("failed", ""), ("failed", "fetch-net"), ("expired", ""), ("stopped", ""))]
      == ["close"] * 4 and watch.recovery("redo-refused") == "close"
      and watch.recovery("redo-lost") == "close"
      and not any("ТРЕВОГА" in t for t in watch.CLOSE_TAIL.values()))
redo_run = mkrun(K("11:01"), ended=K("11:40"), title="Обход redo-5")
pushed_out = mkrun(K("10:00"), ended=K("10:30"), conclusion="cancelled", title="Обход full-6")
redo_mid = mkrun(K("10:10"), ended=K("10:50"), title="Обход redo-5")
check("дозабор не полный сбор: не ответ на заказ полного, не «собрано», не накрывает слот, не вытесняет",
      watch.full_runs([redo_run]) == [] and "redo" not in watch.FULL_KINDS
      and watch.collected_by("full-6", K("10:00"), [redo_run]) is None
      and watch.plan_early({"slot": f"{DAY} 08:15", "days": 6, "at": watch.when(K("08:20")),
                            "state": "missed"}, [mkrun(K("10:00"), status="in_progress",
                                                       title="Обход redo-5")], K("10:30"),
                           {}, None)[0] == "order"
      and watch.superseded_by("full-6", pushed_out, [pushed_out, redo_mid],
                              {str(redo_mid["id"])}) is None
      and watch.lock_verdict({"what": "redo-5", "state": "идёт", "since": "11:01"}, 2,
                             [mkrun(K("11:01"), status="in_progress", title="Обход redo-5")],
                             K("11:20"))[0] == "behind")
reset([morning])
conn = db.connect()
lost = watch.add_order(conn, "redo-555", f"{DAY} 11:00", "", "сторож: дозабор", at=K("11:00"))
conn.close()
edge = last_id()
tick(K("11:15"))
check("дозабор не стартовал за 10 мин → строка «данные основного сбора уже влиты», без ТРЕВОГИ, без заказов",
      record(lost["id"]).get("failed") is True and ORDERS == [] and alarms_after(edge) == []
      and any("дозабор упавших адресов прогона 555" in n and "уже влиты" in n
              for n in notes_after(edge)), notes_after(edge))
hung = mkrun(K("11:01"), status="in_progress", title="Обход redo-555")
reset([morning, hung])
conn = db.connect()
stuck_rec = watch.add_order(conn, "redo-555", f"{DAY} 11:00", "", "сторож: дозабор", at=K("11:00"))
conn.close()
edge = last_id()
tick(K("12:05"))
check("дозабор завис (64 мин > 60) → одна заявка отмены, заказ закрыт строкой, без ТРЕВОГИ",
      TAGS == [("cancel", str(hung["id"]))] and record(stuck_rec["id"]).get("failed") is True
      and alarms_after(edge) == [] and any("уже влиты" in n for n in notes_after(edge)),
      (TAGS, notes_after(edge)))
reset([morning])
rec = done_order(morning, redo="заказан", redoing=watch.when(K("11:00")))
edge = last_id()
tick(K("11:15"))
check("[С2] проверку оборвали посреди заявки дозабора → строка, без ТРЕВОГИ, второго не будет",
      ORDERS == [] and alarms_after(edge) == [] and not record(rec["id"]).get("redoing")
      and any("дозабор заказать не удалось" in n for n in notes_after(edge)), notes_after(edge))
reset([morning])
rec = done_order(morning)
server_has(morning, [down(1)])
cw.order_crawl = refused_order
edge = last_id()
tick(K("11:00"))
cw.order_crawl = fake_order
tick(K("11:15"))
check("заявка дозабора не ушла → строка «заказать не вышло», без ТРЕВОГИ; повтора нет",
      ORDERS == [f"redo-{morning['id']}"] and alarms_after(edge) == []
      and any("заказать не вышло" in n and "уже влиты" in n for n in notes_after(edge))
      and record(rec["id"]).get("redo") == "заявка не ушла", (ORDERS, notes_after(edge)))
stopped = mkrun(K("11:01"), ended=K("11:20"), conclusion="cancelled", title="Обход redo-555")
reset([morning, stopped])
conn = db.connect()
stop_rec = watch.add_order(conn, "redo-555", f"{DAY} 11:00", "", "сторож: дозабор", at=K("11:00"))
conn.close()
jset("crawl_cancel", {str(stopped["id"]): {"at": watch.when(K("11:15")), "number": 1,
                                           "by": "владелец", "alarmed": False}})
edge = last_id()
tick(K("11:30"))
check("дозабор остановил владелец кнопкой → закрыт строкой «остановил владелец», без ТРЕВОГИ",
      record(stop_rec["id"]).get("stopped") is True and alarms_after(edge) == []
      and any("остановил владелец" in n for n in notes_after(edge)), notes_after(edge))

reset([morning])
rec = done_order(morning)
(RESULTS_DIR / "report.json").write_text('[1, "битый", {"строки": 5}]', encoding="utf-8")
(RESULTS_DIR / "games.json").write_text("не JSON", encoding="utf-8")
edge = last_id()
tick(K("11:00"))
check("битый results/report.json на сервере → проверка не падает, дозабора нет, ни строки",
      redo_orders() == [] and notes_after(edge) == [] and record(rec["id"]).get("redo"),
      (ORDERS, notes_after(edge)))
morning2 = mkrun(K("08:21"), ended=K("09:55"))
reset([morning, morning2])
rec = done_order(morning)
second = done_order(morning2, at="08:20", slot=False)
server_has(morning, [down(1)])
real_plan = redo.plan
calls = []


def exploding_plan(**k):
    calls.append(1)
    if len(calls) == 1:
        raise ValueError("битые данные")
    return real_plan(**k)


redo.plan = exploding_plan
edge = last_id()
crashed = None
try:
    tick(K("11:00"))
except Exception as error:                                     # noqa: BLE001
    crashed = error
finally:
    redo.plan = real_plan
edge_rows = notes_after(edge)
check("С7 упал на одной записи → одна строка-предупреждение (не ТРЕВОГА), остальные записи и проверка идут дальше",
      crashed is None and len([n for n in edge_rows if "разбор упал" in n]) == 1
      and alarms_after(edge) == [] and len(calls) == 2
      and "разбор упал" in record(rec["id"]).get("redo", "") + record(second["id"]).get("redo", ""),
      (crashed, edge_rows))
edge = last_id()
tick(K("11:15"))
check("…следующей проверкой строка про упавший разбор не повторяется",
      not any("разбор упал" in n for n in notes_after(edge)), notes_after(edge))

# ════════════════════════════════════════════════════════════════════════════
rule("Д9", "на каждое правило шапки app/redo.py есть проверка")
head = redo.__doc__
rules = re.findall(r"^  (Д\d)\. ", head, re.M)
check("в шапке app/redo.py правила Д1–Д9 по порядку", rules == [f"Д{i}" for i in range(1, 10)], rules)
check("на каждое правило шапки есть проверка с его номером",
      [r for r in rules if r not in COVERED] == [], [r for r in rules if r not in COVERED])
check("сторож зовёт дозабор последним шагом проверки (С7, после С6)",
      inspect.getsource(cw.tick).index("order_redo(t)") > inspect.getsource(cw.tick).index("order_early(t)"))

print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, красных: {len(failed)}")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)

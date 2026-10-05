# -*- coding: utf-8 -*-
r"""Проверки блока «Сбор расписания — экстренно» в админке (владелец
06.10.2026): каждая кнопка через тестовый клиент Flask, отказ без входа и без
CSRF, строка «владелец: …» в «Прогонах».

В сеть не ходит и ничего не заказывает: список прогонов GitHub, тег-заявка и
ожидание старта подменены заглушками. Заявка обхода идёт НАСТОЯЩИМ путём —
`scripts/request_crawl.py` (в этом же процессе вместо отдельной службы).
База — КОПИЯ во временной папке:

    python scripts/test_emergency.py
    python scripts/test_emergency.py --db ..\streams-crawl\data\channel_schedule.db

Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
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

TMP = Path(tempfile.mkdtemp(prefix="emergency-test-"))
src = Path(OPTS.db) if OPTS.db else ROOT / "data" / "channel_schedule.db"
if src.exists():
    shutil.copy(src, TMP / "test.db")
(TMP / "visits").mkdir()
os.environ.update(STREAMS_DB=str(TMP / "test.db"), STREAMS_ADMIN_PASSWORD="adm-test-1",
                  STREAMS_FRIEND_PASSWORD="fr-test-1", SECRET_KEY="k" * 32,
                  STREAMS_VISITS_DIR=str(TMP / "visits"))
os.environ.pop("STREAMS_LOCAL", None)

from app import crawl_hook, db, emergency, trigger, visits, watch, web  # noqa: E402

SLUG = "test/test"

# ── заглушки: ни GitHub, ни тегов ────────────────────────────────────────────
API = {"runs": []}                  # пусто — «GitHub не ответил»
TAGS: list[tuple] = []
SCRIPTS: list[tuple] = []


def fake_runs(slug, limit=0, workflow=""):
    return watch.Runs(dict(r) for r in API["runs"]) if API["runs"] else watch.Runs.silent()


trigger.push_request_tag = lambda kind, value: (TAGS.append((kind, value)) or (True, "тест"))
trigger._repo_slug = lambda: SLUG
watch.github_runs = fake_runs
watch.wait_for_start = lambda order, slug, kinds, **k: ({"run_number": 0}, True)
visits.write = lambda *a, **k: None


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rc = _load("request_crawl")


def fake_script(args, background):
    """`emergency.run_script` без отдельной службы: та же заявка
    `request_crawl.py` в этом процессе, её вывод — как у настоящей."""
    SCRIPTS.append((tuple(args), background))
    buf = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    saved = sys.argv
    sys.argv = ["request_crawl.py", *args]
    try:
        with contextlib.redirect_stdout(buf):
            code = rc.main()
        buf.flush()
    finally:
        sys.argv = saved
    out = buf.buffer.getvalue().decode("utf-8").strip()
    return code == 0, ("заявка запущена" if background else out)


emergency.run_script = fake_script

db.init_db()
app = web.create_app()
passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def setting(key, value=None):
    conn = db.connect()
    try:
        if value is None:
            return db.get_setting(conn, key)
        db.set_setting(conn, key, value)
    finally:
        conn.close()


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


def Z(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_ids = [37500000000]


def mkrun(minutes_ago, status="completed", conclusion="success", title="Обход full-6"):
    _ids[0] += 1
    at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {"id": _ids[0], "run_number": _ids[0] % 1000, "event": "workflow_dispatch",
            "status": status, "conclusion": conclusion if status == "completed" else None,
            "display_title": title, "name": title, "path": ".github/workflows/crawl.yml",
            "repository": {"full_name": SLUG}, "created_at": Z(at), "run_started_at": Z(at),
            "updated_at": Z(at)}


def reset():
    TAGS.clear()
    SCRIPTS.clear()
    API["runs"] = []
    for key in ("crawl_running", "crawl_request", *watch.WATCH_MEMORY):
        setting(key, "")
    # правило «1 час» смотрит и влитые обходы — свежих в копии быть не должно
    conn = db.connect()
    try:
        edge = (datetime.now(watch.KYIV) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
        conn.execute("DELETE FROM runs WHERE finished_at >= ? AND window_days > 0", (edge,))
        conn.commit()
    finally:
        conn.close()


def token(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    return m.group(1) if m else ""


BUTTONS = {"/crawl/emergency/order": {"days": "6"}, "/crawl/emergency/unmark": {},
           "/crawl/emergency/cancel": {}, "/crawl/emergency/github": {},
           "/crawl/emergency/reset": {}}

# ── 1. без входа и без CSRF ──────────────────────────────────────────────────
print("1. защита")
reset()
guest = app.test_client()
answers = [guest.post(url, data=data) for url, data in BUTTONS.items()]
check("без входа: каждая кнопка уводит на вход и ничего не делает",
      all(r.status_code == 302 and "/login" in r.headers["Location"] for r in answers)
      and TAGS == [] and SCRIPTS == [], [r.status_code for r in answers])
friend = app.test_client()
friend.post("/login", data={"password": "fr-test-1"})
answers = [friend.post(url, data=data) for url, data in BUTTONS.items()]
check("друг (не владелец): тоже на вход, ничего не сделано",
      all(r.status_code == 302 and "/login" in r.headers["Location"] for r in answers)
      and TAGS == [] and SCRIPTS == [])
owner = app.test_client()
owner.post("/login", data={"password": "adm-test-1"})
page = owner.get("/runs").get_data(as_text=True)
TOK = token(page)
answers = [owner.post(url, data=data) for url, data in BUTTONS.items()]
check("владелец без CSRF: 400 на каждой кнопке, ничего не сделано",
      all(r.status_code == 400 for r in answers) and TAGS == [] and SCRIPTS == [],
      [r.status_code for r in answers])
answers = [owner.post(url, data=dict(data, csrf_token="0" * 32)) for url, data in BUTTONS.items()]
check("владелец с чужим CSRF: тоже 400", all(r.status_code == 400 for r in answers))


def press(url, **data):
    return owner.post(url, data=dict(data, csrf_token=TOK))


# ── 2. блок на страницах ────────────────────────────────────────────────────
print("2. блок «Сбор расписания — экстренно»")
dash = owner.get("/").get_data(as_text=True)
for where, html in (("«Прогоны»", page), ("дашборд", dash)):
    check(f"{where}: блок и все кнопки на месте",
          "Сбор расписания — экстренно" in html
          and all(w in html for w in ("Заказать сбор сейчас: 6 дней", "Заказать сбор сейчас: 2 дня",
                                      "Проверить GitHub", "Снять отметку", "Остановить зависший сбор",
                                      "Сбросить память сторожа")))
check("опасные кнопки спрашивают подтверждение",
      len(re.findall(r'action="/crawl/emergency/(?:cancel|reset)"\s+onsubmit="return confirm', page)) == 2)
reset()
setting("crawl_running", f"идёт|{int(time.time()) - 150 * 60}|10:00|full-6")
html = owner.get("/runs").get_data(as_text=True)
check("что сейчас: сбор идёт 150 мин дольше потолка → «похоже, завис»",
      "похоже, завис" in html and "150 мин" in html)
conn = db.connect()
try:
    watch.note(conn, "ТРЕВОГА — тестовая тревога сторожа")
finally:
    conn.close()
html = owner.get("/").get_data(as_text=True)
check("последняя ТРЕВОГА видна с текстом", "Последняя ТРЕВОГА" in html and "тестовая тревога" in html)

# ── 3. «Заказать сбор сейчас» ───────────────────────────────────────────────
print("3. Заказать сбор сейчас")
reset()
edge = last_id()
r = press("/crawl/emergency/order", days="6")
check("свободно → та же заявка: сверка --check, затем настоящая (--manual, в фоне)",
      r.status_code == 302 and [s[0] for s in SCRIPTS] == [("days", "6", "--manual", "--check"),
                                                          ("days", "6", "--manual")]
      and [s[1] for s in SCRIPTS] == [False, True], SCRIPTS)
check("…ушёл один тег, заказ записан, отметка «заявка days-6»",
      TAGS == [("days", "6")] and (setting("crawl_request") or "").startswith("обход 6 сут.|")
      and setting("crawl_running").endswith("|days-6"), (TAGS, setting("crawl_request")))
check("…строка «владелец: заказал обход на 6 сут.» в «Прогонах»",
      any(n.startswith("владелец: заказал обход на 6 сут.") for n in notes_after(edge)), notes_after(edge))
check("…заказ кнопкой — не плановый: слот не трогает", setting("crawl_slot") == "")
reset()
setting("crawl_running", f"идёт|{int(time.time()) - 30 * 60}|10:00|full-6")
API["runs"] = [mkrun(30, status="in_progress")]
edge = last_id()
r = press("/crawl/emergency/order", days="2")
html = r.get_data(as_text=True)
check("идёт полный на 6 → заказ на 2 не отправлен, сказано почему",
      r.status_code == 200 and TAGS == [] and "не отправлен" in html and "уже идёт обход" in html,
      (TAGS, re.findall(r"не отправлен[^<]*", html)))
check("…рядом кнопка «Всё равно заказать 2 сут.» с подтверждением",
      "Всё равно заказать 2 сут." in html and 'name="force" value="1"' in html
      and "confirm(" in html)
check("…строка «владелец: заказ … не отправлен»",
      any(n.startswith("владелец: заказ обхода на 2 сут. не отправлен") for n in notes_after(edge)))
SCRIPTS.clear()
r = press("/crawl/emergency/order", days="2", force="1")
check("«Всё равно заказать» → заявка как у сторожа (--force --unlock), тег ушёл",
      SCRIPTS == [(("days", "2", "--manual", "--force", "--unlock"), True)] and TAGS == [("days", "2")],
      (SCRIPTS, TAGS))
check("…строка «в обход правил»", any("в обход правил" in n for n in notes_after(edge)))
reset()
setting("crawl_request", f"обход 6 сут.|{datetime.now(watch.KYIV):%Y-%m-%d %H:%M}")
r = press("/crawl/emergency/order", days="6")
check("заказ на 6 минуту назад (правило «1 час») → не отправлен, объяснено",
      TAGS == [] and "1 час" in r.get_data(as_text=True))
check("вывод заявки --check → слова владельцу без времени и служебных пометок",
      emergency._said("06.10 16:20 сторож: плановый обход 2 сут. не нужен (--check)\n"
                      "06.10 16:20 автомат days 2 пропущен: заказан обход 6 сут. в 16:10")
      == "плановый обход 2 сут. не нужен; автомат days 2 пропущен: заказан обход 6 сут. в 16:10")
reset()
check("глубина не 6 и не 2 → 400, ничего не делает",
      press("/crawl/emergency/order", days="5").status_code == 400
      and press("/crawl/emergency/order", days="x").status_code == 400 and SCRIPTS == [])

# ── 4. «Снять отметку „сбор идёт“» ──────────────────────────────────────────
print("4. Снять отметку")
reset()
setting("crawl_running", f"идёт|{int(time.time()) - 60}|10:00|proba-2")
edge = last_id()
r = press("/crawl/emergency/unmark")
check("отметка снята, строка «владелец: снял отметку … proba-2»",
      r.status_code == 302 and setting("crawl_running") == ""
      and any(n.startswith("владелец: снял отметку") and "proba-2" in n for n in notes_after(edge)),
      notes_after(edge))

# ── 5. «Проверить GitHub» ───────────────────────────────────────────────────
print("5. Проверить GitHub")
reset()
hung = mkrun(150, status="in_progress")
done = mkrun(300, conclusion="failure", title="Обход full-2")
API["runs"] = [hung, done]
edge = last_id()
html = press("/crawl/emergency/github").get_data(as_text=True)
check("живой список: оба прогона, у зависшего пометка и кнопка «Остановить»",
      f"#{hung['run_number']}" in html and f"#{done['run_number']}" in html and "— завис" in html
      and f'name="run_id" value="{hung["id"]}"' in html and "упал" in html)
check("…тегов не шлёт и ничего не меняет", TAGS == [])
check("…строка «владелец: проверил GitHub — сейчас #… (завис)»",
      any(n.startswith("владелец: проверил GitHub") and "(завис)" in n for n in notes_after(edge)),
      notes_after(edge))
API["runs"] = []
html = press("/crawl/emergency/github").get_data(as_text=True)
check("GitHub молчит → «не ответил», не падает", "не ответил" in html)

# ── 6. «Остановить зависший сбор» ──────────────────────────────────────────
print("6. Остановить зависший сбор")
reset()
API["runs"] = [hung, done]
edge = last_id()
r = press("/crawl/emergency/cancel")
check("зависший → тот же тег отмены, что у сторожа (btn-cancel-<id>)",
      TAGS == [("cancel", str(hung["id"]))], TAGS)
check("…записан в память отмен сторожа: он сам сверит остановку и второй не пошлёт",
      str(hung["id"]) in json.loads(setting("crawl_cancel") or "{}"))
check("…строка «владелец: остановил сбор»",
      any(n.startswith("владелец: остановил сбор") for n in notes_after(edge)))
reset()
going = mkrun(20, status="in_progress")
API["runs"] = [going]
r = press("/crawl/emergency/cancel")
check("зависших нет (идёт 20 мин) → ничего не отменяет и говорит, как остановить конкретный",
      TAGS == [] and any("зависших нет" in n for n in notes_after(last_id() - 1)))
r = press("/crawl/emergency/cancel", run_id=str(going["id"]))
check("кнопка у строки списка → отмена именно этого прогона",
      TAGS == [("cancel", str(going["id"]))], TAGS)
TAGS.clear()
press("/crawl/emergency/cancel", run_id=str(done["id"]))
check("прогон уже не идёт → отмены нет", TAGS == [])
check("номер не из цифр → 400", press("/crawl/emergency/cancel", run_id="1;rm").status_code == 400
      and TAGS == [])
reset()
press("/crawl/emergency/cancel")
check("GitHub молчит → отмены нет, строка «GitHub не ответил»",
      TAGS == [] and any("не ответил" in n for n in notes_after(last_id() - 1)))

# ── 7. «Сбросить память сторожа» ───────────────────────────────────────────
print("7. Сбросить память сторожа")
reset()
stamp_ = f"{datetime.now(watch.KYIV):%Y-%m-%d %H:%M}"
setting("crawl_request", f"обход 6 сут.|{stamp_}")
setting("crawl_running", f"идёт|{int(time.time())}|10:00|full-6")
for key in watch.WATCH_MEMORY:
    setting(key, json.dumps({"state": "missed", "slot": "2026-10-06 16:15"}))
edge = last_id()
r = press("/crawl/emergency/reset")
state = json.loads(setting("crawl_watch") or "{}")
check("вся память сторожа стёрта, кроме пометки текущего заказа",
      all(setting(k) == "" for k in watch.WATCH_MEMORY if k != "crawl_watch")
      and state == {"order": stamp_, "reset": True}, state)
check("…заказ и отметку «сбор идёт» не трогает",
      setting("crawl_request").endswith(stamp_) and setting("crawl_running") != "")
order_ = watch.parse_order(setting("crawl_request"))
check("…сторож за этим заказом больше не следит (С4: «всё решено»)",
      watch.decide(order_, None, datetime.now(watch.KYIV) + timedelta(hours=1), state,
                   "unknown")[0] == "closed")
check("…строка «владелец: память сторожа стёрта»",
      any(n.startswith("владелец: память сторожа стёрта") for n in notes_after(edge)))

print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, красных: {len(failed)}")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)

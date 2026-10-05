# -*- coding: utf-8 -*-
r"""Проверки входа друзей и кнопок сбора (владелец 05.10.2026): гость, друг,
владелец; скан даты другом; правило «недавно уже собирали»; правило «1 час»
плановых заявок; устаревание отметки пробы.

В сеть не ходит и настоящий обход не запускает: запуск обхода, тег-заявка и
ожидание GitHub подменены заглушками. База — КОПИЯ во временной папке,
журнал посещений туда же. Запуск:

    python scripts/test_friend.py
    python scripts/test_friend.py --db ..\streams-crawl\data\channel_schedule.db

Без `--db` — копия `data/channel_schedule.db` этого репо, а нет её — пустая
база. Выход 0 — все проверки зелёные. Часы машины должны идти по Киеву (так
пишет время заказа и сама кнопка, `_dispatch`).
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

ARGS = argparse.ArgumentParser()
ARGS.add_argument("--db", help="база, копию которой взять")
OPTS = ARGS.parse_args()

TMP = Path(tempfile.mkdtemp(prefix="friend-test-"))
src = Path(OPTS.db) if OPTS.db else ROOT / "data" / "channel_schedule.db"
if src.exists():
    shutil.copy(src, TMP / "test.db")
(TMP / "visits").mkdir()
os.environ.update(STREAMS_DB=str(TMP / "test.db"), STREAMS_ADMIN_PASSWORD="adm-test-1",
                  STREAMS_FRIEND_PASSWORD="fr-test-1", SECRET_KEY="k" * 32,
                  STREAMS_VISITS_DIR=str(TMP / "visits"))
os.environ.pop("STREAMS_LOCAL", None)

from app import crawl_hook, db, trigger, visits, watch, web  # noqa: E402

# ── заглушки: ни обхода, ни тегов, ни GitHub ─────────────────────────────────
calls: list[tuple] = []
trigger.dispatch_crawl = lambda days, date="", **k: (calls.append(("dispatch", days, date)) or (True, "тест"))
trigger.push_request_tag = lambda kind, value: (calls.append(("tag", kind, value)) or (True, "тест"))
trigger._repo_slug = lambda: "test/test"
watch.wait_for_start = lambda order, slug, **k: {"run_number": 0}
crawl_hook.start_pull = lambda: "тест"
crawl_hook.start_site_crawl = lambda domain: (False, "тест")
visits.write = lambda *a, **k: None          # журнал в тесте не пишем

db.init_db()
app = web.create_app()
KYIV = crawl_hook.KYIV
passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def token(html):
    m = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    return m.group(1) if m else ""


def now_kyiv() -> datetime:
    return datetime.now(KYIV).replace(tzinfo=None)


def sql(query, args=()):
    conn = db.connect()
    try:
        conn.execute(query, args)
        conn.commit()
    finally:
        conn.close()


def setting(key, value=None):
    conn = db.connect()
    try:
        if value is None:
            return db.get_setting(conn, key)
        db.set_setting(conn, key, value)
    finally:
        conn.close()


def reset():
    """Чистый лист: ни свежих обходов, ни отметки «идёт», ни пауз друзей."""
    calls.clear()
    for key in ("crawl_running", "crawl_request", "public_run_at",
                "public_date_run_at", "date_scan_request"):
        setting(key, "")
    edge = (now_kyiv() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    sql("DELETE FROM runs WHERE finished_at >= ?", (edge,))


def add_run(minutes_ago, days, who="", mode=""):
    """Влитый обход, как его пишет заливка (`store`): время — киевское."""
    import json
    at = (now_kyiv() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M")
    sql("INSERT INTO runs (finished_at, window_days, log) VALUES (?, ?, ?)",
        (at, days, json.dumps({"режим": mode or f"полный обход, окно {days} суток",
                               "кто": who}, ensure_ascii=False)))
    return now_kyiv() - timedelta(minutes=minutes_ago)


def order(minutes_ago, days):
    at = now_kyiv() - timedelta(minutes=minutes_ago)
    setting("crawl_request", f"обход {days} сут.|{at:%Y-%m-%d %H:%M}")


def running(state, minutes_ago, what):
    setting("crawl_running", f"{state}|{int(time.time()) - minutes_ago * 60}|00:00|{what}")


def run_btn(client, days, tok):
    r = client.post("/schedule/run", data={"days": str(days), "csrf_token": tok},
                    follow_redirects=True)
    return r.get_data(as_text=True)


def date_btn(client, value, tok):
    r = client.post("/schedule/date", data={"date": value, "csrf_token": tok},
                    follow_redirects=True)
    return r.get_data(as_text=True)


def day(n: int) -> str:
    return (now_kyiv().date() + timedelta(days=n)).isoformat()


if abs((datetime.now() - now_kyiv()).total_seconds()) > 120:
    print("ВНИМАНИЕ: часы машины не киевские — проверки «1 час» могут врать")
reset()

# ── 1. гость ─────────────────────────────────────────────────────────────────
print("1. гость с улицы")
c = app.test_client()
r = c.get("/schedule"); page = r.get_data(as_text=True)
check("витрина открывается", r.status_code == 200)
check("кнопок сбора нет", "Collect 2 days" not in page and "Collect 5 days" not in page
      and "Collect a date" not in page)
check("поля PIN нет", 'name="pin"' not in page)
check("есть ссылка Sign in", "Sign in" in page)
r = app.test_client().post("/schedule/run", data={"days": "2"})
check("POST без куки и токена → 400", r.status_code == 400, r.status_code)
r = app.test_client().post("/schedule/date", data={"date": day(1)})
check("дата: POST без куки и токена → 400", r.status_code == 400, r.status_code)
with c.session_transaction() as s:
    s["csrf_token"] = "abc123"
r = c.post("/schedule/run", data={"days": "2", "csrf_token": "abc123"})
check("гость с токеном: сбор не запущен", r.status_code == 302 and not calls, (r.status_code, calls))
r = c.post("/schedule/date", data={"date": day(1), "csrf_token": "abc123"}, follow_redirects=True)
check("гость с токеном: скан даты не запущен", not calls and "Sign in to run" in r.get_data(as_text=True), calls)
r = c.post("/schedule/date", data={"date": day(1), "csrf_token": "wrong"})
check("дата: чужой токен → 400", r.status_code == 400 and not calls, r.status_code)
r = c.get("/visits")
check("админка гостю закрыта", r.status_code == 302 and "/login" in r.headers["Location"])

# ── 2. друг: вход, кнопки, админка закрыта ───────────────────────────────────
print("2. друг")
f = app.test_client()
r = f.post("/login", data={"password": "nope"})
check("неверный пароль не пускает", "Неверный пароль" in r.get_data(as_text=True))
r = f.post("/login", data={"password": "fr-test-1"})
check("пароль друзей → на витрину", r.status_code == 302 and r.headers["Location"].endswith("/schedule"), r.headers.get("Location"))
r = f.get("/schedule"); page = r.get_data(as_text=True)
ft = token(page)
check("друг видит обе кнопки", "Collect 2 days" in page and "Collect 5 days" in page)
check("друг видит выбор даты", "Collect a date" in page and 'action="/schedule/date"' in page
      and 'id="friend-date"' in page)
check("форма даты — с токеном", re.search(r'action="/schedule/date">\s*<input type="hidden" name="csrf_token" value="[0-9a-f]+"', page) is not None)
check("друг не видит кнопок владельца", "Обход 6 дней" not in page and "Скан даты" not in page and "admin-mark\" href" not in page)
for path in ("/", "/sources", "/visits", "/settings", "/runs"):
    r = f.get(path)
    check(f"админка {path} другу закрыта", r.status_code == 302 and "/login" in r.headers["Location"], r.status_code)
r = f.post("/crawl/run", data={"days": "6", "csrf_token": ft})
check("кнопка владельца «6 дней» другу закрыта", r.status_code == 302 and "/login" in r.headers["Location"] and not calls)
r = f.post("/crawl/day", data={"date": day(1), "csrf_token": ft})
check("«Скан даты» владельца другу закрыт", r.status_code == 302 and "/login" in r.headers["Location"] and not calls)
r = f.post("/schedule/run", data={"days": "6", "csrf_token": ft})
check("друг просит 6 дней → уходит 5", calls == [("dispatch", 5, "")], calls)
check("заказ записан: «обход 5 сут.»", setting("crawl_request").startswith("обход 5 сут.|"))
calls.clear()
setting("crawl_running", "")
text = run_btn(f, 2, ft)
check("сразу второй сбор друга не проходит (только что был на 5 дней)",
      not calls and "no need to run again" in text, calls)
setting("crawl_request", "")
text = run_btn(f, 2, ft)
check("…и часовая пауза друга на месте", not calls and "Please wait" in text, calls)

# ── 3. друг: скан даты ───────────────────────────────────────────────────────
print("3. друг — скан даты")
reset()
for bad in ("2026-10-6", "06.10.2026", "", "2026-13-01", "2026-02-30", "２０２６-10-06",
            day(1) + "T00:00", day(1) + " ", "<script>", day(1) + "\n2026-01-01"):
    text = date_btn(f, bad, ft)
    check(f"не тот формат {bad!r} — отказ без запуска",
          not calls and ("Date not recognised" in text or "Pick a date" in text), calls)
check("отказ по формату паузу не тратит", setting("public_date_run_at") == "")
for n in (-1, 7, 30):
    text = date_btn(f, day(n), ft)
    check(f"вне окна (сегодня {n:+d}) — отказ", not calls and "Pick a date from today to +6" in text, calls)
text = date_btn(f, day(6), ft)
check("сегодня +6 — запущен скан даты", calls == [("dispatch", 2, day(6))], calls)
check("отметка «сбор заказан» — date-…", setting("crawl_running").split("|")[-1] == f"date-{day(6)}")
check("пауза даты записана", setting("public_date_run_at") != "")
check("часовая пауза 2/5 дней не тронута", setting("public_run_at") == "")
calls.clear()
text = date_btn(f, day(3), ft)
check("пока сбор заказан — второй не запускается", not calls and "already requested" in text, calls)
setting("crawl_running", "")
text = date_btn(f, day(3), ft)
check("вторая дата в течение 2 часов — отказ", not calls and "One date per 2 hours" in text, calls)
text = run_btn(f, 2, ft)
check("а сбор на 2 дня у друга отдельной паузой — идёт", calls == [("dispatch", 2, "")], calls)
calls.clear(); setting("crawl_running", ""); setting("crawl_request", "")
setting("public_date_run_at", str(time.time() - 2 * 3600 + 60))
text = date_btn(f, day(3), ft)
check("за минуту до конца паузы — ещё отказ", not calls and "~1 min" in text, calls)
setting("public_date_run_at", str(time.time() - 2 * 3600 - 60))
text = date_btn(f, day(3), ft)
check("2 часа прошли — дата снова доступна", calls == [("dispatch", 2, day(3))], calls)
check("у пульта есть заказ скана даты", setting("day_scan_request").startswith(day(3)))

# ── 4. «недавно уже собирали» ────────────────────────────────────────────────
print("4. недавно уже собирали — не запускать")
reset()
add_run(50, 6)
text = run_btn(f, 2, ft)
check("сбор на 6 дней 50 мин назад → 2 дня не запускаем",
      not calls and "Data was collected 50 min ago (6-day run) — no need to run again." in text, calls)
text = run_btn(f, 5, ft)
check("…и 5 дней тоже", not calls and "no need to run again" in text, calls)
check("отказ «недавно собирали» паузу друга не тратит", setting("public_run_at") == "")
text = date_btn(f, day(2), ft)
check("…и дата внутри окна 6 дней", not calls and "is already covered" in text
      and "6-day run" in text, calls)
text = date_btn(f, day(6), ft)
check("а сегодня +6 окно 6 дней не покрывает — скан идёт", calls == [("dispatch", 2, day(6))], calls)

reset()
add_run(130, 6)
text = run_btn(f, 2, ft)
check("сбор на 6 дней 2 часа назад → 2 дня можно", calls == [("dispatch", 2, "")], calls)

reset()
add_run(20, 2)
text = run_btn(f, 2, ft)
check("сбор на 2 дня 20 мин назад → 2 дня нельзя", not calls and "(2-day run)" in text, calls)
text = run_btn(f, 5, ft)
check("…а 5 дней можно (глубже)", calls == [("dispatch", 5, "")], calls)
reset()
first = add_run(20, 2).date()
text = date_btn(f, (first + timedelta(days=1)).isoformat(), ft)
check("дата внутри окна 2 дней (завтра) — отказ", not calls and "is already covered" in text, calls)
text = date_btn(f, (first + timedelta(days=2)).isoformat(), ft)
check("дата за окном 2 дней (послезавтра) — скан идёт", len(calls) == 1, calls)

reset()
order(10, 6)
text = run_btn(f, 2, ft)
check("обход 6 дней заказан 10 мин назад → «was started», не запускаем",
      not calls and "A 6-day collection was started 10 min ago" in text, calls)
reset()
running("идёт", 5, "full-6")
text = run_btn(f, 5, ft)
check("сбор идёт → не запускаем", not calls and "already running" in text, calls)
text = date_btn(f, day(1), ft)
check("сбор идёт → и дату не запускаем", not calls and "already running" in text, calls)

reset()
add_run(10, 6, who="сервер mojtv.hr")
add_run(10, None, who="", mode="скан даты " + day(0))
add_run(10, None, who="автомат", mode="автомат: заметка")
text = run_btn(f, 2, ft)
check("серверный сбор mojtv, скан даты и заметки «Прогонов» — не в счёт", calls == [("dispatch", 2, "")], calls)

# ── 5. владелец — как было, без ограничений ──────────────────────────────────
print("5. владелец")
a = app.test_client()
r = a.post("/login?next=//evil.example/x", data={"password": "adm-test-1"})
check("чужой адрес в next не действует", r.status_code == 302 and "evil" not in r.headers["Location"], r.headers.get("Location"))
a2 = app.test_client()
r = a2.post("/login?next=/visits", data={"password": "adm-test-1"})
check("свой путь в next работает", r.status_code == 302 and r.headers["Location"].endswith("/visits"), r.headers.get("Location"))
r = a.get("/schedule"); page = r.get_data(as_text=True)
at = token(page)
check("владелец видит все кнопки", all(x in page for x in ("Collect 2 days", "Collect 5 days", "Обход 6 дней", "Скан даты")))
check("кнопки друга «Collect a date» у владельца нет", "Collect a date" not in page)
reset()
add_run(5, 6)
r = a.post("/schedule/run", data={"days": "5", "csrf_token": at})
check("владелец: сбор без паузы и без «недавно собирали»", calls == [("dispatch", 5, "")], calls)
reset(); add_run(5, 6)
r = a.post("/schedule/run", data={"days": "2", "csrf_token": at})
setting("crawl_running", "")              # первый прошёл — замок снят
r = a.post("/schedule/run", data={"days": "2", "csrf_token": at})
check("владелец: два раза подряд — оба уходят", calls == [("dispatch", 2, "")] * 2, calls)
reset(); add_run(5, 6)
r = a.post("/crawl/run", data={"days": "6", "csrf_token": at})
check("владелец: «Обход 6 дней» как был", calls == [("dispatch", 6, "")], calls)
reset(); add_run(5, 6)
r = a.post("/crawl/day", data={"date": day(13), "csrf_token": at})
check("владелец: «Скан даты» до +13 как был", calls == [("dispatch", 2, day(13))], calls)
reset(); add_run(5, 6); setting("public_date_run_at", str(time.time()))
r = a.post("/schedule/date", data={"date": day(2), "csrf_token": at})
check("владелец через дату друга — без паузы и «недавно»", calls == [("dispatch", 2, day(2))], calls)
r = a.get("/visits")
check("админка владельцу открыта", r.status_code == 200, r.status_code)

# ── 6. правило «1 час» плановых заявок ───────────────────────────────────────
print("6. плановые заявки (request_crawl.main с заглушками)")
spec = importlib.util.spec_from_file_location("request_crawl", ROOT / "scripts" / "request_crawl.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)


def planned(days: int) -> bool:
    """Плановая заявка: ушла ли тег-заявка. Сеть — заглушки выше."""
    calls.clear()
    saved = sys.argv
    sys.argv = ["request_crawl.py", "days", str(days)]
    try:
        rc.main()
    finally:
        sys.argv = saved
    return ("tag", "days", str(days)) in calls


def friend_press(days):
    reset()
    run_btn(f, days, ft)
    pressed = list(calls)
    setting("crawl_running", "")          # сбор друга прошёл, замок снят
    return pressed


check("друг нажал 2 дня → плановый на 6 всё равно уходит",
      friend_press(2) == [("dispatch", 2, "")] and planned(6))
check("друг нажал 2 дня → плановый на 2 отменён (правило «1 час»)",
      friend_press(2) == [("dispatch", 2, "")] and not planned(2))
check("друг нажал 5 дней → плановый на 6 всё равно уходит",
      friend_press(5) == [("dispatch", 5, "")] and planned(6))
reset(); date_btn(f, day(1), ft); setting("crawl_running", "")
check("друг сканировал дату → плановые 2 и 6 уходят", planned(2) and planned(6))
reset(); add_run(30, 6)
check("собран обход 6 дней 30 мин назад → плановый на 2 отменён", not planned(2))
conn = db.connect()
try:
    note = conn.execute("SELECT log FROM runs ORDER BY id DESC LIMIT 1").fetchone()["log"]
    words = rc.recent_full(conn, 2, datetime.now(KYIV))
finally:
    conn.close()
check("отмена видна в «Прогонах»", "плановый обход 2 сут. отменён" in note, note)
check("слова отмены прежние", re.fullmatch(r"собран обход 6 сут\. в \d\d:\d\d", words) is not None, words)
reset(); add_run(30, 6)
check("…а плановый на 6 после 6-дневного полчаса назад — тоже отменён", not planned(6))
reset(); a.post("/crawl/run", data={"days": "6", "csrf_token": at}); setting("crawl_running", "")
check("владелец нажал 6 дней → плановый на 2 отменён", not planned(2))
reset(); add_run(70, 6)
check("сбор на 6 дней 70 мин назад → плановый на 2 уходит", planned(2))

print("   замок «сбор идёт» и плановые заявки")
reset(); running("идёт", 10, "full-2")
check("идёт сбор друга на 2 дня → плановый на 6 встаёт в очередь (уходит)", planned(6))
check("…отметку идущего сбора не перетирает", setting("crawl_running").endswith("|full-2"))
reset(); running("заявка", 2, "days-5")
check("заказан сбор на 5 дней → плановый на 6 уходит", planned(6))
reset(); running("идёт", 10, "full-6")
check("идёт сбор на 6 дней → плановый на 2 не шлём", not planned(2))
reset(); running("идёт", 10, "full-2")
check("идёт сбор на 2 дня → плановый на 2 не шлём", not planned(2))
reset(); running("идёт", 10, f"date-{day(1)}")
check("идёт скан даты → плановый держит замок, как было", not planned(6))
reset(); running("идёт", 5, "proba-2")
check("идёт проба → плановый на 2 уходит", planned(2))
check("…отметку пробы не перетирает", setting("crawl_running").endswith("|proba-2"))

# ── 7. устаревание отметки «идёт» ────────────────────────────────────────────
print("7. отметка пробы устаревает через 20 минут")


def busy_after(state, minutes, what):
    running(state, minutes, what)
    conn = db.connect()
    try:
        return crawl_hook.running(conn) is not None
    finally:
        conn.close()


check("проба proba-2: 21 мин → свободно", not busy_after("идёт", 21, "proba-2"))
check("проба probeurl-…: 21 мин → свободно", not busy_after("идёт", 21, "probeurl-ok-200"))
check("проба: 19 мин → ещё идёт", busy_after("идёт", 19, "proba-2"))
check("настоящий обход full-6: 21 мин → всё ещё идёт", busy_after("идёт", 21, "full-6"))
check("скан даты: 21 мин → всё ещё идёт", busy_after("идёт", 21, f"date-{day(1)}"))
check("точечный site-…: 21 мин → всё ещё идёт", busy_after("идёт", 21, "site-nova.bg"))
check("настоящий обход: 3 ч 01 мин → свободно (как было)", not busy_after("идёт", 181, "full-6"))
check("заявка: 21 мин → свободно (как было)", not busy_after("заявка", 21, "days-6"))
reset()
running("идёт", 25, "proba-2")
text = run_btn(f, 2, ft)
check("друг после зависшей пробы (25 мин) может собрать", calls == [("dispatch", 2, "")], calls)

# ── 8. выход друга ───────────────────────────────────────────────────────────
print("8. выход друга")
f2 = app.test_client()
f2.post("/login", data={"password": "fr-test-1"})
f2.get("/logout")
page = f2.get("/schedule").get_data(as_text=True)
check("после выхода друг снова гость", "Collect 2 days" not in page and "Collect a date" not in page
      and "Sign in" in page)

print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, красных: {len(failed)}")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)

# -*- coding: utf-8 -*-
"""Блок «Сбор расписания — экстренно» в админке (владелец 06.10.2026).

Сторож (`app/watch.py`, `scripts/crawl_watch.py`) сам доводит каждый
плановый сбор до конца или пишет ТРЕВОГУ. Эти кнопки — на случай, когда
владелец хочет вмешаться руками. Своей логики у них НЕТ — каждая зовёт то
же, что заявка и сторож:

  Заказать сбор сейчас   → `scripts/request_crawl.py days N --manual`: те же
                           правила, что у плановой заявки (очередь, «идёт
                           полный не меньшей глубины», «1 час»). Сначала та
                           же заявка с `--check`: не пошла бы — кнопка
                           говорит почему и предлагает «Всё равно заказать»
                           (`--force --unlock`, как заказывает сторож)
  Снять отметку          → `crawl_hook.clear`
  Остановить зависший    → `watch.stuck` + `watch.send_cancel` (правило С3)
  Проверить GitHub       → `watch.github_runs` + `watch.stuck`
  Сбросить память        → `watch.reset_memory`

Каждое нажатие — строка «владелец: …» в «Прогонах» (`watch.note`), как
решения сторожа. Опасные кнопки (остановить, сбросить, всё равно заказать)
спрашивают подтверждение в браузере (шаблон `_emergency.html`).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

from . import crawl_hook, db, trigger, watch

WHO = "владелец"
SCRIPT = db.ROOT / "scripts" / "request_crawl.py"
#: сверка «пошла бы заявка» делает не больше одного запроса к GitHub (до 20 с)
CHECK_TIMEOUT_SECONDS = 60
#: глубины, которые можно заказать кнопкой (как у плановых заявок)
ORDER_DAYS = (6, 2)
#: сколько последних заказов книги показать в блоке «что сейчас»
STATUS_ORDERS = 3


def _now() -> datetime:
    return datetime.now(watch.KYIV)


def run_script(args: list[str], background: bool) -> tuple[bool, str]:
    """Запустить `request_crawl.py` с ключами `args`. background — отдельной
    службой systemd, как забор и «Обойти сайт» (заявка ждёт старта до 5
    минут, сайт столько не ждёт); иначе — ждём и возвращаем её вывод."""
    try:
        if background:
            subprocess.run(
                ["systemd-run", "--no-block", "--collect",
                 "--unit", f"streams-order-{int(time.time())}",
                 sys.executable, str(SCRIPT), *args],
                check=True, capture_output=True, timeout=20)
            return True, "заявка запущена"
        r = subprocess.run([sys.executable, str(SCRIPT), *args],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=CHECK_TIMEOUT_SECONDS)
        return r.returncode == 0, (r.stdout or r.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"сервер не запустил заявку: {type(e).__name__}"


def _said(out: str) -> str:
    """Вывод заявки `--check` → слова для владельца: без времени в начале
    строк и без пометок «(--check)»."""
    lines = []
    for line in out.splitlines():
        line = line.strip()
        if line[:2].isdigit() and line[2:3] == "." and line[5:6] == " ":
            line = line[12:]                    # «06.10 16:20 » — время строки
        line = line.replace(" (--check)", "").removeprefix("сторож: ")
        if line:
            lines.append(line)
    return "; ".join(lines) or "заявка ничего не ответила"


# ── кнопки ───────────────────────────────────────────────────────────────────

def order(conn: sqlite3.Connection, days: int, force: bool) -> dict:
    """«Заказать сбор сейчас» / «Всё равно заказать». {ok, refused, words}:
    refused — правила заявки заказ не пустили, `words` — почему."""
    if force:
        ok, out = run_script(["days", str(days), "--manual", "--force", "--unlock"],
                             background=True)
        words = (f"заказал обход на {days} сут. в обход правил («всё равно "
                 f"заказать») — {out}" if ok else
                 f"обход на {days} сут. заказать не вышло: {out}")
        watch.note(conn, words, who=WHO)
        return {"ok": ok, "refused": False, "words": words}
    ok, out = run_script(["days", str(days), "--manual", "--check"], background=False)
    if not (ok and "ПОШЛА БЫ" in out):
        words = f"заказ обхода на {days} сут. не отправлен: {_said(out)}"
        watch.note(conn, words, who=WHO)
        return {"ok": False, "refused": True, "words": words}
    ok, out = run_script(["days", str(days), "--manual"], background=True)
    words = (f"заказал обход на {days} сут. — {out}; итог заявки — строкой "
             f"«автомат» в «Прогонах» через 1–5 мин" if ok else
             f"обход на {days} сут. заказать не вышло: {out}")
    watch.note(conn, words, who=WHO)
    return {"ok": ok, "refused": False, "words": words}


def unmark(conn: sqlite3.Connection) -> str:
    """«Снять отметку „сбор идёт“»: сервер ошибочно считает, что сбор идёт,
    и кнопки сбора не пускают."""
    busy = crawl_hook.running(conn)
    crawl_hook.clear(conn)
    words = (f"снял отметку «сбор {busy['state']}» («{busy['what']}» с "
             f"{busy['since']})" if busy else
             "снял отметку «сбор идёт» (живой отметки и не было)")
    watch.note(conn, words, who=WHO)
    return words


def _run_line(r: dict, now: datetime, stuck_ids: set) -> dict:
    """Прогон GitHub → строка таблицы для владельца."""
    kind, days = watch.run_kind(r)
    status = r.get("status") or ""
    created = watch._utc(r.get("created_at") or "")
    if status in watch.RUNNING:
        start = watch._utc(r.get("run_started_at") or "") or created or now
        minutes = int((now - start).total_seconds() // 60)
        state = (f"идёт {minutes} мин" if status == "in_progress"
                 else f"ждёт очереди {minutes} мин")
    else:
        state = {"success": "✅ готов", "failure": "❌ упал",
                 "cancelled": "⏹ отменён"}.get(r.get("conclusion") or "",
                                               r.get("conclusion") or "?")
    rid = str(r.get("id"))
    return {"id": rid, "number": r.get("run_number"),
            "what": watch.describe(kind, days), "at": watch.hm(created),
            "state": state, "active": status in watch.RUNNING,
            "stuck": rid in stuck_ids}


def github(conn: sqlite3.Connection) -> dict:
    """«Проверить GitHub»: живой список последних прогонов обхода.
    {ok, rows, words}; ok False — GitHub не ответил."""
    now = _now()
    slug = trigger._repo_slug()
    runs = watch.github_runs(slug, workflow=watch.CRAWL_WORKFLOW)
    if not runs:
        words = "проверил GitHub — он не ответил на список прогонов"
        watch.note(conn, words, who=WHO)
        return {"ok": False, "rows": [], "words": words}
    stuck_ids = {str(s["run"].get("id")) for s in watch.stuck(
        runs, now, slug, watch.load_json(conn, "crawl_queue"))}
    queue_ids = {str(w["run"].get("id")) for w in watch.queue_waits(runs, now, slug)}
    rows = [_run_line(r, now, stuck_ids) for r in watch.crawl_only(runs, slug)]
    for row in rows:
        if row["id"] in queue_ids:
            row["state"] += " — очередь GitHub стоит, впереди никого"
    active = [r for r in rows if r["active"]]
    words = ("проверил GitHub — сейчас " +
             (", ".join(f"#{r['number']} {r['what']}: {r['state']}"
                        + (" (завис)" if r["stuck"] else "") for r in active)
              if active else "ничего не идёт"))
    watch.note(conn, words, who=WHO)
    return {"ok": True, "rows": rows, "words": words}


#: ответ кнопки, если общий замок занят: сторож или заявка сейчас пишут ту же
#: память, и запись кнопки затёрлась бы в конце их работы
BUSY = ("сторож сейчас работает (идёт его проверка или заявка) — повторите "
        "через минуту")


def cancel(conn: sqlite3.Connection, run_id: str = "") -> tuple[bool, str]:
    """«Остановить зависший сбор»: без `run_id` — все прогоны, которые сторож
    счёл бы зависшими (`watch.stuck`); с `run_id` — этот идущий прогон
    (кнопка у строки списка GitHub). Заявка отмены — та же, что у сторожа
    (`watch.send_cancel`), и в ту же память: остановку сверит сторож (С3).
    Память пишется под общим замком (`watch.order_lock`)."""
    with watch.order_lock(watch.LOCK_WAIT_BUTTON) as held:
        if not held:
            watch.note(conn, f"хотел остановить сбор — {BUSY}", who=WHO)
            return False, BUSY
        return _cancel(conn, run_id)


def _cancel(conn: sqlite3.Connection, run_id: str) -> tuple[bool, str]:
    now = _now()
    slug = trigger._repo_slug()
    runs = watch.github_runs(slug, workflow=watch.CRAWL_WORKFLOW)
    if not runs:
        words = "хотел остановить сбор, но GitHub не ответил на список прогонов"
        watch.note(conn, words, who=WHO)
        return False, words
    active = watch.active_crawls(runs, slug)
    if run_id:
        targets = [r for r in active if str(r.get("id")) == run_id]
        if not targets:
            words = "хотел остановить прогон, но он уже не идёт"
            watch.note(conn, words, who=WHO)
            return False, words
    else:
        queue = watch.load_json(conn, "crawl_queue")
        targets = [s["run"] for s in watch.stuck(runs, now, slug, queue)]
        if not targets:
            going = ", ".join(f"#{r.get('run_number')} "
                              f"{watch.describe(*watch.run_kind(r))}" for r in active)
            words = ("хотел остановить зависший сбор — по меркам сторожа зависших "
                     "нет" + (f" (идёт {going}; остановить его можно кнопкой у "
                              f"строки после «Проверить GitHub»)" if going
                              else ", на GitHub ничего не идёт"))
            watch.note(conn, words, who=WHO)
            return False, words
    cancels = watch.load_json(conn, "crawl_cancel")
    said, all_ok = [], True
    for r in targets:
        ok, answer = watch.send_cancel(cancels, r, now)
        all_ok = all_ok and ok is not False
        said.append(f"#{r.get('run_number')} — "
                    + ("заявка отмены ушла" if ok else
                       f"заявка могла не дойти ({answer})" if ok is None else
                       f"заявка не ушла ({answer})"))
    watch.save_json(conn, "crawl_cancel", cancels)
    words = (f"остановил сбор: {'; '.join(said)}. Сторож сверит остановку и, "
             f"если это был плановый, сам закажет досрочный")
    watch.note(conn, words, who=WHO)
    return all_ok, words


def reset(conn: sqlite3.Connection) -> tuple[bool, str]:
    """«Сбросить память сторожа» — если он запутался. Под общим замком
    (`watch.order_lock`): иначе конец идущей проверки записал бы память
    обратно."""
    with watch.order_lock(watch.LOCK_WAIT_BUTTON) as held:
        if not held:
            watch.note(conn, f"хотел сбросить память сторожа — {BUSY}", who=WHO)
            return False, BUSY
        words = watch.reset_memory(conn)
    watch.note(conn, words, who=WHO)
    return True, words


# ── что сейчас ───────────────────────────────────────────────────────────────

def status(conn: sqlite3.Connection) -> dict:
    """Строки «что сейчас» для блока — только из базы, к GitHub не ходит.
    {lines: [{cls, text}], alarm: {at, text} | None}."""
    lines = []
    busy = crawl_hook.running(conn)
    if busy is None:
        lines.append({"cls": "ok", "text": "Сейчас сбор не идёт."})
    else:
        minutes = int(busy["age"] // 60)
        limit = watch.ceiling(*watch.parse_what(busy["what"]))
        if busy["state"] == "идёт" and minutes > limit:
            lines.append({"cls": "error", "text":
                          f"Сбор «{busy['what']}» идёт {minutes} мин (с {busy['since']}) "
                          f"— дольше обычного ({limit} мин), похоже, завис. Сторож "
                          f"сверится с GitHub и остановит его сам; можно и "
                          f"кнопкой «Остановить зависший сбор»."})
        else:
            lines.append({"cls": "ok", "text":
                          f"Сбор «{busy['what']}» {busy['state']} с {busy['since']} "
                          f"({minutes} мин)."})
    # книга заказов: последние заказы, по строке на каждый
    for rec in watch.load_orders(conn)[-STATUS_ORDERS:]:
        how = ("дошёл" if rec.get("done") else
               "сорвался" if rec.get("failed") else
               "сторож за ним не следит (память сброшена)" if rec.get("reset")
               else "сторож следит за ним")
        lines.append({"cls": "error" if how == "сорвался" else "ok",
                      "text": f"Заказ {rec['what']} от {rec['order']} — {how}."})
    missed = watch.load_json(conn, "crawl_missed")
    if missed.get("state") == "missed":
        lines.append({"cls": "error", "text":
                      f"Плановый {watch.clock(missed.get('slot', ''))} сорвался — "
                      f"сторож решит на ближайшей проверке (раз в 15 мин)."})
    early = watch.load_json(conn, "crawl_early")
    if early.get("state") in ("ordering", "ordered"):
        lines.append({"cls": "ok", "text":
                      f"Идёт досрочный обход за плановый "
                      f"{watch.clock(early.get('for', ''))} (заказан "
                      f"{watch.clock(early.get('ordered_at') or early.get('begun', ''))})."})
    silent = watch.load_json(conn, "crawl_silent")
    if silent.get("since"):
        lines.append({"cls": "error", "text":
                      f"GitHub не отвечает сторожу с {watch.clock(silent['since'])}."})
    row = conn.execute("SELECT finished_at, log FROM runs WHERE log LIKE ? "
                       "ORDER BY id DESC LIMIT 1", ("%ТРЕВОГА%",)).fetchone()
    alarm = None
    if row:
        try:
            text = (json.loads(row["log"] or "{}") or {}).get("режим") or ""
        except ValueError:
            text = row["log"] or ""
        alarm = {"at": row["finished_at"], "text": text}
    return {"lines": lines, "alarm": alarm, "days": ORDER_DAYS}

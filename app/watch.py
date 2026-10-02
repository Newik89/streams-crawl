# -*- coding: utf-8 -*-
"""Сторож заказа обхода (владелец 02.10.2026): сервер сам убеждается, что
заказанный обход пошёл и дошёл до конца, даже если GitHub не постучал.

Цепочка как была: сервер заказывает (`scripts/request_crawl.py`, тег) → GitHub
обходит → стучит «начал»/«закончил» (`app/crawl_hook`) → сервер забирает.
Сторож закрывает её дыры:
  1. заявка ушла, а обход не стартовал за 3 мин — повторить заявку, один
     раз на заказ (`request_crawl.py` делает это сам сразу после заявки,
     сторож — страховка по cron);
  2. обход кончился, а стука «закончил» нет 10 мин — забрать самому
     (`scripts/hook_pull.sh`, тот же путь, что по стуку);
  3. обход упал или оборван (GitHub режет через 150 мин, `crawl.yml`) —
     повторить заявку один раз; упал и повтор — строка тревоги, дальше
     ничего не заказываем, чтобы при лежащем GitHub не крутить по кругу.
Список прогонов — из ОТКРЫТОГО API GitHub: репозиторий публичный, ключ не
нужен, лимит 60 запросов в час на адрес (нам хватает четырёх-десяти).
Каждое решение — строка «сторож: …» в «Прогонах» админки (таблица `runs`,
колонка «Что собирали») и в терминал (`/var/log/streams-watch.log`).
Память сторожа — настройка `crawl_watch` (JSON), ключ — время заказа: новый
плановый заказ её обнуляет, повторный заказ самого сторожа — наследует.
"""

from __future__ import annotations

import json
import subprocess
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import db

KYIV = ZoneInfo("Europe/Kyiv")
API = "https://api.github.com"
#: минут после заявки, когда обход уже должен был стартовать (тег → прогон
#: обычно за минуту)
START_MINUTES = 3
#: минут после финиша, которые даём стуку «закончил» дойти до сервера
KNOCK_GRACE_MINUTES = 10
#: GitHub обрывает прогон через столько минут (`timeout-minutes` в crawl.yml)
HARD_LIMIT_MINUTES = 150
#: заказ старше — не наш: его давно сменил следующий плановый
ORDER_TTL_HOURS = 6
#: прогон считаем ответом на заявку, если он создан не раньше, чем за столько
#: минут до неё (часы сервера и GitHub могут чуть расходиться)
MATCH_SLACK_MINUTES = 2
RUNNING = ("queued", "in_progress", "waiting", "pending", "requested")


def github_runs(slug: str, limit: int = 12) -> list[dict]:
    """Последние прогоны репозитория; сеть недоступна — пустой список."""
    req = urllib.request.Request(
        f"{API}/repos/{slug}/actions/runs?per_page={limit}",
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "streams-schedule-watch"})
    try:
        with urllib.request.urlopen(req, timeout=20) as answer:
            data = json.loads(answer.read().decode("utf-8"))
    except (OSError, ValueError):
        return []
    return data.get("workflow_runs") or []


def _utc(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def parse_order(raw: str) -> dict | None:
    """`обход 6 сут.|2026-10-02 06:15` → {"days": 6, "at": <Киев>, "stamp": …}."""
    if not raw or "|" not in raw:
        return None
    head, stamp = raw.split("|", 1)
    try:
        days = int(head.split()[1])
        at = datetime.strptime(stamp.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=KYIV)
    except (IndexError, ValueError):
        return None
    return {"days": days, "at": at, "stamp": stamp.strip()}


def run_for(order: dict, runs: list[dict]) -> dict | None:
    """Прогон, которым GitHub ответил на заявку: кнопочный запуск
    (`workflow_dispatch`), созданный после заявки. Из нескольких — самый
    ранний после неё: более поздние — уже чужие («Обойти сайт», повтор)."""
    edge = order["at"] - timedelta(minutes=MATCH_SLACK_MINUTES)
    ours = []
    for r in runs:
        created = _utc(r.get("created_at") or "")
        if r.get("event") != "workflow_dispatch" or created is None:
            continue
        if created >= edge:
            ours.append((created, r))
    if not ours:
        return None
    ours.sort(key=lambda x: x[0])
    return ours[0][1]


def decide(order: dict, run: dict | None, now: datetime, state: dict,
           result: str) -> tuple[str, str]:
    """Одно решение по заказу: (действие, слова). Действия: wait — ничего не
    делать; reorder — повторить заявку; pull — забрать результат самому;
    alarm — строка тревоги (один раз); done — обход забран, больше не следим;
    none — заказ не наш (устарел).

    `result` — судьба результата этого прогона по метке «собрано»
    (`result_state`): picked — уже на сервере; pending — лежит на GitHub, на
    сервере нет; none — прогон результата не оставил (пропуск «сегодня уже
    ходили», проба); unknown — сверить не вышло."""
    age = (now - order["at"]).total_seconds() / 60
    if age > ORDER_TTL_HOURS * 60:
        return "none", f"заказ {order['stamp']} старше {ORDER_TTL_HOURS} ч — не следим"
    if state.get("done"):
        return "none", "уже забран"
    if run is None:
        if age < START_MINUTES:
            return "wait", f"заявка {order['stamp']} ушла, ждём старта ({age:.0f} мин)"
        if not state.get("reordered"):
            return "reorder", (f"обход не стартовал за {age:.0f} мин после заявки "
                               f"{order['stamp']} — повторяю заявку")
        if not state.get("alarmed"):
            return "alarm", (f"обход не стартовал и после повтора заявки "
                             f"({order['stamp']}) — проверьте GitHub")
        return "wait", "обход не стартует, тревога уже подана"
    number = run.get("run_number")
    status = run.get("status") or ""
    started = _utc(run.get("run_started_at") or run.get("created_at") or "") or now
    if status in RUNNING:
        going = (now - started).total_seconds() / 60
        if going >= HARD_LIMIT_MINUTES:
            return "wait", (f"прогон #{number} идёт {going:.0f} мин — дольше предела "
                            f"{HARD_LIMIT_MINUTES}, GitHub его оборвёт, ждём")
        return "wait", f"прогон #{number} идёт {going:.0f} мин"
    conclusion = run.get("conclusion") or "?"
    finished = _utc(run.get("updated_at") or "") or now
    since = (now - finished).total_seconds() / 60
    if conclusion == "success":
        if since < KNOCK_GRACE_MINUTES:
            return "wait", (f"прогон #{number} готов {since:.0f} мин назад — "
                            f"даём стуку {KNOCK_GRACE_MINUTES} мин")
        if result == "pending":
            return "pull", (f"прогон #{number} готов, результат на GitHub, а на "
                            f"сервере нет (стук не дошёл) — забираю сам")
        if result == "picked":
            return "done", f"прогон #{number} готов и забран по стуку"
        if result == "none":
            return "done", (f"прогон #{number} прошёл без результата (пропуск "
                            f"или проба) — забирать нечего")
        return "wait", f"прогон #{number} готов, но метку «собрано» сверить не вышло"
    if not state.get("reordered"):
        return "reorder", (f"прогон #{number} кончился «{conclusion}» — "
                           f"повторяю заявку")
    if not state.get("alarmed"):
        return "alarm", (f"прогон #{number} кончился «{conclusion}» и после "
                         f"повтора — больше не заказываю, проверьте GitHub")
    return "wait", "обход падает, тревога уже подана"


def _collected(text: str) -> datetime | None:
    """Метка «собрано» из games.json (UTC, пишет parse_live)."""
    try:
        raw = json.loads(text).get("собрано") or ""
        return datetime.strptime(raw, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def result_state(root, started: datetime) -> str:
    """Судьба результата прогона, стартовавшего в `started` (UTC): picked —
    «собрано» на сервере не старше старта (результат уже забран); pending —
    такое «собрано» есть только на GitHub (стук не дошёл); none — ни там, ни
    там (прогон результата не оставил); unknown — GitHub не ответил.
    Сравниваем метку результата, а не коммиты: на GitHub между обходами
    ложатся и правки кода, и словари — по ним «забрано ли» не понять
    (02.10 сторож в --check трижды хотел забрать давно забранный #161)."""
    edge = started - timedelta(minutes=MATCH_SLACK_MINUTES)
    try:
        local = _collected((root / "results" / "games.json").read_text(encoding="utf-8"))
    except OSError:
        local = None
    if local and local >= edge:
        return "picked"
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "main"], capture_output=True,
                       text=True, cwd=root, timeout=60, check=True)
        shown = subprocess.run(["git", "show", "origin/main:results/games.json"],
                               capture_output=True, text=True, cwd=root,
                               timeout=60, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    remote = _collected(shown)
    if remote and remote >= edge:
        return "pending"
    return "none"


def note(conn: sqlite3.Connection, text: str, who: str = "сторож") -> None:
    """Строка в «Прогоны» админки: без окна дней она показывается словами
    из поля «режим» (шаблон runs.html)."""
    now = datetime.now(KYIV).strftime("%Y-%m-%d %H:%M")
    conn.execute(
        "INSERT INTO runs (started_at, finished_at, window_days, log) "
        "VALUES (?, ?, NULL, ?)",
        (now, now, json.dumps({"кто": who, "режим": f"{who}: {text}"},
                              ensure_ascii=False)))
    conn.commit()


def load_state(conn: sqlite3.Connection, order: dict) -> dict:
    try:
        state = json.loads(db.get_setting(conn, "crawl_watch") or "{}")
    except ValueError:
        state = {}
    if state.get("order") != order["stamp"]:
        state = {"order": order["stamp"]}
    return state


def save_state(conn: sqlite3.Connection, state: dict) -> None:
    db.set_setting(conn, "crawl_watch", json.dumps(state, ensure_ascii=False))


def wait_for_start(order: dict, slug: str, seconds: int = START_MINUTES * 60,
                   step: int = 20, sleep=None) -> dict | None:
    """Ждём, пока GitHub не заведёт прогон на нашу заявку."""
    import time
    sleep = sleep or time.sleep
    waited = 0
    while True:
        run = run_for(order, github_runs(slug))
        if run is not None or waited >= seconds:
            return run
        sleep(step)
        waited += step

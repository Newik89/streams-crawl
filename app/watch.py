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
С 05.10 (дыра: отметка «идёт» от пробы провисела, заявка 16:15 не ушла, и
сторожу не за чем было следить — обход на 2 дня пропал молча):
  4. заявка не верит отметке «идёт» на слово (`lock_verdict`): сверяется
     со списком прогонов; прогонов нет — отметка ложная, снять и заказать;
  5. плановый обход, который не ушёл или упал и после повтора, не пропадает:
     сторож сразу заказывает «следующий плановый досрочно» (`plan_early`,
     глубина — большая из двух), а в плановое время заменённый обход
     пропускается, если досрочный дошёл (`early_covers`). Досрочный — один
     на сорвавшийся плановый; сорвался и он — тревога, ждём планового;
  6. зависший прогон (дольше потолка своего вида, `CEILING_MINUTES`, или
     в очереди без очереди) отменяется заявкой-тегом `btn-cancel-<id>`
     (`queue.yml`), на следующей проверке сторож сверяет, что отменён.
Список прогонов — из ОТКРЫТОГО API GitHub: репозиторий публичный, ключ не
нужен, лимит 60 запросов в час на адрес (сторож делает один запрос за
проверку; заявка, пока ждёт старта, — до десяти).
Каждое решение — строка «сторож: …» в «Прогонах» админки (таблица `runs`,
колонка «Что собирали») и в терминал (`/var/log/streams-watch.log`).
Память сторожа — настройка `crawl_watch` (JSON), ключ — время заказа: новый
плановый заказ её обнуляет, повторный заказ самого сторожа — наследует.
"""

from __future__ import annotations

import json
import re
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

#: workflow обхода — только его прогоны сторож разбирает и отменяет
CRAWL_WORKFLOW = "crawl.yml"
CRAWL_NAME = "Обход телесайтов"
#: сколько последних прогонов обхода берёт сторож одним запросом
RUNS_LIMIT = 20

#: Плановые заявки сервера (владелец 03.10): время по Киеву и глубина, суток.
#: Одна таблица на всё: из неё cron-строки (`crawl_watch.py --cron`), поиск
#: «какой это плановый» и «какой следующий» (досрочный обход, 05.10).
#: cron сервера (живёт вне репозитория) должен совпадать с ней:
#:   15 6  * * *  … request_crawl.py days 6
#:   15 16 * * *  … request_crawl.py days 2
#:   30 20 * * *  … request_crawl.py days 6
SCHEDULE = (("06:15", 6), ("16:15", 2), ("20:30", 6))
#: заявка считается плановой, если пришла не дальше стольких минут от слота
SLOT_MATCH_MINUTES = 30
#: досрочный заменяет плановый, только если начался не раньше, чем за
#: столько часов до него (владелец 05.10): утренний досрочный 06:30 вечерний
#: 16:15 не заменит — за 10 часов сайты обновятся
EARLY_COVERS_HOURS = 5
#: сорвавшийся плановый старше — заказывать поздно, только тревога
MISSED_TTL_HOURS = 6

#: Потолки длительности прогона по виду, минут (05.10). Цифры — из истории
#: 100 прогонов (#101–#200, 25.09–05.10) с запасом ×1,5 и не ниже ориентира
#: владельца: проба идёт 1–5 мин (×1,5 = 8, берём 20 — как `PROBE_STALE`);
#: один сайт / скан даты 19–21 мин (×1,5 = 32 → 45); обход на 2 дня
#: (16:15) 33–40 мин (×1,5 = 60 → 75: план растёт); на 6 дней 81–103 мин
#: (×1,5 от обычных 88 = 132 → 140; GitHub сам режет на 150). Вид не узнан
#: (прогон до `run-name` в crawl.yml) — самый длинный потолок.
CEILING_MINUTES = {"probe": 20, "site": 45, "date": 45,
                   "full-2": 75, "full-5": 120, "full-6": 140, "schedule": 140,
                   "unknown": 140}
#: прогон ждёт в очереди, хотя перед ним никого, — столько минут ещё терпим
#: (обычно GitHub заводит прогон за минуту)
QUEUE_STUCK_MINUTES = 20
#: заявка отмены исполняется за 1–2 мин; не отменился за столько — тревога
CANCEL_CONFIRM_MINUTES = 10
#: свежая заявка («заказан» моложе стольких минут) на GitHub может ещё не
#: показаться — ей верим без списка прогонов
MARK_FRESH_MINUTES = 5


def github_runs(slug: str, limit: int = 12, workflow: str = "") -> list[dict]:
    """Последние прогоны репозитория (`workflow` — только этого файла, один
    запрос); сеть недоступна — пустой список."""
    where = f"workflows/{workflow}/runs" if workflow else "runs"
    req = urllib.request.Request(
        f"{API}/repos/{slug}/actions/{where}?per_page={limit}",
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
    """Ждём, пока GitHub не заведёт прогон на нашу заявку. Список — только
    прогонов обхода (05.10): кнопочный запуск другого workflow (проверка
    AI-слоя) иначе сошёл бы за ответ на заявку."""
    import time
    sleep = sleep or time.sleep
    waited = 0
    while True:
        run = run_for(order, github_runs(slug, workflow=CRAWL_WORKFLOW))
        if run is not None or waited >= seconds:
            return run
        sleep(step)
        waited += step


# ── 05.10: отметка «идёт» на слово не верим, досрочный обход, отмена ─────────
# Всё ниже — чистые функции: на входе список прогонов из API, время, память
# сторожа и расписание, на выходе решение. Сеть и база — у вызывающих
# (`scripts/request_crawl.py`, `scripts/crawl_watch.py`); проверки без сети —
# `scripts/test_watch.py`.

def kyiv_at(text: str) -> datetime | None:
    """`2026-10-05 16:15` (Киев) → время с поясом; не разобрать — None."""
    try:
        return datetime.strptime(str(text), "%Y-%m-%d %H:%M").replace(tzinfo=KYIV)
    except (TypeError, ValueError):
        return None


def stamp(at: datetime) -> str:
    return at.astimezone(KYIV).strftime("%Y-%m-%d %H:%M")


def hm(at: datetime | None) -> str:
    return at.astimezone(KYIV).strftime("%H:%M") if at else "?"


def crawl_only(runs: list[dict], slug: str = "") -> list[dict]:
    """Только прогоны workflow обхода этого репозитория — остальные сторож
    не разбирает и не отменяет."""
    out = []
    for r in runs:
        path = (r.get("path") or "").split("@")[0]
        if path:
            if path != f".github/workflows/{CRAWL_WORKFLOW}":
                continue
        elif r.get("name") != CRAWL_NAME:
            continue
        repo = (r.get("repository") or {}).get("full_name")
        if slug and repo and repo != slug:
            continue
        out.append(r)
    return out


def parse_what(what: str) -> tuple[str, int]:
    """Вид сбора по слову стука / отметки / названия прогона: `proba-2`,
    `probeurl-…` → проба; `site-…`; `date-…`; `full-6` / `days-6` → полный
    на 6 суток. Не узнан — unknown."""
    what = what or ""
    if what.startswith(("proba", "probeurl")):
        return "probe", 0
    if what.startswith("site-"):
        return "site", 0
    if what.startswith("date-"):
        return "date", 0
    m = re.fullmatch(r"(?:full|days)-(\d+)", what)
    if m:
        return "full", int(m.group(1))
    return "unknown", 0


def run_kind(run: dict) -> tuple[str, int]:
    """Вид прогона по его названию: с 05.10 crawl.yml называет прогон
    `Обход full-6` / `Обход proba-2` / `Обход site-…` / `Обход date-…`
    (`run-name`). Плановый cron GitHub (04:17 UTC) — отдельный вид: он
    почти всегда сразу выходит («сегодня уже ходили»), полным обходом его
    не считаем, иначе плановый сервера пропустился бы зря. Прогоны до этой
    правки называются просто «Обход телесайтов» — вид не узнан."""
    if run.get("event") == "schedule":
        return "schedule", 0
    m = re.fullmatch(r"Обход (\S+)", run.get("display_title") or "")
    return parse_what(m.group(1)) if m else ("unknown", 0)


def describe(kind: str, days: int = 0) -> str:
    return {"probe": "проба адреса", "site": "обход одного сайта",
            "date": "скан одной даты",
            "schedule": "запуск по расписанию GitHub"}.get(
        kind, f"обход на {days} сут." if kind == "full" else "обход")


def ceiling(kind: str, days: int = 0) -> int:
    key = f"full-{days}" if kind == "full" else kind
    return CEILING_MINUTES.get(key, CEILING_MINUTES["unknown"])


def active_crawls(runs: list[dict], slug: str = "") -> list[dict]:
    return [r for r in crawl_only(runs, slug) if (r.get("status") or "") in RUNNING]


def effective_start(run: dict, runs: list[dict]) -> datetime | None:
    """Когда прогон на самом деле пошёл. `run_started_at` у GitHub — время
    создания, даже если прогон час ждал в очереди за другим (`concurrency`:
    #118 «шёл» 36 мин, из них 34 ждал #117). Поэтому старт — не раньше
    конца предыдущих прогонов обхода; ждёт за ещё идущим — None (он не
    завис, зависнуть может тот, что впереди)."""
    created = _utc(run.get("created_at") or "")
    start = _utc(run.get("run_started_at") or "") or created
    if created is None or start is None:
        return None
    for o in runs:
        if o is run or o.get("id") == run.get("id"):
            continue
        oc = _utc(o.get("created_at") or "")
        if oc is None or oc >= created:
            continue
        if (o.get("status") or "") in RUNNING:
            return None
        end = _utc(o.get("updated_at") or "")
        if end and end > start:
            start = end
    return start


def stuck(runs: list[dict], now: datetime, slug: str = "") -> list[dict]:
    """Зависшие прогоны обхода: идёт дольше потолка своего вида или стоит в
    очереди дольше `QUEUE_STUCK_MINUTES`, хотя впереди никого.
    [{run, kind, days, minutes, limit, why}]."""
    crawls = crawl_only(runs, slug)
    out = []
    for r in crawls:
        status = r.get("status") or ""
        if status not in RUNNING:
            continue
        start = effective_start(r, crawls)
        if start is None:
            continue
        minutes = (now - start).total_seconds() / 60
        kind, days = run_kind(r)
        if status == "in_progress":
            limit = ceiling(kind, days)
            why = f"идёт {minutes:.0f} мин, а такой обычно укладывается в {limit}"
        else:
            limit = QUEUE_STUCK_MINUTES
            why = (f"{minutes:.0f} мин стоит в очереди, хотя перед ним "
                   f"ничего не идёт")
        if minutes > limit:
            out.append({"run": r, "kind": kind, "days": days,
                        "minutes": minutes, "limit": limit, "why": why})
    return out


def cancel_decisions(runs: list[dict], now: datetime, cancels: dict,
                     slug: str = "", order_run_id=None) -> list[tuple[str, str, str]]:
    """Отмена зависших (пункт 6 шапки): [(действие, id прогона, слова)].
    cancel — подать заявку отмены; confirmed — GitHub подтвердил, прогон
    остановлен; alarm — заявка отмены не сработала за
    `CANCEL_CONFIRM_MINUTES` (тревога один раз); forget — прогона уже нет в
    списке, забыть. `cancels` — память: {id: {at, number, alarmed}}."""
    by_id = {str(r.get("id")): r for r in crawl_only(runs, slug)}
    out = []
    for rid, c in cancels.items():
        r = by_id.get(rid)
        number = c.get("number")
        if r is None:
            out.append(("forget", rid, ""))
            continue
        if (r.get("status") or "") not in RUNNING:
            out.append(("confirmed", rid,
                        f"прогон #{number} остановлен (итог «{r.get('conclusion') or '?'}»)"))
            continue
        asked = kyiv_at(c.get("at", ""))
        since = (now - asked).total_seconds() / 60 if asked else 0
        if since >= CANCEL_CONFIRM_MINUTES and not c.get("alarmed"):
            out.append(("alarm", rid,
                        f"ТРЕВОГА — прогон #{number} не остановился за {since:.0f} мин "
                        f"после заявки отмены; GitHub всё равно оборвёт его через "
                        f"{HARD_LIMIT_MINUTES} мин после старта, дальше сторож "
                        f"поступит как с упавшим обходом"))
    for s in stuck(runs, now, slug):
        r = s["run"]
        rid = str(r.get("id"))
        if rid in cancels or not re.fullmatch(r"\d+", rid):
            continue
        what = describe(s["kind"], s["days"])
        after = ("на следующей проверке закажу его заново"
                 if order_run_id is not None and str(order_run_id) == rid
                 else "он мешал очереди обходов")
        out.append(("cancel", rid,
                    f"прогон #{r.get('run_number')} ({what}) завис: {s['why']} — "
                    f"отменяю его, {after}"))
    return out


def lock_verdict(busy: dict, days: int, runs: list[dict], now: datetime,
                 slug: str = "") -> tuple[str, str]:
    """Плановая заявка, а отметка говорит «сбор идёт» (пункт 4 шапки).
    Решение: clear — на GitHub прогонов нет, отметка ложная: снять и
    заказать; skip — идёт/ждёт полный обход не меньшей глубины, он соберёт
    и эти дни; behind — идёт что-то меньшее (проба, сайт, дата, полный
    меньшей глубины): заказать, встанет в очередь; postpone — GitHub не
    ответил, отметке верим, а заявку откладываем до сторожа.
    `runs` пустой — значит, GitHub не ответил (у репозитория их сотни)."""
    from .crawl_hook import queue_behind
    what = busy.get("what", "")
    if not runs:
        if queue_behind(busy, "days", str(days)):
            return "behind", (f"по отметке идёт «{what}», GitHub не ответил — "
                              f"плановый обход {days} сут. всё равно заказываю, "
                              f"он встанет в очередь")
        return "postpone", (f"плановый обход {days} сут. отложен: по отметке сбор "
                            f"уже {busy.get('state', 'идёт')} с {busy.get('since', '?')} "
                            f"(«{what}»), а GitHub не ответил, проверить нельзя. "
                            f"Сторож сверится на своей проверке (раз в 15 мин) и "
                            f"закажет обход, если он нужен")
    found = [(run_kind(r), r) for r in active_crawls(runs, slug)]
    fresh = (busy.get("state") == "заказан"
             and busy.get("age", 10 ** 9) < MARK_FRESH_MINUTES * 60)
    if not found and fresh:
        # заявку только что подали — GitHub её ещё не показал
        found = [(parse_what(what), None)]
    if not found:
        return "clear", (f"отметка «сбор {busy.get('state', 'идёт')}» («{what}» с "
                         f"{busy.get('since', '?')}) снята — на GitHub прогонов "
                         f"нет, она ложная. Заказываю плановый обход {days} сут.")
    hint = parse_what(what)
    for (kind, d), r in found:
        if kind == "unknown":
            kind, d = hint
        if kind == "full" and d >= days:
            where = (f"#{r.get('run_number')} " if r else "")
            how = ("заказан" if r is None else
                   "идёт" if r.get("status") == "in_progress" else "ждёт очереди")
            return "skip", (f"плановый обход {days} сут. не нужен — на GitHub уже "
                            f"{how} обход {where}на {d} сут., он соберёт и эти дни")
    names = ", ".join(describe(*k) for k, _ in found)
    return "behind", (f"на GitHub идёт {names} — плановый обход {days} сут. "
                      f"заказываю, он встанет в очередь следом")


def _slots(day, schedule=SCHEDULE):
    for hhmm, days in schedule:
        h, m = (int(x) for x in hhmm.split(":"))
        yield datetime(day.year, day.month, day.day, h, m, tzinfo=KYIV), days


def slot_for(now: datetime, days: int, schedule=SCHEDULE) -> datetime | None:
    """Плановый слот, к которому относится заявка `days` в `now`
    (±`SLOT_MATCH_MINUTES`); ручной заказ — None."""
    now = now.astimezone(KYIV)
    for shift in (-1, 0, 1):
        for at, d in _slots((now + timedelta(days=shift)).date(), schedule):
            if d == days and abs((now - at).total_seconds()) <= SLOT_MATCH_MINUTES * 60:
                return at
    return None


def next_slot(after: datetime, schedule=SCHEDULE) -> tuple[datetime, int]:
    """Ближайший плановый слот строго после `after`: (время, глубина)."""
    after = after.astimezone(KYIV)
    for shift in (0, 1, 2):
        for at, d in sorted(_slots((after + timedelta(days=shift)).date(), schedule)):
            if at > after:
                return at, d
    raise ValueError("пустое расписание")


def cron_lines(root: str, python: str, schedule=SCHEDULE) -> list[str]:
    """Строки cron сервера по таблице `SCHEDULE` (подсказка, сам cron живёт
    вне репозитория): `crawl_watch.py --cron`."""
    out = []
    for hhmm, days in schedule:
        h, m = (int(x) for x in hhmm.split(":"))
        out.append(f"{m} {h} * * * cd {root} && {python} scripts/request_crawl.py "
                   f"days {days} >> /var/log/streams-request.log 2>&1")
    out.append(f"*/15 * * * * cd {root} && {python} scripts/crawl_watch.py "
               f">> /var/log/streams-watch.log 2>&1")
    return out


def plan_early(missed: dict | None, runs: list[dict], now: datetime,
               early: dict | None, last_order: dict | None,
               skip_ids=(), slug: str = "",
               schedule=SCHEDULE) -> tuple[str, dict, str]:
    """Сорвавшийся плановый (пункт 5 шапки): (действие, заказ, слова).
    none — нечего делать; late — сорвался давно (`MISSED_TTL_HOURS`),
    только тревога; drop — после него уже заказан обход не меньшей глубины;
    covered — на GitHub идёт/ждёт полный не меньшей глубины; order —
    заказать сейчас обход глубиной max(сорвавшийся, следующий плановый)
    вместо следующего планового. `skip_ids` — прогоны, которые сторож
    сейчас отменяет: они не в счёт."""
    if not missed or missed.get("state") != "missed":
        return "none", {}, ""
    slot = missed.get("slot", "")
    mdays = int(missed.get("days") or 0)
    at = kyiv_at(missed.get("at", "")) or now
    slot_hm = slot[-5:] if slot else "?"
    if early and early.get("for") == slot:
        return "none", {}, f"досрочный за плановый {slot_hm} уже заказывали"
    if (now - at).total_seconds() > MISSED_TTL_HOURS * 3600:
        return "late", {}, (f"ТРЕВОГА — плановый обход {slot_hm} ({mdays} сут.) так и "
                            f"не состоялся, а прошло больше {MISSED_TTL_HOURS} ч — "
                            f"досрочно уже не заказываю, ждём следующего планового")
    if last_order and last_order["at"] > at and last_order["days"] >= mdays:
        return "drop", {}, (f"плановый обход {slot_hm} не состоялся, но после него "
                            f"уже заказан обход на {last_order['days']} сут. в "
                            f"{hm(last_order['at'])} — он и соберёт")
    skip = {str(x) for x in skip_ids}
    for r in active_crawls(runs, slug):
        if str(r.get("id")) in skip:
            continue
        kind, d = run_kind(r)
        if kind == "full" and d >= mdays:
            return "covered", {}, (f"плановый обход {slot_hm} не состоялся, но на "
                                   f"GitHub уже идёт обход #{r.get('run_number')} на "
                                   f"{d} сут. — он соберёт эти дни, досрочно не заказываю")
    nxt, ndays = next_slot(now, schedule)
    depth = max(mdays, ndays)
    order = {"for": slot, "for_days": mdays, "days": depth,
             "replaces": stamp(nxt), "replaces_days": ndays}
    return "order", order, (
        f"плановый обход {slot_hm} ({mdays} сут.) не состоялся — заказываю сейчас "
        f"обход на {depth} сут. вместо следующего планового {hm(nxt)} ({ndays} сут.). "
        f"Если этот дойдёт до конца, в {hm(nxt)} повторять не буду")


def early_covers(early: dict | None, slot_at: datetime, runs: list[dict],
                 slug: str = "") -> tuple[bool, str]:
    """Пропустить ли плановый в `slot_at`: его заменил досрочный, и тот
    начался не раньше, чем за `EARLY_COVERS_HOURS` до слота, и дошёл до
    конца или ещё идёт. (пропустить, слова; пусто — досрочный не про этот
    слот). `runs` пустой — GitHub молчит: верим памяти сторожа (`state`)."""
    if not early or early.get("replaces") != stamp(slot_at):
        return False, ""
    ordered = kyiv_at(early.get("ordered_at", ""))
    if ordered is None:
        return False, ""
    # ответ на досрочную заявку — первый полный обход после неё (проба,
    # нажатая следом, не в счёт)
    fulls = [r for r in crawl_only(runs, slug) if run_kind(r)[0] in ("full", "unknown")]
    run = run_for({"at": ordered}, fulls) if runs else None
    started = (_utc(run.get("run_started_at") or run.get("created_at") or "")
               if run else None) or ordered
    edge = slot_at - timedelta(hours=EARLY_COVERS_HOURS)
    if started < edge:
        return False, (f"досрочный обход начался в {hm(started)} — раньше, чем за "
                       f"{EARLY_COVERS_HOURS} ч до планового {hm(slot_at)}, сайты "
                       f"успели обновиться: плановый идёт как обычно")
    if run is not None:
        status = run.get("status") or ""
        ok = status in RUNNING or run.get("conclusion") == "success"
        how = ("ещё идёт" if status in RUNNING else "дошёл до конца") if ok \
            else f"кончился «{run.get('conclusion') or '?'}»"
    elif runs:
        ok, how = False, "так и не стартовал"
    else:
        ok = early.get("state") == "done"
        how = "дошёл до конца (по памяти сторожа, GitHub не ответил)" if ok \
            else "не подтверждён (GitHub не ответил)"
    if ok:
        return True, (f"плановый обход {hm(slot_at)} ({early.get('replaces_days')} сут.) "
                      f"выполнен досрочно в {hm(started)} — обход на "
                      f"{early.get('days')} сут. #{run.get('run_number') if run else '?'} "
                      f"{how}; заново не заказываю")
    return False, (f"досрочный обход в {hm(started)} {how} — плановый "
                   f"{hm(slot_at)} идёт как обычно")


def load_json(conn: sqlite3.Connection, key: str) -> dict:
    try:
        value = json.loads(db.get_setting(conn, key) or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def save_json(conn: sqlite3.Connection, key: str, value: dict) -> None:
    db.set_setting(conn, key, json.dumps(value, ensure_ascii=False))

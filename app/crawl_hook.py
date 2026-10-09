# -*- coding: utf-8 -*-
"""Стук GitHub серверу и замок «сбор уже идёт» (владелец 14.09.2026).

Обход заказывает сервер (тег-заявка, `scripts/request_crawl.py`), идёт он на
GitHub, а GitHub стучит сюда дважды: «начал» и «закончил». По «закончил»
сервер сам забирает результат — заборы по часам остались страховкой. Пока
сбор заказан или идёт, кнопки второй не запускают.

Подделать стук нельзя: секретное слово по сети не ездит. GitHub шлёт время
и подпись HMAC-SHA256 от «время.событие.что»; сервер принимает подпись не
старше 5 минут и только с временем новее последнего принятого — перехваченный
стук второй раз не пройдёт. Слово — в секретах GitHub (`CRAWL_HOOK_SECRET`)
и в файле `/etc/streams-hook-secret` на сервере (права 600), в коде его нет.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import db

KYIV = ZoneInfo("Europe/Kyiv")
SECRET_FILE = Path(os.environ.get("STREAMS_HOOK_SECRET_FILE")
                   or "/etc/streams-hook-secret")
EVENTS = ("start", "done-ok", "done-fail")
MAX_SKEW = 300            # подпись старше 5 минут не принимаем
#: GitHub обрывает обход через 150 мин (`crawl.yml`, timeout) — замок, по
#: которому «закончил» так и не пришёл, дольше не держим
RUN_STALE = 3 * 3600
#: заявка ушла, а «начал» не пришёл (тег не сработал) — кнопки снова свободны
REQUEST_STALE = 20 * 60
#: проба (`proba-N`, `probeurl-…`) идёт 2–3 минуты. 05.10 её «закончил»
#: сервер отверг, отметка «идёт» с 13:44 провисела бы 3 часа (`RUN_STALE`) —
#: и плановая заявка 16:15 не ушла. Пробе хватит 20 минут
PROBE_STALE = 20 * 60
#: сколько часов свежий полный обход отменяет плановый (владелец 29.09: 2;
#: 02.10: 1) и отказывает кнопкам друзей (05.10) — правило «1 час»
RECENT_HOURS = 1
#: серверный сайт — не чаще раза в сутки («даже кнопкой», владелец 10.09).
#: Один порог на всех: им живут и server_crawl.py, и кнопка «Обойти сайт»
SITE_GAP_HOURS = 20
PULL_SCRIPT = db.ROOT / "scripts" / "hook_pull.sh"


def _secret() -> bytes:
    try:
        return SECRET_FILE.read_text(encoding="utf-8").strip().encode()
    except OSError:
        return b""


def sign(secret: bytes, stamp: str, event: str, what: str,
         reason: str = "") -> str:
    """Подпись стука; причина провала (`reason`, схема сбоев шаг 3) входит в
    подписанное — иначе её можно было бы подменить и увести сторожа."""
    msg = f"{stamp}.{event}.{what}" + (f".{reason}" if reason else "")
    return hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()


#: допустимый код причины провала (`scripts/fail_reason.py`)
REASON_RE = re.compile(r"^[a-z][a-z-]{0,23}$")
#: память причин: настройка `crawl_fail_reasons`, последние записи
FAIL_MEMORY = "crawl_fail_reasons"
FAIL_KEEP = 30
#: причина считается «про этот прогон», если стук пришёл в этих минутах
#: от конца прогона по GitHub (стук идёт последним шагом job'а)
FAIL_MATCH_MINUTES = 20


def remember_failure(conn: sqlite3.Connection, what: str, reason: str,
                     now: datetime | None = None) -> None:
    """Стук «закончил» с провалом: запомнить (что, причина, когда UTC) —
    сторож найдёт по виду и времени (`fail_reason`)."""
    if not REASON_RE.match(reason or ""):
        return
    now = now or datetime.now(timezone.utc)
    try:
        items = json.loads(db.get_setting(conn, FAIL_MEMORY) or "[]")
    except ValueError:
        items = []
    items.append({"what": what, "reason": reason,
                  "at": now.astimezone(timezone.utc).isoformat(timespec="seconds")})
    db.set_setting(conn, FAIL_MEMORY, json.dumps(items[-FAIL_KEEP:], ensure_ascii=False))


def fail_reason(conn: sqlite3.Connection, what: str, ended: datetime,
                minutes: int = FAIL_MATCH_MINUTES) -> str:
    """Причина провала прогона вида `what`, кончившегося в `ended` (UTC):
    ближайший по времени стук того же вида в окне ± `minutes`; нет — пусто."""
    try:
        items = json.loads(db.get_setting(conn, FAIL_MEMORY) or "[]")
    except ValueError:
        return ""
    best, gap = "", timedelta(minutes=minutes)
    for it in items:
        if it.get("what") != what:
            continue
        try:
            at = datetime.fromisoformat(it.get("at") or "")
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        d = abs(at - ended.astimezone(timezone.utc))
        if d <= gap:
            best, gap = it.get("reason") or "", d
    return best


def verify(conn: sqlite3.Connection, stamp: str, event: str, what: str,
           signature: str, reason: str = "") -> tuple[bool, str]:
    """(принят, почему нет). Время подписи запоминается атомарно: из двух
    одинаковых стуков — и из двух воркеров gunicorn — пройдёт один."""
    secret = _secret()
    if not secret:
        return False, "на сервере нет слова"
    if event not in EVENTS:
        return False, "событие"
    try:
        ts = int(stamp)
    except ValueError:
        return False, "время"
    if abs(time.time() - ts) > MAX_SKEW:
        return False, "время"
    if reason and not REASON_RE.match(reason):
        return False, "причина"
    if not hmac.compare_digest(sign(secret, stamp, event, what, reason),
                               signature or ""):
        return False, "подпись"
    conn.execute("INSERT OR IGNORE INTO settings (key, value) "
                 "VALUES ('hook_last_stamp', '0')")
    taken = conn.execute(
        "UPDATE settings SET value = ? WHERE key = 'hook_last_stamp' "
        "AND CAST(value AS INTEGER) < ?", (str(ts), ts)).rowcount
    conn.commit()
    return (True, "ok") if taken else (False, "повтор")


def mark(conn: sqlite3.Connection, state: str, what: str) -> None:
    """state: `заявка` (сервер заказал) или `идёт` (GitHub сказал «начал»)."""
    now = datetime.now(KYIV)
    db.set_setting(conn, "crawl_running",
                   f"{state}|{int(time.time())}|{now:%H:%M}|{what}")


def clear(conn: sqlite3.Connection) -> None:
    db.set_setting(conn, "crawl_running", "")


def running(conn: sqlite3.Connection) -> dict | None:
    """Сбор заказан или идёт — словарь для надписи; свободно — None."""
    raw = db.get_setting(conn, "crawl_running")
    try:
        state, ts, since, what = raw.split("|", 3)
        age = time.time() - int(ts)
    except ValueError:
        return None
    if age > (REQUEST_STALE if state == "заявка" else
              PROBE_STALE if is_probe(what) else RUN_STALE):
        return None
    # age — секунд с отметки (05.10): свежей заявке сторож верит, даже если
    # GitHub её ещё не показал (`watch.lock_verdict`)
    # since_day — то же время с датой («08.10 14:28»): в плашке над витриной
    # вчерашний и сегодняшний заказ иначе не различить (владелец 08.10)
    return {"state": "заказан" if state == "заявка" else "идёт",
            "state_en": "requested" if state == "заявка" else "running",
            "since": since, "what": what, "age": age,
            "since_day": datetime.fromtimestamp(int(ts), KYIV)
            .strftime("%d.%m %H:%M")}


def is_probe(what: str) -> bool:
    """Проба (`proba-2` — стук «начал», `probeurl-…` — «закончил»), а не обход."""
    return (what or "").startswith(("proba", "probeurl"))


def queue_behind(busy: dict, kind: str, value: str) -> bool:
    """Пустить плановую заявку, хотя «сбор идёт» (05.10): идёт проба или
    полный обход МЕНЬШЕЙ глубины. Обход GitHub и так встаёт в очередь за
    текущим (`concurrency` в crawl.yml); раньше 2-дневный сбор кнопкой,
    шедший в 20:30, отменял плановый на 6 дней — тот просто не заказывался.
    Скан даты и «Обойти сайт» по-прежнему держат замок."""
    if is_probe(busy.get("what", "")):
        return True
    m = re.fullmatch(r"(?:days|full)-(\d+)", busy.get("what", ""))
    return kind == "days" and bool(m) and int(m.group(1)) < int(value)


def fresh_full(conn: sqlite3.Connection,
               now: datetime | None = None) -> list[dict]:
    """Свежие (за `RECENT_HOURS`) полные обходы: [{days, at, done}].
    Источник тот же, что у правила «1 час» плановых заявок: заказ
    (`crawl_request` — его пишут кнопки и `request_crawl.py`, done=False) и
    сбор, уже влитый в `runs` (полный обход — пустое «кто», есть окно;
    done=True). Скан даты, «Обойти сайт», сервер mojtv и проба сюда не
    попадают: у них нет окна или есть «кто». `at` — время по Киеву С ПОЯСОМ;
    «за последний час» считается настоящими часами (UTC), а не настенными:
    в ночь перевода часов (25.10.2026) иначе час растягивался бы до двух
    или сжимался до нуля."""
    now = (now or datetime.now(KYIV)).astimezone(timezone.utc)
    edge = now - timedelta(hours=RECENT_HOURS)
    # отметки в базе — настенное киевское время; с запасом в час на перевод
    # часов отбираем строки, а точно — уже по UTC
    wall_edge = (edge.astimezone(KYIV) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")

    def kyiv(text: str) -> datetime | None:
        try:
            return datetime.strptime(str(text)[:16], "%Y-%m-%d %H:%M").replace(tzinfo=KYIV)
        except ValueError:
            return None

    out = []
    req = db.get_setting(conn, "crawl_request") or ""
    m = re.match(r"обход (\d+) сут\.\|(\d{4}-\d\d-\d\d \d\d:\d\d)", req)
    if m:
        when = kyiv(m.group(2))
        if when and when >= edge:
            out.append({"days": int(m.group(1)), "at": when, "done": False})
    for r in conn.execute("SELECT finished_at, window_days, log FROM runs "
                          "WHERE finished_at >= ? ORDER BY finished_at DESC",
                          (wall_edge,)):
        try:
            who = (json.loads(r["log"] or "{}") or {}).get("кто") or ""
        except ValueError:
            who = "?"
        at = kyiv(r["finished_at"])
        if at is None or at < edge:
            continue
        if not who and (r["window_days"] or 0) > 0:
            out.append({"days": r["window_days"], "at": at, "done": True})
    return out


def recent_full(conn: sqlite3.Connection, days: int,
                now: datetime | None = None) -> dict | None:
    """Свежий полный обход глубиной ≥ `days` или None."""
    return next((x for x in fresh_full(conn, now) if x["days"] >= days), None)


def covering(conn: sqlite3.Connection, day: date,
             now: datetime | None = None) -> dict | None:
    """Свежий полный обход, чьё окно (день обхода + `days`−1) включает `day`."""
    for x in fresh_full(conn, now):
        first = x["at"].date()
        if first <= day <= first + timedelta(days=x["days"] - 1):
            return x
    return None


def start_site_crawl(domain: str) -> tuple[bool, str]:
    """Точечный серверный сбор одного сайта (кнопка «Обойти сайт», 20.09) —
    отдельной службой, как забор: кнопке отвечаем сразу, качает и вливает
    фоновая служба. Сам `server_crawl.py` ещё раз проверит «не чаще раза
    в сутки» (слово владельца 10.09) — двойная страховка.
    Возвращает (получилось, слова для человека), как trigger.dispatch_crawl."""
    script = db.ROOT / "scripts" / "server_crawl.py"
    try:
        subprocess.run(
            ["systemd-run", "--no-block", "--collect",
             "--unit", f"streams-site-crawl-{int(time.time())}",
             sys.executable, str(script), "--only", domain],
            check=True, capture_output=True, timeout=20)
        return True, "сервер пошёл качать — итог на витрине через несколько минут"
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"сервер не запустил сбор: {type(e).__name__}"


def start_pull() -> str:
    """Забор отдельной службой systemd: сайт отвечает GitHub сразу, а
    перезапуск сайта в конце забора не обрывает сам забор."""
    try:
        subprocess.run(
            ["systemd-run", "--no-block", "--collect",
             "--unit", f"streams-hook-pull-{int(time.time())}",
             "/bin/sh", str(PULL_SCRIPT)],
            check=True, capture_output=True, timeout=20)
        return "забор запущен"
    except (OSError, subprocess.SubprocessError) as e:
        return f"забор не запустился: {type(e).__name__}"

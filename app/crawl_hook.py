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
import os
import sqlite3
import subprocess
import time
from datetime import datetime
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
PULL_SCRIPT = db.ROOT / "scripts" / "hook_pull.sh"


def _secret() -> bytes:
    try:
        return SECRET_FILE.read_text(encoding="utf-8").strip().encode()
    except OSError:
        return b""


def sign(secret: bytes, stamp: str, event: str, what: str) -> str:
    return hmac.new(secret, f"{stamp}.{event}.{what}".encode(),
                    hashlib.sha256).hexdigest()


def verify(conn: sqlite3.Connection, stamp: str, event: str, what: str,
           signature: str) -> tuple[bool, str]:
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
    if not hmac.compare_digest(sign(secret, stamp, event, what), signature or ""):
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
    if age > (REQUEST_STALE if state == "заявка" else RUN_STALE):
        return None
    return {"state": "заказан" if state == "заявка" else "идёт",
            "state_en": "requested" if state == "заявка" else "running",
            "since": since, "what": what}


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

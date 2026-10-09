# -*- coding: utf-8 -*-
r"""Сторож витрины: сайт завис — перезапустить службу, не дожидаясь владельца.

Схема сбоев (`deploy/СБОИ-СХЕМА.md`, принята владельцем 06.10.2026, шаг 2):
«витрина зависла → проверка раз в 5 мин, перезапуск (≤3 в час)». Грабли
25.09: рабочий процесс gunicorn залипает — потоки заняты, страницы с
шаблонами висят вечно, а `/api/v1/status` (без шаблона) отвечает мгновенно и
`systemctl is-active` = active. Поэтому пробуем настоящую страницу витрины
прямо у gunicorn (мимо nginx), с таймаутом.

Правила по порядку (`verdict`):
  В1. Страница открылась (HTTP 200 за `TIMEOUT` с) → всё в порядке, молчим.
  В2. Не открылась (таймаут, нет соединения, 5xx) → вторая проба через
      `RETRY_SECONDS` с: одиночный долгий запрос — ещё не зависание.
  В3. Не открылась дважды → перезапуск службы `streams-web`, если за
      последний час их было меньше `RESTARTS_PER_HOUR`; строка в «Прогоны».
  В4. Перезапуски за час исчерпаны → одна ТРЕВОГА в час (строка «ТРЕВОГА —
      …» в «Прогонах»), больше ничего: три перезапуска не помогли — дело не
      в зависании, нужен человек.
Память — настройка `web_watch` (JSON {restarts: [UTC ISO…], alarm_at}).

Cron (deploy/cron.d/streams-schedule): */5 * * * *  web_watch.py
    venv/bin/python scripts/web_watch.py           # проверить и действовать
    venv/bin/python scripts/web_watch.py --check   # только сказать, что сделал бы
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, watch  # noqa: E402

#: адрес страницы витрины у самого gunicorn (deploy/systemd/streams-web.service)
URL = os.environ.get("STREAMS_WEB_URL", "http://127.0.0.1:8000/schedule")
#: столько секунд ждём страницу; витрина отдаёт её за доли секунды,
#: а зависший процесс не ответит никогда
TIMEOUT = 20
#: пауза перед второй пробой (В2)
RETRY_SECONDS = 15
#: перезапусков за час, после которых только ТРЕВОГА (схема сбоев: ≤3)
RESTARTS_PER_HOUR = 3
#: тревожим не чаще раза в час (В4)
ALARM_EVERY = timedelta(hours=1)
SERVICE = "streams-web"
KEY = "web_watch"
WHO = "автомат"


def probe(url: str = URL, timeout: int = TIMEOUT) -> tuple[bool, str]:
    """(открылась ли страница, почему нет)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            code = r.status
            r.read(2048)
    except urllib.error.HTTPError as e:
        return e.code < 500, f"HTTP {e.code}"
    except Exception as e:                       # noqa: BLE001 — таймаут, нет соединения
        return False, f"{type(e).__name__}: {e}"[:120]
    return code == 200, f"HTTP {code}"


def verdict(state: dict, now: datetime, first: tuple[bool, str],
            second) -> tuple[str, str, dict]:
    """Правила В1–В4. `first` — итог первой пробы, `second` — функция второй
    (зовётся только при провале первой). Возвращает (что делать: ok /
    restart / alarm / quiet, слова, новая память)."""
    ok, why = first
    if ok:
        return "ok", "", state
    ok2, why2 = second()
    if ok2:
        return "ok", "", state
    hour_ago = now - timedelta(hours=1)
    restarts = [t for t in state.get("restarts") or []
                if watch.moment(t) and watch.utc(watch.moment(t)) > hour_ago]
    new = dict(state, restarts=restarts)
    if len(restarts) < RESTARTS_PER_HOUR:
        new["restarts"] = restarts + [watch.when(now)]
        return "restart", (f"витрина не ответила дважды ({why}; {why2}) — "
                           f"перезапускаю {SERVICE} ({len(restarts) + 1} из "
                           f"{RESTARTS_PER_HOUR} за час)"), new
    last = watch.moment(state.get("alarm_at") or "")
    if last and watch.utc(last) > now - ALARM_EVERY:
        return "quiet", "", new
    new["alarm_at"] = watch.when(now)
    return "alarm", (f"ТРЕВОГА — витрина не отвечает ({why}), а {RESTARTS_PER_HOUR} "
                     f"перезапуска за час не помогли; сервер нужен человеку"), new


def restart() -> str:
    r = subprocess.run(["systemctl", "restart", SERVICE], capture_output=True, text=True)
    return "ok" if r.returncode == 0 else (r.stderr or r.stdout or "?").strip()[:200]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="только сказать, не делать")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    conn = db.connect()
    try:
        state = watch.load_json(conn, KEY) or {}
        what, words, new = verdict(
            state, now, probe(),
            lambda: (time.sleep(RETRY_SECONDS), probe())[1])
        stamp = now.astimezone(watch.KYIV).strftime("%d.%m %H:%M")
        if what == "ok":
            return 0
        print(f"{stamp} {what}: {words}")
        if args.check:
            return 0
        if what == "restart":
            words += f"; systemctl: {restart()}"
        if what in ("restart", "alarm"):
            watch.note(conn, words, who=WHO)
        watch.save_json(conn, KEY, new)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

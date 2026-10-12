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
Дальше — схема сбоев, шаг 9 (12.10.2026), тоже на каждом запуске:
  В5. Сторож заказов (`crawl_watch.py`, cron */15) молчит дольше порога
      `app/alive.py` (40 мин; правила Ж1–Ж3 — `alive.silent_minutes`) →
      запустить его самому (в фоне, журнал тот же, с `alive.KICKED_ENV`:
      такой запуск отметку «жив» не ставит), не чаще раза в час (`kick_at`).
      Первый пинок за этот раз молчания — ТРЕВОГА (`episode_at`), следующие —
      простая строка «всё ещё молчит» (о долгом молчании владельцу напомнит
      GitHub через /alive, раз в сутки). Своя прошлая отметка тоже старше
      своего порога — лежал весь сервер (или код только приехал): молчание
      сторожа заказов считаем заново с этой минуты (`resume_at`), иначе
      после перезагрузки была бы ложная ТРЕВОГА «cron не запускает».
  В6. Новые ТРЕВОГИ из «Прогонов» — письмом владельцу (`app/alarm_mail.py`,
      правила М1–М4), в том числе написанные этим же запуском.
  В7. Последним — своя отметка «жив» (`alive.beat`): по ней сервер (/alive)
      и GitHub видят, что сторож витрины ходит.
Два запуска разом не идут: замок `web-watch.lock` рядом с базой; занят
(прошлый ещё ждёт витрину или GitHub) — этот выходит молча.
Память — настройка `web_watch` (JSON {restarts: [UTC ISO…], alarm_at,
kick_at, episode_at, resume_at}).

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

from app import alarm_mail, alive, db, watch  # noqa: E402

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
#: сторож заказов: как его запустить самому (В5) и куда писать его вывод —
#: тот же журнал, что у cron
WATCH_SCRIPT = ROOT / "scripts" / "crawl_watch.py"
WATCH_LOG = "/var/log/streams-watch.log"
#: запускать молчащего сторожа и тревожить о нём — не чаще (В5)
KICK_EVERY = timedelta(hours=1)


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


def watch_silence(state: dict, now: datetime, silent_for: int,
                  web_was_down: bool) -> tuple[str, str, dict]:
    """Правило В5. `silent_for` — сколько минут молчит сторож заказов
    (`alive.silent_minutes`); `web_was_down` — своя прошлая отметка старше
    своего порога или её нет. Возвращает (что делать: ok / quiet / kick —
    запустить со строкой / alarm — запустить с ТРЕВОГОЙ, слова, новая память)."""
    name, limit = alive.BEATS["crawl_watch"]
    new = dict(state)
    if web_was_down:
        new["resume_at"] = watch.when(now)
    resume = watch.moment(new.get("resume_at") or "")
    if resume is not None:
        silent_for = min(silent_for, alive.minutes_since(resume, now))
    if silent_for <= limit:
        new.pop("episode_at", None)
        return "ok", "", new
    last = watch.moment(state.get("kick_at") or "")
    if last and watch.utc(last) > now - KICK_EVERY:
        return "quiet", "", new
    new["kick_at"] = watch.when(now)
    if new.get("episode_at"):
        return "kick", (f"{name} всё ещё молчит ({silent_for} мин) — снова "
                        f"запустил его сам"), new
    new["episode_at"] = watch.when(now)
    return "alarm", (f"ТРЕВОГА — {name} молчит {silent_for} мин: cron его не "
                     f"запускает или он падает. Запустил его сам; журнал — "
                     f"{WATCH_LOG}"), new


def restart() -> str:
    r = subprocess.run(["systemctl", "restart", SERVICE], capture_output=True, text=True)
    return "ok" if r.returncode == 0 else (r.stderr or r.stdout or "?").strip()[:200]


def kick() -> str:
    """Запустить сторожа заказов в фоне (В5): он может ждать общий замок до
    7 мин — дольше, чем живёт этот запуск."""
    env = dict(os.environ)
    env[alive.KICKED_ENV] = "1"           # пинок отметку «жив» не ставит
    try:
        with open(WATCH_LOG, "ab") as log:
            subprocess.Popen([sys.executable, str(WATCH_SCRIPT)], cwd=ROOT,
                             stdout=log, stderr=subprocess.STDOUT, env=env,
                             start_new_session=True)
    except OSError as e:
        return f"не запустился: {e}"[:200]
    return "запущен"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="только сказать, не делать")
    args = ap.parse_args()
    lock = db.db_path().with_name("web-watch.lock")
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if not watch._try_lock(fd):
            return 0                     # прошлый запуск ещё идёт
        try:
            return _run(args.check)
        finally:
            watch._unlock(fd)
    finally:
        os.close(fd)


def _run(check: bool) -> int:
    now = datetime.now(timezone.utc)
    stamp = now.astimezone(watch.KYIV).strftime("%d.%m %H:%M")
    # 30 с, как у прочих скриптов: заливка игр держит базу долго, а запись
    # памяти и отметки «жив» не должна из-за неё падать
    conn = db.connect(db.BUSY_TIMEOUT_SCRIPT)
    try:
        state = watch.load_json(conn, KEY) or {}
        own = alive.beat_at(conn, "web_watch")      # до своей новой отметки (В7)
        web_was_down = own is None or (alive.minutes_since(own, now)
                                       > alive.BEATS["web_watch"][1])
        what, words, new = verdict(                                # В1–В4
            state, now, probe(),
            lambda: (time.sleep(RETRY_SECONDS), probe())[1])
        if what != "ok":
            print(f"{stamp} {what}: {words}")
            if not check:
                if what == "restart":
                    words += f"; systemctl: {restart()}"
                if what in ("restart", "alarm"):
                    watch.note(conn, words, who=WHO)
        silent_for, _ = alive.silent_minutes(conn, "crawl_watch", now)
        what, words, new = watch_silence(new, now, silent_for, web_was_down)  # В5
        if what in ("kick", "alarm"):
            print(f"{stamp} {what}: {words}")
            if not check:
                watch.note(conn, f"{words}; запуск: {kick()}", who=WHO)
        if not check and new != state:
            watch.save_json(conn, KEY, new)
        mail = alarm_mail.flush(conn, now, check=check)            # В6
        if mail:
            print(f"{stamp} {mail}")
        if not check:
            alive.beat(conn, "web_watch", now)                     # В7
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

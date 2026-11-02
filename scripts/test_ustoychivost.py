# -*- coding: utf-8 -*-
"""Устойчивость-1 (книга 093, слово владельца 02.11.2026: «чтоб сайт мог
избежать возможных ошибок и если они возникнут — рестарт, и всё заново
работало»). Правило — проверка:

  У1. `web._same_secret` — пароль и CSRF сравниваются в байтах: не-ASCII не
      роняет (15.10 — 500 на /login), верный пароль по-прежнему пускает.
  У2. /login с паролем кириллицей → «Неверный пароль», не 500.
  У3. sqlite «database is locked» в обработчике → 503 + Retry-After, страница
      «минутку»; для /api/ — JSON с error; прочая OperationalError → 500.
  У4. Любая внутренняя ошибка → страница 500 без следов кода (нет Traceback).
  У5. `db.BUSY_TIMEOUT_WEB` = 20 (запись с сайта ждёт заливку, читатели в WAL
      не ждут) — решение владельца 02.11, оно же в test_resheniya.
  У6. Сторож витрины В8–В9: `daily_due` раз в сутки; `db_check` — «ok» на
      живой базе и слова беды (не исключение) на не-базе; `daily_verdict` —
      две ТРЕВОГИ при беде, пусто при порядке; `disk_free_gb` > 0.
  У7. Кухня (если рядом): юнит gunicorn с --timeout/--max-requests,
      StartLimitIntervalSec=0, TimeoutStopSec, MemoryMax; nginx error_page
      502/503/504 → /oshibka.html; страница oshibka.html; logrotate с
      copytruncate. На GitHub кухни нет — пропуск с пометкой.

    venv/bin/python scripts/test_ustoychivost.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="ustoychivost-"))
(TMP / "visits").mkdir()
os.environ.update(STREAMS_DB=str(TMP / "test.db"), STREAMS_ADMIN_PASSWORD="adm-test-1",
                  STREAMS_FRIEND_PASSWORD="fr-test-1", SECRET_KEY="k" * 32,
                  STREAMS_VISITS_DIR=str(TMP / "visits"))
os.environ.pop("STREAMS_LOCAL", None)

from app import db, visits, watch, web  # noqa: E402
import web_watch  # noqa: E402

visits.write = lambda *a, **k: None
db.init_db()
app = web.create_app()
app.config["TESTING"] = True
app.config["PROPAGATE_EXCEPTIONS"] = False      # иначе тест сам увидел бы исключение


@app.route("/_proba/locked")
def _proba_locked():
    raise sqlite3.OperationalError("database is locked")


@app.route("/api/_proba/locked")
def _proba_locked_api():
    raise sqlite3.OperationalError("database is locked")


@app.route("/_proba/sql")
def _proba_sql():
    raise sqlite3.OperationalError("no such table: nichego")


@app.route("/_proba/boom")
def _proba_boom():
    raise RuntimeError("секретная строка кода 12345")


total = green = 0


def check(name: str, ok: bool, extra="") -> None:
    global total, green
    total += 1
    green += bool(ok)
    print(f"  {'✔' if ok else '✗'} {name}" + ("" if ok else f"  → {extra}"))


client = app.test_client()

print("У1. сравнение паролей в байтах")
check("кириллица против латиницы — False без исключения",
      web._same_secret("пароль", "adm-test-1") is False)
check("одинаковые строки с не-ASCII — True", web._same_secret("пароль", "пароль") is True)
check("пустая против непустой — False", web._same_secret("", "x") is False)

print("У2. /login с паролем кириллицей")
r = client.post("/login", data={"password": "пароль"})
check("ответ 200 и «Неверный пароль», не 500",
      r.status_code == 200 and "Неверный пароль" in r.get_data(as_text=True), r.status_code)
r = client.post("/login", data={"password": "adm-test-1"})
check("верный пароль по-прежнему пускает (302)", r.status_code == 302, r.status_code)
# дальше — как вошедший владелец: без входа все пути, кроме витрины, уводят на /login

print("У3. база занята → 503 «повторите», не 500")
r = client.get("/_proba/locked")
text = r.get_data(as_text=True)
check("503, Retry-After 60, страница «минутку» с автообновлением",
      r.status_code == 503 and r.headers.get("Retry-After") == "60"
      and "повторите через минуту" in text and 'http-equiv="refresh"' in text,
      (r.status_code, r.headers.get("Retry-After")))
r = client.get("/api/_proba/locked")
check("для /api/ — JSON с error и 503",
      r.status_code == 503 and r.is_json and "занята" in (r.get_json() or {}).get("error", ""),
      (r.status_code, r.get_data(as_text=True)[:80]))
r = client.get("/_proba/sql")
check("другая ошибка sqlite — обычная 500-страница", r.status_code == 500
      and "не смог показать" in r.get_data(as_text=True), r.status_code)

print("У4. внутренняя ошибка → страница без следов кода")
r = client.get("/_proba/boom")
text = r.get_data(as_text=True)
check("500, слова «не смог показать», без Traceback и без текста исключения",
      r.status_code == 500 and "не смог показать" in text
      and "Traceback" not in text and "12345" not in text, r.status_code)
r = client.get("/schedule")
check("витрина после ошибок открывается (200)", r.status_code == 200, r.status_code)

print("У5. решение: запись с сайта ждёт базу 20 с")
check("db.BUSY_TIMEOUT_WEB == 20", db.BUSY_TIMEOUT_WEB == 20, db.BUSY_TIMEOUT_WEB)

print("У6. сторож витрины В8–В9")
now = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
check("памяти нет → пора", web_watch.daily_due({}, now))
check("проверяли час назад → рано",
      not web_watch.daily_due({"daily_at": watch.when(now - timedelta(hours=1))}, now))
check("проверяли 25 ч назад → пора",
      web_watch.daily_due({"daily_at": watch.when(now - timedelta(hours=25))}, now))
conn = db.connect()
check("quick_check живой базы — ok", web_watch.db_check(conn) == "ok", web_watch.db_check(conn))
conn.close()
junk = TMP / "junk.db"
junk.write_bytes(("\x00это не база\x00" * 100).encode("utf-8"))
bad = sqlite3.connect(junk)
words = web_watch.db_check(bad)
bad.close()
check("не база — слова беды, не исключение", words != "ok" and "Error" in words, words)
check("порядок → тревог нет", web_watch.daily_verdict("ok", 15.0) == [])
alarms = web_watch.daily_verdict("*** in database main *** Page 3: never used", 0.4)
check("беда с базой и мало места → две ТРЕВОГИ",
      len(alarms) == 2 and all(a.startswith("ТРЕВОГА") for a in alarms)
      and "повреждена" in alarms[0] and "0.4 ГБ" in alarms[1], alarms)
check("свободное место на диске базы > 0", web_watch.disk_free_gb(TMP) > 0)
check("сторож --check не падает на пустой памяти",
      web_watch.verdict({}, now, (True, "HTTP 200"), lambda: (True, ""))[0] == "ok")

print("У7. кухня: юнит, nginx, страница, logrotate")
deploy = ROOT.parent / "Streams Schedule" / "deploy"
if deploy.is_dir():
    unit = (deploy / "systemd" / "streams-web.service").read_text(encoding="utf-8")
    nginx = ((deploy / "nginx-streams-tls.conf").read_text(encoding="utf-8")
             + (deploy / "nginx-streams.conf").read_text(encoding="utf-8"))
    page = (deploy / "oshibka.html").read_text(encoding="utf-8")
    rot = (deploy / "logrotate" / "streams-schedule").read_text(encoding="utf-8")
    check("юнит: gunicorn --timeout 60, --max-requests 2000 с разбросом, graceful 20",
          "--timeout 60" in unit and "--max-requests 2000" in unit
          and "--max-requests-jitter 200" in unit and "--graceful-timeout 20" in unit)
    check("юнит: StartLimitIntervalSec=0, TimeoutStopSec=25, MemoryMax=600M, Restart=always",
          "StartLimitIntervalSec=0" in unit and "TimeoutStopSec=25" in unit
          and "MemoryMax=600M" in unit and "Restart=always" in unit)
    check("nginx (оба сервера, 80 и 443): error_page 502 503 504 → /oshibka.html из /var/www/streams, internal",
          nginx.count("error_page 502 503 504 /oshibka.html;") == 2
          and nginx.count("root /var/www/streams;") == 2 and nginx.count("internal;") == 2)
    check("страница: «перезапускается», автообновление, ссылка на /schedule",
          "перезапускается" in page and 'http-equiv="refresh"' in page and 'href="/schedule"' in page)
    check("logrotate: weekly, rotate 8, copytruncate, только /var/log/streams-*.log",
          "weekly" in rot and "rotate 8" in rot and "copytruncate" in rot
          and "/var/log/streams-*.log {" in rot)
else:
    print("  (кухни рядом нет — проверки конфигов сервера пропущены; локально они идут)")

print(f"\nпроверок: {total}, зелёных: {green}, красных: {total - green}")
raise SystemExit(0 if green == total else 1)

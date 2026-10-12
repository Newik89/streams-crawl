# -*- coding: utf-8 -*-
"""Схема сбоев, шаг 9: «сервер лёг» и тревога письмом — сценарий на каждое
правило.

  Ж1–Ж4  `app/alive.py`           кто из сторожей молчит (страница /alive)
  М1–М4  `app/alarm_mail.py`      новые ТРЕВОГИ → тег-письмо
  В5     `scripts/web_watch.py`   сторож заказов молчит → запустить, ТРЕВОГА
  Ж1–Ж3  `scripts/server_alive.py` GitHub: проба /alive → issue
  Т1–Т2  `scripts/alarm_issue.py`  тег-письмо → issue на день
  тег    `trigger.make_tag_object` текст с кириллицей доезжает в тег целым
  /alive страница публичная и не пишется в «Посещения»

В сеть не ходит, GitHub не трогает: база — временная, пробы и отправка
подменены. Запуск:

    venv\\Scripts\\python.exe scripts/test_alive.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="alive-test-"))
(TMP / "visits").mkdir()
os.environ.update(STREAMS_DB=str(TMP / "test.db"), STREAMS_ADMIN_PASSWORD="adm-test-1",
                  SECRET_KEY="k" * 32, STREAMS_VISITS_DIR=str(TMP / "visits"))
os.environ.pop("STREAMS_LOCAL", None)

from app import alarm_mail, alive, db, trigger, visits, watch, web  # noqa: E402
import alarm_issue  # noqa: E402
import server_alive  # noqa: E402
import web_watch  # noqa: E402

зелёных = красных = 0


def проверка(имя, вышло, ждём):
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


NOW = datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)      # 22:00 по Киеву


def чистая_база():
    conn = db.connect()
    conn.execute("DELETE FROM settings WHERE key LIKE 'beat:%' OR key = ?",
                 (alarm_mail.KEY,))
    conn.execute("DELETE FROM runs")
    conn.commit()
    return conn


def отметить(conn, имя, минут_назад):
    alive.beat(conn, имя, NOW - timedelta(minutes=минут_назад))


def строка(conn, текст, кто="сторож", когда="2026-10-12 21:55"):
    conn.execute("INSERT INTO runs (started_at, finished_at, window_days, log) "
                 "VALUES (?, ?, NULL, ?)",
                 (когда, когда, json.dumps({"кто": кто, "режим": f"{кто}: {текст}"},
                                           ensure_ascii=False)))
    conn.commit()


def сторожа_жизни(conn):
    print("Ж1–Ж4. app/alive.py — кто молчит")
    чистая_база()
    r = alive.report(conn, NOW)
    проверка("Ж3 отметок нет — в порядке", (r["жив"], r["минут"]["crawl_watch"]),
             (True, None))
    отметить(conn, "crawl_watch", 10)
    отметить(conn, "web_watch", 3)
    r = alive.report(conn, NOW)
    проверка("Ж1 свежие — жив", (r["жив"], r["молчат"]), (True, []))
    проверка("Ж1 минуты", r["минут"], {"crawl_watch": 10, "web_watch": 3})
    отметить(conn, "crawl_watch", 41)
    r = alive.report(conn, NOW)
    проверка("Ж2 сторож заказов 41 мин > 40", (r["жив"], r["молчат"]),
             (False, ["сторож заказов молчит 41 мин"]))
    отметить(conn, "crawl_watch", 40)
    проверка("Ж1 ровно 40 мин — ещё в порядке", alive.report(conn, NOW)["жив"], True)
    отметить(conn, "web_watch", 21)
    проверка("Ж2 сторож витрины 21 мин > 20", alive.report(conn, NOW)["молчат"],
             ["сторож витрины молчит 21 мин"])
    отметить(conn, "web_watch", 1)
    watch.save_json(conn, alarm_mail.KEY, {
        "last_id": 1, "waiting_since": watch.when(NOW - timedelta(minutes=61))})
    проверка("Ж4 письма не уходят 61 мин", alive.report(conn, NOW)["молчат"],
             ["письма тревог не уходят 61 мин"])
    watch.save_json(conn, alarm_mail.KEY, {
        "last_id": 1, "waiting_since": watch.when(NOW - timedelta(minutes=30))})
    проверка("Ж4 ждут 30 мин — ещё в порядке", alive.report(conn, NOW)["жив"], True)


def письма(conn):
    print("М1–М4. app/alarm_mail.py — тревоги письмом")
    чистая_база()
    строка(conn, "ТРЕВОГА — старая, до первого запуска")
    отправлено = []

    def послать(ответ):
        def f(текст):
            отправлено.append(текст)
            return ответ
        return f

    слова = alarm_mail.flush(conn, NOW, послать((True, "ушёл")))
    проверка("М1 первый запуск — ничего не шлём", (отправлено, "первый" in слова),
             ([], True))
    проверка("М1 память = последняя строка",
             watch.load_json(conn, alarm_mail.KEY), {"last_id": alarm_mail.last_row_id(conn)})
    проверка("М2 новых нет — молчим", alarm_mail.flush(conn, NOW, послать((True, ""))), "")
    строка(conn, "заказал досрочный обход")          # не тревога
    проверка("М2 строка без тревоги — молчим",
             (alarm_mail.flush(conn, NOW, послать((True, ""))), отправлено), ("", []))
    строка(conn, "ТРЕВОГА — витрина не отвечает", кто="автомат", когда="2026-10-12 21:57")
    строка(conn, "ТРЕВОГА — GitHub молчит 60 мин", когда="2026-10-12 21:58")
    alarm_mail.flush(conn, NOW, послать((False, "нет связи")))
    память = watch.load_json(conn, alarm_mail.KEY)
    проверка("М4 не ушло — память не сдвинулась", "waiting_since" in память, True)
    первая = память["waiting_since"]
    alarm_mail.flush(conn, NOW + timedelta(minutes=5), послать((None, "таймаут")))
    проверка("М4 git не ответил — повтор, отметка первой неудачи та же",
             watch.load_json(conn, alarm_mail.KEY).get("waiting_since"), первая)

    def упасть(текст):
        raise OSError("диск")
    слова = alarm_mail.flush(conn, NOW, упасть)
    проверка("М4 отправка упала — сторож не падает", "НЕ ушло" in слова, True)
    отправлено.clear()
    слова = alarm_mail.flush(conn, NOW, послать((True, "тег alarm-1 ушёл")))
    проверка("М3 ушло одно письмо", len(отправлено), 1)
    проверка("М3 в письме обе тревоги со временем",
             [s for s in отправлено[0].splitlines() if "ТРЕВОГА" in s],
             ["12.10 21:57 автомат: ТРЕВОГА — витрина не отвечает",
              "12.10 21:58 сторож: ТРЕВОГА — GitHub молчит 60 мин"])
    проверка("М3 память сдвинута, ожидание снято",
             watch.load_json(conn, alarm_mail.KEY),
             {"last_id": alarm_mail.last_row_id(conn), "sent_at": watch.when(NOW)})
    проверка("М2 после отправки — повторно не шлём",
             alarm_mail.flush(conn, NOW, послать((True, ""))), "")
    for n in range(alarm_mail.MAX_LINES + 3):
        строка(conn, f"ТРЕВОГА — номер {n}")
    отправлено.clear()
    alarm_mail.flush(conn, NOW, послать((True, "")))
    проверка("М3 больше MAX_LINES — остальные числом",
             отправлено[0].splitlines()[-1], "…и ещё 3 — в «Прогонах» админки")
    строка(conn, "ТРЕВОГА — для --check")
    до = watch.load_json(conn, alarm_mail.KEY)
    отправлено.clear()
    слова = alarm_mail.flush(conn, NOW, послать((True, "")), check=True)
    проверка("--check говорит, но не шлёт и не пишет",
             (слова, отправлено, watch.load_json(conn, alarm_mail.KEY) == до),
             ("письмо тревог ушло бы: 1 шт.", [], True))


def сторож_витрины(conn):
    print("В5. scripts/web_watch.py — сторож заказов молчит")
    beat = NOW - timedelta(minutes=10)
    what, words, st = web_watch.watch_silence({}, NOW, beat)
    проверка("свежая отметка — ok", (what, st), ("ok", {}))
    what, words, st = web_watch.watch_silence({}, NOW, NOW - timedelta(minutes=55))
    проверка("55 мин — запустить и ТРЕВОГА", (what, words.startswith("ТРЕВОГА — сторож заказов молчит 55 мин")),
             ("kick", True))
    проверка("время запуска запомнено", st.get("kick_at"), watch.when(NOW))
    what, _, st2 = web_watch.watch_silence(st, NOW + timedelta(minutes=30),
                                           NOW - timedelta(minutes=55))
    проверка("через 30 мин всё молчит — тишина (раз в час)", what, "quiet")
    what, _, _ = web_watch.watch_silence(st, NOW + timedelta(minutes=61),
                                         NOW - timedelta(minutes=55))
    проверка("через час — снова запуск и ТРЕВОГА", what, "kick")
    what, _, st = web_watch.watch_silence({}, NOW, None)
    проверка("отметки нет — ok, запомнили, с какого времени",
             (what, st.get("missing_since")), ("ok", watch.when(NOW)))
    what, _, st3 = web_watch.watch_silence(st, NOW + timedelta(minutes=30), None)
    проверка("нет 30 мин — ещё ждём", what, "ok")
    what, words, _ = web_watch.watch_silence(st, NOW + timedelta(minutes=45), None)
    проверка("нет 45 мин — запустить и ТРЕВОГА",
             (what, "отметки «жив» нет ни одной" in words), ("kick", True))
    what, _, st4 = web_watch.watch_silence(st, NOW, NOW - timedelta(minutes=1))
    проверка("отметка появилась — память «нет отметки» снята",
             (what, "missing_since" in st4), ("ok", False))


def гитхаб_жив():
    print("Ж1–Ж3. scripts/server_alive.py — проба с GitHub")
    проверка("адрес из секрета", server_alive.base_url("http://1.2.3.4/crawl-hook"),
             "http://1.2.3.4")
    проверка("адрес скрыт", server_alive.hide("отказ http://1.2.3.4 и 1.2.3.4:80 и 5.6.7.8",
                                              "http://1.2.3.4"),
             "отказ <сервер> и <сервер>:80 и <адрес>")
    проверка("Ж1 жив", server_alive.verdict("ok", {"жив": True}), (True, ""))
    проверка("Ж1 страницы /alive ещё нет (404)", server_alive.verdict("old", "HTTP 404"),
             (True, ""))
    проверка("Ж3 молчат", server_alive.verdict(
        "ok", {"жив": False, "молчат": ["сторож заказов молчит 50 мин"]}),
             (False, "сервер отвечает, но сторож заказов молчит 50 мин"))
    проверка("Ж2 не отвечает", server_alive.verdict("down", "TimeoutError"),
             (False, "сервер не отвечает (TimeoutError)"))
    пробы, сны = [], []

    def проба(ответы):
        it = iter(ответы)
        def f(url):
            пробы.append(url)
            return next(it)
        return f
    итог = server_alive.look("u", 3, 60, сны.append,
                             проба([("down", "a"), ("ok", {"жив": True}), ("down", "c")]))
    проверка("look: вторая ответила — третьей нет", (итог[0], len(пробы), сны),
             ("ok", 2, [60]))
    пробы.clear(); сны.clear()
    итог = server_alive.look("u", 3, 60, сны.append,
                             проба([("down", "a"), ("down", "b"), ("down", "c")]))
    проверка("look: три мимо — down с последней причиной", (итог, len(пробы), сны),
             (("down", "c"), 3, [60, 60]))
    print("  — что делать с issue")
    свежая = {"number": 7, "updated_at": (NOW - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    старая = {"number": 7, "updated_at": (NOW - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    проверка("жив, issue нет — ничего", server_alive.action(True, [], NOW), ("none", 0))
    проверка("жив, issue открыта — закрыть", server_alive.action(True, [свежая], NOW),
             ("close", 7))
    проверка("беда, issue нет — новая", server_alive.action(False, [], NOW), ("open", 0))
    проверка("беда, issue свежая — молчим", server_alive.action(False, [свежая], NOW),
             ("none", 0))
    проверка("беда, issue старше суток — напомнить",
             server_alive.action(False, [старая], NOW), ("remind", 7))
    текст = server_alive.body_text("сервер не отвечает", NOW, "", "Newik89", True)
    проверка("письмо: упоминание владельца, ПРОБА, киевское время",
             ("@Newik89" in текст, "ПРОБА" in текст, "12.10.2026 22:00" in текст),
             (True, True, True))


def гитхаб_тревога():
    print("Т1–Т2. scripts/alarm_issue.py — issue на день")
    проверка("заголовок по Киеву: 21:30 UTC 12.10 = 13.10",
             alarm_issue.today_title(datetime(2026, 10, 12, 21, 30, tzinfo=timezone.utc)),
             "Тревоги сервера — 13.10.2026")
    title = "Тревоги сервера — 12.10.2026"
    issues = [{"number": 9, "title": title}, {"number": 5, "title": "Тревоги сервера — 11.10.2026"}]
    проверка("сегодняшняя есть — комментарий в неё", alarm_issue.plan(issues, title), (9, [5]))
    проверка("сегодняшней нет — новая, вчерашнюю закрыть",
             alarm_issue.plan(issues[1:], title), (0, [5]))
    проверка("адрес в тексте скрыт", alarm_issue.clean("стук с 157.245.77.140 не дошёл"),
             "стук с <адрес> не дошёл")
    проверка("длинный текст обрезан",
             alarm_issue.clean("я" * (alarm_issue.MAX_CHARS + 50)).endswith("…(обрезано)"), True)
    проверка("чужое имя тега отвергается", bool(alarm_issue._TAG_RE.match("alarm-1 ;rm")), False)
    проверка("своё имя тега годится", bool(alarm_issue._TAG_RE.match("alarm-1760300000")), True)


def тег_с_текстом():
    print("тег. trigger.make_tag_object — кириллица доезжает целой")
    repo = TMP / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)
    run("init", "-q")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
        "--allow-empty", "-m", "пусто")
    текст = "Тревоги сервера Streams Schedule: 1\n\n12.10 21:57 автомат: ТРЕВОГА — витрина"
    sha, ошибка = trigger.make_tag_object(текст, "alarm-1760300000", 1760300000, cwd=repo)
    проверка("объект тега создан", (bool(sha), ошибка), (True, ""))
    показ = subprocess.run(["git", "cat-file", "-p", sha], cwd=repo,
                           capture_output=True).stdout.decode("utf-8")
    проверка("сообщение тега = текст тревоги", показ.split("\n\n", 1)[1].rstrip("\n"), текст)
    проверка("локального тега нет", run("tag", "-l").stdout.strip(), "")


def страница():
    print("/alive — публичная, без «Посещений»")
    записи = []
    visits.write = lambda *a, **k: записи.append(a)
    app = web.create_app()
    conn = чистая_база()
    alive.beat(conn, "crawl_watch")          # страница смотрит по настоящим часам
    alive.beat(conn, "web_watch")
    conn.close()
    r = app.test_client().get("/alive")
    данные = r.get_json() or {}
    проверка("без входа отвечает JSON", (r.status_code, данные.get("жив")), (200, True))
    проверка("в «Посещения» не пишется", записи, [])


def main() -> int:
    db.init_db()
    conn = db.connect()
    try:
        сторожа_жизни(conn)
        письма(conn)
    finally:
        conn.close()
    сторож_витрины(None)
    гитхаб_жив()
    гитхаб_тревога()
    тег_с_текстом()
    страница()
    print(f"\nзелёных {зелёных}, красных {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

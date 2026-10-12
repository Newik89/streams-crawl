# -*- coding: utf-8 -*-
"""Схема сбоев, шаг 9: «сервер лёг» и тревога письмом — сценарий на каждое
правило.

  Ж1–Ж4  `app/alive.py`            кто из сторожей молчит (страница /alive)
  М1–М4  `app/alarm_mail.py`       новые ТРЕВОГИ → тег-письмо
  В5     `scripts/web_watch.py`    сторож заказов молчит → запустить, ТРЕВОГА
  Ж1–Ж4  `scripts/server_alive.py` GitHub: проба /alive → issue
  Т1–Т4  `scripts/alarm_issue.py`  теги-письма → issue на день
  тег    `trigger.make_tag_object` текст с кириллицей доезжает в тег целым;
         `trigger.has_alarm_workflow` — без alarm.yml в коде тег не шлём
  /alive страница публичная и не пишется в «Посещения»

В сеть не ходит, GitHub не трогает: база — временная, пробы и отправка
подменены. Адреса в тесте — из документационных сетей (203.0.113.x). Запуск:

    venv\\Scripts\\python.exe scripts/test_alive.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
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
import crawl_alarm  # noqa: E402
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
    conn.execute("DELETE FROM settings WHERE key LIKE 'beat:%' "
                 "OR key LIKE 'beat_missing:%' OR key = ?", (alarm_mail.KEY,))
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
    r = alive.report(conn, NOW, uptime=None)
    проверка("Ж3 отметок нет — в порядке, отсчёт пошёл", (r["жив"], r["минут"]),
             (True, {"crawl_watch": 0, "web_watch": 0}))
    r = alive.report(conn, NOW + timedelta(minutes=30), uptime=None)
    проверка("Ж3 нет 30 мин: сторож витрины (порог 20) молчит, заказов (40) — нет",
             r["молчат"], ["сторож витрины молчит 30 мин (отметок не было ни одной)"])
    r = alive.report(conn, NOW + timedelta(minutes=41), uptime=None)
    проверка("Ж3 нет 41 мин — молчат оба", len(r["молчат"]), 2)
    отметить(conn, "crawl_watch", 10)
    отметить(conn, "web_watch", 3)
    r = alive.report(conn, NOW, uptime=None)
    проверка("Ж1 свежие — жив", (r["жив"], r["молчат"]), (True, []))
    проверка("Ж1 минуты", r["минут"], {"crawl_watch": 10, "web_watch": 3})
    отметить(conn, "crawl_watch", 41)
    r = alive.report(conn, NOW, uptime=None)
    проверка("Ж2 сторож заказов 41 мин > 40", (r["жив"], r["молчат"]),
             (False, ["сторож заказов молчит 41 мин"]))
    отметить(conn, "crawl_watch", 40)
    проверка("Ж1 ровно 40 мин — ещё в порядке", alive.report(conn, NOW, uptime=None)["жив"], True)
    отметить(conn, "web_watch", 21)
    проверка("Ж2 сторож витрины 21 мин > 20", alive.report(conn, NOW, uptime=None)["молчат"],
             ["сторож витрины молчит 21 мин"])
    отметить(conn, "web_watch", 1)
    watch.save_json(conn, alarm_mail.KEY, {
        "last_id": 1, "waiting_since": watch.when(NOW - timedelta(minutes=61))})
    проверка("Ж4 письма не уходят 61 мин", alive.report(conn, NOW, uptime=None)["молчат"],
             ["письма тревог не уходят 61 мин"])
    watch.save_json(conn, alarm_mail.KEY, {
        "last_id": 1, "waiting_since": watch.when(NOW - timedelta(minutes=30))})
    проверка("Ж4 ждут 30 мин — ещё в порядке", alive.report(conn, NOW, uptime=None)["жив"], True)
    отметить(conn, "crawl_watch", 183)
    r = alive.report(conn, NOW, uptime=None)
    проверка("«кто» — имена молчащих для GitHub", r["кто"], ["crawl_watch"])
    r = alive.report(conn, NOW, uptime=7)
    проверка("Ж3б сервер работает 7 мин после простоя — отметке 183 мин, но это не молчание",
             (r["жив"], r["минут"]["crawl_watch"]), (True, 7))
    проверка("аптайм читается из файла", alive.uptime_minutes(TMP / "нет-такого"), None)
    (TMP / "uptime").write_text("5432.10 999.0\n", encoding="utf-8")
    проверка("аптайм 5432 с = 90 мин", alive.uptime_minutes(TMP / "uptime"), 90)
    conn.execute("DELETE FROM settings WHERE key LIKE 'beat%'")
    conn.commit()
    alive.silent_minutes(conn, "crawl_watch", NOW, write=False, uptime=None)
    проверка("--check не пишет «нет отметки с …»",
             db.get_setting(conn, alive.MISSING_PREFIX + "crawl_watch"), "")


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
    строка(conn, "ТРЕВОГА — GitHub молчит 60 мин; адрес 203.0.113.5:8000",
           когда="2026-10-12 21:58")
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
    проверка("М3 в письме обе тревоги со временем, адрес скрыт",
             [s for s in отправлено[0].splitlines() if "ТРЕВОГА" in s],
             ["12.10 21:57 автомат: ТРЕВОГА — витрина не отвечает",
              "12.10 21:58 сторож: ТРЕВОГА — GitHub молчит 60 мин; адрес <адрес>"])
    проверка("М3 память сдвинута, ожидание снято",
             watch.load_json(conn, alarm_mail.KEY),
             {"last_id": alarm_mail.last_row_id(conn), "sent_at": watch.when(NOW)})
    проверка("М2 после отправки — повторно не шлём",
             alarm_mail.flush(conn, NOW, послать((True, ""))), "")
    for n in range(alarm_mail.MAX_LINES + 3):
        строка(conn, f"ТРЕВОГА — номер {n} " + "я" * 400)
    отправлено.clear()
    alarm_mail.flush(conn, NOW, послать((True, "")))
    проверка("М3 больше MAX_LINES — остальные числом",
             отправлено[0].splitlines()[-1], "…и ещё 3 — в «Прогонах» админки")
    проверка("М3 полное письмо влезает в комментарий целиком",
             len(alarm_issue.clean(отправлено[0])) <= alarm_issue.MAX_CHARS
             and "обрезано" not in alarm_issue.clean(отправлено[0]), True)
    строка(conn, "ТРЕВОГА — для --check")
    до = watch.load_json(conn, alarm_mail.KEY)
    отправлено.clear()
    слова = alarm_mail.flush(conn, NOW, послать((True, "")), check=True)
    проверка("--check говорит, но не шлёт и не пишет",
             (слова, отправлено, watch.load_json(conn, alarm_mail.KEY) == до),
             ("письмо тревог ушло бы: 1 шт.", [], True))


def сторож_витрины():
    print("В5. scripts/web_watch.py — сторож заказов молчит")
    ws = web_watch.watch_silence
    what, words, st = ws({}, NOW, 10, False)
    проверка("10 мин — ok", (what, st), ("ok", {}))
    what, words, st = ws({}, NOW, 55, False)
    проверка("55 мин — запустить и ТРЕВОГА",
             (what, words.startswith("ТРЕВОГА — сторож заказов молчит 55 мин")),
             ("alarm", True))
    проверка("запуск и начало молчания запомнены",
             (st.get("kick_at"), st.get("episode_at")), (watch.when(NOW), watch.when(NOW)))
    what, _, _ = ws(st, NOW + timedelta(minutes=30), 85, False)
    проверка("через 30 мин всё молчит — тишина (раз в час)", what, "quiet")
    what, words, st2 = ws(st, NOW + timedelta(minutes=61), 116, False)
    проверка("через час — снова запуск, но без ТРЕВОГИ (уже сказали)",
             (what, "ТРЕВОГА" in words, "всё ещё молчит" in words), ("kick", False, True))
    what, _, st3 = ws(st2, NOW + timedelta(minutes=70), 3, False)
    проверка("ожил — молчание кончилось, следующее снова с ТРЕВОГОЙ",
             (what, "episode_at" in st3), ("ok", False))
    what, _, st4 = ws(st3, NOW + timedelta(minutes=200), 60, False)
    проверка("новое молчание — снова ТРЕВОГА", what, "alarm")
    print("  — лежал весь сервер (своя отметка тоже старая)")
    what, _, st = ws({}, NOW, 180, True)
    проверка("после перезагрузки 180 мин — не тревога, отсчёт заново",
             (what, st.get("resume_at")), ("ok", watch.when(NOW)))
    what, _, _ = ws(st, NOW + timedelta(minutes=30), 210, False)
    проверка("30 мин после перезагрузки — ещё ждём", what, "ok")
    what, _, _ = ws(st, NOW + timedelta(minutes=45), 225, False)
    проверка("45 мин после перезагрузки сторож так и молчит — ТРЕВОГА", what, "alarm")
    what, _, _ = ws(st, NOW + timedelta(minutes=45), 5, False)
    проверка("а если отметился — ok", what, "ok")
    print("  — пинок не ставит отметку «жив» (иначе мёртвый cron спрятался бы)")
    проверка("пинок помечен переменной окружения", alive.KICKED_ENV, "STREAMS_KICKED")
    исходник = (ROOT / "scripts" / "crawl_watch.py").read_text(encoding="utf-8")
    проверка("сторож заказов не отмечается при пинке",
             "not os.environ.get(alive.KICKED_ENV)" in исходник, True)
    проверка("и при пропуске из-за замка",
             исходник.count("alive.beat(") == 1, True)


def гитхаб_жив():
    print("Ж1–Ж4. scripts/server_alive.py — проба с GitHub")
    проверка("адрес из секрета", server_alive.base_url("http://203.0.113.5/crawl-hook"),
             "http://203.0.113.5")
    проверка("адрес скрыт",
             server_alive.hide("отказ http://203.0.113.5 и 203.0.113.5:80 и 198.51.100.7",
                               "http://203.0.113.5"),
             "отказ <сервер> и <сервер>:80 и <адрес>")
    до, после = date(2026, 10, 15), date(2026, 10, 16)
    проверка("Ж1 жив", server_alive.verdict("ok", {"жив": True}, до), ("", ""))
    проверка("Ж4 страницы /alive нет — до 15.10 ещё не беда",
             server_alive.verdict("old", "HTTP 404", до), ("", ""))
    проверка("Ж4 с 16.10 — беда «отвечает не тем»",
             server_alive.verdict("old", "HTTP 404", после)[0], "wrong")
    проверка("Ж3 молчат", server_alive.verdict(
        "ok", {"жив": False, "молчат": ["сторож заказов молчит 50 мин"],
               "кто": ["crawl_watch"]}, до),
             ("silent:crawl_watch", "сервер отвечает, но сторож заказов молчит 50 мин"))
    проверка("Ж3 вид — состав по алфавиту", server_alive.verdict(
        "ok", {"жив": False, "молчат": ["…", "…"], "кто": ["mail", "crawl_watch"]}, до)[0],
             "silent:crawl_watch+mail")
    проверка("Ж2 не отвечает", server_alive.verdict("down", "TimeoutError", до),
             ("down", "сервер не отвечает (TimeoutError)"))
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
    тело = server_alive.body_text("silent:web_watch", "сервер отвечает, но …", NOW, "", "Newik89", False)

    def issue(вид, часов):
        return {"number": 7, "body": server_alive.body_text(вид, "…", NOW, "", "", False),
                "updated_at": (NOW - timedelta(hours=часов)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    проверка("вид беды хранится в теле", server_alive.issue_kind({"body": тело}), "silent:web_watch")
    проверка("жив, issue нет — ничего", server_alive.action("", [], NOW), ("none", 0))
    проверка("жив, issue открыта — закрыть", server_alive.action("", [issue("down", 2)], NOW),
             ("close", 7))
    проверка("беда, issue нет — новая", server_alive.action("down", [], NOW), ("open", 0))
    проверка("та же беда, issue свежая — молчим",
             server_alive.action("down", [issue("down", 2)], NOW), ("none", 0))
    проверка("та же беда старше суток — напомнить",
             server_alive.action("down", [issue("down", 25)], NOW), ("remind", 7))
    проверка("молчали сторожа, а теперь лёг весь сервер — письмо сразу",
             server_alive.action("down", [issue("silent:crawl_watch", 1)], NOW), ("change", 7))
    проверка("к молчащему сторожу добавились письма — письмо сразу",
             server_alive.action("silent:crawl_watch+mail", [issue("silent:crawl_watch", 1)], NOW),
             ("change", 7))
    проверка("тот же состав — молчим",
             server_alive.action("silent:crawl_watch+mail",
                                 [issue("silent:crawl_watch+mail", 1)], NOW), ("none", 0))
    проверка("заголовок «не отвечает»",
             server_alive.title_text("down", "…", NOW, False), "Сервер не отвечает — 12.10.2026 22:00")
    проверка("заголовок по первым словам беды",
             server_alive.title_text("silent", "сервер отвечает, но письма тревог не уходят 61 мин; сторож витрины молчит 25 мин",
                                     NOW, False),
             "Сервер: письма тревог не уходят 61 мин — 12.10.2026 22:00")
    текст = server_alive.body_text("down", "сервер не отвечает", NOW, "", "Newik89", True)
    проверка("письмо: упоминание владельца, ПРОБА, киевское время",
             ("@Newik89" in текст, "ПРОБА" in текст, "12.10.2026 22:00" in текст),
             (True, True, True))


def гитхаб_тревога():
    print("Т1–Т4. scripts/alarm_issue.py — теги-письма → issue на день")
    refs = [{"ref": "refs/tags/alarm-1760300200"}, {"ref": "refs/tags/alarm-1760300100"},
            {"ref": "refs/tags/alarm-proba-1760300150"}, {"ref": "refs/tags/alarm-1 ;rm"},
            {"ref": "refs/tags/btn-days-2-1"}]
    проверка("Т1 все теги-письма, старые первыми, чужие — мимо", alarm_issue.pending_tags(refs),
             ["alarm-1760300100", "alarm-proba-1760300150", "alarm-1760300200"])
    проверка("Т3 заголовок по Киеву: 21:30 UTC 12.10 = 13.10",
             alarm_issue.today_title(datetime(2026, 10, 12, 21, 30, tzinfo=timezone.utc)),
             "Тревоги сервера — 13.10.2026")
    title = "Тревоги сервера — 12.10.2026"
    issues = [{"number": 9, "title": title}, {"number": 5, "title": "Тревоги сервера — 11.10.2026"}]
    проверка("Т3 сегодняшняя есть — комментарий в неё", alarm_issue.plan(issues, title), (9, [5]))
    проверка("Т3 сегодняшней нет — новая, вчерашнюю закрыть",
             alarm_issue.plan(issues[1:], title), (0, [5]))
    проверка("адрес в тексте скрыт", alarm_issue.clean("стук с 203.0.113.5 не дошёл"),
             "стук с <адрес> не дошёл")
    проверка("длинный текст обрезан",
             alarm_issue.clean("я" * (alarm_issue.MAX_CHARS + 50)).endswith("…(обрезано)"), True)
    print("  — Т5: метка письма, второго письма по тому же тегу нет")
    проверка("метка письма", alarm_issue.mark("alarm-1760300100"), "<!-- tag:alarm-1760300100 -->")
    ответы_api = {
        "/repos/s/issues/9/comments?per_page=100&page=1":
            (200, [{"body": "текст\n\n<!-- tag:alarm-1760300100 -->"}]),
    }
    прежний_api = alarm_issue.api
    alarm_issue.api = lambda token, method, path, body=None: ответы_api.get(path, (500, None))
    try:
        найдено = alarm_issue.sent_marks("t", "s", [{"number": 9,
                                                     "body": "<!-- tag:alarm-1760300050 -->"}])
        сбой = alarm_issue.sent_marks("t", "s", [{"number": 10, "body": ""}])
    finally:
        alarm_issue.api = прежний_api
    проверка("метки из тела и комментариев",
             найдено, {"<!-- tag:alarm-1760300050 -->", "<!-- tag:alarm-1760300100 -->"})
    проверка("GitHub не отдал комментарии — None (письма не шлём вслепую)", сбой, None)
    print("  — повторы запросов к API")
    ответы = iter([OSError("нет связи"), (502, "плохо"), (201, {"number": 1})])
    сны = []

    def звонок(token, method, path, body=None):
        r = next(ответы)
        if isinstance(r, Exception):
            raise r
        return r
    прежний = crawl_alarm.call
    crawl_alarm.call = звонок
    try:
        итог = crawl_alarm.call_retry("t", "POST", "/x", {}, tries=3, pause=5, sleep=сны.append)
    finally:
        crawl_alarm.call = прежний
    проверка("сбой связи и 502 — повтор, третья попытка прошла", (итог[0], сны), (201, [5, 5]))


def тег_с_текстом():
    print("тег. trigger — кириллица доезжает целой, без alarm.yml не шлём")
    repo = TMP / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)
    run("init", "-q")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
        "--allow-empty", "-m", "пусто")
    проверка("в коде без alarm.yml — тег не шлём", trigger.has_alarm_workflow(repo), False)
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "alarm.yml").write_text("name: x\n", encoding="utf-8")
    run("add", ".github/workflows/alarm.yml")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "alarm")
    проверка("alarm.yml в коде есть — можно", trigger.has_alarm_workflow(repo), True)
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
    сторож_витрины()
    гитхаб_жив()
    гитхаб_тревога()
    тег_с_текстом()
    страница()
    print(f"\nзелёных {зелёных}, красных {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Книга 126 (15.11): ход «сайт переехал» (`app/moved.py`, А1–А7).

Случай: сайт перенёс расписание на другой адрес, по старому — «страницы
нет» (HTTP 404 / 410), и сайт молча выпадал из сбора.

Запуск: python scripts/test_moved.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="moved-test-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import db, moved, reader_chain, redo  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def строка(domain: str, n: int = 1, итог: str = "не открылась",
           почему: str = "HTTP 404; браузер: HTTP 404 (браузер)", **job) -> dict:
    j = {"domain": domain, "channel": "", "url": f"https://{domain}/tv-program/day{n}",
         "day": "2026-11-15", "locale": "en-GB", "browser": False, "post": None, "warmup": "",
         "post_json": None, "headers": None, **job}
    return {**j, "итог": итог, "почему": почему, "байт": 0, "меток времени": 0, "чем": "requests"}


class Страница:
    def __init__(self, ok: bool, html: str = ""):
        self.ok, self.html = ok, html


ГЛАВНАЯ = """<html><body><a href="/">Home</a> <a href="/news">News</a>
<a href="/tv/schedule">TV Schedule</a> <a href="/about#x">About</a>
<a href="https://other.example/schedule">Partner schedule</a>
<a href="/sport/program-tv/guide">Program TV</a> <a href="/shop">Shop</a>
<a href="/tv-program/day1">Old page</a></body></html>"""


def качалка(сайты: dict, журнал: list):
    """Подмена `take`: {адрес: html} — что отдаёт сайт; остальное — 404."""
    def take(job):
        журнал.append(job["url"])
        html = сайты.get(job["url"])
        if html is None:
            return Страница(False), {**job, "итог": "не открылась", "почему": "HTTP 404"}
        return Страница(True, html), {**job, "итог": "расписание есть", "почему": "", "байт": len(html),
                                      "меток времени": 9, "чем": "requests", "файл": "new.html"}
    return take


настоящий = reader_chain.parser_rows
молчать = lambda *_: None  # noqa: E731

print("А1–А2. Кто «переехал»")
проверка("«страницы нет» — HTTP 404 и 410; защита, 5xx и сеть — нет",
         [moved.gone(строка("a.tv", почему=p)) for p in
          ("HTTP 404", "HTTP 410; браузер: HTTP 410 (браузер)", "HTTP 403", "HTTP 503",
           "ConnectTimeout: нет ответа")] + [moved.gone(строка("a.tv", итог="расписание есть", почему=""))],
         [True, True, False, False, False, False])
отчёт = [строка("gone.tv", 1), строка("www.gone.tv", 2),
         строка("half.tv", 1), строка("half.tv", 2, итог="расписание есть", почему=""),
         строка("ban.tv", 1, почему="HTTP 403"),
         строка("form.tv", 1, post={"a": "1"}),
         строка("ok.tv", 1, итог="расписание есть", почему="")]
проверка("переехал только сайт, у которого ВСЕ страницы «страницы нет» (и не форма)",
         sorted(moved.moved_sites(отчёт)), ["gone.tv"])

print("А8. Старый адрес перекидывает на главную")
проверка("запрос страницы расписания закончился на главной того же сайта — да",
         [moved.redirected_home(a, b) for a, b in (
             ("https://s.tv/tv-program/day1", "https://s.tv/"),
             ("https://www.s.tv/tv-program/day1", "https://s.tv"),
             ("https://s.tv/tv-program/day1", "https://s.tv/tv/guide"),
             ("https://s.tv/", "https://s.tv/"),
             ("https://s.tv/tv-program/day1", "https://other.tv/"),
             ("https://s.tv/tv-program/day1", ""))],
         [True, True, False, False, False, False])
проверка("строка «перекинуло на главную, расписания нет» — «страницы нет»; с расписанием — нет",
         [moved.gone(строка("r.tv", итог="пусто", почему="времени на странице нет", переадресация=moved.HOME_MARK)),
          moved.gone(строка("r.tv", итог="расписание есть", почему="", переадресация=moved.HOME_MARK)),
          moved.gone(строка("r.tv", итог="пусто", почему="времени на странице нет"))],
         [True, False, False])
проверка("сайт, у которого все страницы перекидывает на главную, — «переехал»",
         sorted(moved.moved_sites([
             строка("r.tv", 1, итог="пусто", почему="времени на странице нет", переадресация=moved.HOME_MARK),
             строка("r.tv", 2, итог="пусто", почему="времени на странице нет", переадресация=moved.HOME_MARK),
             строка("ok.tv", 1, итог="расписание есть", почему="")])), ["r.tv"])
проверка("задание обхода из такой строки — без пометки переадресации",
         "переадресация" in redo.job_of(строка("r.tv", переадресация=moved.HOME_MARK)), False)

print("А3. Ссылки-кандидаты с главной")
ссылки = moved.links(ГЛАВНАЯ, "https://gone.tv/", "gone.tv", {"https://gone.tv/tv-program/day1"})
проверка("только свой сайт, со словом «программа / расписание», без старого адреса; лучшие — первыми",
         ссылки, ["https://gone.tv/sport/program-tv/guide", "https://gone.tv/tv/schedule"])
проверка("слова на разных языках: расписание по-хорватски, по-русски, по-гречески, по-венгерски",
         [bool(moved.links(f'<a href="/{w}">x</a>', "https://s.tv/", "s.tv", set()))
          for w in ("raspored", "teleprogramma", "programma", "musor")] +
         [bool(moved.links('<a href="/tv">Телепрограмма</a>', "https://s.tv/", "s.tv", set())),
          bool(moved.links('<a href="/tv">Πρόγραμμα</a>', "https://s.tv/", "s.tv", set())),
          bool(moved.links('<a href="/shop">Shop</a>', "https://s.tv/", "s.tv", set()))],
         [True, True, True, True, True, True, False])

MOJTV = ('<a href="/tv-program/">TV program</a><a href="/tv-program/bih">BiH</a>'
         '<a href="/tv-program/srpski">Srpski</a><a href="/tv-program/sportski">Sportski</a>'
         '<a href="/tv-program/filmski">Filmski</a>')
проверка("случай mojtv.hr: без подсказки спортивный раздел в первую тройку не попадает",
         "https://mojtv.hr/tv-program/sportski" in moved.links(MOJTV, "https://mojtv.hr/", "mojtv.hr", set()),
         False)
проверка("…с подсказкой прежнего адреса — он первый (в прежнем пути было слово «sportski»)",
         moved.links(MOJTV, "https://mojtv.hr/", "mojtv.hr", set(),
                     hint="https://mojtv.hr/tv-program/-2/sportski/2026-11-15.aspx")[0],
         "https://mojtv.hr/tv-program/sportski")

print("А4–А5. Новый адрес принят, только если свой разборщик прочитал строки")
reader_chain.parser_rows = lambda job, html, setting=None: 12 if "сетка" in html else 0
журнал: list = []
отчёт = [строка("gone.tv", 1), строка("gone.tv", 2), строка("ok.tv", 1, итог="расписание есть", почему="")]
итог = moved.run(отчёт, качалка({"https://gone.tv/": ГЛАВНАЯ,
                                 "https://gone.tv/sport/program-tv/guide": "<p>реклама</p>",
                                 "https://gone.tv/tv/schedule": "<p>сетка</p>"}, журнал),
                 redo.job_of, say=молчать)
проверка("ходили: главная, первый кандидат (строк нет), второй кандидат (принят)",
         журнал, ["https://gone.tv/", "https://gone.tv/sport/program-tv/guide", "https://gone.tv/tv/schedule"])
проверка("в отчёт дописана строка нового адреса с пометкой, старые строки на месте",
         (len(отчёт), отчёт[-1]["url"], отчёт[-1]["итог"], отчёт[-1]["чем"],
          "новый адрес" in отчёт[-1]["почему"], отчёт[-1]["domain"], отчёт[-1]["day"], отчёт[0]["итог"]),
         (4, "https://gone.tv/tv/schedule", "расписание есть", moved.VIA, True, "gone.tv",
          "2026-11-15", "не открылась"))
проверка("раздел отчёта: был — стал — сколько строк",
         итог["найдено"], {"gone.tv": {"был": "https://gone.tv/tv-program/day1",
                                       "стал": "https://gone.tv/tv/schedule", "строк": 12}})
журнал = []
отчёт = [строка("lost.tv", 1)]
итог = moved.run(отчёт, качалка({"https://lost.tv/": ГЛАВНАЯ.replace("gone.tv", "lost.tv")}, журнал),
                 redo.job_of, say=молчать)
проверка("кандидаты не открылись — «не найдено», отчёт не тронут, запросов не больше 1 + 3",
         (итог["не_найдено"], len(отчёт), len(журнал) <= 1 + moved.CANDIDATES), (["lost.tv"], 1, True))
журнал = []
итог = moved.run([строка("dead.tv", 1)], качалка({}, журнал), redo.job_of, say=молчать)
проверка("главная тоже не открылась — «не найдено», один запрос",
         (итог["не_найдено"], журнал), (["dead.tv"], ["https://dead.tv/"]))

print("А2, А6. Массовый сбой и пределы")
журнал = []
массовый = [строка(f"s{n}.tv", 1) for n in range(12)]
итог = moved.run(массовый, качалка({}, журнал), redo.job_of, say=молчать)
проверка("массовый сбой сбора — никого не ищем, запросов нет",
         (итог["найдено"], итог["не_найдено"], журнал), ({}, [], []))
журнал = []
много = [строка(f"m{n}.tv", 1) for n in range(5)] + \
        [строка(f"ok{n}.tv", 1, итог="расписание есть", почему="") for n in range(30)]
итог = moved.run(много, качалка({}, журнал), redo.job_of, say=молчать)
проверка(f"за сбор — не больше {moved.MAX_SITES} сайтов, остальные ждут следующего",
         (len(итог["не_найдено"]), len(итог["ждут"]), len(журнал)), (moved.MAX_SITES, 2, moved.MAX_SITES))
reader_chain.parser_rows = настоящий

print("А7. Уведомление — одна строка на сайт в сутки")
раздел = {"найдено": {"gone.tv": {"был": "https://gone.tv/a", "стал": "https://gone.tv/b", "строк": 12}},
          "не_найдено": ["lost.tv"], "ждут": []}
слова = moved.words(раздел)
проверка("про найденный — был и стал; про ненайденный — нужен новый адрес",
         ("https://gone.tv/a" in слова["gone.tv"] and "https://gone.tv/b" in слова["gone.tv"],
          "новый адрес на главной странице не найден" in слова["lost.tv"]), (True, True))
db.init_db()
conn = db.connect()
проверка("заливка: по строке на сайт", len(moved.after_import(conn, {moved.REPORT_KEY: раздел}, "2026-11-15")), 2)
проверка("вторая заливка в тот же день — молчим",
         moved.after_import(conn, {moved.REPORT_KEY: раздел}, "2026-11-15"), [])
проверка("на следующий день — снова", len(moved.after_import(conn, {moved.REPORT_KEY: раздел}, "2026-11-16")), 2)
проверка("отчёт без раздела — без падения", moved.after_import(conn, {}, "2026-11-16"), [])
conn.close()

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

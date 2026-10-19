# -*- coding: utf-8 -*-
r"""Разбор телегида dir.bg (`app/parsers/tv_dir_bg.py`, слово владельца
18.10.2026: «нужно расписание bTV Action»). По проверке на каждое правило
модуля; страницы — настоящие ответы сайта, снятые с сервера 18.10
(`scripts/testdata/tv_dir_bg_*`, картинки вырезаны): bTV Action на 22.10
(панели 21.10, 22.10, 23.10) и BNT 1 на 19.10 (панели «Днес», «Утре», 20.10).

Здесь же проверка загрузчика (`app/fetch.py`): ключ со страницы разогрева
подставляется не только в первый, но и в каждый следующий запрос к хосту —
на подменённом `requests`, в сеть не ходит.

    python scripts/test_tv_dir_bg.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import daytime, fetch, live, parsers  # noqa: E402
from app.parsers import tv_dir_bg  # noqa: E402

DATA = ROOT / "scripts" / "testdata"
URL_95 = "https://tv.dir.bg/load/programs?channel=95&day=2026-10-22"
URL_57 = "https://tv.dir.bg/load/programs?channel=57&day=2026-10-19"

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def страница(имя: str) -> str:
    return (DATA / имя).read_text(encoding="utf-8")


parse = parsers.get("tv.dir.bg")
btv = parse(страница("tv_dir_bg_95_2026-10-22.json"), url=URL_95)
btv_21 = parse(страница("tv_dir_bg_95_2026-10-22.json"),
               url="https://tv.dir.bg/load/programs?channel=95&day=2026-10-21")
bnt = parse(страница("tv_dir_bg_57_2026-10-19.json"), day=date(2026, 10, 19), url=URL_57)


def найти(строки: list, время: str) -> list:
    return [p for p in строки if p.raw_time == время]


def момент(p) -> str:
    return p.start.strftime("%Y-%m-%d %H:%M %z")


print("правило 1: ответ — JSON, разметка в поле html")
проверка("парсер зарегистрирован на tv.dir.bg", parse is not None, True)
проверка("bTV Action 22.10 — 21 строка", len(btv), 21)
проверка("status ложный — пусто",
         parse('{"status": false, "html": "<div class=\\"panel\\"></div>"}', url=URL_95), [])
проверка("не JSON — пусто", parse("<html><body>нет</body></html>", url=URL_95), [])
проверка("голая разметка без JSON — тоже разбирается", len(parse(
    json.loads(страница("tv_dir_bg_95_2026-10-22.json"))["html"], url=URL_95)), 21)

print("правило 2: канал — по ?channel= из адреса, имена как в alt на /channels")
проверка("95 → bTV Action", {p.channel_raw for p in btv}, {"bTV Action"})
проверка("57 → BNT1 (БНТ1)", {p.channel_raw for p in bnt}, {"BNT1 (БНТ1)"})
проверка("незнакомый номер → канал tv.dir.bg, строки не теряются",
         {p.channel_raw for p in parse(страница("tv_dir_bg_95_2026-10-22.json"),
                                       url="https://tv.dir.bg/load/programs?channel=60&day=2026-10-22")},
         {"tv.dir.bg"})
проверка("фильтр каналов карточки",
         parse(страница("tv_dir_bg_95_2026-10-22.json"), url=URL_95, channels={"bTV"}), [])
каналы = tv_dir_bg.list_channels(страница("tv_dir_bg_channels.html"))
проверка("страница /channels: 100 каналов", len(каналы), 100)
проверка("NAMES совпадают с alt сайта по всем семи номерам",
         {k: каналы.get(k) for k in tv_dir_bg.NAMES}, tv_dir_bg.NAMES)

print("правило 3: день запроса — из адреса, иначе от обхода, иначе сегодня по Софии")
проверка("&day= в адресе сильнее day обхода",
         tv_dir_bg.request_day(URL_95, date(2026, 10, 19), "Europe/Sofia"), date(2026, 10, 22))
проверка("без адреса — day обхода",
         tv_dir_bg.request_day("", date(2026, 10, 19), "Europe/Sofia"), date(2026, 10, 19))
проверка("ни адреса, ни дня — сегодня по Софии",
         tv_dir_bg.request_day("", None, "Europe/Sofia"), daytime.today("Europe/Sofia"))

print("правило 4: панели — сутки; подписи ДД.ММ / Днес / Утре; берём панель дня запроса")
проверка("21.10, 22.10, 23.10 при запросе 22.10",
         tv_dir_bg.panel_days(["21.10", "22.10", "23.10"], date(2026, 10, 22)),
         [date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)])
проверка("Днес, Утре, 20.10 при запросе 19.10 — слова по соседней дате",
         tv_dir_bg.panel_days(["Днес", "Утре", "20.10"], date(2026, 10, 19)),
         [date(2026, 10, 18), date(2026, 10, 19), date(2026, 10, 20)])
проверка("одни слова — средняя панель = день запроса",
         tv_dir_bg.panel_days(["Вчера", "Днес", "Утре"], date(2026, 10, 19)),
         [date(2026, 10, 18), date(2026, 10, 19), date(2026, 10, 20)])
проверка("смена года: 31.12, 01.01, 02.01 при запросе 01.01.2027",
         tv_dir_bg.panel_days(["31.12", "01.01", "02.01"], date(2027, 1, 1)),
         [date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 2)])
проверка("панель 21.10 в ответ на 22.10 не берётся: Комо — Манчестър Юнайтед нет",
         [p.match_raw for p in btv if "Комо" in p.match_raw], [])
проверка("тот же ответ на запрос 21.10 — берётся панель 21.10",
         [(p.raw_time, p.match_raw) for p in btv_21 if p.match_raw.strip()],
         [("19:45", "Комо - Манчестър Юнайтед"), ("22:00", "Байерн Мюнхен - Арсенал"),
          ("01:15", "Астън Вила - Викинг")])
проверка("BNT 1: панель «Утре» = 19.10, 38 строк", len(bnt), 38)

print("правило 5: телесутки с 06:00, время назад — следующий день; пояс Europe/Sofia")
проверка("22:00 22.10 Софии = +0300", момент(найти(btv, "22:00")[0]), "2026-10-22 22:00 +0300")
проверка("00:00 после 22:00 — уже 23.10", момент(найти(btv, "00:00")[0]), "2026-10-23 00:00 +0300")
проверка("05:00 — хвост ночи 23.10", момент(найти(btv, "05:00")[0]), "2026-10-23 05:00 +0300")
проверка("BNT 1: 05:55 — начало 19.10", момент(найти(bnt, "05:55")[0]), "2026-10-19 05:55 +0300")
проверка("BNT 1: 00:15 после 23:25 — 20.10", момент(найти(bnt, "00:15")[0]), "2026-10-20 00:15 +0300")
проверка("extra.day — календарная дата начала",
         (найти(btv, "22:00")[0].extra["day"], найти(btv, "00:00")[0].extra["day"]),
         ("2026-10-22", "2026-10-23"))

print("правило 6: название одной строкой, хвост сериала прижат и снимается перед парой")
проверка("запятые хвоста прижаты",
         tv_dir_bg.clean_title("Екоавтомобили\n   , сезон 2\n   , епизод 7"),
         "Екоавтомобили, сезон 2, епизод 7")
проверка("06:00 на bTV Action", найти(btv, "06:00")[0].title, "Екоавтомобили, сезон 2, епизод 9")
for фраза, ждём in (("Екоавтомобили, сезон 2, епизод 7", "Екоавтомобили"),
                    ("Последният печели, сезон 7", "Последният печели"),
                    ("Блуи, епизод 3", "Блуи"),
                    ("Студио \"УЕФА Шампионска лига\"", "Студио \"УЕФА Шампионска лига\"")):
    проверка(f"хвост сериала: «{фраза}» → «{ждём}»", tv_dir_bg.strip_series(фраза), ждём)

print("правило 7: эфир — приставка ПРЯКО: пометка сайта «пряко», приставка снимается")
нордшеланд = найти(btv, "19:45")[0]
проверка("19:45 Нордшеланд — ЦСКА: live_raw «пряко», пометка сайта",
         (нордшеланд.live_raw, нордшеланд.extra.get(parsers.SITE_FLAG)), ("пряко", parsers.SITE_LIVE))
проверка("приставка снята из названия", нордшеланд.title,
         "УЕФА Лига на конференциите: Нордшеланд - ЦСКА")
проверка("00:00 «УЕФА Лига Европа» без ПРЯКО — маркера нет",
         (найти(btv, "00:00")[0].live_raw, найти(btv, "00:00")[0].extra.get(parsers.SITE_FLAG)),
         ("", None))
проверка("Астън Вила — Викинг 01:15 без ПРЯКО — маркера нет (запись)",
         найти(btv_21, "01:15")[0].live_raw, "")
проверка("эфиров на bTV Action 22.10 ровно два",
         [p.match_raw for p in btv if p.live_raw], ["Нордшеланд - ЦСКА", "Борнемут - Милан"])
маркеры = live.load()
проверка("отсев: Нордшеланд — ЦСКА с «пряко» — эфир, пара видна",
         (live.check(нордшеланд, маркеры).ok, live.check(нордшеланд, маркеры).home,
          live.check(нордшеланд, маркеры).away), (True, "Нордшеланд", "ЦСКА"))
проверка("отсев: Астън Вила — Викинг без ПРЯКО — «нет маркера прямого эфира»",
         live.check(найти(btv_21, "01:15")[0], маркеры).reason, "нет маркера прямого эфира")
проверка("отсев: студия снята стоп-словом",
         live.check(найти(btv, "18:30")[0], маркеры).ok, False)

print("правило 8: лига и пара по последнему «: »; пара только при турнире или ПРЯКО")
for фраза, ждём in (
        ("ПРЯКО: УЕФА Шампионска лига: Комо - Манчестър Юнайтед",
         (True, "УЕФА Шампионска лига", "Комо - Манчестър Юнайтед")),
        ("УЕФА Шампионска лига: Астън Вила - Викинг",
         (False, "УЕФА Шампионска лига", "Астън Вила - Викинг")),
        ("Костенурките нинджа - нова мутация, сезон 3, епизод 12", (False, "", " ")),
        ("ПРЯКО: Лудогорец - Левски", (True, "", "Лудогорец - Левски")),
        ("пряко: Лудогорец - Левски", (True, "", "Лудогорец - Левски")),
        ("Футбол: Първа лига: Лудогорец - Левски",
         (False, "Футбол: Първа лига", "Лудогорец - Левски")),
        ("Студио \"УЕФА Шампионска лига\"", (False, "", " ")),
        ("УЕФА Шампионска лига", (False, "", " ")),
        ("Смъртоносно оръжие, сезон 2, епизод 1", (False, "", " "))):
    проверка(f"«{фраза}»", tv_dir_bg.split_title(фраза), ждём)
проверка("лига у Борнемут — Милан", найти(btv, "22:00")[0].league_raw, "УЕФА Лига Европа")
проверка("BNT 1: сериал с дефисом пары не даёт",
         [p.match_raw for p in bnt if "нинджа" in p.title], [" "])

print("правило 9: пара только при двух непустых именах")
for фраза, ждём in (("ПРЯКО: Лига: - Левски", " "),
                    ("ПРЯКО: Лига: Левски -", " "),
                    ("ПРЯКО: Лига: Левски - ЦСКА", "Левски - ЦСКА")):
    проверка(f"«{фраза}»", tv_dir_bg.split_title(фраза)[2], ждём)
проверка("у строк без пары match_raw = « »",
         {p.match_raw for p in bnt}, {" "})
проверка("source_url — адрес запроса", {p.source_url for p in btv}, {URL_95})

print("загрузчик: ключ разогрева подставляется и во второй запрос к хосту")


class _Ответ:
    def __init__(self, text: str):
        self.status_code = 200
        self.headers = {"content-type": "application/json; charset=utf-8"}
        self.text = text
        self.content = text.encode("utf-8")


журнал: list = []


class _Сессия:
    def __init__(self):
        журнал.append("сессия")

    def get(self, url, **kw):
        журнал.append(("get", url))
        if url.endswith("/init"):
            return _Ответ('{"csrfToken":"KLYUCH40"}')
        if "sporteventz" in url:
            return _Ответ("<html>var accesskey=777;</html>")
        return _Ответ('{"status":true,"html":"<div class=\\"panel\\"></div>"}')

    def post(self, url, data=None, **kw):
        журнал.append(("post", url, dict(data or {})))
        return _Ответ('{"status":true,"html":"<div class=\\"panel\\"></div>"}')


def _без_сессии(*a, **kw):
    raise AssertionError("запрос ушёл мимо сессии")


подмена = types.ModuleType("requests")
подмена.Session = _Сессия
подмена.get = подмена.post = _без_сессии
sys.modules["requests"] = подмена
fetch.CACHE = Path(tempfile.mkdtemp(prefix="dirbg-fetch-"))
fetch.DELAY = 0

грузчик = fetch.Fetcher(offline=False, use_cache=False)
первый = грузчик.get(URL_95, post={"_token": "{WARMKEY}"}, warmup="https://tv.dir.bg/init")
второй = грузчик.get("https://tv.dir.bg/load/programs?channel=57&day=2026-10-22",
                    post={"_token": "{WARMKEY}"}, warmup="https://tv.dir.bg/init")
посты = [z for z in журнал if z[0] == "post"]
проверка("оба ответа получены", (первый.ok, второй.ok), (True, True))
проверка("разогрев — один раз на хост",
         [z for z in журнал if z[0] == "get"], [("get", "https://tv.dir.bg/init")])
проверка("ключ в первом запросе", посты[0][2], {"_token": "KLYUCH40"})
проверка("ключ и во втором запросе (дыра до 18.10: оставалось {WARMKEY})",
         посты[1][2], {"_token": "KLYUCH40"})
проверка("адрес второго запроса — свой канал", посты[1][1],
         "https://tv.dir.bg/load/programs?channel=57&day=2026-10-22")
журнал.clear()
sporteventz = грузчик.get("https://sporteventz.com/index.php?accesskey={WARMKEY}&table=1",
                          warmup="https://sporteventz.com/en/")
проверка("sporteventz: ключ в адресе первого запроса — как и раньше",
         [z for z in журнал if z[0] == "get"],
         [("get", "https://sporteventz.com/en/"),
          ("get", "https://sporteventz.com/index.php?accesskey=777&table=1")])
проверка("fill_warmkey без ключа ничего не трогает",
         fetch.fill_warmkey("https://x/?k={WARMKEY}", {"_token": "{WARMKEY}"}, ""),
         ("https://x/?k={WARMKEY}", {"_token": "{WARMKEY}"}))

print(f"\nитог: {зелёных} зелёных, {красных} красных")
sys.exit(1 if красных else 0)

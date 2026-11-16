# -*- coding: utf-8 -*-
r"""Книга 151 (16.11.2026): страница дня начата передачей вчерашнего вечера.

Находка: страница movistarplus.es за 15.11 (M+ Deportes 2) начиналась строкой
`23:05` — передача шла ещё с вечера 14.11. Разборщик считал сутки приёмом
«время уменьшилось — прибавь день», первую строку ставил на 15.11, а весь
остальной день — на 16.11. Четыре прямых эфира ATP Finals 15.11 были сняты
как запись.

Замер по всем страницам сборов #475 и #491: тот же приём (свой счётчик
полуночи, без общего `daytime.walk_day`) — у 14 разборщиков; страниц с
хвостом вечера в сборах — по 2 из 192 у movistarplus.es, у остальных 13
таких страниц не было, но ошибка у них та же.

Правило общее (`app/daytime.py`): `evening_tail` — три признака хвоста вечера,
`pull_evening_tail` — сдвиг списка канала на сутки назад. Его зовут все
разборщики со своим счётчиком полуночи.
В сеть не ходит, от сегодняшней даты не зависит.
Запуск: python scripts/test_hvost_vechera.py
"""
from __future__ import annotations

import html as _html
import inspect
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import daytime, parsers  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.parsers import (diemaxtra_bg, hrt_hr, movistarplus_es, news_by,  # noqa: E402
                         novasports_gr, programme_tv_net, rtl_de,
                         trtavaz_com_tr, tv8_com_tr, tv24_co_uk,
                         tvguidetonight_com_au, unian_tv, vsetv_com)

MADRID = ZoneInfo("Europe/Madrid")
зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def часы(*времена: str) -> list[tuple[int, int]]:
    """`"23:05", "08:00"` → [(23, 5), (8, 0)]."""
    return [(int(t[:2]), int(t[3:])) for t in времена]


print("1. Три признака хвоста вечера (`daytime.evening_tail`)")
проверка("страница movistarplus 15.11: 23:05, затем целый день — хвост вечера",
         daytime.evening_tail(часы("23:05", "08:00", "11:35", "14:00", "20:30", "00:30", "05:30")))
проверка("редкий канал (M+ Vamos 2, 18.11): 22:40, 08:00, 20:00, 00:00 — хвост вечера",
         daytime.evening_tail(часы("22:40", "08:00", "20:00", "00:00")))
проверка("правило 1: первая строка не поздняя (00:05, 12:05, 00:00) — не хвост",
         daytime.evening_tail(часы("00:05", "12:05", "00:00")), False)
проверка("правило 1: первая строка днём (14:00), дальше ночь и день — не хвост",
         daytime.evening_tail(часы("14:00", "02:00", "13:00")), False)
проверка("правило 2: обычная страница (06:00 … 23:45, 00:30, 04:00) — не хвост",
         daytime.evening_tail(часы("06:00", "12:00", "23:45", "00:30", "04:00")), False)
проверка("правило 2: полночь не сразу за первой строкой (22:00, 23:30, 08:00, 14:00) — не хвост",
         daytime.evening_tail(часы("22:00", "23:30", "08:00", "14:00")), False)
проверка("правило 2: шаг назад меньше четырёх часов (23:00, 21:30, 13:00) — наложение, не полночь",
         daytime.evening_tail(часы("23:00", "21:30", "13:00")), False)
проверка("правило 3: остаток дня (23:30, 00:00, 04:53) — за полночью только ночь, не хвост",
         daytime.evening_tail(часы("23:30", "00:00", "04:53")), False)
проверка("правило 3: до полудня страница доходит только после ВТОРОЙ полуночи — не хвост",
         daytime.evening_tail(часы("23:00", "02:00", "05:00", "00:30", "13:00")), False)
проверка("одна строка и пустой список — не хвост",
         [daytime.evening_tail(часы("23:05")), daytime.evening_tail([])], [False, False])


def строка(канал: str, день: int, время: str, с_днём: bool = True) -> Program:
    """Строка, как её отдаёт разборщик со своим счётчиком полуночи."""
    start = datetime(2026, 11, день, int(время[:2]), int(время[3:]), tzinfo=MADRID)
    return Program(channel_raw=канал, title=f"{канал} {время}", start=start, raw_time=время,
                   extra={"day": start.date().isoformat()} if с_днём else {})


print("2. Сдвиг списка канала на сутки назад (`daytime.pull_evening_tail`)")
хвост = [строка("A", 15, "23:05"), строка("A", 16, "08:00"), строка("A", 16, "14:00"),
         строка("A", 17, "00:30")]
обычный = [строка("B", 15, "06:00"), строка("B", 15, "23:45"), строка("B", 16, "00:30")]
без_времени = Program(channel_raw="A", title="без времени", start=None)
вместе = [хвост[0], обычный[0], хвост[1], без_времени, обычный[1], хвост[2], обычный[2], хвост[3]]
итог = daytime.pull_evening_tail(вместе)
проверка("возвращает тот же список в том же порядке", итог is вместе and [p.title for p in итог][:2],
         ["A 23:05", "B 06:00"])
проверка("правило 2: канал с хвостом — все строки на сутки назад, время суток то же",
         [p.start.strftime("%d %H:%M") for p in хвост],
         ["14 23:05", "15 08:00", "15 14:00", "16 00:30"])
проверка("правило 3: `extra[\"day\"]` переписан под новую дату",
         [p.extra["day"] for p in хвост],
         ["2026-11-14", "2026-11-15", "2026-11-15", "2026-11-16"])
проверка("правило 4: соседний канал той же страницы без хвоста не тронут",
         [p.start.strftime("%d %H:%M") for p in обычный], ["15 06:00", "15 23:45", "16 00:30"])
проверка("правило 1: строка без времени остаётся без времени", без_времени.start, None)
без_дня = [строка("C", 15, "23:05", с_днём=False), строка("C", 16, "13:00", с_днём=False)]
daytime.pull_evening_tail(без_дня)
проверка("строке без `extra[\"day\"]` ключ не дописывается",
         [(p.start.day, p.extra) for p in без_дня], [(14, {}), (15, {})])
остаток = [строка("D", 15, "23:30"), строка("D", 16, "00:00"), строка("D", 16, "04:53")]
daytime.pull_evening_tail(остаток)
проверка("остаток дня (23:30, 00:00, 04:53) остаётся как был: ночь — уже завтра",
         [p.start.strftime("%d %H:%M") for p in остаток], ["15 23:30", "16 00:00", "16 04:53"])


def movistar(канал: str, *передачи: tuple[str, str]) -> str:
    """Страница movistarplus.es: канал и строки (время, заголовок)."""
    boxes = "".join(
        f'<div class="container_box"><ul><li class="genre">Deportes</li>'
        f'<li class="title">{_html.escape(заголовок)}</li><li class="time">{время}</li></ul></div>'
        for время, заголовок in передачи)
    return (f'<html><body><div class="info-canal"><div class="titulo">'
            f'<a href="#">Ver canal {канал}</a></div></div>{boxes}</body></html>')


print("3. Разборщик movistarplus.es на странице с хвостом вечера")
адрес = "https://www.movistarplus.es/programacion-tv/MVDP2/2026-11-15"
страница = movistar(
    "M+ Deportes 2",
    ("23:05", "M+ Deportes 2"), ("08:00", "M+ Deportes 2"),
    ("11:35", "Nitto ATP Finals 2026 (T2026): Heliovaara/Patten - Matos/Luz"),
    ("14:00", "Nitto ATP Finals 2026 (T2026): Zverev - Jódar"),
    ("20:30", "Nitto ATP Finals 2026 (T2026): Shelton - Fils"),
    ("00:30", "Nitto ATP Finals 2026 (T2026): Zverev - Jódar"), ("05:30", "M+ Deportes 2"))
строки = movistarplus_es.parse(страница, day=date(2026, 11, 15), url=адрес)
проверка("случай 15.11: первая строка 23:05 — вчера, эфиры — в день страницы, ночь — завтра",
         [p.start.strftime("%d.%m %H:%M") for p in строки],
         ["14.11 23:05", "15.11 08:00", "15.11 11:35", "15.11 14:00", "15.11 20:30",
          "16.11 00:30", "16.11 05:30"])
проверка("эфир «Zverev - Jódar» 15.11 14:00 — первый показ пары (угаданный эфир), ночной показ — повтор",
         [(p.start.strftime("%d.%m %H:%M"), bool(p.live_raw)) for p in строки
          if "Zverev" in p.title],
         [("15.11 14:00", True), ("16.11 00:30", False)])
обычная = movistarplus_es.parse(
    movistar("DAZN 1", ("06:00", "Motor"), ("14:35", "Premier League (T26/27): Aston Villa - Arsenal"),
             ("23:30", "Resumen"), ("00:00", "Motor"), ("04:53", "Motor")),
    day=date(2026, 11, 15), url="https://www.movistarplus.es/programacion-tv/DAZN1/2026-11-15")
проверка("обычная страница не сдвинулась: день — день страницы, после 23:30 — завтра",
         [p.start.strftime("%d.%m %H:%M") for p in обычная],
         ["15.11 06:00", "15.11 14:35", "15.11 23:30", "16.11 00:00", "16.11 04:53"])
вечер = movistarplus_es.parse(
    movistar("DAZN 2", ("23:30", "Resumen"), ("00:00", "Motor"), ("04:53", "Motor")),
    day=date(2026, 11, 15), url="https://www.movistarplus.es/programacion-tv/DAZN2/2026-11-15")
проверка("остаток дня (23:30, 00:00, 04:53) не сдвинулся",
         [p.start.strftime("%d.%m %H:%M") for p in вечер],
         ["15.11 23:30", "16.11 00:00", "16.11 04:53"])

print("4. Недельная сетка news.by: поправка считается по каждому дню отдельно")


def астро(значение):
    """Сериализация Astro: объект — `[0, …]`, массив — `[1, […]]`."""
    if isinstance(значение, dict):
        return [0, {k: астро(v) for k, v in значение.items()}]
    if isinstance(значение, list):
        return [1, [астро(v) for v in значение]]
    return [0, значение]


def день_недели(*передачи: tuple[str, str]) -> dict:
    return {"programs": [{"time": t, "program": p} for t, p in передачи]}


неделя = {"data": {"schedules": [{
    "start_date": "2026-11-16", "finish_date": "2026-11-22",
    "schedule": {
        "Понедельник": день_недели(("07:00", "Утро"), ("22:50", "Вечер"), ("00:54", "Ночь")),
        "Вторник": день_недели(("23:10", "Хвост понедельника"), ("07:00", "Утро"),
                               ("13:00", "День"), ("00:30", "Ночь")),
    }}]}}
props = _html.escape(json.dumps(астро(неделя), ensure_ascii=False), quote=True)
сетка = news_by.parse(f'<astro-island props="{props}"></astro-island>',
                      url="https://news.by/programma-tv/belarus-5")
проверка("понедельник — как был; вторник начат хвостом 23:10: он в понедельник, день — во вторник",
         [(p.start.strftime("%d.%m %H:%M"), p.title, p.extra["day"]) for p in сетка],
         [("16.11 07:00", "Утро", "2026-11-16"), ("16.11 22:50", "Вечер", "2026-11-16"),
          ("17.11 00:54", "Ночь", "2026-11-17"),
          ("16.11 23:10", "Хвост понедельника", "2026-11-16"), ("17.11 07:00", "Утро", "2026-11-17"),
          ("17.11 13:00", "День", "2026-11-17"), ("18.11 00:30", "Ночь", "2026-11-18")])

print("5. Вкладки дней diemaxtra.nova.bg: поправка считается по каждой вкладке отдельно")


def вкладка(имя: str, *передачи: tuple[str, str]) -> str:
    li = "".join(f'<li><p class="time">{t}</p><p class="title">{_html.escape(p)}</p>'
                 f'<p class="description"></p></li>' for t, p in передачи)
    return f'<div id="{имя}"><ul class="tv_content">{li}</ul></div>'


диема = (
    '<html><head><title>Програма - Diemasport - Diema xtra</title></head><body>'
    '<a data-toggle="tab" href="#monday"><span class="day">пн</span><span class="date">16 ное</span></a>'
    '<a data-toggle="tab" href="#tuesday"><span class="day">вт</span><span class="date">17 ное</span></a>'
    + вкладка("monday", ("06.30", "Утро"), ("23.40", "Вечер"), ("00.15", "Ночь"))
    + вкладка("tuesday", ("23.40", "Хвост"), ("06.30", "Утро"), ("12.30", "День"), ("00.15", "Ночь"))
    + '</body></html>')
сетка = diemaxtra_bg.parse(диема, day=date(2026, 11, 16),
                           url="https://diemaxtra.nova.bg/diemasport/schedule")
проверка("вкладка понедельника — как была; вкладка вторника начата хвостом 23.40",
         [(p.start.strftime("%d.%m %H:%M"), p.title) for p in сетка],
         [("16.11 06:30", "Утро"), ("16.11 23:40", "Вечер"), ("17.11 00:15", "Ночь"),
          ("16.11 23:40", "Хвост"), ("17.11 06:30", "Утро"), ("17.11 12:30", "День"),
          ("18.11 00:15", "Ночь")])

print("6. Класс ошибки закрыт у всех: каждый разборщик со своим счётчиком полуночи зовёт общую поправку")
СВОЙ_СЧЁТЧИК = (diemaxtra_bg, hrt_hr, movistarplus_es, news_by, novasports_gr, programme_tv_net,
                rtl_de, trtavaz_com_tr, tv8_com_tr, tv24_co_uk, tvguidetonight_com_au, unian_tv,
                vsetv_com)
проверка("13 разборщиков зовут `daytime.pull_evening_tail`",
         [m.__name__.rsplit(".", 1)[-1] for m in СВОЙ_СЧЁТЧИК
          if "daytime.pull_evening_tail(" not in inspect.getsource(m)], [])
parsers._load_all()
проверка("все тринадцать по-прежнему в реестре разборщиков",
         [m.DOMAIN for m in СВОЙ_СЧЁТЧИК if parsers.REGISTRY.get(m.DOMAIN) is None], [])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

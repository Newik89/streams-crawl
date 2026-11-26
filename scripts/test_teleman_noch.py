# -*- coding: utf-8 -*-
r"""Книга 179 (26.11.2026): ночная строка teleman.pl — день после «na».

Жалоба владельца 26.11 («на витрине начали появляться лишние игры»): игра НБА
Houston — Lakers стояла 30.11 в 02:30 (#11952, teleman.pl, Eurosport 3), а
настоящий матч — 01.12 в 02:30 (#12025). Сайт пишет ночные строки двумя
датами: «noc pon./wt., 30 listopada na 1 grudnia | 1:30». Разборщик брал
первое «число + слово»:
  * «30 listopada na 1 grudnia» читалось 30-м — на сутки раньше;
  * «28 na 29 listopada» — «28 na» не месяц, строка терялась вовсе (в сборе
    26.11 таких 20 из 600).
Правило (`teleman_pl._cell_date`): у ночной строки день — второй, после «na».
Класс проверен по страницам всех сайтов сбора 26.11: подпись ночи двумя
датами есть только у teleman.pl.
В сеть не ходит. Запуск: python scripts/test_teleman_noch.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.parsers import teleman_pl  # noqa: E402

зелёных = красных = 0
ДЕНЬ = date(2026, 11, 26)


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


print("1. Дата ячейки (`_cell_date`)")
проверка("ночь на стыке месяцев — день после «na»: «30 listopada na 1 grudnia» → 1 декабря",
         teleman_pl._cell_date("noc pon./wt., 30 listopada na 1 grudnia", ДЕНЬ), date(2026, 12, 1))
проверка("ночь внутри месяца — «28 na 29 listopada» → 29 ноября (раньше строка терялась)",
         teleman_pl._cell_date("noc sob./niedz., 28 na 29 listopada", ДЕНЬ), date(2026, 11, 29))
проверка("ночь на стыке лет — год следующий",
         teleman_pl._cell_date("noc czw./pt., 31 grudnia na 1 stycznia", date(2026, 12, 30)), date(2027, 1, 1))
проверка("обычные подписи читаются, как раньше",
         [teleman_pl._cell_date(t, ДЕНЬ) for t in ("poniedziałek, 30 listopada", "dziś, 26 listopada",
                                                    "jutro, 27 listopada", "dziś", "jutro")],
         [date(2026, 11, 30), date(2026, 11, 26), date(2026, 11, 27), date(2026, 11, 26), date(2026, 11, 27)])
проверка("слово без даты и пустая ячейка — None",
         [teleman_pl._cell_date("noc", ДЕНЬ), teleman_pl._cell_date("", ДЕНЬ)], [None, None])

print("2. Лента «Transmisje sportowe» (`parse_sport`) — строки сбора 26.11")


def строка(дата, время, канал, заголовок, описание, вид):
    return (f"<tr><td>{дата}</td><td>{время}</td><td>{канал}</td>"
            f'<td><a class="prog-title" href="/x">{заголовок}</a> <em>{описание}</em>'
            f'<img class="live" title="program na żywo"></td><td>{вид}</td></tr>')


ЛЕНТА = "<table>" + "".join([
    строка("poniedziałek, 30 listopada", "21:10", "Eleven Sports 3", "Piłka nożna: Liga portugalska",
           "mecz: Casa Pia AC - SC Braga", "Piłka nożna"),
    строка("noc pon./wt., 30 listopada na 1 grudnia", "1:30", "Eurosport 3", "Koszykówka mężczyzn: NBA",
           "mecz: Houston Rockets - Los Angeles Lakers", "Koszykówka mężczyzn"),
    строка("noc wt./śr., 1 na 2 grudnia", "2:00", "Eurosport 3", "Koszykówka mężczyzn: NBA",
           "mecz: Chicago Bulls - New York Knicks", "Koszykówka mężczyzn"),
    строка("wtorek, 1 grudnia", "17:55", "Eleven Sports 3", "Piłka nożna: Puchar Niemiec",
           "mecz 1/8 finału: Holstein Kiel - 1. FC Köln", "Piłka nożna"),
]) + "</table>"
ВАРШАВА = ZoneInfo("Europe/Warsaw")
строки = teleman_pl.parse_sport(ЛЕНТА, day=ДЕНЬ, tz="Europe/Warsaw", url="https://www.teleman.pl/sport?page=19")
проверка("все четыре строки прочитаны (ночная внутри месяца больше не теряется)", len(строки), 4)
по_паре = {p.match_raw: p for p in строки}
проверка("Houston — Lakers: 1 декабря 01:30 по Варшаве (02:30 по Киеву), а не 30 ноября",
         по_паре["Houston Rockets - Los Angeles Lakers"].start, datetime(2026, 12, 1, 1, 30, tzinfo=ВАРШАВА))
проверка("Chicago — New York: 2 декабря 02:00 по Варшаве",
         по_паре["Chicago Bulls - New York Knicks"].start, datetime(2026, 12, 2, 2, 0, tzinfo=ВАРШАВА))
проверка("дневные строки — на своих днях",
         [по_паре["Casa Pia AC - SC Braga"].start, по_паре["Holstein Kiel - 1. FC Köln"].start],
         [datetime(2026, 11, 30, 21, 10, tzinfo=ВАРШАВА), datetime(2026, 12, 1, 17, 55, tzinfo=ВАРШАВА)])
проверка("день строки в пометках — тот же, что в начале",
         по_паре["Houston Rockets - Los Angeles Lakers"].extra["day"], "2026-12-01")

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

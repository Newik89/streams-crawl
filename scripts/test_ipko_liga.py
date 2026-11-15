# -*- coding: utf-8 -*-
r"""Книга 133 (15.11.2026): ipko.tv — турнир перед хозяевами после рубрики.

Косовские Sport 1–6 пишут заголовок «Вид: Турнир Хозяева - Гости» без
разделителя между турниром и командой. На сборе 15.11 «Futboll: Raiffeisen
Liga e Pare Prishtina e Re - Liria» ушло на витрину командой «Raiffeisen
Liga e Pare Prishtina e Re» и не сошлось с эталоном. Правила 1–3 — у
`ipko_tv._RUBRIC_LEAGUE`.

Запуск: python scripts/test_ipko_liga.py — в сеть не ходит.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.parsers import ipko_tv  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def пары(*заголовки: str) -> list[str]:
    return [ipko_tv._pair(t) for t in заголовки]


print("Правило 1. Спонсор перед «Liga e …» и «Kupa e …»")
проверка("случай 15.11: «Raiffeisen Liga e Pare Prishtina e Re - Liria» → «Prishtina e Re - Liria»",
         пары("Futboll: Raiffeisen Liga e Pare Prishtina e Re - Liria",
              "Futboll: Digitalb Kupa e Kosoves Drita - Gjilani"),
         ["Prishtina e Re - Liria", "Drita - Gjilani"])

print("Правило 2. Турнир кончается словом лиги, при нём номер или буква дивизиона")
проверка("«La Liga», «Europa League», «Conference League», «UEFA Champions League» перед хозяевами срезаются",
         пары("Futboll: La Liga Valencia - Real Madrid",
              "Futboll: Europa League Crystal Palace - Hoffenheim",
              "Futboll: Conference League Trabzonspor - Freiburg",
              "Futboll: UEFA Champions League Real Madrid - Inter"),
         ["Valencia - Real Madrid", "Crystal Palace - Hoffenheim", "Trabzonspor - Freiburg",
          "Real Madrid - Inter"])
проверка("с номером или буквой дивизиона: «Serie A», «Ligue 1», «2. Bundesliga»",
         пары("Futboll: Serie A Napoli - Roma", "Futboll: Ligue 1 PSG - Lyon",
              "Futboll: 2. Bundesliga Hertha - Schalke"),
         ["Napoli - Roma", "PSG - Lyon", "Hertha - Schalke"])

print("Правило 3. Турнир одним словом")
проверка("«NBA», «Euroleague» перед хозяевами срезаются",
         пары("Basketboll: NBA Dallas - Cleveland", "Basketboll: Euroleague Partizan - Olympiacos"),
         ["Dallas - Cleveland", "Partizan - Olympiacos"])

print("Что НЕ меняется")
проверка("прежние правила (книга 094): «Liga e Kombeve», «ALBI Mall Superliga», «Liga e Kampioneve»",
         пары("Futboll: Liga e Kombeve Norvegji - Uells", "Futboll: ALBI Mall Superliga Drita - Prishtina",
              "Futboll: Liga e Kampioneve Atletico Madrid - Bayern Munich"),
         ["Norvegji - Uells", "Drita - Prishtina", "Atletico Madrid - Bayern Munich"])
проверка("пара без турнира и рубрика без турнира — как были",
         пары("Futboll: Prishtina - Drita", "UFC: Gane - Hokit", "Zenit - Trabzonspor"),
         ["Prishtina - Drita", "Gane - Hokit", "Zenit - Trabzonspor"])
проверка("без рубрики с двоеточием ничего не срезаем: слово «Liga» в начале может быть именем команды",
         пары("Liga Deportiva - Barcelona SC", "La Liga Valencia - Real Madrid"),
         ["Liga Deportiva - Barcelona SC", "La Liga Valencia - Real Madrid"])
проверка("передача без пары парой не становится",
         пары("Futboll: Ligue 1 Highlights Xhiro 10", "Basketboll: NBA Action Episodi 3",
              "Dokumentar: Conor Mc Gregor: Famekeq"), [" ", " ", " "])

print("Весь путь: ответ сайта → строка разбора")
ответ = json.dumps({"shows": [
    {"title": "Futboll: Raiffeisen Liga e Pare Prishtina e Re - Liria", "show_start": 1794747600,
     "genres": ["futbolli"], "categories": "Sport", "summary": ""}]})
строки = ipko_tv.parse(ответ, url="https://stargate.ipko.tv/api/titan.tv.WebEpg/GetWebEpgData?channel_id=sport-1")
проверка("канал Sport 1, пара без турнира, заголовок сайта сохранён как был",
         [(p.channel_raw, p.match_raw, p.title) for p in строки],
         [("Sport 1", "Prishtina e Re - Liria", "Futboll: Raiffeisen Liga e Pare Prishtina e Re - Liria")])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

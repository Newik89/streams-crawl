# -*- coding: utf-8 -*-
r"""Сериал — не матч (книга 087, #8126, слово владельца 27.10.2026). Повод:
Arena Sport 10 «Oni žive za fudbal ep. 252 - Hajduk Čurug, drugi deo»
(31.10 15:30) стал игрой — дефис дал «пару», а эталон правилом «одна
сторона» узнал сербский «Hajduk Čurug» как хорватское «Hajduk» (Хайдук
Сплит — Горица 31.10 16:00).

Что сторожится:

1. слова выпуска и части («ep.», «epizoda», «deo», «dio», «Folge»…) —
   стоп-слова заголовка, на языке своего сайта; «nastavak» (продолжение
   живого матча у sportklub.hr), «základní část», «Серия А» — нет;
2. номер выпуска (`reference._EPISODE_NO`): число от трёх цифр, не год —
   «ep. 252» да; «Como 1907», «Schalke 04», «Hannover 96» — нет;
3. отличающее слово (`canon.odd_word`): «Hajduk Čurug» при «Hajduk Split»,
   «Hajduk» — «CURUG»; своё имя, сокращение эталона, греческое
   «Ολυμπιακός Πειραιώς» — не отличают; иврит не проверяется;
4. `Reference.confirm`: «Hajduk Čurug» с нечитаемым соперником — None;
   «Hajduk» с тем же соперником — «одна сторона», как раньше;
5. `pipeline.run`: строка сериала с tvarenasport.com — снята стоп-словом.

В сеть не ходит, база не нужна:

    python scripts/test_serial_ne_match.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.gettempdir()) / "serial-none.db"))

from app import canon, live, pipeline, site_lang, sport  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import _EPISODE_NO, Reference  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
ВСЕ = live.load()
зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✗ {имя}: вышло {вышло!r}, ждали {ждём!r}")


def стоп(домен: str, заголовок: str) -> str:
    markers = ВСЕ.for_langs(site_lang.of(домен))
    return markers.found(markers.stop_title, заголовок)


print("1. Слова выпуска и части — стоп-слова на языке сайта")
сериал = "Oni žive za fudbal ep. 252 - Hajduk Čurug, drugi deo"
проверка("«ep.» — у tvarenasport.com", bool(стоп("tvarenasport.com", сериал)), True)
проверка("«drugi deo» без «ep.» — тоже", bool(стоп("tvarenasport.com", "Oni žive za fudbal - Hajduk Čurug, drugi deo")), True)
проверка("«drugi dio» — у хорватского сайта", bool(стоп("sportklub.hr", "Hajduk TV - drugi dio")), True)
проверка("«dio 2» — тоже", bool(стоп("sportklub.hr", "Hajduk TV, dio 2")), True)
проверка("«Glavni dio» в названии турнира — НЕ стоп-слово (голое «dio» не берём)",
         стоп("sportklub.hr", "Nogomet - Premier League - Prva faza - Glavni dio: Hibernians - Hamrun"), "")
проверка("«Folge» — у немецкоязычного tv.orf.at",
         bool(стоп("tv.orf.at", "On the Edge - World Cup Ski Racing Folge 4")), True)
проверка("«Folge» на хорватском сайте не ищется", стоп("sportklub.hr", "Folge 4"), "")
проверка("«ep.» — общее, и у португальского сайта",
         bool(стоп("sporttv.pt", "Objetivo Los Ángeles Ep. 1")), True)
проверка("«nastavak» — продолжение живого матча, НЕ стоп-слово",
         стоп("sportklub.hr", "WTA 250 Osaka (NASTAVAK): Boulter - Sakatsume"), "")
проверка("«základní část» — сезон, НЕ стоп-слово",
         стоп("oneplay.cz", "WNBA - základní část, Minnesota Lynx - Indiana Fever"), "")
проверка("«Серия А» — НЕ стоп-слово", стоп("maxsport.live", "Серия А: Милан - Интер"), "")
проверка("«Copa del Rey» — испанское «del» не задето",
         стоп("movistarplus.es", "Copa del Rey Mapfre (T26/27): Sestao - Espanyol"), "")

print("2. Номер выпуска — не команда")
for имя, ждём in (("Oni žive za fudbal ep. 252", True), ("Como 1907", False),
                  ("Schalke 04", False), ("Hannover 96", False), ("1860 München", False),
                  ("Real Madrid", False)):
    проверка(f"«{имя}»", bool(_EPISODE_NO.search(имя)), ждём)

print("3. Отличающее слово команды сайта")
ХАЙДУК = ["Hajduk Split", "Hajduk", "Χάιντουκ Σπλιτ", "Хайдук Сплит", "Хайдук"]
проверка("«Hajduk Čurug» при Хайдук Сплит — CURUG", canon.odd_word("Hajduk Čurug", ХАЙДУК), "CURUG")
проверка("«Hajduk Split» — своё имя", canon.odd_word("Hajduk Split", ХАЙДУК), "")
проверка("«Хайдук Сплит» кириллицей — своё имя", canon.odd_word("Хайдук Сплит", ХАЙДУК), "")
проверка("«Atletico Madrid» при «Atl. Madrid» — сокращение эталона",
         canon.odd_word("Atletico Madrid", ["Atl. Madrid", "Ατλέτικο Μαδρίτης"]), "")
проверка("«Ολυμπιακός Πειραιώς» при «Olympiacos Piraeus» — то же слово",
         canon.odd_word("Ολυμπιακός Πειραιώς", ["Olympiacos Piraeus", "Ολυμπιακός"]), "")
проверка("«Dinamo Minsk» при «Dinamo Moscow» — MINSK",
         canon.odd_word("Dinamo Minsk", ["Dinamo Moscow", "Динамо Москва"]), "MINSK")
проверка("иврит не проверяется", canon.odd_word("הפועל באר שבע", ["H. Beer Sheva"]), "")
# проверка GitHub 27.10 (сбор #352) поймала три настоящих матча:
проверка("рубрика перед именем: «BKT EuroCup … Bahçeşehir Koleji» при «Bahcesehir Kol.»",
         canon.odd_word("BKT EUROCUP BASKETBOL KARŞILAŞMASI BAHÇEŞEHİR KOLEJİ",
                        ["Bahcesehir Kol.", "Bahçeşehir Kol."]), "")
проверка("спонсор перед именем: «Albi Mall Superliga Llapi» при «KF Llapi»",
         canon.odd_word("Albi Mall Superliga Llapi", ["KF Llapi", "Λάπι"]), "")
проверка("город после имени, у эталона уточнения нет: «PAOK Thessaloni» при «PAOK»",
         canon.odd_word("PAOK THESSALONI", ["PAOK", "ΠΑΟΚ"]), "")
проверка("«Inter Milan» при «Inter» — тоже уточнение", canon.odd_word("Inter Milan", ["Inter"]), "")
проверка("«Μάντσεστερ Γιουνάιτεντ» при «Manchester Basketball» — другой клуб (cosmote 01.11)",
         bool(canon.odd_word("Μάντσεστερ Γιουνάιτεντ", ["Manchester Basketball"])), True)
проверка("твёрдая сторона — хозяева",
         canon.firm_side({"home": "Hajduk Čurug", "away": "Oni zive"},
                         {"home": "Hajduk Split", "away": "Gorica",
                          "names": {"hr": ["Hajduk", "Gorica"]}})[0], "Hajduk Čurug")

print("4. Эталон: правило «одна сторона»")
эталон = Reference([{"sport": "F", "home": "Hajduk Split", "away": "Gorica",
                     "league": "CROATIA: HNL", "fs_id": "hajdgori",
                     "start_kyiv": "2026-10-31T16:00",
                     "names": {"hr": ["Hajduk", "Gorica"], "el": ["Χάιντουκ Σπλιτ", "Γκόριτσα"]}}])
когда = datetime(2026, 10, 31, 15, 30, tzinfo=KYIV)
# «Gorizia» — соперник, который буквами «не спорит» с Gorica, но целой пары
# не даёт: ровно случай правила 4 (на старом коде оба — «одна сторона»)
ответ = эталон.confirm("Hajduk Čurug", "Gorizia", когда)
проверка("«Hajduk Čurug» — «Gorizia»: другой клуб, не матч эталона", ответ, None)
ответ = эталон.confirm("Hajduk", "Gorizia", когда)
проверка("«Hajduk» — «Gorizia»: «одна сторона», как раньше",
         ответ and ответ.how, "одна сторона")
ответ = эталон.confirm("Hajduk", "Oni zive za fudbal ep. 252", когда)
проверка("сторона с номером выпуска — не матч эталона", ответ, None)

print("5. pipeline.run: строка сериала с tvarenasport.com")
p = Program(channel_raw="Arena Sport 10", title=сериал,
            start=datetime(2026, 10, 31, 15, 30, tzinfo=KYIV))
row = pipeline.run([p], ВСЕ, sport.load(teams=()), {}, {}, эталон, domain="tvarenasport.com")[0]
проверка("снята стоп-словом", (row.ok, row.reason.startswith("стоп-слово")), (False, True))

print(f"\nзелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

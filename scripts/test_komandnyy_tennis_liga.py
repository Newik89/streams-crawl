# -*- coding: utf-8 -*-
r"""Книга 159 (16.11.2026): лига командного теннисного турнира на языке сайта.

У двух теннисных встреч sport5.co.il лига «גביע בילי ג'ין» (Кубок Билли Джин
Кинг) ушла на витрину транслитом «Cup Bili G'in». Как устроено: лигу на
витрине называет (по порядку) канон игры из эталона, алиас словаря лиг
(серверная база, её выгрузка — `data/dictionaries.json`, руками не правится),
а если их нет — автоперевод `app/league_words.py` по `data/league_words.json`:
фразы, слова, остальное транслитом. Встречи сборных эталон в те дни не
подтвердил, алиаса у ивритского названия не было — сработал транслит.

Общий механизм — фразы автоперевода (данные, не код): название командного
теннисного турнира на языках сайтов → имя, каким его зовёт эталон flashscore
(«TEAMS - WOMEN: Billie Jean King Cup», «TEAMS - MEN: Davis Cup»; United Cup,
Laver Cup, Hopman Cup — английское название). Правила автоперевода прежние.
В сеть не ходит. Запуск: python scripts/test_komandnyy_tennis_liga.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import league_words, leagues  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def витрина(сырая_лига: str) -> str:
    """Как лигу без алиаса и без эталона покажет витрина: чистка + автоперевод."""
    return league_words.auto_english(leagues.clean(сырая_лига))


BJK, DAVIS = "TEAMS - WOMEN: Billie Jean King Cup", "TEAMS - MEN: Davis Cup"

print("Кубок Билли Джин Кинг — написания сайтов сборов 15–16.11 и стандартные")
проверка("иврит (sport5.co.il): «גביע בילי ג'ין» — уже не «Cup Bili G'in»",
         [витрина(x) for x in ("גביע בילי ג'ין", "גביע בילי ג'ין קינג")], [BJK, BJK])
проверка("португальский, польский, французский, нидерландский, немецкий — как на сайтах сбора",
         [витрина(x) for x in ("BILLIE JEAN KING CUP - TÉNIS", "Tenis: Puchar Billie Jean King", "Coupe Billie Jean King 2026",
                               "The Billie Jean King Cup", "Billie Jean King Cup")], [BJK] * 5)
проверка("русский, украинский, болгарский, сербский, греческий, испанский, итальянский, венгерский, турецкий, румынский",
         [витрина(x) for x in ("Кубок Билли Джин Кинг", "Кубок Біллі Джин Кінг", "Купа Били Джийн Кинг", "Куп Били Џин Кинг",
                               "Μπίλι Τζιν Κινγκ Καπ", "Copa Billie Jean King", "Coppa Billie Jean King",
                               "Billie Jean King Kupa", "Billie Jean King Kupası", "Cupa Billie Jean King")], [BJK] * 10)

print("Кубок Дэвиса")
проверка("написания сайтов сбора и словаря лиг: португальский, польский, иврит, испанский, болгарский, венгерский, казахский",
         [витрина(x) for x in ("TAÇA DAVIS - TÉNIS", "Tenis: Puchar Davisa", "גביע דיוויס", "Copa Davis", "Купа Дейвис",
                               "Davis Kupa", "Дэвис кубогы")], [DAVIS] * 7)
проверка("русский, украинский, греческий, чешский, словацкий, хорватский, турецкий, французский, итальянский, немецкий",
         [витрина(x) for x in ("Кубок Дэвиса", "Кубок Девіса", "Ντέιβις Καπ", "Davisův pohár", "Davisov pohár", "Davis Kup",
                               "Davis Kupası", "Coupe Davis", "Coppa Davis", "Davis Cup")], [DAVIS] * 10)

print("United Cup, Laver Cup, Hopman Cup")
проверка("латиницей — как есть; кириллицей, греческим, ивритом — английское название, не транслит",
         [витрина(x) for x in ("United Cup", "Юнайтед Кап", "Γιουνάιτεντ Καπ", "יונייטד קאפ", "Laver Cup", "Кубок Лейвера",
                               "Купа Лейвър", "גביע לייבר", "Hopman Cup", "Кубок Хопмана", "גביע הופמן")],
         ["United Cup"] * 4 + ["Laver Cup"] * 4 + ["Hopman Cup"] * 3)

print("Прежние правила автоперевода целы")
проверка("слова и фразы: «Кубок Германии» → Germany Cup, «плей-офф» → Playoff; латиница без совпадений — как есть; "
         "стадия после названия переводится словом",
         [league_words.auto_english(x) for x in ("Кубок Германии", "НБА. Плей-офф", "Liga BPI", "Premier League",
                                                 "Кубок Дэвиса. Финал")],
         ["Germany Cup", league_words.auto_english("НБА. Плей-офф"), "Liga BPI", "Premier League", DAVIS + ". Final"])
слова = json.loads((ROOT / "data" / "league_words.json").read_text(encoding="utf-8"))
ключи = list(слова["фразы"]) + list(слова["слова"])
проверка("в словаре автоперевода нет повторов ключей; ключи — строчными, без лишних пробелов",
         (len(ключи) == len(set(ключи)), [k for k in ключи if k != " ".join(k.lower().split())]), (True, []))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

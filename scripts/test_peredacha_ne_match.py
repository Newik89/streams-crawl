# -*- coding: utf-8 -*-
r"""Книга 158 (16.11.2026): передача прошла как матч; сторона пары — слово тура.

Находка: передачи на иврите «ערב הכדורסל של ישראל — מחזור 6» («Вечер
израильского баскетбола — тур 6») и «ארץ הכדורגל — ליגה לאומית» («Страна
футбола — Национальная лига») стояли на витрине матчами. Замер на сборе #491:
  * обе передачи уже снимаются стоп-словами «ערב הכדורסל» и «ארץ הכדורגל»
    (раздел `stop_title`, книга 108, 13.11) — нового правила им не нужно;
    здесь они закреплены проверкой;
  * общий признак «сторона пары — слово тура» работает на всех языках сайтов
    и без стоп-слова (`pipeline.tidy_sides`, правило М3 книги 157);
  * по классу найдены три настоящие передачи, которые на сборе шли матчами:
    port.hu «Premier League - Előzetes: 11. forduló» (анонс тура) и
    novasports.gr с рубрикой «Pre Game Show» / «Post Game Show» при заголовке
    «Άρης - Λε Μαν» — им добавлены слова в `data/markers.json` (`stop_title`,
    `stop_genre`) с языком в `data/word_langs.json`.
В сеть не ходит. Запуск: python scripts/test_peredacha_ne_match.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import live, pipeline, site_lang, sport  # noqa: E402
from app.parsers import Program  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


M, виды = live.load(), sport.load()


def строка(сайт, title, match_raw, live_raw, league_raw="", sport_raw=""):
    p = Program(channel_raw="Канал 1", title=title, start=datetime(2026, 11, 17, 19, 45, tzinfo=KYIV),
                live_raw=live_raw, match_raw=match_raw, league_raw=league_raw, sport_raw=sport_raw)
    return pipeline.run([p], M, виды, {}, {}, None, domain=сайт)[0]


print("Передачи на иврите (sport5.co.il) — сняты стоп-словом, как и до правки")
row = строка("sport5.co.il", "ליגת העל בכדורסל: ערב הכדורסל של ישראל - מחזור 6", "ערב הכדורסל של ישראל - מחזור 6", "ישיר",
             league_raw="ליגת העל בכדורסל")
проверка("«ערב הכדורסל של ישראל - מחזור 6» — не игра, причина — стоп-слово передачи",
         (row.ok, row.reason), (False, "стоп-слово в заголовке: ערב הכדורסל"))
row = строка("sport5.co.il", "ארץ הכדורגל - ליגה לאומית", "ארץ הכדורגל - ליגה לאומית", "ישיר")
проверка("«ארץ הכדורגל - ליגה לאומית» — не игра, причина — стоп-слово передачи",
         (row.ok, row.reason), (False, "стоп-слово в заголовке: ארץ הכדורגל"))
проверка("настоящий матч той же лиги на том же сайте остаётся игрой",
         (lambda r: (r.ok, r.home, r.away))(строка("sport5.co.il", "ליגת העל בכדורסל: מכבי תל אביב - הפועל ירושלים",
                                                   "מכבי תל אביב - הפועל ירושלים", "ישיר", league_raw="ליגת העל בכדורסל")),
         (True, "מכבי תל אביב", "הפועל ירושלים"))

print("Общий признак: сторона пары — слово тура (на всех языках сайтов, без стоп-слова)")
ТУРЫ = (("ערב הכדורסל של ישראל", "מחזור 6"), ("Coupe de France", "Journée 5"), ("Coupe de France", "3e journée"),
        ("Bundesliga", "12. Spieltag"), ("Bundesliga", "Spieltag 12"), ("Chance Liga", "3. kolo"),
        ("LaLiga", "Jornada 8"), ("Serie A", "7a giornata"), ("Премьер-лига", "15 тур"), ("Премьер-лига", "Тур 15"),
        ("Super League", "11η Αγωνιστική"), ("Ekstraklasa", "Kolejka 9"), ("Eliteserien", "Runde 3"),
        ("NB I", "11. forduló"), ("Süper Lig", "5. Hafta"), ("Eredivisie", "Speelronde 4"), ("Veikkausliiga", "Kierros 3"),
        ("Allsvenskan", "Omgång 7"), ("Първа лига", "5 кръг"), ("Brasileirão", "Rodada 30"), ("Premier League", "Matchday 11"))
проверка(f"{len(ТУРЫ)} записей «турнир — тур N» на 19 языках — не пара",
         [pipeline.tidy_sides(*x, M) for x in ТУРЫ], [None] * len(ТУРЫ))
КОМАНДЫ = (("מכבי תל אביב", "הפועל ירושלים"), ("Paris SG", "Lyon"), ("1. FC Köln", "Bayer 04"), ("Sparta", "Slavia"),
           ("Real Madrid", "Atlético"), ("ЦСКА", "Спартак"), ("ΠΑΟΚ", "Άρης"), ("Legia", "Lech"), ("Galatasaray", "Tur Abdin"),
           ("Kolos", "Kolo Kolo"), ("Round Rock", "Austin"), ("Rundē", "Liepāja"))
проверка("настоящие пары не тронуты — и те, где слово тура стоит частью имени («Kolo Kolo», «Tur Abdin», «Round Rock»)",
         [pipeline.tidy_sides(*x, M) for x in КОМАНДЫ], list(КОМАНДЫ))
row = строка("programme-tv.net", "Football : Coupe de France - 3e journée", "Coupe de France - 3e journée", "en direct",
             sport_raw="Football")
проверка("строка «турнир — тур» у футбола — не игра: пары не видно", (row.ok, row.reason), (False, pipeline.NO_PAIR))

print("Слова передач, найденных по классу на сборе #491 (`data/markers.json`)")
row = строка("port.hu", "Labdarúgás: Premier League - Előzetes: 11. forduló", "Premier League - Előzetes: 11. forduló", "élő",
             league_raw="Labdarúgás: Premier League - Előzetes")
проверка("port.hu: анонс тура «Előzetes» — стоп-слово венгерского сайта", (row.ok, row.reason),
         (False, "стоп-слово в заголовке: Előzetes"))
row = строка("novasports.gr", "Άρης - Λε Μαν", "Άρης - Λε Μαν", "ζωντανά", league_raw="Pre Game Show")
проверка("novasports.gr: рубрика «Pre Game Show» — передача до матча, не матч", (row.ok, row.reason),
         (False, "стоп-жанр в рубрике: Pre Game Show"))
row = строка("novasports.gr", "Άρης - Λε Μαν", "Άρης - Λε Μαν", "ζωντανά", league_raw="Post Game Show")
проверка("novasports.gr: рубрика «Post Game Show» — передача после матча, не матч", (row.ok, row.reason),
         (False, "стоп-жанр в рубрике: Post Game Show"))
row = строка("novasports.gr", "Άρης - Λε Μαν", "Άρης - Λε Μαν", "ζωντανά", league_raw="Basket League")
проверка("тот же заголовок с лигой в рубрике — игра", (row.ok, row.home, row.away), (True, "Άρης", "Λε Μαν"))
проверка("у каждого нового слова есть язык: «előzetes» — венгерский, слова «… game show» — общие",
         (site_lang.word_langs("előzetes"), site_lang.allowed("előzetes", site_lang.of("sportklub.hr")),
          site_lang.allowed("pre game show", site_lang.of("novasports.gr"))), (frozenset({"hu"}), False, True))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

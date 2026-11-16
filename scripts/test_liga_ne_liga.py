# -*- coding: utf-8 -*-
r"""Книга 156 (16.11.2026): в поле лиги — не лига.

На витрине на месте лиги стояли «Тур 15 Прямая трансляция» (ntvplus.tv: хвост
заголовка вместо названия), слово стадии («alapszakasz», «Τελικός»), сама пара
игры (dagenstv.com, mediaklikk.hu), лига с парой и пометкой эфира (vsetv.com,
sports.kz). Правила Л1–Л6 — `app/leagues.py`, над `_stage_air`:
  Л1. пометка эфира на краю названия срезается (`_air_off`);
  Л2. стадия в скобках в конце — не название (`_stage_tail_off`);
  Л3. остались одни слова стадии, тура и числа — лиги нет (`stage_only`);
  Л4. в названии сама пара строки — срезается с начала пары (`without_pair`);
  Л5. поле заполнено, а лиги в нём нет — лига из рубрик заголовка (`from_title`);
  Л6. ничего не нашлось — лига пустая.
Всё решение — `leagues.settle`, зовёт `pipeline.classify`.
В сеть не ходит. Запуск: python scripts/test_liga_ne_liga.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import leagues, live, pipeline, sport  # noqa: E402
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


print("Л1. Пометка эфира на краю названия — не название")
проверка("в конце — русская, сербская, английская, шведская, греческая, венгерская",
         [leagues.clean(x) for x in ("Кубок Португалии Прямая трансляция", "ABA,  direktno", "NFL Live",
                                     "V85 Direkt", "Super League ζωντανά", "OTP Bank Liga élő")],
         ["Кубок Португалии", "ABA", "NFL", "V85", "Super League", "OTP Bank Liga"])
проверка("в начале — срезается само слово",
         [leagues.clean(x) for x in ("Live UEFA Nations League", "LIVE Fußball ADMIRAL 2. Liga", "Live: Nations Championship")],
         ["UEFA Nations League", "Fußball ADMIRAL 2. Liga", "Nations Championship"])
проверка("в середине и внутри слова не трогаем",
         [leagues.clean(x) for x in ("MOTD Live: Women's Super League", "Triathlon: Mens Finals (Re-Live)", "Liverpool Cup")],
         ["MOTD Live: Women's Super League", "Triathlon: Mens Finals (Re-Live)", "Liverpool Cup"])

print("Л2. Стадия в скобках в конце — не название")
проверка("«(Finale)», «(Halbfinale, Hinspiel)», «(kvalifikace)» снимаются; возраст и город в скобках остаются",
         [leagues.clean(x) for x in ("CONMEBOL Sudamericana (Finale)", "CONMEBOL Libertadores (Halbfinale, Hinspiel)",
                                     "Liga Profesional Clausura (Achtelfinale)", "Liga (U21)", "ATP Finale (Torino)")],
         ["CONMEBOL Sudamericana", "CONMEBOL Libertadores", "Liga Profesional Clausura", "Liga (U21)", "ATP Finale (Torino)"])

print("Л3. Одни слова стадии, тура, пометки эфира и числа — лиги нет")
проверка("венгерский, русский, греческий, хорватский, английский, немецкий, иврит, румынский",
         [leagues.clean(x) for x in ("alapszakasz", "Тур 15 Прямая трансляция", "Тур 12", "8-й тур", "1/64 финала",
                                     "Τελικός", "11η Αγωνιστική", "(parovi) FINALE", "parovi", "Regular Season",
                                     "Round of 16", "Play-offs", "Matchday 5", "Game 7", "Halbfinale", "מחזור 6",
                                     "חצי גמר", "tenis Tenis Ziua 6", "tenis Tenis Finala dublu", "Прямая трансляция",
                                     "LIVE", "csoportkör mérkőzés")],
         [""] * 22)
проверка("слово стадии внутри настоящего названия ничего не меняет",
         [leagues.clean(x) for x in ("NBA Playoffs", "Copa del Rey Final", "Final Four", "NBA Finals", "ATP FINALS",
                                     "EFL Trophy - Southern Group D", "kvalifikacije za EP", "Тур де Франс",
                                     "ליגה לאומית", "Friendly", "Division 1")],
         ["NBA Playoffs", "Copa del Rey Final", "Final Four", "NBA Finals", "ATP FINALS",
          "EFL Trophy - Southern Group D", "kvalifikacije za EP", "Тур де Франс", "ליגה לאומית", "Friendly",
          "Division 1"])
проверка("настоящие лиги с номером и коротким именем целы",
         [leagues.clean(x) for x in ("1. Division", "2. Bundesliga", "Liga 3", "Liga F", "ABA 2", "Serie A",
                                     "Premier League", "Ligue 1 Journée 5")],
         ["1. Division", "2. Bundesliga", "Liga 3", "Liga F", "ABA 2", "Serie A", "Premier League", "Ligue 1"])
проверка("`stage_only`: пустое и число — не стадия; название — не стадия",
         [leagues.stage_only(x) for x in ("", "2026", "Finale", "Serie A", "1/8 финала")],
         [False, False, True, False, True])

print("Л4. В названии лиги стоит сама пара строки")
проверка("лига — одна пара: пусто; лига и пара — остаётся лига; страна в скобках и кавычки не мешают",
         [leagues.without_pair(*x) for x in (
             ("Philadelphia 76ers – Boston Celtics", "Philadelphia 76ers", "Boston Celtics"),
             ("УЕФА Ұлттар Лигасы Германия — Нидерланд", "Германия", "Нидерланд"),
             ("Лига чемпионов. Женщины. Арсенал (Великобритания) - Лион (Франция)", "Арсенал", "Лион"),
             ("CONMEBOL Sudamericana (Finale): Atletico Mineiro (BRA) - Boca Juniors (ARG) (scooore FAST)",
              "Atletico Mineiro", "Boca Juniors"),
             ("Magyarország - Dánia csoportkör mérkőzés", "Magyarország W", "Dánia W"))],
         ["", "УЕФА Ұлттар Лигасы", "Лига чемпионов. Женщины", "CONMEBOL Sudamericana (Finale)", ""])
проверка("стороны переставлены эталоном — пара всё равно находится; пара после названия с тем же словом — режется она",
         [leagues.without_pair(*x) for x in (("Liga: Porto - Benfica", "Benfica", "Porto"),
                                             ("Serbia Cup: Serbia - Montenegro", "Serbia", "Montenegro"))],
         ["Liga", "Serbia Cup"])
проверка("пары в названии нет — оно не тронуто: одна сторона, стороны не рядом, сторона внутри слова",
         [leagues.without_pair(*x) for x in (("Copa Argentina", "Argentina", "Chile"),
                                             ("Roma Cup of Romania and Lazio", "Roma", "Lazio"),
                                             ("Romania Liga 1", "Roma", "Liga"),
                                             ("Real Madrid TV", "Real", "Madrid"))],
         ["Copa Argentina", "Roma Cup of Romania and Lazio", "Romania Liga 1", "Real Madrid TV"])

print("Л5. Лига из рубрик заголовка — общий читатель")
проверка("рубрика до пары: первая, которая осталась названием (вид спорта, тур, стадия, пометка эфира пропускаются)",
         [leagues.from_title(*x) for x in (
             ("Альфа-Банк Российская Премьер-Лига. Тур 15. Прямая трансляция. \"Ростов\" - \"Крылья Советов\"",
              "Ростов", "Крылья Советов"),
             ("Футбол. Чемпионат Австрии. Прямая трансляция. ЛАСК - Хартберг", "ЛАСК", "Хартберг"),
             ("Copa Sudamericana | Τελικός| Ατλ. Μινέϊρο – Μπόκα Τζ.", "Ατλ. Μινέϊρο", "Μπόκα Τζ"),
             ("WTA Finals (Indian Wells): (parovi) FINALE: Siniakova/Townsend - Errani/Paolini",
              "Siniakova/Townsend", "Errani/Paolini"),
             ("Fotbal: 3. kolo: Liga prvaka: Dinamo - Hajduk", "Dinamo", "Hajduk"))],
         ["Альфа-Банк Российская Премьер-Лига", "Чемпионат Австрии", "Copa Sudamericana", "WTA Finals (Indian Wells)",
          "Liga prvaka"])
проверка("пары в заголовке нет — рубрики всего заголовка; одна рубрика-вид спорта — пусто; точка после цифры — не граница",
         [leagues.from_title(*x) for x in (
             ("OTP Bank Liga, műsor, élő adásban", "Ferencvárosi TC", "ETO FC"),
             ("Basket : Philadelphia 76ers – Boston Celtics", "Philadelphia 76ers", "Boston Celtics"),
             ("LIVE Fußball ADMIRAL 2. Liga 13. Runde: Austria Salzburg - Admira Wacker", "Austria Salzburg", "Admira Wacker"))],
         ["OTP Bank Liga", "", "Fußball ADMIRAL 2. Liga"])
проверка("`before_air` — только рубрики до первой пометки эфира",
         [leagues.from_title(x, "Катар", "Панама", before_air=True) for x in (
             "Чемпионат мира среди юношей (U-17). Прямая трансляция из Катара. Катар - Панама",
             "Прямая трансляция из Катара. Катар - Панама")],
         ["Чемпионат мира среди юношей (U-17)", ""])

print("Л1–Л6 вместе (`leagues.settle`)")
СЛУЧАИ = (
    # (поле лиги, заголовок, хозяева, гости) → лига
    (("Тур 15 Прямая трансляция", "Альфа-Банк Российская Премьер-Лига. Тур 15. Прямая трансляция. \"Ростов\" - \"Крылья Советов\"",
      "Ростов", "Крылья Советов"), "Альфа-Банк Российская Премьер-Лига"),
    (("Прямая трансляция", "Чемпионат Бразилии. Прямая трансляция. \"Крузейро\" - \"Палмейрас\"", "Крузейро", "Палмейрас"),
     "Чемпионат Бразилии"),
    (("Прямая трансляция из Катара", "Чемпионат мира среди юношей (U-17). Прямая трансляция из Катара. Катар - Панама",
      "Катар U17", "Панама U17"), "Чемпионат мира среди юношей (U-17)"),
    (("Чемпионат Австрии Прямая трансляция", "Футбол. Чемпионат Австрии. Прямая трансляция. ЛАСК - Хартберг", "ЛАСК", "Хартберг"),
     "Чемпионат Австрии"),
    (("Ferencvárosi TC - ETO FC mérkőzés", "OTP Bank Liga, műsor, élő adásban", "Ferencvárosi TC", "ETO FC"), "OTP Bank Liga"),
    (("Philadelphia 76ers – Boston Celtics", "Basket : Philadelphia 76ers – Boston Celtics", "Philadelphia 76ers", "Boston Celtics"), ""),
    (("Τελικός", "Copa Sudamericana | Τελικός| Ατλ. Μινέϊρο – Μπόκα Τζ.", "Ατλ. Μινέϊρο", "Μπόκα Τζ"), "Copa Sudamericana"),
    (("alapszakasz", "Phoenix Suns - Los Angeles Lakers", "Phoenix Suns", "Los Angeles Lakers"), ""),
    (("Los Angeles Lakers – Charlotte Hornets – Los Angeles Lakers – Charlotte Hornets",
      "Basket : Los Angeles Lakers – Charlotte Hornets – Los Angeles Lakers – Charlotte Hornets",
      "Los Angeles Lakers", "Charlotte Hornets"), ""),                                  # пара в поле лиги повторена
    (("Live UEFA Nations League", "Live UEFA Nations League", "Republic of Ireland", "Kosovo"), "UEFA Nations League"),
    (("ABA,  direktno", "Košarka: SC Derby - Viena, ABA, direktno", "SC Derby", "Viena"), "ABA"),
    (("УЕФА Ұлттар Лигасы Испания — Англия", "Футбол. УЕФА Ұлттар Лигасы. Испания — Англия. Прямая трансляция", "Испания", "Англия"),
     "УЕФА Ұлттар Лигасы"),
    (("Лига чемпионов. Женщины. Арсенал (Великобритания) - Лион (Франция). Прямая трансляция",
      "Футбол. Лига чемпионов. Женщины. Арсенал (Великобритания) - Лион (Франция). Прямая трансляция", "Арсенал W", "Лион W"),
     "Лига чемпионов. Женщины"),
    # прежнее поведение цело
    (("UEFA Nations League", "UEFA Nations League: Spania - England", "Spania", "England"), "UEFA Nations League"),
    (("Piłka nożna: Liga angielska", "Piłka nożna: Liga angielska", "Arsenal", "Chelsea"), "Liga angielska"),
    (("futbolli", "Liga e Pare: Prishtina - Drita", "Prishtina", "Drita"), ""),        # Л6: один вид спорта — заголовок не читаем
    (("", "Bundesliga: Bayern - Köln", "Bayern", "Köln"), ""),                          # поля лиги нет — заголовок не читаем
)
проверка("тринадцать случаев сбора 16.11 и четыре прежних",
         [leagues.settle(*args) for args, _ in СЛУЧАИ], [ждём for _, ждём in СЛУЧАИ])

print("Разбор строки (`pipeline.classify`)")
M, виды = live.load(), sport.load()
p = Program(channel_raw="Матч! Премьер", start=datetime(2026, 11, 22, 16, 0, tzinfo=KYIV),
            title="Альфа-Банк Российская Премьер-Лига. Тур 15. Прямая трансляция. \"Ростов\" - \"Крылья Советов\"",
            live_raw="Прямая трансляция", league_raw="Тур 15 Прямая трансляция", sport_raw="Футбол",
            match_raw="\"Ростов\" - \"Крылья Советов\"")
row = pipeline.classify(p, M, виды)
проверка("строка ntvplus.tv: пара цела, лига — первая рубрика заголовка, а не хвост",
         (row.ok, row.home, row.away, row.league), (True, "Ростов", "Крылья Советов", "Альфа-Банк Российская Премьер-Лига"))
p = Program(channel_raw="M4 Sport", start=datetime(2026, 11, 22, 18, 0, tzinfo=KYIV),
            title="Női kosárlabda Európa-bajnoki selejtező, műsor, élő adásban", live_raw="élő",
            league_raw="Magyarország - Ciprus", match_raw="Magyarország - Ciprus", sport_raw="kosárlabda")
row = pipeline.classify(p, M, виды)
проверка("строка mediaklikk.hu: в поле лиги пара — лига из заголовка, пол турнира дописан к сторонам",
         (row.ok, row.home, row.away, row.league),
         (True, "Magyarország W", "Ciprus W", "Női kosárlabda Európa-bajnoki selejtező"))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

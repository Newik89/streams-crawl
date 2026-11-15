# -*- coding: utf-8 -*-
r"""Книга 144 (15.11.2026): три игры из аудита 12.11 — три общих правила.

  #10444 «Superbet League 2 | 11η Αγωνιστική | Τρίπολη» (ert.gr): к названию
         лиги прилип тур и город → `leagues._tail_off`, правила 1–3;
  #10267 «Baylor — Texas» (эталон «Texas — Baylor»): метка эталона снималась и
         ставилась заново при каждой заливке — сайт пишет пару наоборот →
         `canon.flag_disputed`;
  #10202 мужская BBL с буквой W (sport5): слово «женский» из примечания «начнётся
         после женского баскетбола» стало пометкой пола → `leagues.without_notes`.

Замеры по всем сайтам сбора 15.11: хвост у лиги — 12 игр из 482; пол только из
описания — 36 строк из 13 317, почти все честные (женский турнир назван в
описании), поэтому описание читается по-прежнему, не читается только хвост
после слова «после» на языке сайта.
В сеть не ходит, базу не открывает. Запуск: python scripts/test_tri_igry_audita.py
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import canon, leagues, site_lang  # noqa: E402
import canon_backfill  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


print("Хвост у названия лиги: тур, стадия, место (`leagues.clean` → `_tail_off`), правила 1–3")
проверка("правило 1: части через «|» — лига первая, дальше хвост (ert.gr)",
         [leagues.clean(x) for x in ("Superbet League 2 | 11η Αγωνιστική | Τρίπολη", "Elite League | 8η Αγωνιστική",
                                     "Παγκόσμιο Κύπελλο Κ17 | Κατάρ")],
         ["Superbet League 2", "Elite League", "Παγκόσμιο Κύπελλο Κ17"])
проверка("правило 1: передняя часть, где только вид спорта, пропускается",
         leagues.clean("Ποδόσφαιρο | Superbet League 2 | 11η Αγωνιστική"), "Superbet League 2")
проверка("правило 2: тур с числом и всё после него — хвост: итальянский, немецкий, чешский, португальский, "
         "русский, иврит",
         [leagues.clean(x) for x in (
             "Serie A Women Athora - 7a giornata", "Women's Super League (10. Spieltag): Aston Villa - Birmingham City",
             "UEFA Frauen Champions League Spieltag 5: Austria Wien - Bayern München", "MOL Cup 3. kolo",
             "Liga Portugal 2 - Jornada 12", "Премьер-лига. 15 тур", "ליגת העל מחזור 6")],
         ["Serie A Women Athora", "Women's Super League", "UEFA Frauen Champions League", "MOL Cup",
          "Liga Portugal 2", "Премьер-лига", "ליגת העל"])
проверка("правило 2: тур в начале не трогаем — резать было бы нечего оставить",
         leagues.clean("etapa 6 Nations League: Spania-Anglia Grupe"), "etapa 6 Nations League: Spania-Anglia Grupe")
проверка("слово тура без числа и число в самом названии лиги — не хвост",
         [leagues.clean(x) for x in ("Round Robin", "Round of 16", "Тур де Франс", "2. Bundesliga", "1. HNL",
                                     "Liga Portugal 2", "ATP 500 Tokyo", "Serie A")],
         ["Round Robin", "Round of 16", "Тур де Франс", "2. Bundesliga", "1. HNL", "Liga Portugal 2",
          "ATP 500 Tokyo", "Serie A"])
проверка("правило 3: от названия ничего не осталось — как было; прежняя чистка цела",
         [leagues.clean(x) for x in ("| 11η Αγωνιστική", "Scottish Premiership (15. Spieltag)",
                                     "Piłka nożna: Liga angielska", "LaLiga EA Sports (T26/27)")],
         ["11η Αγωνιστική", "Scottish Premiership", "Liga angielska", "LaLiga EA Sports"])
проверка("пол и возраст читаются по сырой строке, до снятия хвоста",
         (leagues.category("Προκριματικά Eurobasket Γυναικών 2027 | Β’ Προκριματική Φάση", site_lang.of("ert.gr")),
          leagues.category("Elite League U19 | 8η Αγωνιστική")), ("W", "U19"))

print("Пара, записанная наоборот, — тот же матч: метку эталона не снимаем (`canon.flag_disputed`)")
ТЕХАС = {"sport": "B", "home": "Texas", "away": "Baylor", "league": "USA: NCAA", "start_kyiv": "2026-11-15T22:00"}


def игра(home, away):
    return {"sport": "B", "home": home, "away": away, "league": "NCAA", "start_kyiv": "2026-11-15T22:00", "entries": []}


проверка("«Baylor — Texas» при эталонном «Texas — Baylor» и та же пара по местам — не спор; чужая пара — спор",
         [canon.flag_disputed(игра("Baylor", "Texas"), ТЕХАС), canon.flag_disputed(игра("Texas", "Baylor"), ТЕХАС),
          canon.flag_disputed(игра("Duke", "Kansas"), ТЕХАС)], [False, False, True])
проверка("одна сторона узнана твёрдо, вторая нечитаема — не спор, в любом порядке",
         [canon.flag_disputed(игра("Qwzx Plorb", "Texas"), ТЕХАС), canon.flag_disputed(игра("Texas", "Qwzx Plorb"), ТЕХАС)],
         [False, False])
проверка("сверка после заливки снимает метку этим правилом",
         "canon.flag_disputed(game, ref)" in inspect.getsource(canon_backfill))

print("Слово «женский» из примечания о другой передаче — не пол игры (`leagues.without_notes`)")
иврит = site_lang.of("sport5.co.il")
ПРИПИСКА = "ליגה גרמנית בכדורסל: אולדנבורג - אלבה ברלין. השידור יחל מיד בסיום כדורסל נשים"
проверка("sport5: «трансляция начнётся сразу по окончании женского баскетбола» — мужская игра остаётся мужской",
         (leagues.category(ПРИПИСКА, иврит), leagues.category(ПРИПИСКА)), ("", ""))
проверка("честное название женской игры на иврите — с артиклем, с предлогом, и перед словом «после»",
         [leagues.category(x, иврит) for x in ("ליגת העל לנשים: מכבי - הפועל", "גביע המדינה נשים",
                                               "כדורסל נשים: מכבי - הפועל. לאחר המשחק יחל האולפן")],
         ["W", "W", "W"])
проверка("хвост снимается только до конца предложения, и только у сайта этого языка",
         (leagues.without_notes("אחרי ההפסקה. גמר גביע הנשים", иврит).strip().endswith("גמר גביע הנשים"),
          leagues.without_notes(ПРИПИСКА, site_lang.of("webtv.sk")) == ПРИПИСКА,
          leagues.category("Kvalifikácia na ME 2027 ženy: Grécko - Slovensko", site_lang.of("webtv.sk"))),
         (True, True, "W"))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

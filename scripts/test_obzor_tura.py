# -*- coding: utf-8 -*-
r"""Обзор и итоги тура — не матч (книга 172, слово владельца 22.11.2026: «если
там написано обзор тура … записать это в словарь, книгу, чтоб обзор тура это
не матч»).

Повод: сбор 20.11.2026, sport5.co.il — передача «סוגרים בצבע - סיכום מחזור
ליגת העל בכדורסל, מחזור 7» («Закрываем в краске — итоги тура баскетбольной
лиги») с пометкой эфира стояла игрой «סוגרים בצבע — סיכום מחזור»: тире в
названии передачи принято за пару команд.

Что сторожится:

1. «итоги тура» на иврите в заголовке — стоп-слово: строка не игра, хоть сайт
   и пометил её эфиром; обычный матч той же лиги с того же сайта — игра;
2. то же на языках остальных сайтов: слова есть в `data/markers.json`
   (stop_title) и ищутся у сайта своего языка;
3. слово чужого языка на сайте не ищется (`data/word_langs.json`);
4. заголовки настоящих матчей со словами «тур», «итог», «jornada» — НЕ стоп.

В сеть не ходит, база не нужна:

    python scripts/test_obzor_tura.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import live, site_lang                            # noqa: E402
from app.parsers import Program                            # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
ВСЕ = live.load()
passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def стоп(домен: str, заголовок: str) -> str:
    markers = ВСЕ.for_langs(site_lang.of(домен))
    return markers.found(markers.stop_title, заголовок)


def взята(домен: str, заголовок: str, пара: str = "", лига: str = "") -> bool:
    """Берёт ли обход строку в ленту (`live.check`); эфир помечен сайтом."""
    program = Program(channel_raw="Канал", title=заголовок,
                      start=datetime(2026, 11, 23, 20, 0, tzinfo=KYIV),
                      league_raw=лига, live_raw="live", match_raw=пара)
    return live.check(program, ВСЕ.for_langs(site_lang.of(домен))).ok


print("1. Итоги тура на иврите (sport5.co.il, сбор 20.11.2026)")
ОБЗОР = "סוגרים בצבע - סיכום מחזור ליגת העל בכדורסל, מחזור 7"
check("«סוגרים בצבע - סיכום מחזור …» — стоп-слово", bool(стоп("sport5.co.il", ОБЗОР)))
check("с пометкой эфира и «парой» из тире — в ленту не идёт",
      not взята("sport5.co.il", ОБЗОР, пара="סוגרים בצבע - סיכום מחזור", лига="ליגת העל בכדורסל"))
check("«סיכום המחזור» (с артиклем) — тоже", bool(стоп("sport5.co.il", "סיכום המחזור בליגת העל")))
check("обычный матч той же лиги — игра",
      взята("sport5.co.il", "ליגת העל בכדורסל: מכבי תל אביב - הפועל ירושלים, מחזור 7",
            пара="מכבי תל אביב - הפועל ירושלים", лига="ליגת העל בכדורסל"))
check("«מחזור 7» (номер тура у матча) — НЕ стоп-слово",
      стоп("sport5.co.il", "ליגת העל בכדורסל: מכבי תל אביב - הפועל ירושלים, מחזור 7") == "")

print("2. То же на языках остальных сайтов")
for домен, заголовок in (
        ("ntvplus.tv", "Футбол. РПЛ. Обзор тура - 16-й тур"),
        ("maxsport.live", "Премьер-лига - Итоги тура"),
        ("vsetv.com", "УПЛ. Огляд туру - 14-й тур"),
        ("tv.dir.bg", "Първа лига - Обзор на кръга"),
        ("tvarenasport.com", "Superliga Srbije - Pregled kola"),
        ("movistarplus.es", "LALIGA EA Sports - Resumen de la jornada"),
        ("sporttv.pt", "Liga Portugal - Resumo da jornada"),
        ("programme-tv.net", "Ligue 1 - Résumé de la journée"),
        ("programetv.ro", "Superliga - Rezumatul etapei"),
        ("trtspor.com.tr", "Süper Lig - Haftanın özeti"),
        ("teleman.pl", "Ekstraklasa - Podsumowanie kolejki"),
        ("oneplay.cz", "Chance Liga - Souhrn kola"),
        ("rtl.de", "Bundesliga - Zusammenfassung des Spieltags"),
        ("ziggosport.nl", "Eredivisie - Samenvatting speelronde 12"),
        ("cosmotetv.gr", "Super League - Ανασκόπηση αγωνιστικής")):
    check(f"{домен}: «{заголовок}» — стоп-слово и не игра",
          bool(стоп(домен, заголовок)) and not взята(домен, заголовок, пара=заголовок))

print("3. Слово чужого языка на сайте не ищется")
check("испанское «resumen de la jornada» на хорватском сайте — не стоп-слово",
      стоп("sportklub.hr", "Resumen de la jornada") == "")
check("все новые латинские слова размечены языком",
      all(site_lang.word_langs(w) is not None for w in (
          "pregled kola", "pregled kroga", "resumen de la jornada", "resumo da jornada", "résumé de la journée",
          "rezumatul etapei", "haftanın özeti", "podsumowanie kolejki", "souhrn kola", "zhrnutie kola",
          "zusammenfassung des spieltags", "samenvatting speelronde", "sintesi della giornata",
          "forduló összefoglalója")))

print("4. Настоящие матчи — НЕ стоп")
for домен, заголовок, пара in (
        ("ntvplus.tv", "Футбол. РПЛ. 16-й тур. Зенит - Спартак", "Зенит - Спартак"),
        ("movistarplus.es", "LALIGA EA Sports (J13): Athletic Club - Espanyol", "Athletic Club - Espanyol"),
        ("sporttv.pt", "Liga Portugal - 12ª jornada: Benfica x Porto", "Benfica x Porto"),
        ("tvarenasport.com", "Superliga Srbije, 15. kolo: Partizan - Crvena zvezda", "Partizan - Crvena zvezda"),
        ("ziggosport.nl", "FC Barcelona - Villarreal CF", "FC Barcelona - Villarreal CF")):
    check(f"{домен}: «{заголовок}» — игра", стоп(домен, заголовок) == "" and взята(домен, заголовок, пара=пара))

print(f"\nИТОГ: {passed} из {passed + len(failed)}")
if failed:
    print("красные:", *failed, sep="\n  ")
    sys.exit(1)

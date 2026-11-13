# -*- coding: utf-8 -*-
r"""Передача с тире в названии — не матч; хвост тура у лиги (книги 108 и 109,
аудит 13.11.2026).

Повод 108: тире в названии передачи даёт «пару», и передача встаёт игрой
или вопросом владельцу «Вид спорта»:
  * ntvplus.tv «Only Live Once. 5-я серия - "Fise"» — 15 вопросов;
  * ipko.tv «S5E0 - Skoci-Maqedoni» — код выпуска сериала;
  * на витрине 13.11 стояли играми: «Fodbold: Nations League - Studie»
    (tvtid.tv2.dk), «Sport-Bild» (tv.orf.at),
    «ארץ הכדורגל - ליגה לאומית» и «ערב הכדורסל של ישראל - מחזור 6»
    (sport5.co.il).
Повод 109: «Scottish Premiership (15. Spieltag)» (start.sportdigital.de) —
словарь лиг искал подпись целиком и лигу не находил; «G-LEAGUE» (sport5) —
турнира не было в словах баскетбола.

Что сторожится:

1. слова серии по-русски и по-украински («5-я серия») — стоп-слова
   заголовка; «Серия А» — нет;
2. код выпуска «S5E0», «S02 E14» (`live.episode_code`) — не матч; «S4C»
   (канал), «SE», «S5» — нет;
3. студии и передачи — стоп-слова на языке своего сайта: датское «Studie»
   на чешском сайте не ищется (по-чешски это «исследование»);
4. `live.check`: такие строки сняты, обычный матч с того же сайта — взят;
5. судья очереди (`sport_question.Judge`) отвечает «не матч» сам;
6. `leagues.clean`: хвост тура или сезона в скобках срезан, возраст в
   скобках («(U21)») — нет;
7. «G-League» — баскетбол.

В сеть не ходит, база не нужна:

    python scripts/test_peredachi_s_tire.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import leagues, live, site_lang, sport            # noqa: E402
from app.parsers import Program                            # noqa: E402
from app.sport_question import Judge, Question             # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
ВСЕ = live.load()
SPORTS = sport.load()
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
                      start=datetime(2026, 11, 14, 20, 0, tzinfo=KYIV),
                      league_raw=лига, live_raw="live", match_raw=пара)
    return live.check(program, ВСЕ.for_langs(site_lang.of(домен))).ok


print("1. Серия по-русски и по-украински — стоп-слово")
check("«Only Live Once. 5-я серия - \"Fise\"» (ntvplus.tv)",
      bool(стоп("ntvplus.tv", 'Only Live Once. 5-я серия - "Fise"')))
check("«25-я серия - Air and Style»",
      bool(стоп("ntvplus.tv", "25-я серия - Air and Style")))
check("«3-я серія» — по-украински", bool(стоп("vsetv.com", "Спорт. 3-я серія")))
check("«Серия А: Милан - Интер» — НЕ стоп-слово",
      стоп("maxsport.live", "Серия А: Милан - Интер") == "")
check("«Италия. Серия А. Рома - Лацио» — НЕ стоп-слово",
      стоп("ntvplus.tv", "Италия. Серия А. Рома - Лацио") == "")
check("«Мировая серия. Финал» — НЕ стоп-слово",
      стоп("ntvplus.tv", "Мировая серия. Финал") == "")

print("2. Код выпуска сериала")
for текст, ждём in (("S5E0 - Skoci-Maqedoni", True), ("S02 E14 - Hajduk", True),
                    ("s1e3: Derby", True), ("S4C: Wales - Belgium", False),
                    ("SE Palmeiras - Santos", False), ("S5 - Roma", False),
                    ("WSE Cup: Porto - Barcelona", False),
                    ("Arsenal - Chelsea", False)):
    check(f"«{текст}» → {'код' if ждём else 'не код'}",
          bool(live.episode_code(текст)) == ждём, live.episode_code(текст))

print("3. Студии и передачи — на языке своего сайта")
check("«Fodbold: Nations League - Studie» (tvtid.tv2.dk)",
      bool(стоп("tvtid.tv2.dk", "Fodbold: Nations League - Studie")))
check("«Studie» на чешском сайте не ищется",
      стоп("oneplay.cz", "Studie - Sparta") == "")
check("«В перерыве Спорт-центр» в заголовке матча news.by — НЕ стоп-слово",
      стоп("news.by", "Алавес - Атлетик (Бильбао). Прямая трансляция. "
                      "В перерыве Спорт-центр") == "")
check("«Sport-Bild» (tv.orf.at)", bool(стоп("tv.orf.at", "Sport-Bild")))
check("«ארץ הכדורגל - ליגה לאומית» (sport5.co.il)",
      bool(стоп("sport5.co.il", "ארץ הכדורגל - ליגה לאומית")))
check("«ערב הכדורסל של ישראל - מחזור 6» (sport5.co.il)",
      bool(стоп("sport5.co.il",
                "ליגת העל בכדורסל: ערב הכדורסל של ישראל - מחזור 6")))
check("обычный матч sport5 — НЕ стоп-слово",
      стоп("sport5.co.il", "ליגת העל בכדורסל: מכבי תל אביב - הפועל ירושלים") == "")

print("4. Обход такие строки не берёт, матч — берёт")
check("сериал ntvplus снят",
      not взята("ntvplus.tv", 'Only Live Once. 5-я серия - "Fise"'))
check("«S5E0 - Skoci-Maqedoni» снят",
      not взята("ipko.tv", "S5E0 - Skoci-Maqedoni"))
check("код выпуска в поле пары — снят",
      not взята("ipko.tv", "SuperSport", пара="S5E0 - Skoci-Maqedoni"))
check("студия tv2.dk снята",
      not взята("tvtid.tv2.dk", "Fodbold: Nations League - Studie"))
check("«Sport-Bild» снят", not взята("tv.orf.at", "Sport-Bild"))
check("матч tv2.dk взят",
      взята("tvtid.tv2.dk", "Fodbold: Danmark - Norge"))
check("матч ipko.tv взят", взята("ipko.tv", "ARSENAL vs SPORTING"))

print("5. Судья очереди отвечает «не матч» сам")
СУДЬЯ = Judge(None, [], sports=SPORTS, markers=ВСЕ)
for строка, подсказка in (
        ("5-я серия - Fise | Trace Sport Stars (HD) (ntvplus.tv)",
         '2026-11-16 19:30 | Only Live Once. 5-я серия - "Fise"'),
        ("S5E0 - Skoci-Maqedoni | SuperSport 2 (ipko.tv)",
         "2026-11-14 07:00 | S5E0 - Skoci-Maqedoni")):
    ответ = СУДЬЯ.answer(Question.parse(строка, подсказка))
    check(f"«{строка[:40]}» → не матч", ответ.letter == "-", ответ)

print("6. Хвост тура у названия лиги")
for сырое, ждём in (
        ("Scottish Premiership (15. Spieltag)", "Scottish Premiership"),
        ("ASOBAL (T26/27)", "ASOBAL"),
        ("Bundesliga (Runde 11)", "Bundesliga"),
        ("Premier League (U21)", "Premier League (U21)"),
        ("Liga Portugal (Sub-19)", "Liga Portugal (Sub-19)"),
        ("Liga 2 (Romania)", "Liga 2 (Romania)"),
        ("Serie A", "Serie A")):
    check(f"«{сырое}» → «{ждём}»", leagues.clean(сырое) == ждём,
          leagues.clean(сырое))
карта = leagues.sports_map()
check("словарь лиг знает «Scottish Premiership» после чистки",
      карта.get(leagues.clean("Scottish Premiership (15. Spieltag)").lower())
      == "F")
ответ = СУДЬЯ.answer(Question.parse(
    "Heart of Midlothian - Celtic Glasgow | Scottish Premiership "
    "(15. Spieltag) | Sportdigital FUSSBALL (start.sportdigital.de)",
    "2026-11-29 17:30 | Heart of Midlothian - Celtic Glasgow"))
check("судья: «Scottish Premiership (15. Spieltag)» → футбол",
      ответ.letter == "F", ответ)

print("7. G-League — баскетбол")
for строка in ("G-LEAGUE: טקסס - ריו גרנדה ואלי",
               "NBA G League: Texas Legends - Rio Grande Valley Vipers"):
    v = SPORTS.decide(строка, строка)
    check(f"«{строка[:40]}» → баскетбол", v.letter == "B", (v.letter, v.word))

print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, "
      f"красных: {len(failed)}")
sys.exit(1 if failed else 0)

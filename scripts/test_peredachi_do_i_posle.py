# -*- coding: utf-8 -*-
r"""Книга 140 (15.11.2026): передачи ДО и ПОСЛЕ матча — не матч.

Замер по всем сайтам сбора 15.11: из 136 строк, где перед парой стоит слово
передачи, 7 шли в разбор матчем — «A-Liga: Før F.C. København-FC Midtjylland»
(tvtid.tv2.dk), «Juego de Naciones (T26/27): Post España - Inglaterra»
(movistarplus.es). Сравнение имён терпит лишнее слово в названии команды, и
«Før FC Nordsjælland» сходилось с эталоном как «Nordsjaelland». На витрину их
не пускал другой фильтр — случайно: у сайта стоял и сам матч. Словарь такие
«команды» уже выучил («Efter FC Midtjylland W», «Post Barcelona»).

Правило: слова «перед матчем» и «после матча» на языках наших сайтов —
стоп-слова заголовка (`data/markers.json`, раздел `stop_title`), язык каждого
— в `data/word_langs.json`: слово ищется только у сайтов своего языка.
В сеть не ходит, базу не открывает. Запуск: python scripts/test_peredachi_do_i_posle.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import live, pipeline, site_lang, sport  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import Reference  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
M, виды = live.load(), sport.load()
зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def стоп(сайт: str, заголовок: str) -> str:
    """Стоп-слово заголовка, как его видит разбор строк этого сайта."""
    свои = M.for_langs(site_lang.of(сайт))
    return свои.found(свои.stop_title, заголовок) or live.lead_show(свои, заголовок)


print("Передача до и после матча — стоп-слово на языке сайта")
проверка("датский: «Før …» и «Efter …» (tvtid.tv2.dk)",
         [стоп("tvtid.tv2.dk", "A-Liga: Før F.C. København-FC Midtjylland").casefold(),
          стоп("tvtid.tv2.dk", "UEFA Nations League: Efter Danmark-Norge").casefold(),
          стоп("tvsporten.dk", "Optakt: Danmark - Norge").casefold()], ["før", "efter", "optakt"])
проверка("испанский: «Post …» (movistarplus.es) перед парой — и в заголовке, и в поле пары",
         [стоп("movistarplus.es", "Juego de Naciones (T26/27): Post España - Inglaterra").casefold(),
          стоп("movistarplus.es", "Post España - Inglaterra").casefold(),
          стоп("movistarplus.es", "La pista del Tenis. Nitto ATP Finals (T2026): Post Alcaraz - Tiafoe").casefold()],
         ["post", "post", "post"])
проверка("французский, немецкий, шведский, финский, португальский, английский",
         [bool(стоп(сайт, заголовок)) for сайт, заголовок in (
             ("tvpassport.com", "Avant-match LNH"), ("tvpassport.com", "L'après-match LNH"),
             ("tv.orf.at", "Fußball: Vorbericht Österreich - Israel"), ("tvmatchen.nu", "Uppsnack: Sverige - Norge"),
             ("tvmatsit.com", "Ennakko: Suomi - Ruotsi"), ("sporttv.pt", "PÓS-JOGO BENFICA X PORTO"),
             ("tv24.co.uk", "Pre-Match: Arsenal v Chelsea"), ("tv24.co.uk", "Post-Match: Arsenal v Chelsea"))],
         [True] * 8)
проверка("книга 146: то же слово в середине фразы — предлог или пометка, матч остаётся матчем",
         [стоп(сайт, заголовок) for сайт, заголовок in (
             ("tvtid.tv2.dk", "Fodbold: Danmark - Norge (direkte efter TV Avisen)"),
             ("tvtid.tv2.dk", "Fodbold: Danmark - Norge, direkte fra studiet i Herning"),
             ("tv2.no", "Fotball: Norge - Italia, etter pause"), ("tvmatchen.nu", "Sverige - Danmark inför 50 000"),
             ("tv.orf.at", "Fußball: Österreich - Serbien; Vorberichte, das Spiel, Analysen"),
             ("tv24.co.uk", "Live: Arsenal v Chelsea (Build-Up 4.30pm, KO 5.30pm)"),
             ("movistarplus.es", "Euroliga: Bayern - Post SV Nürnberg"),
             ("tvtid.tv2.dk", "Optakt"))],
         [""] * 8)
проверка("сам матч теми же сайтами — не передача",
         [стоп("tvtid.tv2.dk", "A-Liga: F.C. København-FC Midtjylland"),
          стоп("movistarplus.es", "UEFA Nations League (T26/27): Inglaterra - España"),
          стоп("tv.orf.at", "Fußball: Österreich - Israel"), стоп("tvmatchen.nu", "Sverige - Norge")],
         ["", "", "", ""])
проверка("слово — только на своём языке: «post» у словацкого, немецкого и английского сайта стоп-словом не "
         "считается; «før» у шведского — тоже",
         [стоп("webtv.sk", "Basketbal: Post Viedeň - Inter Bratislava"), стоп("tv.orf.at", "Handball: Post SV Wien - Linz"),
          стоп("tv24.co.uk", "Post Office Cup: A v B"), стоп("tvmatchen.nu", "Før Sverige - Norge")],
         ["", "", "", ""])
проверка("клуб Post Wien цел и у испанского сайта: имя лежит в keep_names и вырезается перед поиском",
         [стоп("movistarplus.es", "Baloncesto: Post Wien - Real Madrid"),
          стоп("movistarplus.es", "Baloncesto: Post Viedeň - Real Madrid"),
          стоп("movistarplus.es", "Baloncesto: Post Real Madrid - Barcelona").casefold()],
         ["", "", "post"])

print("Разбор строки")
ЭТАЛОН = Reference([{"sport": "F", "home": "FC Copenhagen W", "away": "Midtjylland W",
                     "league": "DENMARK: A-Liga Women", "start_kyiv": "2026-11-21T15:00",
                     "names": {"da": ["FC København K", "Midtjylland K"]}}])


def разбор(сайт: str, заголовок: str, when=(2026, 11, 21, 15, 0)):
    p = Program(channel_raw="TV 2 Sport", title=заголовок, start=datetime(*when, tzinfo=KYIV),
                live_raw="direkte", match_raw="")
    row = pipeline.classify(p, M, виды, reference=ЭТАЛОН, langs=site_lang.of(сайт))
    return row.ok, (row.reason or "").split(":")[0]


проверка("«A-Liga: Før F.C. København-FC Midtjylland» за полчаса до матча — не матч: стоп-слово в заголовке; "
         "сам матч в свою минуту проходит",
         (разбор("tvtid.tv2.dk", "A-Liga: Før F.C. København-FC Midtjylland", (2026, 11, 21, 14, 30)),
          разбор("tvtid.tv2.dk", "A-Liga: F.C. København-FC Midtjylland")),
         ((False, "стоп-слово в заголовке"), (True, "")))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

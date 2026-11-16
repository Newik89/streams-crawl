# -*- coding: utf-8 -*-
r"""Книга 157 (16.11.2026): мусор в именах сторон.

На витрину уходили «LA LAKERS — PHOENIX !», «2026/27,Inverness Caledonian
Thistle — Ayr United» (bbc.co.uk), «Los Angeles Lakers — Charlotte Hornets -
Los Angeles Lakers - Charlotte Hornets» (dagenstv.com), «ligová fáze Faroe
Island — Moldavsko», «Magyarország W — Dánia csoportkör W», «Ukraine W —
France. Qualifications à l'EuroBasket féminin. 3e journée. Groupe M. W»,
«Eurobasket Feminino 2027 W — 2ª Fase de Qualificação W» (rtp.pt: турнир и
стадия, не пара). Правила:
  `app/live.py` (любой читатель пары):
    К1. знаки на краю стороны счищаются (`_EDGE`);
    К2. сезон «ГГГГ/ГГ» на краю стороны счищается (`_trim`);
    К3. пара, повторённая в подписи, — одна пара (`_unrepeated`);
    К4. срез по концу предложения — ещё одна догадка для эталона (`outer_trims`, правило 6);
  `app/pipeline.py` (`tidy_sides`, правила М0–М3):
    М0. «пара» со словом теннисного тура — название турнира, не трогаем;
    М1. пометка эфира внутри стороны — с неё и до конца срезается;
    М2. слова стадии и тура на внешних краях пары срезаются;
    М3. сторона целиком стадия или тур — строка не пара.
В сеть не ходит. Запуск: python scripts/test_musor_v_imenah.py
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
from app.reference import Reference  # noqa: E402

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


M = live.load()


def чисто(home, away, сайт=""):
    return pipeline.tidy_sides(home, away, M.for_langs(site_lang.of(сайт)) if сайт else M)


print("К1–К2. Края стороны: знаки и сезон")
проверка("знак на краю («PHOENIX !») и сезон, прилипший к имени («2026/27,Inverness…»)",
         [live.split_teams(x) for x in ("LA LAKERS - PHOENIX !", "2026/27,Inverness Caledonian Thistle - Ayr United",
                                        "Arsenal - Chelsea 2025/2026", "* Arsenal - Chelsea?")],
         [("LA LAKERS", "PHOENIX"), ("Inverness Caledonian Thistle", "Ayr United"), ("Arsenal", "Chelsea"),
          ("Arsenal", "Chelsea")])
ИМЕНА = ("Inter Miami CF - 1. FC Köln", "St. Pauli - D.C. United", "Al-Nassr - Bayer 04", "Schalke 04 - 1860 München",
         "Hapoel Be'er Sheva - Dinamo B.", "Hannover 96 - Nottingham F.", "Radnički 1923 - Zemun", "Borussia M. - Como 1907")
проверка("настоящие имена целы: номер, точка сокращения, дефис, год основания, апостроф",
         [live.split_teams(x) for x in ИМЕНА],
         [("Inter Miami CF", "1. FC Köln"), ("St. Pauli", "D.C. United"), ("Al-Nassr", "Bayer 04"),
          ("Schalke 04", "1860 München"), ("Hapoel Be'er Sheva", "Dinamo B."), ("Hannover 96", "Nottingham F."),
          ("Radnički 1923", "Zemun"), ("Borussia M.", "Como 1907")])

print("К3. Пара повторена в подписи — одна пара")
проверка("«A – B – A – B» — пара A, B; три разных куска и «A – B – A» — как раньше, не пара",
         [live.split_teams(x) for x in ("Los Angeles Lakers - Charlotte Hornets – Los Angeles Lakers – Charlotte Hornets",
                                        "Lakers - Hornets - lakers - hornets - Lakers - Hornets",
                                        "Virtus - Bologna - Baskonia", "Real Madrid - Barcelona - Real Madrid")],
         [("Los Angeles Lakers", "Charlotte Hornets"), ("Lakers", "Hornets"), None, None])
проверка("догадки для эталона у повторённой пары — одна чистая пара",
         live.split_candidates("Basket : Los Angeles Lakers – Charlotte Hornets – Los Angeles Lakers – Charlotte Hornets")[0],
         ("Los Angeles Lakers", "Charlotte Hornets"))

print("К4. Срез по концу предложения — догадка для эталона")
срезы = live.outer_trims("Ukraine", "France. Qualifications à l'EuroBasket féminin. 3e journée. Groupe M.")
проверка("восемь слов после точки (больше шести) — срез «France» среди догадок есть",
         (live.TRIM_AWAY, "Ukraine", "France") in [(w, h, a) for w, _c, h, a in срезы])
проверка("срез по точке — только догадка: у «St. Pauli — Eintr. Frankfurt» без эталона ничего не меняется",
         чисто("St. Pauli", "Eintr. Frankfurt"), ("St. Pauli", "Eintr. Frankfurt"))

print("М1–М3. Стадия и пометка эфира в стороне (`pipeline.tidy_sides`)")
проверка("М2: слова стадии и тура на внешних краях пары срезаются — чешский, венгерский, испанский, португальский, румынский",
         [чисто(*x) for x in (("ligová fáze Faroe Island", "Moldavsko"), ("Magyarország", "Dánia csoportkör"),
                              ("8ª jornada Bulgaria", "España"), ("FINAL 8 - CHÉQUIA", "CANADÁ"),
                              ("Badajoz", "Tenerife 1. forduló"), ("Elvetia", "Scotia Grupe"),
                              ("Magyarország", "Portugália csoportkör mérkőzés"), ("Game 7 Lakers", "Celtics"))],
         [("Faroe Island", "Moldavsko"), ("Magyarország", "Dánia"), ("Bulgaria", "España"), ("CHÉQUIA", "CANADÁ"),
          ("Badajoz", "Tenerife"), ("Elvetia", "Scotia"), ("Magyarország", "Portugália"), ("Lakers", "Celtics")])
проверка("М2 по предложениям: за точкой у гостей (перед ней у хозяев) стоит тур — всё за точкой не имя; "
         "точка сокращения без тура за ней не трогается",
         [чисто(*x) for x in (("Ukraine", "France. Qualifications à l'EuroBasket féminin. 3e journée. Groupe M"),
                              ("Coupe d'Europe. 3e journée. Monaco", "Paris"), ("St. Pauli", "Eintr. Frankfurt"),
                              ("Sportfr. Lotte", "Fort. Düsseldorf 2. Mannschaft"))],
         [("Ukraine", "France"), ("Monaco", "Paris"), ("St. Pauli", "Eintr. Frankfurt"),
          ("Sportfr. Lotte", "Fort. Düsseldorf 2. Mannschaft")])
проверка("М1: пометка эфира внутри стороны — с неё и до конца срезается (слова языка сайта)",
         [чисто("Unicaja", "BK KVIS Pardubice Přímý přenos utkání základní skupiny basketbalové Ligy mistrů", "webtv.sk"),
          чисто("Portugal", "Alemanha Direto Teletexto HD Todos 16:9 4:3 RTP Play", "rtp.pt"),
          чисто("Live Arsenal", "Chelsea live", "bbc.co.uk")],
         [("Unicaja", "BK KVIS Pardubice"), ("Portugal", "Alemanha"), ("Arsenal", "Chelsea")])
проверка("М3: сторона целиком стадия или тур — не пара: «турнир — стадия», «передача — тур 6», «Real Madrid — Final»",
         [чисто(*x) for x in (("Eurobasket Feminino 2027", "2ª Fase de Qualificação"), ("ערב הכדורסל של ישראל", "מחזור 6"),
                              ("Real Madrid", "Final"), ("Finale", "Liverpool"), ("Coupe de France", "3e journée"))],
         [None] * 5)
проверка("М0: «пара» со словом теннисного тура — название турнира, её ведут свои правила",
         [чисто(*x) for x in (("ATP", "Nitto ATP Finals"), ("ATP FINALS 2026", "MEIA-FINAL"), ("ATP Finals", "Semifinale"))],
         [("ATP", "Nitto ATP Finals"), ("ATP FINALS 2026", "MEIA-FINAL"), ("ATP Finals", "Semifinale")])
проверка("настоящие имена не тронуты: короткое слово-тёзка стадии («LEG», «Day», «Ida»), греческое «Μονάχου», год, номер",
         [чисто(*x) for x in (("LEG", "GET"), ("Day", "Night"), ("Ida-Virumaa FC Alliance", "Narva Trans"),
                              ("Ζάλγκιρις Κάουνας", "Μπάγερν Μονάχου"), ("Schalke 04", "1860 München"),
                              ("Inter Miami CF", "1. FC Köln"), ("Hapoel Be'er Sheva", "Dinamo B."),
                              ("Zemun", "Radnički 1923"), ("Al-Nassr", "Bayer 04"), ("St. Pauli", "D.C. United"))],
         [("LEG", "GET"), ("Day", "Night"), ("Ida-Virumaa FC Alliance", "Narva Trans"),
          ("Ζάλγκιρις Κάουνας", "Μπάγερν Μονάχου"), ("Schalke 04", "1860 München"), ("Inter Miami CF", "1. FC Köln"),
          ("Hapoel Be'er Sheva", "Dinamo B."), ("Zemun", "Radnički 1923"), ("Al-Nassr", "Bayer 04"),
          ("St. Pauli", "D.C. United")])

print("Разбор строки (`pipeline.classify`)")
виды = sport.load()


def строка(title, match_raw, live_raw="live", description="", league_raw="", sport_raw="", час=20):
    return Program(channel_raw="Sport 1", title=title, start=datetime(2026, 11, 17, час, 0, tzinfo=KYIV),
                   live_raw=live_raw, match_raw=match_raw, description=description, league_raw=league_raw,
                   sport_raw=sport_raw)


row = pipeline.classify(строка("Fotbal", "ligová fáze Faroe Island - Moldavsko", "priamy prenos", sport_raw="Fotbal"), M, виды)
проверка("стадия перед хозяевами срезана и без эталона; срез записан в журнал пометкой «по: стадия»",
         (row.ok, row.home, row.away, row.program.extra.get(pipeline.TRIMMED)),
         (True, "Faroe Island", "Moldavsko",
          {"где": live.TRIM_HOME, "срезано": "ligová fáze", "было": "ligová fáze Faroe Island - Moldavsko",
           "по": pipeline.BY_STAGE}))
row = pipeline.classify(строка("Női kosárlabda Európa-bajnoki selejtező: Magyarország - Dánia csoportkör mérkőzés",
                               "Magyarország - Dánia csoportkör", "élő", league_raw="Női kosárlabda Európa-bajnoki selejtező"),
                        M, виды, langs=site_lang.of("port.hu"))
проверка("стадия после гостей срезана, пол турнира не потерян", (row.ok, row.home, row.away),
         (True, "Magyarország W", "Dánia W"))
row = pipeline.classify(строка("Eurobasket Feminino 2027 - 2ª Fase de Qualificação", "Eurobasket Feminino 2027 - 2ª Fase de Qualificação",
                               "Direto", sport_raw="Basquetebol"), M, виды, langs=site_lang.of("rtp.pt"))
проверка("«турнир — стадия» без эталона — не игра: пары не видно", (row.ok, row.reason), (False, pipeline.NO_PAIR))
ЭТАЛОН = Reference([{"sport": "B", "home": "Portugal W", "away": "Germany W", "start_kyiv": "2026-11-17T20:00",
                     "league": "EUROPE: EuroBasket Women - Qualification", "fs_id": "ptde",
                     "names": {"pt": ["Portugal F", "Alemanha F"]}},
                    {"sport": "B", "home": "Ukraine W", "away": "France W", "start_kyiv": "2026-11-17T20:00",
                     "league": "EUROPE: EuroBasket Women - Qualification", "fs_id": "uafr", "names": {}}])
row = pipeline.classify(строка("Eurobasket Feminino 2027 - 2ª Fase de Qualificação", "Eurobasket Feminino 2027 - 2ª Fase de Qualificação",
                               "Direto", description="Portugal x Alemanha Direto Teletexto HD Todos 16:9 4:3 RTP Play",
                               sport_raw="Basquetebol"), M, виды, reference=ЭТАЛОН, langs=site_lang.of("rtp.pt"))
проверка("…а с эталоном пара берётся из описания, приписка об эфире после гостей срезана",
         (row.ok, row.home, row.away), (True, "Portugal W", "Alemanha W"))
row = pipeline.classify(строка("Basket-ball : Qualifications à l'EuroBasket féminin",
                               "Ukraine - France. Qualifications à l'EuroBasket féminin. 3e journée. Groupe M.", "en direct",
                               sport_raw="basket"), M, виды, reference=ЭТАЛОН, langs=site_lang.of("programme-tv.net"))
проверка("хвост после точки (восемь слов) срезан по эталону; французское «féminin» со значком — женский турнир",
         (row.ok, row.home, row.away, row.league_category), (True, "Ukraine W", "France W", "W"))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

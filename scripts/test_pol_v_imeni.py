# -*- coding: utf-8 -*-
r"""Пол в именах команд и в заголовке строки (книга 086, слово владельца
27.10.2026). Повод: Novasports пишет Манчестер Юнайтед «Μάντσεστερ Γ.»
(Γ. — сокращение), и «Τσέλσι - Μάντσεστερ Γ.» стал женским матчем —
канал Novasports пропал у 4 игр МЮ; в эталоне flashscore 93 мужских имени
читались женскими (инициалы теннисистов «Zheng W.», «Polonia W.», третьи
команды «Ατλέτικο Μαδρίτης Γ»).

Что сторожится:

1. имя (`names.category`): одиночная буква пола (W, Γ, Ž, Ж) — женская
   только последней в имени или в скобках; после неё — лишь страна в
   скобках, «WO», «RETIRED», возраст, номер состава; с точкой — сокращение
   или инициал; «& W» — не пол; в середине имени — часть имени;
   «(F)», «(FEM)» — женская пометка;
2. пара (`names.pair_category`): буква ищется в конце КАЖДОГО имени —
   «Arsenal W» + «Chelsea» женская, как и раньше;
3. эталон (`canon.local_name`): греческая «Γ», «Ž», украинская «Ж» у
   женской английской записи → W, у мужской — не пол («Ατλέτικο Μαδρίτης
   Γ» при «Atl. Madrid C» → «… C»);
4. заголовок (`leagues.category`): буква с точкой или апострофом —
   сокращение («Μάντσεστερ Γ.», «Γ’ Προημιτελικός»); новые пометки
   «(F)», «(FEM)», португальское «Seniores F», албанское «femra…»;
5. язык строки — язык сайта плюс письменность самой строки
   (`site_lang.of_row`): русская строка на литовском tv3.lt — по-русски;
6. `pipeline.run`: novasports «Τσέλσι - Μάντσεστερ Γ.» — без W,
   sporting.pt «Futebol (Seniores F): SL Benfica vs. SPORTING CP» — с W.

В сеть не ходит, база не нужна:

    python scripts/test_pol_v_imeni.py
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
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.gettempdir()) / "pol-none.db"))

from app import canon, leagues, live, names, pipeline, site_lang, sport  # noqa: E402
from app.parsers import Program  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✗ {имя}: вышло {вышло!r}, ждали {ждём!r}")


def женская(имя: str) -> bool:
    return "W" in names.category(имя).split()


print("1. Имя команды")
for имя in ("Arsenal W", "Νυρεμβέργη Γ", "Penarol Ž", "1.ФК Нюрнберг Ж",
            "Arsenal W U19", "Spain W (Esp)", "Werder W II", "Smith W WO",
            "Spain (W)", "Golden State Valkyries (Ж)", "Germany (F)", "Benfica (FEM)"):
    проверка(f"«{имя}» — женская", женская(имя), True)
for имя in ("Μάντσεστερ Γ.", "Polonia W.", "Polonia W. U19", "Zheng W.",
            "Λι Γ./Οβτσαρένκο", "Конісі Камаргу Сілва Ж.", "Havant & W", "H&W Welders",
            "Εμπράικα γ Μακάμπι", "Real Madrid C"):
    проверка(f"«{имя}» — не женская", женская(имя), False)
проверка("возраст остаётся: «Polonia W. U19» → U19", names.category("Polonia W. U19"), "U19")
проверка("сравнение без пометки: «Spain W (Esp)» читается как «Spain (Esp)»",
         names.readings("Spain W (Esp)")[0], names.readings("Spain (Esp)")[0])

print("2. Пара — буква в конце каждого имени")
проверка("«Arsenal W» + «Chelsea» — женская (одна сторона)",
         names.pair_category("Arsenal W", "Chelsea"), "W")
проверка("«Arsenal W» + «Chelsea W U19»", names.pair_category("Arsenal W", "Chelsea W U19"), "U19 W")
проверка("«Τσέλσι» + «Μάντσεστερ Γ.» — мужская", names.pair_category("Τσέλσι", "Μάντσεστερ Γ."), "")
проверка("второй состав — как у склеенной строки",
         names.pair_category("Benfica B", "Porto B"), names.category("Benfica B Porto B"))
проверка("пара + турнир: «Women» в турнире — женская",
         names.pair_category("Liverpool", "Everton", "England: Super League Women"), "W")

print("3. Эталон: местные написания flashscore")
проверка("el, женская: «Νυρεμβέργη Γ» → W",
         canon.local_name("Νυρεμβέργη Γ", "Nurnberg W", "el"), "Νυρεμβέργη W")
проверка("el, мужская: «Ατλέτικο Μαδρίτης Γ» при «Atl. Madrid C» → C",
         canon.local_name("Ατλέτικο Μαδρίτης Γ", "Atl. Madrid C", "el"), "Ατλέτικο Μαδρίτης C")
проверка("hr, мужская без буквы в английском — буква снимается",
         canon.local_name("Dinamo Zagreb Ž", "Dinamo Zagreb", "hr"), "Dinamo Zagreb")
проверка("uk, женская: «Нюрнберг Ж» → W", canon.local_name("Нюрнберг Ж", "Nurnberg W", "uk"),
         "Нюрнберг W")
проверка("cs, женская: «Slavia Praha Ž» → W",
         canon.local_name("Slavia Praha Ž", "Slavia Prague W", "cs"), "Slavia Praha W")
проверка("it, как было: «Italia D» → W", canon.local_name("Italia D", "Italy W", "it"), "Italia W")
проверка("it, мужская — без перемен: «Real Madrid D»",
         canon.local_name("Real Madrid D", "Real Madrid", "it"), "Real Madrid D")
проверка("мужское английское с инициалом «Zheng W.» — не женское", женская("Zheng W."), False)

print("4. Заголовок строки")
EL = site_lang.of("novasports.gr")
проверка("«Τσέλσι - Μάντσεστερ Γ.» на novasports — без W",
         leagues.category("Τσέλσι - Μάντσεστερ Γ.", EL), "")
проверка("«Γ’ Προημιτελικός» — сокращение, не пол",
         leagues.category("Μπάσκετ | Γ’ Προημιτελικός", EL), "")
проверка("«Νυρεμβέργη Γ - Χέρτα Γ» — женская", leagues.category("Νυρεμβέργη Γ - Χέρτα Γ", EL), "W")
проверка("«(F)» — женская везде",
         leagues.category("Golden League 1: Denmark - Germany (F)", site_lang.of("allente.no")), "W")
проверка("«(FEM)» — женская (sporttv.pt)",
         leagues.category("KUKULKOVA X SHAO (FEM)", site_lang.of("sporttv.pt")), "W")
проверка("«Seniores F» — женская на sporting.pt",
         leagues.category("Futebol (Seniores F): SL Benfica vs. SPORTING CP",
                          site_lang.of("sporting.pt")), "W")
проверка("«Seniores F» — португальское, на хорватском сайте не ищется",
         leagues.category("Seniores F", site_lang.of("sportklub.hr")), "")
проверка("«femrave» — женская на ipko.tv",
         leagues.category("Boterori i femrave: Uells-Shqiperi", site_lang.of("ipko.tv")), "W")
проверка("«Ž» в скобках — как было", leagues.category("Odbojka - Njemačka liga (Ž): Stuttgart - Suhl",
                                                     site_lang.of("sportklub.hr")), "W")

print("5. Язык строки = язык сайта + письменность строки")
LT = site_lang.of("tv3.lt")
проверка("латиница ничего не добавляет", site_lang.of_row(LT, "Krepšinis"), LT)
проверка("кириллица добавляет русский", "ru" in site_lang.of_row(LT, "Велоспорт. Париж - Рубе Женщины"),
         True)
проверка("неизвестный сайт — все языки", site_lang.of_row(None, "Женщины"), None)

print("6. pipeline.run с доменом сайта")
KYIV = ZoneInfo("Europe/Kyiv")
ВСЕ = live.load()
SPORTS = sport.load(teams=())


def строка(domain: str, title: str, match: str, league: str = "") -> pipeline.Row:
    p = Program(channel_raw="Канал", title=title, league_raw=league, match_raw=match,
                start=datetime(2026, 10, 28, 20, 0, tzinfo=KYIV), live_raw="live")
    return pipeline.run([p], ВСЕ, SPORTS, {}, {}, domain=domain)[0]


row = строка("novasports.gr", "Τσέλσι - Μάντσεστερ Γ.", "Τσέλσι - Μάντσεστερ Γ.")
проверка("novasports: «Τσέλσι - Μάντσεστερ Γ.» — мужская пара",
         ("W" in names.category(row.home).split(), "W" in names.category(row.away).split(),
          row.league_category), (False, False, ""))
row = строка("sporting.pt", "Futebol (Seniores F): SL Benfica vs. SPORTING CP",
             "SL Benfica - SPORTING CP")
проверка("sporting.pt: «Seniores F» — обе команды с W",
         (row.home.endswith(" W"), row.away.endswith(" W")), (True, True))
row = строка("tv3.lt", "Футбол. Женщины. Литва - Латвия", "Литва - Латвия")
проверка("tv3.lt: русская строка «Женщины» — женская", row.league_category, "W")

print(f"\nзелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

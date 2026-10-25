# -*- coding: utf-8 -*-
r"""Язык сайта для служебных слов строки (книга 084, слово владельца
25.10.2026): «сайт на хорватском — слова проверяются с хорватского на
английский; названия команд могут быть уже по-английски». Повод — #7925:
венгерское «női» (и «noi») нашлось в «Ha Noi» на хорватском sportklub.hr.

Что сторожится:

1. у КАЖДОГО сайта плана обхода есть языки (`site_lang.SITE_LANGS`) — новый
   сайт без языка краснеет здесь;
2. у КАЖДОГО латинского слова `data/markers.json` (live, not_live,
   stop_title, stop_genre) есть язык в `data/word_langs.json` или пометка
   «_общие»; лишних слов в `word_langs.json` нет;
3. пол: «Ha Noi» на хорватском сайте — не женская; «Női» на венгерском —
   женская, на хорватском — нет; английское «Women» и «(w)» — везде;
   сайт неизвестен — все языки, как было;
4. эфир и повтор: «uživo» — эфир на хорватском сайте, «élő» там не ищется,
   но ищется на венгерском; английское «live» — везде; иврит — только у
   израильских сайтов;
5. `pipeline.run` с доменом — строка «Ha Noi» с sportklub.hr идёт без W.

В сеть не ходит, база не нужна:

    python scripts/test_yazyk_sayta.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.gettempdir()) / "yazyk-none.db"))

from app import leagues, live, pipeline, site_lang, sport  # noqa: E402
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


HR = site_lang.of("sportklub.hr")
HU = site_lang.of("port.hu")
IL = site_lang.of("sport5.co.il")

print("1. У каждого сайта плана есть языки")
план = json.loads((ROOT / "data" / "crawl_plan.json").read_text(encoding="utf-8"))
записи = план if isinstance(план, list) else next(v for v in план.values() if isinstance(v, list))
домены = sorted({x["domain"] for x in записи if isinstance(x, dict) and x.get("domain")})
без_языка = [d for d in домены if site_lang.of(d) is None]
проверка(f"сайтов в плане {len(домены)}, без языка — ни одного", без_языка, [])
проверка("www. в домене не мешает", site_lang.of("www.sportklub.hr"), HR)
проверка("английский — у каждого сайта", all("en" in site_lang.of(d) for d in домены), True)
проверка("неизвестный сайт — None (все языки)", site_lang.of("new-site.example"), None)

print("2. У каждого латинского служебного слова есть язык или пометка «общее»")
разметка = json.loads(site_lang.WORD_LANGS_FILE.read_text(encoding="utf-8"))
общие = {" ".join(w.lower().split()) for w in разметка.get("_общие", [])}
markers = json.loads(live.MARKERS_FILE.read_text(encoding="utf-8"))
слова = {" ".join(w.lower().split())
         for section in ("live", "not_live", "stop_title", "stop_genre")
         for w in live._flatten(markers.get(section))}
латинские = {w for w in слова if re.search(r"[a-z]", w)
             and not re.search(r"[Ͱ-ϿЀ-ӿ֐-׿؀-ۿ]", w)}
без_разметки = sorted(w for w in латинские
                      if site_lang.word_langs(w) is None and w not in общие)
проверка(f"латинских слов {len(латинские)}, без языка и не общих — ни одного", без_разметки, [])
размечено = set(site_lang._tagged()) | общие
лишние = sorted(размечено - слова)
проверка("в word_langs.json нет слов, которых нет в markers.json", лишние, [])
проверка("иврит — по буквам", site_lang.word_langs("ישיר"), frozenset({"he"}))
проверка("греческий — по буквам", site_lang.word_langs("ζωντανά"), frozenset({"el"}))
проверка("кириллица — группа языков", "bg" in site_lang.word_langs("пряко"), True)

print("3. Пол по языку сайта")
проверка("«…Shanghai Port - Cong An Ha Noi» на sportklub.hr — не женская (#7925)",
         leagues.category("Nogomet - LP Azije ELITE: Shanghai Port - Cong An Ha Noi", HR), "")
проверка("«Női kézilabda» на port.hu — женская",
         leagues.category("Női kézilabda: Győr - Ferencváros", HU), "W")
проверка("«Női kézilabda» на sportklub.hr — венгерское слово не ищется",
         leagues.category("Női kézilabda", HR), "")
проверка("«ženske» на sportklub.hr — женская",
         leagues.category("Košarka - Euroliga za žene: Zaragoza - Kibirkstis", HR), "W")
проверка("«Women Super League» — английское, на хорватском сайте тоже",
         leagues.category("Nogomet - Women Super League: Arsenal - Chelsea", HR), "W")
проверка("«(w)» — везде", leagues.category("Spain (W) - France (W)", HR), "W")
проверка("«הנשים» на хорватском сайте не ищется, на sport5 — ищется",
         (leagues.category("בכדורגל הנשים", HR), leagues.category("בכדורגל הנשים", IL)), ("", "W"))
проверка("сайт неизвестен — все языки, как было",
         leagues.category("Női kézilabda", None), "W")
проверка("возраст от языка не зависит",
         leagues.category("Liga BPI Sub-19", site_lang.of("canal11.pt")), "U19 W")

print("4. Эфир и повтор по языку сайта")
все = live.load()
hr, hu, il = все.for_langs(HR), все.for_langs(HU), все.for_langs(IL)
проверка("«uživo» — эфир на хорватском сайте", bool(hr.found(hr.live, "Nogomet uživo")), True)
проверка("«élő» на хорватском сайте не ищется", hr.found(hr.live, "Kosárlabda élő"), "")
проверка("«élő» на венгерском — эфир", bool(hu.found(hu.live, "Kosárlabda élő")), True)
проверка("«live» — везде", (bool(hr.found(hr.live, "LIVE")), bool(hu.found(hu.live, "LIVE"))), (True, True))
проверка("«ישיר» — только у израильского сайта",
         (hr.found(hr.live, "ישיר"), bool(il.found(il.live, "ישיר"))), ("", True))
проверка("«snimak» — повтор на хорватском, не на венгерском",
         (bool(hr.found(hr.not_live, "snimak")), hu.found(hu.not_live, "snimak")), (True, ""))
проверка("«studio» — общее, стоп-слово везде",
         (bool(hr.found(hr.stop_title, "Studio")), bool(hu.found(hu.stop_title, "Studio"))), (True, True))
проверка("сайт неизвестен — те же слова, что раньше", все.for_langs(None) is все, True)
проверка("кэш: тот же набор языков — тот же объект", все.for_langs(HR) is hr, True)

print("5. pipeline.run с доменом сайта")
KYIV = ZoneInfo("Europe/Kyiv")
строка = Program(channel_raw="Sport Klub 6",
                 title="Nogomet - LP Azije ELITE: Shanghai Port - Cong An Ha Noi",
                 start=datetime(2026, 10, 27, 12, 0, tzinfo=KYIV), live_raw="uživo",
                 match_raw="Shanghai Port - Cong An Ha Noi", league_raw="LP Azije ELITE")
SPORTS = sport.load(teams=())
row = pipeline.run([строка], все, SPORTS, {}, {}, domain="sportklub.hr")[0]
проверка("sportklub.hr: «Shanghai Port — Cong An Ha Noi» без W",
         (row.home, row.away, row.league_category), ("Shanghai Port", "Cong An Ha Noi", ""))
проверка("…и эфир прочитан по-хорватски", bool(row.live_marker), True)

print(f"\nзелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

# -*- coding: utf-8 -*-
r"""Запасное чтение видит пометку эфира (книга 175; вопрос владельца
22.11.2026 «почему не видит?», слово «да, делаем оба»).

Повод: проба книги 171 на сборе 20.11.2026 — без пометки эфира запасное
чтение не вернуло игры, которых эталон не знает (sport5.co.il: имена на иврите
без перевода), и показ матча, подхваченный каналом с середины (ziggosport.nl).
Пометка у каждого сайта своя: картинка с подписью «ישיר», поле `live`
служебного ответа, слово в названии.

Что сторожится (правила К1–К3 `app/fallback_many.py`):

1. К1: слово эфира — из словаря, на языке сайта; «Liverpool» и «повтор
   прямого эфира» — не эфир;
2. К1: способы пометки на странице с разметкой («после», «до», «название») и
   в служебном ответе («поле», «значение»);
3. К2: тень запоминает способ, которым пометка сошлась со своим разборщиком у
   ВСЕХ строк и на ВСЕХ страницах ключа; не сошлась — способа нет;
4. К3: способу верим с `LIVE_MIN` строк с эфиром; тогда чтение ставит строкам
   пометку эфира, и страница не «слепая»; способа нет — как раньше;
5. отсев: помеченная строка запасного чтения — игра и без эталона; та же
   строка без пометки — нет;
6. детектор: `parse_live` передаёт чтению сайт страницы.

В сеть не ходит, база не нужна:

    python scripts/test_pometka_efira.py
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ["STREAMS_DB"] = str(Path(tempfile.mkdtemp(prefix="pometka-")) / "t.db")

from app import fallback_many, fallback_read, live, pipeline, site_lang, sport  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import Reference  # noqa: E402
import parse_live  # noqa: E402

зелёных = красных = 0
ДЕНЬ = date(2026, 11, 20)
ПОЯС = "Asia/Jerusalem"
ЗОНА = ZoneInfo(ПОЯС)
САЙТ = "sport5.co.il"
АДРЕС = "https://www.sport5.co.il/Ajax/GetBroadcastSheetData.aspx?date=20%2F11%2F2026"
АДРЕС_ЗАВТРА = "https://www.sport5.co.il/Ajax/GetBroadcastSheetData.aspx?date=21%2F11%2F2026"
КАНАЛЫ = ["ערוץ הספורט", "ספורט 2"]


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def ряд(время: str, название: str, эфир: bool) -> str:
    """Строка сетки sport5.co.il: картинка «ישיר» стоит между временем и названием."""
    значок = '<div><img src="/images/img-live.png" alt="ישיר" title="ישיר" /></div>' if эфир else ""
    return (f'<tr><td class="date"><div> {время} </div>{значок}</td>'
            f'<td><div class="spaceleft"></div></td><td class="text">{название}</td></tr>')


def шапка(канал: str) -> str:
    return f'<tr class="tr-header"><th colspan="4"><span class="channel-text">{канал}</span></th></tr>'


def своя(канал: str, часы: int, минуты: int, название: str, эфир: bool, день: date = ДЕНЬ) -> Program:
    """Как свой разборщик sport5.co.il: рубрика до двоеточия — лига, дальше пара, после запятой — тур."""
    лига, _, остаток = название.partition(": ")
    return Program(channel_raw=канал, title=название, live_raw="ישיר" if эфир else "",
                   league_raw=лига if остаток else "", match_raw=(остаток or название).split(", ")[0],
                   start=datetime(день.year, день.month, день.day, часы, минуты, tzinfo=ЗОНА))


СЕТКА = [("ערוץ הספורט", 17, 0, "חדשות הספורט", False),
         ("ערוץ הספורט", 19, 0, "ליגת העל בכדורסל: מכבי רעננה - בני הרצליה, מחזור 7", True),
         ("ערוץ הספורט", 21, 45, "ליגה צרפתית: מונאקו - אוקזר, מחזור 11", True),
         ("ספורט 2", 16, 0, "ליגה סקוטית: מות'רוול - ריינג'רס", True),
         ("ספורט 2", 18, 0, "ליגה סקוטית: מות'רוול - ריינג'רס (שידור חוזר)", False),
         ("ספורט 2", 21, 0, "NBA: ל.א. לייקרס - יוטה", True)]


def страница(сетка) -> str:
    out, канал = ["<table>"], ""
    for к, ч, м, название, эфир in сетка:
        if к != канал:
            out.append(шапка(к))
            канал = к
        out.append(ряд(f"{ч:02d}:{м:02d}", название, эфир))
    return "".join(out) + "</table>"


def свои(сетка, день: date = ДЕНЬ) -> list:
    return [своя(к, ч, м, название, эфир, день) for к, ч, м, название, эфир in сетка]


СТРАНИЦА = страница(СЕТКА)

print("К1. Слово эфира — из словаря, на языке сайта")
слово = fallback_many._live_word(САЙТ)
проверка("«ישיר» — эфир", bool(слово("ישיר")))
проверка("«Liverpool - Everton» — не эфир (слово ищется целиком)", fallback_many._live_word("ziggosport.nl")("Liverpool - Everton"), "")
проверка("«LIVE: Ajax - PSV» — эфир", bool(fallback_many._live_word("ziggosport.nl")("LIVE: Ajax - PSV")))
проверка("рядом слово записи — не эфир", слово("שידור חוזר ישיר"), "")
проверка("не текст и длинный текст — не пометка", [слово(None), слово(True), слово("ישיר " * 100)], ["", "", ""])

print("К1. Способы пометки на странице с разметкой")
строки = fallback_many.rows_marked(СТРАНИЦА, ДЕНЬ, ПОЯС, КАНАЛЫ, слово)
проверка("«после»: картинка эфира между временем и названием — у помеченных строк, и только у них",
         [bool(m["после"]) for _к, _н, _т, m in строки], [э for *_x, э in СЕТКА])
проверка("«название» и «до» на этой странице пометку не видят",
         [(bool(m["название"]), bool(m["до"])) for *_x, m in строки], [(False, False)] * 6)
ДО = ("<div>" + "".join(
    f"<h3>{к}</h3>" + "".join(f"<p>{'<b>LIVE</b>' if э else ''}<span>{ч:02d}:{м:02d}</span><i>{н}</i></p>" for ч, м, н, э in ряды)
    for к, ряды in (("Sport 1", [(18, 0, "Studio", False), (19, 0, "Ajax - PSV", True), (22, 0, "Ajax - PSV (herhaling)", False)]),
                    ("Sport 2", [(19, 0, "Feyenoord - AZ", True)]))) + "</div>")
до = fallback_many.rows_marked(ДО, ДЕНЬ, "Europe/Amsterdam", ["Sport 1", "Sport 2"], fallback_many._live_word("ziggosport.nl"))
проверка("«до»: слово эфира стоит перед временем строки", [bool(m["до"]) for *_x, m in до], [False, True, False, True])
проверка("«после» на такой странице приписало бы пометку соседней строке — оно и не сходится",
         [bool(m["после"]) for *_x, m in до], [True, False, False, False])
проверка("без слова эфира пометки не читаются; `rows` отдаёт тройки, как раньше",
         [fallback_many.rows_marked(СТРАНИЦА, ДЕНЬ, ПОЯС, КАНАЛЫ)[0][3], len(fallback_many.rows(СТРАНИЦА, ДЕНЬ, ПОЯС, КАНАЛЫ)[0])],
         [{}, 3])

print("К1. Способы пометки в служебном ответе")
ОТВЕТ = json.dumps({"channels": [
    {"name": "Ziggo Sport 1", "items": [
        {"start": "2026-11-20T18:00:00+01:00", "title": "Rondo", "live": False},
        {"start": "2026-11-20T20:00:00+01:00", "title": "Ajax - PSV", "live": True},
        {"start": "2026-11-20T23:00:00+01:00", "title": "Ajax - PSV", "live": False}]},
    {"name": "Ziggo Sport 2", "items": [
        {"start": "2026-11-20T20:00:00+01:00", "title": "Feyenoord - AZ", "live": 1, "type": "Voetbal"},
        {"start": "2026-11-20T22:30:00+01:00", "title": "Samenvattingen", "live": 0, "status": "LIVE"}]}]})
ответ = fallback_many.rows_marked(ОТВЕТ, ДЕНЬ, "Europe/Amsterdam", ["Ziggo Sport 1", "Ziggo Sport 2"],
                                  fallback_many._live_word("ziggosport.nl"))
проверка("«поле»: поле эфира со значением «да»", [bool(m["поле"]) for *_x, m in ответ], [False, True, False, True, False])
проверка("«значение»: слово эфира значением другого поля", [bool(m["значение"]) for *_x, m in ответ],
         [False, False, False, False, True])

print("К2. Тень запоминает способ, которым пометка сошлась")
память, вердикты = {}, {}
проверка("страница сошлась", fallback_many.shadow(память, вердикты, САЙТ, АДРЕС, СТРАНИЦА, ДЕНЬ, ПОЯС, свои(СЕТКА)))
ключ = fallback_read.page_key(САЙТ, АДРЕС)
проверка("в памяти — способ «после» и число строк с эфиром",
         [память[ключ][fallback_many.LIVE][fallback_many.LIVE_WAYS], память[ключ][fallback_many.LIVE][fallback_many.LIVE_ROWS]],
         [["после"], 4])
проверка("К4: в памяти — способы вынуть пару из названия, сошедшиеся у всех строк с эфиром",
         [память[ключ][fallback_many.LIVE][fallback_many.PAIR], память[ключ][fallback_many.LIVE][fallback_many.PAIR_ROWS],
          fallback_many.pair_way(память[ключ])],
         [list(fallback_many.PAIR_WAYS), 4, "как есть"])
проверка("К4: способ годен, только если даёт ту же пару, что свой разборщик",
         [fallback_many._pair_key(fallback_many.PAIR_WAYS[w]("Taça - Fase final: Benfica - Porto")) == ("benfica", "porto")
          for w in ("как есть", "до запятой", "после двоеточия", "после двоеточия, до запятой")], [False, False, True, True])
проверка("способу верим: строк с эфиром не меньше LIVE_MIN", fallback_many.live_way(память[ключ]), "после")
ЗАВТРА = date(2026, 11, 21)
проверка("вторая страница ключа в том же сборе сошлась — счёт строк с эфиром копится",
         [fallback_many.shadow(память, вердикты, САЙТ, АДРЕС_ЗАВТРА, СТРАНИЦА, ЗАВТРА, ПОЯС, свои(СЕТКА, ЗАВТРА)),
          память[ключ][fallback_many.LIVE][fallback_many.LIVE_ROWS]], [True, 8])
не_так = свои(СЕТКА)
не_так[0].live_raw = "ישיר"                       # свой разборщик считает эфиром строку без значка
память2, вердикты2 = {}, {}
fallback_many.shadow(память2, вердикты2, САЙТ, АДРЕС, СТРАНИЦА, ДЕНЬ, ПОЯС, не_так)
проверка("пометка не сошлась хоть у одной строки — страница в памяти есть, способа пометки нет",
         [ключ in память2, память2[ключ][fallback_many.LIVE][fallback_many.LIVE_WAYS], fallback_many.live_way(память2[ключ])],
         [True, [], ""])
fallback_many.shadow(память, вердикты, САЙТ, АДРЕС, СТРАНИЦА, ДЕНЬ, ПОЯС, не_так)
проверка("не сошлась на одной из страниц ключа — способа нет у всего ключа", fallback_many.live_way(память[ключ]), "")
мало = СЕТКА[:2] + СЕТКА[4:5]                     # одна строка с эфиром
память3, вердикты3 = {}, {}
fallback_many.shadow(память3, вердикты3, САЙТ, АДРЕС, страница(мало), ДЕНЬ, ПОЯС, свои(мало))
проверка("строк с эфиром меньше LIVE_MIN — способу пока не верим",
         [память3[ключ][fallback_many.LIVE][fallback_many.LIVE_ROWS], fallback_many.live_way(память3[ключ])], [1, ""])
проверка("память без записи о пометке (сбор до книги 175) — способа нет",
         fallback_many.live_way({fallback_many.NAMES: КАНАЛЫ, fallback_many.WINDOW: [0, 30]}), "")

print("К3. Чтение ставит пометку эфира")
память, вердикты = {}, {}
fallback_many.shadow(память, вердикты, САЙТ, АДРЕС, СТРАНИЦА, ДЕНЬ, ПОЯС, свои(СЕТКА))
прочитано = fallback_many.read(СТРАНИЦА, ДЕНЬ, ПОЯС, память[ключ], АДРЕС, None, САЙТ)
проверка("пометка эфира — у тех же строк, что на странице", [bool(p.live_raw) for p in прочитано], [э for *_x, э in СЕТКА])
проверка("каждая строка помнит, что пометку страницы видели; страница не «слепая»",
         [all((p.extra or {}).get(fallback_read.LIVE_SEEN) == "после" for p in прочитано), fallback_read.blind(прочитано)],
         [True, False])
проверка("К4: у строки с эфиром — пара из названия (способ «как есть»); у строки без эфира пары нет",
         [(p.match_raw, p.league_raw) for p in прочитано[1:3]] + [прочитано[0].match_raw, прочитано[4].match_raw],
         [("ליגת העל בכדורסל: מכבי רעננה - בני הרצליה, מחזור 7", ""), ("ליגה צרפתית: מונאקו - אוקזר, מחזור 11", ""), " ", " "])
одна = dict(память[ключ])
одна[fallback_many.LIVE] = {**одна[fallback_many.LIVE], fallback_many.PAIR: ["после двоеточия, до запятой"]}
по_способу = fallback_many.read(СТРАНИЦА, ДЕНЬ, ПОЯС, одна, АДРЕС, None, САЙТ)
проверка("К4: способ «после двоеточия, до запятой» — пара отдельно, рубрика идёт в лигу",
         (по_способу[2].match_raw, по_способу[2].league_raw), ("מונאקו - אוקזר", "ליגה צרפתית"))
без_способа = fallback_many.read(СТРАНИЦА, ДЕНЬ, ПОЯС, память2[ключ], АДРЕС, None, САЙТ)
проверка("способа пометки нет — строки без пометки, страница «слепая», как до книги 175",
         [any(p.live_raw for p in без_способа), fallback_read.blind(без_способа), len(без_способа)], [False, True, 6])

print("Отсев: помеченная строка — игра и без эталона")
M, ВИДЫ = live.load(), sport.load()
судья = Reference([])


def отсев(programs: list) -> list:
    guess = fallback_read.blind(programs)
    return [pipeline.classify(p, M, ВИДЫ, reference=судья, langs=site_lang.of(САЙТ), guess_site=guess).ok for p in programs]


проверка("с пометкой: эфиры — игры, строка без значка и повтор — нет", отсев(прочитано),
         [False, True, True, True, False, True])
проверка("без способа пометки и без эталона — ни одной игры (как до книги 175)", отсев(без_способа), [False] * 6)

print("Детектор")
проверка("`parse_live` передаёт чтению сайт страницы (язык слов эфира)",
         'setting.get("include"), row["domain"])' in inspect.getsource(parse_live))

print(f"\nИТОГ: зелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

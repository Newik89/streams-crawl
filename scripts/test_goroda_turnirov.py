# -*- coding: utf-8 -*-
r"""Книга 142 (15.11.2026): словарь городов теннисных турниров растёт сам.

Турнир узнаётся по городу. Город турнира, который идёт сейчас, даёт эталон
этого сбора; о турнире, который уже НЕ идёт, разбор не знал ничего — и запись
со значком эфира («TENIS ATP: STOCKHOLM OPEN» у primaplay.ro наутро после
финала) шла на витрину трансляцией. Кроме того, итоговые турниры не узнавались
на иврите, румынском и русском: слова события («Turneul Campionilor») у
эталона другие.

Правила:
  1. `broadcast.cities_of` — города и написания из эталона сбора;
  2. `dictionary.remember_cities` — сервер дописывает их в базу насовсем
     (при каждой заливке, `scripts/games_import.py`), `broadcast.merge_cities`
     — только добавляет;
  3. `scripts/dict_sync.py` возит города в файле словаря,
     `broadcast.learned_cities` читает их на стороне разбора;
  4. `broadcast.tournaments` — город узнаётся по словарю владельца, по
     выученным городам и по эталону сбора; дефис и пробел в написании равны;
     слова события двойного имени — и из `tournament_events`;
  5. `scripts/goroda_turnirov.py` — разовый посев из истории сборов.
В сеть не ходит, база временная. Запуск: python scripts/test_goroda_turnirov.py
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="goroda-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import broadcast, db, dictionary, live, pipeline, sport  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import Reference  # noqa: E402
import dict_sync  # noqa: E402
import games_import  # noqa: E402
import goroda_turnirov  # noqa: E402

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


def матч(league, start="2026-11-16T15:00", **местные):
    return {"sport": "T", "home": "A B.", "away": "C D.", "league": league, "start_kyiv": start, "leagues": местные}


СТОКГОЛЬМ = матч("ATP - SINGLES: Stockholm (Sweden), hard (indoor)", "2026-11-10T15:00",
                 pl="ATP - SINGIEL: Sztokholm (Szwecja), twarda (w hali)",
                 ru="ATP - ОДИНОЧНЫЙ РАЗРЯД: Стокгольм (Швеция), хард (в помещении)")
ТУРИН = матч("ATP - SINGLES: Finals - Turin (World), hard (indoor)",
             hu="ATP - EGYÉNI: Finals - Torino (Világ), kemény (fedettpályás)")
УЭЛЛС = матч("WTA - SINGLES: Finals - Indian Wells (World), hard", "2026-11-15T22:00",
             ru="WTA - ОДИНОЧНЫЙ РАЗРЯД: Итоговый турнир - Индиан Уэллс (Мир), хард")
ПАРИЖ_ШЛЕМ = матч("ATP - SINGLES: French Open (France), clay", "2026-05-28T12:00")
ФУТБОЛ = {"sport": "F", "home": "A", "away": "B", "league": "ATP - SINGLES: Rome (Italy), clay", "start_kyiv": "2026-11-16T15:00"}

print("Города из эталона сбора (`broadcast.cities_of`)")
проверка("тур, город и написания на языках эталона; не теннис и битая запись не в счёт",
         broadcast.cities_of([СТОКГОЛЬМ, ФУТБОЛ, 7, {"sport": "T", "league": "Exhibition"}]),
         {"Stockholm": {"tours": ["ATP"], "words": ["stockholm", "sztokholm", "стокгольм"]}})
проверка("двойное имя — как у эталона, целиком", sorted(broadcast.cities_of([ТУРИН, УЭЛЛС])),
         ["Finals - Indian Wells", "Finals - Turin"])

print("Словарь только растёт (`broadcast.merge_cities`, `dictionary.remember_cities`)")
было = {"Stockholm": {"tours": ["ATP"], "words": ["stockholm"]}}
стало, новых = broadcast.merge_cities(было, {"Stockholm": {"tours": ["WTA"], "words": ["sztokholm"]},
                                             "Vienna": {"tours": ["ATP"], "words": ["vienna", "wien"]}, "Битый": 5})
проверка("новый город добавлен, у известного дописаны тур и написание, прежнее цело, битое пропущено",
         (новых, стало), (1, {"Stockholm": {"tours": ["ATP", "WTA"], "words": ["stockholm", "sztokholm"]},
                             "Vienna": {"tours": ["ATP"], "words": ["vienna", "wien"]}}))
db.init_db()
conn = db.connect()
проверка("база: первая заливка учит города, повторная — ничего нового, пустой эталон словарь не трогает",
         [dictionary.remember_cities(conn, broadcast.cities_of([СТОКГОЛЬМ])),
          dictionary.remember_cities(conn, broadcast.cities_of([СТОКГОЛЬМ])),
          dictionary.remember_cities(conn, broadcast.cities_of([ТУРИН])),
          dictionary.remember_cities(conn, None), sorted(dictionary.learned_cities(conn))],
         [(1, 1), (0, 1), (1, 2), (0, 2), ["Finals - Turin", "Stockholm"]])
проверка("заливка сбора зовёт запоминание городов из эталона",
         "dictionary.remember_cities(conn, broadcast.cities_of(" in inspect.getsource(games_import))

print("Файл словаря возит города (`scripts/dict_sync.py`, `broadcast.learned_cities`)")
файл = TMP / "dictionaries.json"
dict_sync.export(conn, файл)
conn.close()
проверка("выгрузка кладёт раздел в файл, разбор его читает; файла нет или он битый — пусто",
         (sorted(json.loads(файл.read_text(encoding="utf-8"))[broadcast.LEARNED_KEY]),
          broadcast.learned_cities(файл)["Stockholm"]["words"],
          broadcast.learned_cities(TMP / "нет.json"), broadcast.learned_cities(TMP / "t.db")),
         (["Finals - Turin", "Stockholm"], ["stockholm", "sztokholm", "стокгольм"], {}, {}))
os.environ["STREAMS_DB"] = str(TMP / "t2.db")
db.init_db()
другая = db.connect()
dict_sync.load(другая, файл)
проверка("загрузка словаря в другую базу переносит города", sorted(dictionary.learned_cities(другая)),
         ["Finals - Turin", "Stockholm"])
другая.close()

print("Турнир по заголовку (`broadcast.tournaments`, `broadcast.key`)")
ВЫУЧЕНО = {"Stockholm": {"tours": ["ATP"], "words": ["stockholm", "sztokholm", "стокгольм"]},
           "Paris": {"tours": ["ATP"], "words": ["paris", "париж"]}}
без = broadcast.tournaments([ТУРИН, УЭЛЛС], learned={})
со = broadcast.tournaments([ТУРИН, УЭЛЛС], learned=ВЫУЧЕНО)
проверка("турнир, который уже не идёт, узнаётся по выученному городу — и видно, что в эталоне его нет",
         (broadcast.key("TENIS ATP: STOCKHOLM OPEN", без), broadcast.key("TENIS ATP: STOCKHOLM OPEN", со),
          broadcast.key("Теннис. ATP. Стокгольм. Финал", со), broadcast.played(("ATP", "Stockholm"), со)),
         (("", ""), ("ATP", "Stockholm"), ("ATP", "Stockholm"), False))
проверка("дефис и пробел в написании равны: «Индиан-Уэллс» у сайта, «Индиан Уэллс» у эталона",
         (broadcast.key("Теннис. WTA. Итоговый турнир. Индиан-Уэллс. Прямая трансляция", со),
          broadcast.key("WTA Finals, Indian-Wells", со)),
         (("WTA", "Finals - Indian Wells"), ("WTA", "Finals - Indian Wells")))
проверка("слова события из словаря: иврит, румынский — вместе с названным туром; без тура — ничей",
         (broadcast.key("גמר טורניר גמר סבב ה-WTA", со), broadcast.key("Tenis Atp: Turneul Campionilor", со),
          broadcast.key("Turneul Campionilor", со)),
         (("WTA", "Finals - Indian Wells"), ("ATP", "Finals - Turin"), ("", "")))
шлем = broadcast.tournaments([ПАРИЖ_ШЛЕМ], learned=ВЫУЧЕНО)
проверка("большой турнир и другой турнир того же города: «Roland Garros … Paris» — это French Open из эталона, "
         "а не парижский турнир осени",
         broadcast.key("ATP Roland Garros, Paris", шлем), ("ATP", "French Open"))

print("Запись турнира, который уже не идёт, — не трансляция (`pipeline.tournament_whole`, Т4)")
ЭТАЛОН = [ТУРИН] + [матч("CHALLENGER MEN - SINGLES: Sydney (Australia), hard", f"2026-11-16T{4 + i % 6:02d}:00")
                    for i in range(40)]
M, виды = live.load(), sport.load()


def разбор(заголовок, выучено):
    broadcast._LEARNED = выучено                 # разбор читает выученное из файла словаря; здесь — подмена
    p = Program(channel_raw="Prima Sport 4", title=заголовок, start=datetime(2026, 11, 16, 8, 15, tzinfo=KYIV),
                live_raw="live")
    row = pipeline.classify(p, M, виды, reference=Reference(ЭТАЛОН))
    return row.ok


проверка("«TENIS ATP: STOCKHOLM OPEN» со значком эфира: город не выучен — слову сайта верим; выучен, а в эталоне "
         "турнира нет — запись",
         (разбор("TENIS ATP: STOCKHOLM OPEN", {}), разбор("TENIS ATP: STOCKHOLM OPEN", ВЫУЧЕНО)), (True, False))
broadcast._LEARNED = None

print("Разовый посев из истории сборов (`scripts/goroda_turnirov.py`)")
проверка("Г1: по одному сбору раз в N дней, самый новый — всегда",
         goroda_turnirov.pick([("a", "2026-11-15"), ("b", "2026-11-15"), ("c", "2026-11-13"), ("d", "2026-11-11"),
                               ("e", "2026-11-04")], 4), ["a", "d", "e"])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

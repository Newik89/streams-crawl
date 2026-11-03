# -*- coding: utf-8 -*-
r"""Книга 095 (03.11.2026): подпись лиги у сайта против эталона и сторона
пары — имя канала.

Жалобы владельца: #9362 «St Gallen — Lugano» показана как «Чемпионат Дании»
(poverkhnost.tv подписал швейцарский матч датской лигой; словарь честно
перевёл в DENMARK: Superliga, и правило 06.10 «лига другой страны — другая
игра» отбросило верный матч эталона SWITZERLAND: Super League: игра без
метки, «Lugano» ушёл в баскетбольный Lugano Tigers); #9541 «Program Sportiv —
Sport 2» (ipko: заставка канала Sport 2 прочитана как пара).

Правила:
  Л1. `canon.align`: буквы ОБЕИХ сторон твёрдые (`FIRM_SIDE`), подпись лиги
      словарь знает, но страна не та, что у эталона → пара уверенная с
      пометкой `HOW_LETTERS`; `reference_league` отдаёт лигу эталона.
  Л2. Подпись лиги словарю не знакома → как раньше: уверенная пара по буквам,
      пометки нет, лига остаётся сайта.
  Л3. Одна сторона слабее `FIRM_SIDE` при чужой стране → как раньше, «мимо»
      (правило 06.10 цело).
  Л4. `canon.apply`: ярлык-ошибку («Чемпионат Дании. Superliga») к лиге
      эталона не учит; имена команд — учит.
  Л5. `countries_differ`: страны известны и разные → да; пусто с любой
      стороны или стадия той же лиги → нет.
  Л6. `pipeline.channel_side`: сторона = имя канала (без регистра, пробелов и
      знаков) → да; клубный канал, вторую сторону эталон знает → нет.
  Л7. `pipeline.classify` на строке ipko «Sport 2 - Program Sportiv» (канал
      Sport 2) → строка не берётся, причина `CHANNEL_SIDE`; «Futboll:
      Prishtina - Drita» на том же канале — не эта причина.

Запуск: venv\Scripts\python.exe scripts\test_liga_i_kanal.py
"""
from __future__ import annotations

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
TMP = Path(tempfile.mkdtemp(prefix="liga-i-kanal-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")

from app import canon, db, live, pipeline, site_lang, sport  # noqa: E402
from app.parsers import ipko_tv  # noqa: E402
from app.reference import Reference  # noqa: E402

total = green = 0


def check(name: str, ok: bool, got=None) -> None:
    global total, green
    total += 1
    green += bool(ok)
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"   ← {got!r}"))


def ref(home, away, league, when="2026-11-08T15:00", sport="F", fs="2Z4xMLR0"):
    return {"sport": sport, "home": home, "away": away, "league": league,
            "fs_id": fs, "start_kyiv": when}


def game(home, away, league, when="2026-11-08T15:00", sport="F"):
    return {"sport": sport, "home": home, "away": away, "league": league,
            "start_kyiv": when, "entries": []}


СЛОВАРЬ = {"Чемпионат Дании. Superliga": "DENMARK: Superliga"}
ЭТАЛОН = [ref("St. Gallen", "Lugano", "SWITZERLAND: Super League")]

print("Л1. буквы твёрдые, подпись лиги чужой страны → уверенно, лига по эталону")
g = game("St Gallen", "Lugano", "Чемпионат Дании. Superliga")
out = canon.align([g], ЭТАЛОН, СЛОВАРЬ)
check("пара уверенная", len(out["sure"]) == 1 and not out["missed"], out)
check("пометка HOW_LETTERS", g.get("канон_как") == canon.HOW_LETTERS, g.get("канон_как"))
check("лига игры — эталона", canon.reference_league(g, ЭТАЛОН[0]) == "SWITZERLAND: Super League",
      canon.reference_league(g, ЭТАЛОН[0]))
check("label_wrong: да", canon.label_wrong(dict(g, league_canon="DENMARK: Superliga"), ЭТАЛОН[0]))
# кириллица сайта против латиницы эталона — тот же путь (poverkhnost пишет
# «Санкт-Галлен - Лугано»; словарь уже знает оба имени, здесь — буквы)
g = game("St Gallen", "Lugano", "Чемпионат Дании. Superliga", when="2026-11-08T15:30")
out = canon.align([g], ЭТАЛОН, СЛОВАРЬ)
check("время сайта в окне (±3 ч) — тоже уверенно", len(out["sure"]) == 1, out["missed"])

print("Л2. подпись лиги словарю не знакома → как раньше")
g = game("St Gallen", "Lugano", "Швейцарская лига")
out = canon.align([g], ЭТАЛОН, {})
check("пара уверенная, пометки нет", len(out["sure"]) == 1 and not g.get("канон_как"), g.get("канон_как"))
check("лига остаётся сайта", canon.reference_league(g, ЭТАЛОН[0]) == "Швейцарская лига",
      canon.reference_league(g, ЭТАЛОН[0]))

print("Л3. одна сторона слабее при чужой стране → «мимо» (06.10 цело)")
g = game("Velke Hamry", "Brozan", "Чемпионат Дании. Superliga")
out = canon.align([g], [ref("Velke Hamry", "Brozany", "CZECH REPUBLIC: 3. CFL")], СЛОВАРЬ)
check("«Brozan» ~ «Brozany» ниже 95 → «мимо»", len(out["missed"]) == 1, out["sure"])
check("тот же вид спорта обязателен (баскетбол к футболу не идёт)",
      not canon.align([game("St Gallen", "Lugano", "Чемпионат Дании. Superliga", sport="B")],
                      ЭТАЛОН, СЛОВАРЬ)["sure"])

print("Л4. apply: ярлык-ошибку к лиге эталона не учит, имена — учит")
conn = db.connect()
db.init_db(conn)
g = game("St Gallen", "Lugano", "Чемпионат Дании. Superliga")
out = canon.align([g], ЭТАЛОН, СЛОВАРЬ)
canon.apply(conn, out)
aliases = [r[0] for r in conn.execute("SELECT alias FROM league_aliases")]
check("алиас «Чемпионат Дании. Superliga» не выучен", "Чемпионат Дании. Superliga" not in aliases, aliases)
teams = [r[0] for r in conn.execute("SELECT alias FROM team_aliases")]
check("имя «St Gallen» выучено", "St Gallen" in teams, teams)
# подпись без ошибки (словарю незнакома) учится как раньше
g = game("St Gallen", "Lugano", "Швейцарская лига")
canon.apply(conn, canon.align([g], ЭТАЛОН, {}))
aliases = [r[0] for r in conn.execute("SELECT alias FROM league_aliases")]
check("незнакомая подпись «Швейцарская лига» выучена к лиге эталона", "Швейцарская лига" in aliases, aliases)
conn.close()

print("Л5. countries_differ")
check("DENMARK против SWITZERLAND → да",
      canon.countries_differ("DENMARK: Superliga", "SWITZERLAND: Super League"))
check("пусто с одной стороны → нет", not canon.countries_differ("", "SWITZERLAND: Super League"))
check("стадия той же лиги → нет",
      not canon.countries_differ("EUROPE: Champions League", "EUROPE: Champions League - League phase"))
check("ярлык без двоеточия (словарю не знаком) → нет",
      not canon.countries_differ("Superliga", "DENMARK: Superliga"))

print("Л6. channel_side")
check("«Program Sportiv — Sport 2» на канале Sport 2 → да",
      pipeline.channel_side("Sport 2", "Program Sportiv", "Sport 2"))
check("порядок сторон не важен", pipeline.channel_side("Sport 2", "Sport 2", "Program Sportiv"))
check("регистр, пробелы и знаки не важны («SPORT-2»)",
      pipeline.channel_side("SPORT-2", "Program Sportiv", "sport 2"))
check("обычная пара на канале → нет", not pipeline.channel_side("Arena Sport 3", "St Gallen", "Lugano"))
check("пустое имя канала → нет", not pipeline.channel_side("", "Program Sportiv", ""))
клубный = Reference([ref("KB Peja", "Trepca", "KOSOVO: Superliga", sport="B")])
check("клубный канал «KB Peja», вторую сторону эталон знает → нет (матч остаётся)",
      not pipeline.channel_side("KB Peja", "KB Peja", "Trepca", клубный))
check("клубный канал, вторая сторона эталону не знакома → да",
      pipeline.channel_side("KB Peja", "KB Peja", "Program Sportiv", клубный))

print("Л7. classify на строке ipko")
MARKERS = live.load()
SPORTS = sport.load(teams=())


def ipko_row(title: str, channel: str = "sport-2"):
    sample = json.dumps({"shows": [{"title": title, "show_start": 1794488400,
                                    "show_end": 1794495600, "genres": ["futboll"],
                                    "categories": "Sport", "summary": ""}]})
    programs = ipko_tv.parse(
        sample, url=f"https://stargate.ipko.tv/api/titan.tv.WebEpg/GetWebEpgData?channel_id={channel}")
    assert len(programs) == 1, programs
    return programs[0]


# язык сайта — как в сборе (книга 084): стоп-слово «Program Sportiv» лежит
# в словаре не для албанского, и на ipko оно не работало — потому #9541 и
# дошла до витрины; правило 095 от языка не зависит
АЛБАНСКИЙ = site_lang.of("ipko.tv")
check("у ipko.tv известен язык сайта", bool(АЛБАНСКИЙ), АЛБАНСКИЙ)
p = ipko_row("Sport 2 - Program Sportiv")
check("канал строки — Sport 2", p.channel_raw == "Sport 2", p.channel_raw)
row = pipeline.classify(p, MARKERS, SPORTS, {}, {}, None, langs=АЛБАНСКИЙ)
check("строка не берётся, причина — имя канала", (row.ok, row.reason) == (False, pipeline.CHANNEL_SIDE),
      (row.ok, row.reason, row.home, row.away))
check("в очередь не идёт", not row.needs_review, row.needs_review)
row = pipeline.classify(ipko_row("Futboll: Prishtina - Drita"), MARKERS, SPORTS, {}, {}, None,
                        langs=АЛБАНСКИЙ)
check("обычная пара на том же канале — не эта причина", row.reason != pipeline.CHANNEL_SIDE,
      (row.ok, row.reason, row.home, row.away))

print()
print(f"проверок: {total}, зелёных: {green}, красных: {total - green}")
sys.exit(0 if green == total else 1)

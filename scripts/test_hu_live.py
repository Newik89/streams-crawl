# -*- coding: utf-8 -*-
r"""Проверки венгерского эфира и сокращений клубов (разбор 06.10.2026).

Случай: Ferencváros — DVSC, OTP Bank Liga, 10.10 17:00 по Будапешту, M4
Sport — port.hu отдал матч с флагом прямого эфира, а на витрину он не
попал: эфир port.hu считался угаданным, угаданный эфир сверяется с
эталоном, а «DVSC» эталон знает как «Debrecen».

* port.hu — эфир по флагам сайта (`is_live_mp`, `is_repeat`), угадывание
  первым показом пары — только у строк, где оба флага молчат;
* пара port.hu — стадия через запятую к именам команд не прилипает;
* `data/aliases.json`, раздел «_клубы целиком» — DVSC, FTC, Puskás
  Akadémia, West Bromwich, OB, R. Racing Club сводятся с именами эталона,
  а чужие клубы и вторые составы — нет; «_сборные целиком» — румынские и
  французские имена сборных (Scotia, Insulele Feroe, Lettonie). Все — из
  строк обхода #205, которые английский эталон не узнавал.

В сеть не ходит, базы не трогает. Запуск:

    python scripts/test_hu_live.py

Выход 0 — все проверки зелёные.
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

# своя пустая база: разбор не должен подтянуть имена из рабочей
os.environ["STREAMS_DB"] = str(Path(tempfile.mkdtemp(prefix="hu-test-")) / "none.db")

import parse_live  # noqa: E402
from app import live, names, pipeline, sport  # noqa: E402
from app.parsers import port_hu  # noqa: E402

BUDAPEST = ZoneInfo("Europe/Budapest")

passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def show(when, title, episode, live_mp=None, repeat=None):
    """Передача в виде ответа ручки port.hu; флаг None — ключа нет вовсе."""
    item = {"start_ts": int(when.timestamp()),
            "start_time": when.strftime("%H:%M"),
            "title": title, "episode_title": episode,
            "short_description": ""}
    if live_mp is not None:
        item["is_live_mp"] = live_mp
    if repeat is not None:
        item["is_repeat"] = repeat
    return item


def answer(channel: str, *programs) -> str:
    return json.dumps({"1791583200": {"channels": [
        {"id": f"tvchannel-{channel}", "programs": list(programs)}]}})


def at(day, hh, mm=0):
    return datetime(2026, 10, day, hh, mm, tzinfo=BUDAPEST)


def by_time(programs):
    return {p.start.astimezone(BUDAPEST).strftime("%d %H:%M"): p for p in programs}


# ── port.hu: эфир по флагам сайта ───────────────────────────────────────────

print("port.hu — флаги эфира")

# как в обходе #205: у каждого дня свой ответ ручки, и утренний повтор
# 11.10 — единственный показ пары в своём файле
m4 = by_time(port_hu.parse(answer(
    "290",
    show(at(10, 17), "OTP Bank Liga", "Ferencvárosi TC - DVSC mérkőzés",
         live_mp=True, repeat=False)), url="https://port.hu/tvapi"))
m4.update(by_time(port_hu.parse(answer(
    "290",
    show(at(11, 8, 50), "OTP Bank Liga", "Ferencvárosi TC - DVSC mérkőzés",
         live_mp=False, repeat=True)), url="https://port.hu/tvapi")))
live_row, repeat_row = m4["10 17:00"], m4["11 08:50"]
check("port.hu_is_live_mp: прямой эфир по флагу сайта, не угаданный",
      live_row.live_raw == "élő" and not live_row.extra.get("live_guess")
      and live_row.channel_raw == "M4 Sport"
      and live_row.match_raw == "Ferencvárosi TC - DVSC",
      (live_row.live_raw, live_row.extra, live_row.match_raw))
check("port.hu_is_repeat: повтор эфиром не бывает и не угадывается",
      repeat_row.live_raw == "" and not repeat_row.extra.get("live_guess"),
      (repeat_row.live_raw, repeat_row.extra))

markers, sports = live.load(), sport.load()
rows = {r.program.start.astimezone(BUDAPEST).strftime("%d %H:%M"): r
        for r in pipeline.run(list(m4.values()), markers, sports)}
check("port.hu_эфир_по_флагу_проходит_отсев: футбол, пара команд",
      rows["10 17:00"].ok and rows["10 17:00"].sport == "F"
      and (rows["10 17:00"].home, rows["10 17:00"].away)
      == ("Ferencvárosi TC", "DVSC"),
      (rows["10 17:00"].ok, rows["10 17:00"].reason, rows["10 17:00"].sport))
check("port.hu_повтор_по_флагу_в_игры_не_идёт",
      not rows["11 08:50"].ok, rows["11 08:50"].reason)
# угаданным строку делает только список доменов без флага в parse_live
# (`REPEAT_GUESS_DOMAINS`), сам разбор её угаданной не помечает
check("port.hu_честная_строка_угадана_только_по_списку_доменов",
      parse_live.guessed("port.hu", rows["10 17:00"])
      == ("port.hu" in parse_live.REPEAT_GUESS_DOMAINS))

spiler = by_time(port_hu.parse(answer(
    "305",
    show(at(10, 13, 20), "Labdarúgás: Premier League", "Arsenal - Leeds United",
         live_mp=False, repeat=False),
    show(at(10, 23, 0), "Labdarúgás: Premier League", "Arsenal - Leeds United",
         live_mp=False, repeat=False)), url="https://port.hu/tvapi"))
first, late = spiler["10 13:20"], spiler["10 23:00"]
check("port.hu_флаги_молчат: эфир — первый показ пары, помечен угаданным",
      first.live_raw == "élő" and first.extra.get("live_guess")
      and first.channel_raw == "Spíler1 TV",
      (first.live_raw, first.extra))
check("port.hu_флаги_молчат: поздний показ той же пары — не эфир",
      late.live_raw == "" and not late.extra.get("live_guess"),
      (late.live_raw, late.extra))
guess_row = next(r for r in pipeline.run([first], markers, sports))
check("port.hu_угаданная_строка_сверяется_с_эталоном (parse_live.guessed)",
      parse_live.guessed("port.hu", guess_row))

old = by_time(port_hu.parse(answer(
    "290",
    show(at(10, 17), "OTP Bank Liga", "Paksi FC - MTK Budapest mérkőzés"),
    show(at(11, 9), "OTP Bank Liga", "Paksi FC - MTK Budapest mérkőzés")),
    url="https://port.hu/tvapi"))
check("port.hu_без_ключей_флагов: как раньше — первый показ пары",
      old["10 17:00"].live_raw == "élő" and old["10 17:00"].extra.get("live_guess")
      and old["11 09:00"].live_raw == "",
      ({k: (p.live_raw, p.extra) for k, p in old.items()}))
check("port.hu_флаг_is_live_«идёт_сейчас»_эфиром_не_считается",
      by_time(port_hu.parse(answer("305", {**show(
          at(10, 6), "Favágók", "Mindenki a fedélzetre!", live_mp=False,
          repeat=True), "is_live": True}), url="x"))["10 06:00"].live_raw == "")


# ── port.hu: стадия через запятую ───────────────────────────────────────────

print("port.hu — пара без стадии")

pairs = by_time(port_hu.parse(answer(
    "290",
    show(at(9, 19, 45), "Női labdarúgó világbajnoki-selejtező: "
         "Magyarország-Hollandia mérkőzés",
         "Magyarország - Hollandia mérkőzés, rájátszás", live_mp=True),
    show(at(10, 18, 45), "Kézilabda: Bajnokok Ligája nők",
         "Csoportkör, Brest - FTC-Toyota Kovács", live_mp=True)), url="x"))
check("port.hu_стадия_после_пары: «Hollandia mérkőzés, rájátszás» → «Hollandia»",
      pairs["09 19:45"].match_raw == "Magyarország - Hollandia",
      pairs["09 19:45"].match_raw)
check("port.hu_стадия_перед_парой: «Csoportkör, Brest» → «Brest»",
      pairs["10 18:45"].match_raw == "Brest - FTC-Toyota Kovács",
      pairs["10 18:45"].match_raw)


# ── сокращения клубов: data/aliases.json, «_клубы целиком» ──────────────────

print("Сокращения клубов")

for mine, ref in (("DVSC", "Debrecen"),               # port.hu ⇒ эталон
                  ("Ferencvárosi TC", "Ferencvaros"),
                  ("FTC", "Ferencvaros"),             # tvarenasport, digisport
                  ("Puskás Akadémia FC", "Puskas Academy"),
                  ("West Bromwich Albion", "West Brom"),
                  ("West Bromwich", "West Brom"),     # port.hu, Match4
                  ("OB", "Odense"),                   # allente.no
                  ("R. Racing Club", "Racing Santander"),  # movistarplus.es
                  ("Scotia", "Scotland"),             # digisport.ro
                  ("Insulele Feroe", "Faroe Islands"),
                  ("Lettonie W", "Latvia W")):        # programme-tv.net
    check(f"сокращение_одна_команда: {mine} = {ref}",
          names.same_team(mine, ref), names.similarity(mine, ref))

for mine, ref in (("FTC", "Ferencvaros II"),           # второй состав — стена
                  ("DVSC", "Debrecen W"),             # женская команда — стена
                  ("DVSC Skyline", "Debrecen"),        # только имя ЦЕЛИКОМ
                  ("West Ham", "West Brom"),
                  ("OB", "Odense W"),
                  ("Puskás Akadémia FC", "Puskas Academy II")):
    check(f"сокращение_не_цепляет_чужих: {mine} ≠ {ref}",
          not names.same_team(mine, ref), names.similarity(mine, ref))


print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, красных: {len(failed)}")
for name in failed:
    print("  красная:", name)
sys.exit(1 if failed else 0)

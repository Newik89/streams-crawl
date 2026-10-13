# -*- coding: utf-8 -*-
r"""Решения владельца и починки, которые до книги случаев (13.10.2026) не
охранял ни один тест: перечень — реестр книги, случаи 047–049. Каждая
проверка — одно решение, с датой и номером жалобы, чтобы при красном было
видно, ЧЬЁ слово нарушено.

1. Настройки обхода — в плане `data/crawl_plan.json` (его пересобирает и
   пушит сервер: красный на GitHub после такого push — сигнал, что кнопка
   или скрипт откатили решение владельца, как cosmotetv 22.09).
2. Сроки и частоты — в коде и workflow.
3. Разбор и сверка — починки по жалобам (#4209, #4597, #3880, #3785…).

В сеть не ходит:
    python scripts/test_resheniya.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import canon, health, leagues, live, names  # noqa: E402
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


PLAN = json.loads((ROOT / "data" / "crawl_plan.json").read_text(encoding="utf-8"))
SITES = {s["domain"]: s for s in PLAN["sources"]}


def адреса(домен: str) -> dict[str, str]:
    return {c.get("name") or "": c.get("pattern") or "" for c in SITES[домен].get("channels") or []}


print("1. настройки обхода (план)")
проверка("окно обхода — не больше 6 дней вперёд (01.09)", PLAN["days"] <= 6, True)
проверка("Sport Klub — только каналы 1–10 (16.09)",
         sorted(SITES["sportklub.hr"]["include"]),
         sorted(f"Sport Klub {n}" for n in range(1, 11)))
проверка("liveonsat выключен (22.09)", [d for d in SITES if "liveonsat" in d], [])
проверка("beinsports.com не трогаем до слова владельца (ОТЛОЖЕНО ⛔)",
         [d for d in SITES if d.removeprefix("www.") == "beinsports.com"], [])
проверка("ORF KIDS выключен (26.09)",
         [c for c in SITES["tv.orf.at"]["include"] if "KIDS" in c.upper()], [])
проверка("Diema Xtra выключен (06.10)",
         [c for c in SITES["diemaxtra.nova.bg"]["include"] if "xtra" in c.lower()], [])
проверка("RTP2 — по ручке tv/8, номер 2 мёртв (22.09)",
         "/list-grid/tv/8/" in адреса("rtp.pt").get("RTP2", ""), True)
проверка("cosmotetv.gr — ручка EPG (03.10: пересборка 22.09 её откатила, 11 дней пусто)",
         any("mwapi-prod.cosmotetvott.gr" in u for u in адреса("cosmotetv.gr").values()), True)
проверка("cosmotetv.gr — 16 каналов Magenta (03.10)",
         len([c for c in SITES["cosmotetv.gr"]["include"] if c.startswith("Magenta Sport")]), 16)
проверка("«M+ Deportes 7» не убирать (06.10)",
         "M+ Deportes 7" in SITES["movistarplus.es"]["include"], True)
проверка("beinsports.com.tr — только по кнопке (08.10)",
         bool(SITES["beinsports.com.tr"].get("manual_only")), True)

print("2. сроки и частоты")
проверка("«устарело» — через 12 часов (06.10)", health.STALE_HOURS, 12)
alive = (ROOT / ".github" / "workflows" / "alive.yml").read_text(encoding="utf-8")
проверка("«Сервер жив?» — раз в 3 часа (13.10)",
         re.findall(r'cron:\s*"([^"]+)"', alive), ["17 */3 * * *"])
crawl = (ROOT / ".github" / "workflows" / "crawl.yml").read_text(encoding="utf-8")
проверка("архив страниц сбора — 3 дня (29.09: хранилище Actions)",
         re.findall(r"retention-days:\s*(\d+)", crawl), ["3"])
pins = (ROOT / "requirements-crawl.txt").read_text(encoding="utf-8")
проверка("selectolax закреплён ниже 1.0 (03.10: 1.0.0 уронила разбор #172)",
         re.search(r"^selectolax==0\.", pins, re.M) is not None, True)

print("3. разбор и сверка — починки по жалобам")
M = live.load()


def эфир(заголовок: str, live_raw: str) -> bool:
    return live.check(Program(channel_raw="TVCG 1", title=заголовок, live_raw=live_raw,
                              start=datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)), M).ok


проверка("rtcg: «prenos» — эфир (#4209, 03.10)",
         bool(M.found(M.live, "prenos")) and not M.found(M.not_live, "prenos"), True)
проверка("rtcg: «odloženi prenos» — запись, не эфир (#4209)",
         эфир("Crna Gora - Jermenija", "odloženi prenos"), False)
проверка("err.ee: «otseülekanne» — эфир (03.10)", bool(M.found(M.live, "otseülekanne")), True)
проверка("теннис: W у игрока — не пол, «Kraus W» = эталонный «Kraus S.» (#4597, 04.10)",
         canon._pair_score({"home": "Kraus W", "away": "Zheng", "sport": "T"},
                           {"home": "Kraus S.", "away": "Zheng W."}) >= 85, True)
проверка("футбол: W — пол, мужская пара не сходится с женской",
         canon._pair_score({"home": "Poland", "away": "Belgium", "sport": "F"},
                           {"home": "Poland W", "away": "Belgium W"}), 0)
проверка("cyta «UNDER - 21» — возраст U21 (25.09)",
         names.category("Cyprus UNDER - 21 Greece UNDER - 21"), "U21")
проверка("«Молодежные сборные» — U21, не U19 (#3880, 27.09)",
         leagues.category("Молодежные сборные"), "U21")
проверка("«Юношеская лига» — U19", leagues.category("Юношеская лига УЕФА"), "U19")
проверка("иврит: הכוכב האדום בלגרד — Crvena Zvezda (#3785, 26.09)",
         names.same_team("הכוכב האדום בלגרד", "Crvena Zvezda"), True)
проверка("иврит: שבדיה — Sweden (#3885, 27.09)", names.to_english("שבדיה"), "Sweden")

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

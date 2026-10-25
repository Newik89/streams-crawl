# -*- coding: utf-8 -*-
r"""Один эфир на соседних каналах (книга 082, 25.10.2026): у сайта без
честного флага эфира Al Kass Eight начал трансляцию матча 17:30 в 17:00, а
Al Kass One — в 17:30. `parse_live.nearest_shows` (правило 3, 13.10) снимал
Eight как запись: дальше `SAME_SHOW` (15 мин) от ближайшего показа.
Правило 4 (25.10): если лучший показ тоже угадан, все показы пары, начатые в
окне эфира (от `LIVE_SHOW_BEFORE` до начала матча до `LIVE_SHOW_AFTER`
после), — один эфир, не записи.

Что сторожится:

1. два угаданных показа в окне эфира (17:00 и 17:30 при матче 17:30) — оба
   остаются;
2. показ раньше окна (15:30) и показ позже окна (17:50) — записи, как в
   правиле 3;
3. Rai Sport 17:25 при матче 19:15 (книга, 13.10) — по-прежнему запись;
4. movistar Al Ittihad — Al Shabab (книга 051): показ 19:55 при матче 21:00
   — за окном (65 мин), снят, как и раньше;
5. честный лучший показ 19:55 и угаданная студия 19:30 (правило 1, 20.10)
   — студия снята: правило 4 при честном лучшем показе не действует;
6. одновременный эфир (17:30 и 17:40) — оба, как в правиле 3.

В сеть не ходит, база не нужна:

    python scripts/test_odin_pokaz_dva_kanala.py

Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.gettempdir()) / "odin-pokaz-none.db"))

import parse_live  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✗ {имя}: вышло {вышло!r}, ждали {ждём!r}")


def когда(день: str, часы: str) -> datetime:
    return datetime.fromisoformat(f"{день}T{часы}").replace(tzinfo=KYIV)


def показ(канал: str, часы: str, честный: bool = False, день: str = "2026-10-20"):
    """Строка сайта, как её видит `nearest_shows`: канал, начало, флаг."""
    return ("alkass.net", SimpleNamespace(
        channel=канал, start_kyiv=когда(день, часы), честный=честный,
        home="Egypt", away="Kuwait", sport="F"))


def оставшиеся(показы: list, матч: str, день: str = "2026-10-20") -> list[str]:
    """Каналы, которые `nearest_shows` оставил эфиром (по времени)."""
    kick = когда(день, матч)
    kept, _gone = parse_live.nearest_shows(
        показы, kickoff_of=lambda r: kick,
        guessed_of=lambda domain, r: not r.честный,
        key_of=lambda domain, r: (domain, r.sport, r.home, r.away))
    return [r.channel for _d, r in sorted(kept, key=lambda x: x[1].start_kyiv)]


print("1. Al Kass: два угаданных показа в окне эфира — оба эфир")
проверка("Eight 17:00 и One 17:30 при матче 17:30 → оба остаются",
         оставшиеся([показ("Al Kass Eight", "17:00"), показ("Al Kass One", "17:30")], "17:30"),
         ["Al Kass Eight", "Al Kass One"])
проверка("показ за час до матча (16:30 при 17:30) — край окна, остаётся",
         оставшиеся([показ("Al Kass Eight", "16:30"), показ("Al Kass One", "17:30")], "17:30"),
         ["Al Kass Eight", "Al Kass One"])

print("2. Показы вне окна эфира — записи, как в правиле 3")
проверка("показ за два часа до матча (15:30) снят",
         оставшиеся([показ("Al Kass Eight", "15:30"), показ("Al Kass One", "17:30")], "17:30"),
         ["Al Kass One"])
проверка("показ через 20 мин после начала (17:50) снят",
         оставшиеся([показ("Al Kass One", "17:30"), показ("Al Kass Four", "17:50")], "17:30"),
         ["Al Kass One"])

print("3. Прежние случаи книги не меняются")
проверка("Rai Sport 17:25 при матче 19:15 (13.10) — запись",
         оставшиеся([показ("Rai Sport", "17:25", день="2026-10-13"),
                     показ("Rai 2", "19:05", день="2026-10-13")], "19:15", день="2026-10-13"),
         ["Rai 2"])
проверка("movistar 19:55 при матче 21:00 (книга 051, 65 мин) — снят",
         оставшиеся([показ("M+ Liga de Campeones", "19:55", день="2026-10-16"),
                     показ("M+ Vamos", "20:55", день="2026-10-16")], "21:00", день="2026-10-16"),
         ["M+ Vamos"])
проверка("честный эфир 19:55 и угаданная студия 19:30 (20.10) — студия снята",
         оставшиеся([показ("TV 2 Sport", "19:30"), показ("TV 2 Sport X", "19:55", честный=True)],
                    "20:00"),
         ["TV 2 Sport X"])
проверка("одновременный эфир 17:30 и 17:40 (правило 3) — оба",
         оставшиеся([показ("Al Kass One", "17:30"), показ("Al Kass Four", "17:40")], "17:30"),
         ["Al Kass One", "Al Kass Four"])

print(f"\nзелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

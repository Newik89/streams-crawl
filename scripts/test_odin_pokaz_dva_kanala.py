# -*- coding: utf-8 -*-
r"""Один эфир на соседних каналах (книга 082, 25.10.2026): у сайта без
честного флага эфира Al Kass Eight начал трансляцию матча 17:30 в 17:00, а
Al Kass One — в 17:30. `parse_live.nearest_shows` (правило 3, 13.10) снимал
Eight как запись: дальше `SAME_SHOW` (15 мин) от ближайшего показа.
Правило 4 (25.10): если лучший показ тоже угадан, показ пары на ДРУГОМ
канале, начатый в окне эфира (от `LIVE_SHOW_BEFORE` до начала матча до
`LIVE_SHOW_AFTER` после) с ТЕМ ЖЕ заголовком передачи, — тот же эфир; оба
помечаются `same_show`, и фильтр позднего показа (`late_show`) их не
трогает. Другой заголовок или тот же канал раньше матча — предматчевая
студия (movistar «Previa»), запись, как раньше.

Что сторожится:

1. два угаданных показа на разных каналах в окне эфира (17:00 и 17:30 при
   матче 17:30) — оба остаются и помечены `same_show`;
2. `late_show`: One 17:30 после Eight 17:00 — не поздний показ (проверка на
   сборе #339: без этого настоящий показ снимался как поздний);
3. другая передача — студия movistar «Previa» 21:30 перед матчем 21:54 —
   снята и на том же канале (M+ LALIGA), и на соседнем с другим
   заголовком (M+ LALIGA HDR): тот же эфир — это та же передача;
4. показ раньше окна (15:30) и показ позже окна (17:50) — записи;
5. Rai Sport 17:25 при матче 19:15 (книга, 13.10) — по-прежнему запись;
6. movistar Al Ittihad — Al Shabab (книга 051): показ 19:55 при матче 21:00
   — за окном (65 мин), снят, как и раньше;
7. честный лучший показ 19:55 и угаданная студия 19:30 (правило 1, 20.10)
   — студия снята: правило 4 при честном лучшем показе не действует;
8. одновременный эфир (17:30 и 17:40) — оба, как в правиле 3.

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
САЙТ = "alkass.net"
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


def показ(канал: str, часы: str, честный: bool = False, день: str = "2026-10-20",
         заголовок: str = "Gulf U-17 Cup: Egypt - Kuwait"):
    """Строка сайта, как её видят `nearest_shows` и `late_show`: канал,
    начало, заголовок передачи, пометка эфира (честная — `site_flag`,
    угаданная — `live_guess`)."""
    extra = {"site_flag": "live"} if честный else {"live_guess": True}
    return (САЙТ, SimpleNamespace(
        start_kyiv=когда(день, часы), home="Egypt", away="Kuwait", sport="F",
        program=SimpleNamespace(channel_raw=канал, title=заголовок, extra=extra)))


def оставшиеся(показы: list, матч: str, день: str = "2026-10-20") -> list[str]:
    """Каналы, которые `nearest_shows` оставил эфиром (по времени)."""
    kick = когда(день, матч)
    kept, _gone = parse_live.nearest_shows(
        показы, kickoff_of=lambda r: kick, guessed_of=parse_live.guessed)
    return [r.program.channel_raw for _d, r in sorted(kept, key=lambda x: x[1].start_kyiv)]


def поздние(показы: list) -> list[str]:
    """Каналы, которые `late_show` снял бы как поздний показ."""
    firsts = parse_live.first_shows(показы)
    return [r.program.channel_raw for d, r in показы
            if parse_live.late_show(d, r, firsts) is not None]


print("1. Al Kass: два угаданных показа на разных каналах в окне эфира — оба эфир")
пара = [показ("Al Kass Eight", "17:00"), показ("Al Kass One", "17:30")]
проверка("Eight 17:00 и One 17:30 при матче 17:30 → оба остаются",
         оставшиеся(пара, "17:30"), ["Al Kass Eight", "Al Kass One"])
проверка("…оба помечены same_show",
         [r.program.extra.get("same_show") for _d, r in пара], [True, True])
проверка("показ за час до матча (16:30 при 17:30) — край окна, остаётся",
         оставшиеся([показ("Al Kass Eight", "16:30"), показ("Al Kass One", "17:30")], "17:30"),
         ["Al Kass Eight", "Al Kass One"])

print("2. Фильтр позднего показа тот же эфир не трогает")
проверка("One 17:30 после Eight 17:00 — не поздний показ", поздние(пара), [])
проверка("а без правила 4 (пометки нет) One 17:30 — поздний показ, как раньше",
         поздние([показ("Al Kass Eight", "17:00"), показ("Al Kass One", "17:30")]), ["Al Kass One"])
проверка("повтор в 23:00 на третьем канале — поздний показ по-прежнему",
         поздние(пара + [показ("Al Kass Four", "23:00")]), ["Al Kass Four"])

print("3. Тот же канал раньше матча — студия, запись (сбор #339, movistar «Previa»)")
проверка("M+ LALIGA 21:30 и M+ LALIGA 21:54 при матче 22:00 → остаётся 21:54",
         оставшиеся([показ("M+ LALIGA", "21:30"), показ("M+ LALIGA", "21:54")], "22:00"),
         ["M+ LALIGA"])
студия = [показ("DAZN LALIGA 2", "16:45"), показ("DAZN LALIGA 2", "17:10")]
kept = оставшиеся(студия, "17:15")
проверка("DAZN LALIGA 2 16:45 (Previa) при матче 17:15 снят, 17:10 остался",
         [r.program.channel_raw + " " + r.start_kyiv.strftime("%H:%M")
          for _d, r in parse_live.nearest_shows(студия, kickoff_of=lambda r: когда("2026-10-20", "17:15"),
                                                guessed_of=parse_live.guessed)[0]],
         ["DAZN LALIGA 2 17:10"])
проверка("…пометки same_show у них нет",
         [r.program.extra.get("same_show") for _d, r in студия], [None, None])
сосед = [показ("M+ LALIGA HDR", "21:30", заголовок="La Casa del Fútbol Previa: Sevilla FC - CA Osasuna"),
         показ("M+ LALIGA", "21:54", заголовок="LALIGA EA SPORTS: Sevilla FC - CA Osasuna")]
проверка("студия с ДРУГИМ заголовком на соседнем канале (M+ LALIGA HDR 21:30) снята — другая передача",
         оставшиеся(сосед, "22:00"), ["M+ LALIGA"])
проверка("…и same_show никому не ставится", [r.program.extra.get("same_show") for _d, r in сосед], [None, None])

print("4. Показы вне окна эфира — записи, как в правиле 3")
проверка("показ за два часа до матча (15:30) снят",
         оставшиеся([показ("Al Kass Eight", "15:30"), показ("Al Kass One", "17:30")], "17:30"),
         ["Al Kass One"])
проверка("показ через 20 мин после начала (17:50) снят",
         оставшиеся([показ("Al Kass One", "17:30"), показ("Al Kass Four", "17:50")], "17:30"),
         ["Al Kass One"])

print("5. Прежние случаи книги не меняются")
проверка("Rai Sport 17:25 при матче 19:15 (13.10) — запись",
         оставшиеся([показ("Rai Sport", "17:25", день="2026-10-13"),
                     показ("Rai 2", "19:05", день="2026-10-13")], "19:15", день="2026-10-13"),
         ["Rai 2"])
проверка("movistar 19:55 при матче 21:00 (книга 051, 65 мин) — снят",
         оставшиеся([показ("M+ Liga de Campeones", "19:55", день="2026-10-16"),
                     показ("M+ Vamos", "20:55", день="2026-10-16")], "21:00", день="2026-10-16"),
         ["M+ Vamos"])
проверка("честный эфир 19:55 и угаданная студия 19:30 на другом канале (20.10) — студия снята",
         оставшиеся([показ("TV 2 Sport", "19:30"), показ("TV 2 Sport X", "19:55", честный=True)],
                    "20:00"),
         ["TV 2 Sport X"])
проверка("одновременный эфир 17:30 и 17:40 (правило 3) — оба",
         оставшиеся([показ("Al Kass One", "17:30"), показ("Al Kass Four", "17:40")], "17:30"),
         ["Al Kass One", "Al Kass Four"])

print(f"\nзелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

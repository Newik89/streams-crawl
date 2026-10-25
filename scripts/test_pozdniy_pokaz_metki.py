# -*- coding: utf-8 -*-
r"""Метки из эталона у показа вне окна эфира и иврит в индексе эталона
(книга 080, 25.10.2026). После выкладки правила 5 «метки из эталона» (книга
079) на витрине остался матч WNBA второй строкой без W: sport5 ставит
«גולדן סטייט — אטלנטה» на 03:00 при начале 02:00 (на час позже, со значком
эфира). `Reference.confirm` такому показу верно отвечает None (не окно эфира),
но метку пара заслуживает: в ±3 ч эталон знает её только с W.

Что сторожится:

1. `Reference.late_marks`: показ вне окна эфира, пара без меток сошлась с
   записью эталона без её меток, запись одна, вид спорта тот же → метка;
   `confirm` при этом — None, как раньше (эфиром показ не становится);
   без вида спорта, с другим видом, при взрослом матче той же пары рядом,
   при двух записях с метками, у строки со своими метками, дальше ±3 ч —
   None;
2. иврит в индексе кандидатов (`reference._words`, костяк согласных): раньше
   «גולדן סטייט» не находила «Golden State» вовсе, и до правил `confirm`
   ивритская строка без словаря не доходила; теперь правило 5 в окне эфира
   и `late_marks` вне окна ей отвечают;
3. `pipeline.classify`: метка дописана к именам, `by_reference` =
   `LATE_MARKS_HOW`; в окне эфира — прежний путь (`MARKS_HOW`).

В сеть не ходит, база не нужна:

    python scripts/test_pozdniy_pokaz_metki.py

Выход 0 — все проверки зелёные.
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
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.gettempdir()) / "pozdniy-pokaz-none.db"))

from app import live, pipeline, sport  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import LATE_MARKS_HOW, MARKS_HOW, Reference  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
MARKERS = live.load()
SPORTS = sport.load(teams=())
зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✗ {имя}: вышло {вышло!r}, ждали {ждём!r}")


def матч(вид: str, дом: str, гость: str, когда: str, **написания) -> dict:
    return {"sport": вид, "home": дом, "away": гость, "league": "",
            "fs_id": (дом[:4] + гость[:4]).replace(" ", ""),
            "start_kyiv": когда, "names": написания}


def момент(когда: str) -> datetime:
    return datetime.fromisoformat(когда)


def поздно(эталон: Reference, дом: str, гость: str, когда: str, вид: str = ""):
    got = эталон.late_marks(дом, гость, момент(когда), вид)
    if got is None:
        return None
    return (got.entry["home"], got.entry["away"], got.how, got.swapped, got.marks)


def эфир(эталон: Reference, дом: str, гость: str, когда: str, вид: str = ""):
    got = эталон.confirm(дом, гость, момент(когда), вид)
    return None if got is None else (got.how, got.marks)


# ── эталоны ──────────────────────────────────────────────────────────────────
#: WNBA 27.10 (сбор #339): финал в 02:00, рядом НБА в 04:00 с тем же словом
WNBA = Reference([
    матч("B", "Golden State Valkyries W", "Atlanta Dream W", "2026-10-27T02:00",
         el=["Γκόλντεν Στέιτ Βάλκιριζ Γ", "Ατλάντα Ντρημ Γ"],
         tr=["Golden State Valkyries K", "Atlanta Dream K"]),
    матч("B", "Denver Nuggets", "Golden State Warriors", "2026-10-27T04:00"),
])
#: взрослый и женский матч одной пары в один вечер — метку не гадаем
ОБА = Reference([матч("F", "Poland W", "Belgium W", "2026-10-24T19:00"),
                 матч("F", "Poland", "Belgium", "2026-10-24T19:00")])
#: U19 и U21 одной пары — не гадаем
ДВА_ВОЗРАСТА = Reference([матч("F", "Serbia U19", "Bulgaria U19", "2026-10-24T19:00"),
                          матч("F", "Serbia U21", "Bulgaria U21", "2026-10-24T19:00")])

# ═════════════════════════════════════════════════════════════════════════════
print("1. Reference.late_marks — показ вне окна эфира")
проверка("sport5 03:00 при матче 02:00 → метка W, ответ «показ вне окна»",
         поздно(WNBA, "Golden State Valkyries", "Atlanta Dream", "2026-10-27T03:00", "B"),
         ("Golden State Valkyries W", "Atlanta Dream W", LATE_MARKS_HOW, False, "W"))
проверка("…а `confirm` тому же показу — None, как раньше (не окно эфира)",
         эфир(WNBA, "Golden State Valkyries", "Atlanta Dream", "2026-10-27T03:00", "B"), None)
проверка("обратный порядок сторон → swapped",
         поздно(WNBA, "Atlanta Dream", "Golden State Valkyries", "2026-10-27T03:00", "B")[3], True)
проверка("показ за два часа до матча (00:00) — тоже метка",
         поздно(WNBA, "Golden State Valkyries", "Atlanta Dream", "2026-10-27T00:00", "B")[4], "W")
проверка("вид спорта не назван → None (обязателен)",
         поздно(WNBA, "Golden State Valkyries", "Atlanta Dream", "2026-10-27T03:00"), None)
проверка("другой вид спорта (футбол) → None",
         поздно(WNBA, "Golden State Valkyries", "Atlanta Dream", "2026-10-27T03:00", "F"), None)
проверка("дальше ±3 ч (06:00) → None",
         поздно(WNBA, "Golden State Valkyries", "Atlanta Dream", "2026-10-27T06:00", "B"), None)
проверка("строка со своей меткой → None",
         поздно(WNBA, "Golden State Valkyries W", "Atlanta Dream W", "2026-10-27T03:00", "B"), None)
проверка("имена не сходятся (Denver — Atlanta) → None",
         поздно(WNBA, "Denver Nuggets", "Atlanta Dream", "2026-10-27T03:00", "B"), None)
проверка("взрослый матч той же пары рядом → None, метку не гадаем",
         поздно(ОБА, "Poland", "Belgium", "2026-10-24T20:30", "F"), None)
проверка("две записи с метками (U19 и U21) → None",
         поздно(ДВА_ВОЗРАСТА, "Serbia", "Bulgaria", "2026-10-24T20:30", "F"), None)
проверка("в окне эфира правило 5 `confirm` главнее: «метки из эталона»",
         эфир(WNBA, "Golden State Valkyries", "Atlanta Dream", "2026-10-27T02:00", "B"),
         (MARKS_HOW, "W"))

print("2. Иврит в индексе кандидатов эталона")
проверка("«גולדן סטייט — אטלנטה» 03:00 → метка W (костяк согласных нашёл запись)",
         поздно(WNBA, "גולדן סטייט", "אטלנטה", "2026-10-27T03:00", "B")[2:5],
         (LATE_MARKS_HOW, False, "W"))
проверка("та же ивритская пара в 02:00 → правило 5 `confirm`: «метки из эталона»",
         эфир(WNBA, "גולדן סטייט", "אטלנטה", "2026-10-27T02:00", "B"), (MARKS_HOW, "W"))
проверка("ивритская строка про другой матч (דנבר — גולדן סטייט, НБА 04:00) → «пара», без меток",
         эфир(WNBA, "דנבר", "גולדן סטייט", "2026-10-27T04:00", "B"), ("пара", ""))


# ═════════════════════════════════════════════════════════════════════════════
def строка(заголовок: str, когда: str, *, пара: str, лига: str = "WNBA",
           вид: str = "basketball", канал: str = "Teledeporte"):
    program = Program(channel_raw=канал, title=заголовок,
                      start=момент(когда).replace(tzinfo=KYIV),
                      league_raw=лига, sport_raw=вид, live_raw="live",
                      match_raw=пара)
    return pipeline.classify(program, MARKERS, SPORTS, {}, {}, WNBA)


print("3. pipeline.classify — метка дописана к именам")
row = строка("WNBA: Golden State Valkyries - Atlanta Dream", "2026-10-27T03:00",
             пара="Golden State Valkyries - Atlanta Dream")
проверка("показ 03:00: ok, имена с W, вид B, by_reference «показ вне окна»",
         (row.ok, row.home, row.away, row.sport, row.by_reference),
         (True, "Golden State Valkyries W", "Atlanta Dream W", "B", LATE_MARKS_HOW))
row = строка("WNBA: Golden State Valkyries - Atlanta Dream", "2026-10-27T02:00",
             пара="Golden State Valkyries - Atlanta Dream")
проверка("показ 02:00: прежний путь — «метки из эталона»",
         (row.home, row.away, row.by_reference),
         ("Golden State Valkyries W", "Atlanta Dream W", MARKS_HOW))
row = строка("WNBA - פלייאוף: גולדן סטייט - אטלנטה, גמר - משחק 5", "2026-10-27T03:00",
             пара="גולדן סטייט - אטלנטה", лига="WNBA - פלייאוף", канал="ספורט 5+")
проверка("строка sport5 ивритом 03:00: обе команды с W",
         (row.ok, row.home.endswith(" W"), row.away.endswith(" W"), row.by_reference),
         (True, True, True, LATE_MARKS_HOW))
row = строка("NBA: Denver Nuggets - Golden State Warriors", "2026-10-27T04:00",
             пара="Denver Nuggets - Golden State Warriors", лига="NBA")
проверка("НБА 04:00 — без меток, имена как на сайте",
         (row.home, row.away), ("Denver Nuggets", "Golden State Warriors"))

print(f"\nзелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

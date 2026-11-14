"""Книга 120 (#10237, 14.11): пара наоборот и «стена словаря».

Случай: movistarplus.es подписал матч «Inglaterra - España» (у эталона —
«Spain - England»). Сверка сравнивала стороны по местам, свой матч набрал
33, а чужой «Finland - San Marino» по похожести букв стал «явным лидером» —
34 строки каналов уехали к чужой игре.

Н1. Сайт записал пару наоборот — это тот же матч; стороны игры
    переставляются по эталону (`canon._flip_reversed`).
Н2. Стена словаря: команде, которую словарь знает твёрдо, решение программы
    не может назначить другую команду (`canon.dictionary_disputes`).

Запуск: python scripts/test_para_naoborot.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import canon, names  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def эталон(home: str, away: str, когда: str, fs: str, league: str = "EUROPE: UEFA Nations League",
           sport: str = "F") -> dict:
    return {"sport": sport, "home": home, "away": away, "league": league, "fs_id": fs,
            "start_kyiv": когда}


def игра(home: str, away: str, когда: str, league: str = "UEFA Nations League",
         sport: str = "F") -> dict:
    return {"sport": sport, "home": home, "away": away, "league": league, "start_kyiv": когда,
            "entries": []}


def свести(game: dict, refs: list) -> tuple[str, str]:
    """(итог, fs_id пары эталона) для одной игры."""
    out = canon.align([game], refs, {})
    for kind in ("sure", "ask"):
        for _, ref, _ in out[kind]:
            return kind, ref["fs_id"]
    return "missed", ""


ИСПАНИЯ = эталон("Spain", "England", "2026-11-15T21:45", "zs0jyKt4")
ФИНЛЯНДИЯ = эталон("Finland", "San Marino", "2026-11-15T19:00", "dOS9WO3d")

print("Н1. Сайт записал пару наоборот — тот же матч")
g = игра("Inglaterra", "Spain", "2026-11-15T20:05")
проверка("случай #10237: «Inglaterra — Spain» сходится со «Spain — England», а не с "
         "«Finland — San Marino»", свести(g, [ИСПАНИЯ, ФИНЛЯНДИЯ]), ("sure", "zs0jyKt4"))
проверка("…стороны игры переставлены по эталону, пометка стоит",
         (g["home"], g["away"], g.get(canon.REVERSED)), ("Spain", "Inglaterra", True))
проверка("…решили буквы, а не правило программы — пометки «программа» нет",
         g.get("канон_как"), None)
g = игра("Spain", "England", "2026-11-15T21:30")
проверка("пара в порядке эталона — сходится как раньше, без перестановки",
         (свести(g, [ИСПАНИЯ, ФИНЛЯНДИЯ]), g["home"], g.get(canon.REVERSED)),
         (("sure", "zs0jyKt4"), "Spain", None))
g = игра("Испания", "Англия", "2026-11-15T21:45")
проверка("кириллица в порядке эталона — без перестановки",
         (свести(g, [ИСПАНИЯ, ФИНЛЯНДИЯ]), g.get(canon.REVERSED)), (("sure", "zs0jyKt4"), None))
g = игра("Англия", "Испания", "2026-11-15T21:45")
проверка("кириллица наоборот — тот же матч, стороны переставлены",
         (свести(g, [ИСПАНИЯ, ФИНЛЯНДИЯ]), g["home"], g.get(canon.REVERSED)),
         (("sure", "zs0jyKt4"), "Испания", True))
g = игра("Cleveland Cavaliers", "Dallas Mavericks", "2026-11-15T02:30", "NBA", "B")
нба = эталон("Dallas Mavericks", "Cleveland Cavaliers", "2026-11-15T02:30", "nba1", "USA: NBA", "B")
проверка("клубы, не сборные: «гости — хозяева» у сайта — тот же матч",
         (свести(g, [нба]), g["home"]), (("sure", "nba1"), "Dallas Mavericks"))
ВТОРАЯ = эталон("Spain", "England", "2026-11-15T19:30", "dubl")
g = игра("Inglaterra", "Spain", "2026-11-15T20:05")
итог = свести(g, [ИСПАНИЯ, ВТОРАЯ, ФИНЛЯНДИЯ])
проверка("перевёрнутых кандидатов двое — не гадаем, игру не переставляем",
         (g["home"], g.get(canon.REVERSED)), ("Inglaterra", None))
проверка("…и к «Finland — San Marino» она всё равно не уходит", итог[1] != "dOS9WO3d")
g = игра("TBC", "Spain", "2026-11-15T21:45")
свести(g, [ИСПАНИЯ, ФИНЛЯНДИЯ])
проверка("заглушку («TBC») не переставляем", g.get(canon.REVERSED), None)
g = игра("Inglaterra", "Spain", "2026-11-15T20:05")
проверка("своего матча у эталона нет — игра остаётся как на сайте, к чужой не уходит",
         (свести(g, [ФИНЛЯНДИЯ]), g["home"]), (("missed", ""), "Inglaterra"))

print("Н2. Стена словаря: известной команде буквы не назначат другую")
g = игра("Inglaterra", "Spain", "2026-11-15T20:05")
проверка("«Inglaterra» словарь знает как England — пара с Finland спорит со словарём",
         "ENGLAND" in canon.dictionary_disputes(g, ФИНЛЯНДИЯ), True)
проверка("своя пара со словарём не спорит",
         canon.dictionary_disputes(игра("Espanha", "Inglaterra", ""), ИСПАНИЯ), "")
проверка("словарь команд не знает — стена молчит (для этого и нужны решения программы)",
         canon.dictionary_disputes(игра("Zzyzx Athletic", "Qwertyu United", ""), ФИНЛЯНДИЯ), "")
out = {"sure": [], "ask": [], "missed": []}
canon._sure(out, g, ФИНЛЯНДИЯ, canon.SURE, canon.HOW_LEADER)
проверка("решение программы «явный лидер» против словаря не принимается — игра в «мимо»",
         (len(out["sure"]), len(out["missed"])), (0, 1))
for how in (canon.HOW_BRIDGE, canon.HOW_FIRM, canon.HOW_AGED):
    out = {"sure": [], "ask": [], "missed": []}
    canon._sure(out, игра("Inglaterra", "Spain", ""), ФИНЛЯНДИЯ, canon.SURE, how)
    проверка(f"…то же для «{how}»", (len(out["sure"]), len(out["missed"])), (0, 1))
names.set_overrides({"Селта": "Celta Vigo", "Хетафе": "Getafe"})
try:
    проверка("подтверждённое имя клуба словарь тоже знает твёрдо",
             (names.known_team("Селта"), names.known_team("Неведомый клуб")), ("Celta Vigo", ""))
    клуб = эталон("Getafe", "Sevilla", "2026-11-15T19:00", "esp1", "SPAIN: LaLiga")
    проверка("«Селта» = Celta Vigo по словарю — парой Getafe она не станет",
             bool(canon.dictionary_disputes(игра("Селта", "Севиля", ""), клуб)), True)
    проверка("«Хетафе» = Getafe — со своей парой спора нет",
             canon.dictionary_disputes(игра("Хетафе", "Севиля", ""), клуб), "")
finally:
    names.set_overrides({})
проверка("страна из справочника известна твёрдо, с пометками пола и возраста",
         (names.known_team("Inglaterra"), names.known_team("Финландия"),
          names.known_team("Spain U21")), ("ENGLAND", "FINLAND", "SPAIN"))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

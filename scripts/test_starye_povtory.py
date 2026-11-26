# -*- coding: utf-8 -*-
r"""Книга 180 (26.11.2026): повтор матча, сыгранного больше 60 часов назад.

Жалоба владельца 26.11 («на витрине начали появляться лишние игры»):
  * #11892 «TORINO — NAPOLI» 26.11 21:45 (tvarenasport.hr) — матч сыгран 21.11;
  * #12066 «Βαλένθια — Βίρτους Μπολόνια» 27.11 20:45 (novasports.gr) — матч
    Евролиги сыгран 19.11 (тура 26–27.11 нет: окно сборных); неподтверждённой
    игре программа поставила футбол.
Сайты запись не помечают, эталон сбора начинается с сегодняшней полуночи.
Правила П1–П5 — в шапке `app/played.py`. Предел: пара, которую сайт зовёт
иначе, чем эталон («Asvel — Armani»), не узнаётся.
В сеть не ходит. Запуск: python scripts/test_starye_povtory.py
"""
from __future__ import annotations

import inspect
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import broadcast, played  # noqa: E402
from app.reference import Reference  # noqa: E402
import parse_live  # noqa: E402

зелёных = красных = 0
СЕЙЧАС = datetime(2026, 11, 26, 9, 46)


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


# записи эталона прошлых сборов — как их отдаёт flashscore (с местными написаниями)
ВАЛЕНСИЯ = {"sport": "B", "home": "Valencia", "away": "Virtus Bologna", "league": "EUROPE: Euroleague",
            "fs_id": "val19", "start_kyiv": "2026-11-19T22:00",
            "names": {"el": ["Βαλένθια", "Βίρτους Μπολόνια"], "ru": ["Валенсия", "Виртус Болонья"]},
            "leagues": {"el": "ΕΥΡΩΠΗ: Ευρωλίγκα"}}
НАПОЛИ = {"sport": "F", "home": "Napoli", "away": "Torino", "league": "ITALY: Serie A", "fs_id": "nap21",
          "start_kyiv": "2026-11-21T21:45", "names": {"hr": ["Napoli", "Torino"]}}
ЛИОН = {"sport": "B", "home": "Lyon-Villeurbanne", "away": "Olimpia Milano", "league": "EUROPE: Euroleague",
        "fs_id": "lyo24", "start_kyiv": "2026-11-24T21:45"}
СТАРЫЙ = {"sport": "F", "home": "Lazio", "away": "Cagliari", "league": "ITALY: Serie A", "fs_id": "old",
          "start_kyiv": "2026-11-10T16:00"}


def игра(home, away, когда, sport="F", каналы=("Arena Sport 6",), назвал=""):
    """`назвал` — откуда вид спорта (`Row.sport_source`): «word» — слово на сайте, пусто — догадка."""
    строки = [SimpleNamespace(payload=SimpleNamespace(sport_source=назвал))]
    return SimpleNamespace(home=home, away=away, start=datetime.fromisoformat(когда), sport=sport,
                           channels=list(каналы), entries=строки)


print("1. Память (`load`, `remember`, `dump`, П1)")
память = played.load({played.KEY: [ВАЛЕНСИЯ, НАПОЛИ, ЛИОН, СТАРЫЙ]}, now=СЕЙЧАС, seed=Path("нет-такого-файла.json"))
проверка("запись старше 8 суток в память не берётся", sorted(e["fs_id"] for e in память.values()),
         ["lyo24", "nap21", "val19"])
проверка("в памяти только поля сверки пары (переводы лиг не хранятся)",
         sorted(память["val19"]), ["away", "fs_id", "home", "league", "names", "sport", "start_kyiv"])
посев = Path(tempfile.mkdtemp(prefix="povtory-")) / "seed.json"
посев.write_text(json.dumps([НАПОЛИ, СТАРЫЙ, {"нет": "времени"}], ensure_ascii=False), encoding="utf-8")
проверка("посев дополняет память, просроченное и битое из него не берётся",
         sorted(played.load({}, now=СЕЙЧАС, seed=посев)), ["nap21"])
проверка("нет ни памяти, ни посева — пусто, без падения",
         played.load(None, now=СЕЙЧАС, seed=Path("нет-такого-файла.json")), {})
СЕГОДНЯ = {"sport": "F", "home": "Venezia", "away": "Bologna", "league": "ITALY: Serie A", "fs_id": "ven27",
           "start_kyiv": "2026-11-27T21:45"}
эталон = Reference([СЕГОДНЯ])
новая: dict = {}
добавлено = played.remember(новая, [игра("Venezia", "Bologna", "2026-11-27T21:45"),
                                      игра("Venezia", "Bologna", "2026-11-27T21:45"),
                                      игра("Никто", "Ничей", "2026-11-27T21:45"),
                                      игра("Davis Cup", broadcast.SESSION, "2026-11-27T17:00", "T")], эталон)
проверка("в память идёт запись эталона, подтвердившая игру сбора, — один раз; неподтверждённое и турнир без пары — нет",
         (добавлено, sorted(новая)), (1, ["ven27"]))
проверка("итог сбора: память по времени, без просроченных",
         [e["fs_id"] for e in played.dump({**память, "old": СТАРЫЙ}, now=СЕЙЧАС)], ["val19", "nap21", "lyo24"])

print("2. Повтор или нет (`replay_of`, П2–П5) — живые строки 26.11")
сыгранные = Reference(list(память.values()))
пустой = Reference([])
проверка("#11892 «TORINO — NAPOLI» 26.11 21:45: матч сыгран 21.11 (стороны наоборот) — повтор",
         (played.replay_of("TORINO", "NAPOLI", datetime(2026, 11, 26, 21, 45), сыгранные, эталон) or {}).get("fs_id"), "nap21")
проверка("#12066 «Βαλένθια — Βίρτους Μπολόνια» 27.11 20:45: сыгран 19.11, написание местное — повтор",
         (played.replay_of("Βαλένθια", "Βίρτους Μπολόνια", datetime(2026, 11, 27, 20, 45), сыгранные, эталон) or {}).get("fs_id"),
         "val19")
проверка("П3а (слово владельца «почему её не решить?»): #12005 «Asvel — Armani» 27.11 21:45 — словарь команд знает "
         "оба прозвища, матч «Lyon-Villeurbanne — Olimpia Milano» сыгран 24.11 — повтор",
         (played.replay_of("Asvel", "Armani", datetime(2026, 11, 27, 21, 45), сыгранные, эталон) or {}).get("fs_id"), "lyo24")
проверка("П3а: словарь команд ветки знает прозвища (живые данные)",
         [played.by_dictionary("Asvel"), played.by_dictionary("ARMANI"), played.by_dictionary("Нет такой команды")],
         ["Lyon-Villeurbanne", "Olimpia Milano", "Нет такой команды"])
словарь = Path(tempfile.mkdtemp(prefix="povtory-slovar-")) / "d.json"
словарь.write_text(json.dumps({"teams": [
    {"name": "Lyon-Villeurbanne", "aliases": ["Asvel", "Lyon"]}, {"name": "Lyon", "aliases": ["Olympique Lyonnais"]},
    {"name": "", "aliases": ["пусто"]}, "мусор"]}, ensure_ascii=False), encoding="utf-8")
проверка("П3а: написание, которое словарь знает за двумя командами («Lyon»), не переводится; мусор словаря не роняет",
         [played.by_dictionary("asvel", словарь), played.by_dictionary("Lyon", словарь),
          played.by_dictionary("Olympique  Lyonnais", словарь), played.by_dictionary("пусто", словарь)],
         ["Lyon-Villeurbanne", "Lyon", "Lyon", "пусто"])
проверка("П3а: словаря нет — имена как на сайте, без падения",
         played.by_dictionary("Asvel", Path("нет-такого-словаря.json")), "Asvel")
проверка("П2: раньше 60 часов после матча судит прежнее правило — здесь молчим",
         played.replay_of("Napoli", "Torino", datetime(2026, 11, 23, 12, 0), сыгранные, пустой), None)
проверка("П2: позже 8 суток — уже не повтор той встречи",
         played.replay_of("Napoli", "Torino", datetime(2026, 11, 30, 12, 0), сыгранные, пустой), None)
проверка("П2: показ до матча памяти — не повтор",
         played.replay_of("Napoli", "Torino", datetime(2026, 11, 20, 21, 45), сыгранные, пустой), None)
НОВАЯ_ВСТРЕЧА = {"sport": "F", "home": "Torino", "away": "Napoli", "league": "ITALY: Coppa Italia", "fs_id": "cup26",
                 "start_kyiv": "2026-11-26T21:45"}
проверка("П5: новая встреча тех же команд стоит в эталоне на это время — не повтор",
         played.replay_of("TORINO", "NAPOLI", datetime(2026, 11, 26, 21, 45), сыгранные, Reference([НОВАЯ_ВСТРЕЧА])), None)
проверка("П4: трансляция турнира без пары и неназванный соперник — не судим",
         [played.replay_of("Napoli", broadcast.SESSION, datetime(2026, 11, 26, 21, 45), сыгранные, пустой),
          played.replay_of("Napoli", "TBC", datetime(2026, 11, 26, 21, 45), сыгранные, пустой)], [None, None])
КАРДИЦА = {"sport": "B", "home": "AS Karditsas", "away": "Olympiacos", "league": "GREECE: Basket League",
           "fs_id": "kar22", "start_kyiv": "2026-11-22T15:00", "names": {"el": ["Α.Σ. Καρδίτσας", "Ολυμπιακός"]}}
с_кардицей = Reference(list(память.values()) + [КАРДИЦА])
проверка("П3 (проба 26.11): сайт сам назвал футбол — баскетбольный матч тех же вывесок не повтор",
         played.replay_of("Αναγέννηση Καρδίτσας", "Ολυμπιακός Β’", datetime(2026, 11, 29, 14, 45), с_кардицей, эталон, "F"), None)
проверка("П3: вид спорта — догадка (сайт его не называл) — сверяем без него",
         (played.replay_of("Α.Σ. Καρδίτσας", "Ολυμπιακός", datetime(2026, 11, 29, 14, 45), с_кардицей, эталон, "") or {}).get("fs_id"),
         "kar22")
мост = SimpleNamespace(confirm=lambda *a: SimpleNamespace(how="одна сторона", entry={"home": "Juventus", "away": "Omonia"}))
проверка("П2 (проба 26.11): мост «одна сторона» с чужим матчем того же вечера повтор не отменяет",
         (played.replay_of("TORINO", "NAPOLI", datetime(2026, 11, 26, 21, 45), сыгранные, мост) or {}).get("fs_id"), "nap21")
проверка("другая пара с тем же клубом — не повтор",
         played.replay_of("Napoli", "Roma", datetime(2026, 11, 26, 21, 45), сыгранные, пустой), None)
проверка("пустая память, нет времени, нет сторон — None",
         [played.replay_of("Napoli", "Torino", datetime(2026, 11, 26, 21, 45), пустой, пустой),
          played.replay_of("Napoli", "Torino", None, сыгранные, пустой),
          played.replay_of("", "Torino", datetime(2026, 11, 26, 21, 45), сыгранные, пустой)], [None, None, None])

print("3. Список игр сбора (`drop_replays`)")
игры = [игра("TORINO", "NAPOLI", "2026-11-26T21:45", назвал="word"), игра("Venezia", "Bologna", "2026-11-27T21:45"),
        игра("Βαλένθια", "Βίρτους Μπολόνια", "2026-11-27T20:45"), игра("Asvel", "Armani", "2026-11-27T21:45", "B"),
        игра("Αναγέννηση Καρδίτσας", "Ολυμπιακός Β’", "2026-11-29T14:45", назвал="word")]
оставлены, сняты = played.drop_replays(игры, {**память, "kar22": КАРДИЦА}, эталон)
проверка("сняты три повтора (третий — по словарю команд); живой матч и футбольный матч при баскетбольной памяти остались",
         ([(g.home, g.away) for g in оставлены], [(g.home, e["fs_id"]) for g, e in сняты]),
         ([("Venezia", "Bologna"), ("Αναγέννηση Καρδίτσας", "Ολυμπιακός Β’")],
          [("TORINO", "nap21"), ("Βαλένθια", "val19"), ("Asvel", "lyo24")]))
живая = Reference([{"sport": "B", "home": "Lyon-Villeurbanne", "away": "Olimpia Milano", "league": "EUROPE: Euroleague",
                    "fs_id": "live", "start_kyiv": "2026-11-24T21:45"}])
память_прозвищ: dict = {}
played.remember(память_прозвищ, [игра("Asvel", "Armani", "2026-11-24T21:45", "B")], живая)
проверка("П3а в памяти: живой матч под прозвищами записывается записью эталона", sorted(память_прозвищ), ["live"])
проверка("вид спорта игры: назван сайтом — буква, догадка — пусто",
         [played.stated_sport(игра("A", "B", "2026-11-27T21:45", "B", назвал="league")),
          played.stated_sport(игра("A", "B", "2026-11-27T21:45", "F")),
          played.stated_sport(игра("A", "B", "2026-11-27T21:45", "B", назвал="ref"))], ["B", "", ""])
проверка("пустая память — список не меняется", played.drop_replays(игры, {}, эталон), (игры, []))

print("4. Место правила в разборе (`parse_live`)")
код = inspect.getsource(parse_live)
проверка("детектор: память берётся из прошлого итога, правило стоит после повтора по эталону и до поздних повторов",
         0 < код.index("played.load(previous_payload())") < код.index("drop_reference_repeats(games, reference_full)\n")
         < код.index("played.drop_replays(games, память_сыгранных, judge)") < код.index("games, late = drop_late_repeats(games)"))
проверка("детектор: снятое идёт в журнал своим именем, память уходит в итог сбора",
         ["removed_row(СНЯТО_СТАРЫЙ_ПОВТОР" in код, "payload[played.KEY] = played.dump(память_сыгранных)" in код,
          "played.remember(память_сыгранных, games, judge)" in код], [True, True, True])
проверка("глубина памяти — 8 суток, порог — прежние 60 часов",
         (played.DEPTH, played.AFTER), (timedelta(days=8), timedelta(hours=60)))
посев_ветки = played.SEED_FILE
проверка("посев в ветке читается и держит только поля сверки",
         посев_ветки.exists() and all(set(e) <= set(played.FIELDS)
                                      for e in json.loads(посев_ветки.read_text(encoding="utf-8"))))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

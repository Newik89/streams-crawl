# -*- coding: utf-8 -*-
r"""Книга 141 (15.11.2026): теннисный матч с игроками, который буквы не узнали.

Греческий сайт cosmotetv.gr пишет игроков полным именем и своим переводом
фамилии («Κάρλος Αλκαράθ - Φράνσις Τιαφό»), эталон — фамилией с инициалом и
своим («Αλκαράζ Γκαρφία Κ.», «Τιαφόε Φ.»). На витрине матч стоял второй
строкой («Karlos Alkarath vs Fransis Tiafo») рядом со своим же матчем эталона.
Замер по всем сайтам сбора 15.11: эталон не узнал 6 из 20 теннисных матчей с
игроками — все шесть с этого сайта.

Правила:
  1. `translit.to_english` — знак «микро» (µ) в греческом слове читается буквой «мю»;
  2. `names._letter_readings` — греческий инициал «Ν.» / «Μ.» читается и как
     первый звук имени на «Ντ» / «Μπ»;
  3. `canon.tennis_one_side`, Т1–Т6 — один игрок узнан твёрдо, матч в окне
     эфира у него один, второй игрок не спорит → решение программы
     `canon.HOW_TENNIS` в сверке (`canon.align`).
В сеть не ходит, базу не открывает. Запуск: python scripts/test_tennis_igrok_uznan.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import canon, names  # noqa: E402
from app.translit import to_english  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


МИКРО = "µ"      # знак «микро» — на глаз как греческая «мю»

print("Чтение греческих имён")
проверка("знак «микро» в греческом слове читается буквой «мю»: слово не рвётся",
         (to_english(f"Τι{МИКРО} Πιουτς"), names.readings(f"Τέο Αρι{МИКРО}πάτζε"), to_english("Τιμ Πιουτς")),
         ("Tim Piuts", ("TEO ARIMBATZE",), "Tim Piuts"))
проверка("инициал «Ν.» сходится с именем на «Ντ», «Μ.» — с именем на «Μπ» (эталон сокращает до первой буквы)",
         (names.similarity("Ντανιίλ Μεντβέντεφ", "Μεντβέντεφ Ν. (Κοσ)"),
          names.similarity("Μπεν Σέλτον", "Σέλτον Μ. (Ηπα)"),
          names.similarity("Νόβακ Τζόκοβιτς", "Τζόκοβιτς Ν. (Σερ)"),
          names.similarity("Μαρσέλο Αρέβαλο/Μέιτ Πάβιτς", "Αρεβάλο Μ./Πάβιτς Μ.")), (100, 100, 100, 100))
проверка("чужой инициал по-прежнему чужой: другой человек с той же фамилией; латиницу правило не трогает",
         (names.similarity("Αλεξάντερ Μεντβέντεφ", "Μεντβέντεφ Ν. (Κοσ)") < canon.SURE,
          names.similarity("Daniil Medvedev", "Medvedev N.") < canon.SURE,
          names.similarity("Daniil Medvedev", "Medvedev D.")), (True, True, 100))


def матч(home, away, start, **местные):
    return {"sport": "T", "home": home, "away": away, "start_kyiv": start, "fs_id": home[:3] + away[:3],
            "league": "ATP - SINGLES: Finals - Turin (World), hard (indoor)", "names": местные}


ЗВЕРЕВ = матч("Zverev A.", "Jodar R.", "2026-11-15T15:00", el=["Ζβέρεφ Α. (Γερ)", "Ζόνταρ Ρ. (Ισπ)"])
ШЕЛТОН = матч("Shelton B.", "Fils A.", "2026-11-15T16:30", el=["Σέλτον Μ. (Ηπα)", "Φις Α. (Γαλ)"])
АЛЬКАРАС = матч("Alcaraz C.", "Tiafoe F.", "2026-11-16T15:00", el=["Αλκαράζ Γκαρφία Κ. (Ισπ)", "Τιαφόε Φ. (Ηπα)"])
ПАРА = матч("Darderi L./Etcheverry T.", "Granollers M./Zeballos H.", "2026-11-16T15:00")
БРАТЬЯ = [матч("Cerundolo F.", "Ruud C.", "2026-11-17T15:00"), матч("Cerundolo J. M.", "Paul T.", "2026-11-17T15:30")]
ЭТАЛОН = [ЗВЕРЕВ, ШЕЛТОН, АЛЬКАРАС, ПАРА] + БРАТЬЯ


def рядом(start):
    return [(r, datetime.fromisoformat(r["start_kyiv"])) for r in ЭТАЛОН
            if abs(datetime.fromisoformat(r["start_kyiv"]) - start) <= canon.WINDOW]


def игрок(home, away, start, sport="T"):
    when = datetime.fromisoformat(start)
    got = canon.tennis_one_side({"sport": sport, "home": home, "away": away, "start_kyiv": start}, рядом(when), when)
    return None if got is None else (got[0]["home"], got[1])


print("Теннис: игрок узнан, матч в это время у него один (`canon.tennis_one_side`), правила Т1–Т6")
проверка("Т4, Т6: «Αλεξάντερ Ζβέρεφ — Ραφαέλ Χόδαρ» — Зверев узнан твёрдо, матч в окне у него один; "
         "перевод «Χόδαρ» с эталонным «Ζόνταρ» не сходится — и не нужен",
         (names.similarity("Ραφαέλ Χόδαρ", "Ζόνταρ Ρ. (Ισπ)") < 50, игрок("Αλεξάντερ Ζβέρεφ", "Ραφαέλ Χόδαρ", "2026-11-15T15:00")),
         (True, ("Zverev A.", False)))
проверка("Т4: твёрдо — от 90: «Τιαφό» против «Τιαφόε» (буква перевода); сайт записал пару наоборот — так и говорим",
         (игрок("Κάρλος Αλκαράθ", "Φράνσις Τιαφό", "2026-11-16T15:00"),
          игрок("Φράνσις Τιαφό", "Κάρλος Αλκαράθ", "2026-11-16T15:00")),
         (("Alcaraz C.", False), ("Alcaraz C.", True)))
проверка("Т3: показ не в окне эфира матча (за два часа до и через полчаса после начала) — не берём; "
         "за час до и через 15 минут после — берём",
         [игрок("Αλεξάντερ Ζβέρεφ", "Ραφαέλ Χόδαρ", when) is not None for when in
          ("2026-11-15T13:00", "2026-11-15T15:30", "2026-11-15T14:00", "2026-11-15T15:15")],
         [False, False, True, True])
проверка("Т2: одиночка с парой не сводится — «Etcheverry» совпадает с «Darderi/Etcheverry» (регресс 01.10)",
         (игрок("Etcheverry T.", "Неизвестный Игрок", "2026-11-16T15:00"),
          игрок("Darderi L./Etcheverry T.", "Кто-то/Ещё", "2026-11-16T15:00"),
          игрок("Darderi L./Etcheverry T.", "Одиночка", "2026-11-16T15:00")),
         (None, ("Darderi L./Etcheverry T.", False), None))
проверка("Т5: вторая сторона — твёрдо игрок ДРУГОГО матча эталона рядом: это запись другого матча в час, "
         "когда играет Зверев, — не берём",
         игрок("Zverev A.", "Fils A.", "2026-11-15T15:00"), None)
проверка("Т6: два кандидата в окне (братья с одной фамилией) — не знаем",
         игрок("Cerundolo", "Неизвестный Игрок", "2026-11-17T15:00"), None)
проверка("Т1: не теннис, заглушка вместо игрока, трансляция турнира без игроков — не наш случай",
         (игрок("Zverev A.", "Χόδαρ", "2026-11-15T15:00", sport="F"), игрок("Zverev A.", "TBC", "2026-11-15T15:00"),
          игрок("ATP Finals Turin", "tournament", "2026-11-15T15:00")), (None, None, None))

print("Сверка с эталоном (`canon.align`)")
игры = [{"sport": "T", "home": "Κάρλος Αλκαράθ", "away": "Φράνσις Τιαφό", "league": "", "start_kyiv": "2026-11-16T15:00"},
        {"sport": "T", "home": "Φράνσις Τιαφό", "away": "Κάρλος Αλκαράθ", "league": "", "start_kyiv": "2026-11-16T15:00"},
        {"sport": "T", "home": "Zverev A.", "away": "Fils A.", "league": "", "start_kyiv": "2026-11-15T15:00"},
        {"sport": "T", "home": "Carlos Alcaraz", "away": "Frances Tiafoe", "league": "", "start_kyiv": "2026-11-16T15:00"}]
итог = canon.align(игры, ЭТАЛОН)
# по номеру игры в списке: переставленная пара получает те же имена, что прямая
уверенно = {next(i for i, x in enumerate(игры) if x is g):
            (g["home"], ref["home"], g.get("канон_как"), bool(g.get(canon.REVERSED))) for g, ref, _s in итог["sure"]}
проверка("матч, узнанный по игроку, — уверенная пара с пометкой решения программы (слабую сторону выучит словарь)",
         уверенно.get(0), ("Κάρλος Αλκαράθ", "Alcaraz C.", canon.HOW_TENNIS, False))
проверка("пара, записанная наоборот, переставлена по эталону и помечена",
         уверенно.get(1), ("Κάρλος Αλκαράθ", "Alcaraz C.", canon.HOW_TENNIS, True))
проверка("буквы главнее: пара, сошедшаяся буквами, пометки не получает; запись другого матча уверенной не стала",
         (уверенно.get(3), 2 in уверенно), (("Carlos Alcaraz", "Alcaraz C.", None, False), False))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

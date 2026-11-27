# -*- coding: utf-8 -*-
r"""Книга 182 (27.11.2026): студия, внутри которой идёт матч, — показ матча.

Жалоба владельца 27.11: «#11633 — почему на этой игре нет канала Al kass 1 ?» (Algeria U17 — Dominican Republic
U17, 17:00). alkass.net подписал трёхчасовой показ «Mondial Studio 2 / Algeria × Dominican», отдельной строки
матча у канала нет. Стоп-слово «Studio» срезало строку раньше эталона — за день потерялись все четыре показа
чемпионата мира U17 на каналах Al Kass. Слово владельца на правило — «Да, делаем». Правила:
  1. знак «×» — разделитель пары у общего читателя (`live._SPLIT`), как буква «x»;
  2. `live.studio_cut` (Ч1–Ч5): название студии срезается из подписи, остаток читается как пара;
  3. `pipeline.studio_word` (С1): отсев — стоп-слово заголовка класса «студия» (раздел `studio_show` файла
     `data/markers.json`; каждое его слово стоит и в `stop_title`);
  4. `pipeline.studio_pair` (С2, П1–П6): в остатке нет других стоп-слов, эталон подтверждает пару целиком;
  5. `pipeline.studio_inside` (С3–С5): следующая передача канала — не раньше `STUDIO_COVER` после начала матча,
     своей строки этого матча на странице нет; иначе строка остаётся отсевом, как была;
  6. `proverka.twin`, «студия»: к игре пришла ранняя строка-студия, и начало игры стало её временем — сравнение
     сборов не считает это пропажей игры (все прежние каналы при ней).
Замер по четырём сборам 22–27.11 (220 строк со стоп-словом и парой эталона): под правило подходят только четыре
строки alkass.net; передачи перед матчем остаются отсевом. В сеть не ходит.
Запуск: python scripts/test_studiya_s_matchem.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
# базу не открываем, но на всякий случай — не боевая
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.gettempdir()) / "studiya-none.db"))

from app import live, pipeline, sport  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import MARKS_HOW, Reference  # noqa: E402
import proverka  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
MARKERS = live.load()
#: словарь команд пустой — сценарии не зависят от data/dictionaries.json
SPORTS = sport.load(teams=())
зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def матч(дом: str, гость: str, когда: str, fs: str, вид: str = "F") -> dict:
    """Запись эталона в том виде, в каком её кладёт сбор (`games.json`)."""
    return {"sport": вид, "home": дом, "away": гость, "league": "", "fs_id": fs, "start_kyiv": когда, "names": {}}


#: эталон по образцу сбора 27.11: чемпионат мира U17 и два взрослых матча
ЭТАЛОН = Reference([
    матч("Algeria U17", "Dominican Republic U17", "2026-11-27T17:00", "SAgfPOqC"),
    матч("Montenegro U17", "Chile U17", "2026-11-27T17:00", "0MAZgmBL"),
    матч("Romania U17", "Cameroon U17", "2026-11-27T18:00", "4IaDn53e"),
    матч("Levante", "Ath Bilbao", "2026-11-27T21:00", "LevaAthB"),
    матч("Liverpool", "Manchester City", "2026-11-27T18:30", "LiveManc"),
    матч("PSG", "Le Mans", "2026-11-27T21:45", "PSGLeMa"),
])


def передача(канал: str, заголовок: str, когда: str, *, пара: str = " ", эфир: str = "") -> Program:
    return Program(channel_raw=канал, title=заголовок,
                   start=datetime.fromisoformat(f"2026-11-27T{когда}").replace(tzinfo=KYIV),
                   live_raw=эфир, match_raw=пара)


def страница(*программы: Program, эталон: Reference | None = ЭТАЛОН, сайт: str = "alkass.net") -> list:
    """Страница сайта через общий разбор, как в сборе (`pipeline.run`). Служебные слова ищутся на языке сайта."""
    return pipeline.run(list(программы), MARKERS, SPORTS, {}, {}, эталон, domain=сайт, guess_site=True)


def итог(row) -> tuple:
    return (row.ok, row.home, row.away)


print("1. Знак «×» — разделитель пары у общего читателя")
проверка("«Al Sadd × Al Hilal» — пара", live.split_teams("Al Sadd × Al Hilal"), ("Al Sadd", "Al Hilal"))
проверка("буква «x» работает, как раньше", live.split_teams("PORTIMONENSE X LEIXÕES"), ("PORTIMONENSE", "LEIXÕES"))
проверка("знак без пробелов разделителем не считается («4×100 м»)", live.split_teams("Эстафета 4×100 м"), None)
проверка("рубрика через « / » перед парой со знаком — чистая пара среди догадок общего читателя",
         ("FIFA U-17 World Cup / Ireland", "Tanzania") in live.split_candidates("FIFA U-17 World Cup / Ireland × Tanzania"))

print("\n2. Срез названия студии (`live.studio_cut`)")
for подпись, ждём, зачем in (
        ("Mondial Studio 2 / Algeria × Dominican", "Algeria × Dominican", "Ч3: часть со студией без пары — долой"),
        ("Al-Mundial Studio 1 / Colombia × Serbia", "Colombia × Serbia", "Ч3: то же с другим названием"),
        ("Studio 2 Španělsko - Česko", "Španělsko - Česko", "Ч4: слово перед парой — срез до него и номер"),
        ("Fotbal - studio Jablonec - Lugano", "Jablonec - Lugano", "Ч4: первый разделитель — рубрика, слово всё равно перед парой"),
        ("Arsenal - Chelsea Studio", "Arsenal - Chelsea", "Ч4: слово после пары — срез от него до конца"),
        ("Viaplay Premier League: Studio før Liverpool - Manchester City",
         "Viaplay Premier League: før Liverpool - Manchester City", "Ч5: части склеены через «: », «før» остаётся — его увидит П2"),
        ("Algeria × Dominican", "", "Ч1: слова студии нет — правило не про эту строку"),
        ("Studio Zagreb - Dinamo", "", "Ч1: «Studio Zagreb» — имя клуба (`keep_names`), не студия"),
        ("JOJŠPORT štúdio", "", "Ч3: кроме названия студии, ничего нет"),
        ("Horse Racing Studio", "", "Ч3: студия без пары"),
):
    проверка(f"«{подпись}» → «{ждём}» ({зачем})", live.studio_cut(MARKERS, подпись), ждём)

print("\n3. С1: класс «студия» (`pipeline.studio_word`, раздел `studio_show`)")
проверка("причина «стоп-слово в заголовке: Studio» — слово студии",
         pipeline.studio_word("стоп-слово в заголовке: Studio", MARKERS), "Studio")
проверка("причина так и пишется отсевом: «Mondial Studio 2 / Algeria × Dominican»",
         live.check(передача("Al Kass One", "Mondial Studio 2 / Algeria × Dominican", "16:30"), MARKERS).reason,
         pipeline.STOP_IN_TITLE + "Studio")
проверка("другое стоп-слово («Previa») — не студия", pipeline.studio_word("стоп-слово в заголовке: Previa", MARKERS), "")
проверка("слово студии в ПОЛЕ ПАРЫ («стоп-слово или запись в паре») — правило не трогает",
         pipeline.studio_word("стоп-слово или запись в паре: Studio", MARKERS), "")
проверка("другая причина отсева — не про студию", pipeline.studio_word("нет маркера прямого эфира", MARKERS), "")
слова = live._flatten(json.loads((ROOT / "data" / "markers.json").read_text(encoding="utf-8"))["studio_show"])
проверка("раздел `studio_show` не пуст", len(слова) >= 6)
проверка("каждое слово раздела стоит и в `stop_title` (иначе до правила строка не дойдёт)",
         [w for w in слова if not MARKERS.found(MARKERS.stop_title, w)], [])
проверка("словарь языка сайта класс не теряет (`for_langs`)",
         MARKERS.for_langs(frozenset({"en"})).studio is MARKERS.studio)

print("\n4. С2: пара из подписи студии по эталону (`pipeline.studio_pair`)")


def пара(заголовок: str, когда: str, эталон: Reference | None = ЭТАЛОН):
    program = передача("Тест 1", заголовок, когда)
    got = pipeline.studio_pair(program, MARKERS, эталон, program.start)
    return None if got is None else (got[0].home, got[0].away, got[1].how, got[1].entry["fs_id"])


проверка("«Mondial Studio 2 / Algeria × Dominican» за полчаса до матча — пара целиком, метки из эталона",
         пара("Mondial Studio 2 / Algeria × Dominican", "16:30"), ("Algeria", "Dominican", MARKS_HOW, "SAgfPOqC"))
проверка("порядок сторон — как у эталона («Dominican × Algeria»)",
         пара("Mondial Studio 2 / Dominican × Algeria", "16:30"), ("Algeria", "Dominican", MARKS_HOW, "SAgfPOqC"))
проверка("П1: студия без пары — None", пара("Horse Racing Studio", "16:30"), None)
проверка("П2: в остатке слово передачи перед матчем («Studio før Liverpool - Manchester City») — None",
         пара("Viaplay Premier League: Studio før Liverpool - Manchester City", "17:30"), None)
проверка("П3: прошлый сезон в подписи — классика, None",
         пара("Studio 2003/04 / Levante - Ath Bilbao", "20:30"), None)
проверка("П5: эталон узнаёт только одну сторону («PSG - Lens» при «PSG — Le Mans») — None",
         пара("Studio / PSG - Lens", "21:30"), None)
проверка("П5: показ за три часа до матча — эталон эфиром не признаёт, None",
         пара("Studio / Levante - Ath Bilbao", "18:00"), None)
проверка("без эталона — None", пара("Mondial Studio 2 / Algeria × Dominican", "16:30", эталон=None), None)

print("\n5. С3–С5: студия накрывает матч (`pipeline.studio_inside` внутри `pipeline.run`)")
# а) страница Al Kass 27.11: студия 16:30, следующая передача канала 19:30, своей строки матча нет
студия = передача("Al Kass One", "Mondial Studio 2 / Algeria × Dominican", "16:30", пара="Mondial Studio 2 - Dominican",
                  эфир="live")
rows = страница(передача("Al Kass One", "News", "15:30"), студия, передача("Al Kass One", "tawasol", "19:30"))
проверка("а) студия с матчем внутри взята: пара чистая, возраст — из эталона",
         итог(rows[1]), (True, "Algeria U17", "Dominican U17"))
проверка("а) вид спорта — от эталона; эталон подтвердил «метки из эталона»",
         (rows[1].sport, rows[1].by_reference), ("F", MARKS_HOW))
проверка("а) эфир угаданный: дальше строку проверяют фильтры повторов", студия.extra.get("live_guess"), True)
проверка("а) пометка строки: слово студии, начало матча и ключ матча эталона",
         студия.extra.get(pipeline.STUDIO), {"слово": "Studio", "начало": "2026-11-27T17:00", "матч": "SAgfPOqC"})
проверка("а) соседние передачи канала остались отсевом", (rows[0].ok, rows[2].ok), (False, False))

# б) студия перед матчем: следующая передача — сам матч
до = передача("Тест 1", "Studio: Levante - Ath Bilbao", "20:30")
rows = страница(до, передача("Тест 1", "Levante - Ath Bilbao", "21:00", пара="Levante - Ath Bilbao", эфир="live"),
                передача("Тест 1", "News", "23:00"))
проверка("б) студия перед матчем остаётся отсевом (С3: следующая передача — в минуту начала; С4: своя строка)",
         (rows[0].ok, rows[0].reason), (False, pipeline.STOP_IN_TITLE + "Studio"))
проверка("б) сам матч на месте", итог(rows[1]), (True, "Levante", "Ath Bilbao"))
проверка("б) у непринятой строки пометок разбора не осталось", (до.extra.get(pipeline.STUDIO), до.extra.get("live_guess")),
         (None, None))

# в) С3: следующая передача раньше, чем через полтора часа после начала матча
rows = страница(передача("Тест 1", "Studio / Levante - Ath Bilbao", "20:30"), передача("Тест 1", "News", "22:15"))
проверка("в) следующая передача через 75 минут после начала матча — мало, отсев", rows[0].ok, False)
rows = страница(передача("Тест 1", "Studio / Levante - Ath Bilbao", "20:30"), передача("Тест 1", "News", "22:30"))
проверка("в) ровно через 90 минут — показ накрывает матч, строка взята", итог(rows[0]), (True, "Levante", "Ath Bilbao"))
проверка("в) порог — полтора часа", pipeline.STUDIO_COVER, timedelta(minutes=90))

# г) С3: следующей передачи канала на странице нет — конец показа неизвестен
rows = страница(передача("Тест 1", "News", "19:00"), передача("Тест 1", "Studio / Levante - Ath Bilbao", "20:30"),
                передача("Тест 2", "News", "23:30"))
проверка("г) следующей передачи ЭТОГО канала нет (передача другого канала не в счёт) — не гадаем, отсев", rows[1].ok, False)

# д) С4: своя строка матча — на другом канале той же страницы
rows = страница(передача("Тест 1", "Studio / Levante - Ath Bilbao", "20:30"), передача("Тест 1", "News", "23:30"),
                передача("Тест 2", "Levante - Ath Bilbao", "21:00", пара="Levante - Ath Bilbao", эфир="live"),
                передача("Тест 2", "News", "23:00"))
проверка("д) матч идёт своей строкой на другом канале страницы — студия вокруг матча, отсев", rows[0].ok, False)
проверка("д) своя строка матча на месте", итог(rows[2]), (True, "Levante", "Ath Bilbao"))

# е) один показ на двух каналах — берётся на обоих (С4 судит по строкам ДО правила)
rows = страница(передача("Al Kass Seven", "Al-Mundial Studio 1 / Romania × Cameroon", "18:00"),
                передача("Al Kass Seven", "News", "20:30"),
                передача("Al Kass Online", "Al-Mundial Studio 1 / Romania × Cameroon", "18:00"),
                передача("Al Kass Online", "News", "20:30"))
проверка("е) одна студия на двух каналах — оба показа взяты",
         [итог(rows[0]), итог(rows[2])], [(True, "Romania U17", "Cameroon U17")] * 2)

# ж) П2 через всю страницу: «Studio før …» накрывает матч, но это передача перед матчем
rows = страница(передача("Тест 1", "Viaplay Premier League: Studio før Liverpool - Manchester City", "17:30"),
                передача("Тест 1", "News", "21:00"), сайт="allente.no")
проверка("ж) слово передачи перед матчем в остатке (норвежский сайт, «før») — отсев, сколько бы показ ни длился",
         rows[0].ok, False)

# з) без эталона правило молчит
rows = страница(студия_без := передача("Al Kass One", "Mondial Studio 2 / Algeria × Dominican", "16:30"),
                передача("Al Kass One", "tawasol", "19:30"), эталон=None)
проверка("з) без эталона студия остаётся отсевом", (rows[0].ok, rows[0].reason), (False, pipeline.STOP_IN_TITLE + "Studio"))
проверка("з) и пометок не получает", студия_без.extra, {})

print("\n6. Обычный разбор строки студию не спасает (`classify` без `studio`)")
row = pipeline.classify(передача("Al Kass One", "Mondial Studio 2 / Algeria × Dominican", "16:30"), MARKERS, SPORTS, {}, {}, ЭТАЛОН)
проверка("одна строка без страницы — отсев: накрывает ли показ матч, знает только страница",
         (row.ok, row.reason), (False, pipeline.STOP_IN_TITLE + "Studio"))

print("\n7. Сравнение сборов понимает пришедшую строку-студию (`proverka.twin`, «студия»)")


def игра(дом: str, гость: str, начало: str, *строки: tuple) -> dict:
    return {"sport": "F", "home": дом, "away": гость, "start_kyiv": f"2026-11-27T{начало}",
            "entries": [{"source": сайт, "channel": канал, "start_kyiv": f"2026-11-27T{когда}", "raw_title": подпись}
                        for сайт, канал, когда, подпись in строки]}


СВОИ = (("rtcg.me", "TVCG 2", "16:50", "Crna Gora - Čile"), ("sport1.maariv.co.il", "Sport1 4", "16:55", "מונטנגרו - צ'ילה"))
была = игра("Crna Gora U17", "Čile U17", "16:50", *СВОИ)
стала = игра("Montenegro U17", "Chile U17", "16:30",
             ("alkass.net", "Al Kass Eight", "16:30", "Mondial Studio 2 / Montenegro × Chile"), *СВОИ)
проверка("начало новой игры — время её строки-студии", proverka.studio_start(стала))
проверка("у прежней игры строки-студии нет", proverka.studio_start(была), False)
проверка("игра сменила имя и встала на время студии, все прежние каналы при ней — та же игра («студия»)",
         proverka.twin(была, [стала], [])[1], "студия")
без_студии = игра("Montenegro U17", "Chile U17", "16:30", ("alkass.net", "Al Kass Eight", "16:30", "Montenegro × Chile"), *СВОИ)
проверка("ранняя строка — не студия: сдвиг начала без эталона по-прежнему не переезд", proverka.twin(была, [без_студии], []),
         (None, ""))
потеряла = игра("Montenegro U17", "Chile U17", "16:30",
                ("alkass.net", "Al Kass Eight", "16:30", "Mondial Studio 2 / Montenegro × Chile"), СВОИ[0])
проверка("пришла студия, а прежний канал пропал — не та же игра: потерю сравнение покажет",
         proverka.twin(была, [потеряла], []), (None, ""))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

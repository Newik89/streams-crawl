"""Книга 124 (этап 2 плана «сайт не перестаёт разбираться»): выжимка приёмов
всех разборщиков — в общий читатель пары.

Опись 89 разборщиков (14.11): у 59 своя функция поиска пары, 47 умеют брать
пару из описания, и ни один не делится приёмами с остальными. Теперь общий
читатель (`live.split_candidates`, `pipeline.pair_guesses`) знает разделители
и слова «против» всех сайтов и читает описание передачи. Каждая догадка идёт
в ленту, только если её подтвердил эталон.

Запуск: python scripts/test_obshchiy_chitatel.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import live, pipeline, sport  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import Reference  # noqa: E402

зелёных = красных = 0
MARKERS = live.load()
SPORTS = sport.load(teams=())
ЭТАЛОН = Reference([
    {"sport": "F", "home": "Spain", "away": "England", "league": "EUROPE: UEFA Nations League",
     "fs_id": "a1", "start_kyiv": "2026-11-15T21:45"},
])


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def строка(title: str, pair: str = " ", description: str = "", live_raw: str = "live"):
    start = datetime(2026, 11, 15, 19, 45, tzinfo=timezone.utc)           # 21:45 по Киеву
    return Program(channel_raw="Kanal 7", title=title, start=start,
                   raw_time=start.strftime("%H:%M"), description=description,
                   league_raw="football", sport_raw="football", live_raw=live_raw,
                   match_raw=pair, source_url="https://example.test/x", extra={})


def разбор(p: Program, reference=ЭТАЛОН):
    return pipeline.classify(p, MARKERS, SPORTS, {}, {}, reference, None)


print("Правило 6: разделители и слова «против» со всех сайтов")
for подпись, пара in (
        ("Arsenal v Chelsea", ("Arsenal", "Chelsea")),
        ("Arsenal vs. Chelsea", ("Arsenal", "Chelsea")),
        ("Arsenal / Chelsea", ("Arsenal", "Chelsea")),
        ("Arsenal | Chelsea", ("Arsenal", "Chelsea")),
        ("Bayern gegen Dortmund", ("Bayern", "Dortmund")),
        ("Prishtina ndaj Drita", ("Prishtina", "Drita")),
        ("AIK mot Hammarby", ("AIK", "Hammarby")),
        ("Legia kontra Lech", ("Legia", "Lech")),
        ("Спартак против Зенит", ("Спартак", "Зенит")),
        ("Левски срещу Лудогорец", ("Левски", "Лудогорец")),
        ("Fenerbahçe karşı Galatasaray", ("Fenerbahçe", "Galatasaray"))):
    проверка(f"«{подпись}»", пара in live.split_candidates(подпись), True)
проверка("два таких разделителя — не гадаем",
         ("Arsenal", "Chelsea v Spurs") in live.split_candidates("Arsenal v Chelsea v Spurs"), False)
проверка("прежние правила на месте: « - », « vs », « at », слитный дефис",
         [("Spain", "England") in live.split_candidates(t)
          for t in ("Spain - England", "Spain vs England", "England at Spain", "Spain-England")],
         [True, True, True, True])

print("Правило 7 и первая строка описания")
ФРАЗА = "UEFA Nations League - Shikoni ndeshjen e futbollit në të cilën Spanja përballon Angli."
проверка("фраза-шаблон «A встречается с B» (ipko.tv)", live.phrase_pairs(ФРАЗА), [("Spanja", "Angli")])
проверка("текст без шаблона — пусто", live.phrase_pairs("Lajmet më të fundit nga vendi dhe bota."), [])
проверка("первая строка описания — подпись матча", live.lead("Prishtina - Drita. Ndeshje e javës."),
         "Prishtina - Drita")
проверка("длинный рассказ — не подпись", live.lead("а" * 120 + ". Продолжение"), "")
проверка("пустое описание", live.lead(""), "")
p = строка("Sport News", " ", "Spain - England. Live from Madrid.")
проверка("догадки строки: поле пары, заголовок, первая строка описания, фразы",
         ("Spain", "England") in pipeline.pair_guesses(p), True)
p = строка("Sport News", "Aaa - Bbb")
проверка("без поля пары (`with_field=False`) пара разборщика в догадки не идёт",
         (("Aaa", "Bbb") in pipeline.pair_guesses(p), ("Aaa", "Bbb") in pipeline.pair_guesses(p, False)),
         (True, False))

print("В отсеве: общий читатель — запасной ход за разборщиком сайта")
p = строка("Ndeshja e javës", " ", "Spain v England")
r = разбор(p)
проверка("разборщик пары не дал, пара — в первой строке описания через « v »: эталон подтвердил",
         (r.ok or bool(r.home), r.home, r.away), (True, "Spain", "England"))
p = строка("Ndeshja e javës", "Liga e Kombeve - Ndeshja e javës",
           "Liga - Shikoni ndeshjen në të cilën Spain përballon England.")
r = разбор(p)
проверка("разборщик дал мусорную пару, настоящая — во фразе описания: взята она",
         (r.home, r.away, bool(p.extra.get(pipeline.TITLE_PAIR))), ("Spain", "England", True))
p = строка("Ndeshja e javës", " ", "Qwerty Town v Asdfgh City")
r = разбор(p)
проверка("пару из описания эталон не подтвердил — строка в ленту не идёт, как раньше",
         (r.ok, r.home), (False, ""))
p = строка("Spain - England", "Spain - England", "Zzyzx Rovers v Xyzzy United")
r = разбор(p)
проверка("разборщик прочитал верно — описание не читается",
         ((r.home, r.away), p.extra.get(pipeline.TITLE_PAIR)), (("Spain", "England"), None))

p = строка("Sport News", " ", "Fotbal - Spain")
r = разбор(p)
проверка("догадка только из описания сошлась «одной стороной» — не берём (сбор 14.11: "
         "«Fotbal - Liga národů» у oneplay.cz)", (r.ok, r.home), (False, ""))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

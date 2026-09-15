# -*- coding: utf-8 -*-
"""Сборка: страница → готовые строки ленты (ТЗ разд. 5, шаги 3–5).

Здесь три шага пайплайна, которые одинаковы для всех сайтов:

    парсер сайта  →  отсев (app/live.py)  →  вид спорта (app/sport.py)  →  время

Что делает каждый — написано в своём модуле. Здесь только порядок и то, что
получается на выходе: строка `Row`, у которой уже есть время в UTC и в Киеве,
пара команд и понятная причина, если событие не взяли.

Названия команд остаются здесь в том виде, в каком стояли на сайте (поля
`home` / `away`, как `*_auto` в базе) — с одной поправкой: если турнир
женский или возрастной, метка (` W`, ` U19`) дописывается к именам сразу.
Иначе она теряется навсегда: дальше по конвейеру названия турнира уже нет,
а женский матч без метки склеится с мужским.

Приведением имён к канону (`Мидълзбро` → `Middlesbrough`) занимаются
`app/names.py` и словари, склейкой одинаковых игр — `app/merge.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from . import daytime, leagues, live, sport
from .parsers import Program


@dataclass
class Row:
    program: Program
    ok: bool                       # берём в ленту?
    reason: str = ""               # почему нет — понятной строкой
    needs_review: bool = False     # в очередь модерации, а не в мусор
    live_marker: str = ""
    home: str = ""
    away: str = ""
    league: str = ""               # ядро названия лиги, без вида спорта и сезона
    league_category: str = ""      # `W`, `U19` — из названия турнира
    sport: str = ""                # F | B | T
    sport_word: str = ""           # слово, по которому определили
    start_utc: datetime | None = None
    start_kyiv: datetime | None = None

    @property
    def when(self) -> str:
        return self.start_kyiv.strftime("%d.%m %H:%M") if self.start_kyiv else "—:—"


def hint_fresh(day: str | None, start_kyiv: datetime | None) -> bool:
    """Действует ли подсказка владельца на матч с этим временем.

    Подсказка привязана к дню матча и живёт ±36 часов вокруг него: та же
    пара в другом туре может играть другой спорт — теннисное дерби
    Тель-Авива не должно делать теннисом будущий футбол (владелец 15.09).
    Подсказка без дня — бессрочная (записи до этой правки)."""
    if not day:
        return True
    if start_kyiv is None:
        return False
    try:
        полдень = datetime.strptime(day, "%Y-%m-%d").replace(hour=12)
    except ValueError:
        return True                      # кривую дату считаем бессрочной
    return abs(start_kyiv.replace(tzinfo=None) - полдень) <= timedelta(hours=36)


def classify(program: Program, markers: live.Markers, sports: sport.Sports,
             league_sports: dict[str, str] | None = None,
             pair_sports: dict[str, str] | None = None) -> Row:
    row = Row(program=program, ok=False,
              start_utc=daytime.to_utc(program.start),
              start_kyiv=daytime.to_kyiv(program.start))

    verdict = live.check(program, markers)
    row.live_marker = verdict.live_marker
    row.home, row.away = verdict.home, verdict.away
    if not verdict.ok:
        row.reason = verdict.reason
        return row

    # Пол и возраст часто видны только по названию турнира, а команды на
    # сайте подписаны как обычно. Дописываем метку к именам, иначе женский
    # матч склеится с мужским (правило проекта: лишний ` W` лучше потерянного).
    row.league = leagues.clean(program.league_raw)
    row.league_category = leagues.category(
        " ".join(x for x in (program.league_raw, program.title,
                             program.description) if x))
    if row.league_category:
        row.home = leagues.with_category(row.home, row.league_category)
        row.away = leagues.with_category(row.away, row.league_category)

    text = " ".join(x for x in (program.title, program.sport_raw,
                                program.league_raw, program.description) if x)
    letter, word = sports.detect(text)
    row.sport_word = word
    if letter == "-":
        row.reason = f"другой вид спорта: {word}"
        return row
    if letter is None and league_sports:
        # Слов вида спорта в тексте нет, но лига известна словарю
        # (`data/dictionaries.json` — он едет в git и есть и у обхода).
        for key in (row.league, program.league_raw, program.sport_raw):
            letter = league_sports.get(" ".join(key.lower().split()))
            if letter:
                row.sport_word = key
                break
    if letter is None and pair_sports:
        # владелец сам сказал, какой это спорт, для такой пары команд
        # (страница «Названия», раздел «Вид спорта»): сайт о нём молчит
        ключ = f"{row.home} - {row.away}".strip()
        hint = pair_sports.get(ключ)
        if hint and hint_fresh(hint[1], row.start_kyiv):
            letter = hint[0]
            row.sport_word = "подсказка владельца"

    if letter is None:
        # ТЗ разд. 6: не определился — не в мусор, а владельцу на проверку
        row.reason = "вид спорта не определён"
        row.needs_review = True
        return row
    row.sport = letter

    if row.start_utc is None:
        row.reason = "не разобрали время"
        row.needs_review = True
        return row

    row.ok = True
    return row


def run(programs, markers: live.Markers | None = None,
        sports: sport.Sports | None = None,
        league_sports: dict[str, str] | None = None,
        pair_sports: dict[str, str] | None = None) -> list[Row]:
    markers = markers or live.load()
    sports = sports or sport.load()
    if league_sports is None:
        league_sports = leagues.sports_map()
    if pair_sports is None:
        pair_sports = leagues.pair_sports()
    return [classify(p, markers, sports, league_sports, pair_sports)
            for p in programs]

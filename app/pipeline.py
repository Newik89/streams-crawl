# -*- coding: utf-8 -*-
"""Сборка: страница → готовые строки ленты (ТЗ разд. 5, шаги 3–5).

Здесь три шага пайплайна, которые одинаковы для всех сайтов:

    парсер сайта  →  отсев (app/live.py)  →  вид спорта (app/sport.py)  →  время

Что делает каждый — написано в своём модуле. Здесь только порядок и то, что
получается на выходе: строка `Row`, у которой уже есть время в UTC и в Киеве,
пара команд и понятная причина, если событие не взяли.

Вид спорта («наш или чужой») решается в ОДНОМ месте — `sport.Sports.decide`,
десять правил по номерам. `classify` для него только собирает улики: текст
строки, пару, ответ эталона flashscore (`app/reference.py`), лигу из словаря
лиг, подсказку владельца. Номер сработавшего правила остаётся в строке
(`Row.sport_rule`).

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

from . import daytime, leagues, live, names, sport
from .parsers import Program
from .reference import Reference


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
    sport_source: str = ""         # откуда буква: ref (эталон flashscore) |
                                   # word (слово на сайте) | league (лига в
                                   # словаре) | women | hint
    sport_rule: int = 0            # номер сработавшего правила из
                                   # `sport.Sports.decide`
    sport_group: str = ""          # чужой вид спорта словами («хоккей») —
                                   # вкладка «Other Sport» (владелец 03.10)
    team_word: str = ""            # слово чужого вида, признанное именем
                                   # команды из пары («Le Mans», 06.10)
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
             pair_sports: dict[str, str] | None = None,
             reference: Reference | None = None) -> Row:
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
    # Пол по одной стороне (владелец 28.09, #3535): женская команда с
    # мужской не играет, и если хоть одна сторона женская — вся пара
    # женская. Возраст так НЕ переносим: в EFL Trophy «Chelsea U21» честно
    # играет со взрослым Wycombe
    клуб_спорт = ""
    if row.home and row.away:
        клуб_спорт = leagues.women_team(row.home) or leagues.women_team(row.away)
        женская = [("W" in names.category(x).split()) for x in (row.home, row.away)]
        if any(женская) or клуб_спорт:
            row.home = leagues.with_category(row.home, "W")
            row.away = leagues.with_category(row.away, "W")

    # ── Вид спорта. Здесь только собираются улики; само решение — в одном
    # месте, `sport.Sports.decide`, там правила записаны по номерам ────────
    # что сайт пишет о матче сам (без описания) и весь текст строки
    head = " ".join(x for x in (program.title, program.sport_raw,
                                program.league_raw) if x)
    text = " ".join(x for x in (head, program.description) if x)
    # эталон flashscore: знает ли он эту пару в это время (правило 2)
    by_ref = reference.sport_of(row.home, row.away, row.start_kyiv) \
        if reference is not None else ""
    # эталон знает хоть одну сторону как команду (правило 3: «пара похожа
    # на матч»)
    ref_team = reference is not None and any(
        reference.knows_team(side) for side in (verdict.home, verdict.away))
    # лига из словаря лиг (правило 6): `data/dictionaries.json` едет в git
    # и есть и у обхода
    league = None
    for key in (row.league, program.league_raw, program.sport_raw):
        letter = (league_sports or {}).get(" ".join(key.lower().split()))
        if letter:
            league = (letter, key)
            break
    # подсказка владельца для этой пары (правило 8; страница «Названия»,
    # раздел «Вид спорта») — пока не вышел её срок
    hint = (pair_sports or {}).get(f"{row.home} - {row.away}".strip())
    by_hint = hint[0] if hint and hint_fresh(hint[1], row.start_kyiv) else ""

    decision = sports.decide(text, head, (verdict.home, verdict.away),
                             ref=by_ref, ref_team=ref_team, league=league,
                             club=клуб_спорт,
                             hint=by_hint,
                             # месяц строки: турнир не в свой месяц — запись
                             # (правило 1, раздел «сезоны» markers.json)
                             month=row.start_kyiv.month if row.start_kyiv else 0)
    letter = decision.letter
    row.sport_word = decision.word
    row.sport_source = decision.source
    row.sport_rule = decision.rule
    row.team_word = decision.team_word
    if letter == "-":
        row.reason = f"другой вид спорта: {decision.word}"
        row.sport_group = decision.group
        return row
    if letter is None:
        # ТЗ разд. 6: не определился — не в мусор, а владельцу на проверку
        row.reason = "вид спорта не определён"
        row.needs_review = True
        return row
    row.sport = letter
    if letter == "T" and (row.home, row.away) != (verdict.home, verdict.away):
        # Теннис: пол игрока задаёт турнир (WTA/ATP), к фамилии его не пишет
        # ни эталон flashscore, ни другие сайты. sportklub.hr кладёт в описание
        # «teniski turnir za žene» — и «Kraus W — Yastremska W» не сходилась с
        # эталонной «Kraus S. — Yastremska D.», все женские матчи сайта жили
        # без канона (#4597, владелец 04.10). Возраст оставляем как был.
        без_пола = " ".join(p for p in row.league_category.split() if p != "W")
        row.home = leagues.with_category(verdict.home, без_пола)
        row.away = leagues.with_category(verdict.away, без_пола)

    if row.start_utc is None:
        row.reason = "не разобрали время"
        row.needs_review = True
        return row

    row.ok = True
    return row


def run(programs, markers: live.Markers | None = None,
        sports: sport.Sports | None = None,
        league_sports: dict[str, str] | None = None,
        pair_sports: dict[str, str] | None = None,
        reference: Reference | None = None) -> list[Row]:
    """`reference` — эталон flashscore этого обхода (`app/reference.py`).
    Без него правило 2 (`sport.Sports.decide`) молчит, остальные работают."""
    markers = markers or live.load()
    sports = sports or sport.load()
    if league_sports is None:
        league_sports = leagues.sports_map()
    if pair_sports is None:
        pair_sports = leagues.pair_sports()
    return [classify(p, markers, sports, league_sports, pair_sports, reference)
            for p in programs]

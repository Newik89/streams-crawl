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

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import daytime, leagues, live, names, sport
from .parsers import Program
from .reference import Confirmed, Reference


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
    by_reference: str = ""         # эталон подтвердил эфир/пару/вид спорта:
                                   # «пара» или «одна сторона» (правило (в),
                                   # `Reference.confirm`, 20.10)
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


#: причины отсева, которые эталон вправе оспорить (правило (в)): сайт не
#: сказал «эфир» или пара не прочиталась. Слово записи, студия и стоп-слово —
#: прямые слова сайта, их не трогаем
ASK_REFERENCE_REASONS = ("нет маркера прямого эфира", "не видно пары команд")
#: что ставит отсев строке, эфир которой подтвердил эталон, а не сайт
REFERENCE_MARKER = "эталон"
#: сезон в подписи: «2003/04», «2019-2020», «1998/99». Прошлый сезон — это
#: классика, а не эфир: «Klasici Premijer Lige: Chelsea - Tottenham, 2003/04»
#: на Arena Sport 1 за полчаса до живого Chelsea — Tottenham эталон
#: подтвердил бы как эфир (проверка перед выкладкой, сбор #301, 20.10)
_SEASON = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[/–-]\s*(?:\d{2}|(?:19|20)\d{2})(?!\d)")


def past_season(text: str, when: datetime | None) -> bool:
    """Подпись называет ПРОШЛЫЙ сезон — показ не эфир. Текущий сезон
    начинается с июля: в марте 2026 «2025/26» — ещё текущий, в октябре 2026
    «2025/26» — уже прошлый. Год основания клуба («Grazer AK 1902») без
    второй половины сезоном не считается."""
    if when is None:
        return False
    current = when.year if when.month >= 7 else when.year - 1
    return any(int(m.group(1)) < current for m in _SEASON.finditer(text or ""))


def ask_reference(program: Program, verdict: live.Verdict,
                  reference: Reference | None, start_kyiv: datetime | None,
                  league_category: str = ""):
    """Правило (в): строку, которую отсев не взял (`verdict`), спрашиваем у
    эталона. Пару дают все читатели (`live.split_candidates`), и пара
    строки — догадка, которую эталон подтвердил как эфир
    (`Reference.confirm`), в порядке сторон эталона. Из нескольких
    подтверждённых берётся сошедшаяся ЦЕЛИКОМ («пара»), а не первая по
    порядку: у rtl «2. Bundesliga Live - Topspiel: 1. FC Nürnberg - 1. FC
    Kaiserslautern» первая догадка («2. Bundesliga Live» — «Topspiel: …»)
    сходилась «одной стороной», и игра уезжала на витрину с мусорным именем
    (проверка книги 064, 20.10). Возвращает (новый вердикт, ответ эталона)
    либо None — тогда строка решается, как раньше."""
    if reference is None or start_kyiv is None \
            or verdict.reason not in ASK_REFERENCE_REASONS:
        return None
    # прошлый сезон в подписи — классика, эталон не спрашиваем
    if past_season(" ".join(x for x in (program.title, program.match_raw,
                                        program.league_raw) if x), start_kyiv):
        return None
    # догадки — и из поля пары, и из заголовка: парсер кладёт в поле « »,
    # когда пары не нашёл, а заголовок её держит («Al Nassr-Al Neom», ipko)
    candidates: list[tuple[str, str]] = []
    for text in ((program.match_raw or "").strip(), (program.title or "").strip()):
        for pair in live.split_candidates(text):
            if pair not in candidates:
                candidates.append(pair)
    confirmed: list[tuple[str, str, Confirmed]] = []
    for home, away in candidates:
        # пол и возраст турнира — к догадке сразу: «Polska - Belgia» в женском
        # отборе должна сойтись с «Poland W — Belgium W», а не с мужской парой
        home = leagues.with_category(home, league_category)
        away = leagues.with_category(away, league_category)
        got = reference.confirm(home, away, start_kyiv)
        if got is not None:
            confirmed.append((home, away, got))
            if got.how == "пара":
                break                      # лучше не бывает
    if not confirmed:
        return None
    home, away, got = next((x for x in confirmed if x[2].how == "пара"), confirmed[0])
    if got.swapped:
        home, away = away, home
    # эфир угадан (эталоном, не словом сайта): дальше его проверяют те же
    # фильтры повторов, что и прочие угадайки (`parse_live.guessed`)
    program.extra["live_guess"] = True
    return (live.Verdict(True, "", live_marker=verdict.live_marker or REFERENCE_MARKER,
                         home=home, away=away), got)


def classify(program: Program, markers: live.Markers, sports: sport.Sports,
             league_sports: dict[str, str] | None = None,
             pair_sports: dict[str, str] | None = None,
             reference: Reference | None = None) -> Row:
    row = Row(program=program, ok=False,
              start_utc=daytime.to_utc(program.start),
              start_kyiv=daytime.to_kyiv(program.start))

    # Пол и возраст часто видны только по названию турнира, а команды на
    # сайте подписаны как обычно — считаем метку раньше отсева: она нужна и
    # вопросу эталону ниже (женскую пару с мужским матчем он не сведёт)
    row.league = leagues.clean(program.league_raw)
    row.league_category = leagues.category(
        " ".join(x for x in (program.league_raw, program.title,
                             program.description) if x))

    verdict = live.check(program, markers)
    row.live_marker = verdict.live_marker
    row.home, row.away = verdict.home, verdict.away
    confirmed = None
    if not verdict.ok:
        # Правило (в) починки самопроверки №13 (владелец 20.10): «не уверен —
        # спроси эталон» вместо списков по сайтам. Нет пометки эфира или
        # пара не прочиталась — пару ищут все читатели (`live.split_candidates`,
        # правило (г)), а эталон отвечает, эфир ли это (`Reference.confirm`:
        # матч с такой парой начинается рядом с показом). Эфир тогда
        # угаданный (`live_guess`) — его проверят те же фильтры повторов,
        # что и прочие угадайки. Слово записи, студию и стоп-слово эталон
        # не оспаривает: это сайт сказал прямо
        rescued = ask_reference(program, verdict, reference, row.start_kyiv,
                                row.league_category)
        if rescued is None:
            row.reason = verdict.reason
            return row
        verdict, confirmed = rescued
        row.live_marker = verdict.live_marker
        row.home, row.away = verdict.home, verdict.away
        row.by_reference = confirmed.how
    rescued = confirmed is not None        # эфир строке дал эталон, не сайт

    # Дописываем метку турнира к именам, иначе женский матч склеится с
    # мужским (правило проекта: лишний ` W` лучше потерянного).
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
    # эталон flashscore: знает ли он эту пару в это время (правило 2). Не на
    # 95, а на 85 (и в окне эфира, а не ±3 ч) — тоже спрашиваем (правило (в):
    # «вид неясен → совпало с эталоном»), но только ПАРОЙ ЦЕЛИКОМ: одна
    # твёрдая сторона вид спорта не решает («PSG - Lens» при эталонном
    # «PSG - Le Mans» — другая вторая команда, эталон молчит; тест правила 2).
    # Исключение — строка, которую эталон уже признал эфиром своего матча
    # (`rescued`): раз это показ того матча, вид спорта — его
    by_ref = reference.sport_of(row.home, row.away, row.start_kyiv) \
        if reference is not None else ""
    if not by_ref and reference is not None:
        if confirmed is None:
            confirmed = reference.confirm(row.home, row.away, row.start_kyiv)
        if confirmed is not None and (rescued or confirmed.how == "пара"):
            by_ref = confirmed.entry.get("sport") or "F"
            row.by_reference = row.by_reference or confirmed.how
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

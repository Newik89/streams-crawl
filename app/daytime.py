# -*- coding: utf-8 -*-
"""Время расписания: ТВ-сутки, переход через полночь, перевод в Киев.

ТЗ разд. 7. Два непохожих случая:

* Сайт отдал **абсолютное** время — ISO со смещением (`tv.nova.cz`) или
  UNIX-метку (`sporttv.pt`). Тогда часовой пояс источника не нужен вообще,
  и правило перехода через полночь тоже: время уже однозначное.
* Сайт отдал **настенное** время (`14:30` на `nova.bg`, `6:00` на
  `teleman.pl`). Тогда день берём из адреса страницы, пояс — из карточки
  источника, а полночь разбираем правилом ниже.

**Правило полуночи.** ТВ-сутки идут примерно с 06:00 до 06:00: страница за
29.08 заканчивается блоками `01:30` и `03:30`, и это уже 30.08. Разведка
подтвердила такую разметку на обоих сайтах с настенным временем.
Идём по странице сверху вниз и, как только время заметно меньше
предыдущего, прибавляем сутки. Шаг назад меньше `НАЛОЖЕНИЕ` — не полночь,
а две передачи сетки наложились (teleman 06.10: `5:00`, затем `2:45` той же
ночи; `3:30`, затем `3:15`) — раньше такой шаг уводил остаток страницы на
сутки вперёд.

**Хвост прошлого вечера (06.10, #4224).** Страница дня бывает начата с
передачи, которая идёт СЕЙЧАС: teleman.pl, открытый в 23:50 по Варшаве,
отдал за 06.10 сперва `23:00` (это ещё 05.10), потом `1:00 … 20:35 … 23:00`
и `1:00 … 5:30` следующей ночи. Прочитав первую строку как 06.10, весь день
уехал на 07.10. Признак: после ПЕРВОЙ полуночи страница доходит до дня
(`ДЕНЬ_НАЧАЛСЯ`, полдень и позже) — значит, за полночью идут целые сутки
дня страницы, а до неё был вчерашний вечер, и отсчёт начинается с `day - 1`.
У обычной страницы (`6:00 … 23:45`, `0:00 … 4:00`) и у остатка дня
(nova.bg вечером: `23:00`, `0:30`, `2:00`) за полночью только ночь — они
читаются как раньше.

**Окно страницы (07.10, flashscore).** Бывает страница дня, которая честно
показывает и края соседних суток: flashscore.mobi за 10.10 начинает блок
лиги с `23:00` 09.10 и заканчивает `00:15` 11.10, а матчи у полуночи стоят
на обеих страницах. Такому сайту `walk_day` передаёт `window` — с какого
часа накануне и до какого часа после страница ещё показывает. Тогда день
первой строки выбирается не по `ДЕНЬ_НАЧАЛСЯ`, а по окну: из двух прочтений
(«первая строка в день страницы» и «первая строка накануне») берётся то,
при котором в окно попадает больше строк; поровну — день самой страницы.
Порядок внутри такой страницы строгий (сайт сортирует по началу), поэтому
полуночью там считается любой шаг назад: `overlap=1`.

**Сегодня — по часам сайта.** Относительный день (`dziś`, `?d=1`, «0-й
день») сайт считает по своему поясу, а GitHub живёт по UTC: в 22:30 UTC
в Варшаве уже завтра. `today(tz)` даёт дату в поясе сайта; всё время на
выходе разбора — со смещением, в Киев его переводит `to_kyiv`.

Своих регулярок для времени здесь нет — разбор строки берётся из
`app/timemarks.py`, как договорились в `PLAN.md`.
"""

from __future__ import annotations

from datetime import date as _date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import timemarks

KYIV = ZoneInfo("Europe/Kyiv")
#: шаг назад по времени меньше этого (минуты) — не полночь, а наложение
#: передач в сетке. Настоящая полночь — шаг с вечера на ночь, часов на 15+
НАЛОЖЕНИЕ = 4 * 60
#: час, до которого страница доходит за первой полуночью, только если за
#: полночью целые сутки: тогда до полуночи был вчерашний вечер (шапка)
ДЕНЬ_НАЧАЛСЯ = 12


def parse_hhmm(raw: str) -> tuple[int, int] | None:
    """`14:30`, `6:00`, `21h10`, `05 :58` → (14, 30). Не время — None."""
    marks = timemarks.find(timemarks.normalize(raw))
    if not marks:
        return None
    h, m = marks[0].split(":")
    return int(h), int(m)


def today(tz: str | None) -> _date:
    """Какое сегодня число на часах сайта (пояс `tz`; нет пояса — UTC)."""
    return datetime.now(ZoneInfo(tz) if tz else timezone.utc).date()


def walk_day(raw_times, day: _date, tz: str | None, *,
             overlap: int = НАЛОЖЕНИЕ,
             window: tuple[int, int] | None = None):
    """Настенное время страницы за `day` → список моментов со смещением.

    На вход — время в том порядке, в каком оно стоит на странице. Значение,
    которое меньше предыдущего, считается уже следующими сутками.
    Нераспознанное время даёт `None` на своём месте, чтобы список не съезжал.

    * `overlap` — шаг назад меньше этого (минуты) не полночь, а наложение
      передач (шапка). Сайту со строгим порядком — `1`: полночь любой шаг.
    * `window` — окно страницы `(с, до)` в минутах: страница дня `D`
      показывает время с минуты `с` дня `D-1` до минуты `до` дня `D+1`
      (шапка, «Окно страницы»). Без окна страница, начатая хвостом
      прошлого вечера, узнаётся правилом `ДЕНЬ_НАЧАЛСЯ`.
    """
    zone = ZoneInfo(tz) if tz else timezone.utc
    marks = [parse_hhmm(raw or "") for raw in raw_times]
    # сколько полуночей прошло к каждой строке
    passed: list[int] = []
    shift = 0
    prev: tuple[int, int] | None = None
    for hm in marks:
        if hm is not None:
            if prev is not None and _minutes(prev) - _minutes(hm) >= overlap:
                shift += 1
            prev = hm
        passed.append(shift)
    if window is not None:
        day += timedelta(days=_start_by_window(marks, passed, window))
    elif any(hm is not None and n == 1 and hm[0] >= ДЕНЬ_НАЧАЛСЯ
             for hm, n in zip(marks, passed)):
        day -= timedelta(days=1)          # до первой полуночи — вчерашний вечер
    out: list[datetime | None] = []
    for hm, n in zip(marks, passed):
        if hm is None:
            out.append(None)
            continue
        naive = datetime.combine(day + timedelta(days=n),
                                 datetime.min.time()).replace(hour=hm[0], minute=hm[1])
        # fold=0: в ночь перевода стрелок берём первое из двух одинаковых
        # значений — расписание печатают по «обычному» ходу часов.
        out.append(naive.replace(tzinfo=zone, fold=0))
    return out


def walk_programs(programs: list, day: _date, tz: str | None) -> list:
    """Дата каждой строки страницы за `day` — по правилу полуночи
    `walk_day`, отдельно по каждому каналу в порядке страницы. Время суток
    строки не меняется, меняется только дата (и `extra["day"]`).

    Для сеток, где раньше стояло жёсткое «час < 6 → следующий день» (07.10,
    сбор #205): ntvplus и trt.net.tr начинают страницу передачей, идущей в
    начале суток (`02:50` 06.10 на странице 06.10 уезжало на 07.10),
    oneplaysport и sport5 отдают календарные сутки с `00:20`, а rts.rs
    кончает страницу `05:43` следующего утра (порог 5 ставил её на сегодня).
    """
    by_channel: dict[str, list] = {}
    for prg in programs:
        if prg.start is not None:
            by_channel.setdefault(prg.channel_raw, []).append(prg)
    for rows in by_channel.values():
        clock = [prg.start.strftime("%H:%M") for prg in rows]
        for prg, moment in zip(rows, walk_day(clock, day, tz)):
            prg.start = moment
            if isinstance(prg.extra, dict) and "day" in prg.extra:
                prg.extra["day"] = moment.date().isoformat()
    return programs


def _start_by_window(marks, passed, window: tuple[int, int]) -> int:
    """В какой день стоит первая строка: `0` — в день страницы, `-1` —
    накануне. Правила (шапка, «Окно страницы»):

    1. Каждое прочтение раскладывает строки по суткам: строка после `n`
       полуночей стоит в день `первая + n`.
    2. Считаем, сколько строк попадает в окно страницы: с минуты `с`
       накануне до минуты `до` следующих суток.
    3. Берём прочтение, где таких строк больше; поровну — день страницы.
    """
    since, until = window
    lo, hi = -24 * 60 + since, 24 * 60 + until    # минуты от полуночи дня D

    def inside(first_day: int) -> int:
        return sum(1 for hm, n in zip(marks, passed) if hm is not None
                   and lo <= (first_day + n) * 24 * 60 + _minutes(hm) < hi)

    return -1 if inside(-1) > inside(0) else 0


def _minutes(hm: tuple[int, int]) -> int:
    return hm[0] * 60 + hm[1]


def to_utc(moment: datetime | None) -> datetime | None:
    return moment.astimezone(timezone.utc) if moment else None


def to_kyiv(moment: datetime | None) -> datetime | None:
    return moment.astimezone(KYIV) if moment else None


def from_unix_ms(value) -> datetime | None:
    """`1787616000000` → момент в UTC. Так время отдаёт `sporttv.pt`."""
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def from_iso(value: str | None) -> datetime | None:
    """`2026-08-29T17:10:00+02:00` → момент со смещением (`tv.nova.cz`)."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else None

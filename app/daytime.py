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
Идём по странице сверху вниз и, как только время меньше предыдущего,
прибавляем сутки. Так не нужно угадывать порог: важен сам разрыв.

Своих регулярок для времени здесь нет — разбор строки берётся из
`app/timemarks.py`, как договорились в `PLAN.md`.
"""

from __future__ import annotations

from datetime import date as _date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import timemarks

KYIV = ZoneInfo("Europe/Kyiv")


def parse_hhmm(raw: str) -> tuple[int, int] | None:
    """`14:30`, `6:00`, `21h10`, `05 :58` → (14, 30). Не время — None."""
    marks = timemarks.find(timemarks.normalize(raw))
    if not marks:
        return None
    h, m = marks[0].split(":")
    return int(h), int(m)


def walk_day(raw_times, day: _date, tz: str | None):
    """Настенное время страницы за `day` → список моментов со смещением.

    На вход — время в том порядке, в каком оно стоит на странице. Значение,
    которое меньше предыдущего, считается уже следующими сутками.
    Нераспознанное время даёт `None` на своём месте, чтобы список не съезжал.
    """
    zone = ZoneInfo(tz) if tz else timezone.utc
    out: list[datetime | None] = []
    shift = 0
    prev: tuple[int, int] | None = None
    for raw in raw_times:
        hm = parse_hhmm(raw or "")
        if hm is None:
            out.append(None)
            continue
        if prev is not None and hm < prev:
            shift += 1
        prev = hm
        naive = datetime.combine(day + timedelta(days=shift),
                                 datetime.min.time()).replace(hour=hm[0], minute=hm[1])
        # fold=0: в ночь перевода стрелок берём первое из двух одинаковых
        # значений — расписание печатают по «обычному» ходу часов.
        out.append(naive.replace(tzinfo=zone, fold=0))
    return out


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

# -*- coding: utf-8 -*-
"""raspored.hrt.hr — Хорватия, HRT. Расписание обычным текстом.

Сам сайт на Next.js и в HTML пуст (был отложен 01.09), но у HRT остался
старый текстовый вывод — он открывается обычным запросом и разбирается в
десять строк:

    https://raspored.hrt.hr/format/text.xml?mreza={номер}&datum={YYYY-MM-DD}

    HRT - HTV 1, utorak, 01.09.2026.

    06:26 TV kalendar (kod. na sat.)
    06:45 Dobro jutro, Hrvatska
    …

Первая строка — канал и дата, дальше «время + название». Номера сети:
`2` — HTV 1, `3` — HTV 2 (там футбол), `4` — HTV 3; `1` и `5` пусты.

Отдельного поля эфира нет, но пометки в строке есть (аудит 06.10): `(R)` —
повтор, «…, prijenos» в конце — прямая трансляция. Их читаем как пометку
сайта (`site_says`); строки без пометки (`Nogomet: Dinamo - Hajduk`)
угадываем первым показом пары.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import Program, mark_first_show, register, site_says

DOMAIN = "raspored.hrt.hr"
TZ = "Europe/Zagreb"

_HEAD = re.compile(r"^HRT\s*-\s*(.+?),\s*[^,]+,\s*(\d{2})\.(\d{2})\.(\d{4})")
_ROW = re.compile(r"^(\d{1,2}):(\d{2})\s+(.+)$")
#: служебные хвосты сайта: `(R)`, `(kod. na sat.)`, `(12/60)`
_TAIL = re.compile(r"\s*\((?:R|kod\.[^)]*|\d+/\d+)\)", re.I)
#: пометка сайта «повтор» — `(R)` (repriza) хвостом строки; в обходе #205
#: у 300+ строк. До 06.10 хвост просто срезался, и повтор, оказавшийся
#: первым показом пары, получал эфир угадыванием
SAYS_REPEAT = re.compile(r"\(R\)")
#: пометка сайта «прямая трансляция» — слово `prijenos` последним в строке:
#: «Zadar: Misa, prijenos», «…, KD V. Lisinski, prijenos»
SAYS_LIVE = re.compile(r",\s*prijenos\s*$", re.I)


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs ", " : "):
        home, s, away = text.partition(sep)
        if s and home.strip() and away.strip():
            return f"{home.strip()} - {away.strip()}"
    return " "


def _split(title: str) -> tuple[str, str]:
    """`Nogomet: Dinamo - Hajduk` → (вид спорта/лига, пара)."""
    head, sep, rest = title.partition(":")
    if sep and _pair(rest).strip():
        return head.strip(), _pair(rest)
    return "", _pair(title)


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    lines = [line.strip() for line in html.splitlines()]

    channel = ""
    first = day
    for line in lines:
        head = _HEAD.match(line)
        if head:
            channel = head.group(1).strip()
            first = _date(int(head.group(4)), int(head.group(3)),
                          int(head.group(2)))
            break
    if not channel or (channels and channel not in channels):
        return []

    out: list[Program] = []
    previous = None
    shift = 0
    for line in lines:
        row = _ROW.match(line)
        if not row:
            continue
        title = _TAIL.sub("", row.group(3)).strip(" ,")
        if not title:
            continue
        minutes = int(row.group(1)) * 60 + int(row.group(2))
        if previous is not None and minutes < previous:
            shift += 1
        previous = minutes
        start = None
        if first is not None:
            start = datetime(first.year, first.month, first.day,
                             int(row.group(1)), int(row.group(2)),
                             tzinfo=zone) + timedelta(days=shift)
        league, pair = _split(title)
        program = Program(
            channel_raw=channel, title=title, start=start,
            raw_time=f"{row.group(1)}:{row.group(2)}",
            league_raw=league, sport_raw=league, match_raw=pair,
            source_url=url,
            extra={"day": start.date().isoformat() if start else ""},
        )
        # пометки HRT в самой строке (аудит 06.10): `(R)` — повтор,
        # «…, prijenos» в конце — прямая трансляция (мессы, концерты, матчи)
        if SAYS_REPEAT.search(row.group(3)):
            site_says(program, False)
        elif SAYS_LIVE.search(title):
            site_says(program, True, "prijenos")
        out.append(program)
    return mark_first_show(out, "uživo")

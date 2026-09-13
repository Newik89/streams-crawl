# -*- coding: utf-8 -*-
"""unian.tv — Украина, сайт телеканала УНІАН. Один канал, день в адресе.

    https://unian.tv/{DD.MM.YYYY}

Сетка лежит прямо в HTML, разбирать нечего:

    div.tv-item
      div.tv-item__time    `18:45`
      div.tv-item__title   `Пожежники Чикаго`
      div.tv-item__type    `Серіал` / `Програма`
      div.tv-item__now     `Зараз в ефірі` — идёт прямо сейчас

Канал новостной, футбола на нём не бывает, но выключать источник без слова
владельца нельзя (правило проекта), а стоит он один запрос в день.

`Зараз в ефірі` — это «идёт сейчас», а не «прямая трансляция»: в маркеры
эфира не годится, кладём его в описание как есть.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "unian.tv"
TZ = "Europe/Kyiv"
CHANNEL = "УНІАН"

_URL_DAY = re.compile(r"/(\d{2})\.(\d{2})\.(\d{4})")


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs "):
        home, s, away = text.partition(sep)
        if s and home.strip() and away.strip():
            return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    if channels and CHANNEL not in channels:
        return []
    zone = ZoneInfo(tz or TZ)
    found = _URL_DAY.search(url or "")
    first = _date(int(found.group(3)), int(found.group(2)),
                  int(found.group(1))) if found else day

    out: list[Program] = []
    previous = None
    shift = 0
    for item in HTMLParser(html).css("div.tv-item"):
        time_node = item.css_first("div.tv-item__time")
        title_node = item.css_first("div.tv-item__title")
        if not time_node or not title_node:
            continue
        raw_time = time_node.text(strip=True)
        stamp = re.match(r"^(\d{1,2}):(\d{2})$", raw_time)
        title = title_node.text(strip=True)
        if not stamp or not title:
            continue
        minutes = int(stamp.group(1)) * 60 + int(stamp.group(2))
        if previous is not None and minutes < previous:
            shift += 1
        previous = minutes
        kind = item.css_first("div.tv-item__type")
        now = item.css_first("div.tv-item__now")
        start = None
        if first is not None:
            start = datetime(first.year, first.month, first.day,
                             int(stamp.group(1)), int(stamp.group(2)),
                             tzinfo=zone) + timedelta(days=shift)
        out.append(Program(
            channel_raw=CHANNEL, title=title, start=start, raw_time=raw_time,
            description=" ".join(x.text(strip=True) for x in (kind, now) if x),
            match_raw=_pair(title), source_url=url,
            extra={"day": start.date().isoformat() if start else ""},
        ))
    return out

# -*- coding: utf-8 -*-
"""tv8.com.tr — Турция, канал TV8. Один канал, день в адресе.

    https://www.tv8.com.tr/yayin-akisi              — сегодня
    https://www.tv8.com.tr/yayin-akisi/{DD-MM-YYYY} — другой день

Сетка лежит обычной таблицей:

    td.stream-time   `06:30`
    td.stream-name   `Tuzak` + span.stream-type `Dizi` (жанр)

Блок `ld+json` с `BroadcastEvent` на странице всего один — только идущая
сейчас передача, поэтому опираемся на таблицу, а из блока берём лишь
подтверждение имени канала.

Пометки эфира у сайта нет — эфиром считаем первый показ пары, домен внесён
в `REPEAT_GUESS_DOMAINS`.
"""

from __future__ import annotations

import html as _html
import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "tv8.com.tr"
TZ = "Europe/Istanbul"
CHANNEL = "TV8"

_URL_DAY = re.compile(r"/yayin-akisi/(\d{2})-(\d{2})-(\d{4})")
_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")


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

    tree = HTMLParser(html)
    out: list[Program] = []
    previous = None
    shift = 0
    for row in tree.css("div.stream-list-table tr"):
        clock = row.css_first("td.stream-time")
        name = row.css_first("td.stream-name")
        if clock is None or name is None:
            continue
        stamp = _TIME.match(clock.text(strip=True))
        kind_node = name.css_first("span.stream-type")
        kind = kind_node.text(strip=True) if kind_node else ""
        title = _html.unescape(name.text(strip=True))
        if kind:
            title = title.replace(kind, " ")
        title = " ".join(title.split())
        if not stamp or not title:
            continue
        minutes = int(stamp.group(1)) * 60 + int(stamp.group(2))
        if previous is not None and minutes < previous:
            shift += 1
        previous = minutes
        start = None
        if first is not None:
            start = datetime(first.year, first.month, first.day,
                             int(stamp.group(1)), int(stamp.group(2)),
                             tzinfo=zone) + timedelta(days=shift)
        out.append(Program(
            channel_raw=CHANNEL, title=title, start=start,
            raw_time=clock.text(strip=True), description=kind,
            match_raw=_pair(title), source_url=url,
            extra={"day": start.date().isoformat() if start else ""},
        ))
    return mark_first_show(out, "canlı")

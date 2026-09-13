# -*- coding: utf-8 -*-
"""aspor.com.tr — Турция, канал A Spor. Одна страница, текущий день.

`https://www.aspor.com.tr/yayin-akisi` держит сетку одного канала. Вкладки
других дней на странице есть, но они пустые: сами передачи приходят только
за сегодня, поэтому источник заведён «канальной сеткой» (один запрос).

    li[data-time-start="2026-09-01T08:00:00"]
      span.tmd-broadcastList__programItem__time   `08:00`
      span.tmd-broadcastList__programItem__name   `Sabah Sporu`
        span…name-badge--presenter                `Canlı` — прямой эфир

Время в `data-time-start` идёт без пояса — это местное турецкое.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "aspor.com.tr"
TZ = "Europe/Istanbul"
CHANNEL = "A Spor"

_STAMP = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})")
_LIVE = re.compile(r"canl[ıi]", re.I)


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs ", " / "):
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
    out: list[Program] = []
    for item in HTMLParser(html).css("li.tmd-broadcastList__programItem"):
        stamp = _STAMP.match(item.attributes.get("data-time-start") or "")
        name_node = item.css_first("span.tmd-broadcastList__programItem__name")
        if not stamp or name_node is None:
            continue
        # `css` у selectolax отдаёт и сам узел, если он подходит под селектор,
        # поэтому берём именно пометки, а не все вложенные `span`
        badges = [b.text(strip=True) for b in name_node.css(
            "span.tmd-broadcastList__programItem__name-badge")]
        title = name_node.text(strip=True)
        for badge in badges:                    # заголовок без пометок
            if badge:
                title = title.replace(badge, " ")
        title = " ".join(title.split())
        if not title:
            continue
        start = datetime(*(int(stamp.group(i)) for i in range(1, 6)),
                         tzinfo=zone)
        live = next((b for b in badges if _LIVE.search(b)), "")
        out.append(Program(
            channel_raw=CHANNEL, title=title, start=start,
            raw_time=f"{stamp.group(4)}:{stamp.group(5)}",
            live_raw=live, match_raw=_pair(title), source_url=url,
            extra={"day": start.date().isoformat()},
        ))
    return out

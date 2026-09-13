# -*- coding: utf-8 -*-
"""bnt.bg — Болгария, уровень B (разметка HTML), канал BNT 3 (спортивный).

Одна страница `/program/bnt3` — «сетка»: 14 дней (неделя назад и вперёд)
в контейнерах `div.tab-holder-YYYYMMDD`, один запрос на всё.

    a.program-box
      span.hour     `17:05` (бывает без ведущего нуля)
      span.name     `Футбол: България - Англия, среща от световното …`
      span.type     `пряко предаване от Панагюрище` | `обзор` | пусто

Маркер эфира — `type` начинается с «пряко» (проба 31.08: записи идут с
«обзор»/пустым). Пара — в `name` после вида спорта с двоеточием, до
запятой. Дни календарные (полночь внутри контейнера дня не пересекается —
ночные строки лежат в контейнере своего дня).
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "bnt.bg"
TZ = "Europe/Sofia"

_HOLDER = re.compile(r"tab-holder-(\d{8})")
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    channel = "BNT 3"
    if channels and channel not in channels:
        return []

    out: list[Program] = []
    for holder in HTMLParser(html).css("div[class*=tab-holder-]"):
        m = _HOLDER.search(holder.attributes.get("class") or "")
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        for box in holder.css("a.program-box"):
            hour = box.css_first("span.hour")
            name = box.css_first("span.name")
            typ = box.css_first("span.type")
            hm = _HHMM.match(hour.text(strip=True) if hour else "")
            title = name.text(strip=True) if name else ""
            if not hm or not title:
                continue
            kind = typ.text(strip=True) if typ else ""
            live = kind.lower().startswith("пряко")
            sport_word, _, rest = title.partition(":")
            rest = rest.strip()
            pair = rest.split(",", 1)[0].strip() if " - " in rest.split(",", 1)[0] else " "
            out.append(Program(
                channel_raw=channel, title=title,
                start=datetime(d.year, d.month, d.day,
                               int(hm.group(1)), int(hm.group(2)), tzinfo=zone),
                raw_time=hour.text(strip=True),
                description=kind[:200],
                league_raw=rest.split(",", 1)[1].strip()[:120]
                if pair != " " and "," in rest else "",
                sport_raw=sport_word if rest else "",
                live_raw="пряко" if live else "",
                match_raw=pair, source_url=url,
                extra={"day": d.isoformat()},
            ))
    return out

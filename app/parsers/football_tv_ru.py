# -*- coding: utf-8 -*-
"""football-tv.ru — Россия, телеканал «Футбол» (Tilda-сайт).

Главная — карточки ближайших прямых трансляций канала, один запрос:

    .t-card__uptitle    `28.08.2026 в 14:30` (московское время)
    .t-card__title > a  `Далянь - Бейцзин Гоань`

Карточки без даты («подборка хайлайтов…») — реклама, мимо. Всё с датой —
анонс эфира, отдельного маркера нет: канал публикует только прямые.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "football-tv.ru"
TZ = "Europe/Moscow"

_CARD = re.compile(
    r't-card__uptitle[^>]*>\s*(\d{2})\.(\d{2})\.(\d{4})\s+в\s+'
    r'(\d{1,2}):(\d{2})\s*</div>.*?t-card__title[^>]*>.*?>\s*([^<]+?)\s*</a>',
    re.S)


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    channel = "Футбол"
    if channels and channel not in channels:
        return []
    out: list[Program] = []
    for m in _CARD.finditer(html):
        dd, mo, yy, hh, mi, title = m.groups()
        title = title.strip()
        try:
            start = datetime(int(yy), int(mo), int(dd), int(hh), int(mi),
                             tzinfo=zone)
        except ValueError:
            continue
        pair = title if " - " in title else " "
        out.append(Program(
            channel_raw=channel, title=title, start=start,
            raw_time=f"{hh}:{mi}",
            sport_raw="футбол",
            live_raw="live broadcast",
            match_raw=pair, source_url=url,
            extra={"day": start.date().isoformat()},
        ))
    return out

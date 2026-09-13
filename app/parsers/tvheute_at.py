# -*- coding: utf-8 -*-
"""tvheute.at — австрийский телегид; у нас закрывает немецкие ARD и ZDF.

Прямые сайты не дались: у ARD телегид спрятан за хеш-классами, у ZDF —
за graphql с ключом. Аналог нашёлся в `iptv-org/epg` (02.09, по просьбе
владельца закрыть дыры): `tvheute.at` отдаёт серверу готовый HTML-кусок
на канал и день:

    /part/channel-shows/partial/{слаг}/{DD-MM-YYYY}   (ard, zdf, …)

Основная сетка — таблица: в `<tr>` время `td.start-col time[datetime]`
(`2026-09-03 09:00`), заголовок `strong` (полный — в его атрибуте `title`),
подзаголовок `span.sub` (у матчей там пара), жанр `span.type`
(Film/Info/Serie/Show/Sport). Врезка «highlights» сверху дублирует часть
строк — дедуп по (время, заголовок). Маркера эфира нет: первый показ
пары + `REPEAT_GUESS_DOMAINS`.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "tvheute.at"
TZ = "Europe/Vienna"

_URL_SLUG = re.compile(r"/partial/([a-z0-9]+)/")
_NAMES = {"ard": "Das Erste", "zdf": "ZDF"}
_PAIR_SEPS = (" - ", " – ", " gegen ")


def _pair(text: str) -> str:
    for sep in _PAIR_SEPS:
        if sep in text:
            home, _, away = text.partition(sep)
            home, away = home.strip(), away.strip()
            if home and away and (len(home.split()) >= 2
                                  or len(away.split()) >= 2
                                  or sep != " - "):
                return f"{home} - {away}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    m = _URL_SLUG.search(url or "")
    channel = _NAMES.get(m.group(1) if m else "", "tvheute")
    tree = HTMLParser(html)

    zone = ZoneInfo(tz or TZ)
    out: list[Program] = []
    seen: set[tuple] = set()
    for row in tree.css("tr"):
        time_node = row.css_first("td.start-col time")
        title_node = row.css_first("strong")
        if not time_node or not title_node:
            continue
        stamp = time_node.attributes.get("datetime") or ""
        title = " ".join((title_node.attributes.get("title")
                          or title_node.text()).split())
        if not stamp or not title:
            continue
        try:
            begin = datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(
                tzinfo=zone)
        except ValueError:
            continue
        sub_node = row.css_first("span.sub")
        sub = " ".join(sub_node.text().split()) if sub_node else ""
        genre_node = row.css_first("span.type")
        genre = " ".join(genre_node.text().split()) if genre_node else ""
        key = (stamp, title)
        if key in seen:
            continue
        seen.add(key)
        pair = _pair(title)
        league = sub if pair != " " else ""
        if pair == " " and sub:
            pair = _pair(sub)
            league = title if pair != " " else ""
        out.append(Program(
            channel_raw=channel, title=f"{title}: {sub}" if sub else title,
            start=begin,
            raw_time=begin.strftime("%H:%M"),
            description=sub,
            league_raw=league[:120],
            sport_raw=genre,
            match_raw=pair,
            source_url=url, extra={"day": begin.date().isoformat()},
        ))
    return mark_first_show(out, "live")

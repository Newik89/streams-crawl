# -*- coding: utf-8 -*-
"""tvpassport.com — телегид США/Канады; у нас — Fox Soccer Plus.

Официального EPG у FOX нет, расписание канала держат телегиды; tvpassport
отдал страницу серверу с первой пробы (02.09) и даёт самые честные данные —
всё в data-атрибутах строки `div.list-group-item`:

    data-st           `2026-09-01 05:00:00` — начало в поясе страницы
                      (`#timezone_selector`, по умолчанию America/New_York)
    data-showName     `Italian Serie B Soccer` — турнир
    data-episodeTitle `Pisa vs. Catanzaro` — пара
    data-live         `1` у прямого эфира, data-repeat `1` у повтора

Адрес на канал и день: `/tv-listings/stations/{слаг}/{YYYY-MM-DD}`
(подсмотрено в iptv-org/epg).
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "tvpassport.com"
TZ = "America/New_York"

_URL_SLUG = re.compile(r"/stations/([a-z0-9-]+)/")
_NAMES = {"fox-soccer-plus": "Fox Soccer Plus",
          "tsn1-hd": "TSN1", "tsn2-hd": "TSN2", "tsn3-hd": "TSN3",
          "tsn4-hd": "TSN4", "tsn5-hd": "TSN5"}


def _pair(text: str) -> str:
    for sep in (" vs. ", " vs ", " Vs. "):
        if sep in text:
            home, _, away = text.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    tree = HTMLParser(html)
    sel = tree.css_first("#timezone_selector option[selected]")
    zone = ZoneInfo(tz or (sel.attributes.get("value") if sel else None) or TZ)
    m = _URL_SLUG.search(url or "")
    channel = _NAMES.get(m.group(1) if m else "", "tvpassport")

    out: list[Program] = []
    for row in tree.css("div.list-group-item"):
        a = row.attributes
        stamp = a.get("data-st") or ""
        league = " ".join((a.get("data-showname") or "").split())
        episode = " ".join((a.get("data-episodetitle") or "").split())
        if not stamp or not league:
            continue
        try:
            begin = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=zone)
        except ValueError:
            continue
        pair = _pair(episode)
        live = "live" if (a.get("data-live") or "").strip() else ""
        if (a.get("data-repeat") or "").strip():
            live = ""
        out.append(Program(
            channel_raw=channel,
            title=f"{league}: {episode}" if episode else league,
            start=begin,
            raw_time=begin.strftime("%H:%M"),
            league_raw=league[:120],
            live_raw=live,
            match_raw=pair,
            source_url=url, extra={"day": begin.date().isoformat()},
        ))
    # data-live проставлен далеко не всегда: непомеченным повтором строкам
    # эфир достаётся первым показом пары (домен в REPEAT_GUESS_DOMAINS)
    return mark_first_show(out, "live")

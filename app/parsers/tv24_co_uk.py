# -*- coding: utf-8 -*-
"""tv24.co.uk — Великобритания, TNT Sports (АПЛ, ЛЧ, MotoGP) на канал и день.

Сайт найден через `iptv-org/epg` после того, как `tntsports.co.uk` закрылся
403-м. Ручка: `/x/channel/{слаг}/0/{YYYY-MM-DD}` — кусок HTML без каркаса.
Слаги из `iptv-org` устарели (`bt-sport-1` отвечает «Channel Off Air»),
живые проверены пробой 02.09: `tnt-sports-1-hd` … `tnt-sports-4-hd`;
`tnt-sports-5-hd` пока «off air» — пятый ищется под другим слагом.

Строка: `li > a.program`:

    span.time   `6:00am` — 12-часовое, `/0/` в адресе — смещение пояса,
                поэтому время читаем как UTC (так же его читает iptv-org)
    h3          заголовок; у прямого эфира внутри `<span class="live">LIVE</span>`
    span.desc   подзаголовок — здесь пара матча: `Liverpool v Forest`
    p           длинное описание; пары ИЗ НЕГО НЕ БРАТЬ — там перечисления
                анонсов («including Chelsea v Brighton, Spurs v Newcastle»)
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta, timezone

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "tv24.co.uk"
TZ = "UTC"

_TIME = re.compile(r"^(\d{1,2}):(\d{2})\s*(am|pm)$", re.I)
_URL_DAY = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_URL_SLUG = re.compile(r"/x/channel/([a-z0-9-]+)/")


def _channel_from_url(url: str) -> str:
    m = _URL_SLUG.search(url or "")
    if not m:
        return "tv24"
    words = m.group(1).removesuffix("-hd").split("-")
    return " ".join(w.upper() if w in ("tnt",) else w.capitalize()
                    for w in words)


def _pair(text: str) -> str:
    for sep in (" v ", " vs ", " V "):
        if sep in text:
            home, _, away = text.partition(sep)
            home, away = home.strip(" .,"), away.strip(" .,")
            if home and away:
                return f"{home} - {away}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    m = _URL_DAY.search(url or "")
    day = (_date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m
           else day or _date.today())
    channel = _channel_from_url(url)
    tree = HTMLParser(html)

    out: list[Program] = []
    offset = 0
    prev: tuple | None = None
    for item in tree.css("a.program"):
        time_node = item.css_first("span.time")
        title_node = item.css_first("h3")
        if not time_node or not title_node:
            continue
        hm = _TIME.match(" ".join(time_node.text().split()))
        if not hm:
            continue
        live = bool(title_node.css_first("span.live"))
        title = " ".join(title_node.text().replace("LIVE", " ").split())
        if not title:
            continue
        hour = int(hm.group(1)) % 12 + (12 if hm.group(3).lower() == "pm" else 0)
        minute = int(hm.group(2))
        if prev is not None and (hour, minute) < prev:
            offset += 1
        prev = (hour, minute)
        desc_node = item.css_first("span.desc")
        desc = " ".join(desc_node.text().split()) if desc_node else ""
        # пара — из заголовка или подзаголовка, длинное описание не смотрим;
        # когда пара в подзаголовке, турниром служит заголовок
        # (`Serie A Football` + `Napoli v Como`)
        pair = _pair(title)
        league = desc if pair != " " else ""
        if pair == " ":
            pair = _pair(desc)
            league = title if pair != " " else ""
        d = day + timedelta(days=offset)
        out.append(Program(
            channel_raw=channel, title=title,
            start=datetime(d.year, d.month, d.day, hour, minute,
                           tzinfo=timezone.utc),
            raw_time=f"{hour:02d}:{minute:02d}",
            description=desc,
            league_raw=league[:120],
            live_raw="LIVE" if live else "",
            match_raw=pair,
            source_url=url, extra={"day": d.isoformat()},
        ))
    return out

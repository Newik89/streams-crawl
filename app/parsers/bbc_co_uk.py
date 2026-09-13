# -*- coding: utf-8 -*-
"""bbc.co.uk — Британия, расписания BBC. Адрес на канал и день.

    https://www.bbc.co.uk/schedules/{pid}/{YYYY}/{MM}/{DD}

`pid` — постоянный код канала (`p00fzl6p` — BBC One London). Разметка
разговорчивая и стабильная, время лежит машинным:

    h3.broadcast__time[content="2026-09-01T06:00:00+01:00"]
    span.programme__title      `Breakfast`
    span.programme__subtitle   `01/09/2026` или название матча
    p.programme__synopsis      описание

Имя канала — из `<title>`: `BBC One London - Schedules, Tuesday 1 September`.

Прямой эфир BBC отдельным словом не помечает; футбол у них идёт под
названиями вида `Football: Team A v Team B`, поэтому пару ищем и в
подзаголовке, а эфиром считаем первый показ (`mark_first_show`).
"""

from __future__ import annotations

import html as _html
import re
from datetime import date as _date, datetime

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "bbc.co.uk"
TZ = "Europe/London"

_TITLE_TAIL = re.compile(r"\s*-\s*Schedules.*$", re.I)
_PAIR = re.compile(r"\s+v\.?\s+|\s+vs\.?\s+|\s+-\s+", re.I)


def _pair(text: str) -> str:
    parts = _PAIR.split(text or "", maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return f"{parts[0].strip()} - {parts[1].strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    tree = HTMLParser(html)
    head = tree.css_first("title")
    channel = _TITLE_TAIL.sub("", _html.unescape(
        head.text(strip=True) if head else "")).strip()
    if not channel:
        return []
    if channels and channel not in channels:
        return []

    out: list[Program] = []
    for item in tree.css("div.broadcast"):
        clock = item.css_first("h3.broadcast__time")
        title_node = item.css_first("span.programme__title")
        if clock is None or title_node is None:
            continue
        stamp = clock.attributes.get("content") or ""
        try:
            start = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        title = _html.unescape(title_node.text(strip=True))
        if not title:
            continue
        subtitle_node = item.css_first("span.programme__subtitle")
        synopsis_node = item.css_first("p.programme__synopsis")
        subtitle = _html.unescape(
            subtitle_node.text(strip=True)) if subtitle_node else ""
        pair = _pair(title)
        if not pair.strip():
            pair = _pair(subtitle)
        out.append(Program(
            channel_raw=channel, title=" ".join(x for x in (title, subtitle) if x),
            start=start, raw_time=f"{start:%H:%M}",
            description=_html.unescape(
                synopsis_node.text(strip=True)) if synopsis_node else "",
            league_raw=title if pair.strip() and pair not in title else "",
            match_raw=pair, source_url=url,
            extra={"day": start.date().isoformat()},
        ))
    return mark_first_show(out, "live")

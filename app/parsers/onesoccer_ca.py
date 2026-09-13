# -*- coding: utf-8 -*-
"""onesoccer.ca — Канада: футбольный канал OneSoccer (CanPL, сборные).

`/schedule` рисуется скриптом (браузер, `needs_js=1`): после догрузки на
странице виджет Opta с ближайшими матчами, которые канал покажет. Всё в
выдаче — трансляции, маркер эфира ставим каждой строке.

Карточка `div.Opta-fixture`: `data-date` — unix-миллисекунды начала
(абсолютные), два `div.Opta-TeamName` — хозяева и гости.
"""

from __future__ import annotations

from datetime import date as _date, datetime, timezone

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "onesoccer.ca"
TZ = "UTC"
CHANNEL = "OneSoccer"


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    tree = HTMLParser(html)
    out: list[Program] = []
    seen: set[tuple] = set()
    for card in tree.css("div.Opta-fixture"):
        stamp = card.attributes.get("data-date")
        names = [" ".join(n.text().split())
                 for n in card.css("div.Opta-TeamName")]
        names = [n for n in names if n]
        if not stamp or len(names) < 2:
            continue
        try:
            begin = datetime.fromtimestamp(int(stamp) / 1000, tz=timezone.utc)
        except (ValueError, OSError):
            continue
        pair = f"{names[0]} - {names[1]}"
        key = (stamp, pair)
        if key in seen:
            continue
        seen.add(key)
        out.append(Program(
            channel_raw=CHANNEL, title=pair,
            start=begin,
            raw_time=begin.strftime("%H:%M"),
            sport_raw="Soccer",
            live_raw="live",
            match_raw=pair,
            source_url=url, extra={"day": begin.date().isoformat()},
        ))
    return out

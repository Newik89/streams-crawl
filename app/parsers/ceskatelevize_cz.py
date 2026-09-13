# -*- coding: utf-8 -*-
"""ceskatelevize.cz — Чехия, уровень B (разметка HTML), канал ČT sport.

Дневная сетка: `/tv-program/{DD}.{MM}.{YYYY}/` — все каналы ЧТ за день,
нам нужен блок `programmeBlockChannel4` (ČT sport). Частично закрывает
чешскую дыру: `tv.nova.cz` (Nova Sport) отрезан Cloudflare-ом.

Разметка передачи (проба 31.08):

    li.programme
      span.progTime               `18:50`
      h4 a.progTitle              турнир: `ME ve volejbalu žen 2026`
      h5                          пара: `Česko - Švédsko` (или дисциплина)
      .progInfo p                 `Přímý přenos osmifinálového utkání (Brno)`
                                  или `Záznam 2. utkání …`
      span[title="Živě"]          значок эфира — честный, у `Záznam` его нет

День телегида идёт 06:00 → 06:00: ночные строки после полуночи относятся к
следующей дате — время монотонно, перелом ловит `daytime.walk_day`.
"""

from __future__ import annotations

from datetime import date as _date

from selectolax.parser import HTMLParser

from .. import daytime
from . import Program, register

DOMAIN = "ceskatelevize.cz"
TZ = "Europe/Prague"

#: номер блока → имя канала; спортивный у ЧТ один
CHANNELS = {"4": "ČT sport"}


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    day = day or _date.today()
    tree = HTMLParser(html)

    out: list[Program] = []
    for num, channel in CHANNELS.items():
        if channels and channel not in channels:
            continue
        rows = []
        for blk in tree.css(f"div.programmeBlockChannel{num}"):
            for li in blk.css("li.programme"):
                t = li.css_first("span.progTime")
                h4 = li.css_first("h4 a")
                if not t or not h4:
                    continue
                h5 = li.css_first("h5")
                p = li.css_first(".progInfo p")
                rows.append({
                    "raw_time": t.text(strip=True),
                    "title": h4.text(strip=True),
                    "sub": h5.text(strip=True) if h5 else "",
                    "desc": p.text(strip=True) if p else "",
                    "zive": li.css_first('span[title="Živě"]') is not None,
                })
        moments = daytime.walk_day([r["raw_time"] for r in rows], day, tz or TZ)
        for row, moment in zip(rows, moments):
            sub = row["sub"]
            pair = sub if " - " in sub else " "
            live = row["zive"] or row["desc"].lower().startswith("přímý přenos")
            out.append(Program(
                channel_raw=channel,
                title=row["title"], start=moment, raw_time=row["raw_time"],
                description=row["desc"][:300],
                league_raw=row["title"] if pair != " " else "",
                sport_raw="",
                live_raw="přímý přenos" if live else "",
                match_raw=pair, source_url=url,
                extra={"sub": sub},
            ))
    return out

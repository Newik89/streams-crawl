# -*- coding: utf-8 -*-
"""skysports.com — Великобритания, уровень B (разметка HTML).

Одна страница `/watch/sport-on-sky` — все ПРЯМЫЕ трансляции каналов Sky
на ближайшие ~2 дня (проба 31.08: два дня, 31 событие). Источник-«сетка»:
один запрос на всё, каналы Sky Sports нигде больше не покрыты.

Разметка (по порядку документа):

    h3.text-h4                      день: `Mon 31st August` (год не пишут)
    h3.box.text-h5                  вид спорта секции: Football / Tennis / …
    ul.row-table.event              матч: col1 strong — хозяева,
                                    col2 — время `20:00`, col3 strong — гости
    p.event-detail                  `Premier League, Sky Sports Main Event
                                    (18:30), Sky Sports+ (19:45)` — лига (без
                                    скобок) и каналы со временем ВКЛЮЧЕНИЯ

Что важно:

* страница и есть список прямых эфиров — маркер `live broadcast` у всех;
* канал в скобках даёт время НАЧАЛА ПЕРЕДАЧИ (пре-шоу), матч — в col2:
  берём время матча, канал — только именем;
* каналов на матч несколько → отдаём по `Program` на канал, склейка
  сведёт их в одну игру;
* время лондонское, день без года — год от дня обхода (стык декабря
  чинит `_year_for` из парсера Arena).
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register
from .tvarenaprogram_com import _year_for

DOMAIN = "skysports.com"
TZ = "Europe/London"

_DAY = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"))}
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_CHANNEL = re.compile(r"([^,()]+?)\s*\((\d{1,2}:\d{2})\)")


def _classes(node) -> str:
    return node.attributes.get("class") or ""


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    anchor = day or datetime.now(ZoneInfo(tz or TZ)).date()
    zone = ZoneInfo(tz or TZ)
    out: list[Program] = []

    cur_day: _date | None = None
    cur_sport = ""
    pending: tuple[str, str, str] | None = None   # (home, time, away)

    for node in HTMLParser(html).root.traverse():
        cls = _classes(node)
        if node.tag == "h3" and "text-h4" in cls:
            m = _DAY.search(node.text(strip=True))
            mo = _MONTHS.get(m.group(2).lower()[:12]) if m else None
            cur_day = _year_for(int(m.group(1)), mo, anchor) if m and mo else None
            pending = None
        elif node.tag == "h3" and "text-h5" in cls:
            cur_sport = node.text(strip=True)
            pending = None
        elif node.tag == "ul" and "event" in cls.split():
            cols = node.css("li")
            home = away = when = ""
            for li in cols:
                c = _classes(li)
                strong = li.css_first("strong")
                if "col1" in c and strong:
                    home = strong.text(strip=True)
                elif "col3" in c and strong:
                    away = strong.text(strip=True)
                elif "col2" in c:
                    when = li.text(strip=True)
            pending = (home, when, away)
        elif node.tag == "p" and "event-detail" in cls:
            if not pending or cur_day is None:
                continue
            home, when, away = pending
            pending = None
            hm = _HHMM.match(when)
            if not home or not away or not hm:
                continue
            text = node.text(strip=True)
            league = text.split(",", 1)[0].strip()
            if "(" in league:
                league = ""
            found = _CHANNEL.findall(text)
            start = datetime(cur_day.year, cur_day.month, cur_day.day,
                             int(hm.group(1)), int(hm.group(2)), tzinfo=zone)
            for chan, _t in (found or [("Sky Sports", "")]):
                chan = chan.strip(" ,")
                if channels and chan not in channels:
                    continue
                out.append(Program(
                    channel_raw=chan, title=f"{home} vs {away}",
                    start=start, raw_time=when,
                    league_raw=league, sport_raw=cur_sport,
                    live_raw="live broadcast",
                    match_raw=f"{home} - {away}", source_url=url,
                    extra={"day": cur_day.isoformat()},
                ))
    return out

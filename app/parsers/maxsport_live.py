# -*- coding: utf-8 -*-
"""maxsport.live — Болгария, уровень B (разметка HTML), каналы MAX Sport.

Одна страница `/tv-guide/` — сетка: вкладки-каналы (MAX Sport 1–4 берём,
Max Movie / Max One — кино, мимо) и по 7 дней в каждой. Один запрос на всё.

Разметка (копия 28.08, подтверждено пробой 31.08):

    .elementor-tab-title.elementor-tab-desktop-title    имена каналов, по
                                                        порядку = вкладкам
    .elementor-tab-content                              вкладка канала
      .month-day                                        дата дня: `31.08`
      .day-guides-list                                  передачи этого дня
        .guides-item  .guides-item-time / -title        `20:30` / заголовок

Маркер эфира — заголовок начинается с `ПРЯКО` («прямо» по-болгарски):
`ПРЯКО, Ла Лига: Расинг Сантандер - Елче`. Лига — до двоеточия, пара —
после. Записи идут без приставки. Дата без года — год от дня обхода.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register
from .tvarenaprogram_com import _year_for

DOMAIN = "maxsport.live"
TZ = "Europe/Sofia"

_DDMM = re.compile(r"^(\d{1,2})\.(\d{1,2})\.?$")
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_LIVE = re.compile(r"^\s*ПРЯКО\b[\s,:]*", re.I)

#: кино-вкладки того же сайта — не спорт
_SKIP = {"max movie", "max one"}


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    anchor = day or datetime.now(ZoneInfo(tz or TZ)).date()
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)

    names = [t.text(strip=True)
             for t in tree.css(".elementor-tab-title.elementor-tab-desktop-title")]
    contents = tree.css(".elementor-tab-content")

    out: list[Program] = []
    for name, content in zip(names, contents):
        if name.lower() in _SKIP:
            continue
        if channels and name not in channels:
            continue
        dates = []
        for d in content.css(".month-day"):
            m = _DDMM.match(d.text(strip=True))
            dates.append(_year_for(int(m.group(1)), int(m.group(2)), anchor)
                         if m else None)
        for d, block in zip(dates, content.css(".day-guides-list")):
            if d is None:
                continue
            for item in block.css(".guides-item"):
                t = item.css_first(".guides-item-time")
                title_node = item.css_first(".guides-item-title")
                hm = _HHMM.match(t.text(strip=True) if t else "")
                title = title_node.text(strip=True) if title_node else ""
                if not hm or not title:
                    continue
                live = bool(_LIVE.match(title))
                clean = _LIVE.sub("", title).strip()
                league, _, tail = clean.partition(":")
                tail = tail.strip()
                pair = tail if " - " in tail else " "
                out.append(Program(
                    channel_raw=name, title=clean,
                    start=datetime(d.year, d.month, d.day,
                                   int(hm.group(1)), int(hm.group(2)),
                                   tzinfo=zone),
                    raw_time=t.text(strip=True),
                    league_raw=league.strip() if pair != " " else "",
                    sport_raw="",
                    live_raw="пряко" if live else "",
                    match_raw=pair, source_url=url,
                    extra={"day": d.isoformat()},
                ))
    return out

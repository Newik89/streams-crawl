# -*- coding: utf-8 -*-
"""oneplaysport.cz — Чехия; 12 спортканалов одной страницей на день.

**Чем ценен.** Здесь открыто лежат `Nova Sport 1–6` — те самые, ради которых
мы бились с `tv.nova.cz` и упёрлись в Cloudflare (он режет и GitHub, и
DigitalOcean, см. `ГРАБЛИ.md`). OnePlay пускает обычным запросом.

Адрес: `https://oneplaysport.cz/program?date=ГГГГ-ММ-ДД` — один запрос отдаёт
все каналы за день, поэтому источник заведён «дневной сеткой»
(`DAY_GRID_DOMAINS`), а не адресом на канал.

Разметка ровная, без скриптов:

    div.channel
      div.mobile-channel > img[alt]     `Nova Sport 3` — имя канала
      div.channel-content
        a.program-item[data-start][data-end]
          span.date   `21:30 - 00:30`
          span.name   `CHL: AC Sparta Praha-SK Slavia Praha`

Заголовок устроен как `ЛИГА: Хозяева-Гости`: лига до двоеточия, пара — после,
разделитель дефис **без пробелов**. Пробельный дефис тоже встречается, поэтому
проверяем оба, а на всякий случай и тире. У `Nova Sport` двоеточия обычно нет
(`Borussia Dortmund - Hamburger SV`) — там пару ищем прямо в заголовке.

Маркера эфира сайт не даёт вовсе — все строки идут без `live_raw`, отсев
работает по паре команд и лиге.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "oneplaysport.cz"
TZ = "Europe/Prague"

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_DATE_IN_URL = re.compile(r"date=(\d{4})-(\d{2})-(\d{2})")


def _pair(rest: str) -> str:
    """`AC Sparta Praha-SK Slavia Praha` → `AC Sparta Praha - SK Slavia Praha`.
    Дефис у OnePlay стоит без пробелов, но встречается и с ними.

    Голый дефис берём с оговоркой: он же стоит внутри названий передач
    (`TIKI-TAKA`, `Penaltový král`). Пара засчитывается, только если хотя бы
    у одной стороны есть пробел, то есть название команды из двух слов."""
    for sep in (" - ", " – "):
        if sep in rest:
            home, _, away = rest.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    for sep in ("-", "–"):
        if sep in rest:
            home, _, away = rest.partition(sep)
            home, away = home.strip(), away.strip()
            if home and away and (" " in home or " " in away):
                return f"{home} - {away}"
            break
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    got = _DATE_IN_URL.search(url or "")
    if got:
        day = _date(int(got.group(1)), int(got.group(2)), int(got.group(3)))
    day = day or _date.today()
    tree = HTMLParser(html)

    out: list[Program] = []
    for block in tree.css("div.channel"):
        logo = block.css_first("img[alt]")
        if not logo:
            continue
        channel = (logo.attributes.get("alt") or "").strip()
        if not channel or (channels and channel not in channels):
            continue
        for item in block.css("a.program-item"):
            start = (item.attributes.get("data-start") or "").strip()
            hm = _HHMM.match(start)
            name = item.css_first("span.name")
            title = name.text(strip=True) if name else ""
            if not hm or not title:
                continue
            league, _, rest = title.partition(":")
            rest = rest.strip()
            # «CHL» здесь — спонсорское имя чешской Chance Liga (футбол),
            # а не хоккейная Champions Hockey League: голое CHL в лиге
            # улетало в «чужой вид спорта», и вся Chance Liga с каналов
            # Oneplay Sport пропадала с витрины (12.09)
            if league.strip().upper() == "CHL":
                league = "Chance Liga"
            # `ЛИГА: Хозяева-Гости` — пара после двоеточия, но у Nova Sport
            # двоеточия часто нет вовсе (`Borussia Dortmund - Hamburger SV`),
            # и тогда пару ищем прямо в заголовке
            pair = _pair(rest) if rest else _pair(title)
            # телегид-день идёт с утра: «00:30» на странице за 31.08 — это
            # уже ночь на 1 сентября
            d = day + timedelta(days=1) if int(hm.group(1)) < 6 else day
            out.append(Program(
                channel_raw=channel, title=title,
                start=datetime(d.year, d.month, d.day,
                               int(hm.group(1)), int(hm.group(2)), tzinfo=zone),
                raw_time=start,
                league_raw=league.strip() if rest else "",
                match_raw=pair, source_url=url,
                extra={"day": d.isoformat(),
                       "end": (item.attributes.get("data-end") or "").strip()},
            ))
    return mark_first_show(out, "live")

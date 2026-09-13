# -*- coding: utf-8 -*-
"""trtavaz.com.tr — Турция, один канал TRT Avaz, страница на день.

`/yayin-akisi/{YYYY-MM-DD}` — обычный HTML, браузер не нужен. Дату берём
из адреса страницы, не из аргумента.

Строка расписания — `<tr>` таблицы:

    <span class="sp01">21</span><span class="sp02">:00</span>   — время
    <a href="/program/..." title="...">Название</a>             — заголовок

Телегид-день начинается в ~06:00 и заканчивается под утро следующего:
уменьшение времени в ходе списка — переход через полночь.

Спорт у TRT Avaz редкий (канал общий, тюркоязычные страны), заголовок
матча — в духе `Futbol: Türkiye - Azerbaycan`; пара после двоеточия.
Маркера эфира сайт не даёт — эфиром помечаем первый показ пары
(`mark_first_show`), домен в `REPEAT_GUESS_DOMAINS`.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, time as _time, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "trtavaz.com.tr"
TZ = "Europe/Istanbul"
CHANNEL = "TRT Avaz"

_URL_DAY = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs ", " VS "):
        if sep in text:
            home, _, away = text.partition(sep)
            home, away = home.strip(), away.strip()
            if home and away:
                return f"{home} - {away}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    m = _URL_DAY.search(url or "")
    day = (_date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m
           else day or _date.today())
    tree = HTMLParser(html)

    out: list[Program] = []
    offset = 0
    prev: _time | None = None
    for row in tree.css("tr"):
        hh = row.css_first("span.sp01")
        mm = row.css_first("span.sp02")
        link = row.css_first("td a[title]")
        if not hh or not mm or not link:
            continue
        try:
            start_t = _time(int(hh.text().strip()),
                            int(mm.text().strip().lstrip(":")))
        except ValueError:
            continue
        title = " ".join(link.text().split()) or (link.attributes.get("title") or "")
        if not title:
            continue
        if prev is not None and start_t < prev:
            offset += 1
        prev = start_t
        # `Futbol: Türkiye - Azerbaycan` — до двоеточия вид спорта/турнир
        head, sep, tail = title.partition(":")
        rest = tail.strip() if sep and tail.strip() else title
        league = head.strip() if sep and tail.strip() else ""
        d = day + timedelta(days=offset)
        out.append(Program(
            channel_raw=CHANNEL, title=title,
            start=datetime(d.year, d.month, d.day, start_t.hour,
                           start_t.minute, tzinfo=zone),
            raw_time=f"{start_t.hour:02d}:{start_t.minute:02d}",
            league_raw=league[:120],
            match_raw=_pair(rest),
            source_url=url, extra={"day": d.isoformat()},
        ))
    return mark_first_show(out, "canlı")

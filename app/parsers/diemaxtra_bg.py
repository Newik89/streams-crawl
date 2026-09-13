# -*- coding: utf-8 -*-
"""diemaxtra.nova.bg — Болгария, спортивный пакет Diema Xtra.

Разведка отмечала сайт как «нужен браузер», но расписание открывается
обычным запросом по адресу канала, и в ответе лежит **вся неделя**:

    https://diemaxtra.nova.bg/schedule             — Diema Xtra
    https://diemaxtra.nova.bg/diemasport/schedule  — Diema Sport
    https://diemaxtra.nova.bg/diemasport2/schedule — Diema Sport 2
    https://diemaxtra.nova.bg/diemasport3/schedule — Diema Sport 3

Дни разложены по вкладкам, даты подписаны по-болгарски рядом с ярлыком:

    a[href="#tuesday"] span.day `вт`  span.date `01 септ`
    div#tuesday ul.tv_content li
        p.time         `15.30`  (время через точку)
        p.title        `ЦСКА - Черно море`
        p.description  `7 кръг, Футбол: efbet Лига 2026/2027, директно`

В описании сразу тур, вид спорта, лига и маркер эфира — как у `nova.bg`
(тот же вещатель, но разметка другая, поэтому парсер свой). `директно` —
эфир, `/n/` — пометка повтора, эфиром такие строки не считаются.

Год в подписи не указан: берём текущий, а если получилась дата больше чем
на полгода назад — значит, неделя переходит в следующий год.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "diemaxtra.nova.bg"
TZ = "Europe/Sofia"

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
        "sunday")

#: болгарские сокращения месяцев в подписи вкладки: `01 септ`
MONTHS = {"ян": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "юни": 6,
          "юли": 7, "авг": 8, "септ": 9, "сеп": 9, "окт": 10, "ное": 11,
          "дек": 12}

_TIME = re.compile(r"^(\d{1,2})[.:](\d{2})$")
_DATE = re.compile(r"^(\d{1,2})\s+([а-я]+)", re.I)
# `7 кръг, Футбол: efbet Лига 2026/2027, директно`
_SPORT_LEAGUE = re.compile(r"([^,:]+)\s*:\s*([^,]+)")


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs "):
        home, s, away = text.partition(sep)
        if s and home.strip() and away.strip():
            return f"{home.strip()} - {away.strip()}"
    return " "


def _tab_dates(tree, today: _date) -> dict[str, _date]:
    """Ярлык вкладки → дата. Год в подписи не пишут, достраиваем сами."""
    out: dict[str, _date] = {}
    for link in tree.css('a[data-toggle="tab"]'):
        name = (link.attributes.get("href") or "").lstrip("#")
        node = link.css_first("span.date")
        if name not in DAYS or node is None:
            continue
        found = _DATE.match(node.text(strip=True))
        if not found:
            continue
        month = next((m for key, m in MONTHS.items()
                      if found.group(2).lower().startswith(key)), 0)
        if not month:
            continue
        day = _date(today.year, month, int(found.group(1)))
        if (today - day).days > 180:        # неделя перешла в новый год
            day = _date(today.year + 1, month, int(found.group(1)))
        elif (day - today).days > 180:
            day = _date(today.year - 1, month, int(found.group(1)))
        out[name] = day
    return out


def _channel(tree, url: str) -> str:
    """Имя канала: у Diema Xtra оно только в адресе раздела."""
    for key, name in (("diemasport3", "Diema Sport 3"),
                      ("diemasport2", "Diema Sport 2"),
                      ("diemasport", "Diema Sport")):
        if key in (url or ""):
            return name
    return "Diema Xtra"


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)
    channel = _channel(tree, url)
    if channels and channel not in channels:
        return []

    dates = _tab_dates(tree, day or _date.today())
    out: list[Program] = []
    for name in DAYS:
        pane = tree.css_first(f"div#{name}")
        first = dates.get(name)
        if pane is None or first is None:
            continue
        previous = None
        shift = 0
        for item in pane.css("ul.tv_content li"):
            clock = item.css_first("p.time")
            title_node = item.css_first("p.title")
            if clock is None or title_node is None:
                continue
            stamp = _TIME.match(clock.text(strip=True))
            title = title_node.text(strip=True)
            if not stamp or not title:
                continue
            minutes = int(stamp.group(1)) * 60 + int(stamp.group(2))
            if previous is not None and minutes < previous:
                shift += 1          # вкладка перевалила за полночь
            previous = minutes
            note = item.css_first("p.description")
            description = note.text(strip=True) if note else ""
            sport = league = ""
            found = _SPORT_LEAGUE.search(description)
            if found:
                sport, league = found.group(1).strip(), found.group(2).strip()
            start = datetime(first.year, first.month, first.day,
                             int(stamp.group(1)), int(stamp.group(2)),
                             tzinfo=zone) + timedelta(days=shift)
            out.append(Program(
                channel_raw=channel, title=title, start=start,
                raw_time=clock.text(strip=True), description=description,
                league_raw=league, sport_raw=sport, match_raw=_pair(title),
                source_url=url, extra={"day": start.date().isoformat()},
            ))
    return out

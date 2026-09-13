# -*- coding: utf-8 -*-
"""movistarplus.es — Испания, телегид Movistar Plus+. Адрес на канал и день.

    https://www.movistarplus.es/programacion-tv/{slug}/{YYYY-MM-DD}

Спортивных каналов у площадки много (DAZN 1-4, M+ LaLiga 1-4, M+ Liga de
Campeones 1-5, M+ Deportes 1-7, Eurosport 1-2, Teledeporte, …) — слаги взяты
из разведки `recon/source_channels_draft.csv`.

Разметка простая и одинаковая для всех каналов:

    div.info-canal .titulo a      `Ver canal DAZN 1` — имя канала
    div.container_box
      li.genre                    `Deportes`
      li.title                    `Premier League (T26/27): Aston Villa - Arsenal`
      li.time                     `14:35`

Времена идут по возрастанию и в конце заворачиваются за полночь
(`23:30, 00:00, 04:53`) — всё, что после переворота, относится к следующей
дате. Дату страница словами не пишет, берём из адреса (её подставляет обход).

Маркера прямого эфира на странице нет вовсе — как у `ert.gr` и `oneplaysport.cz`.
Поэтому эфиром считаем первый показ пары (`mark_first_show`), а домен внесён
в `REPEAT_GUESS_DOMAINS` (`scripts/parse_live.py`), чтобы ночной повтор той же
пары из соседнего дня не попал в ленту.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "movistarplus.es"
TZ = "Europe/Madrid"

_URL_DAY = re.compile(r"/(\d{4})-(\d{2})-(\d{2})\b")
#: `(T26/27)`, `(T2026)` — номер сезона в заголовке, для пары он лишний
_SEASON = re.compile(r"\s*\(T[^)]*\)\s*")


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs ", " v "):
        home, s, away = text.partition(sep)
        if s and home.strip() and away.strip():
            return f"{home.strip()} - {away.strip()}"
    return " "


def _split(title: str) -> tuple[str, str]:
    """`Premier League (T26/27): Aston Villa - Arsenal` → (лига, пара)."""
    clean = _SEASON.sub(" ", title).strip()
    league, sep, rest = clean.partition(":")
    if sep and _pair(rest).strip():
        return league.strip(), _pair(rest)
    return "", _pair(clean)


def _day_from_url(url: str, day: _date | None) -> _date | None:
    found = _URL_DAY.search(url or "")
    if found:
        return _date(int(found.group(1)), int(found.group(2)), int(found.group(3)))
    return day


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)

    head = tree.css_first("div.info-canal .titulo a")
    channel = (head.text(strip=True) if head else "").removeprefix("Ver canal").strip()
    if not channel:
        return []
    if channels and channel.casefold() not in {c.casefold() for c in channels}:
        return []

    first = _day_from_url(url, day)
    out: list[Program] = []
    previous = None
    shift = 0
    for box in tree.css("div.container_box"):
        time_node = box.css_first("li.time")
        title_node = box.css_first("li.title")
        if not time_node or not title_node:
            continue
        raw_time = time_node.text(strip=True)
        stamp = re.match(r"^(\d{1,2}):(\d{2})$", raw_time)
        title = title_node.text(strip=True)
        if not stamp or not title:
            continue
        minutes = int(stamp.group(1)) * 60 + int(stamp.group(2))
        if previous is not None and minutes < previous:
            shift += 1          # список перевалил за полночь
        previous = minutes
        genre_node = box.css_first("li.genre")
        league, pair = _split(title)
        start = None
        if first is not None:
            start = datetime(first.year, first.month, first.day,
                             int(stamp.group(1)), int(stamp.group(2)),
                             tzinfo=zone) + timedelta(days=shift)
        out.append(Program(
            channel_raw=channel, title=title, start=start, raw_time=raw_time,
            league_raw=league,
            sport_raw=genre_node.text(strip=True) if genre_node else "",
            match_raw=pair, source_url=url,
            extra={"day": start.date().isoformat() if start else ""},
        ))
    return mark_first_show(out, "directo")


def list_channels(html: str) -> list[str]:
    """Все каналы площадки — из полосы логотипов сверху (`title` картинки)."""
    names: list[str] = []
    for node in HTMLParser(html).css("div.canalnumber img"):
        name = (node.attributes.get("title") or "").strip()
        if name and name not in names:
            names.append(name)
    return names

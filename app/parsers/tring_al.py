# -*- coding: utf-8 -*-
"""tring.al — Албания, уровень A (JSON внутри React-потока).

Одна страница `/kalendari-sportiv` — весь спортивный календарь каналов
Tring Sport (Serie A, Bundesliga и т.д.) на недели вперёд, один запрос.
Данные лежат в экранированном виде внутри RSC-потока:

    {\"id\":\"evt-001\",\"championship\":\"Serie A\",\"date\":\"2026-05-01\",
     \"time\":\"20:45\",\"event\":\"Pisa - Lecce\",\"channel\":\"Tring Sport 1\",…}

Поля идут в неизменном порядке — берём их регуляркой, JSON целиком не
восстанавливаем. Страница — календарь именно ТРАНСЛЯЦИЙ, отдельного
маркера нет: всё считается эфиром (прошедшее режет окно обхода), повторов
на странице не замечено. Время местное (Тирана).
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "tring.al"
TZ = "Europe/Tirane"

_EVENT = re.compile(
    r'\\"championship\\":\\"(?P<league>[^"\\]*)\\",'
    r'\\"date\\":\\"(?P<date>\d{4}-\d{2}-\d{2})\\",'
    r'\\"time\\":\\"(?P<time>\d{1,2}:\d{2})\\",'
    r'\\"event\\":\\"(?P<event>[^"\\]*)\\",'
    r'\\"channel\\":\\"(?P<channel>[^"\\]*)\\"')


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    out: list[Program] = []
    seen: set[tuple] = set()
    for m in _EVENT.finditer(html):
        channel = m.group("channel").strip()
        if channels and channel not in channels:
            continue
        key = (m.group("date"), m.group("time"), m.group("event"), channel)
        if key in seen:
            continue
        seen.add(key)
        try:
            d = _date.fromisoformat(m.group("date"))
            hh, mm = m.group("time").split(":")
            start = datetime(d.year, d.month, d.day, int(hh), int(mm),
                             tzinfo=zone)
        except ValueError:
            continue
        event = m.group("event").strip()
        pair = event if " - " in event else " "
        out.append(Program(
            channel_raw=channel, title=event, start=start,
            raw_time=m.group("time"),
            league_raw=m.group("league").strip() if pair != " " else "",
            sport_raw="",
            live_raw="live broadcast",
            match_raw=pair, source_url=url,
            extra={"day": m.group("date")},
        ))
    return out

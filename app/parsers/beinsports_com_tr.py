# -*- coding: utf-8 -*-
"""beinsports.com.tr — Турция, beIN SPORTS. Готовый JSON в разметке.

Это **не** `beinsports.com` (тот отложен владельцем, `ОТЛОЖЕНО.md` → ⛔),
а турецкий сайт того же вещателя: Süper Lig, Лига чемпионов, Лига Европы.

    https://beinsports.com.tr/yayin-akisi/{канал}/{день-недели}

День в адресе — не дата, а название дня по-турецки (`sali`), поэтому в
шаблон адреса поставлена метка `{WEEKDAY_TR}` (`app/urls.py`).
Каналы: `beinsports` (1), `beinsports-2`, `beinsports-3`, `beinsports-4`,
`bein-sports-haber` (13).

Расписание лежит в `__NEXT_DATA__`:

    props.pageProps.data = {"event_date": "2026-09-01",
      "listTvGuides": [{"channel_id": 1, "event_time": "12:00:00",
                        "name": "Kocaelispor - Fenerbahçe",
                        "related_match_name": null}, …]}

Пометки эфира у сайта нет вовсе, поэтому эфиром считаем первый показ пары
(домен внесён в `REPEAT_GUESS_DOMAINS`).
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, mark_first_show, register

DOMAIN = "beinsports.com.tr"
TZ = "Europe/Istanbul"

#: номер канала → имя, как его показывает сам сайт
CHANNELS = {1: "beIN SPORTS 1", 2: "beIN SPORTS 2", 3: "beIN SPORTS 3",
            4: "beIN SPORTS 4", 13: "beIN SPORTS HABER"}

_NEXT = re.compile(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_TIME = re.compile(r"^(\d{1,2}):(\d{2})")


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs "):
        home, s, away = text.partition(sep)
        if s and home.strip() and away.strip():
            return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    block = _NEXT.search(html)
    if not block:
        return []
    try:
        page = json.loads(block.group(1))["props"]["pageProps"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []

    data = page.get("data") or {}
    rows = data.get("listTvGuides") or []
    stamp = _DATE.match(str(data.get("event_date") or ""))
    if stamp:
        first = _date(int(stamp.group(1)), int(stamp.group(2)),
                      int(stamp.group(3)))
    else:
        first = day
    zone = ZoneInfo(tz or TZ)

    out: list[Program] = []
    previous = None
    shift = 0
    for row in rows:
        clock = _TIME.match(str(row.get("event_time") or ""))
        title = (row.get("name") or "").strip()
        if not clock or not title:
            continue
        channel = CHANNELS.get(row.get("channel_id"), "")
        if not channel or (channels and channel not in channels):
            continue
        minutes = int(clock.group(1)) * 60 + int(clock.group(2))
        if previous is not None and minutes < previous:
            shift += 1              # сетка перевалила за полночь
        previous = minutes
        start = None
        if first is not None:
            start = datetime(first.year, first.month, first.day,
                             int(clock.group(1)), int(clock.group(2)),
                             tzinfo=zone)
            if shift:
                from datetime import timedelta
                start += timedelta(days=shift)
        match = (row.get("related_match_name") or "").strip() or title
        out.append(Program(
            channel_raw=channel, title=title, start=start,
            raw_time=f"{clock.group(1)}:{clock.group(2)}",
            match_raw=_pair(match), source_url=url,
            extra={"day": start.date().isoformat() if start else ""},
        ))
    return mark_first_show(out, "canlı")

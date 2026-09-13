# -*- coding: utf-8 -*-
"""ziggosport.nl — Нидерланды, пакет Ziggo Sport. Готовый JSON на день.

Сама страница `/programmagids` рисует только шкалу времени (это и было
причиной отложить сайт). Данные лежат в кэше сайта, и указатель файлов
открыт:

    https://www.ziggosport.nl/cache/site/ZiggosportNL/json/epg/index.json
        ["epg-2026-09-01.json", "epg-2026-09-02.json", …]
    https://www.ziggosport.nl/cache/site/ZiggosportNL/json/epg/epg-{YYYY-MM-DD}.json

В дневном файле сразу **все семь каналов**:

    [{"channel": "Ziggo Sport 1",
      "programming": [{"title": "Rondo (herhaling)", "description": "…",
                       "live": false,
                       "dateStart": "2026-09-01T05:00:00+00:00"}, …]}]

Поле `live` — честный признак прямого эфира, берём его. Время в UTC.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime

from . import Program, register

DOMAIN = "ziggosport.nl"
TZ = "Europe/Amsterdam"

_PAIR = re.compile(r"\s+-\s+|\s+–\s+|\s+vs\.?\s+", re.I)


def _pair(text: str) -> str:
    parts = _PAIR.split(text or "", maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return f"{parts[0].strip()} - {parts[1].strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = json.loads(html)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    out: list[Program] = []
    for block in data:
        channel = (block.get("channel") or "").strip()
        if not channel or (channels and channel not in channels):
            continue
        for item in block.get("programming") or []:
            title = (item.get("title") or "").strip()
            stamp = item.get("dateStart") or ""
            if not title or not stamp:
                continue
            try:
                start = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            out.append(Program(
                channel_raw=channel, title=title, start=start,
                raw_time=f"{start:%H:%M}",
                description=(item.get("description") or "").strip(),
                league_raw=(item.get("event") or "") or "",
                sport_raw=(item.get("sportName") or "") or "",
                live_raw="live" if item.get("live") else "",
                match_raw=_pair(title), source_url=url,
                extra={"day": start.date().isoformat()},
            ))
    return out


def list_channels(html: str) -> list[str]:
    try:
        data = json.loads(html)
    except json.JSONDecodeError:
        return []
    names: list[str] = []
    for block in data if isinstance(data, list) else []:
        name = (block.get("channel") or "").strip()
        if name and name not in names:
            names.append(name)
    return names

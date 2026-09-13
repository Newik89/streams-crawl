# -*- coding: utf-8 -*-
"""dr.dk — Дания, открытый JSON платформы dr-massive.

Ручка нашлась в два шага (01–02.09): адрес — в бандле страницы гида, а id
канала — в самой странице, в ссылке «LIVE»: `/kanal/dr1_20875` → DR1 = 20875.
С кодами `dr1`/`dr2` ручка отвечает пустотой — нужны числовые id.

    https://prod95.dr-massive.com/api/schedules?channels={id}&date={YYYY-MM-DD}
        &hour=0&duration=24&device=web_browser&sub=Anonymous

Ответ: `[{channelId, schedules: [...]}]`; у передачи `startDate` (UTC, ISO),
честный флаг `live` и `item.title` / `item.description`. Спорт у DR редкий
(гандбол, велоспорт, сборные) — большинство строк отсеется по виду спорта,
это нормально.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime

from . import Program, register

DOMAIN = "dr.dk"
TZ = "Europe/Copenhagen"

#: id из ссылок `/kanal/…` на странице гида; имена — эфирные каналы DR
CHANNELS = {"20875": "DR1", "20876": "DR2"}


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    start = html.find("[")
    if start < 0:
        return []
    try:
        data = json.loads(html[start:html.rfind("]") + 1])
    except ValueError:
        return []

    out: list[Program] = []
    for block in data if isinstance(data, list) else []:
        channel = CHANNELS.get(str(block.get("channelId") or ""),
                               f"DR {block.get('channelId')}")
        if channels and channel not in channels:
            continue
        for row in block.get("schedules") or []:
            item = row.get("item") or {}
            title = " ".join((item.get("title") or "").split())
            raw_start = row.get("startDate") or ""
            if not title or not raw_start:
                continue
            try:
                begin = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            except ValueError:
                continue
            text = f"{title} {item.get('description') or ''}"
            pair = " "
            m = re.search(r"([A-ZÆØÅ][\w.ÆØÅæøå ]{1,40}?)\s*[-–]\s*"
                          r"([A-ZÆØÅ][\w.ÆØÅæøå ]{1,40})", title)
            if m:
                pair = f"{m.group(1).strip()} - {m.group(2).strip()}"
            out.append(Program(
                channel_raw=channel, title=title,
                start=begin,
                raw_time=raw_start[11:16],
                description=(item.get("description") or "")[:200],
                live_raw="live" if row.get("live") else "",
                match_raw=pair,
                source_url=url, extra={"day": raw_start[:10]},
            ))
    return out

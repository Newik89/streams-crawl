# -*- coding: utf-8 -*-
"""tvarenasport.com — Сербия, уровень A (инлайн-JSON в странице).

Одна страница `/tv-scheme` — всё расписание: 18 спортивных каналов Arena
(Premium 1–5, Sport 1–10, Tenis, Adrenalin, 1X2) на 7 дней вперёд. Дата и
канал в адрес не подставляются — источник-«сетка», один запрос на всё.

Внутри HTML лежит переменная:

    TV_SCHEMES = {"Arena Premium 1": {"days": {"2026-08-27": {"emisije":
        [{"content": "AEK - Levski", "time": "00:00",
          "category": "UEFA LIGA ŠAMPIONA - Kvalifikacije",
          "sport": "Fudbal", "description": "snimak"}, …]}}}, …};

Что важно (разведано агентом по копии 28.08, подтверждено счётчиком):

* **`description` — честный флаг**: `uzivo` — прямой эфир (251 шт. в копии),
  `snimak` — запись (1510). Различает, в отличие от `/dirette/` у raiplay.
  Переводим в маркер `uživo` из `data/markers.json`.
* `sport` — сербское слово (`Fudbal`, `Košarka`, `Tenis`, `Odbojka`…),
  отсев по `app/sport.py`; пара команд — в `content` («AEK - Levski»).
* `time` — настенное белградское, дата — ключ `days`.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "tvarenasport.com"
TZ = "Europe/Belgrade"

_SCHEMES = re.compile(r"TV_SCHEMES\s*=\s*(\{)")
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")


def _extract(html: str) -> dict:
    """Вырезать объект `TV_SCHEMES = {...};` из HTML по балансу скобок."""
    m = _SCHEMES.search(html)
    if not m:
        return {}
    start = m.start(1)
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(html)):
        c = html[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i + 1])
                except ValueError:
                    return {}
    return {}


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    schemes = _extract(html)
    zone = ZoneInfo(tz or TZ)

    out: list[Program] = []
    for channel, payload in schemes.items():
        if channels and channel not in channels:
            continue
        for day_key, block in (payload.get("days") or {}).items():
            try:
                d = _date.fromisoformat(day_key)
            except ValueError:
                continue
            for item in (block or {}).get("emisije", []) or []:
                title = (item.get("content") or "").strip()
                hm = _HHMM.match((item.get("time") or "").strip())
                if not title or not hm:
                    continue
                start = datetime(d.year, d.month, d.day,
                                 int(hm.group(1)), int(hm.group(2)),
                                 tzinfo=zone)
                mark = (item.get("description") or "").strip().lower()
                out.append(Program(
                    channel_raw=channel, title=title, start=start,
                    raw_time=item.get("time") or "",
                    league_raw=(item.get("category") or "").strip(),
                    sport_raw=(item.get("sport") or "").strip(),
                    live_raw="uživo" if mark in ("uzivo", "uživo") else "",
                    match_raw=title, source_url=url,
                    extra={"day": day_key, "mark": mark},
                ))
    return out

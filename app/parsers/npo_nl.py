# -*- coding: utf-8 -*-
r"""npo.nl — Нидерланды, каналы NPO1/NPO2/NPO3; свой запрос на канал и день.

Список каналов лежит открыто:

    https://npo.nl/start/api/domain/guide-channels?type=tv&date=2026-09-01

а расписание канала — в соседней ручке. Она долго отвечала 403 на любые
подстановки, и причина оказалась не в правах, а **в формате даты: здесь она
`ДД-ММ-ГГГГ`**, тогда как в соседней ручке — `ГГГГ-ММ-ДД`:

    https://npo.nl/start/api/domain/guide-channel?date=01-09-2026&guid=<guid канала>

Ответ — список передач за сутки:

    [{"programStart": 1788213000, "durationInSeconds": 3299,
      "mainTitle": "Eva", "episodeTitle": null, "synopsis": "…",
      "isRepeat": true, "isLive": false,
      "genres": [{"name": "Informatief", "type": "primary"}]}]

`programStart` — секунды UTC. Флаги `isLive` и `isRepeat` сайт заполняет
честно, угадывать эфир не нужно. Жанр (`Sport`) кладём в вид спорта, а пару
команд ищем в заголовке и подзаголовке: у NOS матч подписан как
`NOS Voetbal: Ajax - PSV`.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime, timezone
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "npo.nl"
TZ = "Europe/Amsterdam"

_ARRAY = re.compile(r"\[.*\]", re.S)
_GUID = re.compile(r"guid=([0-9a-f-]{36})")

#: guid ручки → имя канала у зрителя (те же, что в плане обхода)
CHANNELS = {
    "83dc1f25-a065-496c-9418-bd5c60dfb36d": "NPO1",
    "316951f5-ce06-41d2-ae24-44eb25368a61": "NPO2",
    "2042e1ee-0e79-4766-aea2-5b300d6839b2": "NPO3",
}


def _pair(text: str) -> str:
    tail = text.split(":", 1)[1] if ":" in text else text
    for sep in (" - ", " – ", " tegen "):
        if sep in tail:
            home, _, away = tail.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    body = _ARRAY.search(html)
    if not body:
        return []
    try:
        shows = json.loads(body.group(0))
    except ValueError:
        return []
    if not isinstance(shows, list) or not shows:
        return []

    # Ответ канал не называет — он только в адресе. При полном обходе в
    # `channels` приходят ВСЕ каналы источника, поэтому имя из плана берётся
    # лишь при разовом запросе одного канала; остальным его даёт карта guid.
    # Заглушка из guid («NPO 2042e1ee») до 19.09 доезжала до базы и витрины —
    # так завёлся канал-пустышка (#3046)
    channel = ""
    if channels and len(channels) == 1:
        channel = next(iter(channels))
    if not channel:
        got = _GUID.search(url or "")
        channel = CHANNELS.get(got.group(1), f"NPO {got.group(1)[:8]}") \
            if got else "NPO"

    out: list[Program] = []
    for show in shows:
        if not isinstance(show, dict):
            continue
        stamp = show.get("programStart")
        title = " ".join((show.get("mainTitle") or "").split())
        if not title or not isinstance(stamp, (int, float)):
            continue
        start = datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone(zone)
        episode = " ".join((show.get("episodeTitle") or "").split())
        genres = [g.get("name") or "" for g in (show.get("genres") or [])
                  if isinstance(g, dict)]
        full = f"{title}: {episode}" if episode else title
        out.append(Program(
            channel_raw=channel, title=full, start=start,
            raw_time=start.strftime("%H:%M"),
            description=" ".join((show.get("synopsis") or "").split())[:300],
            league_raw=episode[:120],
            sport_raw=" ".join(genres)[:60],
            live_raw="" if show.get("isRepeat") else
                     ("live broadcast" if show.get("isLive") else ""),
            match_raw=_pair(full), source_url=url,
            extra={"day": start.date().isoformat()},
        ))
    return out

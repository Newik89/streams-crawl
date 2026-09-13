# -*- coding: utf-8 -*-
r"""canal11.pt — Португалия, канал Федерации футбола; открытый JSON платформы.

Свой `/api/event/list` у сайта отвечал 502, и источник надолго завис в
`ОТЛОЖЕНО.md`. Разгадка нашлась не на самом сайте: **соседний проект уже
берёт эти данные** (`reference/canal11.py`), и адрес там другой — сайт
только витрина, а данные лежат на платформе Pixellot:

    POST https://fpf.watch.pixellot.tv/api/event/list
    {"page": 0, "size": 50, "next": true, "count": true,
     "filters": {"status": "upcoming"}}

Тело — настоящий JSON (не поля формы), и нужны заголовки `Origin` и
`Referer` самого canal11.pt.

Ответ — готовые матчи, без разбора заголовков вообще:

    {"content": {"entries": [
      {"sportType": "soccer", "gameStartDate": 1788253500000,
       "eventTeams": {"homeTeam": {"shortName": "Benfica"},
                      "awayTeam": {"shortName": "Porto"}},
       "mediaIdentities": [{"mediaParentIdentities": [{"title": "Liga BPI"}]}]}]}}

`gameStartDate` — миллисекунды. Берём только `soccer`: остальные виды спорта
платформа отдаёт вперемешку, а нам они всё равно не нужны.

Статусы запрашиваются двумя запросами: `live` — то, что идёт сейчас,
`upcoming` — ближайшее. Первый и даёт признак прямого эфира.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime, timezone
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "canal11.pt"
TZ = "Europe/Lisbon"
CHANNEL = "Canal 11"

_JSON = re.compile(r"\{.*\}", re.S)


def _team(side: dict) -> str:
    return (side.get("shortName") or side.get("name") or "").strip()


@register(DOMAIN)
@register("fpf.watch.pixellot.tv")
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    if channels and CHANNEL not in channels:
        return []
    body = _JSON.search(html)
    if not body:
        return []
    try:
        data = json.loads(body.group(0))
    except ValueError:
        return []
    entries = ((data.get("content") or {}).get("entries")
               if isinstance(data, dict) else None)
    if not isinstance(entries, list):
        return []

    # какой статус спрашивали, видно по самому запросу: `live` — идёт сейчас
    live_now = '"live"' in html[:1] or "status=live" in (url or "")

    out: list[Program] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("sportType") != "soccer":
            continue
        teams = entry.get("eventTeams") or {}
        home = _team(teams.get("homeTeam") or {})
        away = _team(teams.get("awayTeam") or {})
        stamp = entry.get("gameStartDate") or entry.get("event_date")
        if not home or not away or not isinstance(stamp, (int, float)):
            continue
        media = (entry.get("mediaIdentities") or [{}])[0] or {}
        parent = (media.get("mediaParentIdentities") or [{}])[0] or {}
        league = (parent.get("title")
                  or (entry.get("title") or "").split(" - ")[0]).strip()
        start = datetime.fromtimestamp(stamp / 1000, tz=timezone.utc).astimezone(zone)
        out.append(Program(
            channel_raw=CHANNEL, title=f"{league}: {home} - {away}".strip(": "),
            start=start, raw_time=start.strftime("%H:%M"),
            league_raw=league[:120], sport_raw="futebol",
            live_raw="direto",
            match_raw=f"{home} - {away}", source_url=url,
            extra={"day": start.date().isoformat(),
                   "статус": "live" if live_now else "upcoming"},
        ))
    return out

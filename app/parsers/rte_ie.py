# -*- coding: utf-8 -*-
"""rte.ie — Ирландия, 17 каналов; на каждый канал свой готовый JSON.

Страница listings рисуется скриптом, а её данные лежат открытыми файлами —
адреса нашлись в `djstatic/dotie/listings/main.js`:

    https://www.rte.ie/data-feed/pa/rte-2.json

Один файл — один канал и сразу десять суток (лишнее обрезает
`scripts/parse_live.py`). Устройство:

    {"total": 413, "item": [
      {"title": "FAI Cup Live", "dateTime": "2026-09-05T14:45:00.000Z",
       "duration": 75, "attribute": ["hd", "repeat"],
       "summary": {"short": "St Patrick's Athletic v Bohemians (Kick-off 4.00pm)"},
       "asset": {"category": [{"code": "sports", "name": "Sports"},
                              {"code": "sports:football-club", …}]}}]}

Особенности:

- **пара команд не в заголовке, а в описании**: заголовок — название
  передачи (`FAI Cup Live`), команды через ` v ` стоят в `summary.short`;
- вид спорта берём из кода категории (`sports:football-soccer`), название
  категории для футбола записано как `Football/Soccer` — словарь такого не
  знает, поэтому коды приводим к одному слову;
- имя канала в файле не названо — оно в имени самого файла, поэтому берём
  его из адреса по таблице ниже;
- `dateTime` всегда в UTC (`Z`), переводим в дублинское время;
- маркер эфира сайт ставит словом `Live` в заголовке.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "rte.ie"
TZ = "Europe/Dublin"

#: `…/data-feed/pa/rte-2.json` → как канал называется у зрителя
CHANNELS = {
    "rte-1": "RTÉ One", "rte-2": "RTÉ2", "rte-news": "RTÉ News",
    "rte-jr": "RTÉjr", "tg4": "TG4",
    "virgin-media-one": "Virgin Media One",
    "virgin-media-two": "Virgin Media Two",
    "virgin-media-three": "Virgin Media Three",
    "virgin-media-four": "Virgin Media Four",
    "oireachtas-tv": "Oireachtas TV",
    "bbc-1": "BBC One", "bbc-2": "BBC Two", "itv": "ITV1", "itv-2": "ITV2",
    "channel-4": "Channel 4", "more-4": "More4", "E4": "E4",
}

#: код категории → слово вида спорта, понятное словарям
_SPORT = {"football-soccer": "Football", "football-club": "Football",
          "football-international": "Football", "soccer": "Football",
          "tennis": "Tennis", "basketball": "Basketball"}

_FILE = re.compile(r"/pa/([A-Za-z0-9-]+)\.json")
_PAIR = re.compile(r"^(.{2,60}?)\s+[vV]\.?\s+(.{2,60}?)(?:\s*\(|$)")


def _channel(url: str) -> str:
    got = _FILE.search(url or "")
    if not got:
        return ""
    return CHANNELS.get(got.group(1), got.group(1).replace("-", " ").upper())


def _sport(codes: list[str], names: list[str]) -> str:
    for code in codes:
        tail = code.split(":", 1)[-1]
        if tail in _SPORT:
            return _SPORT[tail]
    for code, name in zip(codes, names):
        if code != "sports" and code.startswith("sports"):
            return name
    return "Sports" if "sports" in codes else ""


def _pair(text: str) -> str:
    got = _PAIR.match(text.strip())
    if not got:
        return " "
    return f"{got.group(1).strip()} - {got.group(2).strip()}"


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    try:
        data = json.loads(html)
    except ValueError:
        return []
    items = data.get("item") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []

    channel = _channel(url)
    if not channel or (channels and channel not in channels):
        return []

    out: list[Program] = []
    for show in items:
        if not isinstance(show, dict):
            continue
        title = " ".join((show.get("title") or "").split())
        stamp = show.get("dateTime") or ""
        if not title or not stamp:
            continue
        try:
            start = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        start = start.astimezone(zone)
        summary = show.get("summary") or {}
        short = " ".join((summary.get("short") or "").split())
        long = " ".join((summary.get("medium") or summary.get("long") or "").split())
        asset = show.get("asset") or {}
        cats = [c for c in (asset.get("category") or []) if isinstance(c, dict)]
        codes = [c.get("code") or "" for c in cats]
        names = [c.get("name") or "" for c in cats]
        repeat = "repeat" in (show.get("attribute") or [])
        pair = _pair(short) if _PAIR.match(short.strip()) else _pair(long)
        out.append(Program(
            channel_raw=channel, title=title, start=start,
            raw_time=start.strftime("%H:%M"),
            description=(short or long)[:300],
            league_raw=title.removesuffix(" Live").strip()[:120],
            sport_raw=_sport(codes, names),
            live_raw="" if repeat else ("Live" if "Live" in title else ""),
            match_raw=pair, source_url=url,
            extra={"day": start.date().isoformat()},
        ))
    return out

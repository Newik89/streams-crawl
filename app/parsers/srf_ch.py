# -*- coding: utf-8 -*-
"""srf.ch — Швейцария, уровень A (открытый JSON SRG).

Сайт `srf.ch/play` — клиентское приложение, но у SRG есть открытый слой:
`il.srgssr.ch/integrationlayer/2.0/srf/programGuide/tv/byDate/{дата}.json`
— дневная сетка всех каналов SRF одним запросом (проба 31.08: SRF 1,
SRF zwei, SRF info; спорт живёт на SRF zwei).

Запись `programList[]`: `title`, `startTime`/`endTime` (ISO с поясом),
`genre` (`Sport`), **`isLive` — честный флаг** (1 live из 24 передач в
пробе). Заголовок: `Tennis – US Open 1. Runde Frauen, …` — вид спорта до
длинного тире, дальше турнир и, у командных видов, пара.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime

from . import Program, register

DOMAIN = "srf.ch"
TZ = "Europe/Zurich"

_SPLIT = re.compile(r"\s+[–—-]\s+")


@register(DOMAIN)
@register("il.srgssr.ch")
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = json.loads(html)
    except ValueError:
        return []

    out: list[Program] = []
    for block in data.get("programGuide") or []:
        name = ((block.get("channel") or {}).get("title") or "").strip()
        if not name or (channels and name not in channels):
            continue
        for item in block.get("programList") or []:
            title = (item.get("title") or "").strip()
            raw = (item.get("startTime") or "").strip()
            if not title or not raw:
                continue
            try:
                start = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            parts = _SPLIT.split(title, 1)
            sport_word = parts[0] if len(parts) == 2 else ""
            rest = parts[1] if len(parts) == 2 else title
            league, _, tail = rest.partition(":")
            tail = tail.strip()
            if not tail:
                league, tail = "", rest
            pair = " "
            for sep in (" - ", " – "):
                if sep in tail:
                    home, _, away = tail.partition(sep)
                    if home.strip() and away.strip():
                        pair = f"{home.strip()} - {away.strip()}"
                    break
            out.append(Program(
                channel_raw=name, title=title, start=start,
                raw_time=raw[11:16],
                description=(item.get("lead") or item.get("subtitle") or "")[:200],
                league_raw=league.strip() if pair != " " else "",
                sport_raw=sport_word or (item.get("genre") or ""),
                live_raw="live" if item.get("isLive") else "",
                match_raw=pair, source_url=url,
                extra={"day": raw[:10]},
            ))
    return out

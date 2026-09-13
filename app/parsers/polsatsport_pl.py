# -*- coding: utf-8 -*-
"""polsatsport.pl — Польша, уровень A (внутренний AJAX-JSON).

Одна страница = все 18 каналов Polsat на кусок дня:
`/ajax-program-tv-column/module/page{1..7}/` (разведка 28.08, `notes` в базе).
Ответ — чистый JSON:

    {"channels": [{"id": 320, "title": "Polsat Sport 1",
                   "programs": [{"title": "Siatkówka kobiet: ME - mecz grupy A:
                                           Turcja - Polska",
                                 "emissionDate": 1787976000000,   # мс, UTC
                                 "live": true, "reply": false,
                                 "description": "…"}, …]}, …]}

Что важно:

* **`live` — булев флаг сайта, и он честный**: у повторов `live: false`
  и `reply: true`. Флаг переводим в слово `live` (маркер из
  `data/markers.json`), дальше отсев обычный.
* **Пара команд — в хвосте заголовка** после `mecz …:`; сам заголовок
  начинается с вида спорта (`Siatkówka kobiet: …`) — его разберёт
  `app/sport.py`.
* `emissionDate` — миллисекунды эпохи, то есть абсолютное время;
  часовой пояс нужен только для показа.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "polsatsport.pl"
TZ = "Europe/Warsaw"

# `… - mecz grupy A: Turcja - Polska` → `Turcja - Polska`
_MATCH_TAIL = re.compile(r"mecz[^:]*:\s*(.+)$", re.I)


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = json.loads(html)
    except ValueError:
        return []
    zone = ZoneInfo(tz or TZ)

    out: list[Program] = []
    for channel in data.get("channels", []):
        name = (channel.get("title") or "").strip()
        if not name or (channels and name not in channels):
            continue
        for item in channel.get("programs", []):
            title = (item.get("title") or "").strip()
            ms = item.get("emissionDate")
            if not title or not ms:
                continue
            start = datetime.fromtimestamp(ms / 1000, tz=zone)
            m = _MATCH_TAIL.search(title)
            # У polsat пара команд всегда стоит после `mecz …:`. Нет её —
            # матча нет («mecz finałowy gry pojedynczej» у тенниса), и пары
            # из заголовка добывать нельзя: тире в нём разделяет не команды.
            # Пробел вместо пустоты — чтобы отсев не полез в заголовок.
            out.append(Program(
                channel_raw=name, title=title, start=start,
                raw_time=start.strftime("%H:%M"),
                description=(item.get("description") or "")[:300],
                league_raw=title.split(" - ")[0] if " - " in title else title,
                live_raw="live" if item.get("live") else "",
                match_raw=m.group(1).strip() if m else " ",
                source_url=url,
                extra={"reply": bool(item.get("reply")),
                       "day": start.date().isoformat()},
            ))
    return out

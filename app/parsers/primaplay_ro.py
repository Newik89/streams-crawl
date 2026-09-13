# -*- coding: utf-8 -*-
"""primaplay.ro — Румыния; Prima Sport 1–5, PPV и общие каналы Prima.

`/programtv` отдаёт неделю по всем каналам сразу — один запрос на всё окно.
Вторая румынская сетка после `digisport.ro`: вместе они закрывают Суперлигу,
Кубок Румынии и европейские кубки на румынских каналах.

Разметка — вкладки бутстрапа, вложенные двумя уровнями:

    div.tab-pane#day2026-08-31           день
      a.chanel-program[href="#channel2026-08-31-4"]   `Prima Sport 1`
      div.tab-pane#channel2026-08-31-4               сетка этого канала
        tr > td   `22:30`
        tr > td   `Barcelona - Rayo Vallecano Vezi LIVE`

Номер в `id` канала — не порядковый: у `Prima Sport 1` он `4`, у
`Prima Sport 2` — `1`. Поэтому имя канала берём по ссылке `href`, а не по
позиции.

`Vezi LIVE` — приписка «смотреть в прямом эфире», для нас честный маркер;
из заголовка её снимаем, иначе она приклеится к имени гостей.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "primaplay.ro"
TZ = "Europe/Bucharest"

_DAY_ID = re.compile(r"^day(\d{4})-(\d{2})-(\d{2})$")
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_LIVE_TAIL = re.compile(r"\s*Vezi\s+LIVE\s*$", re.I)


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs ", " VS "):
        if sep in text:
            home, _, away = text.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)

    out: list[Program] = []
    for pane in tree.css("div.tab-pane"):
        got = _DAY_ID.match(pane.attributes.get("id") or "")
        if not got:
            continue
        current = _date(int(got.group(1)), int(got.group(2)), int(got.group(3)))
        # какой вкладке какое имя канала
        names = {}
        for link in pane.css("a.chanel-program"):
            href = (link.attributes.get("href") or "").lstrip("#")
            name = " ".join(link.text().split())
            if href and name:
                names[href] = name
        for tab in pane.css("div.tab-pane"):
            channel = names.get(tab.attributes.get("id") or "")
            if not channel or (channels and channel not in channels):
                continue
            for row in tab.css("tr"):
                cells = row.css("td")
                if len(cells) < 2:
                    continue
                hm = _HHMM.match(" ".join(cells[0].text().split()))
                title = " ".join(cells[1].text().split())
                if not hm or not title:
                    continue
                live = bool(_LIVE_TAIL.search(title))
                clean = _LIVE_TAIL.sub("", title).strip()
                out.append(Program(
                    channel_raw=channel, title=clean,
                    start=datetime(current.year, current.month, current.day,
                                   int(hm.group(1)), int(hm.group(2)),
                                   tzinfo=zone),
                    raw_time=hm.group(0),
                    live_raw="vezi live" if live else "",
                    match_raw=_pair(clean), source_url=url,
                    extra={"day": current.isoformat()},
                ))
    return out

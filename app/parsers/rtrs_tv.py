# -*- coding: utf-8 -*-
"""rtrs.tv — Республика Сербская (Босния), канал РТРС 1.

Дешёвый источник: один запрос `/program/raspored.php?c=1` отдаёт **неделю
вперёд** по всему каналу, поэтому он заведён сеткой (`GRID_DOMAINS`) и даты
в адресе не нужно. `c=2` — радио, его не берём; есть ещё отдельный сайт
`plus.rtrs.tv` (РТРС Плюс) — он не проверялся.

Дни размечены якорями, а не заголовками, и это единственный способ понять,
к какому числу относится строка:

    <a name="2026-08-31"></a><div>31. Август, понедјељак</div>
    div#schedule > div.program-wrapp
        div.program-lijevi   `06:04`
        div.program-desni    заголовок, а в нём иногда `div.rerun` — повтор

Спорт на общественном канале появляется наездами (матчи сборной), поэтому
маркера эфира у сайта нет вовсе: `live_raw` ставим пустым, а повтор помечаем
через `rerun`, чтобы отсев не принял его за прямую трансляцию.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "rtrs.tv"
TZ = "Europe/Sarajevo"
CHANNEL = "РТРС 1"

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})")
_DAY_ANCHOR = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " : "):
        if sep in text:
            home, _, away = text.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    if channels and CHANNEL not in channels:
        return []
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)

    out: list[Program] = []
    current = day or _date.today()
    for node in tree.root.traverse():
        if node.tag == "a":
            anchor = _DAY_ANCHOR.match(node.attributes.get("name") or "")
            if anchor:
                current = _date(int(anchor.group(1)), int(anchor.group(2)),
                                int(anchor.group(3)))
            continue
        if node.tag != "div" or "program-wrapp" not in (node.attributes.get("class") or ""):
            continue
        left = node.css_first("div.program-lijevi")
        title_node = node.css_first("div.program-uzivo-title")
        if not left or not title_node:
            continue
        hm = _HHMM.match(left.text(strip=True))
        title = " ".join(title_node.text().split())
        if not hm or not title:
            continue
        rerun = node.css_first("div.rerun") is not None
        _, _, rest = title.partition(":")
        rest = rest.strip()
        out.append(Program(
            channel_raw=CHANNEL, title=title,
            start=datetime(current.year, current.month, current.day,
                           int(hm.group(1)), int(hm.group(2)), tzinfo=zone),
            raw_time=hm.group(0),
            league_raw=title.split(":", 1)[0].strip() if rest else "",
            description="repriza" if rerun else "",
            match_raw=_pair(rest) if rest else _pair(title),
            source_url=url, extra={"day": current.isoformat(),
                                   "rerun": rerun},
        ))
    return mark_first_show(out, "uživo")

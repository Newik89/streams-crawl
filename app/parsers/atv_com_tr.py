# -*- coding: utf-8 -*-
"""atv.com.tr — Турция, один канал atv; сетку отдаёт отдельный запрос.

Страница `/yayin-akisi` дни переключает скриптом; адрес нашёлся в
`iatv.tmgrup.com.tr/site/v2/j/custom.js` (функция `changeStreamDay`):

    https://www.atv.com.tr/streaming/jsondatehtml?dt=1.09.2026&isajax=true

День в адресе — **без ведущего нуля** (`1.09.2026`), время в вызове со
страницы можно не передавать. Ответ — `{"status": true, "html": "…"}`,
внутри готовая разметка:

    div.item
      span.time > em            `08<em>: 00</em>`  → `08:00`
      figcaption .title h3      `Kahvaltı Haberleri`

Канал на странице один — сам atv. Признака прямого эфира сайт не ставит
вовсе, поэтому эфир определяем первым показом пары (`mark_first_show`),
а домен стоит в `REPEAT_GUESS_DOMAINS`.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "atv.com.tr"
TZ = "Europe/Istanbul"
CHANNEL = "atv"

_HHMM = re.compile(r"(\d{1,2})\D{0,3}(\d{2})")
_DATE = re.compile(r"dt=(\d{1,2})\.(\d{2})\.(\d{4})")


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs ", " v "):
        if sep in text:
            home, _, away = text.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    if channels and CHANNEL not in channels:
        return []
    body = html.lstrip()
    if body[:1] == "{":
        try:
            html = (json.loads(body) or {}).get("html") or ""
        except ValueError:
            return []

    # дату берём из самого адреса: ответ её не называет
    got = _DATE.search(url or "")
    d = _date(int(got.group(3)), int(got.group(2)), int(got.group(1))) \
        if got else (day or _date.today())

    tree = HTMLParser(html)
    out: list[Program] = []
    for item in tree.css("div.item"):
        time_node = item.css_first("span.time")
        name_node = item.css_first("figcaption .title h3")
        if not time_node or not name_node:
            continue
        hm = _HHMM.search(time_node.text(strip=True))
        title = " ".join(name_node.text().split())
        if not hm or not title:
            continue
        hour, minute = int(hm.group(1)), int(hm.group(2))
        if hour > 23 or minute > 59:
            continue
        # день сетки начинается утром: ночные часы — уже следующая дата
        when = d + timedelta(days=1) if hour < 6 else d
        out.append(Program(
            channel_raw=CHANNEL, title=title,
            start=datetime(when.year, when.month, when.day, hour, minute,
                           tzinfo=zone),
            raw_time=f"{hour:02d}:{minute:02d}",
            match_raw=_pair(title), source_url=url,
            extra={"day": when.isoformat()},
        ))
    return mark_first_show(out, "canlı")

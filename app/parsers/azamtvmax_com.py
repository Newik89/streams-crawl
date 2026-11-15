# -*- coding: utf-8 -*-
r"""azamtvmax.com — Танзания, приложение AzamTV Max: программа каналов Azam Sports.

Источник найден владельцем (записка 14.11.2026, книга 129). Закрытый адрес
приложения без служебного заголовка данные не отдаёт (HTTP 400) — его не
трогаем. Страница канала открывается браузером:

    https://web.azamtvmax.com/channel/CH-3974c2cd-9ec4-4d03-82b1-9c993973e487

и показывает программу глазами (проба GitHub 15.11.2026):

    NAMUNGO V POLISI TANZANIA
    Sat, 14 Nov - 10:00PM - 12:00AM

Особенности (из записки владельца и пробы):
  * программа есть ТОЛЬКО на текущие сутки, новый день появляется через
    1–2 часа после полуночи по Танзании; прошедшие передачи пропадают;
  * время на странице — по часам браузера: на GitHub это UTC, поэтому пояс
    источника — UTC (как у canpl.ca). Собирать с сервера — пояс сервера;
  * одна и та же передача стоит на странице в нескольких блоках подряд —
    берём один раз;
  * года на странице нет — берём из дня запроса; запись за 31 декабря,
    прочитанная 1 января, — прошлый год;
  * «LIVE» в названии — слово сайта о прямом эфире («NIGERIA V TANZANIA
    LIVE»); без него эфир решает эталон.

Канал — по номеру в адресе (`CHANNELS`), а если номер незнаком — первая
строка страницы («Azam Sports 1 HD»).
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import daytime, fallback_read
from . import Program, register

DOMAIN = "azamtvmax.com"
#: часы браузера на GitHub
TZ = "UTC"
#: номер канала в адресе → имя канала
CHANNELS = {
    "CH-3974c2cd-9ec4-4d03-82b1-9c993973e487": "Azam Sports 1 HD",
    "CH-a8f7959c-f424-4064-8b71-6c125da488ff": "Azam Sports 3 HD",
}
_ID = re.compile(r"/channel/(CH-[0-9a-f-]{36})", re.I)
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
#: «Sat, 14 Nov - 10:00PM - 12:00AM», «Sat, 14 Nov-10:00PM - 12:00AM»,
#: «Sat, 14 Nov 10:00PM - 12:00AM»
_WHEN = re.compile(
    r"^[A-Za-z]{3},\s*(?P<d>\d{1,2})\s+(?P<mon>[A-Za-z]{3})\s*-?\s*"
    r"(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ap>[AP]M)\s*-\s*\d{1,2}:\d{2}\s*[AP]M$", re.I)
_LIVE = re.compile(r"\bLIVE\b", re.I)
#: служебные строки страницы — не названия передач
_NOT_TITLES = {"today", "schedule", "epg", "scheduled", "related", "watch now", "sports"}


def _pair(title: str) -> str:
    """«NAMUNGO V POLISI TANZANIA» → «NAMUNGO - POLISI TANZANIA»; пары нет — « »."""
    clean = " ".join(_LIVE.sub(" ", title).split())
    for sep in (" V ", " v ", " VS ", " vs ", " - "):
        if sep in clean:
            home, _, away = clean.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    lines = fallback_read.lines_of(html)
    if not lines:
        return []
    zone = ZoneInfo(tz or TZ)
    day = day or daytime.today(tz or TZ)
    got = _ID.search(url or "")
    channel = CHANNELS.get(got.group(1)) if got else None
    channel = channel or lines[0]
    if channels and channel not in channels:
        return []
    out: list[Program] = []
    seen = set()
    for i, line in enumerate(lines):
        when = _WHEN.match(line)
        if not when or i == 0:
            continue
        title = lines[i - 1].strip()
        month = _MONTHS.get(when["mon"].lower())
        if not month or len(title) < 3 or title.lower() in _NOT_TITLES or _WHEN.match(title):
            continue
        hour = int(when["h"]) % 12 + (12 if when["ap"].upper() == "PM" else 0)
        try:
            start = datetime(day.year, month, int(when["d"]), hour, int(when["m"]), tzinfo=zone)
        except ValueError:
            continue
        if start.date() - day > timedelta(days=180):      # 31 декабря, прочитано 1 января
            start = start.replace(year=day.year - 1)
        if (title, start) in seen:
            continue
        seen.add((title, start))
        out.append(Program(
            channel_raw=channel, title=title, start=start,
            raw_time=f"{hour:02d}:{when['m']}", sport_raw="",
            live_raw="live" if _LIVE.search(title) else "",
            match_raw=_pair(title), source_url=url,
            extra={"day": start.date().isoformat()}))
    return out

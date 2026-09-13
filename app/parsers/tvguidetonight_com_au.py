# -*- coding: utf-8 -*-
"""tvguidetonight.com.au — Австралия, страница на канал и день.

Адрес: `/channels/{slug}` — сегодня, `/channels/{slug}/tomorrow` — завтра,
дальше — имя дня недели (`/friday`); в адресе это метка `{AU_DAYPATH}`
(`app/urls.py`). Слаг канала — с городом: `10-bold-sydney`, `7mate-hd-sydney`
(старые слаги без города отвечают 404 — смена адресов поймана 02.09).

Строка расписания:

    <h4>AFL Women's Premiership</h4>
    <li class="show-time">7:00 - 9:15 pm</li>

Время 12-часовое, am/pm стоит ТОЛЬКО у конца диапазона: `11:30 - 12:00 pm`
— это 11:30 УТРА. Начало восстанавливаем подбором: из двух чтений (am/pm)
берём то, при котором передача длится меньше 12 часов и начинается до конца.

Заголовок в `<h1>` врёт (кэш сервера отдаёт чужой день) — дату берём из
аргумента `day`: обход сам знает, за какой день качал адрес.

Маркера эфира нет — эфиром считаем первый показ пары (`mark_first_show`),
домен в `REPEAT_GUESS_DOMAINS`. Пары австралийцы пишут через ` v `.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "tvguidetonight.com.au"
TZ = "Australia/Sydney"

_TIME = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*(am|pm)$",
                   re.I)


def _channel_from_url(url: str) -> str:
    """`/channels/7mate-hd-sydney/tomorrow` → `7mate HD Sydney`."""
    m = re.search(r"/channels/([a-z0-9-]+)", url or "")
    if not m:
        return "tvguidetonight"
    slug = m.group(1)
    for tail in ("/tomorrow", "/yesterday"):
        slug = slug.removesuffix(tail)
    words = []
    for w in slug.split("-"):
        words.append(w.upper() if w in ("hd", "abc") else w.capitalize())
    return " ".join(words)


def _minutes(h: int, m: int, pm: bool) -> int:
    h = h % 12 + (12 if pm else 0)
    return h * 60 + m


def _start_minutes(sh: int, sm: int, end: int) -> int | None:
    """Начало из двух чтений: то, при котором длительность 0–12 часов."""
    for pm in (False, True):
        start = _minutes(sh, sm, pm)
        for shift in (0, 24 * 60):        # конец мог уехать за полночь
            if 0 < (end + shift) - start <= 12 * 60:
                return start
    return None


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    day = day or _date.today()
    channel = _channel_from_url(url)
    tree = HTMLParser(html)

    out: list[Program] = []
    offset = 0
    prev: int | None = None
    for block in tree.css("div.show-information"):
        title_node = block.css_first("h4")
        time_node = block.css_first("li.show-time")
        if not title_node or not time_node:
            continue
        title = " ".join(title_node.text().split())
        hm = _TIME.match(" ".join(time_node.text().split()))
        if not title or not hm:
            continue
        end = _minutes(int(hm.group(3)), int(hm.group(4)),
                       hm.group(5).lower() == "pm")
        start = _start_minutes(int(hm.group(1)), int(hm.group(2)), end)
        if start is None:
            continue
        if prev is not None and start < prev:
            offset += 1
        prev = start
        d = day + timedelta(days=offset)
        pair = " "
        for sep in (" v ", " vs ", " V "):
            if sep in title:
                home, _, away = title.partition(sep)
                if home.strip() and away.strip():
                    pair = f"{home.strip()} - {away.strip()}"
                break
        out.append(Program(
            channel_raw=channel, title=title,
            start=datetime(d.year, d.month, d.day, start // 60, start % 60,
                           tzinfo=zone),
            raw_time=f"{start // 60:02d}:{start % 60:02d}",
            match_raw=pair,
            source_url=url, extra={"day": d.isoformat()},
        ))
    return mark_first_show(out, "live")

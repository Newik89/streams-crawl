# -*- coding: utf-8 -*-
"""rtl.de — Германия, телегид группы RTL. Адрес на канал и день.

    https://www.rtl.de/fernsehprogramm/{канал}/{YYYY-MM-DD}/

Каналы: `rtl` (главный, у него адрес без имени — `/fernsehprogramm/{дата}/`),
`vox`, `nitro`, `rtl-up`, `vox-up`, `rtl-crime`, `rtl-living`, `rtl-passion`.

Разметка собрана сборщиком, поэтому в именах классов есть хеш сборки
(`EpgItem_time__wrUmZ`) — он меняется при каждом обновлении сайта. Опираемся
на **начало** имени класса, а не на всё имя:

    button[class^="EpgItem_item"]
      div[class^="EpgItem_time"]      `00:15`
      span[class^="EpgItem_title"]    `vox nachrichten`
      span[class^="EpgItem_subtitle"] подзаголовок

День на странице разбит на части (`Nachts`, `Morgens`, `Mittags`, `Abends`),
время идёт по возрастанию; всё, что после переворота через полночь, — уже
следующая дата. Саму дату берём из адреса, в заголовке она словом
(`VOX Fernsehprogramm morgen`).

Прямой эфир сайт никак не помечает — эфиром считаем первый показ пары,
домен внесён в `REPEAT_GUESS_DOMAINS` (`scripts/parse_live.py`).
"""

from __future__ import annotations

import html as _html
import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "rtl.de"
TZ = "Europe/Berlin"

_URL_DAY = re.compile(r"/(\d{4})-(\d{2})-(\d{2})/")
_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")
_HEAD = re.compile(r"\s*Fernsehprogramm.*$", re.I)


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs ", " gegen ", " : "):
        home, s, away = text.partition(sep)
        if s and home.strip() and away.strip():
            return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)

    head = tree.css_first("h1")
    channel = _HEAD.sub("", _html.unescape(
        head.text(strip=True) if head else "")).strip()
    if not channel:
        return []
    if channels and channel.casefold() not in {c.casefold() for c in channels}:
        return []

    found = _URL_DAY.search(url or "")
    first = _date(int(found.group(1)), int(found.group(2)),
                  int(found.group(3))) if found else day

    out: list[Program] = []
    previous = None
    shift = 0
    for item in tree.css('button[class^="EpgItem_item"]'):
        clock = item.css_first('div[class^="EpgItem_time"]')
        title_node = item.css_first('span[class^="EpgItem_title"]')
        if clock is None or title_node is None:
            continue
        stamp = _TIME.match(clock.text(strip=True))
        title = _html.unescape(title_node.text(strip=True))
        if not stamp or not title:
            continue
        minutes = int(stamp.group(1)) * 60 + int(stamp.group(2))
        if previous is not None and minutes < previous:
            shift += 1
        previous = minutes
        subtitle = item.css_first('span[class^="EpgItem_subtitle"]')
        subtitle_text = _html.unescape(
            subtitle.text(strip=True)) if subtitle else ""
        start = None
        if first is not None:
            start = datetime(first.year, first.month, first.day,
                             int(stamp.group(1)), int(stamp.group(2)),
                             tzinfo=zone) + timedelta(days=shift)
        pair = _pair(title)
        if not pair.strip() and subtitle_text:
            pair = _pair(subtitle_text)
        out.append(Program(
            channel_raw=channel, title=title, start=start,
            raw_time=clock.text(strip=True), description=subtitle_text,
            match_raw=pair, source_url=url,
            extra={"day": start.date().isoformat() if start else ""},
        ))
    return mark_first_show(out, "live")

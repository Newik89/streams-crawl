# -*- coding: utf-8 -*-
"""ssport.tv — Турция, S Sport и S Sport 2. Неделя трансляций одной страницей.

`https://ssport.tv/yayin-akisi` отдаёт сразу **семь дней и оба канала** —
211 строк за один запрос, поэтому источник заведён сеткой.

Разметка обычная (`li` со временем, названием и турниром), но дата и канал в
видимом тексте не написаны — они лежат в кнопке «Takvime Ekle» («добавить в
календарь»): ссылка `data:text/calendar` с готовым VEVENT.

    download="Barcelona - Rayo Vallecano-S Sport"
    href="data:text/calendar;charset=utf8;base64,…"
        DTSTART;TZID=Europe/Istanbul:20260901T003000
        SUMMARY:Barcelona - Rayo Vallecano-S Sport

Оттуда и берём: дату, время с поясом и имя канала (хвост после последнего
дефиса в имени файла). Видимый текст даёт заголовок (`h3`) и турнир
(`p` в блоке `streaming-explanation`, напр. `İspanya LaLiga`).

Маркер эфира у сайта есть — плашка `CANLI` на строке
(`span.uk-label-danger`); повторы её не несут. До 02.09 эфир угадывался
первым показом и в ленту пролезали повторы — поймано владельцем на
витрине, теперь читаем честную плашку.
"""

from __future__ import annotations

import base64
import binascii
import html as _html
import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "ssport.tv"
TZ = "Europe/Istanbul"

_DTSTART = re.compile(r"DTSTART;TZID=([^:\r\n]+):(\d{8})T(\d{6})")
#: хвост тура в названии турнира: `İspanya LaLiga 4. Hafta Maçı`
_ROUND_TAIL = re.compile(r"\s+\d+\.\s*(?:Hafta|Tur|Etap)(?:\s+Maçı)?\s*$", re.I)
_LIVE = "canlı"


def _pair(text: str) -> str:
    """Турки пишут пару через дефис (`Barcelona - Rayo Vallecano`); косую
    черту тоже встречаем в кубковых парах."""
    for sep in (" - ", " – ", " / ", " vs "):
        home, s, away = text.partition(sep)
        if s and home.strip() and away.strip():
            return f"{home.strip()} - {away.strip()}"
    return " "


def _event(node) -> tuple[datetime | None, str]:
    """Дата, время и канал из вложенного календаря строки."""
    link = node.css_first('a[href^="data:text/calendar"]')
    if link is None:
        return None, ""
    name = _html.unescape(link.attributes.get("download") or "")
    channel = name.rsplit("-", 1)[-1].strip() if "-" in name else ""
    href = link.attributes.get("href") or ""
    payload = href.partition("base64,")[2]
    try:
        text = base64.b64decode(payload).decode("utf-8", errors="replace")
    except (binascii.Error, ValueError):
        return None, channel
    stamp = _DTSTART.search(text)
    if not stamp:
        return None, channel
    day, clock = stamp.group(2), stamp.group(3)
    try:
        zone = ZoneInfo(stamp.group(1))
    except Exception:                      # неизвестный пояс — берём турецкий
        zone = ZoneInfo(TZ)
    start = datetime(int(day[:4]), int(day[4:6]), int(day[6:]),
                     int(clock[:2]), int(clock[2:4]), tzinfo=zone)
    return start, channel


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    tree = HTMLParser(html)
    out: list[Program] = []
    # строки-`li` вложены в другие `li`, и внешний тоже видит и заголовок, и
    # время своей строки — поэтому одну и ту же передачу отдаём один раз
    seen: set[tuple] = set()
    for item in tree.css("li"):
        title_node = item.css_first("h3")
        time_node = item.css_first("time")
        if title_node is None or time_node is None:
            continue
        title = title_node.text(strip=True)
        if not title:
            continue
        start, channel = _event(item)
        if not channel or (channels and channel not in channels):
            continue
        key = (channel, start, title)
        if key in seen:
            continue
        seen.add(key)
        league_node = item.css_first(".streaming-explanation p")
        badge = item.css_first("span.uk-label-danger")
        live = _LIVE if badge and "CANLI" in badge.text() else ""
        raw_time = (time_node.attributes.get("datetime")
                    or time_node.text(strip=True) or "")
        out.append(Program(
            channel_raw=channel, title=title, start=start,
            raw_time=raw_time.strip(),
            league_raw=_ROUND_TAIL.sub(
                "", league_node.text(strip=True)) if league_node else "",
            live_raw=live,
            match_raw=_pair(title), source_url=url,
            extra={"day": start.date().isoformat() if start else ""},
        ))
    return out


def list_channels(html: str) -> list[str]:
    names: list[str] = []
    for link in HTMLParser(html).css('a[href^="data:text/calendar"]'):
        name = _html.unescape(link.attributes.get("download") or "")
        channel = name.rsplit("-", 1)[-1].strip() if "-" in name else ""
        if channel and channel not in names:
            names.append(channel)
    return names

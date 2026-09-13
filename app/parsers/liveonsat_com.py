# -*- coding: utf-8 -*-
"""liveonsat.com — международный справочник: матч и каналы, которые его дают.

Это не сетка канала, а список игр: на каждый матч — время начала и все
каналы мира, показывающие его (спутник, кабель, IPTV). За два дня страница
`2day.php` отдаёт 72 матча и 209 упоминаний каналов, один запрос.

    https://liveonsat.com/2day.php?start_dd={DD}&start_mm={MM}&start_yyyy={YYYY}
        &end_dd={DD}&end_mm={MM}&end_yyyy={YYYY}&postponed=0

Разметка старая, на `div`-ах с говорящими классами:

    h2.sport_head                     `Football` — вид спорта раздела
    span.comp_head                    `Brazilian Série A - Week 25`
    div.blockfix                      один матч
      div.fix_text div.fLeft          `Remo v Coritiba`
      div.fLeft_time_live[data-timestamp]  метка времени UTC (`ST: 16:00`)
      a.chan_live_free / .chan_live_not_free / .chan_live_iptvcable
                                      `viju+ Sport HD` — канал

Время берём из `data-timestamp`: в самом тексте оно в поясе, выбранном
куки-настройкой сайта, а метка честная и в UTC.

Отдельного слова «прямой эфир» нет — на странице только прямые трансляции
(класс так и называется `..._live`), поэтому маркер ставим сами.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timezone

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "liveonsat.com"
TZ = "UTC"

_CHANNEL = "a.chan_live_free, a.chan_live_not_free, a.chan_live_iptvcable"
_PAIR = re.compile(r"\s+v\.?\s+|\s+vs\.?\s+", re.I)
#: хвосты у имени канала: `Sky Sports+ [via APP]`, `Canal 11 [online] (geo/R) 📺`
_CHANNEL_TAIL = re.compile(r"\s*(?:\[[^\]]*\]|\([^)]*\)|[\U0001F300-\U0001FAFF])+\s*$")


def _channel_name(raw: str) -> str:
    """Имя канала без пометок способа доставки и без значка экрана."""
    name = " ".join((raw or "").split())
    previous = None
    while name != previous:                 # хвостов бывает несколько подряд
        previous = name
        name = _CHANNEL_TAIL.sub("", name).strip()
    return name


def _pair(text: str) -> str:
    """`Remo v Coritiba` → `Remo - Coritiba`."""
    parts = _PAIR.split(text, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return f"{parts[0].strip()} - {parts[1].strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    tree = HTMLParser(html)
    body = tree.body or tree.root
    if body is None:
        return []

    sport = ""
    competition = ""
    out: list[Program] = []
    for node in body.traverse(include_text=False):
        classes = (node.attributes.get("class") or "")
        if node.tag == "h2" and "sport_head" in classes:
            sport = node.text(strip=True)
            continue
        if node.tag == "span" and "comp_head" in classes:
            competition = node.text(strip=True)
            continue
        if "blockfix" not in classes.split():
            continue

        title_node = node.css_first("div.fix_text div.fLeft")
        if title_node is None:
            continue
        title = title_node.text(strip=True)
        pair = _pair(title)
        if not pair.strip():
            continue

        stamps = node.css("div.fLeft_time_live")
        groups = node.css("div.fLeft_live")
        seen: set[tuple] = set()
        for index, group in enumerate(groups):
            stamp = stamps[index] if index < len(stamps) else (
                stamps[0] if stamps else None)
            mark = (stamp.attributes.get("data-timestamp") or "") if stamp else ""
            start = None
            if mark.isdigit():
                start = datetime.fromtimestamp(int(mark), timezone.utc)
            for link in group.css(_CHANNEL):
                channel = _channel_name(link.text(strip=True))
                if not channel or (channels and channel not in channels):
                    continue
                key = (channel, start)
                if key in seen:
                    continue
                seen.add(key)
                out.append(Program(
                    channel_raw=channel, title=title, start=start,
                    raw_time=stamp.text(strip=True).removeprefix("ST:").strip()
                    if stamp else "",
                    league_raw=competition, sport_raw=sport,
                    live_raw="live broadcast", match_raw=pair, source_url=url,
                    extra={"day": start.date().isoformat() if start else ""},
                ))
    return out


def list_channels(html: str) -> list[str]:
    names: list[str] = []
    for link in HTMLParser(html).css(_CHANNEL):
        name = _channel_name(link.text(strip=True))
        if name and name not in names:
            names.append(name)
    return names

# -*- coding: utf-8 -*-
"""ntvplus.tv — НТВ-ПЛЮС; 25 спортканалов, включая весь пакет «МАТЧ!».

**Адрес не тот, что в браузере.** Обычная страница `/tv/sport/?date=…`
приходит пустым каркасом (27 КБ, ноль меток времени) — сетку дорисовывает
скрипт. Зато её же источник открыт и отвечает обычному запросу:

    https://ntvplus.tv/tv/ajax/tv?genre=sport&date=ДД.ММ.ГГГГ&tz=0&search=&channel=&offset=0

Один такой запрос отдаёт все 25 каналов за день (544 передачи), поэтому
источник заведён «дневной сеткой». Ответ — кусок разметки, не JSON.

Разметка:

    div.tv-schedule--inner
      div.channel-header--title > a      `МАТЧ! Футбол 1 (HD)`
      div.tv-schedule--list
        div.tv-schedule--item[class~=live|current|passed]
          div.tv-schedule--item-time     `21:45`
          a.tv-schedule--item-title      `Футбол. Лига чемпионов. Арсенал - Реал (6+)`

Заголовок идёт частями через точку: вид спорта, турнир, пояснения, и в самом
конце — пара команд. Возрастную метку `(6+)` снимаем, иначе она приклеивается
к имени гостей. `live` в классе — честный маркер эфира, он же встречается у
студий («Все на Матч!»), их режут стоп-слова.

Время сайт отдаёт московское (`tz=0` в адресе — часовой пояс по умолчанию).
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "ntvplus.tv"
TZ = "Europe/Moscow"

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})")
_DATE_IN_URL = re.compile(r"date=(\d{2})\.(\d{2})\.(\d{4})")
_AGE = re.compile(r"\s*\(\d{1,2}\+\)\s*$")


def _split(title: str) -> tuple[str, str, str]:
    """Заголовок → (вид спорта, лига, пара). Пара — последний кусок с дефисом."""
    clean = _AGE.sub("", title).strip()
    parts = [p.strip() for p in clean.split(".") if p.strip()]
    pair = " "
    tail = ""
    for i in range(len(parts) - 1, -1, -1):
        for sep in (" - ", " – "):
            if sep in parts[i]:
                home, _, away = parts[i].partition(sep)
                if home.strip() and away.strip():
                    pair = f"{home.strip()} - {away.strip()}"
                    tail = parts[i]
                break
        if pair != " ":
            break
    sport = parts[0] if parts else ""
    league = " ".join(p for p in parts[1:] if p != tail)
    return sport, league[:120], pair


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    got = _DATE_IN_URL.search(url or "")
    if got:
        day = _date(int(got.group(3)), int(got.group(2)), int(got.group(1)))
    day = day or _date.today()
    tree = HTMLParser(html)

    out: list[Program] = []
    for block in tree.css("div.tv-schedule--inner"):
        head = block.css_first(".channel-header--title")
        channel = head.text(strip=True) if head else ""
        if not channel or (channels and channel not in channels):
            continue
        for item in block.css("div.tv-schedule--item"):
            time_node = item.css_first(".tv-schedule--item-time")
            title_node = item.css_first(".tv-schedule--item-title")
            if not time_node or not title_node:
                continue
            hm = _HHMM.match(time_node.text(strip=True))
            title = title_node.text(strip=True)
            if not hm or not title:
                continue
            live = "live" in (item.attributes.get("class") or "")
            sport, league, pair = _split(title)
            # телегид-день начинается с 06:00, как у большинства сеток
            d = day + timedelta(days=1) if int(hm.group(1)) < 6 else day
            out.append(Program(
                channel_raw=channel, title=_AGE.sub("", title).strip(),
                start=datetime(d.year, d.month, d.day,
                               int(hm.group(1)), int(hm.group(2)), tzinfo=zone),
                raw_time=hm.group(0), league_raw=league, sport_raw=sport,
                live_raw="прямая трансляция" if live else "",
                match_raw=pair, source_url=url,
                extra={"day": d.isoformat()},
            ))
    return out

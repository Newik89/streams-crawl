# -*- coding: utf-8 -*-
"""nova.bg — Болгария, уровень B (разметка HTML).

Одна страница = один канал за один день: `schedule/index/{канал}/{Г}/{М}/{Д}/`.
Готового JSON нет, но разметка простая и не менялась с разведки:

    li[id^="production"]          блок передачи
      div.timeline-hour           14:30
      div.timeline-show > h2      Мидълзбро - Уест Бромич Албиън
      div.timeline-show > span    3 кръг, Футбол: Чемпиъншип 2026/2027, директно

В последней строке сразу тур, вид спорта, лига и маркер эфира — через запятую.
Маркеры: `директно` — эфир, `запис` — запись, `/n/` — значение неизвестно
(встречается у повторов), такие блоки отсеиваются сами: маркера эфира нет.

Канал и день берём **из самой страницы** (`link rel=canonical`), а не из
запрошенного адреса: если сайт увёл на другой день, мы это увидим.
Время настенное, софийское, с переходом через полночь — день заканчивается
блоками `01:30` и `03:30`, это уже следующие сутки.
"""

from __future__ import annotations

import re
from datetime import date as _date

from selectolax.parser import HTMLParser

from .. import daytime
from . import Program, register

DOMAIN = "nova.bg"
TZ = "Europe/Sofia"

_CANON = re.compile(r"/schedule/index/(\d+)/(\d{4})/(\d{1,2})/(\d{1,2})")
# `3 кръг, Футбол: Чемпиъншип 2026/2027, директно` → спорт и лига
_SPORT_LEAGUE = re.compile(r"([^,:]+)\s*:\s*([^,]+)")


def page_channel_and_day(html: str) -> tuple[str | None, _date | None]:
    """Номер канала и дата — так, как их назвала сама страница."""
    tree = HTMLParser(html)
    node = tree.css_first("link[rel=canonical]") or tree.css_first('meta[property="og:url"]')
    href = (node.attributes.get("href") or node.attributes.get("content") or "") if node else ""
    m = _CANON.search(href)
    if not m:
        return None, None
    return m.group(1), _date(int(m.group(2)), int(m.group(3)), int(m.group(4)))


def list_channels(html: str) -> dict[str, str]:
    """Переключатель каналов: номер → название. Нужен, чтобы обходить все
    спортивные каналы, а не тот один, что стоял в закладке владельца
    (`recon/channels_map.md`). Название лежит в `alt` у логотипа."""
    out: dict[str, str] = {}
    for a in HTMLParser(html).css('a[href*="schedule/index"]'):
        m = _CANON.search(a.attributes.get("href") or "")
        img = a.css_first("img")
        if m and img and img.attributes.get("alt"):
            out.setdefault(m.group(1), img.attributes["alt"].strip())
    return out


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "") -> list[Program]:
    tree = HTMLParser(html)
    channel_id, page_day = page_channel_and_day(html)
    day = page_day or day
    channel = list_channels(html).get(channel_id or "", "") or f"канал {channel_id}"

    blocks = tree.css('li[id^="production"]')
    rows = []
    for li in blocks:
        hour = li.css_first(".timeline-hour")
        head = li.css_first(".timeline-show h2")
        tail = li.css_first(".timeline-show span")
        rows.append((
            hour.text(strip=True) if hour else "",
            head.text(strip=True) if head else "",
            tail.text(strip=True) if tail else "",
        ))

    moments = daytime.walk_day([r[0] for r in rows], day or _date.today(), tz or TZ)

    out = []
    for (raw_time, title, note), moment in zip(rows, moments):
        sport = league = ""
        m = _SPORT_LEAGUE.search(note)
        if m:
            sport, league = m.group(1).strip(), m.group(2).strip()
        out.append(Program(
            channel_raw=channel, title=title, start=moment, raw_time=raw_time,
            description=note, league_raw=league, sport_raw=sport,
            live_raw=note, match_raw=title, source_url=url,
            extra={"channel_id": channel_id, "day": day.isoformat() if day else ""},
        ))
    return out

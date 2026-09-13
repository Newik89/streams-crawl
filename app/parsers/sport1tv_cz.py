# -*- coding: utf-8 -*-
"""sport1tv.cz и sport1tv.hu — сетки Sport1/Sport2 одной страницей.

Оба сайта — одна WordPress-тема `sporttv`, разметка совпадает до классов;
отличаются составом каналов, форматом даты и языком пометок. Чешский разобран
02.09 по копии, венгерский добавлен тем же днём — его страница тоже
дорисовывается скриптом (браузер, `needs_js=1`).

`/programovy-pruvodce` рисуется скриптом: обычный запрос даёт каркас,
нужен браузер с ожиданием догрузки (`needs_js=1`, таймаут 60 с). После
догрузки в странице три колонки `div.channel[data-channel-id]` — по числу
логотипов в слайдере: Sport1 CZ, Sport1 SK, Sport2. Дата показанного дня
лежит в переключателе: `div.day span.date` → `01.09.2026`.

Карточка `div.show.js-program-card`:

    p.date   `21:00-23:00` — берём только начало
    p.name   `Fotbal` — вид спорта по-чешски
    p.desc   `Coppa Italia, 2. kolo, premiéra, živě, HD<br>Turín - Monza`
             до `<br>` — турнир и служебные пометки, после — пара команд

Маркер эфира честный: `živě` в описании; повторы помечены `repríza`.

Две ловушки:
  * слайдер slick клонирует колонки — каждая карточка встречается дважды,
    одинаковые отбрасываем по тройке (канал, время, заголовок);
  * колонка дня начинается с передачи, залезшей из вчера (`22:45-02:45`
    первой строкой) — первое время позднее 20:00 относим к предыдущей дате,
    дальше уменьшение времени означает переход через полночь.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, time as _time, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "sport1tv.cz"
DOMAIN_HU = "sport1tv.hu"
TZ = "Europe/Prague"

#: порядок совпадает со слайдером логотипов страницы:
#: у чехов sport1-cz, sport1-sk, sport2; у венгров sport1, sport2
_CHANNELS = {
    DOMAIN: {"0": "Sport1 CZ", "1": "Sport1 SK", "2": "Sport2"},
    DOMAIN_HU: {"0": "Sport1 HU", "1": "Sport2 HU"},
}
_TZS = {DOMAIN: "Europe/Prague", DOMAIN_HU: "Europe/Budapest"}

_TIME = re.compile(r"^(\d{1,2}):(\d{2})")
_PAGE_DAY = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")      # чешская 01.09.2026
_PAGE_DAY_HU = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")   # венгерская 2026.09.01.

#: служебные слова описания — не турнир: `premiéra, živě, HD`, `2. kolo`;
#: венгерские: `ism.` — повтор, `élő` — эфир, `3. forduló` — тур
_NOISE = re.compile(r"^(?:premiéra|repríza|živě|nové|HD|část \d+|\d+\. ?kolo"
                    r"|\d+\. ?den|ism\.?|élő|\d+\. ?forduló|\d+\. ?nap)$", re.I)
_LIVE = re.compile(r"živě|élő", re.I)


def _page_day(tree: HTMLParser) -> _date | None:
    node = tree.css_first("div.day span.date")
    if not node:
        return None
    text = node.text()
    m = _PAGE_DAY_HU.search(text)
    if m:                                  # венгерский порядок: год впереди
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _PAGE_DAY.search(text)
    if m:
        return _date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _desc_parts(node) -> tuple[str, str]:
    """Описание до `<br>` (турнир и пометки) и после (пара команд)."""
    raw = node.html or ""
    raw = re.sub(r"</?p[^>]*>", "", raw)
    chunks = [re.sub(r"<[^>]+>", " ", c) for c in re.split(r"<br\s*/?>", raw)]
    chunks = [" ".join(c.split()) for c in chunks]
    info = chunks[0] if chunks else ""
    pair = chunks[1] if len(chunks) > 1 else ""
    return info, pair


@register(DOMAIN)
@register(DOMAIN_HU)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    domain = DOMAIN_HU if DOMAIN_HU in (url or "") else DOMAIN
    zone = ZoneInfo(tz or _TZS[domain])
    tree = HTMLParser(html)
    day = _page_day(tree) or day or _date.today()

    out: list[Program] = []
    seen: set[tuple] = set()
    for col in tree.css("div.channel[data-channel-id]"):
        cid = col.attributes.get("data-channel-id") or ""
        channel = _CHANNELS[domain].get(cid)
        if not channel or (channels and channel not in channels):
            continue
        offset: int | None = None    # None — ещё не видели первой карточки
        prev: _time | None = None
        for card in col.css("div.js-program-card"):
            date_node = card.css_first("p.date")
            name_node = card.css_first("p.name")
            hm = _TIME.match(" ".join(date_node.text().split())) if date_node else None
            sport = " ".join(name_node.text().split()) if name_node else ""
            if not hm or not sport:
                continue
            start_t = _time(int(hm.group(1)), int(hm.group(2)))
            if offset is None:
                # колонка покрывает 00:00–24:00: первая карточка позднее
                # 20:00 началась ещё вчера
                offset = -1 if start_t >= _time(20, 0) else 0
            elif prev is not None and start_t < prev:
                offset += 1
            prev = start_t
            desc_node = card.css_first("p.desc")
            info, pair = _desc_parts(desc_node) if desc_node else ("", "")
            key = (channel, hm.group(0), sport, info, pair)
            if key in seen:      # клоны слайдера slick
                continue
            seen.add(key)
            league = next((p for p in (s.strip() for s in info.split(","))
                           if p and not _NOISE.match(p)), "")
            found = _LIVE.search(info)
            live = found.group(0) if found else ""
            d = day + timedelta(days=offset)
            out.append(Program(
                channel_raw=channel,
                title=f"{sport}: {pair}" if pair else sport,
                start=datetime(d.year, d.month, d.day, start_t.hour,
                               start_t.minute, tzinfo=zone),
                raw_time=hm.group(0),
                description=info,
                league_raw=league[:120],
                sport_raw=sport,
                live_raw=live,
                match_raw=pair or " ",
                source_url=url, extra={"day": d.isoformat()},
            ))
    return out

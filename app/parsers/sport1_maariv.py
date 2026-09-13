# -*- coding: utf-8 -*-
"""sport1.maariv.co.il — Израиль, каналы Sport 1; пять каналов за один запрос.

Страница `/broadcast-schedule/` приходит пустой — расписание подставляет
скрипт. Его источник нашёлся в `broadcast.82b321.js` и открыт всем:

    https://sport1.maariv.co.il/wp-json/sport1/v1/broadcast/day/ГГГГ-ММ-ДД/?live=1

Ответ — JSON-строка, внутри которой лежит готовая разметка (не объект с
полями). Поэтому сначала снимаем кавычки `json.loads`, а разбираем уже HTML.
`?live=1` оставляет только прямые эфиры — ровно то, что нам нужно; без него
приходит весь день.

Разметка:

    div.channel-container
      div.channel-name-wrapper > img[src=…/sport1-6-channel-logo.svg]
      div.date-shows-container.shows-container-for-2026-08-31
        div.show-container
          p.show-starting-time    `21:50`
          p.show-second-status    `ישיר` — прямой эфир
          p.show-name             `אסטון וילה - ארסנל`
          p.show-description      `הליגה האנגלית 2026/27`

**Ни номер контейнера, ни номер логотипа — не номер канала.** Настоящие
имена стоят на самой странице `/broadcast-schedule/` в заголовках
`<h2 data-channel-id="N">ספורט M</h2>` (снято пробой 07.09, прогон #254):

    контейнер 2 · логотип sport1-1 → Спорт 1
    контейнер 3 · логотип sport1-3 → Спорт 2
    контейнер 4 · логотип sport1-4 → Спорт 3
    контейнер 5 · логотип sport1-5 → Спорт 4
    контейнер 1 · логотип sport1-6 → Спорт 6

`channel_raw` остаётся «Sport1 <логотип>» — это ключ алиаса в базе
(`channel_aliases`, источник 89), а показываемое имя — `channels.canonical_name`,
его и правим по карте выше (`CHANNEL_NAMES`). До 07.09 каналы в базе звались
«Sport 1 (4)» и т. п., и владелец искал игры не на той вкладке сайта.

Женские матчи сайт помечает словом `נשים` в описании — оно добавлено в
`app/leagues.py`, иначе женская пара склеилась бы с мужской (`ГРАБЛИ.md`).
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "sport1.maariv.co.il"
TZ = "Asia/Jerusalem"

#: логотип `sport1-N` → как канал называется на сайте (см. докстринг)
CHANNEL_NAMES = {"1": "Sport 1", "3": "Sport 2", "4": "Sport 3",
                 "5": "Sport 4", "6": "Sport 6"}

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})")
_LOGO = re.compile(r"sport1-(\d+)-channel-logo")
_DAY_CLASS = re.compile(r"shows-container-for-(\d{4})-(\d{2})-(\d{2})")
_LIVE = "ישיר"


def _pair(text: str) -> str:
    for sep in (" - ", " – "):
        if sep in text:
            home, _, away = text.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    body = html.lstrip()
    if body[:1] == '"':
        # ответ — JSON-строка с разметкой внутри
        try:
            html = json.loads(body)
        except ValueError:
            return []
    tree = HTMLParser(html)
    day = day or _date.today()

    out: list[Program] = []
    for block in tree.css("div.channel-container"):
        logo = block.css_first(".channel-name-wrapper img")
        got = _LOGO.search((logo.attributes.get("src") or "") if logo else "")
        if not got:
            continue
        channel = f"Sport1 {got.group(1)}"
        if channels and channel not in channels:
            continue
        for holder in block.css("div.date-shows-container"):
            stamp = _DAY_CLASS.search(holder.attributes.get("class") or "")
            d = _date(int(stamp.group(1)), int(stamp.group(2)),
                      int(stamp.group(3))) if stamp else day
            for show in holder.css("div.show-container"):
                time_node = show.css_first("p.show-starting-time")
                name_node = show.css_first("p.show-name")
                if not time_node or not name_node:
                    continue
                hm = _HHMM.match(time_node.text(strip=True))
                title = " ".join(name_node.text().split())
                if not hm or not title:
                    continue
                status = show.css_first("p.show-second-status")
                status = status.text(strip=True) if status else ""
                league = show.css_first("p.show-description")
                league = " ".join(league.text().split()) if league else ""
                # день сетки у сайта — КАЛЕНДАРНЫЙ (израильский): матч в 03:20
                # лежит в дне 11.09 и идёт 11.09 в 03:20 — сверено 07.09 по
                # эталону flashscore (Cienciano — Montevideo City 11.09 03:30,
                # River — Ind. Rivadavia 07.09 01:15). Прежний сдвиг ночных
                # часов на сутки «как у остальных источников» ставил такие игры
                # на витрину днём позже, и эталон их не находил
                when = d
                out.append(Program(
                    channel_raw=channel, title=title,
                    start=datetime(when.year, when.month, when.day,
                                   int(hm.group(1)), int(hm.group(2)),
                                   tzinfo=zone),
                    raw_time=hm.group(0), league_raw=league[:120],
                    live_raw=status if status == _LIVE else "",
                    match_raw=_pair(title), source_url=url,
                    extra={"day": when.isoformat()},
                ))
    return out

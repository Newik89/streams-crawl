# -*- coding: utf-8 -*-
"""mediaklikk.hu — Венгрия, портал общественного вещателя MTVA.

**Чем ценен.** Здесь лежит расписание **M4 Sport** — канала, из-за которого
`programetv.ro` пришлось выключить (румынский агрегатор отдавал по нему
пустые заголовки, см. `ОТЛОЖЕНО.md`). Сайт самого канала (`m4sport.hu`)
рвал соединение, а портал открывается обычным запросом.

Адрес `/musorujsag/` отдаёт сетку всех каналов MTVA на день — один запрос.

Разметка удобная: у каждой передачи стоит машинное время со смещением.

    div.tvguide.channel
      div.channel_logo[style=…/channel_logos_small/30_h.png]   ← номер канала
      li.program_body[data-from="2026-08-31 20:00:00+0200"]
        div.time > time            `20:00`
        div.elo                    `Élő` — прямой эфир
        div.program_info > h1      заголовок
        div.program_info > p       подзаголовок (часто и есть пара команд)

**Имя канала на странице пустое** (`p.channel_name` без текста) — есть только
номер в адресе логотипа. Поэтому берём те номера, которые опознаны по составу
сетки; `30` — это M4 Sport (велоспорт, каякинг, «M4 pillanatok»). Остальные
номера — общие каналы и радио MTVA; чтобы не подписать канал наугад, они
пропускаются. Опознавать их надо по живой сетке, а не по догадке.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "mediaklikk.hu"
TZ = "Europe/Budapest"

#: номер в адресе логотипа → имя канала. Пополнять по мере опознания.
CHANNELS = {"30": "M4 Sport"}

_LOGO = re.compile(r"/(\d+)_h\.png")
_STAMP = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})")
_LIVE = "él"


#: Хвосты венгерского анонса, приклеенные к имени гостей:
#: «Szlovénia - Magyarország mérkőzés» («матч»), «… közvetítés» («трансляция»).
_TAIL = re.compile(r"\s+(mérkőzés\w*|közvetítés\w*|élőben|ismétlés\w*)\s*$", re.I)


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs ", " VS ", " – ", "-"):
        if sep in text:
            home, _, away = text.partition(sep)
            home, away = home.strip(), _TAIL.sub("", away.strip()).strip()
            if home and away and (sep != "-" or " " in home or " " in away):
                return f"{home} - {away}"
            if sep == "-":
                break
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)

    out: list[Program] = []
    for block in tree.css("div.tvguide.channel"):
        logo = block.css_first(".channel_logo")
        got = _LOGO.search((logo.attributes.get("style") or "") if logo else "")
        channel = CHANNELS.get(got.group(1)) if got else None
        if not channel or (channels and channel not in channels):
            continue
        for item in block.css("li.program_body"):
            stamp = _STAMP.match(item.attributes.get("data-from") or "")
            head = item.css_first(".program_info h1")
            title = " ".join(head.text().split()) if head else ""
            if not stamp or not title:
                continue
            sub_node = item.css_first(".program_info p")
            sub = " ".join(sub_node.text().split()) if sub_node else ""
            # блок «Élő» стоит у КАЖДОЙ передачи, но у непрямых он спрятан
            # классом `dn` и `display:none` — без этой проверки эфиром
            # оказывается вся сетка целиком
            elo = item.css_first("div.elo")
            live = bool(elo and _LIVE in elo.text(strip=True).lower()
                        and "dn" not in (elo.attributes.get("class") or "").split()
                        and "none" not in (elo.attributes.get("style") or ""))
            # Пара надёжнее в подзаголовке: там она подписана целиком
            # («Szlovénia - Magyarország mérkőzés»), а в заголовке на её
            # месте бывает описание с дефисом («Férfi kosárlabda vb -
            # selejtező»). Поэтому сначала подзаголовок, потом заголовок.
            sub_pair = sub.split(":", 1)[-1].strip() if ":" in sub else sub
            pair = _pair(sub_pair) if _pair(sub_pair).strip() else _pair(title)
            start = datetime(int(stamp.group(1)), int(stamp.group(2)),
                             int(stamp.group(3)), int(stamp.group(4)),
                             int(stamp.group(5)), tzinfo=zone)
            out.append(Program(
                channel_raw=channel, title=title, start=start,
                raw_time=f"{stamp.group(4)}:{stamp.group(5)}",
                description=sub[:200], league_raw=sub[:120],
                live_raw="élő" if live else "",
                match_raw=pair, source_url=url,
                extra={"day": start.date().isoformat()},
            ))
    # «Élő» сайт ставит только текущей передаче, будущие матчи идут без
    # пометки — как у `oneplaysport.cz`, помечаем первый показ пары
    return mark_first_show(out, "élő")

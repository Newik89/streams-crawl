# -*- coding: utf-8 -*-
"""mediaklikk.hu — Венгрия, портал общественного вещателя MTVA.

**Чем ценен.** Здесь лежит расписание **M4 Sport** — канала, из-за которого
`programetv.ro` пришлось выключить (румынский агрегатор отдавал по нему
пустые заголовки, см. `ОТЛОЖЕНО.md`). Сайт самого канала (`m4sport.hu`)
рвал соединение, а портал открывается обычным запросом.

Адрес `/musorujsag/` отдаёт сетку всех каналов MTVA, но только на СЕГОДНЯ.
Другие дни страница догружает скриптом (`ProgramGuide.js`, функция
`getChanelGuides`): POST на

    https://mediaklikk.hu/wp-content/plugins/hms-global-widgets/widgets/
        programGuide/programGuideInterface.php

с полями `ChannelIds=30,34,` (номера через запятую, с хвостовой),
`ShortCodes=m4,m4p,`, `Names=…`, `Date=ГГГГ-ММ-ДД`, `Type=0` (ТВ),
`buttonType=text_type`, `newDesign=true`. Ответ — те же блоки
`div.tvguide.channel`, что и на странице, только выбранные каналы и день
(проба #208: 10.10, M4 Sport и M4 Sport+, Ferencvárosi TC - DVSC в 16:57).
Окно сайта — 14 дней вперёд. GET на ту же ручку отдаёт «страница не
найдена» (проба #207). Поэтому сайт — «дневная сетка»
(`DAY_GRID_DOMAINS`), поля формы лежат в карточке источника
(`post_fields`, дата — меткой `{YYYY-MM-DD}`; `scripts/add_mediaklikk_days.py`).

Разметка удобная: у каждой передачи стоит машинное время со смещением.

    div.tvguide.channel
      div.channel_logo[style=…/channel_logos_small/30_h.png]   ← номер канала
      li.program_body[data-from="2026-08-31 20:00:00+0200"]
        div.time > time            `20:00`
        div.elo                    `Élő` — прямой эфир
        div.program_info > h1      заголовок
        div.program_info > p       подзаголовок (часто и есть пара команд)

**Имя канала в блоке пустое** (`p.channel_name` без текста) — есть номер в
адресе логотипа. Поэтому берём те номера, которые опознаны; `30` — это M4
Sport (велоспорт, каякинг, «M4 pillanatok»), `34` — M4 Sport+ (06.10: у
обёртки блока `data-channelname="M4 Sport +"`, в настройке страницы номер
34 ведёт на прямой эфир `mtv4plus`). Остальные номера — общие каналы и
радио MTVA; чтобы не подписать канал наугад, они пропускаются.

**Эфир.** «Élő» у будущих передач спрятан всегда (проба #208: на 10.10 все
45 пометок с `display: none`), так что эфир угадывается первым показом пары
(`mark_first_show`), домен — в `REPEAT_GUESS_DOMAINS`. Матч сайт режет на
куски (тайм, перерыв, тайм: 16:57, 17:51, 17:59) — эфир получает первый.
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
CHANNELS = {"30": "M4 Sport", "34": "M4 Sport+"}

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

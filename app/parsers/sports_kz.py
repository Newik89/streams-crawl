# -*- coding: utf-8 -*-
"""sports.kz — Казахстан; страница «спорт на казахстанском ТВ», неделя вперёд.

Один запрос `/tv` отдаёт шесть дней по каналу Qazsport (сайт показывает
только его). Даты — заголовками дней, поэтому окно «сегодня + 6» покрывается
целиком одним ответом.

    div.tv_day_
      h3                       `вт` + `<span>1 сентября</span>`
      ul.tv_telekanal-…
        li:first > a[title]    `Телеканал «Qazsport»` — имя канала
        li > span              `07:05`
        li > p                 `Футбол. УЕФА Еуропа Лигасы. Плей-офф кезеңі.
                                «Қайрат» (Қазақстан) — «Андерлехт» (Бельгия)`

Заголовок казахский: вид спорта и турнир идут через точку, пара — в конце,
через длинное тире, имена в кавычках-ёлочках, страна в скобках. Кавычки и
скобки снимаем — иначе `«Қайрат» (Қазақстан)` не совпадёт с `Kairat` из
других источников (таблица казахской кириллицы уже есть в `app/translit.py`).
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "sports.kz"
TZ = "Asia/Almaty"

_MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5,
           "июня": 6, "июля": 7, "августа": 8, "сентября": 9, "октября": 10,
           "ноября": 11, "декабря": 12}

_DAY_HEAD = re.compile(r"(\d{1,2})\s+([а-яё]+)", re.I)
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_COUNTRY = re.compile(r"\s*\([^)]*\)\s*")


def _clean_team(name: str) -> str:
    return _COUNTRY.sub("", name).strip(' «»"\u00a0')


def _pair(text: str) -> str:
    for sep in (" — ", " – ", " - "):
        if sep in text:
            home, _, away = text.partition(sep)
            home, away = _clean_team(home), _clean_team(away)
            if home and away:
                return f"{home} - {away}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    today = day or _date.today()
    tree = HTMLParser(html)

    out: list[Program] = []
    for block in tree.css("div.tv_day_"):
        head = block.css_first("h3")
        got = _DAY_HEAD.search(" ".join(head.text().split())) if head else None
        month = _MONTHS.get(got.group(2).lower()) if got else None
        if not month:
            continue
        year = today.year + (1 if month < today.month else 0)
        current = _date(year, month, int(got.group(1)))
        for group in block.css("ul"):
            link = group.css_first("a[title]")
            channel = (link.attributes.get("title") or "").strip() if link else ""
            if not channel or (channels and channel not in channels):
                continue
            for item in group.css("li"):
                time_node = item.css_first("span")
                title_node = item.css_first("p")
                if not time_node or not title_node:
                    continue
                hm = _HHMM.match(time_node.text(strip=True))
                title = " ".join(title_node.text().split())
                if not hm or not title:
                    continue
                # `Футбол. Лига. Этап. «А» — «Б»` — вид спорта первым куском
                parts = [x.strip() for x in title.split(".") if x.strip()]
                pair = " "
                for chunk in reversed(parts):
                    got_pair = _pair(chunk)
                    if got_pair.strip():
                        pair = got_pair
                        break
                out.append(Program(
                    channel_raw=channel, title=title,
                    start=datetime(current.year, current.month, current.day,
                                   int(hm.group(1)), int(hm.group(2)),
                                   tzinfo=zone),
                    raw_time=hm.group(0),
                    sport_raw=parts[0] if parts else "",
                    league_raw=" ".join(parts[1:-1])[:120] if len(parts) > 2 else "",
                    match_raw=pair, source_url=url,
                    extra={"day": current.isoformat()},
                ))
    # маркера эфира сайт не даёт вовсе — помечаем первый показ пары
    return mark_first_show(out, "тікелей эфир")

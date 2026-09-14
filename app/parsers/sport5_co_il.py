# -*- coding: utf-8 -*-
r"""sport5.co.il — Израиль, каналы «Спорт 5»; пять каналов за один запрос.

Страница `/html/pages/broadcastsheet.html` приходит с пустой таблицей —
её наполняет скрипт. Адрес запроса виден в самой странице
(`var broadcastAjaxUrl = '/Ajax/GetBroadcastSheetData.aspx'`), а вот
параметр пришлось подобрать: работает **`?date=ДД/ММ/ГГГГ`** (косые чёрточки
в адресе кодируются). С `bcDate=` и без параметров ответ пустой.

Ответ — кусок таблицы:

    <tr class="tr-header"><th><img alt="ערוץ הספורט"></th></tr>
    <tr>
      <td class="date"><div>16:00</div>
                       <div><img src="/images/img-live.png" alt="ישיר"></div></td>
      <td class="text">מסע"ת: הפועל תל אביב לקראת בית"ר ירושלים</td>
    </tr>

Имя канала — в `alt` логотипа заголовка; строки до следующего заголовка
относятся к нему. Прямой эфир сайт помечает картинкой `img-live.png`
(`ישיר` — «прямой»), то же слово, что и у соседнего `sport1.maariv.co.il`.

Сайт отдаёт **остаток текущего дня**, а не сутки целиком (как `nova.bg`):
за полную картину отвечает окно обхода, а не этот парсер.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "sport5.co.il"
TZ = "Asia/Jerusalem"

_HHMM = re.compile(r"(\d{1,2}):(\d{2})")
_DATE = re.compile(r"date=(\d{2})[/%]2?[Ff]?(\d{2})[/%]2?[Ff]?(\d{4})")
_LIVE = "ישיר"
#: хвост заголовка — тур или стадия: «…, מחזור 5», «…, שלב הבתים»
_ROUND = re.compile(r"\s*,\s*[^,]*(?:\d|מחזור|שלב|סיבוב|גמר|חצי|רבע)[^,]*$")


def _league(text: str) -> str:
    """Лига — перед двоеточием: «ליגה צרפתית בכדורגל הנשים: מונפלייה -
    מארסיי». В ней же вид спорта («בכדורגל») и пол («הנשים»): без лиги
    женский матч Монпелье шёл мужским, а Paris FC — Strasbourg не сводился
    с эталоном вовсе (#2525, #2499, владелец 14.09)."""
    return text.split(":", 1)[0].strip()[:120] if ":" in text else ""


def _pair(text: str) -> str:
    """Пара команд — после двоеточия, через дефис или ивритское «против»."""
    tail = text.split(":", 1)[1] if ":" in text else text
    tail = _ROUND.sub("", tail)
    for sep in (" - ", " – ", " נגד ", " לקראת "):
        if sep in tail:
            home, _, away = tail.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    got = _DATE.search(url or "")
    base = _date(int(got.group(3)), int(got.group(2)), int(got.group(1))) \
        if got else (day or _date.today())

    tree = HTMLParser(html)
    out: list[Program] = []
    channel = ""
    for row in tree.css("tr"):
        if "tr-header" in (row.attributes.get("class") or ""):
            logo = row.css_first("img")
            channel = (logo.attributes.get("alt") or "").strip() if logo else ""
            continue
        if not channel or (channels and channel not in channels):
            continue
        when = row.css_first("td.date")
        name = row.css_first("td.text")
        if not when or not name:
            continue
        hm = _HHMM.search(when.text())
        title = " ".join(name.text().split())
        if not hm or not title:
            continue
        hour, minute = int(hm.group(1)), int(hm.group(2))
        # телегид-день начинается утром: ночные часы — уже следующая дата
        d = base + timedelta(days=1) if hour < 6 else base
        live = row.css_first('img[src*="img-live"]')
        out.append(Program(
            channel_raw=channel, title=title,
            start=datetime(d.year, d.month, d.day, hour, minute, tzinfo=zone),
            raw_time=hm.group(0), league_raw=_league(title),
            live_raw=_LIVE if live is not None else "",
            match_raw=_pair(title), source_url=url,
            extra={"day": d.isoformat()},
        ))
    return out

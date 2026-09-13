# -*- coding: utf-8 -*-
r"""rts.rs — Сербия, каналы РТС; адрес на канал, в ответе сутки.

Сайт долго считался пустым: `www.rts.rs/tv/rts1/broadcast.html` отдаёт
страницу, где блок `div#programska-sema` пуст — и запросу, и браузеру, даже
с ожиданием догрузки. Разгадку подсказал владелец: **работает адрес без
`www`**. Тот же путь на `rts.rs` возвращает полную сетку.

    https://rts.rs/tv/rts2/broadcast.html

Разметка простая:

    <div class="programRow rowOdd">
      <div class="time ColorSport">16:00</div>
      <div class="name">Фудбал: Партизан - Црвена звезда</div>
    </div>

Категорию сайт кладёт в класс времени (`ColorSport`, `ColorFilmovi`,
`ColorVesti`) — по ней сразу видно спортивные строки, не разбирая заголовок.

Дату берём из заголовка страницы (`уторак, 01. сеп 2026`), а не из адреса:
в адресе месяц нумеруется с нуля (`m=8` — сентябрь), и на этом уже
спотыкались (`ГРАБЛИ.md`). Признака прямого эфира у сайта нет — эфир
определяем первым показом пары.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "rts.rs"
TZ = "Europe/Belgrade"

_HHMM = re.compile(r"(\d{1,2}):(\d{2})")
_CHANNEL = re.compile(r"/tv/([a-z0-9-]+)/broadcast", re.I)
#: `уторак, 01. сеп 2026` — сербские сокращения месяцев
_MONTHS = {"јан": 1, "феб": 2, "мар": 3, "апр": 4, "мај": 5, "јун": 6,
           "јул": 7, "авг": 8, "сеп": 9, "окт": 10, "нов": 11, "дец": 12}
_TITLE_DATE = re.compile(r"(\d{1,2})\.\s*([а-шђјљњћџ]{3})\s*(\d{4})", re.I)

#: как канал называется у зрителя
NAMES = {"rts1": "РТС 1", "rts2": "РТС 2", "rts3": "РТС 3",
         "rts-sat": "РТС САТ", "rts-svet": "РТС Свет",
         "rts-digital": "РТС Дигитал", "rts-drama": "РТС Драма",
         "rts-klasika": "РТС Класика", "rts-kolo": "РТС Коло",
         "rts-muzika": "РТС Музика", "rts-nauka": "РТС Наука",
         "rts-poletarac": "РТС Полетарац", "rts-trezor": "РТС Трезор",
         "rts-zivot": "РТС Живот"}


def _pair(text: str) -> str:
    tail = text.split(":", 1)[1] if ":" in text else text
    for sep in (" - ", " – ", " — "):
        if sep in tail:
            home, _, away = tail.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


def _day_from_title(tree) -> _date | None:
    head = tree.css_first("h1.title") or tree.css_first("h1")
    got = _TITLE_DATE.search(head.text()) if head else None
    if not got:
        return None
    month = _MONTHS.get(got.group(2).lower())
    return _date(int(got.group(3)), month, int(got.group(1))) if month else None


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)
    base = _day_from_title(tree) or day or _date.today()

    got = _CHANNEL.search(url or "")
    slug = got.group(1).lower() if got else ""
    channel = NAMES.get(slug, slug.upper() or "РТС")
    if channels and channel not in channels:
        return []

    out: list[Program] = []
    for row in tree.css("div.programRow"):
        mark = row.css_first("div.time")
        name = row.css_first("div.name")
        if not mark or not name:
            continue
        hm = _HHMM.search(mark.text())
        # в блоке имени рядом с заголовком лежит скрытая подсказка
        # (`div#cluetip`) с полным описанием — берём только саму ссылку,
        # иначе заголовок склеивается сам с собой
        link = name.css_first("a")
        title = " ".join((link or name).text().split())
        if not hm or not title:
            continue
        hour, minute = int(hm.group(1)), int(hm.group(2))
        # день сетки начинается утром: ночные часы — уже следующая дата
        d = base + timedelta(days=1) if hour < 5 else base
        kind = mark.attributes.get("class") or ""
        out.append(Program(
            channel_raw=channel, title=title,
            start=datetime(d.year, d.month, d.day, hour, minute, tzinfo=zone),
            raw_time=hm.group(0),
            sport_raw="спорт" if "ColorSport" in kind else "",
            match_raw=_pair(title), source_url=url,
            extra={"day": d.isoformat()},
        ))
    return mark_first_show(out, "директан пренос")

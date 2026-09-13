# -*- coding: utf-8 -*-
r"""skai.gr — Греция, канал ΣΚΑΪ; адрес на день, канал один.

Ссылку принёс владелец. Сайт открытый — пускает и раннер GitHub, и наш
сервер, читалка ему не нужна:

    https://www.skai.gr/tv/programma/2026-09-06

Разметка простая, но заголовка передачи в привычном теге нет — он лежит в
`div.h2` (класс, а не тег):

    <div class="col-md-12 … list1 color_athlitika monobala-2 …">
      <div class="col-lg-1 ti"><span>12:30</span>
        <div class="live-img"><a href="/tv/live"><span>LIVE</span></a></div></div>
      <a href="/tv/episode/athlitika/monobala-2/2026-09-06-12">
        <div class="h2">Monobala</div>
        <p class="date">Το ποδόσφαιρο παίζει δυνατά στον ΣΚΑΪ…</p></a>
    </div>

Категорию сайт кладёт в класс строки (`color_athlitika` — спортивная) и в
адрес эпизода (`/tv/episode/athlitika/…`). Берём её как вид спорта: для
греческого «αθλητικά» этого мало, чтобы назвать игру футболом, но описание
под заголовком обычно называет спорт своим словом (`ποδόσφαιρο`).

Пометка `LIVE` у сайта означает прямой эфир канала в этот час, а не
трансляцию матча, поэтому в маркер эфира её не превращаем: эфир, как у
`ert.gr`, определяем первым показом пары.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "skai.gr"
TZ = "Europe/Athens"
CHANNEL = "ΣΚΑΪ"

_HHMM = re.compile(r"(\d{1,2}):(\d{2})")
_DAY = re.compile(r"/programma/(\d{4})-(\d{2})-(\d{2})")
_KIND = re.compile(r"color_([a-z]+)")


def _pair(text: str) -> str:
    tail = text.split(":", 1)[1] if ":" in text else text
    for sep in (" - ", " – ", " — ", " vs "):
        if sep in tail:
            home, _, away = tail.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    if channels and CHANNEL not in channels:
        return []
    got = _DAY.search(url or "")
    base = _date(int(got.group(1)), int(got.group(2)), int(got.group(3))) \
        if got else (day or _date.today())

    tree = HTMLParser(html)
    out: list[Program] = []
    for row in tree.css("div.list1"):
        mark = row.css_first("div.ti span")
        head = row.css_first("div.h2")
        if not mark or not head:
            continue
        hm = _HHMM.search(mark.text())
        title = " ".join(head.text().split())
        if not hm or not title:
            continue
        hour, minute = int(hm.group(1)), int(hm.group(2))
        # день сетки начинается утром: ночные часы — уже следующая дата
        d = base + timedelta(days=1) if hour < 5 else base
        about = row.css_first("p.date")
        about = " ".join(about.text().split()) if about else ""
        kind = _KIND.search(row.attributes.get("class") or "")
        out.append(Program(
            channel_raw=CHANNEL, title=title,
            start=datetime(d.year, d.month, d.day, hour, minute, tzinfo=zone),
            raw_time=hm.group(0), description=about[:300],
            sport_raw=(kind.group(1) if kind else ""),
            match_raw=_pair(title) if _pair(title).strip() else _pair(about),
            source_url=url, extra={"day": d.isoformat()},
        ))
    return mark_first_show(out, "ζωντανά")

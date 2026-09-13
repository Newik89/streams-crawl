# -*- coding: utf-8 -*-
"""rtcg.me — Черногория, общественное вещание: TVCG 1/2/3 и TVMNE.

**Только браузером.** На обычный запрос сайт отвечает честным `200` и отдаёт
каркас без единой строки расписания — сетку рисует скрипт. Поэтому у источника
стоит `needs_js=1`, и обход берёт его сразу браузером (`--browser` в
`crawl_fetch.py`). Именно на этом сайте правило и понадобилось: запасной путь
через браузер включается по отказу, а отказа тут нет.

Адрес: `/tv/programska-sema.html?broadcastId=КАНАЛ&typeId=0&day=НОМЕР`.
`broadcastId`: TVCG 1 — 177, TVCG 2 — 178, TVCG 3 — 978, TVMNE — 179.
`day` — номер дня от сегодня, начиная с нуля (метка `{DAYNUM}` в шаблоне);
даты в адресе нет вовсе. `typeId=1018` отфильтровал бы только спорт, но мы
берём всю сетку: матчи сборной идут и в общей программе.

Разметка простая, всё в неразрывных пробелах:

    div.tabs-container
      div.guideBrowser
        div.time    `05:00`
        div.title   `Košarka: Crna Gora - Ukrajina, kvalifikacije za SP, direktno`

Заголовок: вид спорта до двоеточия, дальше пара через дефис, а в хвосте через
запятую — турнир и пометка эфира. `direktno` — честный маркер прямой
трансляции, `snimak` и `r` (repriza) — повтор.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "rtcg.me"
TZ = "Europe/Podgorica"

#: `broadcastId` в адресе → имя канала, как оно заведено в базе
CHANNELS = {"177": "TVCG 1", "178": "TVCG 2", "978": "TVCG 3", "179": "TVMNE"}

_HHMM = re.compile(r"(\d{1,2}):(\d{2})")
_ID_IN_URL = re.compile(r"broadcastId=(\d+)")
_DAY_IN_URL = re.compile(r"[?&]day=(\d+)")
_LIVE = re.compile(r"\bdirektno\b", re.I)


def _clean(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    got = _ID_IN_URL.search(url or "")
    channel = CHANNELS.get(got.group(1)) if got else None
    if not channel or (channels and channel not in channels):
        return []
    # даты в адресе нет — только номер дня от сегодняшнего
    day = day or _date.today()
    shift = _DAY_IN_URL.search(url or "")
    if shift and not day:
        day = _date.today() + timedelta(days=int(shift.group(1)))
    tree = HTMLParser(html)

    out: list[Program] = []
    for item in tree.css("div.guideBrowser"):
        time_node = item.css_first("div.time")
        title_node = item.css_first("div.title")
        if not time_node or not title_node:
            continue
        hm = _HHMM.search(_clean(time_node.text()))
        title = _clean(title_node.text())
        if not hm or not title:
            continue
        sport, _, rest = title.partition(":")
        rest = rest.strip()
        # хвост после запятой — турнир и пометка эфира, в пару он не входит
        head = rest.split(",")[0].strip() if rest else ""
        pair = " "
        for sep in (" - ", " – "):
            if sep in head:
                home, _, away = head.partition(sep)
                if home.strip() and away.strip():
                    pair = f"{home.strip()} - {away.strip()}"
                break
        d = day + timedelta(days=1) if int(hm.group(1)) < 5 else day
        out.append(Program(
            channel_raw=channel, title=title,
            start=datetime(d.year, d.month, d.day,
                           int(hm.group(1)), int(hm.group(2)), tzinfo=zone),
            raw_time=hm.group(0),
            league_raw=", ".join(rest.split(",")[1:]).strip()[:120] if rest else "",
            sport_raw=sport.strip() if rest else "",
            live_raw="direktno" if _LIVE.search(title) else "",
            match_raw=pair, source_url=url,
            extra={"day": d.isoformat()},
        ))
    return out

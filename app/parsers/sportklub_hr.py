# -*- coding: utf-8 -*-
"""sportklub.hr — Хорватия, каналы Sport Klub (United Cloud), уровень A.

Страница `sportklub.hr/tv-program/` пустая: сетку рисует виджет United Cloud
(`web-apps.ug.cdn.united.cloud/epg/bundle.js`). Данные — открытая ручка:

    https://api-web.ug-be.cdn.united.cloud/v1/public/events/epg
        ?cid=556&fromTime=<мс>&toTime=<мс>
        &communityIdentifier=sk_hr&languageId=181

Пускает только с гостевым ключом и заголовком `X-UCP-TIME-FORMAT:
timestamp` — это делает `app/fetch.py` (`TOKEN_HOSTS`). Один канал за
запрос, зато сразу на неделю: у Sport Klub опубликовано ~4 дня (16.09).

Ответ: `{"556": [{"title", "startTime", "endTime", "liveBroadcast",
"categories", "shortDescription", …}]}`, время — мс UTC.

Заголовок: `Nogomet - Španjolska liga: Barcelona - Racing` — до двоеточия
вид спорта и турнир, после — пара. Без двоеточия пары нет («Nizozemska liga
- Pregled» — это обзор). Прямой эфир сайт помечает сам: `liveBroadcast`.
"""

from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "sportklub.hr"
TZ = "Europe/Zagreb"

#: номер канала ручки → имя у зрителя. SK 1–5 — те же каналы, что приходят
#: с `mojtv.hr` («Sport Klub 1» и т.д.), имена совпадают, чтобы не двоить.
#: Список — из `/v1/public/channels?…sk_hr` (16.09)
CHANNELS = {
    "556": "Sport Klub 1", "923": "Sport Klub 2", "924": "Sport Klub 3",
    "928": "Sport Klub 4", "728": "Sport Klub 5", "927": "Sport Klub 6",
    "1072": "Sport Klub 7", "1073": "Sport Klub 8", "1074": "Sport Klub 9",
    "1075": "Sport Klub 10", "925": "Sport Klub 11", "926": "Sport Klub 12",
    "644": "Sport Klub 4K", "73": "Sport Klub Golf", "72": "Sport Klub Fight",
    "929": "Sport Klub Esports",
}

_LIVE = "uživo"


def _split(title: str) -> tuple[str, str, str]:
    """`Nogomet - Španjolska liga: Barcelona - Racing` →
    (вид спорта, турнир, пара). Без двоеточия пары нет.

    Пара — после ПОСЛЕДНЕГО двоеточия: бывает и `Nogomet: Liga prvaka Azije
    - TWO: Wahda - Kuwait`, и `Nogomet: 2. Bundesliga: Greuther Furth -
    Magdeburg` (по первому двоеточию пара терялась, 16.09)."""
    head, colon, tail = title.rpartition(":")
    if not colon:
        return "", "", " "
    first, more, rest = head.partition(":")
    if more:                                  # `Nogomet: 2. Bundesliga`
        sport, league = first, rest
    else:
        sport, dash, league = head.partition(" - ")
        if not dash:                          # одно слово — вид спорта
            sport, league = (head, "") if " " not in head.strip() else ("", head)
    tail = tail.strip()
    home, sep, away = tail.partition(" - ")
    pair = f"{home.strip()} - {away.strip()}" if sep and home.strip() and away.strip() else " "
    return sport.strip(), league.strip(), pair


def _categories(event: dict) -> str:
    names = []
    for item in event.get("categories") or []:
        name = item.get("name") if isinstance(item, dict) else item
        # у ручки в категориях бывает служебный номер («205») — не слово
        if name and not str(name).strip().isdigit():
            names.append(str(name))
    return " ".join(names)


@register(DOMAIN)
def parse(html: str, *, day=None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = json.loads(html)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    zone = ZoneInfo(tz or TZ)
    asked = (parse_qs(urlsplit(url).query).get("cid") or [""])[0]

    out: list[Program] = []
    for cid, events in data.items():
        if not isinstance(events, list):
            continue
        name = CHANNELS.get(str(cid)) or CHANNELS.get(asked) or f"Sport Klub {cid}"
        if channels and name not in channels:
            continue
        for event in events:
            title = " ".join((event.get("title") or "").split())
            stamp = event.get("startTime")
            if not title or not isinstance(stamp, (int, float)):
                continue
            start = datetime.fromtimestamp(stamp / 1000, tz=zone)
            sport, league, pair = _split(title)
            out.append(Program(
                channel_raw=name, title=title, start=start,
                raw_time=start.strftime("%H:%M"),
                description=" ".join((event.get("shortDescription") or "").split())[:300],
                league_raw=league[:120],
                sport_raw=" ".join(x for x in (sport, _categories(event)) if x)[:80],
                live_raw=_LIVE if event.get("liveBroadcast") else "",
                match_raw=pair, source_url=url,
                extra={"day": start.date().isoformat(), "cid": str(cid)},
            ))
    return out

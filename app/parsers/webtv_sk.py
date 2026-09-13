# -*- coding: utf-8 -*-
r"""webtv.sk — Словакия, 181 канал; свой запрос на канал и день.

Этим сайтом закрылся `jojsport.joj.sk`: у самого JOJ ручка `/api/v1/program/
details` так и не поддалась (параметры лежат в отдельном чанке виджета), а
здесь те же каналы отдаются открыто. Адрес подсмотрен в проекте
`iptv-org/epg` — приём, который до этого закрыл `port.hu`.

Список каналов:

    POST https://api.webtv.sk/channels     {"type": "TV", "channels_content": null}

Расписание канала за сутки:

    POST https://api.webtv.sk/epg/channel  {"channel_id": "joj_sport",
                                            "date": "2026-09-01T00:00:00.000Z"}

Ответ:

    {"id": …, "content": [
        {"ChannelTitle": "JOJ Šport", "Start": "2026-09-01T01:00:00+02:00",
         "Stop": "…", "Title": "Futbal", "Subtitle": "Slovan - Trnava",
         "Description": "…", "Genres": [...]}]}

`Start` уже со смещением, пересчитывать не нужно. Пара команд обычно в
подзаголовке (`Subtitle`), а вид спорта — в самом заголовке (`Futbal`,
`Basketbal`), поэтому в `sport_raw` кладём заголовок, а разбираем подзаголовок.

Признака прямого эфира сайт не даёт — эфир определяем первым показом пары.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, mark_first_show, register

DOMAIN = "webtv.sk"
TZ = "Europe/Bratislava"

_ID = re.compile(r'"channel_id"\s*:\s*"([a-z0-9_]+)"')

#: как канал зовётся у зрителя (ключ — `channel_id` сайта)
NAMES = {"joj_sport": "JOJ Šport", "joj_sport_2": "JOJ Šport 2",
         "arena_sport_1": "Kanal1 Sport", "nova_sport_1_hd": "Nova Sport 1",
         "nova_sport_2_hd": "Nova Sport 2", "eurosport_1": "Eurosport 1",
         "eurosport_2": "Eurosport 2", "sport_1": "Sport 1", "sport_2": "Sport 2"}


#: номер тура в начале подзаголовка: `2. kolo Lecce - Řím`. Без этого он
#: прилипает к имени хозяев (та же беда, что ловили на `digisport.ro`)
_ROUND = re.compile(r"^\s*\d{1,2}\.\s*(kolo|kolá|týždeň|zápas)\s*", re.I)


#: описание идёт сплошной строкой: `Kanada - Slovensko Záznam zápasu…`.
#: Всё, что после служебного слова, к именам команд уже не относится
_TAIL = re.compile(r"\s+(Záznam|Priamy|Prenos|Zostrih|Štúdio|,).*$", re.I | re.S)


def _pair(text: str) -> str:
    """Пара команд из описания вроде `Serie A, 2. kolo Lecce - Řím, (šport)`.

    Описание идёт сплошной строкой: лига, тур, сама пара и служебный хвост —
    всё через запятую. Поэтому режем по запятым и берём тот кусок, где есть
    разделитель пары, а из него снимаем номер тура.
    """
    text = _TAIL.sub("", text)
    for part in text.split(","):
        part = _ROUND.sub("", part).strip()
        for sep in (" - ", " – ", " — ", " vs "):
            if sep in part:
                home, _, away = part.partition(sep)
                if home.strip() and away.strip():
                    return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
@register("api.webtv.sk")
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    try:
        data = json.loads(html)
    except ValueError:
        return []
    shows = data.get("content") if isinstance(data, dict) else None
    if not isinstance(shows, list):
        return []

    out: list[Program] = []
    for show in shows:
        if not isinstance(show, dict):
            continue
        title = " ".join((show.get("Title") or "").split())
        stamp = show.get("Start") or ""
        if not title or not stamp:
            continue
        try:
            start = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=zone)
        # имя канала сайт кладёт в каждую строку; если не положил — берём из
        # запроса, там `channel_id`
        channel = " ".join((show.get("ChannelTitle") or "").split())
        if not channel:
            got = _ID.search(url or "")
            channel = NAMES.get(got.group(1), got.group(1)) if got else DOMAIN
        if channels and channel not in channels:
            continue
        sub = " ".join((show.get("Subtitle") or "").split())
        about = " ".join((show.get("Description") or "").split())
        out.append(Program(
            channel_raw=channel, title=f"{title}: {sub}" if sub else title,
            start=start, raw_time=start.strftime("%H:%M"),
            description=about[:300], league_raw=sub[:120], sport_raw=title[:40],
            match_raw=_pair(sub) if _pair(sub).strip() else _pair(about),
            source_url=url, extra={"day": start.date().isoformat()},
        ))
    return mark_first_show(out, "priamy prenos")

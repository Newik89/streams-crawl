# -*- coding: utf-8 -*-
"""tv.nova.cz — Чехия, уровень A (готовый JSON в странице).

Самый дешёвый источник из всех: по адресу `tv.nova.cz/program` (дата в
адресе не нужна) приходит переменная `var PageData = {...}`, а в ней вся
программа **14 каналов на 28 дней за один запрос**:

    PageData.program[день].channels[канал].segments[утро|день|вечер].items[]
    PageData.channels[]  → человеческие названия каналов

Время в `start_at` уже со смещением (`2026-08-29T17:10:00+02:00`), поэтому
ни часовой пояс источника, ни правило перехода через полночь здесь не нужны.

Маркер эфира отдельным полем не приходит — он словом внутри `description`:
`Přímý přenos` — эфир, `Záznam`, `Sestřih`, `Reportáž`, `Dokument` — нет.
Названия команд стоят прямо в заголовке: `Sporting Gijón - CE Sabadell FC`.
"""

from __future__ import annotations

import json
from datetime import date as _date

from .. import daytime
from . import Program, register

DOMAIN = "tv.nova.cz"
TZ = "Europe/Prague"

_ANCHOR = "var PageData = "


def page_data(html: str) -> dict:
    """Достаёт `PageData` из страницы. `raw_decode` дочитывает ровно один
    объект и останавливается там, где кончился JSON, — резать по `;` нельзя,
    точка с запятой встречается внутри текста передач."""
    i = html.find(_ANCHOR)
    if i < 0:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(html[i + len(_ANCHOR):])
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def list_channels(html: str) -> dict[str, str]:
    """`nova-sport-1` → `Nova Sport 1`."""
    return {c.get("id", ""): c.get("title", "")
            for c in page_data(html).get("channels") or [] if c.get("id")}


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    """`channels` — какие каналы брать: годится и код (`nova-sport-1`), и
    название (`Nova Sport 1`) — в базе каналы записаны названиями, а в данных
    сайта стоят коды. По умолчанию берём все. `day` — оставить только эти
    сутки; по умолчанию все 28 дней."""
    data = page_data(html)
    names = {c.get("id", ""): c.get("title", "") for c in data.get("channels") or []}

    out = []
    for entry in data.get("program") or []:
        for channel in entry.get("channels") or []:
            cid = channel.get("id", "")
            if channels and cid not in channels and names.get(cid) not in channels:
                continue
            for segment in channel.get("segments") or []:
                for item in segment.get("items") or []:
                    start = daytime.from_iso(item.get("start_at"))
                    if day and (start is None or start.date() != day):
                        continue
                    title = (item.get("title") or "").strip()
                    note = (item.get("description") or "").strip()
                    out.append(Program(
                        channel_raw=names.get(cid, cid), title=title, start=start,
                        raw_time=start.strftime("%H:%M") if start else "",
                        description=note, live_raw=note, match_raw=title,
                        source_url=url,
                        extra={"channel_id": cid, "id": item.get("id"),
                               "end_at": item.get("end_at")},
                    ))
    return out

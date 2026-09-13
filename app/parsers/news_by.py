# -*- coding: utf-8 -*-
"""news.by — Беларусь 5: недельные сетки в props Astro-острова.

Обычным запросом страница пуста — данные дорисовывает скрипт, берём
браузером (`needs_js=1`). Расписание лежит в атрибуте `props` элемента
`<astro-island>`: сериализация Astro — каждая нода `[0, значение]` (объект)
или `[1, [массив]]`, разворачивается рекурсивно.

Путь: `data.schedules[]` — недельные блоки `{start_date, finish_date,
schedule: {"Понедельник": {programs: [{time, program}]}, ...}}`. Дата дня =
`start_date` недели + номер дня. Заголовок держит всё сразу:
«Футбол. Чемпионат Беларуси. 19-й тур. Торпедо-БелАЗ (Жодино) - Днепр
(Могилев). Прямая трансляция» — вид спорта, лига, пара и честный маркер.
"""

from __future__ import annotations

import html as _html
import json
import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "news.by"
TZ = "Europe/Minsk"
CHANNEL = "Беларусь 5"

_DAYS = {"Понедельник": 0, "Вторник": 1, "Среда": 2, "Четверг": 3,
         "Пятница": 4, "Суббота": 5, "Воскресенье": 6}
_PROPS = re.compile(r'props="([^"]+)"')
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
#: пара в скобочной записи: `Неман (Гродно) - Динамо (Молодечно)`
_PAIR = re.compile(r"([А-ЯЁA-Z][\w'’-]*(?:[ -][\w'’()-]+){0,4})\s+-\s+"
                   r"([А-ЯЁA-Z][\w'’-]*(?:[ -][\w'’()-]+){0,4})")


def _unwrap(v):
    if isinstance(v, list) and len(v) == 2 and v[0] == 0:
        return _unwrap(v[1])
    if isinstance(v, list) and len(v) == 2 and v[0] == 1:
        return [_unwrap(x) for x in v[1]]
    if isinstance(v, dict):
        return {k: _unwrap(x) for k, x in v.items()}
    return v


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    blob = None
    for m in _PROPS.finditer(html):
        if "schedules" in m.group(1) and (blob is None or
                                          len(m.group(1)) > len(blob)):
            blob = m.group(1)
    if not blob:
        return []
    try:
        data = _unwrap(json.loads(_html.unescape(blob)))
    except ValueError:
        return []
    weeks = (data.get("data") or {}).get("schedules") or []

    out: list[Program] = []
    for week in weeks:
        try:
            monday = datetime.fromisoformat(week["start_date"]).date()
        except (KeyError, ValueError):
            continue
        for day_name, block in (week.get("schedule") or {}).items():
            shift = _DAYS.get(day_name)
            if shift is None:
                continue
            d = monday + timedelta(days=shift)
            prev = None
            offset = 0
            for row in (block or {}).get("programs") or []:
                hm = _TIME.match((row.get("time") or "").strip())
                title = " ".join((row.get("program") or "").split())
                if not hm or not title:
                    continue
                start_t = (int(hm.group(1)), int(hm.group(2)))
                if prev is not None and start_t < prev:
                    offset += 1
                prev = start_t
                live = "Прямая трансляция" if re.search(
                    r"(?i)прямая трансляция", title) else ""
                # части через точку: `Хоккей. Кубок Беларуси. Групповой
                # этап. Неман (Гродно) - Динамо (Молодечно). Прямая…`
                parts = [p.strip() for p in title.split(".") if p.strip()]
                sport = parts[0] if parts else ""
                pair = " "
                for p in parts:
                    found = _PAIR.search(p)
                    if found:
                        pair = f"{found.group(1).strip()} - {found.group(2).strip()}"
                        break
                league = next((p for p in parts[1:]
                               if "трансляция" not in p.lower()
                               and not _PAIR.search(p)), "")
                dd = d + timedelta(days=offset)
                out.append(Program(
                    channel_raw=CHANNEL, title=title,
                    start=datetime(dd.year, dd.month, dd.day, start_t[0],
                                   start_t[1], tzinfo=zone),
                    raw_time=f"{start_t[0]:02d}:{start_t[1]:02d}",
                    league_raw=league[:120],
                    sport_raw=sport,
                    live_raw=live,
                    match_raw=pair,
                    source_url=url, extra={"day": dd.isoformat()},
                ))
    return out

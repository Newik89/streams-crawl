# -*- coding: utf-8 -*-
"""raiplay.it — Италия, уровень A (открытый JSON).

Сайт в браузере виснет, но JSON отдаётся обычным запросом (разведка 28.08):
`/palinsesto/app/{канал}/{дд-мм-гггг}.json` — расписание одного канала на
день. Канал зашит в адрес, поэтому у источника строки в `source_channels`
со своим `page_url` на каждый нужный канал (начали с `rai-sport`).

Формат ответа:

    {"channel": "Rai 1", "date": "29-08-2026",
     "events": [{"name": "Calcio: Serie A - Lecce - Roma", "hour": "20:40",
                 "duration": "110 min", "description": "…",
                 "channel": "Rai 1"}, …]}

`hour` — настенное итальянское время; переход через полночь виден по
следующему дню в адресе, поэтому каждую страницу разбираем в её дату.

**Маркера эфира в этом JSON нет.** Слова `diretta` Rai не пишет, а
`event_weblink` со `/dirette/` стоит у ВСЕХ передач — и у повторов, и у
студии (проверено на живой странице 31.08). Поэтому эфир определяем так же, как
у `ert.gr` и `oneplaysport.cz`: маркер получает **самый ранний показ пары**
(`mark_first_show`), домен внесён в `REPEAT_GUESS_DOMAINS`. С этим источник
вернулся в обход 01.09; если владельцу повторы не понравятся, зацепка для
честного признака — `/palinsesto/onAir.json`.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, mark_first_show, register

DOMAIN = "raiplay.it"
TZ = "Europe/Rome"

_DATE_IN_URL = re.compile(r"/(\d{2})-(\d{2})-(\d{4})\.json")
_HOUR = re.compile(r"^(\d{1,2}):(\d{2})$")


def _pair(text: str) -> str:
    """Пара команд из куска заголовка (`Italia - Bulgaria`).

    Сторона, начинающаяся с цифры, парой не считается: у Rai через тире
    пишут и куски вроде `11a giornata - prima parte`.
    """
    for sep in (" - ", " – ", " vs "):
        home, s, away = text.partition(sep)
        home, away = home.strip(), away.strip()
        if not s or not home or not away:
            continue
        if home[0].isdigit() or away[0].isdigit():
            continue
        return f"{home} - {away}"
    return " "


def _split(name: str) -> tuple[str, str]:
    """Заголовок Rai → (турнир, пара).

    Пишут двумя способами: `Calcio: Serie A - Lecce - Roma` (вид спорта,
    турнир, пара) и `Europei femminili di Pallavolo 2026 - Ottavi:
    Italia - Bulgaria` (пара после двоеточия). Поэтому сначала пробуем
    хвост после ПОСЛЕДНЕГО двоеточия, а если пары там нет — две последние
    части, разделённые тире.
    """
    head, sep, tail = name.rpartition(":")
    if sep and _pair(tail).strip():
        return head.strip(), _pair(tail)
    parts = [p.strip() for p in name.split(" - ") if p.strip()]
    if len(parts) >= 3:
        return " - ".join(parts[:-2]), f"{parts[-2]} - {parts[-1]}"
    if len(parts) == 2 and sep:
        return head.strip(), f"{parts[0]} - {parts[1]}"
    return "", " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = json.loads(html)
    except ValueError:
        return []
    zone = ZoneInfo(tz or TZ)

    m = _DATE_IN_URL.search(url or "")
    if m:
        day = _date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    elif data.get("date"):
        try:
            dd, mm, yyyy = data["date"].split("-")
            day = _date(int(yyyy), int(mm), int(dd))
        except ValueError:
            pass
    if day is None:
        day = _date.today()

    out: list[Program] = []
    for event in data.get("events", []):
        name = (event.get("name") or "").strip()
        hour = (event.get("hour") or "").strip()
        hm = _HOUR.match(hour)
        if not name or not hm:
            continue
        channel = (event.get("channel") or data.get("channel") or "").strip()
        if channels and channel not in channels:
            continue
        start = datetime(day.year, day.month, day.day,
                         int(hm.group(1)), int(hm.group(2)), tzinfo=zone)
        out.append(Program(
            channel_raw=channel, title=name, start=start, raw_time=hour,
            description=(event.get("description") or "")[:300],
            league_raw=_split(name)[0], sport_raw=_split(name)[0],
            match_raw=_split(name)[1], source_url=url,
            extra={"day": day.isoformat(),
                   "duration": event.get("duration") or ""},
        ))
    # Слова «diretta» Rai не пишет, а ссылка `/dirette/` стоит у всех
    # передач подряд. Поэтому идём общим для проекта путём: эфир — самый
    # ранний показ пары, остальное считаем повтором (домен внесён в
    # `REPEAT_GUESS_DOMAINS`).
    return mark_first_show(out, "diretta")

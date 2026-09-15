# -*- coding: utf-8 -*-
r"""port.hu — Венгрия, телегид на 149 каналов; свой запрос на канал и день.

Этим сайтом закрылась венгерская дыра: `mediaklikk.hu` даёт только M4 Sport,
а матчи венгерского чемпионата идут на `Spíler1 TV` и `Spíler2 TV`, которых
у нас не было вовсе.

Адрес ручки подсмотрен в открытом проекте `iptv-org/epg` — там лежит 251
готовый разбор телесайтов, и `port.hu` среди них. Сам сайт свои страницы
(`/tvmusor`, `/csatornak`, поиск) отдаёт как 404, а ручка отвечает всем:

    https://port.hu/tvapi?channel_id[]=tvchannel-305
        &i_datetime_from=2026-09-01&i_datetime_to=2026-09-01

Ответ разложен по дням, ключ — секунды начала суток:

    {"1788213600": {"channels": [{"id": "tvchannel-305", "programs": [
        {"start_ts": 1788213600, "title": "Favágók",
         "episode_title": "…", "short_description": "…"}]}]}}

Список каналов с номерами отдаёт `https://port.hu/tvapi/init-new`.
Спортивные: 305 Spíler1, 362 Spíler2, 375 Match4, 290 M4 Sport, 320 M4
Sport+, 90 Sport1, 44 Sport2, 94 Eurosport 1, 37 Eurosport 2.

Признака прямого эфира у сайта нет — эфир определяем первым показом пары.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, mark_first_show, register

DOMAIN = "port.hu"
TZ = "Europe/Budapest"

_CHANNEL = re.compile(r"tvchannel-(\d+)")

#: номер канала → как он называется у зрителя
NAMES = {"305": "Spíler1 TV", "362": "Spíler2 TV", "375": "Match4",
         "290": "M4 Sport", "320": "M4 Sport+", "90": "Sport1",
         "44": "Sport2", "94": "Eurosport 1", "37": "Eurosport 2",
         "98": "Extreme Sports", "367": "Auto Motor Sport TV"}


#: венгерские слова студийных передач: `Premier League: Összefoglaló` —
#: это обзор тура, а не матч, и парой команд его считать нельзя
_NOT_MATCH = re.compile(r"összefoglaló|magazin|stúdió|híradó|hírek", re.I)

#: хвост венгерского анонса у гостей: «ZTE FC mérkőzés» («матч»), как у
#: `mediaklikk.hu`. С хвостом «ZTE FC mérkőzés» не сводилось с эталоном,
#: и M4 Sport терял матчи тура (владелец 15.09)
_TAIL = re.compile(r"\s+(mérkőzés\w*|közvetítés\w*|élőben|ismétlés\w*)\s*$", re.I)


def _pair(text: str) -> str:
    if _NOT_MATCH.search(text):
        return " "
    for sep in (" - ", " – ", " — ", " vs ", " × "):
        if sep in text:
            home, _, away = text.partition(sep)
            home = home.split(":")[-1]
            away = _TAIL.sub("", away.strip()).strip()
            if home.strip() and away:
                return f"{home.strip()} - {away}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    try:
        data = json.loads(html)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []

    out: list[Program] = []
    for block in data.values():                 # ключ — начало суток
        if not isinstance(block, dict):
            continue
        for channel_block in block.get("channels") or []:
            got = _CHANNEL.search(channel_block.get("id") or "")
            number = got.group(1) if got else ""
            channel = NAMES.get(number, f"port.hu {number}" if number else "port.hu")
            if channels and channel not in channels:
                continue
            for show in channel_block.get("programs") or []:
                title = " ".join((show.get("title") or "").split())
                stamp = show.get("start_ts")
                if not title or not isinstance(stamp, (int, float)):
                    continue
                episode = " ".join((show.get("episode_title") or "").split())
                about = " ".join((show.get("short_description")
                                  or show.get("description") or "").split())
                full = f"{title}: {episode}" if episode else title
                start = datetime.fromtimestamp(stamp, tz=zone)
                out.append(Program(
                    channel_raw=channel, title=full, start=start,
                    raw_time=show.get("start_time") or start.strftime("%H:%M"),
                    # лига — заголовок передачи («OTP Bank Liga»), а не
                    # эпизод: там пара команд, и она копилась в словаре
                    # лигой («Ferencvárosi TC - Újpest FC mérkőzés», 15.09)
                    description=about[:300],
                    league_raw=(title if episode else "")[:120],
                    match_raw=_pair(full) if _pair(full).strip() else _pair(about),
                    source_url=url,
                    extra={"day": start.date().isoformat()},
                ))
    return mark_first_show(out, "élő")

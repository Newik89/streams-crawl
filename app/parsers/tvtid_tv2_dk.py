# -*- coding: utf-8 -*-
"""tvtid.tv2.dk — Дания, официальный телегид TV 2: каналы одним запросом на день.

Сайт — каркас, сетку рисует скрипт; данные отдаёт открытая ручка (пробы
#187–#192, 05.10.2026):

    https://tvtid-api.api.tv2.dk/api/tvtid/v1/epg/dayviews/2026-10-05?ch=77&ch=2147483561…

Номера каналов — из `…/v1/schedules/channels` (98 штук, см. `CHANNELS`).
Ответ: `[{"id": "77", "programs": [{"start": 1791225300, "stop": …,
"title": "UEFA Nations League: Italien-Tyrkiet", "live": true,
"rerun": false, …}]}]`. Время — unix-секунды; `live` — честный флаг прямого
эфира, `rerun` — повтор. Глубина — не меньше 10 дней скользящим окном.

**Пара есть только у каналов самого TV 2**: «Турнир: Хозяева-Гости[, стадия,
город]», дефис БЕЗ пробелов («Randers FC-Viborg FF»), а где в имени свой
дефис — с пробелами («Bosnien-Hercegovina - Polen»). У чужих каналов гида
(TV3 Sport, See, Eurosport) в заголовке один турнир («Premier League»,
«Cykling: Paris-Tours») — их пары даёт `tvsporten.dk`, сюда они не заведены.

Матч TV 2 режет на две передачи (тайм — передача) с одним заголовком, а до
и после ставит студию («…: Før Randers FC-Viborg FF», «…: Efter …»,
«…: Studiet»): вторую половину и студию не берём.

Теннис без игроков («ATP: Finale, Tokyo», «WTA: Beijing», «ATP: Shanghai»)
отдаём «парой» из тура и хвоста — такую строку `app/broadcast.py` сводит с
другими сайтами в трансляцию турнира («ATP Tokyo»).
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime, timedelta, timezone

from . import Program, register

DOMAIN = "tvtid.tv2.dk"
TZ = "Europe/Copenhagen"

#: номер канала в ручке → имя; линейка TV 2 — только у неё пары в заголовке
CHANNELS = {"77": "TV 2 Sport", "2147483561": "TV 2 Sport X",
            "3": "TV 2 Danmark", "4": "TV 2 Echo", "31": "TV 2 Charlie",
            "12566": "TV 2 Fri", "133": "TV 2 News"}

#: студия до и после матча — не игра («Før», «Efter» перед парой)
_STUDIO = re.compile(r"^(?:før|efter|optakt(?: til)?)\s+", re.I)
#: виды, где дефис в названии — гонка, а не пара («Cykling: Paris-Roubaix»)
_SOLO = re.compile(r"cykl|tour de|giro|vuelta|golf|formel|motor|rally|atletik"
                   r"|maraton|svøm|ski|langrend|alpin|ridning|ridebane|sejl"
                   r"|triatlon|skydning", re.I)
_TOUR = re.compile(r"^(?:atp|wta)\b", re.I)
#: датские лиги, в названии которых вида спорта нет: без подсказки гандбол
#: «Herreligaen: Skanderborg AGF-Fredericia» уходил в очередь «вид спорта»
_LEAGUE_SPORT = {"herreligaen": "Håndbold", "kvindeligaen": "Håndbold",
                 "håndboldligaen": "Håndbold", "metal ligaen": "Ishockey",
                 "basketligaen": "Basket"}
#: женская лига без слова «женская»: A-Liga — высший дивизион Дании
_WOMEN_LEAGUE = {"a-liga"}
#: вторую половину матча с тем же заголовком считаем той же игрой
_SAME_GAME = timedelta(hours=4)


def _split(title: str) -> tuple[str, str]:
    """(турнир, пара) из «Турнир: Хозяева-Гости, стадия, город»."""
    if ":" not in title:
        return "", " "
    league, _, tail = title.partition(":")
    league, tail = league.strip(), tail.strip()
    if _SOLO.search(league):
        return league, " "
    head = tail.split(",", 1)[0].strip()
    if _STUDIO.match(head):
        return league, " "
    for sep in (" - ", " – "):
        if sep in head:
            home, _, away = head.partition(sep)
            break
    else:
        # дефис без пробелов делит пару, только когда он один: два дефиса
        # («Liège-Bastogne-Liège») — либо гонка, либо имя с дефисом
        if head.count("-") != 1:
            home = away = ""
        else:
            home, _, away = head.partition("-")
    home, away = home.strip(), away.strip()
    if len(home) >= 2 and len(away) >= 2 \
            and home[0].isalnum() and away[0].isalnum():
        return league, f"{home} - {away}"
    if _TOUR.match(league) and tail:
        # теннис без игроков: «ATP: Finale, Tokyo» → трансляция турнира
        return league, f"{league} - {tail.replace(',', ' ')}"
    return league, " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = json.loads(html)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []

    out: list[Program] = []
    for block in data:
        if not isinstance(block, dict):
            continue
        channel = CHANNELS.get(str(block.get("id") or ""))
        if not channel or (channels and channel not in channels):
            continue
        shown: dict[str, datetime] = {}      # заголовок → начало первой части
        for show in block.get("programs") or []:
            title = " ".join((show.get("title") or "").split())
            try:
                start = datetime.fromtimestamp(int(show.get("start")),
                                               timezone.utc)
            except (TypeError, ValueError, OSError):
                continue
            if not title:
                continue
            live_now = bool(show.get("live")) and not show.get("rerun")
            league, pair = _split(title)
            first = shown.get(title)
            if live_now and first is not None and start - first <= _SAME_GAME:
                continue                     # второй тайм той же игры
            if live_now:
                shown.setdefault(title, start)
            out.append(Program(
                channel_raw=channel, title=title,
                start=start, raw_time=start.strftime("%H:%M"),
                league_raw=league[:120],
                sport_raw=_LEAGUE_SPORT.get(league.lower(), ""),
                live_raw="direkte" if live_now else "",
                description=" ".join(x for x in (
                    "genudsendelse" if show.get("rerun") else "",
                    "kvinder" if league.lower() in _WOMEN_LEAGUE else "") if x),
                match_raw=pair, source_url=url,
                extra={"day": start.date().isoformat(),
                       "program_id": show.get("id") or ""},
            ))
    return out

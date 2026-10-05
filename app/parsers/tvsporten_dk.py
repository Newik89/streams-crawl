# -*- coding: utf-8 -*-
"""tvsporten.dk — Дания, справочник «спорт по ТВ»: событие → каналы.

Страница — Next.js, в HTML только сегодняшний день; остальные дни её скрипт
берёт ручкой самого сайта (нашлась в чанке `199-….js`, проба #192, 05.10.2026):

    https://www.tvsporten.dk/api/fixtures/bydate?day=2026-10-06&dayBreakHour=5&tz=Europe%2FCopenhagen

Ключа не просит. Параметр именно `day` (`date`, `from` молча отдают сегодня).
Ответ: `[{"date": "2026-10-06", "oldFixtures": [...], "newFixtures": [...]}]`,
у события `fixture_id`, `title`, `home_team` / `visiting_team` (пусто у гонок
и турниров), `league`, `sport`, `date` (UTC) и `channels` — список
`{name, shortname, is_streaming}`.

Сайт показывает только прямые трансляции — отдельного признака эфира нет,
эфиром считается каждое событие. Каналы с `is_streaming` (Viaplay, TV 2 Play,
Disney+, youSee…) — стриминги и пакеты операторов, в сетку не берём.

«Сутки» у сайта тянутся до 05:00 следующего дня (`dayBreakHour`), поэтому
ночные игры приходят в ответе предыдущего дня — дату берём из самого события.

Теннис без игроков («China Open», лига «WTA») отдаём «парой» из тура и
названия — `app/broadcast.py` сводит такие строки в трансляцию турнира.
"""

from __future__ import annotations

import json
from datetime import date as _date, datetime

from . import Program, register

DOMAIN = "tvsporten.dk"
TZ = "Europe/Copenhagen"

#: вид спорта, как его зовёт сайт → слово, которое знает `data/markers.json`
_SPORT = {"Motor": "Motorsport", "Fighting": "Kampsport"}


def _fixtures(node):
    """Все события ответа, где бы они ни лежали (`oldFixtures`/`newFixtures`)."""
    if isinstance(node, dict):
        if "fixture_id" in node:
            yield node
        else:
            for value in node.values():
                yield from _fixtures(value)
    elif isinstance(node, list):
        for value in node:
            yield from _fixtures(value)


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = json.loads(html)
    except ValueError:
        return []

    out: list[Program] = []
    seen: set[tuple] = set()
    for fx in _fixtures(data):
        title = " ".join((fx.get("title") or "").split())
        stamp = fx.get("date") or ""
        if not title or not stamp:
            continue
        try:
            start = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        home = " ".join((fx.get("home_team") or "").split())
        away = " ".join((fx.get("visiting_team") or "").split())
        league = " ".join((fx.get("league") or "").split())
        kind = (fx.get("sport") or "").strip()
        if home and away:
            pair = f"{home} - {away}"
        elif kind == "Tennis" and league:
            pair = f"{league} - {title}"     # трансляция турнира без игроков
        else:
            pair = " "
        stage = " ".join((fx.get("additional_info") or "").split())
        for ch in fx.get("channels") or []:
            if not isinstance(ch, dict) or ch.get("is_streaming"):
                continue
            channel = (ch.get("name") or ch.get("shortname") or "").strip()
            if not channel or (channels and channel not in channels):
                continue
            key = (fx.get("fixture_id"), channel)
            if key in seen:
                continue
            seen.add(key)
            out.append(Program(
                channel_raw=channel, title=title,
                start=start, raw_time=start.strftime("%H:%M"),
                league_raw=league[:120],
                sport_raw=_SPORT.get(kind, kind),
                live_raw="direkte",
                description=stage[:120],
                match_raw=pair, source_url=url,
                extra={"day": start.date().isoformat(),
                       "fixture_id": fx.get("fixture_id")},
            ))
    return out

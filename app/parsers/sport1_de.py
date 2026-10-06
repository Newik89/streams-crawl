# -*- coding: utf-8 -*-
"""tv.sport1.de — Германия, канал SPORT1. Открытый JSON без параметров.

Страница `tv.sport1.de/programm` — каркас, но её приложение ходит в открытую
ручку. В разведке 01.09 шаблон с меткой времени давал `400`; оказалось, что
метка не нужна вовсе:

    https://api.sport1.info/v3/de/tv/epg

Ответ — каналы и их передачи на текущие сутки и часть следующих:

    {"channels": [{"id": 106, "name": "SPORT1", "broadcasts": [
        {"startTime": "2026-08-31T16:00:00.000+00:00",
         "programTitle": "Fußball - Frauen-Bundesliga",
         "episodeTitle": "FC Bayern München - 1. FSV Mainz 05, 2. Spieltag"}]}]}

`programTitle` — вид спорта и турнир, `episodeTitle` — пара команд с
хвостом тура (`, 2. Spieltag`), его снимаем перед разбором пары.

Пометка эфира у передачи есть — поле `emissionType` (аудит 06.10, обход
#205): `live`, `Wiederholung` (повтор), `Erstausstrahlung` (первый показ
записи), `Exklusiv`. Раньше здесь было «пометки нет», и эфир угадывался
первым показом пары. Теперь поле читаем (`EMISSION`, `site_says`); угадывание
осталось только для строк, где сайт промолчал.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime

from . import Program, mark_first_show, register, site_says

DOMAIN = "tv.sport1.de"
TZ = "Europe/Berlin"

#: поле `emissionType` передачи → пометка сайта (True — эфир, False —
#: повтор или запись). Чего нет в таблице (`Exklusiv`, пусто) — сайт
#: промолчал, строку угадывает `mark_first_show`
EMISSION = {"live": True, "wiederholung": False, "erstausstrahlung": False}

#: хвост тура: `, 2. Spieltag`, `, 1. Runde`, `, Finale`
_ROUND_TAIL = re.compile(
    r",\s*(?:\d+\.\s*(?:Spieltag|Runde|Etappe)|Finale|Halbfinale|"
    r"Viertelfinale|Achtelfinale)\b.*$", re.I)
_PAIR = re.compile(r"\s+-\s+|\s+–\s+|\s+vs\.?\s+", re.I)


def _pair(text: str) -> str:
    parts = _PAIR.split(_ROUND_TAIL.sub("", text or ""), maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return f"{parts[0].strip()} - {parts[1].strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = json.loads(html)
    except json.JSONDecodeError:
        return []

    out: list[Program] = []
    for channel in data.get("channels") or []:
        name = (channel.get("name") or "").strip()
        if not name or (channels and name not in channels):
            continue
        for item in channel.get("broadcasts") or []:
            stamp = item.get("startTime") or ""
            program = (item.get("programTitle") or "").strip()
            episode = (item.get("episodeTitle") or "").strip()
            title = " - ".join(x for x in (program, episode) if x)
            if not stamp or not title:
                continue
            try:
                start = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            row = Program(
                channel_raw=name, title=title, start=start,
                raw_time=f"{start:%H:%M}", description=episode,
                league_raw=program, sport_raw=program,
                match_raw=_pair(episode), source_url=url,
                extra={"day": start.date().isoformat()},
            )
            kind = (item.get("emissionType") or "").strip().casefold()
            # `live` и `wiederholung` — слова словаря (live / not_live)
            site_says(row, EMISSION.get(kind),
                      kind if kind in ("live", "wiederholung") else "")
            out.append(row)
    # `Exklusiv` и пустой вид сайт эфиром не называет и не отрицает —
    # такие строки угадываются первым показом пары (`live_guess`)
    return mark_first_show(out, "live")


def list_channels(html: str) -> list[str]:
    try:
        data = json.loads(html)
    except json.JSONDecodeError:
        return []
    return [(c.get("name") or "").strip()
            for c in data.get("channels") or [] if c.get("name")]

# -*- coding: utf-8 -*-
"""tv2.no — Норвегия, 69 каналов за один запрос.

Страница `/tvguide/` — SvelteKit, в HTML сетки нет. Адрес данных лежал в
странице открытым текстом (`PUBLIC_EPG_API_URL`), а форма вызова — в узле
маршрута `/tvguide/_app/immutable/nodes/2.*.js`:

    https://tv2no-epg-api.public.tv2.no/epg/days/2026/09/01

Ключа не просит. Ответ — список каналов, у каждого `programs` за сутки:

    [{"date": "2026-09-01",
      "channel": {"id": "TV2S1", "displayName": "TV 2 Sport 1"},
      "programs": [{"title": "Eliteserien: Start - KFUM Oslo",
                    "synopsis": "…", "genre": "sport",
                    "startTime": "2026-09-01T12:05:00",
                    "live": false, "replay": false}]}]

Заголовок устроен как `Турнир: Хозяева - Гости` — двоеточие режет лигу от
пары. Жанр называет вид спорта своим словом (`Fotball`, `Tennis`,
`Håndball`), общий `sport` не говорит ничего.

**Флаги `live` и `replay` у сайта честные** (аудит 06.10, обход #205: 20
матчей `live`, 108 `replay` за 6 дней, `live` стоит и на будущих днях —
«Eliteserien: Fredrikstad - Tromsø» 11.10). Раньше здесь было написано, что
`live` — «идёт сейчас» и всегда `false`; на 01.09 так и было, и эфир
угадывался первым показом пары. Теперь флаг читаем (`site_says`): `live` —
эфир (он главнее `replay`: у «Saint-Raphaël - Elverum» стоят оба), `replay`
— повтор, ни того ни другого — не эфир. Флаги стоят только у каналов самого
TV 2; у гостей гида (NRK, Viasport, Eurosport…) они пустые — там эфир
по-прежнему угадывается первым показом пары.

Время в `startTime` без смещения — это местное время Осло.
"""

from __future__ import annotations

import json
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, mark_first_show, register, site_says

DOMAIN = "tv2.no"
TZ = "Europe/Oslo"

#: жанры, которые сайт ставит вместо названия вида спорта
_EMPTY_GENRE = {"sport", "annet", "sportsmagasin", "dokumentar", "tv-lek"}


def _pair(title: str) -> str:
    """Пара команд стоит после двоеточия: `Eliteserien: Start - KFUM Oslo`."""
    tail = title.split(":", 1)[1] if ":" in title else title
    for sep in (" - ", " – ", " vs. ", " vs "):
        if sep in tail:
            home, _, away = tail.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


def _league(title: str) -> str:
    """Всё до двоеточия — турнир: `Elkjøp-ligaen, kvinner`."""
    return title.split(":", 1)[0].strip() if ":" in title else ""


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    try:
        days = json.loads(html)
    except ValueError:
        return []
    if not isinstance(days, list):
        return []

    # Флаги сайт ставит только СВОИМ каналам (TV 2 Sport 1/2/Premium, TV 2
    # Direkte, Nyheter, Zebra, Livsstil): у NRK, Viasport, Eurosport и прочих
    # гостей гида `live`/`replay` — false у всех строк (обход #205). Поэтому
    # флаг живой у КАНАЛА, где хоть одна передача им помечена; гостей угадываем
    flagged = {((b.get("channel") or {}).get("displayName") or "").strip()
               for b in days if isinstance(b, dict)
               if any(isinstance(show, dict)
                      and (show.get("live") or show.get("replay"))
                      for show in (b.get("programs") or []))}
    out: list[Program] = []
    for block in days:
        if not isinstance(block, dict):
            continue
        channel = ((block.get("channel") or {}).get("displayName") or "").strip()
        if not channel or (channels and channel not in channels):
            continue
        for show in block.get("programs") or []:
            title = " ".join((show.get("title") or "").split())
            stamp = show.get("startTime") or ""
            if not title or not stamp:
                continue
            try:
                start = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=zone)
            genre = (show.get("genre") or "").strip()
            program = Program(
                channel_raw=channel, title=title,
                start=start, raw_time=start.strftime("%H:%M"),
                description=" ".join((show.get("synopsis") or "").split())[:300],
                league_raw=_league(title)[:120],
                sport_raw="" if genre.lower() in _EMPTY_GENRE else genre,
                match_raw=_pair(title), source_url=url,
                extra={"day": start.date().isoformat()},
            )
            if channel in flagged:
                site_says(program, True if show.get("live")
                          else False if show.get("replay") else None,
                          "direkte" if show.get("live") else "")
            out.append(program)
    # у канала с живыми флагами строка без пометки — не эфир, угадывать её
    # нельзя; угадываем только каналы-гости без флагов
    mark_first_show([p for p in out if p.channel_raw not in flagged], "direkte")
    return out

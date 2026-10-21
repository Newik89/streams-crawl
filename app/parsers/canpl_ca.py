# -*- coding: utf-8 -*-
"""canpl.ca — Канадская премьер-лига (CPL): календарь сезона с каналами матча.

Слово владельца 22.10.2026: «HFX Wanderers — Supra du Québec» 25.10 шёл на
TVA Sports 2 и OneSoccer, а у нас не было ни того, ни другого (разведка
#311–#312). OneSoccer показывает CPL в своём приложении и в программе канала
одной общей передачей («Canadian Premier League Soccer | The Outcomes - All
Matches» у tvpassport) — каналы КАЖДОЙ игры знает только сама лига.

`/schedule/` рисуется скриптом (браузер). Разметка (проба #312, 21.10):

    <span>Sunday, Oct 25</span>                       — заголовок дня, без года
    <div data-matchid=… data-match-status="UPCOMING"  — матч (FINISHED — сыгран)
         data-match-teams="Pacific vs Forge, venue: Royal Athletic Park">
      <span data-translation-key="matchtimeformat">My Time</span><span>8:00 PM</span>
      <span>Canadian Premier League</span>
      <a … data-translation-key="onesoccer">onesoccer</a>   — каналы матча
      <a … data-translation-key="tvas2">tvas2</a>

Правила по порядку:
1. Берём только несыгранные матчи: `FINISHED` — в прошлом, пропускаем.
2. Дата — последний заголовок дня перед матчем; год — тот, при котором дата
   ближе всего к дню страницы (плей-офф может перейти через Новый год).
3. Время «8:00 PM» («My Time») — по часам БРАУЗЕРА обхода, пояса на странице
   нет. На GitHub браузер живёт в UTC, поэтому у карточки источника пояс UTC;
   если качать с сервера — карточке ставить пояс сервера.
4. Каждый код канала — отдельная строка (как у сетки): `onesoccer` →
   OneSoccer, `tvas2` → TVA Sports 2, `tva` → TVA Sports, `tsn` → TSN,
   `cbc` → CBC. Незнакомый код — канал с этим именем заглавными: каналы сами
   не выбрасываем (правило проекта).
5. Лига перечисляет тех, кто ПОКАЗЫВАЕТ матч, — каждая строка эфир
   (`site_says(True)`).
"""

from __future__ import annotations

import html as _html
import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, register, site_says

DOMAIN = "canpl.ca"
TZ = "UTC"
LEAGUE = "Canadian Premier League"

#: код канала на странице → имя канала (правило 4)
CHANNELS = {"onesoccer": "OneSoccer", "tvas2": "TVA Sports 2",
            "tva": "TVA Sports", "tsn": "TSN", "cbc": "CBC"}

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
     "nov", "dec"), start=1)}
#: заголовок дня: «Sunday, Oct 25», «Friday, July 24»
_DAY = re.compile(r"<span[^>]*>\s*(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,\s+"
                  r"([A-Z][a-z]+)\s+(\d{1,2})\s*</span>")
#: открывающий тег матча — со всеми атрибутами, порядок любой
_MATCH = re.compile(r"<div\b[^>]*\bdata-matchid=\"[^\"]+\"[^>]*>")
_ATTR = re.compile(r"\b(data-match-status|data-match-teams)=\"([^\"]*)\"")
_TIME = re.compile(r"data-translation-key=\"matchtimeformat\"[^>]*>[^<]*</span>"
                   r"\s*<span[^>]*>\s*([0-9]{1,2}:[0-9]{2}\s*[AaPp][Mm])\s*</span>")
#: ссылка канала: текст ссылки = её код перевода
_CHANNEL = re.compile(r"<a\b[^>]*\bdata-translation-key=\"([a-z0-9]+)\"[^>]*>\s*\1\s*</a>")


def _year(month: int, dom: int, today: _date) -> _date | None:
    """Дата без года — в год, где она ближе всего к дню страницы (правило 2)."""
    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            when = _date(year, month, dom)
        except ValueError:
            continue
        if best is None or abs((when - today).days) < abs((best - today).days):
            best = when
    return best


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    today = day or datetime.now(zone).date()
    days = [(m.start(), m.group(1), int(m.group(2))) for m in _DAY.finditer(html)]
    starts = [m.start() for m in _MATCH.finditer(html)]
    out: list[Program] = []
    for i, pos in enumerate(starts):
        tag = _MATCH.match(html, pos).group(0)
        attrs = dict(_ATTR.findall(tag))
        if attrs.get("data-match-status", "").upper() == "FINISHED":
            continue                                        # правило 1
        teams = _html.unescape(attrs.get("data-match-teams", ""))
        teams = teams.split(", venue:")[0]
        home, sep, away = teams.partition(" vs ")
        if not sep or not home.strip() or not away.strip():
            continue
        head = [d for d in days if d[0] < pos]
        if not head:
            continue
        _, month_name, dom = head[-1]
        month = _MONTHS.get(month_name[:3].lower())
        when_day = _year(month, dom, today) if month else None
        block = html[pos: starts[i + 1] if i + 1 < len(starts) else len(html)]
        t = _TIME.search(block)
        if not when_day or not t:
            continue
        clock = datetime.strptime(" ".join(t.group(1).upper().split()), "%I:%M %p")
        begin = datetime(when_day.year, when_day.month, when_day.day,
                         clock.hour, clock.minute, tzinfo=zone)   # правило 3
        pair = f"{home.strip()} - {away.strip()}"
        codes = list(dict.fromkeys(_CHANNEL.findall(block)))
        for code in codes:                                   # правило 4
            program = Program(
                channel_raw=CHANNELS.get(code, code.upper()),
                title=f"{LEAGUE}: {pair}",
                start=begin,
                raw_time=t.group(1).strip(),
                league_raw=LEAGUE,
                sport_raw="Soccer",
                match_raw=pair,
                source_url=url, extra={"day": begin.date().isoformat()},
            )
            out.append(site_says(program, True))             # правило 5
    return out

# -*- coding: utf-8 -*-
"""yallakora.com — Египет: «матчи дня» с каналом показа (книга 167).

Задание владельца 17.11.2026: «найти официальное расписание ON Sport».
Разведка 18–19.11: официальный сайт ON Time Sports закрыт (Cloudflare),
египетские телегиды спортивных каналов не дают, sat.tv пишет «Football
Match» без команд. Здесь же у матча стоит канал — слово владельца 19.11:
«да, делаем», вторым источником рядом со страницами каналов livesoccertv.

**Что отдаёт сайт.** `https://www.yallakora.com/match-center?date=М/Д/ГГГГ`
— обычный HTML (проба GitHub #508), матчи одного дня по турнирам. Время —
каирское (`Africa/Cairo`). Канал у матча появляется к дню игры: на
«сегодня» каналы есть, на «завтра» почти нет — глубже завтрашнего дня
ходить незачем. Язык — арабский; у турнира есть английское имя
(`enName`), у команд — нет: имена приводит к написанию эталона общая
сверка, а где эталона нет — они идут как на сайте.

Разметка:

    button.dayTabLinks.active[date="11/19/2026"]        — день страницы
    div.matchCard                                        — турнир
      a.tourTitle img[alt="كأس مصر"][enName="Egypt-Cup"]  — имя турнира
      h2                                                 `كأس مصر`
      div.item[liveScoreMatchId]                         — матч
        div.channel.icon-channel   `ON Sport MAX`        (нет блока — канала нет)
        div.topData div.date       `دور الـ 16`          — стадия
        div.teams.teamA p          `المصري`
        div.teams.teamB p          `بترول أسيوط`
        div.MResult span.time      `17:00`

Правила разбора по порядку:

1. День — из активной вкладки дня (`М/Д/ГГГГ`), иначе из `date=` в
   адресе, иначе `day` от обхода, иначе «сегодня» по часам Каира.
2. Матч без канала — не строка: сайт для нас справочник «кто показывает».
3. Канал пишется как на сайте, регистр и пробелы выравниваются по списку
   `CHANNELS` («ON Sport MAX» → «ON Sport Max»). Канал не из списка
   разбор не выбрасывает (каналы сами не отсеиваем) — какие брать, решает
   список каналов сайта в плане обхода (`channels`).
4. Вид спорта — по приставке турнира: сайт пишет её перед тире у всего,
   что не футбол («كرة يد - السوبر المصري»). Приставки — `_SPORTS`; нет
   приставки — футбол.
5. Лига — английское имя турнира (`enName`, дефисы — пробелами), если оно
   написано латиницей; иначе арабское имя без приставки вида спорта.
6. Все строки — прямой эфир по слову сайта (`site_says`): это расписание
   матчей, записей и студий в нём нет.
7. Одинаковые строки (канал, время, пара) берём один раз.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from .. import daytime
from . import Program, register, site_says

DOMAIN = "yallakora.com"
TZ = "Africa/Cairo"

#: правило 3: как сайт пишет канал (без регистра и пробелов) → имя канала
CHANNELS = {
    "onsport": "ON Sport",
    "onsportmax": "ON Sport Max",
    "onsportplus": "ON Sport Plus",
}

#: правило 4: приставка турнира (без «ال») → вид спорта по-английски
_SPORTS = {
    "كرة يد": "Handball",
    "كرة سلة": "Basketball",
    "كرة طائرة": "Volleyball",
    "كرة طاولة": "Table tennis",
    "تنس": "Tennis",
}
FOOTBALL = "Soccer"

_DAY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_DASH = re.compile(r"\s+[-–—]\s+")


def _text(node) -> str:
    return " ".join(node.text().split()) if node is not None else ""


def _key(text: str) -> str:
    return "".join(c for c in (text or "").casefold() if c.isalnum())


def channel_name(raw: str) -> str:
    """Правило 3: имя канала по списку, иначе как на сайте."""
    return CHANNELS.get(_key(raw), " ".join((raw or "").split()))


def _mdy(text: str) -> _date | None:
    m = _DAY.match((text or "").strip())
    if not m:
        return None
    try:
        return _date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def page_day(tree: HTMLParser, url: str, day: _date | None, tz: str) -> _date:
    """Правило 1: день страницы."""
    tab = tree.css_first("button.dayTabLinks.active")
    found = _mdy(tab.attributes.get("date") or "") if tab is not None else None
    if found is None:
        asked = parse_qs(urlsplit(url or "").query).get("date") or [""]
        found = _mdy(asked[0])
    return found or day or daytime.today(tz)


def sport_and_league(arabic: str, english: str) -> tuple[str, str]:
    """Правила 4 и 5: (вид спорта, лига) по имени турнира."""
    arabic = " ".join((arabic or "").split())
    parts = _DASH.split(arabic, maxsplit=1)
    head, tail = (parts[0], parts[1]) if len(parts) == 2 else (arabic, "")
    # приставка без артикля: «كرة اليد» и «كرة يد» — одно и то же
    plain = " ".join(w[2:] if w.startswith("ال") and len(w) > 3 else w for w in head.split())
    sport = _SPORTS.get(plain, "") if tail else ""
    league = " ".join((english or "").replace("-", " ").split())
    if not league or not league.isascii():
        league = tail if sport else arabic
    return sport or FOOTBALL, league


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone_name = tz or TZ
    zone = ZoneInfo(zone_name)
    tree = HTMLParser(html)
    day = page_day(tree, url, day, zone_name)
    out: list[Program] = []
    seen: set[tuple] = set()
    for card in tree.css("div.matchCard"):
        logo = card.css_first("a.tourTitle img")
        arabic = _text(card.css_first("h2")) or ((logo.attributes.get("alt") or "") if logo is not None else "")
        english = (logo.attributes.get("enname") or "") if logo is not None else ""
        sport, league = sport_and_league(arabic, english)
        for item in card.css("div.item"):
            raw_channel = _text(item.css_first("div.channel"))
            if not raw_channel:
                continue                                      # правило 2
            channel = channel_name(raw_channel)
            if channels and channel not in channels:
                continue                                      # правило 3
            home = _text(item.css_first("div.teamA p"))
            away = _text(item.css_first("div.teamB p"))
            hm = _HHMM.match(_text(item.css_first("span.time")))
            if not home or not away or not hm:
                continue
            key = (channel, hm.group(0), home, away)
            if key in seen:
                continue                                      # правило 7
            seen.add(key)
            stage = _text(item.css_first("div.topData div.date"))
            program = Program(
                channel_raw=channel, title=f"{home} - {away}",
                start=datetime(day.year, day.month, day.day,
                               int(hm.group(1)), int(hm.group(2)), tzinfo=zone),
                raw_time=hm.group(0), description=stage,
                league_raw=league, sport_raw=sport,
                match_raw=f"{home} - {away}", source_url=url,
                extra={"day": day.isoformat()},
            )
            out.append(site_says(program, True))              # правило 6
    return out

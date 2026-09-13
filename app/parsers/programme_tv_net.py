# -*- coding: utf-8 -*-
"""programme-tv.net — Франция, крупный телегид. Адрес на канал и день.

    https://www.programme-tv.net/programme/chaine/{YYYY-MM-DD}/programme-{слаг}-{id}.html

Общая страница `/programme/toutes-les-chaines/{дата}/` не годится: она
показывает всего по две передачи прайм-тайма на канал. Полный день лежит
только на странице канала.

    div.mainBroadcastCard-infos
      p.mainBroadcastCard-startingHour   `20h42`  (французская запись времени)
      h3.mainBroadcastCard-title a       заголовок, в `title` — без хвостов
      p.mainBroadcastCard-subtitle       подзаголовок
      p.mainBroadcastCard-format         `Sport`, `Série TV`, `Cinéma`

Турнир сайт отдельным полем не пишет, но он виден в адресе передачи:
`/programme/sport/r306814-football-coupe-dallemagne/31432845-hebc-hambourg-borussia-dortmund/`
— оттуда берём и вид спорта (`sport`), и название турнира.

Пару команд французы пишут через косую черту (`HEBC Hambourg / Borussia
Dortmund`), поэтому здесь она разделитель наравне с дефисом.

Маркера прямого эфира на страницах нет — эфиром считаем первый показ пары
(`mark_first_show`), домен внесён в `REPEAT_GUESS_DOMAINS`.
"""

from __future__ import annotations

import html as _html
import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "programme-tv.net"
TZ = "Europe/Paris"

_URL_DAY = re.compile(r"/(\d{4})-(\d{2})-(\d{2})/")
_TIME = re.compile(r"^(\d{1,2})h(\d{2})$")
#: `/programme/sport/r306814-football-coupe-dallemagne/…`
_TOPIC = re.compile(r"/programme/([a-z-]+)/r\d+-([a-z0-9-]+)/")
_HEAD = re.compile(r"^\s*Programme\s+TV\s+", re.I)
_HEAD_TAIL = re.compile(r"\s+(?:de\s+demain|d[’']aujourd[’']hui|du\s+.+)$", re.I)


def _pair(text: str) -> str:
    for sep in (" / ", " - ", " – ", " vs "):
        home, s, away = text.partition(sep)
        if s and home.strip() and away.strip():
            return f"{home.strip()} - {away.strip()}"
    return " "


#: первое слово в слаге турнира — обычно вид спорта
_SPORT_WORDS = ("football", "basket", "basketball", "tennis", "rugby",
                "cyclisme", "handball", "volley", "athletisme", "golf",
                "formule", "moto", "boxe", "natation", "ski")


def _topic(href: str) -> tuple[str, str]:
    """(вид спорта, турнир) из адреса передачи.

    `/programme/sport/r306814-football-coupe-dallemagne/…` — раздел `sport`,
    слаг турнира начинается с вида спорта. Слаг пишем словами и с заглавных:
    `football-coupe-dallemagne` → вид `football`, турнир `Coupe Dallemagne`.
    Апострофы в слаге потеряны (`d'Allemagne` → `dallemagne`) — это имя для
    сопоставления, а не для витрины.
    """
    found = _TOPIC.search(href or "")
    if not found:
        return "", ""
    section = found.group(1)
    words = found.group(2).split("-")
    sport = ""
    if words and words[0] in _SPORT_WORDS:
        sport, words = words[0], words[1:]
    tournament = " ".join(w.capitalize() if len(w) > 3 else w for w in words)
    return " ".join(x for x in (section, sport) if x), tournament


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)

    head = tree.css_first("h1")
    channel = _html.unescape(head.text(strip=True) if head else "")
    channel = _HEAD_TAIL.sub("", _HEAD.sub("", channel)).strip()
    if not channel:
        return []
    if channels and channel.casefold() not in {c.casefold() for c in channels}:
        return []

    found = _URL_DAY.search(url or "")
    first = _date(int(found.group(1)), int(found.group(2)),
                  int(found.group(3))) if found else day

    out: list[Program] = []
    previous = None
    shift = 0
    for card in tree.css("div.mainBroadcastCard-infos"):
        clock = card.css_first("p.mainBroadcastCard-startingHour")
        title_link = card.css_first("h3.mainBroadcastCard-title a")
        if clock is None or title_link is None:
            continue
        stamp = _TIME.match(clock.text(strip=True))
        title = _html.unescape(title_link.attributes.get("title")
                               or title_link.text(strip=True))
        if not stamp or not title:
            continue
        minutes = int(stamp.group(1)) * 60 + int(stamp.group(2))
        if previous is not None and minutes < previous:
            shift += 1              # сетка перевалила за полночь
        previous = minutes
        sport_hint, tournament = _topic(title_link.attributes.get("href") or "")
        subtitle = card.css_first("p.mainBroadcastCard-subtitle")
        fmt = card.css_first("p.mainBroadcastCard-format")
        start = None
        if first is not None:
            start = datetime(first.year, first.month, first.day,
                             int(stamp.group(1)), int(stamp.group(2)),
                             tzinfo=zone) + timedelta(days=shift)
        subtitle_text = _html.unescape(
            subtitle.text(strip=True)) if subtitle else ""
        pair = _pair(title)
        if not pair.strip() and subtitle_text:
            pair = _pair(subtitle_text)
        out.append(Program(
            channel_raw=channel, title=title, start=start,
            raw_time=clock.text(strip=True), description=subtitle_text,
            league_raw=tournament,
            sport_raw=" ".join(x for x in (
                fmt.text(strip=True) if fmt else "", sport_hint) if x),
            match_raw=pair, source_url=url,
            extra={"day": start.date().isoformat() if start else ""},
        ))
    return mark_first_show(out, "en direct")


def list_channels(html: str) -> list[str]:
    """Каналы с общей страницы `/programme/toutes-les-chaines/`."""
    names: list[str] = []
    for link in HTMLParser(html).css("a.gridRow-cardsChannelItemLink"):
        text = _html.unescape(link.text(strip=True))
        name = re.sub(r"^N°\d+", "", text).strip()
        if name and name not in names:
            names.append(name)
    return names

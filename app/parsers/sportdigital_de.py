# -*- coding: utf-8 -*-
"""start.sportdigital.de — Германия, линейка Sportdigital (6 каналов).

Автоподбор 23.09 сайт не взял (балл < 45): разметка своя, ни на один из
готовых разборов не похожа — написан свой (28.09, слово владельца
«подбери для него парсер»).

Страница `/tvprogramm/<код>` — канальная сетка: один канал, 21 день вперёд.
Разметка образцовая:

    section.epgTag[data-epg-datum="2026-09-27"]        день
      div.epgSendung.epgArt_live|epgArt_wdh|epgArt_tipp
        .epgKarte (div или <a>)
          time[datetime="2026-09-27T00:00:00+02:00"]   начало, ISO со смещением
          h3.epgTitel     «Kuwait - Irak» ИЛИ «LFC TV - EFL Cup (3. Runde)»
          p.epgInfo       «Gulf Cup (…)» ИЛИ «Liverpool FC - Tottenham Hotspur»
          p.epgZusatz     «Fussball (Wh. v. 26.09.2026)» — спорт + пометка повтора

Пара и турнир меняются местами между Titel и Info: пара — тот из двух, где
нет турнирных слов и скобок. Эфир — ТОЛЬКО класс `epgArt_live` (слово LIVE
в заголовках стоит и у повторов, `epgArt_tipp` — редакционный значок TIPP).
Дата берётся из `time[datetime]` самой карточки, не из аргумента.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "start.sportdigital.de"
TZ = "Europe/Berlin"

#: имя канала по коду в адресе `/tvprogramm/<код>`; голый `/tvprogramm` —
#: страница первого канала (кнопка active)
CHANNELS = {"sdf": "Sportdigital FUSSBALL", "sdf2": "Sportdigital FUSSBALL2",
            "sd1p": "Sportdigital1+", "edge": "Sportdigital EDGE",
            "esportsone": "eSportsONE", "scooorefast": "scooore"}

#: маркер эфира — слово из `markers.json` → `live.проверено`
_LIVE = "liveübertragung"
#: служебный префикс заголовка: «Fortsetzung:Atletico Mineiro - …» —
#: продолжение трансляции после перерыва, к имени не относится
_PREFIX = re.compile(r"(?i)^(fortsetzung|wiederholung|whg?\.?)\s*:\s*")
#: признаки «это турнир/передача, а не пара команд»
_TOURNEY = re.compile(
    r"(?i)[()]|\b(cup|liga|league|runde|spieltag|gruppe|highlights|magazin"
    r"|show|matchday|pokal|qualifikation|klub|club|tv|alle tore|countdown"
    r"|wochenshow|classics|inside|storys?)\b")


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs. ", " vs "):
        home, s, away = text.partition(sep)
        if s and home.strip() and away.strip():
            return f"{home.strip()} - {away.strip()}"
    return " "


def _match_and_league(title: str, info: str) -> tuple[str, str]:
    """Пара — тот из двух кусков, где она есть и нет турнирных слов."""
    if _pair(title).strip() and not _TOURNEY.search(title):
        return _pair(title), info
    if _pair(info).strip() and not _TOURNEY.search(info):
        return _pair(info), title
    return " ", info or title


def _channel(url: str, tree: HTMLParser) -> str:
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    if slug in CHANNELS:
        return CHANNELS[slug]
    h1 = tree.css_first("h1")
    name = re.sub(r"^\s*TV-Programm\s+", "", h1.text(strip=True)) if h1 else ""
    return name or CHANNELS["sdf"]


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    tree = HTMLParser(html)
    channel = _channel(url, tree)
    if channels and channel not in channels:
        return []
    out: list[Program] = []

    for wrap in tree.css("div.epgSendung"):
        card = wrap.css_first(".epgKarte")
        if card is None:
            continue
        stamp = card.css_first("time")
        try:
            start = datetime.fromisoformat(
                (stamp.attributes.get("datetime") or "") if stamp else "")
        except ValueError:
            continue
        title_node = card.css_first("h3.epgTitel")
        info_node = card.css_first("p.epgInfo")
        extra_node = card.css_first("p.epgZusatz")
        title = _PREFIX.sub("", title_node.text(strip=True)) if title_node else ""
        info = info_node.text(strip=True) if info_node else ""
        zusatz = extra_node.text(strip=True) if extra_node else ""
        if not title:
            continue
        pair, league = _match_and_league(title, info)
        # «Fussball (Wh. v. 26.09.2026)» → вид спорта — первое слово
        sport = (zusatz.split("(")[0].split() or [""])[0]
        classes = wrap.attributes.get("class") or ""
        out.append(Program(
            channel_raw=channel, title=title, start=start,
            raw_time=f"{start:%H:%M}", description=zusatz,
            league_raw=league, sport_raw=sport, match_raw=pair,
            live_raw=_LIVE if "epgArt_live" in classes else "",
            source_url=url,
            extra={"day": start.date().isoformat()},
        ))
    return out

# -*- coding: utf-8 -*-
"""tv.orf.at — Австрия, телегид ORF. Адрес на канал, день — сегодняшний.

В закладке владельца стоял адрес с хешем и датой февраля
(`index~_day-22-02-2026_-1179c4a9…html`), из-за чего сайт числился сложным.
На деле работает короткий адрес `https://tv.orf.at/program/{канал}/index.html`
— он отдаёт текущий день (и хвост следующего). Ссылки на другие дни лежат в
самой странице, но у каждой свой хеш, вычислить его нельзя, поэтому берём
только сегодня: источник заведён «канальной сеткой» (адрес на канал, дата не
подставляется).

Каналы: `orf1`, `orf2`, `orf3`, `orfs` (ORF SPORT+), `kids`.

    li.broadcast[data-channel][data-start-time]   `2026-08-31T06:00:00.000+02:00`
      div.start-time        `06:00`
      div.series-title      `Silent Sports +`
      div.episode-title     `Springreiten Global Champions Tour Wien`
      div.meta-data         `Übertragung` — так ORF помечает трансляцию

Своего слова «прямой эфир» у ORF нет: `Übertragung` стоит и у повтора.
Поэтому маркер получают только передачи с этой пометкой, и лишь самый ранний
показ пары (`mark_first_show`), домен — в `REPEAT_GUESS_DOMAINS`.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "tv.orf.at"
TZ = "Europe/Vienna"

#: имя канала по коду в разметке — на странице оно есть только в подписи логотипа
CHANNELS = {"orf1": "ORF 1", "orf2": "ORF 2", "orf3": "ORF III",
            "orfs": "ORF SPORT+", "kids": "ORF KIDS"}

_LIVE = "übertragung"
#: приставка прямого эфира в заголовке ORF
_LIVE_WORD = re.compile(r"\bLIVE\b")
#: этап турнира перед парой: «2. Qualifikationsrunde: SK Sturm Graz - …»
_STAGE = re.compile(r"^[^:–-]{3,60}:\s*")
#: место съёмки хвостом: «… - VfL Wolfsburg aus Graz» (26.09, #Sturm)
_PLACE = re.compile(r"\s+aus\s+\S.{0,30}$")


def _pair(text: str) -> str:
    # этап перед двоеточием — не имя команды, место съёмки «aus …» — тоже
    text = _STAGE.sub("", _PLACE.sub("", text))
    for sep in (" - ", " – ", " vs ", " gegen "):
        home, s, away = text.partition(sep)
        if s and home.strip() and away.strip():
            return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    tree = HTMLParser(html)
    covered: list[Program] = []
    rest: list[Program] = []

    for item in tree.css("li.broadcast"):
        code = (item.attributes.get("data-channel") or "").strip()
        channel = CHANNELS.get(code, code.upper())
        if not channel or (channels and channel not in channels):
            continue
        stamp = item.attributes.get("data-start-time") or ""
        try:
            start = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        series = item.css_first("div.series-title")
        episode = item.css_first("div.episode-title")
        meta = item.css_first("div.meta-data")
        series_text = series.text(strip=True) if series else ""
        episode_text = episode.text(strip=True) if episode else ""
        title = " ".join(x for x in (series_text, episode_text) if x)
        if not title:
            continue
        meta_text = meta.text(strip=True) if meta else ""
        pair = _pair(episode_text) if episode_text else " "
        if not pair.strip():
            pair = _pair(title)
        program = Program(
            channel_raw=channel, title=title, start=start,
            raw_time=f"{start:%H:%M}", description=meta_text,
            league_raw=series_text if series_text != episode_text else "",
            sport_raw="", match_raw=pair, source_url=url,
            extra={"day": start.date().isoformat()},
        )
        if _LIVE_WORD.search(title):
            # ORF пишет прямые трансляции с приставкой `LIVE` в заголовке
            # (`LIVE Handball HLA & WHA Media Day`) — это честный признак,
            # угадывать по первому показу тут не нужно
            program.live_raw = "live"
            rest.append(program)
        elif meta_text.casefold().startswith(_LIVE):
            program.live_raw = _LIVE
            covered.append(program)
        else:
            rest.append(program)

    return mark_first_show(covered, _LIVE) + rest


def list_channels(html: str) -> list[str]:
    """Каналы из полосы логотипов: `title` вида `ORF SPORT+ Programm`."""
    names: list[str] = []
    for node in HTMLParser(html).css("a.channel-logo"):
        name = re.sub(r"\s*Programm\s*$", "",
                      (node.attributes.get("title") or "").strip())
        if name and name not in names:
            names.append(name)
    return names

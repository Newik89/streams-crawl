# -*- coding: utf-8 -*-
"""novasports.gr — Греция: вся линейка Novasports одной страницей.

`/tv-program/` отдаёт текущий день по 25 каналам обычным запросом:
Novasports 1–6, Prime, Premier League, Start, News, Extra 1–4 — плюс
греческие Eurosport 1–2 и все Cosmote Sport 1–9 (готовый резерв на случай,
если наш путь к `cosmotetv.gr` через читалку отвалится).

Разметка: блок канала — `div.channel-title` (имя текстом) и следом
`div.channel-program` с карточками `div.tv-broadcast`:

    div.time        `19:00`
    текстовые узлы  `Ατρόμητος - ΠΑΟΚ` и `Super League 2026/27`
                    (у передач без матча — название и подпись)

Пара — узел, где есть « - » с двумя сторонами; лига — соседний узел.
Маркера эфира нет: эфиром считаем первый показ пары (`mark_first_show`),
домен в `REPEAT_GUESS_DOMAINS`. Ночные карточки (00:00, 02:00 в конце
списка) — следующая дата, ловится по убыванию времени.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, time as _time, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "novasports.gr"
TZ = "Europe/Athens"

_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_SEASON = re.compile(r"(20\d{2})/(\d{2})")


def _pair(text: str) -> str:
    if " - " in text:
        home, _, away = text.partition(" - ")
        if home.strip() and away.strip():
            return f"{home.strip()} - {away.strip()}"
    return ""


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    day = day or _date.today()
    tree = HTMLParser(html)

    out: list[Program] = []
    honest: list[int] = []       # карточки с настоящей пометкой (Ζ)/LIVE
    channel = ""
    offset = 0
    prev: _time | None = None
    # Каналы и их карточки связаны только порядком в документе, а селектор
    # через запятую отдаёт совпадения ГРУППАМИ (грабля из `ГРАБЛИ.md`) —
    # поэтому идём по ВСЕМ div подряд и держим текущее имя канала.
    for node in tree.css("div"):
        classes = node.attributes.get("class") or ""
        if "channel-title" in classes:
            channel = " ".join(node.text().split())
            offset, prev = 0, None
            continue
        if "tv-broadcast" not in classes.split():
            continue
        if not channel or (channels and channel not in channels):
            continue
        time_node = node.css_first("div.time")
        hm = _TIME.match(" ".join(time_node.text().split())) if time_node else None
        if not hm:
            continue
        # настоящая пометка эфира (владелец 22.09): «(Ζ)» в названии и
        # плашка LIVE появляются, когда матч УЖЕ идёт — будущие карточки
        # сайт не помечает, их страхует эталон. Застали пометку — эфир
        # честный, угадыванию и правилу повторов его не трогать
        live_now = bool(node.css_first("strong.live-now"))
        texts = []
        for cls_name in ("subtitle", "title"):
            for sub in node.css(f"div.{cls_name}"):
                own = " ".join(sub.text().split())
                if "(Ζ)" in own:
                    live_now = True
                    own = " ".join(own.replace("(Ζ)", " ").split())
                if own and own not in texts:
                    texts.append(own)
        pair = ""
        league = ""
        for t in texts:
            if not pair and _pair(t):
                pair = _pair(t)
            elif not league:
                league = t
        title = pair or (texts[0] if texts else "")
        if not title:
            continue
        start_t = _time(int(hm.group(1)), int(hm.group(2)))
        if prev is not None and start_t < prev:
            offset += 1
        prev = start_t
        d = day + timedelta(days=offset)
        # архивные повторы канал крутит днём с плашкой старого сезона
        # («Premier League 2025/26» в сентябре 2026) — это не эфир
        season = _SEASON.search(league)
        year_now = d.year if d.month >= 7 else d.year - 1
        stale = bool(season) and int(season.group(1)) != year_now
        out.append(Program(
            channel_raw=channel, title=title,
            start=datetime(d.year, d.month, d.day, start_t.hour,
                           start_t.minute, tzinfo=zone),
            raw_time=hm.group(0),
            league_raw=league[:120],
            live_raw="" if stale else None,
            match_raw=" " if stale else (pair or " "),
            source_url=url, extra={"day": d.isoformat()},
        ))
        if live_now and not stale:
            honest.append(len(out) - 1)
    out = mark_first_show(out, "ζωντανά")
    # пометка сайта сильнее угадывания: карточка с (Ζ)/LIVE остаётся
    # эфиром, даже если mark_first_show счёл её повтором
    for i in honest:
        out[i].live_raw = "ζωντανά"
        out[i].extra.pop("repeat_guess", None)
    return out

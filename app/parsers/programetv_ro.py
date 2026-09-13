# -*- coding: utf-8 -*-
"""programetv.ro — Румыния, уровень A (инлайн-JSON), агрегатор всех RO-каналов.

Страница канала `/program-tv/{слаг}/` держит СЕГОДНЯ и ЗАВТРА двумя
массивами — `"shows":[…]` и `"nextDayShows":[…]` — окно обхода целиком,
один запрос на канал (тип `CHANNEL_GRID_DOMAINS` в `app/crawl.py`).
Каталог каналов — `/program-tv/`: 371 слаг, спортивные выбраны в
`source_channels` (Digi Sport 1–4, Prima Sport 1–4, Pro Arena).

Запись: `{title, start, stop, categories: ["Sport"], live, replay}`.
Время ISO с поясом (+03:00). Что важно (проба 31.08):

* **поля `live`/`replay` мёртвые** — false у всех 74 передач Digi Sport 1;
  честный маркер — приставка `LIVE ` в `title`;
* пара команд через дефис БЕЗ пробелов: `FC Bacau-CSM Slatina` — режем по
  первому дефису и отдаём `A - B`; хвост `Etapa N` (тур) срезаем;
* прерванный матч идёт двумя записями с LIVE (тайм 1 в 17:30, тайм 2 в
  18:30) — эфиром считается первый показ пары, поздние глушим здесь же;
  межфайловые повторы добивает `parse_live.py` (`REPEAT_GUESS_DOMAINS`);
* вид спорта сайт не называет (`categories` всегда `Sport`) — `sport_raw`
  пустой, вид определяется по лиге/названию дальше по конвейеру.

Имя канала строим из слага адреса: `digi-sport-1` → `Digi Sport 1` — оно же
`raw_name` в `source_channels`.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime

from . import Program, register

DOMAIN = "programetv.ro"
TZ = "Europe/Bucharest"

_ARRAYS = ("shows", "nextDayShows")
_SLUG = re.compile(r"/program-tv/([\w-]+)")
_LIVE = re.compile(r"^\s*LIVE[\s:]+", re.I)
_ETAPA = re.compile(r"\s+(?:Etapa|Turul)\s+\d+\s*$", re.I)


def _channel_from(url: str) -> str:
    m = _SLUG.search(url or "")
    if not m:
        return ""
    words = [w.upper() if w.isdigit() or len(w) <= 2 else w.capitalize()
             for w in m.group(1).split("-")]
    return " ".join(words)


def _array(html: str, name: str) -> list:
    m = re.search(rf'"{name}"\s*:\s*\[', html)
    if not m:
        return []
    start = m.end() - 1
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(html)):
        c = html[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i + 1])
                except ValueError:
                    return []
    return []


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    channel = _channel_from(url)
    if channels and channel and channel not in channels:
        return []

    out: list[Program] = []
    seen: set[tuple] = set()
    for name in _ARRAYS:
        for item in _array(html, name):
            title = (item.get("title") or "").strip()
            raw = (item.get("start") or "").strip()
            if not title or not raw:
                continue
            key = (raw, title)
            if key in seen:          # тот же блок мог попасть в оба массива
                continue
            seen.add(key)
            try:
                start = datetime.fromisoformat(raw)
            except ValueError:
                continue
            live = bool(_LIVE.match(title))
            clean = _ETAPA.sub("", _LIVE.sub("", title)).strip()
            league, _, tail = clean.partition(":")
            tail = tail.strip()
            if not tail:
                # без лиги-приставки (Prima Sport): `Rapid București – CS U
                # Craiova` — заголовок и есть пара
                league, tail = "", clean
            pair, spaced = " ", False
            for sep in (" – ", " — ", " - ", "-"):
                if sep in tail:
                    home, _, away = tail.partition(sep)
                    if home.strip() and away.strip():
                        pair = f"{home.strip()} - {away.strip()}"
                        spaced = sep != "-"
                    break
            if pair == " ":
                league = ""
            out.append(Program(
                channel_raw=channel, title=clean, start=start,
                raw_time=raw[11:16],
                league_raw=league.strip() if pair != " " else "",
                sport_raw="",
                live_raw="live" if live else "",
                match_raw=pair, source_url=url,
                extra={"day": raw[:10], "spaced": spaced},
            ))

    # Prima Sport и Pro Arena размечают эфир никак: ни LIVE, ни лиги —
    # просто `Rapid București – CS U Craiova`. Если на странице канала
    # приставки LIVE нет ВООБЩЕ, эфиром считаем передачи-пары (только с
    # пробельным тире — дефис без пробелов в имени передачи не в счёт);
    # повторы срежет правило первого показа ниже.
    if out and not any(p.live_raw for p in out):
        for p in out:
            if p.extra.get("spaced"):
                p.live_raw = "live"
                p.extra["live_guess"] = True
                # лиги в таких заголовках не бывает, вид спорта взять неоткуда;
                # каналы эти — футбольные (авто/мото и прочее режет список
                # «чужих» по названию передачи), даём осторожный дефолт
                if not p.sport_raw:
                    p.sport_raw = "fotbal"
                    p.extra["sport_guess"] = True

    # Эфир — первый показ пары; поздние сегменты/повторы того же матча
    # (в т.ч. с переставленной парой) идут записью.
    def _pk(p: Program):
        if " - " not in p.match_raw:
            return None
        return tuple(sorted(" ".join(s.lower().split())
                            for s in p.match_raw.split(" - ", 1)))

    first: dict[tuple, datetime] = {}
    for p in out:
        k = _pk(p)
        if k is not None and (k not in first or p.start < first[k]):
            first[k] = p.start
    for p in out:
        k = _pk(p)
        if p.live_raw and k is not None and p.start > first[k]:
            p.live_raw = ""
            p.extra["repeat_guess"] = True
    return out

# -*- coding: utf-8 -*-
"""tv-program.aktuality.sk — Словакия, телегид Aktuality; сетка спортканалов.

Разведка 31.08 отложила сайт: адрес шёл на канал (`/stanica/{слаг}/`), а
списка спортивных слагов не было. Зацепка из `ОТЛОЖЕНО.md` сработала —
фильтр «Športové» живёт по своему адресу `/sportove-stanice/` и отдаёт
**все 11 спортивных станций одной страницей**: ČT sport, EuroSport,
EuroSport 2, Eurosport HD, Nova Sport, Nova Sport 2, Sport1, Sport2,
Premier Sport, JOJ Šport, RTVS Šport. Поэтому источник заведён сеткой —
один запрос за обход.

Только сегодняшний день: адреса вида `/sportove-stanice/zajtra/` сайт молча
подменяет главной страницей (проверено 01.09 — вернулись «Markíza, JOJ,
Jednotka», то есть обычный список станций).

Разбирать разметку не нужно: рядом с каждой передачей лежит готовый кусок
JavaScript со всеми полями сразу —

    program_desc[11908650] = { title:'Volejbal: Itálie - Bulharsko',
        desc:'ME ve volejbalu žen 2026Přímý přenos osmifinálového utkání',
        category:'šport', channel_title:'ČT sport', start_time:'1788184200' };

`start_time` — метка времени UTC, дату из неё и берём (телегид-день здесь
не при чём). Маркер эфира — чешское `Přímý přenos` в описании, он уже есть
в `data/markers.json`.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timezone
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "tv-program.aktuality.sk"
TZ = "Europe/Bratislava"

_BLOCK = re.compile(r"program_desc\[\d+\]\s*=\s*\{(.*?)\};", re.S)


def _field(block: str, name: str) -> str:
    m = re.search(name + r"\s*:\s*'((?:[^'\\]|\\.)*)'", block, re.S)
    if not m:
        return ""
    return m.group(1).replace("\\'", "'").replace("\\\\", "\\").strip()


def _pair(text: str) -> str:
    """Пара команд из куска заголовка (`Itálie - Bulharsko`)."""
    for sep in (" - ", " – ", " vs ", " x "):
        home, s, away = text.partition(sep)
        if s and home.strip() and away.strip():
            return f"{home.strip()} - {away.strip()}"
    return " "


def _split(title: str) -> tuple[str, str]:
    """Заголовок → (вид спорта, пара). Словаки пишут `Vид: Хозяева - Гости`,
    иногда с турниром в середине: `Futbal: Niké liga: Slovan - Trnava`."""
    head, sep, rest = title.partition(":")
    if not sep:
        return "", _pair(title)
    pair = _pair(rest)
    if not pair.strip():
        # турнир отделён вторым двоеточием
        _, _, tail = rest.partition(":")
        pair = _pair(tail)
    return head.strip(), pair


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    out: list[Program] = []
    for block in _BLOCK.findall(html):
        channel = _field(block, "channel_title")
        title = _field(block, "title")
        stamp = _field(block, "start_time")
        if not channel or not title or not stamp.isdigit():
            continue
        if channels and channel not in channels:
            continue
        start = datetime.fromtimestamp(int(stamp), timezone.utc).astimezone(zone)
        desc = _field(block, "desc")
        sport, pair = _split(title)
        out.append(Program(
            channel_raw=channel, title=title, start=start,
            raw_time=f"{start:%H:%M}", description=desc,
            # лигу отдельным полем сайт не даёт: в описании она растворена в
            # предложении («4. kola … ligy Ligue 2 BKT»), а вид спорта и метку
            # W/U19 отсев и так берёт из описания
            league_raw="", sport_raw=sport or _field(block, "category"),
            live_raw="", match_raw=pair, source_url=url,
            extra={"day": start.date().isoformat()},
        ))
    return out


def list_channels(html: str) -> list[str]:
    """Станции со страницы фильтра — по заголовку блока."""
    seen: list[str] = []
    for name in re.findall(r'class="station-title">([^<]+)<', html):
        name = name.strip()
        if name and name not in seen:
            seen.append(name)
    return seen

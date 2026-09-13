# -*- coding: utf-8 -*-
r"""livesoccertv.com — СПРАВОЧНИК: кто показывает конкретный матч в любой стране.

Правило то же, что у `liveonsat.com` (решение владельца 01.09.2026): в
ежедневный обход сайт **не входит**, обращаемся точечно — когда у матча не
хватает канала.

Почему не сводка. Общая страница `/schedules/` матчи показывает, а каналы
прячет: с американского адреса (а раннер GitHub именно такой) в колонке
стоит `Available on-demand`. Зато **страница отдельного матча отдаёт полную
таблицу «страна → каналы» независимо от того, откуда пришёл запрос**:

    /match/getafe-vs-osasuna/1b65f
    …
    <tr><td><span class="flag ukraine">Ukraine</span></td>
        <td><a href="/channels/megogo-ukraine/">Megogo</a>
            <a href="/channels/megogo-football-1/">MEGOGO Football 1</a></td></tr>

Как пользоваться:

1. взять ссылку матча со сводки (`/schedules/`, `<a href="/match/…">`);
2. `github_run.py dispatch --urls "https://www.livesoccertv.com/match/…"`;
3. разобрать ответ этим парсером — на каждый канал получится своя строка.

Время матча лежит в атрибуте `dv` — миллисекунды UTC, часовой пояс страницы
роли не играет. Пара команд — в заголовке `h1` (`Osasuna vs Getafe stream and
TV schedule`).

Строки помечаются как прямой эфир: справочник показывает именно трансляции.

**Страницы каналов** (`/channels/<slug>/`) — с 03.09 ИСТОЧНИК для SuperSport
Албания (этап 6в; liveonsat закрыт капчей, других телегидов с албанским
разделом нет). Страница отдаёт сетку канала на дни вперёд:

    <tr class="matchrow" data-ko="2026-09-02 15:00:00">
      <span class='livecell live' title='Live Broadcast'>
      <span class='ts' dv='1788375600000'>          ← миллисекунды UTC
      <a href="/match/...">Burnley vs Middlesbrough</a>
      <a href="/competitions/england/championship/">Championship</a>

Имя канала — из <title> («SuperSport 2 Digitalb TV Schedule…»). Открывается
с серверных адресов (пробы #193/#195 02.09), в отличие от сводки.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timezone
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "livesoccertv.com"
TZ = "Europe/Kyiv"

_MS = re.compile(r"dv=['\"](\d{10,13})['\"]")
_TITLE = re.compile(r"^(.{2,60}?)\s+vs\.?\s+(.{2,60}?)(?:\s+stream|\s+live|$)", re.I)


def _pair(title: str) -> tuple[str, str]:
    got = _TITLE.match(title.strip())
    return (got.group(1).strip(), got.group(2).strip()) if got else ("", "")


def _channel_page(tree: HTMLParser, url: str, zone: ZoneInfo) -> list[Program]:
    """Сетка одного канала: все матчи страницы идут этому каналу."""
    head = tree.css_first("title")
    title = " ".join(head.text().split()) if head else ""
    channel = title.split(" TV Schedule")[0].strip()
    if not channel:
        return []
    out: list[Program] = []
    for row in tree.css("tr.matchrow"):
        ts = row.css_first("span.ts[dv]")
        link = row.css_first('a[href^="/match/"]')
        if ts is None or link is None:
            continue
        ms = ts.attributes.get("dv") or ""
        if not ms.isdigit():
            continue
        start = datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc) \
            .astimezone(zone)
        pair = " ".join(link.text().split())
        if " vs " not in pair:
            continue
        home, _, away = pair.partition(" vs ")
        comp = row.css_first('a[href^="/competitions/"]')
        league = " ".join(comp.text().split()) if comp else ""
        live = row.css_first("span.livecell.live") is not None
        out.append(Program(
            channel_raw=channel, title=pair, start=start,
            raw_time=start.strftime("%H:%M"),
            league_raw=league, sport_raw="Soccer",
            live_raw="live broadcast" if live else "",
            match_raw=f"{home.strip()} - {away.strip()}", source_url=url,
            extra={"day": start.date().isoformat()},
        ))
    return out


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)

    if "/channels/" in (url or ""):
        return _channel_page(tree, url, zone)

    head = tree.css_first("h1")
    title = " ".join(head.text().split()) if head else ""
    home, away = _pair(title)
    if not home or not away:
        return []

    # время берём из блока самого матча (`div.m-date`), а не первым поиском по
    # странице: выше него стоит блок «предстоящие матчи», и там свои метки
    ms = ""
    for node in tree.css("div.m-date span.ts, div.m-date > span"):
        ms = node.attributes.get("dv") or ""
        if ms:
            break
    if not ms:
        stamp = _MS.search(html)
        ms = stamp.group(1) if stamp else ""
    if not ms.isdigit():
        return []
    start = datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc) \
        .astimezone(zone)

    out: list[Program] = []
    for row in tree.css("tr"):
        flag = row.css_first("span.flag")
        if flag is None:
            continue
        country = " ".join(flag.text().split())
        for link in row.css('a[href^="/channels/"]'):
            channel = " ".join(link.text().split())
            if not channel or (channels and channel not in channels):
                continue
            out.append(Program(
                channel_raw=channel, title=title, start=start,
                raw_time=start.strftime("%H:%M"),
                league_raw="", description=f"livesoccertv: {country}",
                live_raw="live broadcast",
                match_raw=f"{home} - {away}", source_url=url,
                extra={"day": start.date().isoformat(), "country": country},
            ))
    return out

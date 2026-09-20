# -*- coding: utf-8 -*-
"""oneplay.cz — Чехия, телегид OnePlay (CMS jyxo), уровень A.

Страница `oneplay.cz/program` — каркас Nuxt, сетку рисует скрипт. Данные —
открытая ручка, без входа (разведка 16–18.09):

    POST https://http.cms.jyxo.cz/api/v1.13/epg.display
    {"deviceInfo": {...web...}, "context": {"requestId", "clientId"},
     "payload": {"criteria": {"viewport": {"schema": "EpgViewportAbsolute",
                 "channelRange": {"from": 0, "to": 52},
                 "timeRange": {"from": ISO, "to": ISO}}},
                 "requestedOutput": {"channelSchedule": true}}}

Ответ: `data.channelList` (id, name) и `data.schedule` — по колонке на
канал, у передачи `title`, `description`, `startAt`/`endAt` со смещением.
Каналов 149, нужные владельцу (18.09) стоят в первых 51 — одним запросом на
сутки берём диапазон 0–52 и отбираем по имени. Сутки — UTC: ручка отдаёт и
передачи, лишь задевшие окно, поэтому берём только начавшиеся в эти сутки,
иначе ночной матч приходил бы дважды.

Чем ценен рядом с `oneplaysport.cz` (те же Nova Sport / Oneplay Sport):
в ОПИСАНИИ есть вид спорта («Záznam fotbalového utkání…», «tenisového
turnaje», «Hokej») и отметка эфира («Přímý přenos», «živě» / «Záznam»).

Формы заголовка:
  - `CHL: FC Slovan Liberec-FK Mladá Boleslav` — лига до двоеточия;
  - `Fotbal - Evropská liga, Ligová fáze, Sunderland - AZ` (Sport1) — куски
    через запятую, пара — с конца, первый кусок «спорт - лига»;
  - `Maxa liga 2026/2027, Hokej` (ČT Sport) — пары в заголовке нет, она в
    описании: `… | VHK ROBE Vsetín - RI Okna Berani Zlín. Záznam utkání…`;
  - `Ipswich Town - Arsenal FC` (Nova Sport) — пара целиком.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime, timezone
from urllib.parse import parse_qs, urlsplit

from . import Program, register

DOMAIN = "oneplay.cz"
TZ = "Europe/Prague"

#: слова вида спорта, которыми Sport1 и ČT Sport открывают или закрывают
#: заголовок («Fotbal - Evropská liga, …», «Maxa liga, Hokej»): такой кусок —
#: рубрика, а не пара команд
_SPORT_WORDS = {
    "fotbal", "lední hokej", "hokej", "tenis", "basketbal", "házená",
    "volejbal", "florbal", "futsal", "americký fotbal", "rugby", "box",
    "mma", "atletika", "cyklistika", "golf", "šipky", "snooker",
    "motorsport", "formule 1", "poker", "plážový fotbal", "stolní tenis",
}

_LIVE_WORDS = ("přímý přenos", "živě")


#: имена, которые в базе уже записаны иначе: «ČT sport» (Чехия) пришёл с
#: `tv-program.aktuality.sk`, второй такой канал был бы двойником
_OUR_NAMES = {"ČT Sport": "ČT sport"}


def channel_name(raw: str) -> str:
    """`Nova Sport 1 HD` → `Nova Sport 1`: у нас каналы без «HD», и так же их
    называют `oneplaysport.cz` и словацкие телегиды."""
    name = re.sub(r"\s+HD$", "", " ".join((raw or "").split()))
    return _OUR_NAMES.get(name, name)


def _pair(text: str) -> str:
    """Пара `Хозяева - Гости` из куска текста. Дефис без пробелов (`AC Sparta
    Praha-SK Slavia Praha`) — только если у одной из сторон два слова, иначе
    `TIKI-TAKA` станет матчем (правило `oneplaysport.cz`)."""
    for sep in (" - ", " – "):
        if sep in text:
            home, _, away = text.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    for sep in ("-", "–"):
        if sep in text:
            home, _, away = text.partition(sep)
            home, away = home.strip(), away.strip()
            if home and away and (" " in home or " " in away):
                return f"{home} - {away}"
            break
    return ""


def split(title: str, description: str) -> tuple[str, str, str]:
    """(вид спорта, лига, пара) из заголовка, а при нужде — из описания."""
    title = " ".join((title or "").split())
    sport = league = pair = ""
    head, colon, rest = title.partition(":")
    if colon and rest.strip():
        league = head.strip()
        # «CHL» у OnePlay — Chance Liga (футбол), а не хоккейная Лига
        # чемпионов: так же и в `oneplaysport.cz` (12.09)
        if league.upper() == "CHL":
            league = "Chance Liga"
        pair = _pair(rest.strip())
    else:
        pieces = [p.strip() for p in title.split(",") if p.strip()]
        for i in range(len(pieces) - 1, -1, -1):
            left = pieces[i].partition(" - ")[0].strip().lower()
            if left in _SPORT_WORDS:
                continue
            pair = _pair(pieces[i])
            if pair:
                pieces = pieces[:i]
                break
        for piece in pieces:
            left, dash, right = piece.partition(" - ")
            if piece.lower() in _SPORT_WORDS:
                sport = sport or piece
            elif dash and left.strip().lower() in _SPORT_WORDS:
                sport, league = sport or left.strip(), league or right.strip()
            elif not league:
                league = piece
    if not pair and description:
        # `Maxa liga 2026/2027, Hokej | VHK ROBE Vsetín - RI Okna Berani Zlín.
        # Záznam utkání…` — пара в первой фразе после черты
        body = description.rpartition(" | ")[2]
        # в скобках — место и стадия («(Red Bull Ring - Spielberg)»), не пара
        body = re.sub(r"\([^)]*\)", " ", body.split(". ")[0])
        pair = _pair(" ".join(body.split()))
    return sport, league, pair


def _utc_day(url: str, day) -> _date | None:
    got = (parse_qs(urlsplit(url or "").query).get("day") or [""])[0]
    try:
        return _date.fromisoformat(got)
    except ValueError:
        return day if isinstance(day, _date) else None


@register(DOMAIN)
def parse(html: str, *, day=None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = (json.loads(html) or {}).get("data") or {}
    except (ValueError, AttributeError):
        return []
    names = {str(c.get("id")): channel_name(c.get("name") or "")
             for c in data.get("channelList") or [] if isinstance(c, dict)}
    asked = _utc_day(url, day)

    out: list[Program] = []
    for column in data.get("schedule") or []:
        name = names.get(str(column.get("channelId")), "")
        if not name or (channels and name not in channels):
            continue
        for item in column.get("items") or []:
            title = " ".join((item.get("title") or "").split())
            try:
                start = datetime.fromisoformat(item.get("startAt") or "")
            except ValueError:
                continue
            if not title or start.tzinfo is None:
                continue
            if asked and start.astimezone(timezone.utc).date() != asked:
                continue
            description = " ".join((item.get("description") or "").split())
            sport, league, pair = split(title, description)
            text = f"{title} {description}".lower()
            live = next((w for w in _LIVE_WORDS if w in text), "")
            out.append(Program(
                channel_raw=name, title=title, start=start,
                raw_time=start.strftime("%H:%M"),
                description=description[:300],
                league_raw=league[:120], sport_raw=sport[:80],
                live_raw=live, match_raw=pair or " ", source_url=url,
                extra={"day": start.date().isoformat(),
                       "end": item.get("endAt") or ""},
            ))
    return out

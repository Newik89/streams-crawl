# -*- coding: utf-8 -*-
"""football-tv.ru — Россия, телеканал «Футбол» (Tilda-сайт).

Главная — карточки ближайших прямых трансляций канала, один запрос:

    .t-card__uptitle    `28.08.2026 в 14:30` (московское время)
    .t-card__title > a  `Далянь - Бейцзин Гоань`

Карточки без даты («подборка хайлайтов…») — реклама, мимо. Всё с датой —
анонс эфира, отдельного маркера нет: канал публикует только прямые.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "football-tv.ru"
TZ = "Europe/Moscow"
#: единственный канал сайта. Книга 125, З7: когда карточек анонсов на главной
#: нет (разбор ниже даёт ноль строк), страницу читает запасное чтение
#: (`app/fallback_read.py`) — суточную сетку с повторами, эфир в ней
#: подтверждает эталон
CHANNEL = "Футбол"

_CARD = re.compile(
    r't-card__uptitle[^>]*>\s*(\d{2})\.(\d{2})\.(\d{4})\s+в\s+'
    r'(\d{1,2}):(\d{2})\s*</div>.*?t-card__title[^>]*>.*?>\s*([^<]+?)\s*</a>',
    re.S)


#: анонсы прямых эфиров в бегущей строке (с ноября 2026, книга 128):
#: «Live | Данди – Хартс | SPFL | Суббота 21.11.2026 в 20:45»; лиги может не
#: быть: «Live | Рейнджерс – Абердин | Вторник 24.11.2026 в 23:00»
_TICKER = re.compile(
    r"Live\s*\|\s*(?P<pair>[^|<]+?)\s*\|\s*(?:(?P<league>[^|<]+?)\s*\|\s*)?"
    r"[^\W\d_]+\s+(\d{2})\.(\d{2})\.(\d{4})\s+в\s+(\d{1,2}):(\d{2})")


def _ticker(html: str, zone, channel: str, url: str) -> list[Program]:
    """Анонсы из бегущей строки; повтор одной записи (строка крутится
    дважды) — один раз."""
    out, seen = [], set()
    for m in _TICKER.finditer(html):
        dd, mo, yy, hh, mi = m.groups()[2:]
        title = " ".join(m["pair"].split())
        try:
            start = datetime(int(yy), int(mo), int(dd), int(hh), int(mi), tzinfo=zone)
        except ValueError:
            continue
        if (title, start) in seen:
            continue
        seen.add((title, start))
        pair = title.replace(" – ", " - ")
        out.append(Program(
            channel_raw=channel, title=title, start=start, raw_time=f"{hh}:{mi}",
            league_raw=" ".join((m["league"] or "").split())[:120], sport_raw="футбол",
            live_raw="live broadcast", match_raw=pair if " - " in pair else " ",
            source_url=url, extra={"day": start.date().isoformat()}))
    return out


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    channel = CHANNEL
    if channels and channel not in channels:
        return []
    out: list[Program] = []
    for m in _CARD.finditer(html):
        dd, mo, yy, hh, mi, title = m.groups()
        title = title.strip()
        try:
            start = datetime(int(yy), int(mo), int(dd), int(hh), int(mi),
                             tzinfo=zone)
        except ValueError:
            continue
        pair = title if " - " in title else " "
        out.append(Program(
            channel_raw=channel, title=title, start=start,
            raw_time=f"{hh}:{mi}",
            sport_raw="футбол",
            live_raw="live broadcast",
            match_raw=pair, source_url=url,
            extra={"day": start.date().isoformat()},
        ))
    # книга 128: тот же анонс бывает и в бегущей строке — добавляем её
    # записи, которых нет среди карточек
    have = {(p.start, p.match_raw.replace(" ", "").lower()) for p in out}
    out += [p for p in _ticker(html, zone, channel, url)
            if (p.start, p.match_raw.replace(" ", "").lower()) not in have]
    return out

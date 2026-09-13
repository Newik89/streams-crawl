# -*- coding: utf-8 -*-
r"""cosmotetv.gr — Греция, каналы COSMOTE Sport 1–9; все каналы одним адресом.

Сайт закрыт для дата-центров: у владельца в браузере он отдаёт всё
расписание, а любому серверу — и раннеру GitHub, и нашему DigitalOcean —
заглушку Imperva. Капчу мы не обходим, поэтому страницу берёт открытая
читалка (`app/fetch.py` → `VIA_READER`); для парсера это обычный HTML.

Адрес — время начала суток в секундах и категория «спортивные»:

    https://www.cosmotetv.gr/program?date={unix}&category=Αθλητικά

Разметка Next.js с хешированными классами, поэтому цепляемся за их
устойчивую часть (`[class*=…]`):

    [class*=stripeChannelLogo] > img[alt="COSMOTE Sport 1 HD"]   имя канала
    [class*=itemTitle]  `Ποδόσφαιρο: Μπράγκα - Βιτόρια Γκιμαράες`
    [class*=itemType]   `Ποδόσφαιρο`
    [class*=itemStart]  `16:00`

Строки идут в порядке страницы: сначала логотип канала, потом его передачи,
дальше следующий канал. Прямой эфир сайт помечает пометкой `(Ζ)` в конце
заголовка — от `ζωντανά`, «живьём».
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "cosmotetv.gr"
#: 11.09.2026 сайт (уже как magentatv.gr) перестал класть сетку в HTML:
#: сервер-рендер отдаёт только первые две ленты-заглушки (Highlights и
#: Promo), остальные каналы дорисовывает скрипт при прокрутке — обход
#: получал «расписание есть», а матчей ноль. Данные берём с их же ручки
#: EPG (нашлась через конфиг cosmotetv.gr в iptv-org/epg; открыта и
#: GitHub-раннеру — проба #289, и нашему серверу):
#:     https://mwapi-prod.cosmotetvott.gr/api/v3.4/epg/listings/el
#:         ?from={UNIXDAY}&to={UNIXDAYEND}&endingIncludedInRange=false
#: Без `callSigns` отвечает сеткой всех ~111 каналов за сутки UTC — один
#: запрос на день; окно шире суток и список каналов через запятую ручка
#: молча игнорирует (проверено с сервера 12.09). Нужные каналы отбирает
#: `include` карточки источника.
API_DOMAIN = "mwapi-prod.cosmotetvott.gr"
#: 07.09.2026 сайт перезапустился под именем Magenta TV (бывший Cosmote), и
#: время в отдаваемой разметке теперь стоит в UTC — в местное его пересчитывает
#: скрипт уже в браузере (Удинезе — Лацио лежал как 18:45 при эфире 21:45
#: Афин; из-за трёх часов разницы игра не склеивалась с эталоном и жила
#: дублем). Поэтому часы читаем как UTC; прежний пояс оставлен только для
#: истории. Каналы страница зовёт «Magenta Sport N» — старые имена
#: «COSMOTE Sport N HD» связывает `scripts/magenta_aliases.py`.
TZ = "UTC"

_HHMM = re.compile(r"(\d{1,2}):(\d{2})")
_UNIX = re.compile(r"date=(\d{9,11})")
_LIVE_MARK = re.compile(r"\(\s*Ζ\s*\)\s*$")


def _pair(title: str) -> str:
    tail = title.split(":", 1)[1] if ":" in title else title
    tail = _LIVE_MARK.sub("", tail)
    for sep in (" - ", " – ", " — "):
        if sep in tail:
            home, _, away = tail.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


def _parse_api(html: str, *, url: str = "",
               channels: set[str] | None = None) -> list[Program]:
    """Разбор JSON ручки EPG: каналы → передачи, время ISO с поясом."""
    data = json.loads(html)
    out: list[Program] = []
    for ch in data.get("channels") or []:
        channel = " ".join((ch.get("title") or "").split())
        if not channel or (channels and channel not in channels):
            continue
        for it in ch.get("items") or []:
            title = " ".join((it.get("title") or "").split())
            raw = (it.get("startTime") or "").replace("Z", "+00:00")
            try:
                begin = datetime.fromisoformat(raw)
            except ValueError:
                continue
            if begin.tzinfo is None:      # пояса нет — считаем UTC, как всюду у ручки
                begin = begin.replace(tzinfo=timezone.utc)
            genre = ((it.get("qoe") or {}).get("genre") or "").strip()
            out.append(Program(
                channel_raw=channel, title=title,
                start=begin,
                raw_time=begin.strftime("%H:%M"),
                sport_raw=genre,
                live_raw="ζωντανά" if _LIVE_MARK.search(title) else "",
                match_raw=_pair(title), source_url=url,
                extra={"day": begin.date().isoformat()},
            ))
    return out


@register(DOMAIN)
@register(API_DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    head = html.lstrip()[:1]
    if head == "{":                       # ответ ручки EPG, а не страница
        return _parse_api(html, url=url, channels=channels)
    zone = ZoneInfo(tz or TZ)
    got = _UNIX.search(url or "")
    base = (datetime.fromtimestamp(int(got.group(1)), tz=timezone.utc)
            .astimezone(zone).date()) if got else (day or _date.today())

    tree = HTMLParser(html)
    out: list[Program] = []
    channel = title = kind = ""
    # идём по всем `div` подряд: селектор через запятую selectolax отдаёт
    # группами, а не в порядке страницы, и связь «канал → его передачи»
    # разваливается (те же грабли, что на `vsetv.com`)
    for node in tree.css("div"):
        classes = node.attributes.get("class") or ""
        if not any(k in classes for k in
                   ("stripeChannelLogo", "itemTitle", "itemType", "itemStart")):
            continue
        text = " ".join(node.text().split())
        if "stripeChannelLogo" in classes:
            img = node.css_first("img")
            channel = ((img.attributes.get("alt") if img else "") or text).strip()
        elif "itemTitle" in classes:
            title = text
        elif "itemType" in classes:
            kind = text
        elif "itemStart" in classes:
            hm = _HHMM.search(text)
            if not hm or not channel or not title:
                continue
            if channels and channel not in channels:
                continue
            hour, minute = int(hm.group(1)), int(hm.group(2))
            # страница — ведро одного UTC-дня (unix-метка в адресе), ночные
            # часы никуда не сдвигаем: 23:30 UTC — это ещё тот же день
            d = base
            out.append(Program(
                channel_raw=channel, title=title,
                start=datetime(d.year, d.month, d.day, hour, minute, tzinfo=zone),
                raw_time=hm.group(0), sport_raw=kind,
                live_raw="ζωντανά" if _LIVE_MARK.search(title) else "",
                match_raw=_pair(title), source_url=url,
                extra={"day": d.isoformat()},
            ))
            title = kind = ""
    return out

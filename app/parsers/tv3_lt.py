# -*- coding: utf-8 -*-
"""tv3.lt — Литва: телегид портала TV3, канал × день.

Адрес канала: `/programos/<канал>` — день целиком (00:00–24:00); другой
день — параметром `?d=2026-09-08` (нашлось в табах `a.dayItem`, разведка
06.09.2026). Слаги — с подчёркиваниями: `go3_sport_1`, `lrt_plius`.

Разметка строки:

    div.program-item-block
      div.time-item > div.time          `18:30`
      div.description-item > div.title  `TOPLYGA. Lietuvos futbolo
                                         čempionatas. "Kauno Žalgiris" -
                                         Telšių "Džiugas"`

Дата — в активном табе дней (`a.dayItem.on`, `href="?d=2026-09-06"`), её и
берём: страница сама говорит, за какой день сетка. Маркера прямого эфира у
сайта нет — эфир угадывается первым показом пары (`mark_first_show`),
домен перечислен в `REPEAT_GUESS_DOMAINS`.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "tv3.lt"
TZ = "Europe/Vilnius"

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

#: заголовок страницы: `BTV programa`, `Go3 Sport 1 programa`
_TITLE_RE = re.compile(r"^(.*?)\s+programa\b", re.I)

_SEPS = (" - ", " – ", " — ")

#: кавычки в литовской сетке стоят и ВНУТРИ имени (`Telšių "Džiugas"` —
#: город + имя клуба в кавычках), поэтому их не обрезаем по краям, а
#: убираем совсем
_QUOTES = re.compile(r"[«»\"']")


def _side(text: str) -> str:
    return " ".join(_QUOTES.sub(" ", text).split()).strip(" .")


def _pair_chunk(chunks: list[str]) -> int:
    """Номер куска заголовка с парой команд, с конца; -1 — пары нет.
    Куски — предложения через точку: лига и турнир стоят до пары
    (`TOPLYGA. Lietuvos futbolo čempionatas. "Kauno Žalgiris" - Telšių
    "Džiugas"`), но пара не обязательно последняя."""
    for i in range(len(chunks) - 1, -1, -1):
        text = chunks[i]
        for sep in _SEPS:
            if sep in text:
                home, _, away = text.partition(sep)
                if len(_side(home)) >= 2 and len(_side(away)) >= 2:
                    return i
    return -1


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)

    channel = ""
    head = tree.css_first('[class*="ProgramsTitle"]')
    if head:
        got = _TITLE_RE.match(" ".join(head.text().split()))
        if got:
            channel = got.group(1).strip()
    if not channel:
        return []                      # не канальная страница (общая сетка)
    if channels and channel not in channels:
        return []

    page_day = day or _date.today()
    for tab in tree.css("a.dayItem"):
        cls = tab.attributes.get("class") or ""
        if " on" in f" {cls} ":
            got = _DATE.search(tab.attributes.get("href") or "")
            if got:
                page_day = _date(int(got.group(1)), int(got.group(2)),
                                 int(got.group(3)))
            break

    out: list[Program] = []
    for block in tree.css("div.program-item-block"):
        t = block.css_first(".time-item .time")
        title_node = block.css_first(".description-item .title")
        if t is None or title_node is None:
            continue
        hm = _HHMM.match(t.text(strip=True))
        title = " ".join(title_node.text().split())
        if not hm or not title:
            continue
        desc_node = block.css_first(".description-item .description")
        desc = " ".join(desc_node.text().split()) if desc_node else ""

        chunks = [c.strip() for c in title.split(". ") if c.strip()]
        at = _pair_chunk(chunks)
        pair, league = " ", ""
        if at >= 0:
            text = chunks[at]
            for sep in _SEPS:
                if sep in text:
                    home, _, away = text.partition(sep)
                    pair = f"{_side(home)} - {_side(away)}"
                    break
            league = ". ".join(chunks[:at])

        out.append(Program(
            channel_raw=channel, title=title,
            start=datetime(page_day.year, page_day.month, page_day.day,
                           int(hm.group(1)), int(hm.group(2)), tzinfo=zone),
            raw_time=hm.group(0), description=desc,
            league_raw=league[:120], match_raw=pair, source_url=url,
            extra={"day": page_day.isoformat()},
        ))
    return mark_first_show(out, "tiesiogiai")

# -*- coding: utf-8 -*-
"""digisport.ro — Румыния; Digi Sport 1–4, неделя вперёд одной страницей.

Адрес на канал: `/program-tv/digisport-1` … `-4`, даты в адресе нет — страница
сама держит семь дней, ровно то окно, которое нам нужно (сегодня и ещё шесть).
Четыре запроса на всю неделю по всем четырём каналам.

Разметка — обычные таблицы, по одной на день:

    h3                       `Luni 31 August` — заголовок дня
    table > tbody > tr
      td.schedule-icon[data-schedule]  вид передачи: `superliga`, `stiri`…
      td                                `21:30`
      td                                `<span class="tag">LIVE</span> CFR Cluj - FCSB`

`data-schedule` — подсказка сайта, что за передача: `stiri` (новости),
`superliga`, `la liga`, `fotbal european`. Кладём её в лигу — по ней вид
спорта определяется даже там, где в заголовке одна пара команд.

`<span class="tag">LIVE</span>` — честный маркер прямого эфира.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "digisport.ro"
TZ = "Europe/Bucharest"

#: румынские месяцы в заголовках дней (`Luni 31 August`)
_MONTHS = {"ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
           "mai": 5, "iunie": 6, "iulie": 7, "august": 8, "septembrie": 9,
           "octombrie": 10, "noiembrie": 11, "decembrie": 12}

_DAY_HEAD = re.compile(r"(\d{1,2})\s+([A-Za-zăâîșşţț]+)", re.I)
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_CHANNEL = re.compile(r"digisport-(\d)")


#: Хвост стадии турнира сайт приклеивает к имени гостей БЕЗ пробела:
#: `Superliga: Rapid-Universitatea CraiovaEtapa 7`. Снимаем до разбора пары,
#: иначе «Крайова» навсегда останется «CraiovaEtapa 7». Хвостов бывает
#: несколько через запятую (`Real Madrid-InterGrupe, etapa 1` — «группы,
#: тур 1»), поэтому снимаем их цепочкой, а не по одному (поймано 06.09).
_STAGE_TAIL = re.compile(
    r"(?:(?:Etapa\s*\d+|Grupe|Optimi|Sferturi|Semifinale|Finala|Play-?off|"
    r"Turul\s*\w+|Manșa\s*\w+)[\s,]*)+$", re.I)


def _pair(text: str) -> str:
    text = _STAGE_TAIL.sub("", text).strip()
    for sep in (" - ", " – ", " vs ", " VS "):
        if sep in text:
            home, _, away = text.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    # у Digi дефис стоит без пробелов: `Rapid-Universitatea Craiova`
    for sep in ("-", "–"):
        if sep in text:
            home, _, away = text.partition(sep)
            home, away = home.strip(), away.strip()
            if home and away and (" " in home or " " in away
                                  or (len(home) > 3 and len(away) > 3)):
                return f"{home} - {away}"
            break
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    got = _CHANNEL.search(url or "")
    channel = f"Digi Sport {got.group(1)}" if got else "Digi Sport"
    if channels and channel not in channels:
        return []
    today = day or _date.today()
    tree = HTMLParser(html)

    out: list[Program] = []
    current: _date | None = None
    for node in tree.root.traverse():
        if node.tag == "h3":
            head = _DAY_HEAD.search(" ".join(node.text().split()))
            month = _MONTHS.get(head.group(2).lower()) if head else None
            if head and month:
                # года на странице нет: он тот же, что у сегодняшнего дня,
                # а на переходе через Новый год — следующий
                year = today.year + (1 if month < today.month else 0)
                current = _date(year, month, int(head.group(1)))
            continue
        if node.tag != "tr" or current is None:
            continue
        cells = node.css("td")
        if len(cells) < 3:
            continue
        hm = _HHMM.match(cells[1].text(strip=True))
        if not hm:
            continue
        kind = (cells[0].attributes.get("data-schedule") or "").strip()
        tag = cells[2].css_first("span.tag")
        live = bool(tag and "LIVE" in tag.text(strip=True).upper())
        title = " ".join(cells[2].text().split())
        if tag:
            title = title.replace(tag.text(strip=True), "", 1).strip()
        if not title:
            continue
        # `Superliga: Rapid-Universitatea CraiovaEtapa 7` — лига до двоеточия,
        # пара после; двоеточия нет — пару ищем во всём заголовке
        head, sep, rest = title.partition(":")
        league = f"{kind} {head.strip()}".strip() if sep and rest.strip() else kind
        pair = _pair(rest) if sep and rest.strip() else _pair(title)
        out.append(Program(
            channel_raw=channel, title=title,
            start=datetime(current.year, current.month, current.day,
                           int(hm.group(1)), int(hm.group(2)), tzinfo=zone),
            raw_time=hm.group(0), league_raw=league[:120],
            live_raw="live" if live else "",
            match_raw=pair, source_url=url,
            extra={"day": current.isoformat()},
        ))
    return out

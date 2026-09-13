# -*- coding: utf-8 -*-
"""ert.gr — Греция, общественное вещание; 9 каналов одной страницей на день.

Сначала казалось, что нужен адрес на каждый канал (`/tv/program/ert2/?dt=…`),
но общая страница `/tv/program/?dt=ГГГГ-ММ-ДД` уже содержит колонки всех
девяти — один запрос вместо девяти. Источник заведён «дневной сеткой».

Разметка удобная: у каждой передачи проставлено машинное время со смещением,
свою склейку даты и часового пояса городить не нужно.

    div.slide-items
      div.column                       колонка одного канала
        a[title]                       `ΕΡΤ2 ΣΠΟΡ` — имя канала
        div.broadcast[data-start-time]  `2026-08-31 21:00:00+0300`
          span.fs-xs > span            `21:00`
          strong.fs-ms                 заголовок передачи

Спортивные каналы здесь — `ΕΡΤ2 ΣΠΟΡ`, `ΕΡΤ Sports 1`, `ΕΡΤ Sports 2`;
остальные шесть владелец тоже оставил (31.08): матчи сборной идут и на ΕΡΤ1.

Пару команд греки пишут через дефис (`Ολυμπιακός - ΑΕΚ`), иногда с приставкой
вида спорта через двоеточие — разбираем как у остальных.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "ert.gr"
TZ = "Europe/Athens"

_STAMP = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})")


def _pair(text: str) -> str:
    """Пара команд из куска заголовка. Голый дефис берём осторожно: он же
    стоит внутри названий (`Ελλάδα-Ισπανία` — пара, `ΕΡΤ-Αρχείο` — нет),
    поэтому требуем, чтобы хотя бы одна сторона была из двух слов, либо
    чтобы разделитель был с пробелами."""
    for sep in (" - ", " – ", " vs ", " VS "):
        if sep in text:
            home, _, away = text.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    for sep in ("-", "–"):
        if sep in text:
            home, _, away = text.partition(sep)
            home, away = home.strip(), away.strip()
            if home and away and (" " in home or " " in away
                                  or (len(home) > 3 and len(away) > 3)):
                return f"{home} - {away}"
            break
    return " "


def _split(title: str) -> tuple[str, str, str]:
    """Заголовок → (вид спорта, турнир, пара).

    ERT пишет матч частями через вертикальную черту, и пара стоит **не
    обязательно последней**:

        Basket | Προκριματικά Παγκοσμίου Κυπέλλου | Ελλάδα-Ισπανία | Β' Φάση | ΟΑΚΑ

    Здесь последний кусок — стадион, предпоследний — этап, а пара третья.
    Поэтому идём с конца и берём первый кусок, в котором пара нашлась; всё
    остальное складываем в турнир, а первый кусок оставляем видом спорта —
    по нему `app/sport.py` и опознаёт игру (`Basket`, `Ποδόσφαιρο`).
    """
    parts = [p.strip() for p in title.split("|") if p.strip()]
    if len(parts) < 2:
        # без черты: `Handball Ανδρών: Αίγυπτος – Ελλάδα` — вид спорта
        # отделён двоеточием
        head, _, rest = title.partition(":")
        rest = rest.strip()
        if rest:
            return head.strip(), head.strip(), _pair(rest)
        return "", "", _pair(title)

    pair, used, inner = " ", -1, ""
    for i in range(len(parts) - 1, -1, -1):
        # внутри куска бывает вид спорта через двоеточие:
        # `Handball Ανδρών: Αίγυπτος – Ελλάδα (Τελικός)` — его надо отрезать
        # ДО поиска пары, иначе он уедет в имя хозяев
        head, sep, tail = parts[i].partition(":")
        got = _pair(tail.strip()) if sep and tail.strip() else " "
        if got.strip():
            pair, used, inner = got, i, head.strip()
            break
        got = _pair(parts[i])
        if got.strip():
            pair, used = got, i
            break
    sport = inner or parts[0]
    league = " | ".join(p for i, p in enumerate(parts) if i not in (0, used))
    return sport, (league or sport)[:120], pair


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)

    out: list[Program] = []
    for column in tree.css("div.slide-items div.column"):
        head = column.css_first("a[title]")
        channel = (head.attributes.get("title") or "").strip() if head else ""
        if not channel or (channels and channel not in channels):
            continue
        for item in column.css("div.broadcast"):
            stamp = _STAMP.match(item.attributes.get("data-start-time") or "")
            title_node = item.css_first("strong")
            title = title_node.text(strip=True) if title_node else ""
            if not stamp or not title:
                continue
            sport, league, pair = _split(title)
            start = datetime(int(stamp.group(1)), int(stamp.group(2)),
                             int(stamp.group(3)), int(stamp.group(4)),
                             int(stamp.group(5)), tzinfo=zone)
            out.append(Program(
                channel_raw=channel, title=title, start=start,
                raw_time=f"{stamp.group(4)}:{stamp.group(5)}",
                league_raw=league, sport_raw=sport,
                match_raw=pair, source_url=url,
                extra={"day": start.date().isoformat()},
            ))
    return mark_first_show(out, "ζωντανά")

# -*- coding: utf-8 -*-
"""teleman.pl — Польша, уровень B (разметка HTML).

Одна страница = один канал за один день:
`program-tv/stacje/{слаг}?date={ГГГГ-ММ-ДД}`. Разметка аккуратная:

    ul.stationItems > li[id^="prog"]     блок передачи (реклама — li.ad, мимо)
      em                                  12:55  (без ведущего нуля!)
      .detail > a                         Piłka nożna: 2. liga niemiecka
      p.genre                             mecz: Karlsruher SC - VfL Wolfsburg
      p (без класса)                      описание
      span.attr-live[title]               прямой эфир — отдельным тегом
      класс на li: cat-spo / cat-dok …    рубрика

Две особенности сайта:

* **Команды стоят не в заголовке, а в `p.genre`** — там `mecz: Хозяева -
  Гости`. В заголовке только вид спорта и лига. Поэтому пару команд ищем
  в `p.genre`, а заголовок оставляем как есть.
* **Маркера записи нет вообще.** Нет тега `attr-live` — значит не эфир,
  других признаков сайт не даёт. Мусор виден по жанру: `magazyn piłkarski`,
  `film dokumentalny`, `cykl reportaży`.

Время настенное, варшавское, с переходом через полночь: день идёт
`6:00 → 23:45 → 0:00 → 2:00 → 4:00`.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from .. import daytime
from . import Program, register

DOMAIN = "teleman.pl"
TZ = "Europe/Warsaw"

_DATE_IN_URL = re.compile(r"date=(\d{4})-(\d{2})-(\d{2})")
_SLUG_IN_URL = re.compile(r"/program-tv/stacje/([^/?#]+)")
# `mecz: Karlsruher SC - VfL Wolfsburg` — слева жанр, справа пара команд
_MATCH_GENRE = re.compile(r"^\s*(mecz|me[cz]z)\s*:\s*(.+)$", re.I)


def page_day(html: str, url: str = "") -> _date | None:
    """Дата страницы: сперва из адреса, потом из ссылки `canonical`."""
    for source in (url, html[:4000]):
        m = _DATE_IN_URL.search(source or "")
        if m:
            return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    node = HTMLParser(html).css_first("link[rel=canonical]")
    if node:
        m = _DATE_IN_URL.search(node.attributes.get("href") or "")
        if m:
            return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def page_channel(html: str, url: str = "") -> str:
    """Название канала. В заголовке страницы оно стоит первым:
    `Eleven Sports 2 - Program TV na Poniedziałek 23.02.2026`."""
    node = HTMLParser(html).css_first("title")
    if node:
        name = node.text(strip=True).split(" - Program")[0].strip()
        if name:
            return name
    m = _SLUG_IN_URL.search(url or "")
    return m.group(1).replace("-", " ") if m else ""


def list_channels(html: str) -> dict[str, str]:
    """Слаг → название по списку станций внизу страницы. 155 каналов,
    спортивных 26 — в закладке владельца стоял один (`recon/channels_map.md`)."""
    out: dict[str, str] = {}
    for a in HTMLParser(html).css('a[href*="/program-tv/stacje/"]'):
        m = _SLUG_IN_URL.search(a.attributes.get("href") or "")
        name = a.text(strip=True)
        if m and name:
            out.setdefault(m.group(1), name)
    return out


def sport_channels(html: str) -> dict[str, str]:
    """Только группа «Sportowe» из списка станций — 26 каналов.

    Обходить все 155 незачем: 129 из них к спорту отношения не имеют, а
    страница здесь одна на канал и на день, то есть каждый лишний канал —
    это плюс 13 запросов к сайту (`recon/channels_map.md`).
    """
    out: dict[str, str] = {}
    for nav in HTMLParser(html).css("nav.stations-sidebar-group"):
        head = nav.css_first("h3")
        if not head or "sport" not in head.text(strip=True).lower():
            continue
        for a in nav.css("a[href]"):
            m = _SLUG_IN_URL.search(a.attributes.get("href") or "")
            name = a.attributes.get("title") or a.text(strip=True)
            if m and name:
                out.setdefault(m.group(1), name.strip())
    return out


# ── сводная страница «Transmisje sportowe» ──────────────────────────────────
# /sport?live=1&stations=all&page={N} — все спортивные ПРЯМЫЕ эфиры всех
# каналов одной таблицей (нашёл владелец, 31.08). Колонки: дата, время,
# канал, заголовок (+ <em>mecz …: Хозяева - Гости</em>, + иконка «na żywo»),
# категория. Одна страница = 20 строк; дальше пагинация. Это заменяет обход
# 26 канальных страниц: ~3 страницы на день вместо 26 запросов.

_PL_MONTHS = {"stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4,
              "maja": 5, "czerwca": 6, "lipca": 7, "sierpnia": 8,
              "września": 9, "października": 10, "listopada": 11,
              "grudnia": 12}
_DAY_CELL = re.compile(r"(\d{1,2})\s+(\w+)", re.U)


def _cell_date(text: str, anchor: _date) -> _date | None:
    """`dziś, 31 sierpnia` / `jutro, 1 września` / `środa, 3 września` →
    дата. Год берём от дня запроса; декабрь/январь на стыке — поправка."""
    low = text.strip().lower()
    if low.startswith("dziś"):
        return anchor
    if low.startswith("jutro"):
        return anchor + timedelta(days=1)
    m = _DAY_CELL.search(low)
    if not m or m.group(2) not in _PL_MONTHS:
        return None
    month = _PL_MONTHS[m.group(2)]
    year = anchor.year + (1 if month < anchor.month - 6 else 0)
    return _date(year, month, int(m.group(1)))


def parse_sport(html: str, *, day: _date | None = None, tz: str | None = None,
                url: str = "") -> list[Program]:
    tree = HTMLParser(html)
    anchor = day or _date.today()
    out: list[Program] = []
    for tr in tree.css("table tr"):
        cells = tr.css("td")
        if len(cells) < 5:
            continue
        when = _cell_date(cells[0].text(strip=True), anchor)
        raw_time = cells[1].text(strip=True)
        channel = cells[2].text(strip=True)
        title_node = cells[3].css_first("a.prog-title")
        live_node = cells[3].css_first("img.live")
        em = cells[3].css_first("em")
        genre = cells[4].text(strip=True)
        if when is None or not title_node or not raw_time:
            continue
        hm = daytime.parse_hhmm(raw_time)
        if hm is None:
            continue
        moment = datetime(when.year, when.month, when.day, hm[0], hm[1],
                          tzinfo=ZoneInfo(tz or TZ))
        text = em.text(strip=True) if em else ""
        # пара команд — в <em>: `mecz 1/8 finału: Holandia - Słowenia`;
        # нет двоеточия с парой — матча в строке нет
        tail = text.split(":", 1)[1].strip() if text.lower().startswith("mecz") \
            and ":" in text else ""
        out.append(Program(
            channel_raw=channel, title=title_node.text(strip=True),
            start=moment, raw_time=raw_time, description=text,
            league_raw=title_node.text(strip=True), sport_raw=genre,
            live_raw=(live_node.attributes.get("title") or "program na żywo")
            if live_node else "",
            match_raw=tail or " ", source_url=url,
            extra={"day": when.isoformat(), "genre": genre},
        ))
    return out


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "") -> list[Program]:
    if "/sport" in (url or "").split("?")[0]:
        return parse_sport(html, day=day, tz=tz, url=url)
    tree = HTMLParser(html)
    day = page_day(html, url) or day or _date.today()
    channel = page_channel(html, url)

    rows = []
    # `[id^=prog]` — иначе в список попадает рекламный блок `li.ad`
    # без времени и заголовка, и в отчёте появляется пустая строка
    for li in tree.css('ul.stationItems > li[id^="prog"]'):
        time_node = li.css_first("em")
        title_node = li.css_first(".detail > a")
        genre_node = li.css_first("p.genre")
        text_nodes = [p.text(strip=True) for p in li.css(".detail > p")
                      if "genre" not in (p.attributes.get("class") or "")]
        live_node = li.css_first("span.attr-live")
        rows.append({
            "raw_time": time_node.text(strip=True) if time_node else "",
            "title": title_node.text(strip=True) if title_node else "",
            "genre": genre_node.text(strip=True) if genre_node else "",
            "text": " ".join(text_nodes),
            "live": (live_node.attributes.get("title") or "прямой эфир") if live_node else "",
            "cat": li.attributes.get("class") or "",
        })

    moments = daytime.walk_day([r["raw_time"] for r in rows], day, tz or TZ)

    out = []
    for row, moment in zip(rows, moments):
        genre = row["genre"]
        m = _MATCH_GENRE.match(genre)
        # пара команд живёт в жанре; нет приставки `mecz:` — матча тут нет
        match_raw = m.group(2).strip() if m else ""
        out.append(Program(
            channel_raw=channel, title=row["title"], start=moment,
            raw_time=row["raw_time"], description=row["text"],
            league_raw=row["title"], sport_raw=genre,
            live_raw=row["live"], match_raw=match_raw, source_url=url,
            extra={"genre": genre, "cat": row["cat"], "day": day.isoformat()},
        ))
    return out

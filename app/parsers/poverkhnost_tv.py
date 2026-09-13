# -*- coding: utf-8 -*-
"""poverkhnost.tv — Украина, уровень B (текст с <br>), каналы Sport 1–5.

Телекомпания «Поверхность»: `pages/index.php?c=10&s={id}` — программа
одного канала на НЕДЕЛЮ одной страницей (тип «канальная сетка», без даты).
Спортивные id: 135 Sport 1, 121 Sport 2, 161 Sport 3, 124 Sport 4,
168 Sport 5 (там же неспортивные Kino/RAZ — не берём).

Разметка — простой текст с разделителями:

    <b>Понедельник 31 августа</b>           день (год не пишут, месяц словом,
                                            текст русский)
    20:00&nbsp; …Футбол. Лига Европы. Стыковые матчи. 2-й матч.
    Кауно Жальгирис (LTU) - Бешикташ (TUR).&nbsp;<b><font …>LIVE</font></b>

**`LIVE` красным — честный маркер** (проба 31.08). Строка передачи:
`Вид. Турнир[. Тур]. Пара` — вид спорта первым словом с точкой, пара —
сегмент с « - »/« – ». Времена внутри дня календарные (день начинается
с 00:00).
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, register
from .tvarenaprogram_com import _year_for

DOMAIN = "poverkhnost.tv"
TZ = "Europe/Kyiv"

CHANNELS = {"135": "Sport 1", "121": "Sport 2", "161": "Sport 3",
            "124": "Sport 4", "168": "Sport 5"}

_MONTHS = {m: i + 1 for i, m in enumerate(
    ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
     "августа", "сентября", "октября", "ноября", "декабря"))}
_DAY = re.compile(r"(\d{1,2})\s+([а-яё]+)", re.I)
_ROW = re.compile(r"^(\d{1,2}):(\d{2})\s*(.+)$")
_TAGS = re.compile(r"<[^>]+>")
_PAIR_SEP = (" - ", " – ", " — ")


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    anchor = day or datetime.now(ZoneInfo(tz or TZ)).date()
    zone = ZoneInfo(tz or TZ)
    m = re.search(r"[?&]s=(\d+)", url or "")
    channel = CHANNELS.get(m.group(1)) if m else None
    if not channel:
        return []
    if channels and channel not in channels:
        return []

    out: list[Program] = []
    cur: _date | None = None
    # <br> и <div> — переводы строк; жирные заголовки дней остаются в тексте
    text = re.sub(r"<(?:br|/?div)[^>]*>", "\n", html)
    for line in text.split("\n"):
        live = "LIVE" in line
        clean = _TAGS.sub("", line).replace("&nbsp;", " ").replace("\xa0", " ")
        clean = " ".join(clean.split()).removesuffix("LIVE").strip(" .")
        if not clean:
            continue
        dm = _DAY.search(clean)
        if dm and _MONTHS.get(dm.group(2).lower()) and not _ROW.match(clean):
            cur = _year_for(int(dm.group(1)), _MONTHS[dm.group(2).lower()],
                            anchor)
            continue
        row = _ROW.match(clean)
        if not row or cur is None:
            continue
        body = row.group(3).strip()
        parts = [p.strip() for p in body.split(". ") if p.strip()]
        sport_word = parts[0] if len(parts) > 1 else ""
        pair, league_parts = " ", []
        for part in (parts[1:] if len(parts) > 1 else parts):
            if pair == " ":
                for sep in _PAIR_SEP:
                    if sep in part:
                        home, _, away = part.partition(sep)
                        if home.strip() and away.strip():
                            pair = f"{home.strip()} - {away.strip()}"
                        break
                if pair != " ":
                    continue
            if pair == " ":
                league_parts.append(part)
        out.append(Program(
            channel_raw=channel, title=body,
            start=datetime(cur.year, cur.month, cur.day,
                           int(row.group(1)), int(row.group(2)), tzinfo=zone),
            raw_time=f"{row.group(1)}:{row.group(2)}",
            league_raw=". ".join(league_parts)[:120] if pair != " " else "",
            sport_raw=sport_word,
            live_raw="live" if live else "",
            match_raw=pair, source_url=url,
            extra={"day": cur.isoformat()},
        ))
    return out

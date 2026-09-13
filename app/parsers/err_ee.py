# -*- coding: utf-8 -*-
"""jupiter.err.ee — Эстония, ERR: открытый JSON отдельным доменом.

Сам сайт за Cloudflare, но API живёт на `services.err.ee` и отвечает
серверам (снято браузером владельца 02.09, проба с раннера 200):

    https://services.err.ee/api/tvSchedule/getTimelineSchedule
        ?day={D}&month={M}&year={YYYY}&channel=etv2

Каналы: `etv`, `etv2`, `etvpluss`. Спорт у ERR редкий (лыжи, отборы
сборных, олимпиады) — большинство строк отсеется, это нормально.

Запись: `startTime` — unix-секунды (абсолютные, пояс не нужен);
`programName` — полное имя («Jalgpall: ...»); `automaticReplay == "Y"` —
повтор. Флага прямого эфира нет: непомеченные повтором строки получают
маркер первым показом пары (`mark_first_show`), домен в
`REPEAT_GUESS_DOMAINS`.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime, timezone

from . import Program, mark_first_show, register

DOMAIN = "jupiter.err.ee"
TZ = "Europe/Tallinn"

_CHANNELS = {"etv": "ETV", "etv2": "ETV2", "etvpluss": "ETV+"}
_URL_CHANNEL = re.compile(r"channel=([a-z0-9]+)")


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs "):
        if sep in text:
            home, _, away = text.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    start = html.find("[")
    if start < 0:
        return []
    try:
        data = json.loads(html[start:html.rfind("]") + 1])
    except ValueError:
        return []
    m = _URL_CHANNEL.search(url or "")
    channel = _CHANNELS.get(m.group(1) if m else "", "ERR")

    out: list[Program] = []
    for rec in data if isinstance(data, list) else []:
        title = " ".join((rec.get("programName") or rec.get("name") or "").split())
        stamp = rec.get("startTime")
        if not title or not stamp:
            continue
        begin = datetime.fromtimestamp(int(stamp), tz=timezone.utc)
        replay = (rec.get("automaticReplay") or "") == "Y"
        head, sep, tail = title.partition(":")
        rest = tail.strip() if sep and tail.strip() else title
        out.append(Program(
            channel_raw=channel, title=title,
            start=begin,
            raw_time=begin.strftime("%H:%M"),
            description=(rec.get("lead") or "")[:200],
            league_raw=head.strip()[:120] if sep and tail.strip() else "",
            live_raw="" if replay else "",
            match_raw=" " if replay else _pair(rest),
            source_url=url, extra={"day": begin.date().isoformat()},
        ))
    return mark_first_show(out, "otseülekanne")

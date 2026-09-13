# -*- coding: utf-8 -*-
r"""kolla.tv (он же dagenstv.com) — Швеция, 16 каналов за один запрос.

`dagenstv.com` — только витрина: сам сайт по своему же `/api/...` гоняет
запрос по кругу редиректов, а сертификат отдаёт неполной цепочкой. Настоящий
адрес данных нашёлся в его бандле — `baseURL: "https://www.kolla.tv"`:

    https://www.kolla.tv/api/es/channels/listWithPrograms?dat=2026-09-01

Ответ — сутки по всем каналам сразу:

    {"status": true, "content": {"channels": [
        {"name": "Eurosport 1", "programs": [
            {"name": "Fotboll: Malmö FF - AIK", "startTime": 1788253500000,
             "live": true, "repeat": false, "sports": true,
             "formattedStartTime": "11:05", "description": "…"}]}]}}

Особенности:

- время — миллисекунды, часовой пояс страницы значения не имеет;
- заголовок устроен как `Вид спорта: Турнир, Хозяева - Гости`, поэтому вид
  спорта берём словом до двоеточия (`Fotboll`, `Tennis`), а пару — из хвоста;
- флаги `live` и `repeat` у сайта есть, но **всегда пустые** (проверено на
  401 передаче за сутки), поэтому эфир, как у `ert.gr`, определяем первым
  показом пары — домен в `REPEAT_GUESS_DOMAINS`;
- флаг `sports` сайт проставляет не всем спортивным передачам (у Eurosport он
  пуст у всех), опираться на него нельзя — только на слово в заголовке.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime, timezone
from zoneinfo import ZoneInfo

from . import Program, mark_first_show, register

DOMAIN = "kolla.tv"
TZ = "Europe/Stockholm"

_JSON = re.compile(r"\{.*\}", re.S)


def _pair(title: str) -> str:
    tail = title.split(":", 1)[1] if ":" in title else title
    for sep in (" - ", " – ", " mot ", " vs "):
        if sep in tail:
            home, _, away = tail.partition(sep)
            home = home.split(",")[-1]
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


def _sport(title: str) -> str:
    """Вид спорта сайт ставит первым словом заголовка: `Fotboll: …`."""
    head = title.split(":", 1)[0].strip() if ":" in title else ""
    return head if 0 < len(head) <= 20 else ""


@register(DOMAIN)
@register("dagenstv.com")
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    # ответ иногда приходит завёрнутым в страницу-просмотрщик (`<pre>{…}</pre>`)
    body = _JSON.search(html)
    if not body:
        return []
    try:
        data = json.loads(body.group(0))
    except ValueError:
        return []
    content = (data.get("content") or {}) if isinstance(data, dict) else {}

    out: list[Program] = []
    for block in content.get("channels") or []:
        channel = (block.get("name") or "").strip()
        if not channel or (channels and channel not in channels):
            continue
        for show in block.get("programs") or []:
            title = " ".join((show.get("name") or "").split())
            stamp = show.get("startTime")
            if not title or not isinstance(stamp, (int, float)):
                continue
            start = datetime.fromtimestamp(stamp / 1000, tz=timezone.utc) \
                .astimezone(zone)
            out.append(Program(
                channel_raw=channel, title=title, start=start,
                raw_time=show.get("formattedStartTime")
                or start.strftime("%H:%M"),
                description=" ".join((show.get("description") or "").split())[:300],
                league_raw=title.split(":", 1)[-1].split(",")[0].strip()[:120],
                sport_raw=_sport(title),
                live_raw="live broadcast" if show.get("live") else "",
                match_raw=_pair(title), source_url=url,
                extra={"day": start.date().isoformat()},
            ))
    return mark_first_show(out, "direkt")

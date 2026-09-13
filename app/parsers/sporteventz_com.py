# -*- coding: utf-8 -*-
"""sporteventz.com — агрегатор «матч → каналы мира», как liveonsat.

Ручка `index.php?option=com_magictable&…&accesskey={WARMKEY}&…` отвечает
чистым JSON, но ключ одноразовый: живёт меньше суток и лежит в главной
странице. Обход берёт его сам — метка `{WARMKEY}` в адресе + `warmup_url`
на `/en/` (`WARMKEY_PATTERNS` в `app/fetch.py`). Догадка образца 01.09
(«ключ надо брать из свежей страницы») подтвердилась пробой 02.09.

Запись: `Begin` — `Tuesday, 01 September 2026 15:30` во времени пояса
`client_tz_offset` из адреса. Шлём смещение Киева на день запроса — метка
`{KYIVOFF}` в шаблоне адреса (`%2B0300` летом, `%2B0200` зимой; C1 аудита),
разбор читает его из того же адреса — запрос и разбор не разъедутся.
`Sport.#text` — `Soccer`;
`Tournament.#text`, `Team1/Team2.#text`, `Channels.Channel` — один канал
словарём или список; у канала `Name` и `Country`.

Всё в выдаче — трансляции: маркер эфира ставим каждой строке, как у
`liveonsat.com` и `skysports.com`. Параметр `se_date` сайт игнорирует и
отдаёт текущий день — ежедневному обходу этого достаточно.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "sporteventz.com"
TZ = "Europe/Kyiv"                      # client_tz_offset={KYIVOFF} в адресе

_BEGIN = re.compile(r"(\d{1,2}) (\w+) (\d{4}) (\d{1,2}):(\d{2})")
_MONTHS = {m: i for i, m in enumerate(
    ("January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"), start=1)}
_OFFSET = re.compile(r"client_tz_offset=%2B(\d{2})")


def _channels(rec: dict):
    node = (rec.get("Channels") or {}).get("Channel")
    if isinstance(node, dict):
        node = [node]
    seen = set()
    for ch in node or []:
        name = " ".join((ch.get("Name") or "").split())
        if name and name not in seen:
            seen.add(name)
            yield name, (ch.get("Country") or "")


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    start = html.find("{")
    if start < 0:
        return []
    try:
        data = json.loads(html[start:html.rfind("}") + 1])
    except ValueError:
        return []
    m = _OFFSET.search(url or "")
    # пояс — из адреса запроса (каким попросили, таким сайт и показал);
    # адреса без смещения — старые пробы: считаем киевским по календарю
    zone = timezone(timedelta(hours=int(m.group(1)))) if m \
        else ZoneInfo("Europe/Kyiv")

    out: list[Program] = []
    for rec in data.get("Records") or []:
        b = _BEGIN.search(rec.get("Begin") or "")
        month = _MONTHS.get(b.group(2)) if b else None
        if not b or not month:
            continue
        begin = datetime(int(b.group(3)), month, int(b.group(1)),
                         int(b.group(4)), int(b.group(5)), tzinfo=zone)
        home = " ".join(((rec.get("Team1") or {}).get("#text") or "").split())
        away = " ".join(((rec.get("Team2") or {}).get("#text") or "").split())
        if not home or not away:
            continue
        league = ((rec.get("Tournament") or {}).get("#text") or "").strip()
        sport = ((rec.get("Sport") or {}).get("#text") or "").strip()
        for name, country in _channels(rec):
            out.append(Program(
                channel_raw=name, title=f"{home} - {away}",
                start=begin,
                raw_time=f"{begin.hour:02d}:{begin.minute:02d}",
                league_raw=league[:120],
                sport_raw=sport,
                live_raw="live",
                match_raw=f"{home} - {away}",
                source_url=url,
                extra={"day": begin.date().isoformat(), "country": country},
            ))
    return out

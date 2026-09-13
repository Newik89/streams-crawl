# -*- coding: utf-8 -*-
"""epg.cyta.com.cy — Кипр, телегид оператора Cyta. Готовый список трансляций.

Страница `/tv-guide/en` — приложение на Angular, в HTML пусто. Адрес данных
нашёлся в бандле `main.<хеш>.js` (приём 2 из скилла): база
`https://epg.cyta.com.cy/api/` и три ручки —

    mediacatalog/fetchLiveSports?language=en&offset=0&count=200
    mediacatalog/fetchEpg?startTimeEpoch=…&endTimeEpoch=…&channelIds=…
    mediacatalog/fetchChannels?language=en

Берём первую: это не сетка канала, а **сразу список спортивных трансляций**
на неделю вперёд, с турниром и списком каналов у каждой. Один запрос за
обход — источник заведён сеткой.

    {"liveSportsEpgs": [{"date": "2026-09-01T00:00:00",
      "liveSportEvents": [{"name": "PARMA - CREMONESE (Z)",
        "programEvent": "COPPA ITALIA 2026-27",
        "startTime": "2026-09-01T19:00:00+03:00",
        "channels": [{"name": "Cytavision Sports4 HD"}, …]}]}]}

Особенности:

* `(Z)` — греческое ζωντανά, `(L)` — live; других хвостов в ответе нет, и
  ручка по смыслу отдаёт только прямые эфиры. Хвост снимаем и ставим маркер;
* один матч идёт на нескольких каналах — строка на каждый канал;
* пары каналов `Cytavision Sports6 HD` и `Cytavision Sports6 HD Real Time`
  — это один и тот же канал (второй — «сдвиг в реальном времени»), поэтому
  хвост `Real Time` снимаем и повтор не заводим;
* дефис в паре бывает без пробела слева (`SASSUOLO- FROSINONE`).
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime

from . import Program, register

DOMAIN = "epg.cyta.com.cy"
TZ = "Asia/Nicosia"

#: `ΧΩΡΙΣ ΠΑΡΩΠΙΔΕΣ (66η …) (Z)` — снимаем только хвостовую пометку эфира
_MARK = re.compile(r"\s*\(([ZL])\)\s*$")
_DASH = re.compile(r"\s+-\s*|\s*-\s+")
#: хвост с датой в имени матча: `Toulouse - Lille 3/9/26`
_TAIL_DATE = re.compile(r"\s+\d{1,2}/\d{1,2}/\d{2,4}\s*$")


def _pair(name: str) -> str:
    """Пара команд: дефис с пробелом хотя бы с одной стороны. Голый дефис
    внутри слова не трогаем — `SAINT-ETIENNE` должен остаться целым."""
    parts = _DASH.split(name, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return f"{parts[0].strip()} - {parts[1].strip()}"
    return " "


def _channel(name: str) -> str:
    return re.sub(r"\s*Real\s*Time\s*$", "", name.replace("\xa0", " ")).strip()


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = json.loads(html)
    except json.JSONDecodeError:
        return []

    out: list[Program] = []
    for block in data.get("liveSportsEpgs") or []:
        for event in block.get("liveSportEvents") or []:
            name = (event.get("name") or "").strip()
            stamp = event.get("startTime") or ""
            if not name or not stamp:
                continue
            mark = _MARK.search(name)
            title = _TAIL_DATE.sub("", _MARK.sub("", name).strip())
            try:
                start = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            # `programEvent` — обычно короткое имя турнира (`LA LIGA 2026-27`),
            # но у каналов Cablenet туда попадает рекламный абзац на двух
            # языках. Длинное в лигу не пишем — только в описание, оттуда
            # отсев всё равно возьмёт и вид спорта, и метку W/U19.
            event_name = (event.get("programEvent") or "").strip()
            league = event_name if len(event_name) <= 60 else ""
            seen: set[str] = set()
            for channel in event.get("channels") or []:
                clean = _channel(channel.get("name") or "")
                if not clean or clean in seen:
                    continue
                seen.add(clean)
                if channels and clean not in channels:
                    continue
                out.append(Program(
                    channel_raw=clean, title=title, start=start,
                    raw_time=f"{start:%H:%M}", league_raw=league,
                    description=event_name,
                    live_raw="ζωντανά" if mark else "",
                    match_raw=_pair(title), source_url=url,
                    extra={"day": start.date().isoformat()},
                ))
    return out


def list_channels(html: str) -> list[str]:
    """Каналы из ответа `fetchChannels` (или из списка трансляций)."""
    try:
        data = json.loads(html)
    except json.JSONDecodeError:
        return []
    names: list[str] = []
    for channel in data.get("channels") or []:
        clean = _channel(channel.get("name") or "")
        if clean and clean not in names:
            names.append(clean)
    if names:
        return names
    for block in data.get("liveSportsEpgs") or []:
        for event in block.get("liveSportEvents") or []:
            for channel in event.get("channels") or []:
                clean = _channel(channel.get("name") or "")
                if clean and clean not in names:
                    names.append(clean)
    return names

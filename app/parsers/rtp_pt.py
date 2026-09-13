# -*- coding: utf-8 -*-
"""rtp.pt — Португалия, общественное вещание RTP. Готовый JSON на канал и день.

Страница канала (`https://www.rtp.pt/rtp1/`) рисует сетку скриптом, но адрес
данных лежит прямо в её разметке (приём 1 из скилла):

    https://www.rtp.pt/EPG/json/rtp-channels-page/list-grid/tv/{id}/{YYYY-MM-DD}

Ответ — один канал за один день, разложенный по частям суток:

    {"_info": {"name": "RTP1", "timeZone": "lis"},
     "result": {"morning": [...], "afternoon": [...], "evening": [...],
       где элемент = {"date": "2026-09-01 06:00:00", "name": "Bom Dia Portugal",
                      "description": "…",
                      "symbols": [{"symbol_description": "Direto"}, …]}}}

Пометки честные: `Direto` — прямой эфир, `Repetição` — повтор; оба слова уже
есть в `data/markers.json`. Дату берём из самой записи, а не из адреса.

Номера каналов не подряд: `1` — RTP1, `3` — RTP Açores, а `2` отвечает
`HTTP 500`. Остальные номера ещё не проверены (`ОТЛОЖЕНО.md`).

Имена и описания приходят с HTML-сущностями (`RTP A&ccedil;ores`) — их
разворачиваем, иначе название канала не совпадёт со списком в базе.
"""

from __future__ import annotations

import html as _html
import json
import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "rtp.pt"
TZ = "Europe/Lisbon"

_STAMP = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})")


def _clean(text: str) -> str:
    return _html.unescape(text or "").strip()


def _pair(text: str) -> str:
    for sep in (" x ", " X ", " - ", " – ", " vs "):
        home, s, away = text.partition(sep)
        if s and home.strip() and away.strip():
            return f"{home.strip()} - {away.strip()}"
    return " "


def _split(title: str) -> tuple[str, str]:
    """`Futebol: Benfica x Estoril` → (вид спорта/лига, пара)."""
    head, sep, rest = title.partition(":")
    if sep and _pair(rest).strip():
        return head.strip(), _pair(rest)
    return "", _pair(title)


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = json.loads(html)
    except json.JSONDecodeError:
        return []

    zone = ZoneInfo(tz or TZ)
    channel = _clean((data.get("_info") or {}).get("name") or "")
    if not channel or (channels and channel not in channels):
        return []

    out: list[Program] = []
    for part in (data.get("result") or {}).values():
        if not isinstance(part, list):
            continue
        for item in part:
            stamp = _STAMP.match(str(item.get("date") or ""))
            title = _clean(item.get("name") or "")
            if not stamp or not title:
                continue
            marks = [_clean(s.get("symbol_description") or "")
                     for s in item.get("symbols") or []]
            start = datetime(*(int(stamp.group(i)) for i in range(1, 6)),
                             tzinfo=zone)
            head, pair = _split(title)
            out.append(Program(
                channel_raw=channel, title=title, start=start,
                raw_time=f"{stamp.group(4)}:{stamp.group(5)}",
                description=" ".join([_clean(item.get("description") or "")]
                                     + marks),
                league_raw=head, sport_raw=head,
                live_raw=next((m for m in marks if m.casefold() == "direto"), ""),
                match_raw=pair, source_url=url,
                extra={"day": start.date().isoformat()},
            ))
    return out

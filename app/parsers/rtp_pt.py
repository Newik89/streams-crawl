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

Номера каналов не подряд и не совпадают с именем канала: `1` — RTP1,
`3` — RTP Açores, `4` — Madeira, `5` — Mundo, `6` — África, `7` — Notícias,
а **RTP2 отвечает по номеру 8** (номер `2` даёт `HTTP 500` — на него и
напоролась разведка, из-за чего канал год не собирался; верный номер берём
из разметки самой страницы канала, 22.09.2026).

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


def _pair(text: str) -> tuple[str, str]:
    """Пара и хвост-турнир: `Juventus x SL Benfica - UEFA Liga dos Campeões
    Feminina` → («Juventus - SL Benfica», «UEFA Liga dos Campeões Feminina»).

    Турнир RTP пишет ХВОСТОМ после имени гостей (поймано на женской Лиге
    чемпионов 22.09.2026). Раньше он прилипал к имени команды, и матч не
    сходился с эталоном. Отделяем только там, где пару разделило « x »/« vs »:
    если пара сама разделена « - », хвост резать нечем и незачем.
    """
    for sep in (" x ", " X ", " - ", " – ", " vs "):
        home, s, away = text.partition(sep)
        if not (s and home.strip() and away.strip()):
            continue
        tail = ""
        if sep not in (" - ", " – "):
            away, dash, rest = away.partition(" - ")
            if dash and away.strip() and rest.strip():
                tail = rest.strip()
            elif dash and not away.strip():
                away = rest          # « x  - »: имя пустое, хвост — это гости
        return f"{home.strip()} - {away.strip()}", tail
    return " ", ""


def _split(title: str) -> tuple[str, str, str]:
    """`Futebol: Benfica x Estoril - Taça` → (вид спорта, пара, турнир)."""
    head, sep, rest = title.partition(":")
    if sep:
        pair, tail = _pair(rest)
        if pair.strip():
            return head.strip(), pair, tail
    pair, tail = _pair(title)
    return "", pair, tail


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
            head, pair, tail = _split(title)
            out.append(Program(
                channel_raw=channel, title=title, start=start,
                raw_time=f"{stamp.group(4)}:{stamp.group(5)}",
                description=" ".join([_clean(item.get("description") or "")]
                                     + marks),
                # турнир из хвоста точнее вида спорта в начале строки; пол и
                # возраст конвейер берёт из всего заголовка, так что ` W` от
                # такой замены не теряется
                league_raw=tail or head, sport_raw=head,
                live_raw=next((m for m in marks if m.casefold() == "direto"), ""),
                match_raw=pair, source_url=url,
                extra={"day": start.date().isoformat()},
            ))
    return out

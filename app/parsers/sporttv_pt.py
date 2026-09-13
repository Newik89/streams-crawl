# -*- coding: utf-8 -*-
"""sporttv.pt — Португалия, уровень A (`__NUXT_DATA__`).

Один запрос на `sporttv.pt/guia` — и приходит сетка **8 каналов на 14 дней**
(1694 передачи). Данные лежат в сжатом виде: массив, где вместо значений
стоят номера его же элементов; разворачивает их `devalue.py`.

Передача узнаётся по полю `tipoEmissao` — так надёжнее, чем идти по
вложенности страницы. Поля:

    data       начало, UNIX-миллисекунды UTC (время абсолютное, до секунд)
    canal.nome SPORT.TV2
    descricao  MIDDLESBROUGH X WEST BROMWICH
    evento.nome                 EFL CHAMPIONSHIP - FUTEBOL
    modalidade.nomeModalidade   FUTEBOL
    tipoEmissao                 DIRETO | Recorded | Magazine | Long Summary …

**Ловушка сайта.** Превью `ANTEVISÃO PORTIMONENSE X LEIXÕES SC` идёт с
`tipoEmissao = DIRETO` в 09:29, а сам матч — в 09:49: те же команды, тот же
маркер. Одного `DIRETO` мало, спасает отсев по заголовку (`app/live.py`).

Время абсолютное, поэтому ни пояс источника, ни правило полуночи не нужны.
"""

from __future__ import annotations

from datetime import date as _date

from .. import daytime
from . import Program, devalue, register

DOMAIN = "sporttv.pt"
TZ = "Europe/Lisbon"


def _rows(html: str) -> list[dict]:
    flat = devalue.extract_payload(html)
    return devalue.rows_with(flat, "tipoEmissao") if flat else []


def list_channels(html: str) -> dict[str, str]:
    """Каналы сетки: `5422` → `SPORT.TV5`. Все восемь спортивные."""
    out: dict[str, str] = {}
    for row in _rows(html):
        channel = row.get("canal") or {}
        if channel.get("nome"):
            out.setdefault(str(channel.get("id")), channel["nome"])
    return out


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    """`day` — оставить только эти сутки (по лиссабонскому времени);
    по умолчанию отдаём всё окно в 14 дней. `channels` — названия каналов
    (`SPORT.TV2`); по умолчанию все восемь, они и так все спортивные."""
    zone = tz or TZ
    out = []
    for row in _rows(html):
        start = daytime.from_unix_ms(row.get("data"))
        if day is not None:
            local = start.astimezone(daytime.ZoneInfo(zone)) if start else None
            if local is None or local.date() != day:
                continue
        channel = (row.get("canal") or {}).get("nome") or ""
        if channels and channel not in channels:
            continue
        title = (row.get("descricao") or "").strip()
        league = ((row.get("evento") or {}).get("nome") or "").strip()
        sport = ((row.get("modalidade") or {}).get("nomeModalidade") or "").strip()
        kind = (row.get("tipoEmissao") or "").strip()
        out.append(Program(
            channel_raw=channel, title=title, start=start,
            raw_time=start.astimezone(daytime.ZoneInfo(zone)).strftime("%H:%M")
            if start else "",
            description=f"{league} {sport}".strip(), league_raw=league,
            sport_raw=sport, live_raw=kind, match_raw=title, source_url=url,
            extra={"id_epg": row.get("id_epg"), "duracao": row.get("duracao"),
                   "tipoEmissao": kind},
        ))
    return out

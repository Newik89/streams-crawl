# -*- coding: utf-8 -*-
"""allente.no — Норвегия, уровень A (чистый JSON с api-адреса).

Дневная сетка: `api/epg/refetch-epg-data?Start={ГГГГ-ММ-ДД}&Genre=Sport` —
один запрос на день, в ответе все каналы со спортивными передачами
(проба 31.08: 15–19 каналов, ~140 передач; без фильтра — 119 каналов).
Шаблон вывел агент из их `tvGuide.js`, живьём подтверждено: `Start=`
работает и на завтра.

Структура: `channels[{name, programs[{title, eventStart, eventEnd,
genres, shortDescription}]}]`. Время — ISO с поясом (приходит в UTC).
Заголовок матча: `LaLiga EA Sports: Celta - Athletic` — лига до двоеточия,
пара после. Жанры: `["Sport", "Fotball"]` — второй и есть вид спорта.

**Флага прямого эфира нет вообще** (слово «Direkte» в данных — почти
только имя канала `TV 2 Direkte`). Признак повтора один: та же пара уже
показана раньше (Осасуна — Хетафе: 17:25 — сам матч, 21:30 и 22:10 —
записи). Правило то же, что у `trtspor`: маркер `direkte` получает только
самый ранний показ пары, поздние (и перевёрнутые) идут записью. Одиночный
повтор вчерашнего матча этим не ловится — цена источника без флага.
"""

from __future__ import annotations

import json
from datetime import date as _date, datetime

from . import Program, register

DOMAIN = "allente.no"
TZ = "Europe/Oslo"


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = json.loads(html)
    except ValueError:
        return []

    out: list[Program] = []
    for channel in data.get("channels") or []:
        block_name = (channel.get("name") or "").strip()
        for item in channel.get("programs") or []:
            # Имя блока у Allente иногда не то: 01.09 блок назывался
            # `Sky News`, а внутри у всех передач стояло `V sport 2 HD` — и
            # английский футбол в ленте оказывался на новостном канале.
            # Верим полю самой передачи, имя блока — только запасное.
            name = (item.get("channelName") or "").strip() or block_name
            if not name or (channels and name not in channels):
                continue
            title = (item.get("title") or "").strip()
            raw = (item.get("eventStart") or "").strip()
            if not title or not raw:
                continue
            try:
                start = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            league, _, tail = title.partition(":")
            tail = tail.strip()
            genres = [g for g in (item.get("genres") or []) if g]
            sport = next((g for g in genres if g.lower() != "sport"), "")
            out.append(Program(
                channel_raw=name, title=title, start=start,
                raw_time=raw[11:16],
                description=(item.get("shortDescription") or "")[:300],
                league_raw=league.strip() if tail else "",
                sport_raw=sport,
                live_raw="direkte",          # уточняется ниже по повторам
                match_raw=tail if " - " in tail else " ",
                source_url=url,
                extra={"day": raw[:10], "genres": genres},
            ))

    # Повторы: маркер остаётся только у самого раннего показа пары,
    # порядок команд не важен (запись часто идёт с перевёрнутой парой).
    def _pair(p: Program):
        if " - " not in p.match_raw:
            return None
        return tuple(sorted(" ".join(s.lower().split())
                            for s in p.match_raw.split(" - ", 1)))

    first: dict[tuple, datetime] = {}
    for p in out:
        pair = _pair(p)
        if pair is not None and (pair not in first or p.start < first[pair]):
            first[pair] = p.start
    for p in out:
        pair = _pair(p)
        if pair is None or p.start > first[pair]:
            p.live_raw = ""
            if pair is not None:
                p.extra["repeat_guess"] = True
    return out

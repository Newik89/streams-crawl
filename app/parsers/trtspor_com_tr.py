# -*- coding: utf-8 -*-
"""trtspor.com.tr — Турция, уровень A (`__NEXT_DATA__` в странице).

Одна страница `/yayin-akisi/trt-spor` отдаёт сразу три спортивных канала
(TRT SPOR, TRT SPOR YILDIZ, Tabii Spor) на ~3 дня — источник-«сетка»,
один запрос на всё.

Путь в JSON: `props.pageProps.data.rows[].content.epg[]` →
`{date, tvChannels[{title, slug, past[], current{}, upcoming[]}]}`.
У записи: `title`, `starttime`/`endtime`, `isRepeat`, `synopsis`. Время
пишется с «Z», но оно МЕСТНОЕ стамбульское, не UTC (сверено с эталоном
06.10: «20:30Z» EuroCup Bourg — Tofaş = 20:30 по Киеву, а не 23:30).
В `pageComponents` те же данные второй раз — копии отсекаются по (канал,
время, заголовок). К 06.10 сайт перенёс сетку целиком в `pageComponents`, а
имя канала у дня убрал (осталось в `content.channels` по `slug`) — разбор
давал 0 строк при «расписание есть»; теперь блок `content` с `epg` ищется
по всему дереву (`_contents`).

**Признак эфира.** Поле `livestream_access` — мусор (false у всех 418,
капкан как `/dirette/` у raiplay). Честное здесь — `isRepeat`: у повторов
true. «Не повтор» переводим в маркер `canlı`; студийные передачи без пары
команд отсев режет сам. Записи матчей турки помечают `isRepeat: true`
(46 шт. в копии) — на этом и держимся.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "trtspor.com.tr"
TZ = "Europe/Istanbul"

# Заголовок матча: `<лига> KARŞILAŞMASI <хозяева> - <гости>` («карşılaşма» —
# «встреча»). До слова — лига, после — пара. Без него пары в заголовке нет.
_MATCH_SPLIT = re.compile(r"karşılaşmas[ıi]", re.I)

# Номер тура прилипает к паре: `5.HAFTA  BANDIRMA SPOR - ...` («hafta» —
# «неделя/тур»). К имени команды он не относится — срезаем.
_HAFTA = re.compile(r"^\d+\.\s*HAFTA\s+", re.I)


def _items(channel: dict):
    for bucket in ("past", "current", "upcoming"):
        value = channel.get(bucket)
        if isinstance(value, dict):
            yield value
        elif isinstance(value, list):
            yield from value


def _contents(node):
    """Все блоки `content` с сеткой (`epg`) — где бы они ни лежали.

    До октября сетка была в `pageProps.data.rows[]`, к 06.10 сайт перенёс её
    в `pageProps.pageComponents[…].rows[].data.content` (`data` остался с
    одной шапкой) — и разбор молча отдавал 0 строк при «расписание есть»
    (самопроверка `audit_run.py`, обход #205). Ищем по всему дереву: копии
    одной передачи в двух ветках отсекает `seen` ниже."""
    if isinstance(node, dict):
        content = node.get("content")
        if isinstance(content, dict) and isinstance(content.get("epg"), list):
            yield content
        for value in node.values():
            yield from _contents(value)
    elif isinstance(node, list):
        for value in node:
            yield from _contents(value)


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    node = HTMLParser(html).css_first("script#__NEXT_DATA__")
    if node is None:
        return []
    try:
        data = json.loads(node.text())
        page = data["props"]["pageProps"]
    except (ValueError, KeyError, TypeError):
        return []

    out: list[Program] = []
    seen: set[tuple] = set()
    for content in _contents(page):
        # имя канала у дня бывает пустым — тогда берём его по `slug` из
        # списка каналов того же блока (так с переносом 06.10)
        by_slug = {c.get("slug"): (c.get("title") or "").strip()
                   for c in content.get("channels") or [] if isinstance(c, dict)}
        for epg_day in content.get("epg") or []:
            for channel in epg_day.get("tvChannels") or []:
                name = (channel.get("title") or by_slug.get(channel.get("slug"))
                        or "").strip()
                if not name or (channels and name not in channels):
                    continue
                for item in _items(channel):
                    title = (item.get("title") or "").strip()
                    raw = (item.get("starttime") or "").strip()
                    if not title or not raw:
                        continue
                    key = (name, raw, title)
                    if key in seen:        # та же запись во втором блоке
                        continue
                    seen.add(key)
                    try:
                        # «Z» у сайта врёт: время МЕСТНОЕ (Стамбул). Сверено
                        # с эталоном flashscore 06.10: «20:30Z» Bourg — Tofaş
                        # = 20:30 Киева, «19:30Z» ÇBK Mersin — Fenerbahçe =
                        # 19:30 Киева; гимн «İstiklal Marşı» — в 06:58
                        start = datetime.fromisoformat(
                            raw.replace("Z", "")[:19]).replace(
                                tzinfo=ZoneInfo(tz or TZ))
                    except ValueError:
                        continue
                    m = _MATCH_SPLIT.search(title)
                    league = title[:m.start()].strip() if m else ""
                    tail = title[m.end():].strip(' "\t.:-–') if m else ""
                    tail = _HAFTA.sub("", tail)
                    out.append(Program(
                        channel_raw=name, title=title, start=start,
                        raw_time=raw[11:16],
                        description=(item.get("synopsis") or "")[:300],
                        league_raw=league,
                        live_raw="" if item.get("isRepeat") else "canlı",
                        match_raw=tail if " - " in tail else " ",
                        source_url=url,
                        extra={"isRepeat": bool(item.get("isRepeat")),
                               "day": raw[:10]},
                    ))

    # `isRepeat` честен только у прошедших показов: будущий повтор матча
    # (Фенербахче — Лион вечером и он же завтра днём) идёт без пометки.
    # Правило: та же пара уже стоит раньше в этой же выгрузке — значит,
    # поздние показы записи. Одновременный показ на двух каналах не трогаем.
    # Пара с переставленными командами — тоже повтор («BODO - NEC» через
    # сутки после «NEC - BODO»): ответные матчи так близко не ставят,
    # окно обхода — двое суток.
    def _pair(p: Program):
        if " - " not in p.match_raw:
            return None
        sides = [" ".join(s.lower().split())
                 for s in p.match_raw.split(" - ", 1)]
        return tuple(sorted(sides))

    first: dict[tuple, datetime] = {}
    for p in out:
        pair = _pair(p)
        if pair is None or p.start is None:
            continue
        if pair not in first or p.start < first[pair]:
            first[pair] = p.start
    for p in out:
        pair = _pair(p)
        if p.live_raw and pair is not None and p.start is not None \
                and p.start > first[pair]:
            p.live_raw = ""
            p.extra["repeat_guess"] = True
    return out

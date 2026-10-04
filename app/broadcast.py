# -*- coding: utf-8 -*-
"""Трансляция турнира без пары игроков (теннис).

Сайт часто показывает турнир целиком, не называя, кто играет: «ATP 500 Tokyo
- 1/4 Finale», «China Open - Beijing», «TÓQUIO 2026 - QUARTOS DE FINAL»,
«ATP 500: רבעי גמר - 2 משחקים». Разбор делит заголовок по тире и получает
«пару» из названия турнира и стадии: на витрине она стояла как «ATP 500
Tokyo vs 1/4 Finale», висела в «Names to fix» и портила долю игр без канона
(04.10: 48 из 84 таких «игр» — заголовки пяти сайтов).

Решение владельца 04.10: оставлять, показывать трансляцией турнира без «vs»;
назовёт сайт игроков — следующий сбор приносит матч с именами, а заголовок
уходит (`store.save_games` гасит его отметки, `store.schedule` прячет строку
без живых каналов).

Слова — `data/markers.json`, раздел `tournament`, пополняются без правки
кода. Достаточно слова в одной из сторон: у настоящей пары ни в одной
фамилии нет «ATP», «Open» или «Finale». Игру, которую узнал эталон
flashscore, заголовком не считаем никогда — это решает вызывающий.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .live import MARKERS_FILE, _flatten, _pattern, greek_plain

#: стадия дробью («1/4 Finale», «1/2 Finale B») и год турнира («TÓQUIO 2026»):
#: в словарь их не положить, а у игроков таких «слов» не бывает. Дробь пары
#: («Hijikata/Uesugi», «TBD/TBD») сюда не попадает — в ней нет цифр
_STAGE = re.compile(r"(?<![\w/])1/(?:2|4|8|16|32|64)(?![\w/])|(?<!\d)20\d\d(?!\d)")


@lru_cache(maxsize=4)
def _words(path: Path | None = None) -> re.Pattern | None:
    data = json.loads((path or MARKERS_FILE).read_text(encoding="utf-8"))
    return _pattern(_flatten(data.get("tournament")))


def _side(text: str) -> bool:
    text = greek_plain(text or "")
    if _STAGE.search(text):
        return True
    words = _words()
    return bool(words and words.search(text))


def is_title(sport: str, home: str, away: str) -> bool:
    """«Пара» — название турнира или стадии, а не игроки. Только теннис:
    там трансляция турнира без пары — обычная строка телепрограммы."""
    if (sport or "") != "T":
        return False
    return _side(home) or _side(away)


# ── один турнир с разных сайтов — одна строка ────────────────────────────────
# Каждый сайт зовёт трансляцию по-своему: «China Open - Beijing» (Ziggo), «ATP
# 500 - BEIJING» (Cytavision), «BEIJING 2026 - QUARTOS DE FINAL» (Sport TV),
# «ATP 500: רבעי גמר, טורניר בייג'ינג» (Sport 5) — по буквам они не сходятся, и
# один турнир лежал на витрине четырьмя строками. Общее у них — тур и город.
# Узнали оба — строка получает одно имя («ATP Beijing» + `SESSION`), и обычная
# склейка сводит сайты в одну строку со всеми каналами (владелец 04.10).
# Не узнали (нет города в словаре, два города в одном блоке, не понять,
# ATP это или WTA) — строка остаётся как была: лишняя строка лучше чужой.

#: вторая «сторона» сведённой трансляции. На витрину не выходит: вместо неё
#: показывается стадия, если сайт её назвал
SESSION = "tournament"

#: «ATP - SINGLES: Beijing (China), hard» и то же на языках эталона:
#: тур — до тире, город — между двоеточием и скобкой страны
_REF_LEAGUE = re.compile(r"^\s*(ATP|WTA|CHALLENGER)\b[^:]*:\s*([^(:]+?)\s*\(")
#: тур в заголовке сайта. «ATP500:» пишут слитно, «ATP CH 125» — челленджер
_CHALLENGER = re.compile(r"(?<![a-z])challenger(?![a-z])|(?<![a-z])ch\s?\d", re.I)
_WTA = re.compile(r"(?<![a-z])wta(?![a-z])", re.I)
_ATP = re.compile(r"(?<![a-z])atp(?![a-z])", re.I)
_STAGE_BY_FRACTION = (("Quarterfinals", re.compile(r"(?<![\w/])1/4(?![\w/])")),
                      ("Semifinals", re.compile(r"(?<![\w/])1/2(?![\w/])")))


def _city_of(league: str) -> tuple[str, str]:
    """(тур, город) из названия турнира эталона; не турнир тура — ("", "")."""
    m = _REF_LEAGUE.match(league or "")
    if not m:
        return "", ""
    tour = {"ATP": "ATP", "WTA": "WTA"}.get(m.group(1).upper(), "Challenger")
    # «Wuning 3», «Monastir 33» — номер турнира в городе, не часть имени
    city = re.sub(r"\s+\d+$", "", m.group(2)).strip()
    return tour, city


@lru_cache(maxsize=4)
def _dict_cities(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    data = json.loads((path or MARKERS_FILE).read_text(encoding="utf-8"))
    return {city: tuple(words) for city, words
            in (data.get("tournament_cities") or {}).items()
            if city != "_" and isinstance(words, list)}


def tournaments(reference: list | None = None) -> dict:
    """Что известно о городах турниров: словарь `tournament_cities` плюс
    эталон flashscore (английское имя и написания на его языках).
    Возвращает {"cities": {город: шаблон}, "tours": {город: {туры}}} —
    считается один раз на разбор и передаётся в `tournament`."""
    words: dict[str, set[str]] = {c: set(w) | {c.lower()}
                                  for c, w in _dict_cities().items()}
    tours: dict[str, set[str]] = {}
    for ref in reference or []:
        if not isinstance(ref, dict) or ref.get("sport") != "T":
            continue
        tour, city = _city_of(ref.get("league") or "")
        if not city:
            continue
        tours.setdefault(city, set()).add(tour)
        bag = words.setdefault(city, set())
        bag.add(city.lower())
        for local in (ref.get("leagues") or {}).values():
            _, local_city = _city_of(local or "")
            if local_city:
                bag.add(local_city.lower())
    return {"cities": {c: _pattern(w) for c, w in words.items()}, "tours": tours}


def tournament(text: str, known: dict) -> str:
    """Имя турнира для сведения («ATP Beijing») по заголовку сайта. Пусто —
    сводить нельзя: города нет в словаре и эталоне, в блоке два города или
    два тура («ATP 500 Tokyo & WTA 1000 + ATP 500 Peking»), либо тур не
    назван, а в городе в эту неделю играют и ATP, и WTA."""
    text = greek_plain(text or "")
    found = [city for city, pattern in known["cities"].items()
             if pattern and pattern.search(text)]
    if len(found) != 1:
        return ""
    city = found[0]
    if _CHALLENGER.search(text):
        tour = "Challenger"
    else:
        wta, atp = bool(_WTA.search(text)), bool(_ATP.search(text))
        if wta and atp:
            return ""
        tour = "WTA" if wta else "ATP" if atp else ""
    if not tour:
        here = known["tours"].get(city) or set()
        if len(here) != 1:
            return ""
        tour = next(iter(here))
    return f"{tour} {city}"


@lru_cache(maxsize=4)
def _stages(path: Path | None = None) -> tuple:
    data = json.loads((path or MARKERS_FILE).read_text(encoding="utf-8"))
    groups = (data.get("tournament") or {}).get("стадия") or {}
    # порядок важен: «quartos de final» и «1/2 Finale» — не финал
    return tuple((name, _pattern(groups.get(name) or []))
                 for name in ("Quarterfinals", "Semifinals", "Final"))


def stage(text: str) -> str:
    """Стадия словами витрины («Semifinals») по заголовку сайта; пусто —
    сайт стадию не назвал."""
    text = greek_plain(text or "")
    for name, pattern in _STAGE_BY_FRACTION:
        if pattern.search(text):
            return name
    for name, pattern in _stages():
        if pattern and pattern.search(text):
            return name
    return ""

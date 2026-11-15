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
from datetime import datetime
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


#: книга 138: с такого числа теннисных матчей эталон «богат» — по нему можно
#: судить, что турнира в эти дни НЕТ (тот же порог, что у фильтра повторов
#: без эталона в `scripts/parse_live.py`)
RICH = 40


def _name_parts(name: str) -> tuple[list[str], str]:
    """Двойное имя турнира в эталоне — «событие - город»: «Finals - Turin» →
    (["Finals"], "Turin"). Обычное имя («Beijing») → ([], "Beijing")."""
    parts = [p.strip() for p in (name or "").split(" - ") if p.strip()]
    if len(parts) > 1:
        return parts[:-1], parts[-1]
    return [], (name or "").strip()


def tournaments(reference: list | None = None) -> dict:
    """Что известно о турнирах: словарь `tournament_cities` плюс эталон
    flashscore (английское имя и написания на его языках). Считается один
    раз на разбор и передаётся в `key` / `tournament`. Возвращает:

      "cities"  {город: шаблон слов города};
      "events"  {город: шаблон слов события} — у двойных имён эталона
                («Finals - Turin»: событие «Finals», «Итоговый турнир»,
                «Turnaj mistrů»); город такого имени («Turin», «Torino»,
                «Турин») идёт в "cities" (книга 138);
      "tours"   {город: {туры}} — только турниры эталона;
      "starts"  {(тур, город): [начала матчей по Киеву]} — книга 138;
      "matches" сколько теннисных матчей в эталоне всего."""
    dict_cities = _dict_cities()
    words: dict[str, set[str]] = {c: set(w) | {c.lower()}
                                  for c, w in dict_cities.items()}
    events: dict[str, set[str]] = {}
    tours: dict[str, set[str]] = {}
    starts: dict[tuple[str, str], list[datetime]] = {}
    matches = 0
    for ref in reference or []:
        if not isinstance(ref, dict) or ref.get("sport") != "T":
            continue
        matches += 1
        tour, city = _city_of(ref.get("league") or "")
        if not city:
            continue
        tours.setdefault(city, set()).add(tour)
        try:
            starts.setdefault((tour, city), []).append(
                datetime.fromisoformat(ref.get("start_kyiv") or ""))
        except ValueError:
            pass
        bag = words.setdefault(city, set())
        event_bag = events.setdefault(city, set())
        local = [_city_of(x or "")[1] for x in (ref.get("leagues") or {}).values()]
        for name in [city] + [x for x in local if x]:
            bag.add(name.lower())
            event, place = _name_parts(name)
            if event:
                bag.add(place.lower())
                bag.update(dict_cities.get(place) or ())
                event_bag.update(x.lower() for x in event)
    return {"cities": {c: _pattern(w) for c, w in words.items()},
            "events": {c: _pattern(w) for c, w in events.items() if w},
            "tours": tours, "starts": starts, "matches": matches}


def _tour_in(text: str) -> str | None:
    """Тур, названный в тексте: «Challenger», «WTA» или «ATP»; "" — не
    назван; None — названы и ATP, и WTA сразу (сводить нельзя)."""
    if _CHALLENGER.search(text):
        return "Challenger"
    wta, atp = bool(_WTA.search(text)), bool(_ATP.search(text))
    if wta and atp:
        return None
    return "WTA" if wta else "ATP" if atp else ""


def key(text: str, known: dict) -> tuple[str, str]:
    """(тур, город) турнира по заголовку сайта; не узнан — ("", "").

    Правила по порядку:
      1. Названы и ATP, и WTA («ATP 500 Tokyo & WTA 1000 + ATP 500 Peking») —
         не сводим.
      2. Город ищется по словарю и эталону (`known["cities"]`).
      3. Города нет, а тур назван — ищется слово события из двойного имени
         эталона («Finals» у «Finals - Turin»), и только у турниров
         названного тура: «ATP Finals» → Турин, «WTA Finals» → свой город,
         а «Davis Cup Finals» без тура — ничей (книга 138).
      4. Нашлось несколько, тур назван — остаются турниры этого тура из
         эталона: город словаря и турнир эталона с тем же городом — одно.
      5. Остался ровно один — он; иначе не сводим: города нет, в блоке два
         города, либо не понять, какой из двух.
      6. Тур — названный в тексте; не назван — единственный тур этого
         города в эталоне (в городе играют и ATP, и WTA — не сводим)."""
    text = greek_plain(text or "")
    named = _tour_in(text)
    if named is None:                                                    # 1
        return "", ""
    tours = known.get("tours") or {}
    found = [city for city, pattern in known["cities"].items()          # 2
             if pattern and pattern.search(text)]
    if not found and named:                                              # 3
        found = [city for city, pattern in (known.get("events") or {}).items()
                 if pattern and pattern.search(text)
                 and named in (tours.get(city) or ())]
    if len(found) > 1 and named:                                         # 4
        found = [city for city in found if named in (tours.get(city) or ())]
    if len(found) != 1:                                                  # 5
        return "", ""
    city = found[0]
    tour = named
    if not tour:                                                         # 6
        here = tours.get(city) or set()
        if len(here) != 1:
            return "", ""
        tour = next(iter(here))
    return tour, city


def tournament(text: str, known: dict) -> str:
    """Имя турнира для сведения («ATP Beijing») по заголовку сайта. Пусто —
    сводить нельзя (правила — в `key`)."""
    tour, city = key(text, known)
    return f"{tour} {city}" if city else ""


# ── книга 138: турнир назван одним куском, пары нет вовсе ────────────────────
# Правило 04.10 выше берёт трансляцию турнира, когда заголовок делится по тире
# на «пару» («ATP 500 Tokyo - 1/4 Finale»). Заголовок одним куском («ATP FINALS
# 2026», «Tenis ATP Torino 2026», «Nitto ATP Finals: Торино») пары не даёт и
# отсеивался как «не видно пары команд»: на сборе 15.11 — 240 прямых эфиров на
# 20 сайтах (владелец 15.11: «теннис, если нет имён, попадает просто названием
# турнира — это уже было решено»). Сами правила — `pipeline.tournament_whole`,
# здесь — три вопроса, на которые они опираются.

@lru_cache(maxsize=4)
def _sport_words(path: Path | None = None) -> re.Pattern | None:
    """Слова самого вида спорта («tenis», «теннис», «τένις») — раздел
    `sport` → `T` → «вид спорта» того же `data/markers.json`."""
    data = json.loads((path or MARKERS_FILE).read_text(encoding="utf-8"))
    node = (data.get("sport") or {}).get("T") or {}
    return _pattern(_flatten(node.get("вид спорта")))


def names_tournament(text: str) -> bool:
    """В тексте назван турнир, а не один лишь вид спорта: кроме слова
    «теннис» есть слово тура или турнира («ATP», «Open», «Masters»), стадия
    или год. «Tenis» — нет; «Tenis ATP Torino 2026» — да."""
    text = greek_plain(text or "")
    sport = _sport_words()
    if sport:
        text = sport.sub(" ", text)
    return _side(text)


def played(tournament_key: tuple[str, str], known: dict) -> bool:
    """Турнир идёт: в эталоне есть хоть один его матч."""
    return bool((known.get("starts") or {}).get(tournament_key))


def starts_near(tournament_key: tuple[str, str], start: datetime | None,
                known: dict) -> bool:
    """Показ — эфир турнира: в эталоне есть матч этого турнира, который
    начинается рядом с началом показа. Окно то же, что у пар
    (`reference.LIVE_SHOW_BEFORE/AFTER`): матч начинается не раньше 15 минут
    до показа и не позже часа после него."""
    from .reference import LIVE_SHOW_AFTER, LIVE_SHOW_BEFORE
    if start is None:
        return False
    if start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    return any(-LIVE_SHOW_AFTER <= (begins - start) <= LIVE_SHOW_BEFORE
               for begins in (known.get("starts") or {}).get(tournament_key) or ())


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

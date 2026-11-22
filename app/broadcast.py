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
    # книга 149: строка со служебной второй стороной — трансляция турнира по
    # определению, какие бы слова ни стояли в названии («Billie Jean King
    # Cup» слов тура не несёт)
    if (away or "") == SESSION and (home or "").strip():
        return True
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


@lru_cache(maxsize=4)
def _dict_events(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Книга 142: слова события двойного имени («Finals») на языках наших
    сайтов, которых нет у эталона, — раздел `tournament_events` того же
    `data/markers.json`. Ключ — событие по-английски, как у flashscore."""
    data = json.loads((path or MARKERS_FILE).read_text(encoding="utf-8"))
    return {event: tuple(words) for event, words
            in (data.get("tournament_events") or {}).items()
            if event != "_" and isinstance(words, list)}


#: книга 142: раздел файла словаря (`data/dictionaries.json`) с городами
#: турниров, которые сервер выучил из эталона прошлых сборов
LEARNED_KEY = "tournament_cities"
DICTIONARIES_FILE = MARKERS_FILE.parent / "dictionaries.json"


def cities_of(reference: list | None) -> dict[str, dict]:
    """Книга 142: города турниров из эталона — что о них стоит запомнить.
    → {город: {"tours": [туры], "words": [написания на языках эталона]}}.
    Город — как у flashscore («Stockholm», «Finals - Turin»), слова — в
    нижнем регистре, без повторов, по алфавиту."""
    out: dict[str, dict] = {}
    for ref in reference or []:
        if not isinstance(ref, dict) or ref.get("sport") != "T":
            continue
        tour, city = _city_of(ref.get("league") or "")
        if not city:
            continue
        rec = out.setdefault(city, {"tours": set(), "words": set()})
        rec["tours"].add(tour)
        rec["words"].add(city.lower())
        for local in (ref.get("leagues") or {}).values():
            local_city = _city_of(local or "")[1]
            if local_city:
                rec["words"].add(local_city.lower())
    return {city: {"tours": sorted(rec["tours"]), "words": sorted(rec["words"])}
            for city, rec in sorted(out.items())}


def merge_cities(known: dict | None, fresh: dict | None) -> tuple[dict, int]:
    """Книга 142: дописать к выученным городам новые. Только добавляет —
    ни город, ни написание не пропадают. → (словарь, сколько новых городов)."""
    out = {city: {"tours": sorted(set(rec.get("tours") or [])),
                  "words": sorted(set(rec.get("words") or []))}
           for city, rec in (known or {}).items() if isinstance(rec, dict)}
    new = 0
    for city, rec in (fresh or {}).items():
        if not isinstance(rec, dict):
            continue
        if city not in out:
            new += 1
            out[city] = {"tours": [], "words": []}
        out[city] = {"tours": sorted(set(out[city]["tours"]) | set(rec.get("tours") or [])),
                     "words": sorted(set(out[city]["words"]) | set(rec.get("words") or []))}
    return dict(sorted(out.items())), new


_LEARNED: dict | None = None


def learned_cities(path: Path | None = None) -> dict[str, dict]:
    """Книга 142: города, выученные из эталона прошлых сборов, — раздел
    `LEARNED_KEY` файла словаря. Файла или раздела нет, файл битый — пусто:
    тогда о городе знают только словарь `markers.json` и эталон этого сбора."""
    global _LEARNED
    if path is None and _LEARNED is not None:
        return _LEARNED
    try:
        data = json.loads((path or DICTIONARIES_FILE).read_text(encoding="utf-8")).get(LEARNED_KEY)
    except (OSError, ValueError, AttributeError):
        data = None
    out = {city: rec for city, rec in (data or {}).items()
           if isinstance(rec, dict)} if isinstance(data, dict) else {}
    if path is None:
        _LEARNED = out
    return out


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


def _spellings(word: str) -> set[str]:
    """Книга 142: слово города или события и то же слово с дефисом вместо
    пробела и наоборот — «индиан-уэллс» у сайта и «индиан уэллс» у эталона
    одно и то же («hong kong» и «hong-kong», «monte carlo» и «monte-carlo»)."""
    word = " ".join((word or "").lower().split())
    return {word, word.replace("-", " "), word.replace(" ", "-")} - {""}


def tournaments(reference: list | None = None, learned: dict | None = None) -> dict:
    """Что известно о турнирах: словарь `tournament_cities`, города,
    выученные из эталона прошлых сборов (`learned`; None — из файла словаря,
    `learned_cities`), и эталон flashscore этого сбора (английское имя и
    написания на его языках). Считается один раз на разбор и передаётся в
    `key` / `tournament`. Возвращает:

      "cities"  {город: шаблон слов города};
      "events"  {город: шаблон слов события} — у двойных имён эталона
                («Finals - Turin»: событие «Finals», «Итоговый турнир»,
                «Turnaj mistrů»); город такого имени («Turin», «Torino»,
                «Турин») идёт в "cities" (книга 138);
      "tours"   {город: {туры}} — только турниры эталона;
      "starts"  {(тур, город): [начала матчей по Киеву]} — книга 138;
      "leagues" {(тур, город): название турнира у эталона целиком} — книга
                148: подпись лиги сведённой строки; одиночный разряд
                («SINGLES») главнее парного;
      "matches" сколько теннисных матчей в эталоне всего."""
    dict_cities, dict_events = _dict_cities(), _dict_events()
    words: dict[str, set[str]] = {}
    events: dict[str, set[str]] = {}

    def add(city: str, names) -> None:
        """Написания города: имя целиком; у двойного имени («событие - город»)
        город — отдельным словом, событие — в `events` (книга 138); к ним —
        слова словаря для города и для события (книга 142)."""
        bag = words.setdefault(city, set())
        event_bag = events.setdefault(city, set())
        for name in names:
            if not name:
                continue
            bag |= _spellings(name)
            event, place = _name_parts(name)
            if event:
                bag |= _spellings(place)
                for word in dict_cities.get(place) or ():
                    bag |= _spellings(word)
                for part in event:
                    event_bag |= _spellings(part)
                    for word in dict_events.get(part) or ():
                        event_bag |= _spellings(word)

    for city, extra in dict_cities.items():                # словарь владельца
        add(city, [city, *extra])
    if learned is None:
        learned = learned_cities()
    for city, rec in (learned or {}).items():              # выучено из эталона
        add(city, [city, *(rec.get("words") or [])])
    tours: dict[str, set[str]] = {}
    starts: dict[tuple[str, str], list[datetime]] = {}
    ref_leagues: dict[tuple[str, str], str] = {}
    matches = 0
    for ref in reference or []:                            # эталон этого сбора
        if not isinstance(ref, dict) or ref.get("sport") != "T":
            continue
        matches += 1
        tour, city = _city_of(ref.get("league") or "")
        if not city:
            continue
        tours.setdefault(city, set()).add(tour)
        league = (ref.get("league") or "").strip()
        if (tour, city) not in ref_leagues or (
                "SINGLES" in league.upper()
                and "SINGLES" not in ref_leagues[(tour, city)].upper()):
            ref_leagues[(tour, city)] = league
        try:
            starts.setdefault((tour, city), []).append(
                datetime.fromisoformat(ref.get("start_kyiv") or ""))
        except ValueError:
            pass
        add(city, [city] + [_city_of(x or "")[1] for x in (ref.get("leagues") or {}).values()])
    return {"cities": {c: _pattern(w) for c, w in words.items() if w},
            "events": {c: _pattern(w) for c, w in events.items() if w},
            "tours": tours, "starts": starts, "leagues": ref_leagues,
            "matches": matches}


def city(text: str, known: dict) -> str:
    """Книга 146: город турнира по заголовку БЕЗ оглядки на тур — для
    вопросов «идёт ли турнир» и «начинается ли матч рядом» (`city_played`,
    `city_starts_near`). Тур сайт и эталон зовут по-разному: «WTA 125
    Colina» у эталона — CHALLENGER WOMEN, а турниры Большого шлема идут
    сразу в двух турах и по `key` не узнаются вовсе. Правила:
      1. город ищется по словарю и эталону; города нет, а тур назван —
         слово события двойного имени у турниров этого тура (как в `key`);
      2. нашлось несколько — остаются турниры, которые идут сейчас (есть в
         эталоне): «Roland Garros … Paris» — это French Open из эталона, а
         не парижский турнир осени из словаря;
      3. остался ровно один — он; иначе пусто."""
    text = greek_plain(text or "")
    named = _tour_in(text)
    tours = known.get("tours") or {}
    found = [c for c, pattern in known["cities"].items() if pattern and pattern.search(text)]
    if not found and named:                                                   # 1
        found = [c for c, pattern in (known.get("events") or {}).items()
                 if pattern and pattern.search(text) and named in (tours.get(c) or ())]
    if len(found) > 1:                                                        # 2
        found = [c for c in found if tours.get(c)]
    return found[0] if len(found) == 1 else ""                                # 3


def _city_starts(city_name: str, known: dict) -> list:
    return [begins for (_tour, c), starts in (known.get("starts") or {}).items()
            if c == city_name for begins in starts]


def city_played(city_name: str, known: dict) -> bool:
    """Книга 146: турнир этого города идёт — в эталоне есть хоть один его
    матч, в любом туре."""
    return bool(city_name and _city_starts(city_name, known))


def city_starts_near(city_name: str, start: datetime | None, known: dict) -> bool:
    """Книга 146: рядом с показом начинается матч турнира этого города (в
    любом туре). Окно — как у `starts_near`."""
    from .reference import LIVE_SHOW_AFTER, LIVE_SHOW_BEFORE
    if start is None or not city_name:
        return False
    if start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    return any(-LIVE_SHOW_AFTER <= (begins - start) <= LIVE_SHOW_BEFORE
               for begins in _city_starts(city_name, known))


def covered(start: datetime | None, known: dict) -> bool:
    """Книга 146: показ лежит в днях, на которые у эталона уже есть теннисная
    сетка (не позже последнего начала матча в эталоне). Дальше эталон о
    турнире судить не может: сетку следующих дней ещё не опубликовали."""
    if start is None:
        return False
    if start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    last = max((begins for starts in (known.get("starts") or {}).values() for begins in starts),
               default=None)
    return last is not None and start <= last


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
    сводить нельзя (правила — в `key`). У двойного имени эталона тире
    убирается («Finals - Turin» → «ATP Finals Turin»): тире в имени стороны
    дальше читалось бы как граница пары (книга 138)."""
    tour, city = key(text, known)
    return f"{tour} {city}".replace(" - ", " ") if city else ""


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


@lru_cache(maxsize=4)
def _not_live_words(path: Path | None = None) -> re.Pattern | None:
    """Книга 163: слова повтора, обзора, жеребьёвки и студии в заголовке
    трансляции турнира — раздел `tournament_not_live` того же
    `data/markers.json`."""
    data = json.loads((path or MARKERS_FILE).read_text(encoding="utf-8"))
    return _pattern(_flatten(data.get("tournament_not_live")))


def not_live_title(text: str) -> str:
    """Книга 163: слово, по которому заголовок трансляции турнира — не эфир
    («ATP Finals: Redifusión», «Sorteo ATP Finals», «Sintesi», студия «La
    pista del Tenis»); пусто — такого слова нет. Только заголовок, рубрика и
    лига: описание сюда не давать."""
    words = _not_live_words()
    found = words.search(greek_plain(text or "")) if words else None
    return found.group(0) if found else ""


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


def show_stage(name: str, title: str, known: dict | None) -> str:
    """Книга 160: стадия ПОКАЗА сведённой трансляции `name` («ATP Finals
    Turin») по заголовку сайта `title`.

    Имя турнира само бывает словом стадии: «ATP Finals» читается как
    «Final». Раньше такую стадию не показывали никогда — и в день настоящего
    финала тоже («ATP FINALS 2026 - FINAL»). Правила:
      1. турнир с двойным именем эталона («Finals - Turin») — из заголовка
         вынимается слово события этого турнира («Finals», «ATP Finale»,
         «Turneul Campionilor», «итоговый турнир» — `known["events"]`),
         стадия ищется в остатке: «ATP FINALS 2026 - FINAL» → «Final»,
         «Nitto ATP Finals» → пусто. Каждое НАПИСАНИЕ вынимается один раз:
         сайт зовёт турнир и на двух языках сразу («Turneul Campionilor
         Tenis: ATP Finals Torino» — оба слова имя турнира, не финал), а
         повтор того же написания («ATP Finals: Finals») — уже стадия;
      2. слова события в заголовке не нашлось, а стадия заголовка та же,
         что даёт само имя турнира, — это имя турнира в незнакомом
         написании, стадии нет;
      3. иначе — стадия заголовка как есть (`stage`)."""
    plain = greek_plain(title or "")
    events = None
    for city, pattern in ((known or {}).get("events") or {}).items():
        if pattern and any(f"{tour} {city}".replace(" - ", " ") == name
                           for tour in ("ATP", "WTA", "Challenger")):
            events = pattern
            break
    if events is not None:
        seen: set[str] = set()

        def once(match) -> str:
            """Первое вхождение каждого написания — пробел, повтор — как был."""
            word = " ".join(match.group(0).lower().split())
            if word in seen:
                return match.group(0)
            seen.add(word)
            return " "

        rest = events.sub(once, plain)                                    # 1
        if seen:
            return stage(rest)
    found = stage(plain)
    if found and found == stage(name):                                    # 2
        return ""
    return found                                                          # 3


# ── книга 149: следующая игра командной встречи ──────────────────────────────
# Командный турнир (Кубок Билли Джин Кинг, Кубок Дэвиса) — встреча сборных из
# нескольких игр, часто на два дня. Сайт ставит в сетку каждую игру отдельной
# передачей с той же парой стран и пометкой прямого эфира. Эталон знает
# встречу одной записью — началом первого дня, и следующие передачи снимались
# как «матч уже сыгран» либо вставали второй строкой той же пары. Слово
# владельца 16.11: «если там тоже написана пометка Live — они показывают
# следующую игру: просто строкой с названием турнира на то время, которое
# указано на сайте». Сами правила — `scripts/parse_live.py`, `next_tie_games`.

#: «TEAMS - WOMEN: Billie Jean King Cup - World Group (World) - Play Offs»:
#: турнир — между двоеточием и первым « - »
_TEAM_LEAGUE = re.compile(r"^\s*TEAMS\b[^:]*:\s*(.+?)\s*(?:\s-\s.*)?$")


def team_tournament(league: str) -> str:
    """Книга 149: название командного теннисного турнира из названия лиги
    эталона («TEAMS - WOMEN: Billie Jean King Cup - World Group…» → «Billie
    Jean King Cup»). Не командный турнир — пусто."""
    m = _TEAM_LEAGUE.match(league or "")
    return m.group(1).strip() if m else ""


# ── книга 176: командный турнир без пары — одной строкой ─────────────────────
# Жалоба владельца 22.11: полуфинал Кубка Дэвиса 27.11 стоял на витрине семью
# строками — «Polufinale 1», «Davis Cup Finals 2026:», «Tennis: Coupe Davis
# 2026: Demi-finale: équipes à communiquer», «גביע דיוויס - גמר: חצי גמר»… Пары
# у полуфинала ещё нет, в эталоне его нет, а сведение по туру и городу (`key`)
# командный турнир не берёт: тура у него нет («Davis Cup Finals» без тура —
# ничей). Названия командных турниров на языках сайтов уже лежат в словаре
# лиг (`data/league_words.json`, книга 159) — по ним строка и получает одно
# имя: «Davis Cup» + `SESSION`, как следующая игра встречи (книга 149).

#: метка игры в `results/games.json`: имя игры — сведённое название турнира
#: (а не заголовок сайта); по ней заливка переименовывает прежнюю строку базы
MERGED = "сведена"
TEAM_FILE = MARKERS_FILE.parent / "league_words.json"
#: раздел словаря лиг: командные турниры, которые эталон зовёт без «TEAMS»
TEAM_KEY = "командный_теннис"


@lru_cache(maxsize=2)
def _team_words(path: Path | None = None) -> tuple:
    """((название турнира, лига словаря, шаблон написаний), …) из словаря лиг:
    фразы, чей перевод — командный теннисный турнир. Командный — перевод вида
    «TEAMS - MEN: Davis Cup» (`team_tournament`) либо название из раздела
    `TEAM_KEY` (United Cup, Laver Cup, Hopman Cup). Написания ищутся целыми
    словами, без регистра и греческих ударений; само английское название —
    тоже написание."""
    try:
        data = json.loads((path or TEAM_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    plain = {str(x).strip() for x in data.get(TEAM_KEY) or [] if str(x).strip()}
    spelled: dict[tuple[str, str], set[str]] = {(name, name): set() for name in plain}
    for phrase, english in (data.get("фразы") or {}).items():
        if not isinstance(phrase, str) or not isinstance(english, str):
            continue
        name = team_tournament(english) or (english if english in plain else "")
        if name and phrase.strip():
            spelled.setdefault((name, english), set()).add(phrase)
    out = []
    for (name, english), phrases in sorted(spelled.items()):
        words = {" ".join(greek_plain(p).lower().split()) for p in phrases | {name}}
        body = "|".join(re.escape(w).replace(r"\ ", r"\s+")
                        for w in sorted(words, key=len, reverse=True))
        out.append((name, english, re.compile(rf"(?<!\w)(?:{body})(?!\w)", re.I | re.U)))
    return tuple(out)


def no_pair(home: str, away: str) -> bool:
    """Книга 176, К0: пары в строке нет вовсе — вторая сторона служебная
    (`SESSION`) либо ОБЕ стороны — слова турнира или стадии («FINAL 8» —
    «MEIA-FINAL»). Одна сторона — страна или игрок («Ausztria» —
    «Spanyolország negyeddöntő», port.hu) — это показ матча: его сводит с
    матчем эталон, названием турнира такая строка не становится."""
    if (away or "") == SESSION:
        return bool((home or "").strip())
    return _side(home or "") and _side(away or "")


def team_show(text: str, reference: list | None = None) -> tuple[str, str]:
    """Книга 176: (название, лига) командного теннисного турнира, названного
    в заголовке сайта; не назван — ("", ""). Правила (К0 — `no_pair` —
    проверяет вызывающий: `parse_live`):
      К1. название ищется написаниями словаря лиг (`_team_words`): «Cupa
          Davis», «TAÇA DAVIS», «Coupe Davis», «גביע דיוויס» → «Davis Cup»;
          и английским названием из лиг эталона («TEAMS - …: X»), которого в
          словаре ещё нет;
      К2. названы два разных турнира — не сводим;
      К3. лига строки — лига этого турнира у эталона, если она у него одна
          («TEAMS - MEN: Davis Cup - World Group (World)»); эталон турнир не
          ведёт или зовёт двумя лигами — перевод словаря («TEAMS - MEN: Davis
          Cup»)."""
    text = greek_plain(text or "")
    ref_leagues: dict[str, set[str]] = {}
    for ref in reference or []:
        name = team_tournament(ref.get("league") or "") if ref.get("sport") == "T" else ""
        if name:
            ref_leagues.setdefault(name, set()).add(ref.get("league") or "")
    found = {name: english for name, english, pattern in _team_words()        # К1
             if pattern.search(text)}
    for name in ref_leagues:
        if name not in found and len(name) >= 6 \
                and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I):
            found[name] = ""
    if len(found) != 1:                                                       # К2
        return "", ""
    name, english = next(iter(found.items()))
    leagues = ref_leagues.get(name) or set()
    return name, (next(iter(leagues)) if len(leagues) == 1 else english)      # К3


#: порядок стадий: ранняя первой
_STAGE_ORDER = ("Quarterfinals", "Semifinals", "Final")


def shows_stage(name: str, titles: list, known: dict | None) -> str:
    """Книга 176: стадия сведённой трансляции `name` по заголовкам ВСЕХ её
    живых отметок. Раньше бралась стадия первой отметки, её назвавшей; у
    строки с десятью сайтами первым мог оказаться «Davis Cup Finals 2026:» —
    и полуфинал вышел бы «финалом». Правила:
      1. стадию каждого заголовка даёт `show_stage`;
      2. у командного турнира «Finals» сразу после его названия («Davis Cup
         Finals», «Billie Jean King Cup Finals») — имя финального турнира, а
         не стадия: из заголовка вынимается;
      3. сайты назвали разные стадии — берём самую раннюю (четвертьфинал
         раньше полуфинала, полуфинал раньше финала): слово «финал» входит в
         имена турниров («Final 8», «Finals»), слово ранней стадии — нет;
      4. никто не назвал — пусто."""
    own = next((pattern for team, _english, pattern in _team_words() if team == name), None)
    finals = re.compile(rf"(?:{own.pattern})\s+finals(?!\w)", re.I | re.U) if own else None
    found = set()
    for title in titles or []:
        title = greek_plain(title or "")
        if finals is not None:
            title = finals.sub(" ", title)                                   # 2
        found.add(show_stage(name, title, known))                            # 1
    return next((s for s in _STAGE_ORDER if s in found), "")                 # 3, 4

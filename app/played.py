# -*- coding: utf-8 -*-
"""Книга 180: память сыгранных матчей — повтор старше 60 часов.

Жалоба владельца 26.11: «на витрине начали появляться лишние игры». Среди них
повторы: tvarenasport.hr ставит «NAPOLI - TORINO» на 26.11 (матч сыгран
21.11), novasports.gr — «Βαλένθια - Βίρτους Μπολόνια» на 27.11 (сыгран 19.11).
Сайты запись не помечают, а правило повтора (`parse_live.played_before`)
видит эталон только текущего сбора — он начинается с сегодняшней полуночи, и
глубина правила 60 часов. Слово владельца 26.11 на «помнить сыгранные пары
неделю»: «Да, все три».

Правила:
  П1. Память — записи эталона, которыми подтверждены игры сборов
      (`remember`): матч, который шёл у наших сайтов. Живёт `DEPTH` (8 суток:
      неделя и сутки запаса — повтор ставят в тот же день недели), хранится в
      итоге сбора под ключом `KEY` и переходит из сбора в сбор; первые дни её
      дополняет посев `data/played_seed.json`.
  П2. Игра сбора — повтор, если эталон этого сбора её на это время НЕ
      подтвердил парой целиком, а в памяти есть матч той же пары, начавшийся
      раньше показа больше чем на `AFTER` (60 часов — до них судит
      `played_before`) и не больше чем на `DEPTH`. Мост «одна сторона»
      (`Reference.confirm`, правило 4) подтверждением не считается: «TORINO —
      NAPOLI» он сводил с «Juventus — Omonia» того же вечера.
  П3. «Та же пара» — пара сошлась ЦЕЛИКОМ (`Reference.replays`:
      `canon.SURE`, местные написания, любой порядок сторон). Вид спорта:
      сайт назвал его сам (`STATED` — слово на сайте, лига словаря, женский
      клуб, подсказка владельца) — запись памяти должна быть того же вида:
      футбольная «Αναγέννηση Καρδίτσας — Ολυμπιακός Β’» не повтор
      баскетбольного «AS Karditsas — Olympiacos». Буква поставлена догадкой
      — вид не спрашиваем (баскетбольная Евролига у novasports.gr стояла
      футболом).
  П3а. Сайт зовёт команду прозвищем или именем спонсора («Asvel — Armani»
      у sportklub.hr, эталон — «Lyon-Villeurbanne — Olimpia Milano»): пара
      сверяется ещё и именами словаря команд (`data/dictionaries.json`,
      «teams» — имя и синонимы, `by_dictionary`). Берутся только однозначные
      написания: «Lyon» словарь знает и за футбольным клубом, и за
      баскетбольным — такое не переводится. То же при записи в память (П1).
  П4. Не судим: трансляцию турнира без пары (`broadcast.SESSION`) и пару с
      неназванным соперником (`names.is_placeholder`).
  П5. Новая встреча тех же команд через несколько дней (серия, кубок и лига)
      стоит в эталоне на своё время — её подтверждает П2, повтором она не
      становится.
Предел: пара, которую сайт зовёт иначе, чем эталон, и которой нет и в словаре
команд, не узнаётся — пока словарь её не выучит.
"""

from __future__ import annotations

import json
from functools import lru_cache
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import broadcast, names
from .reference import REPEAT_DEPTH, Reference

KEY = "сыгранные"
SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "played_seed.json"
#: П3а: словарь команд — выгрузка базы сервера, едет в git
DICT_FILE = Path(__file__).resolve().parent.parent / "data" / "dictionaries.json"
#: П1: сколько живёт запись памяти
DEPTH = timedelta(days=8)
#: П2: раньше этого судит `parse_live.played_before`
AFTER = REPEAT_DEPTH
#: П2: мост `Reference.confirm` — не подтверждение пары
ONE_SIDE = "одна сторона"
#: П3: источники вида спорта, когда его назвал сам сайт (`pipeline.Row.sport_source`)
STATED = frozenset({"word", "league", "women", "hint"})
#: что от записи эталона нужно для сверки пары
FIELDS = ("sport", "home", "away", "league", "start_kyiv", "fs_id", "names")


def now_kyiv() -> datetime:
    """Сейчас по Киеву, без пояса — как время записей эталона."""
    return datetime.now(ZoneInfo("Europe/Kyiv")).replace(tzinfo=None)


def _start(entry: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(entry.get("start_kyiv") or "")
    except ValueError:
        return None


def _key(entry: dict) -> str:
    return entry.get("fs_id") or "|".join(str(entry.get(k) or "") for k in ("sport", "home", "away", "start_kyiv"))


def _plain(name: str) -> str:
    return " ".join((name or "").lower().split())


@lru_cache(maxsize=2)
def _dictionary(path: Path | None = None) -> dict:
    """П3а: написание команды → её имя в словаре команд. Только однозначные:
    написание, которое словарь знает за двумя командами, не переводится."""
    try:
        teams = json.loads((path or DICT_FILE).read_text(encoding="utf-8")).get("teams") or []
    except (OSError, ValueError, AttributeError):
        return {}
    seen: dict[str, set] = {}
    for team in teams:
        name = (team.get("name") or "").strip() if isinstance(team, dict) else ""
        if not name:
            continue
        for alias in [name, *(team.get("aliases") or [])]:
            if isinstance(alias, str) and alias.strip():
                seen.setdefault(_plain(alias), set()).add(name)
    return {alias: next(iter(found)) for alias, found in seen.items() if len(found) == 1}


def by_dictionary(name: str, path: Path | None = None) -> str:
    """П3а: имя команды по словарю; словарь написания не знает — как было."""
    return _dictionary(path).get(_plain(name), name)


def spellings(home: str, away: str) -> list[tuple[str, str]]:
    """П3а: пара как на сайте и пара именами словаря (если отличается)."""
    pairs = [(home, away)]
    known = (by_dictionary(home), by_dictionary(away))
    if known != (home, away):
        pairs.append(known)
    return pairs


def compact(entry: dict) -> dict:
    """Запись эталона для памяти: только поля сверки пары."""
    return {k: entry[k] for k in FIELDS if entry.get(k)}


def load(previous: dict | None, now: datetime | None = None, seed: Path | None = None) -> dict:
    """П1: память прошлого сбора и посев → {ключ: запись}, без просроченных."""
    now = now or now_kyiv()
    rows = list((previous or {}).get(KEY) or [])
    try:
        rows += json.loads((seed or SEED_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    memory: dict = {}
    for entry in rows:
        start = _start(entry) if isinstance(entry, dict) else None
        if start is not None and now - start <= DEPTH:
            memory.setdefault(_key(entry), compact(entry))
    return memory


def remember(memory: dict, games: list, judge: Reference | None) -> int:
    """П1: записи эталона, подтвердившие игры этого сбора, — в память.
    Возвращает число новых записей."""
    if judge is None:
        return 0
    added = 0
    for g in games:
        if g.away == broadcast.SESSION:
            continue
        found = next((c for c in (judge.confirm(home, away, g.start, g.sport or "")
                                  for home, away in spellings(g.home, g.away))    # П3а
                      if c is not None), None)
        if found is None:
            continue
        key = _key(found.entry)
        if key not in memory:
            memory[key] = compact(found.entry)
            added += 1
    return added


def dump(memory: dict, now: datetime | None = None) -> list:
    """Память для итога сбора: по времени, без просроченных."""
    now = now or now_kyiv()
    rows = [e for e in memory.values() if (_start(e) is not None and now - _start(e) <= DEPTH)]
    return sorted(rows, key=lambda e: (e.get("start_kyiv") or "", e.get("home") or ""))


def replay_of(home: str, away: str, start: datetime | None,
              played: Reference | None, judge: Reference | None,
              sport: str = "") -> dict | None:
    """П2–П5: запись памяти, повтором которой является показ; None — не
    повтор. `sport` — вид спорта, если его назвал сам сайт (П3)."""
    if played is None or not len(played) or start is None or not home or not away:
        return None
    if away == broadcast.SESSION or names.is_placeholder(home) or names.is_placeholder(away):
        return None                                                        # П4
    pairs = spellings(home, away)                                          # П3а
    for h, a in pairs:
        found = judge.confirm(h, a, start, sport) if judge is not None else None
        if found is not None and found.how != ONE_SIDE:
            return None                                                    # П2, П5
    when = start.replace(tzinfo=None)
    best, best_gap = None, None
    for h, a in pairs:
        for entry, kickoff in played.replays(h, a, sport):                 # П3
            gap = when - kickoff
            if AFTER < gap <= DEPTH and (best_gap is None or gap < best_gap):
                best, best_gap = entry, gap
    return best


def stated_sport(game) -> str:
    """П3: вид спорта игры, если хоть у одной её строки его назвал сам сайт
    (`STATED`); иначе пусто — буква поставлена догадкой."""
    for entry in getattr(game, "entries", None) or []:
        if getattr(entry.payload, "sport_source", "") in STATED:
            return game.sport or ""
    return ""


def drop_replays(games: list, memory: dict, judge: Reference | None) -> tuple[list, list]:
    """Снять показы матчей, сыгранных больше 60 часов назад (правила — в
    шапке). Возвращает (оставленные игры, [(снятая игра, запись памяти)])."""
    if not memory:
        return games, []
    played = Reference(list(memory.values()))
    kept, dropped = [], []
    for g in games:
        entry = replay_of(g.home, g.away, g.start, played, judge, stated_sport(g))
        if entry is None:
            kept.append(g)
        else:
            dropped.append((g, entry))
    return kept, dropped

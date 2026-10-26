# -*- coding: utf-8 -*-
"""Полная программа канала главнее чужой строки про этот канал (слово
владельца 26.10.2026, игра #7042, книга 085).

Повод: «PSG — Лион» перенесли с 25.10 21:45 на 26.10 21:30. ipko.tv (полная
программа каналов SuperSport) поставил матч на SuperSport 2, а на SuperSport
3 в 21:00 у него «Premier League Channel». Агрегатор livesoccertv.com так и
держал матч на SuperSport 3. Каждый сайт гасит только свои отметки
(`app/miss.py`), спор двух сайтов об одном канале никто не решал — и канал,
которого в эфире нет, горел на витрине живым.

Правила по порядку (после склейки, когда видно, какие сайты дали игру):

1. Канал узнаём по словарю каналов (`data/dictionaries.json` → «channels»:
   написание сайта → канал и страна): «SuperSport 3» у ipko, «SS3» у
   tring.al и «SuperSport 3 Digitalb» у livesoccertv — один канал. Не узнали
   — строку не судим.
2. ПОЛНАЯ СЕТКА сайта B на канале K в момент T: у B на этом канале за
   `GRID_BACK` до T (и до 10 мин после) не меньше `GRID_SHOWS` передач, без
   разрыва длиннее `GRID_GAP`, и последняя из них началась не раньше чем за
   `GRID_GAP` до T. Страница агрегатора (только матчи, через часы) — не
   сетка.
3. Строку сайта A «игра на канале K» снимаем, если:
   а) сайт B показывает ЭТУ ЖЕ игру (у склеенной игры есть его строки — на
      другом канале);
   б) у B полная сетка канала K в это время (правило 2);
   в) в сетке K у B в ±`NEAR` нет этой игры — ни строки игры, ни передачи с
      именем команды игры в заголовке;
   г) у самого A на канале K не полная сетка: две полные сетки спорят —
      это спор, а не ошибка агрегатора, не судим.
4. Игра, у которой не осталось строк, уходит целиком (на деле у неё всегда
   остаются строки сайта B).
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DICT_FILE = ROOT / "data" / "dictionaries.json"
KYIV = ZoneInfo("Europe/Kyiv")

#: сетку канала смотрим за столько до начала игры
GRID_BACK = timedelta(hours=6)
#: …и в этом окне у сайта не меньше стольких передач канала
GRID_SHOWS = 3
#: разрыв между соседними передачами сетки не длиннее этого
GRID_GAP = timedelta(hours=3)
#: игра «есть в сетке», если её строка или передача с её командой ближе этого
NEAR = timedelta(minutes=90)
#: слова, которые есть в именах многих команд — по ним «та же игра» не решаем
_COMMON = {"club", "city", "united", "real", "sport", "sporting", "athletic",
           "football", "futbol", "futboll", "league", "liga", "channel", "team",
           "women", "olympique", "dinamo", "dynamo", "atletico", "deportivo"}


def _bare(domain: str) -> str:
    return (domain or "").strip().lower().removeprefix("www.")


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _ts(when: datetime | None) -> float | None:
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=KYIV)
    return when.timestamp()


def load_map(path: Path | None = None) -> dict:
    """Словарь каналов (правило 1): (сайт, написание) → (канал, страна).
    Написание без сайта годится любому сайту, но только если имя канала
    однозначно (у «Nova Sport 1» две страны — такое не берём)."""
    try:
        data = json.loads((path or DICT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict = {}
    anywhere: dict = {}
    for row in data.get("channels") or []:
        key = (row.get("name") or "", row.get("country") or "")
        if not key[0]:
            continue
        alias = _norm(row.get("alias") or "")
        source = _bare(row.get("source") or "") or None
        if alias and source:
            out[(source, alias)] = key
        for plain in {alias, _norm(key[0])} - {""}:
            if source is None or plain == _norm(key[0]):
                anywhere.setdefault(plain, set()).add(key)
    for plain, keys in anywhere.items():
        if len(keys) == 1:
            out.setdefault((None, plain), next(iter(keys)))
    return out


def channel_key(cmap: dict, domain: str, raw: str):
    """Канал строки сайта по словарю (правило 1); не узнали — None."""
    raw = _norm(raw)
    return cmap.get((_bare(domain), raw)) or cmap.get((None, raw))


def _words(*names: str) -> set[str]:
    """Значимые слова имён команд — без ударений, от 4 букв, без общих."""
    out = set()
    for name in names:
        plain = unicodedata.normalize("NFKD", name or "")
        plain = "".join(ch for ch in plain if not unicodedata.combining(ch)).lower()
        out |= {w for w in re.findall(r"\w{4,}", plain) if w not in _COMMON}
    return out


#: названия-заглушки телегидов: передачи нет, сайт заполнил пустое место
_PLACEHOLDERS = re.compile(
    r"^(?:unknown show|no information|to be announced|tba|program|programet\b.*|"
    r"нет данных|нет информации)$", re.I)


def placeholder(title: str, key) -> bool:
    """Заглушка вместо передачи: «Unknown show», «Programet e TS4 HD» или
    само имя канала («Tring Sport 3 HD» у канала Tring Sport 3)."""
    plain = _norm(title)
    if not plain or _PLACEHOLDERS.match(plain):
        return True
    name = _norm((key or ("",))[0])
    return bool(name) and plain.startswith(name)


class Grids:
    """Передачи каждого сайта по каналам — из ВСЕХ разобранных страниц
    сбора (и матчи, и прочее): (сайт, канал) → [(время, заголовок)]."""

    def __init__(self, pages, cmap: dict):
        self.cmap = cmap
        self.shows: dict = {}
        for domain, programs in pages:
            for p in programs or []:
                ts = _ts(getattr(p, "start", None))
                key = channel_key(cmap, domain, getattr(p, "channel_raw", ""))
                if ts is None or key is None:
                    continue
                self.shows.setdefault((_bare(domain), key), set()).add(
                    (ts, getattr(p, "title", "") or ""))
        self.shows = {k: sorted(v) for k, v in self.shows.items()}

    def full(self, domain: str, key, ts: float) -> bool:
        """Правило 2: у сайта сплошная сетка канала к моменту `ts`.
        Заглушка — не сетка (сбор 26.10 20:08: у ipko каналы Tring Sport
        расписаны «Unknown show» каждый час или «Tring Sport 3 HD» каждые
        2 ч, и правило сняло настоящие матчи с сайта самого Tring): в окне
        должно быть не меньше двух разных названий, а передача в момент
        матча — не заглушка (`placeholder`)."""
        shows = self.shows.get((_bare(domain), key)) or []
        window = [(t, title) for t, title in shows
                  if ts - GRID_BACK.total_seconds() <= t <= ts + 600]
        if len(window) < GRID_SHOWS:
            return False
        if ts - window[-1][0] > GRID_GAP.total_seconds():
            return False
        gaps = [b[0] - a[0] for a, b in zip(window, window[1:])]
        if not all(g <= GRID_GAP.total_seconds() for g in gaps):
            return False
        if len({_norm(title) for _, title in window}) < 2:
            return False
        return not placeholder(window[-1][1], key)

    def mentions(self, domain: str, key, ts: float, words: set[str]) -> bool:
        """Правило 3в: в сетке канала у сайта рядом есть передача, где в
        заголовке стоит имя команды игры."""
        near = NEAR.total_seconds()
        for t, title in self.shows.get((_bare(domain), key)) or []:
            if abs(t - ts) <= near and _words(title) & words:
                return True
        return False


def same_match(games: list, reference: list | None) -> dict[int, int]:
    """Игры, которые эталон признал ОДНИМ матчем, — общий номер группы.
    На GitHub строки разных сайтов склеиваются не всегда («PARIS SAINT-
    GERMAIN — Olympique Lyon» у ipko и «PSG — Olympique Lyonnais» у
    livesoccertv легли двумя играми, #7042): их сводит только метка
    flashscore, как на сервере (`canon.align`, уверенные пары). Без эталона
    — каждая игра сама по себе."""
    group = {id(g): i for i, g in enumerate(games)}
    if not reference:
        return group
    from . import canon
    dicts = [{"home": g.home, "away": g.away, "sport": g.first.sport or "",
              "league": g.first.league or "",
              "start_kyiv": g.start.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M"),
              "_game": g} for g in games]
    by_fs: dict = {}
    for d, ref, _score in canon.align(dicts, reference).get("sure", []):
        fs = ref.get("fs_id")
        if fs:
            group[id(d["_game"])] = by_fs.setdefault(fs, group[id(d["_game"])])
    return group


def drop_contradicted(games: list, grids: Grids,
                      reference: list | None = None) -> tuple[list, list]:
    """Правила 3–4. Возвращает (игры, [(игра, снятая строка, сайт-сетка)]).
    `reference` — эталон сбора: игры одного матча эталона считаются одной
    игрой для правила 3а (`same_match`)."""
    cmap = grids.cmap
    group = same_match(games, reference)
    members: dict = {}
    for g in games:
        members.setdefault(group[id(g)], []).extend(g.entries)
    removed: list = []
    kept: list = []
    for game in games:
        entries = members[group[id(game)]]          # строки всех сайтов матча
        sites = {_bare(e.source) for e in entries}
        words = _words(*[n for e in entries for n in (e.home, e.away)])
        drop: dict = {}
        for e in game.entries:
            a = _bare(e.source)
            key = channel_key(cmap, e.source, e.channel)
            ts = _ts(e.start)
            if key is None or ts is None or grids.full(a, key, ts):     # 1, 3г
                continue
            for b in sorted(sites - {a}):                               # 3а
                if not grids.full(b, key, ts):                          # 3б
                    continue
                on_k = any(_bare(x.source) == b
                           and channel_key(cmap, x.source, x.channel) == key
                           for x in entries)
                if on_k or grids.mentions(b, key, ts, words):           # 3в
                    continue
                drop[id(e)] = b
                break
        removed += [(game, e, drop[id(e)]) for e in game.entries if id(e) in drop]
        game.entries = [e for e in game.entries if id(e) not in drop]
        if game.entries:                                                # 4
            kept.append(game)
    return kept, removed

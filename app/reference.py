# -*- coding: utf-8 -*-
"""Эталон flashscore как судья вида спорта (владелец 06.10.2026).

Эталон — расписание flashscore из того же обхода: футбол, баскетбол и теннис
на все дни окна, с английскими и местными написаниями команд. Если пара из
строки сайта стоит в эталоне в то же время — вид спорта известен точно, и
никакое слово на странице его не оспорит: «PSG - Le Mans» — футбол, хотя
«Le Mans» ещё и гонка (#4710).

Здесь только поиск: «какой вид спорта у этой пары в это время». Само решение
«наш вид или чужой» — в одном месте, `app/sport.py` → `Sports.decide`
(правило 2). Пару с записью эталона сравнивает `canon._pair_score` — та же
функция, которой проект закрепляет имена команд, с местными написаниями и
стеной по полу и возрасту.
"""

from __future__ import annotations

from datetime import datetime

from . import canon, names

#: С какого сходства пары эталон диктует вид спорта. 95 — «пара сошлась почти
#: точно», порог владельца от 02.10 (#4335/#4336: при меньшем сходстве
#: баскетбольный Еврокубок записывался футболом по одной похожей стороне).
REF_SURE = 95

#: Насколько время строки может отличаться от времени матча в эталоне.
#: Три часа, как у закрепления имён (`canon.WINDOW`): сетки ставят блок
#: раньше матча, а flashscore.mobi живёт в UTC+2.
REF_WINDOW = canon.WINDOW


def _words(name: str, cache: dict) -> frozenset:
    """Слова всех чтений имени, огрублённые так же, как при сравнении имён
    (`names._exo`, `names._rough`). Нужны только чтобы быстро отобрать
    кандидатов: пара, сошедшаяся на `REF_SURE`, обязана делить с записью
    эталона хотя бы по одному слову на каждой стороне."""
    got = cache.get(name)
    if got is None:
        got = frozenset(names._rough(names._exo(word))
                        for reading in names.readings(name)
                        for word in reading.split())
        cache[name] = got
    return got


class Reference:
    """Эталон, разложенный для быстрого вопроса «какой это вид спорта»."""

    def __init__(self, entries: list[dict] | None = None):
        self._entries: list[tuple[dict, datetime]] = []
        self._home: dict[str, set[int]] = {}      # слово хозяев → номера записей
        self._away: dict[str, set[int]] = {}      # слово гостей → номера записей
        self._cache: dict[str, frozenset] = {}
        for entry in entries or []:
            try:
                start = datetime.fromisoformat(entry.get("start_kyiv") or "")
            except ValueError:
                continue
            home, away = entry.get("home") or "", entry.get("away") or ""
            if not home or not away:
                continue
            number = len(self._entries)
            self._entries.append((entry, start))
            # английское написание и все местные: строка сайта может быть на
            # любом языке, и сравнивать её будут со «своим» написанием
            sides = [(home, away)]
            for pair in (entry.get("names") or {}).values():
                if isinstance(pair, (list, tuple)) and len(pair) == 2 \
                        and pair[0] and pair[1]:
                    sides.append((str(pair[0]), str(pair[1])))
            for h, a in sides:
                for word in _words(h, self._cache):
                    self._home.setdefault(word, set()).add(number)
                for word in _words(a, self._cache):
                    self._away.setdefault(word, set()).add(number)

    def __len__(self) -> int:
        return len(self._entries)

    def sport_of(self, home: str, away: str, start: datetime | None) -> str:
        """Буква вида спорта (`F`/`B`/`T`), если пара стоит в эталоне в окне
        `REF_WINDOW` вокруг `start` и сошлась на `REF_SURE`. Пусто — эталон
        пару не знает ЛИБО знает её сразу в двух видах спорта (футбольное и
        баскетбольное дерби одних клубов в один вечер): тогда он не судья."""
        if not self._entries or not home or not away or start is None:
            return ""
        start = start.replace(tzinfo=None)        # эталон — наивное киевское
        by_home: set[int] = set()
        for word in _words(home, self._cache):
            by_home |= self._home.get(word, set())
        if not by_home:
            return ""
        by_away: set[int] = set()
        for word in _words(away, self._cache):
            by_away |= self._away.get(word, set())
        game = {"home": home, "away": away}
        letters: set[str] = set()
        for number in by_home & by_away:
            entry, when = self._entries[number]
            if abs(start - when) > REF_WINDOW:
                continue
            if canon._pair_score(game, entry) >= REF_SURE:
                letters.add(entry.get("sport") or "F")
        return letters.pop() if len(letters) == 1 else ""

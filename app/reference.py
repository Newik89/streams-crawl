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

from collections import Counter
from datetime import datetime, timedelta

from . import canon, names

#: С какого сходства пары эталон диктует вид спорта. 95 — «пара сошлась почти
#: точно», порог владельца от 02.10 (#4335/#4336: при меньшем сходстве
#: баскетбольный Еврокубок записывался футболом по одной похожей стороне).
REF_SURE = 95

#: Насколько время строки может отличаться от времени матча в эталоне.
#: Три часа, как у закрепления имён (`canon.WINDOW`): сетки ставят блок
#: раньше матча, а flashscore.mobi живёт в UTC+2.
REF_WINDOW = canon.WINDOW

# ── «показ в час матча или нет» — общие пороги обхода и очереди ─────────────
# Фильтр повторов обхода (`scripts/parse_live.py: played_before`) и пересуд
# вопроса «вид спорта» (`app/sport_question.py`) судят по одним числам.

#: матч эталона в пределах ±3 ч от строки — строка показывает его вживую
#: (тот же допуск, что у сверки угаданного эфира с эталоном)
LIVE_NEAR = timedelta(hours=3)
#: насколько раньше строки должен был пройти матч, чтобы считать показ
#: повтором. Меньше — это тот же матч в своём окне (студия, разброс сеток)
REPEAT_AFTER = timedelta(hours=4)
#: как далеко в прошлое смотрим: канал крутит запись день-два, дальше уже
#: не повтор, а новый матч тех же команд
REPEAT_DEPTH = timedelta(hours=60)
#: время эталона — «заглушка тура», если у лиги в этот день столько матчей
#: ровно в одну минуту: WWIN liga BiH 10.10 — все 5 в 18:00, а Arena ставит
#: их на пт 18:00, сб 18:30, вс 16:00 и 18:30 (самопроверка #205, 06.10).
#: По такому времени «матч уже сыгран» не доказать
ROUND_SAME_TIME = 5


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
        self._teams: set[str] = set()     # чтения всех команд эталона
        #: (лига, время) → сколько матчей — для `round_placeholder`
        self._slots: Counter | None = None
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
                for name in (h, a):
                    self._teams.update(r for r in names.readings(name)
                                       if r.strip())
                for word in _words(h, self._cache):
                    self._home.setdefault(word, set()).add(number)
                for word in _words(a, self._cache):
                    self._away.setdefault(word, set()).add(number)

    def __len__(self) -> int:
        return len(self._entries)

    def knows_team(self, name: str) -> bool:
        """Эталон знает такую команду (в любой день окна): одно из чтений
        имени совпало с чтением команды эталона — английским или местным.
        Нужен правилу 3 `sport.Sports.decide`: «пара похожа на матч»."""
        return any(r in self._teams for r in names.readings(name or "")
                   if r.strip())

    def sport_of(self, home: str, away: str, start: datetime | None) -> str:
        """Буква вида спорта (`F`/`B`/`T`), если пара стоит в эталоне в окне
        `REF_WINDOW` вокруг `start` и сошлась на `REF_SURE`. Пусто — эталон
        пару не знает ЛИБО знает её сразу в двух видах спорта (футбольное и
        баскетбольное дерби одних клубов в один вечер): тогда он не судья."""
        if start is None:
            return ""
        start = start.replace(tzinfo=None)        # эталон — наивное киевское
        letters = {entry.get("sport") or "F"
                   for entry, when in self.pair_times(home, away)
                   if abs(start - when) <= REF_WINDOW}
        return letters.pop() if len(letters) == 1 else ""

    def pair_times(self, home: str, away: str) -> list[tuple[dict, datetime]]:
        """Все матчи эталона с этой парой (сходство ≥ `REF_SURE`, хозяева с
        хозяевами) — в любой день окна, по времени. Нужны, чтобы понять,
        показывает ли строка сам матч или его повтор (`app/sport_question`)."""
        if not self._entries or not home or not away:
            return []
        by_home: set[int] = set()
        for word in _words(home, self._cache):
            by_home |= self._home.get(word, set())
        if not by_home:
            return []
        by_away: set[int] = set()
        for word in _words(away, self._cache):
            by_away |= self._away.get(word, set())
        game = {"home": home, "away": away}
        found = [self._entries[number] for number in by_home & by_away
                 if canon._pair_score(game, self._entries[number][0])
                 >= REF_SURE]
        return sorted(found, key=lambda x: x[1])

    def round_placeholder(self, entry: dict, when: datetime) -> bool:
        """Время записи — «заглушка тура»: у её лиги в эту минуту не меньше
        `ROUND_SAME_TIME` матчей (flashscore ставит весь тур на одно время,
        пока лига не назначила его по матчам)."""
        league = entry.get("league") or ""
        if not league:
            return False
        if self._slots is None:
            self._slots = Counter((e.get("league") or "", t)
                                  for e, t in self._entries)
        return self._slots[(league, when)] >= ROUND_SAME_TIME

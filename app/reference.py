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

from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
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
#: …а у футбола — уже через 3 ч, ровно там, где кончается «в час матча»
#: (`LIVE_NEAR`): матч с добавленным временем, овертаймом и пенальти короче
#: трёх часов. С общими 4 ч между 3 и 4 ч жила дыра — строка там не была ни
#: эфиром, ни повтором: S Sport пометил «canlı» ночной показ Deportivo —
#: Levante 17.10 01:30 после матча 16.10 22:00, и скан даты завёл дубль
#: (разбор владельца 12.10). Баскетбол и теннис — общие 4 ч (теннис по
#: очереди корта уходит далеко от времени эталона)
REPEAT_AFTER_BY_SPORT = {"F": LIVE_NEAR}


def repeat_after(sport: str) -> timedelta:
    """Через сколько после начала матча эталона показ — уже повтор."""
    return REPEAT_AFTER_BY_SPORT.get(sport or "F", REPEAT_AFTER)
#: как далеко в прошлое смотрим: канал крутит запись день-два, дальше уже
#: не повтор, а новый матч тех же команд
REPEAT_DEPTH = timedelta(hours=60)
#: время эталона — «заглушка тура», если у лиги в этот день столько матчей
#: ровно в одну минуту: WWIN liga BiH 10.10 — все 5 в 18:00, а Arena ставит
#: их на пт 18:00, сб 18:30, вс 16:00 и 18:30 (самопроверка #205, 06.10).
#: По такому времени «матч уже сыгран» не доказать
ROUND_SAME_TIME = 5

# ── «не уверен — спроси эталон» (правило (в) починки №13, владелец 20.10) ──
#: показ — эфир матча, если матч начинается от `LIVE_SHOW_AFTER` ДО показа
#: до `LIVE_SHOW_BEFORE` ПОСЛЕ него: сетка ставит блок раньше матча (teleman
#: 18:55 при 19:00, бывает и за час), а показ сильно позже начала — запись.
#: Те же окна, что у проверки 13 самопроверки (`audit_run.SEEN_BEFORE/AFTER`)
LIVE_SHOW_BEFORE = timedelta(minutes=60)
LIVE_SHOW_AFTER = timedelta(minutes=15)
#: одна сторона пары узнана «твёрдо» — само имя эталона или его алиас
SIDE_SURE = 95
#: другая хотя бы «не спорит» буквами. Замер 20.10 (`names.similarity`):
#: чужие клубы дают 26–58 (Portimonense ~ Porto 58, Lens ~ Le Mans 50,
#: Barcelona ~ Lyon-Villeurbanne 46), обрезанное своё — 60 («1. FC Kaiser»
#: ~ Kaiserslautern), остальное своё — 90–100. Ниже 60 выручает только общее
#: слово (`_shares_word`)
SIDE_FLOOR = 60


@dataclass
class Confirmed:
    """Ответ эталона на «это эфир какого матча?» (`Reference.confirm`)."""
    entry: dict            # запись эталона
    start: datetime        # её начало (наивное киевское)
    how: str               # «пара» — сошлась целиком; «одна сторона» — мост
    swapped: bool = False  # пара сошлась в обратном порядке («гости at хозяева»)


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
        #: записи по времени — для окна эфира в `confirm`
        self._by_time: list[tuple[datetime, int]] | None = None
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
            # (пометки пола и возраста местных — уже наши, `canon.local_name`)
            sides = [(home, away)] + [(h, a) for _lang, h, a
                                      in canon.local_pairs(entry)]
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

    def confirm(self, home: str, away: str, start: datetime | None,
                sport: str = "") -> Confirmed | None:
        """«Не уверен — спроси эталон» (правило (в) починки самопроверки №13,
        владелец 20.10): показ пары `home — away` в `start` — это эфир какого
        матча эталона? Один ответ для всех, кто раньше решал по спискам
        сайтов: отсев без пометки эфира, пара, прочитанная догадкой
        (`live.split_candidates`), строка без вида спорта, сверка угаданного
        эфира в `parse_live`. Правила:

          1. матч начинается в окне эфира: от `LIVE_SHOW_AFTER` до показа до
             `LIVE_SHOW_BEFORE` после него;
          2. вид спорта, если назван, — тот же;
          3. пара сошлась целиком — `canon._pair_score` не ниже `canon.SURE`
             (с местными написаниями и стеной по полу и возрасту), в любом
             порядке сторон («гости at хозяева» — `swapped`) → «пара»; из
             нескольких таких — ближайший по времени. Но если та же пара в
             ±`REF_WINDOW` стоит в РАЗНЫХ видах спорта (футбольное и
             баскетбольное дерби одних клубов в один вечер) — эталон не
             судья, None (как `sport_of`): решает слово сайта;
          4. иначе одна сторона твёрдо (`SIDE_SURE`), другая не спорит —
             буквами (`SIDE_FLOOR`) или хотя бы одним общим словом от 4 букв
             с любым написанием эталона («ASVEL Villeurbanne» и
             «Lyon-Villeurbanne» дают буквами 26, но слово общее), стена по
             полу и возрасту та же, не теннис (там игрок в один день стоит и
             в одиночке, и в паре) — и такой матч в окне ОДИН: клуб не играет
             два матча в один час → «одна сторона».

        Ничего не сошлось — None: эталон пару не знает, строка решается как
        раньше."""
        if start is None or not self._entries or not home or not away:
            return None
        when = start.replace(tzinfo=None)         # эталон — наивное киевское
        # кандидаты — только записи, делящие слово с одной из сторон (индекс
        # слов всех языков): так вопрос дёшев и на тысячи строк
        pool: set[int] = set()
        for name in (home, away):
            for word in _words(name, self._cache):
                pool |= self._home.get(word, set())
                pool |= self._away.get(word, set())
        straight = {"home": home, "away": away, "sport": sport}
        swapped = {"home": away, "away": home, "sport": sport}
        whole: list[tuple[timedelta, bool, int, bool]] = []   # правило 3
        sided: list[tuple[bool, int]] = []                    # правило 4
        for number in pool:
            entry, kickoff = self._entries[number]
            gap = kickoff - when
            if abs(gap) > REF_WINDOW:
                continue
            letter = entry.get("sport") or "F"
            if sport and letter != sport:
                continue
            # окно эфира: матч начинается от 15 мин до показа до часа после
            inside = -LIVE_SHOW_AFTER <= gap <= LIVE_SHOW_BEFORE
            scores = (canon._pair_score(straight, entry),
                      canon._pair_score(swapped, entry))
            best = max(scores)
            turned = scores[1] > scores[0]
            if best >= canon.SURE:
                whole.append((abs(gap), turned, number, inside))
                continue
            if not inside or letter == "T":
                continue
            # порядок сторон для моста — по ТВЁРДОЙ стороне, а не по счёту
            # пары целиком: у «Sevilla — Real Clube» против «Sevilla — Real
            # Sociedad» пара даёт 33 прямо и 40 наоборот, и Sevilla (100)
            # терялась в обратном порядке (проверка 20.10)
            sides = ((canon._best_side(straight, entry), False, straight),
                     (canon._best_side(swapped, entry), True, swapped))
            side, turned, game = max(sides, key=lambda x: x[0])
            if side < SIDE_SURE:
                continue
            if canon._pair_score(game, entry) >= SIDE_FLOOR or (
                    canon._same_category(game, entry)
                    and self._shares_word(game, entry, number)):
                sided.append((turned, number))
        if whole:
            if len({self._entries[n][0].get("sport") or "F" for *_x, n, _i in whole}) > 1:
                return None               # та же пара в двух видах спорта
            inside_whole = [x for x in whole if x[3]]
            if not inside_whole:
                return None               # пара есть, но показ не в час матча
            _gap, turned, number, _i = min(inside_whole, key=lambda x: x[0])
            entry, kickoff = self._entries[number]
            return Confirmed(entry, kickoff, "пара", turned)
        if len(sided) == 1:
            turned, number = sided[0]
            entry, kickoff = self._entries[number]
            return Confirmed(entry, kickoff, "одна сторона", turned)
        return None

    def _shares_word(self, game: dict, entry: dict, number: int) -> bool:
        """Слабая сторона пары (та, что хуже сошлась с английским именем)
        делит с той же стороной записи `number` хотя бы одно слово от 4 букв —
        в любом написании эталона (индекс `_home`/`_away` хранит слова всех
        языков). Короткие слова («FC», «SK», «Al») общими не считаются."""
        home_score = names.similarity(game["home"], entry.get("home") or "")
        away_score = names.similarity(game["away"], entry.get("away") or "")
        weak, index = (("home", self._home) if home_score < away_score
                       else ("away", self._away))
        return any(number in index.get(word, ())
                   for word in _words(game[weak], self._cache) if len(word) >= 4)

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

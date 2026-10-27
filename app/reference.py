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
стеной по полу и возрасту. Одна щель в стене — правило 5 `confirm`: у
строки меток нет вовсе, а эталон в эту минуту знает пару только с меткой
(«Man City – Psg» ↔ «Manchester City U19 – PSG U19») — метка дописывается
из эталона (`MARKS_HOW`, слово владельца 24.10).
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import canon, names

#: номер выпуска в «имени команды» (книга 087, #8126): число от трёх цифр, но
#: не год основания или сезона (18xx–20xx): «Oni žive za fudbal ep. 252» —
#: передача, а «Como 1907», «Schalke 04», «Hannover 96» — команды
_EPISODE_NO = re.compile(r"(?<![\w.])(?!(?:18|19|20)\d\d(?!\d))\d{3,}(?![\w.])")

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

# ── «метки из эталона» (правило 5 `confirm`, слово владельца 24.10) ─────────
#: как `confirm` называет ответ «пара сошлась, если не смотреть на пол и
#: возраст эталона»: сайт пишет «Man City – Psg» без возраста, а эталон в
#: эту минуту знает только «Manchester City U19 – PSG U19». Раньше такая
#: строка упиралась в стену по полу и возрасту (`canon._pair_score` → 0),
#: эталон молчал, и фильтр обхода снимал эфир как запись (книга 003).
#: Владелец 24.10: «дописывать возраст из эталона» — потерянная метка хуже
#: лишней (правило проекта, как с W). Метка идёт в `Confirmed.marks`, и
#: `pipeline.classify` дописывает её к именам пары
MARKS_HOW = "метки из эталона"
#: то же для показа вне окна эфира (`Reference.late_marks`, 25.10): метка
#: дописывается, но эфиром матча показ не признаётся
LATE_MARKS_HOW = "метки из эталона, показ вне окна"


@dataclass
class Confirmed:
    """Ответ эталона на «это эфир какого матча?» (`Reference.confirm`)."""
    entry: dict            # запись эталона
    start: datetime        # её начало (наивное киевское)
    how: str               # «пара» — сошлась целиком; «одна сторона» — мост;
                           # `MARKS_HOW` — сошлась без пола и возраста эталона
    swapped: bool = False  # пара сошлась в обратном порядке («гости at хозяева»)
    marks: str = ""        # пометки записи, которых нет у строки («U19», «W»,
                           # «U17 W») — только при `how == MARKS_HOW`


def _strip_marks(name: str) -> str:
    """Имя без пометок пола и возраста: «Manchester City U19» → «Manchester
    City», «Poland W» → «Poland». Те же регулярки, что у `names.category`."""
    bare = names._WOMEN_RE.sub(" ", names._AGE_RE.sub(" ", name or ""))
    return " ".join(bare.split())


def _marks_of(name: str) -> list[str]:
    """Пометки пола и возраста имени («U19 W» → [«U19», «W»]). Второй состав
    («B») — не пол и не возраст: его правило 5 не трогает."""
    return names.category(name or "").split()


def _entry_marks(entry: dict) -> str:
    """Метка записи эталона, если она ОДНА И ТА ЖЕ у обеих команд («U19»,
    «W», «U17 W») и это не второй состав. Пусто — у записи меток нет, они
    разные («Chelsea U21 — Wycombe» в EFL Trophy) или среди них «B»."""
    дома = _marks_of(entry.get("home"))
    в_гостях = _marks_of(entry.get("away"))
    if not дома or дома != в_гостях or "B" in дома:
        return ""
    return " ".join(дома)


def _bare_entry(entry: dict) -> dict:
    """Запись эталона без пометок пола и возраста — и в английском, и в
    местных написаниях (те уже с нашими пометками, `canon.local_pairs`):
    «Italia W — Bielorussia W» (из «Italia D — Bielorussia D») → «Italia —
    Bielorussia». С ней `canon._pair_score` сравнивает строку без меток."""
    return dict(entry,
                home=_strip_marks(entry.get("home") or ""),
                away=_strip_marks(entry.get("away") or ""),
                names={lang: [_strip_marks(h), _strip_marks(a)]
                       for lang, h, a in canon.local_pairs(entry)})


def _words(name: str, cache: dict) -> frozenset:
    """Слова всех чтений имени, огрублённые так же, как при сравнении имён
    (`names._exo`, `names._rough`). Нужны только чтобы быстро отобрать
    кандидатов: пара, сошедшаяся на `REF_SURE`, обязана делить с записью
    эталона хотя бы по одному слову на каждой стороне."""
    got = cache.get(name)
    if got is None:
        words = {names._rough(names._exo(word))
                 for reading in names.readings(name)
                 for word in reading.split()}
        # иврит пишется без гласных: чтение «GOLDN STIIT» никогда не совпадёт
        # со словами «GOLDEN STATE» записи, хотя `names.similarity` даёт 100
        # (там сверяют и костяк согласных). Индекс хранит костяки слов всех
        # записей (`Reference.__init__`), ивритская строка ищет по ним — иначе
        # sport5 «גולדן סטייט — אטלנטה» не доходила до правил `confirm` вовсе
        # (25.10, матч WNBA)
        if names._HEBREW_RE.search(name):
            words |= {names._skeleton(w) for w in words}
        got = frozenset(w for w in words if w)
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
                for index, name in ((self._home, h), (self._away, a)):
                    for word in _words(name, self._cache):
                        index.setdefault(word, set()).add(number)
                        # костяк согласных — для ивритских строк (`_words`)
                        bones = names._skeleton(word)
                        if bones and bones != word:
                            index.setdefault(bones, set()).add(number)

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
             два матча в один час → «одна сторона»;
          5. «метки из эталона» (слово владельца 24.10, книга 003): у ОБЕИХ
             команд строки нет пометок пола и возраста, а правило 3 не
             сошлось только из-за стены по ним — сравниваем с записью БЕЗ
             её меток (`_bare_entry`, как `canon.align` HOW_AGED, плюс W):
             имена сходятся на `canon.SURE`, вид спорта тот же, окно эфира
             то же, метка у записи одна и та же у обеих команд (U19/U21/W…,
             `_entry_marks`), и такой кандидат в окне ОДИН → `MARKS_HOW`,
             метка в `Confirmed.marks`. Кандидат по правилу 3 главнее (есть
             взрослый матч той же пары — метку не гадаем); два кандидата с
             метками в одно время (U19 и U21) — None, не гадаем; правило 4
             после пятого: половина пары слабее целой.

          0. (книга 087) сторона с номером выпуска — не команда: «Oni žive za
             fudbal ep. 252» (`_EPISODE_NO`) → None;
          4а. (книга 087) у твёрдой стороны сайта есть слово, которого нет ни
             в одном написании команды эталона (`canon.odd_word`), — правило
             4 молчит: «Hajduk Čurug» — не «Hajduk».

        Ничего не сошлось — None: эталон пару не знает, строка решается как
        раньше."""
        if start is None or not self._entries or not home or not away:
            return None
        if _EPISODE_NO.search(home) or _EPISODE_NO.search(away):
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
        # правило 5 только для строки без пометок пола и возраста у ОБЕИХ
        # команд: «Man City – Psg» — да, «Chelsea U21 – Wycombe» — нет
        plain = not _marks_of(home) and not _marks_of(away)
        whole: list[tuple[timedelta, bool, int, bool]] = []   # правило 3
        sided: list[tuple[bool, int]] = []                    # правило 4
        marked: list[tuple[bool, int, str]] = []              # правило 5
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
            if not inside:
                continue
            # правило 5: у записи метка одна на обе команды, у строки меток
            # нет — сравниваем без меток, в обоих порядках сторон
            marks = _entry_marks(entry) if plain else ""
            if marks:
                bare = _bare_entry(entry)
                без_меток = (canon._pair_score(straight, bare),
                             canon._pair_score(swapped, bare))
                if max(без_меток) >= canon.SURE:
                    marked.append((без_меток[1] > без_меток[0], number, marks))
                    continue
            if letter == "T":
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
            # у твёрдой стороны сайта есть слово, которого нет ни в одном
            # написании команды эталона, — это другой клуб: «Hajduk Čurug»
            # не «Hajduk» (книга 087, #8126)
            if canon.odd_word(*canon.firm_side(game, entry)):
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
        if marked:
            if len(marked) > 1:
                return None               # U19 и U21 в одно время — не гадаем
            turned, number, marks = marked[0]
            entry, kickoff = self._entries[number]
            return Confirmed(entry, kickoff, MARKS_HOW, turned, marks)
        if len(sided) == 1:
            turned, number = sided[0]
            entry, kickoff = self._entries[number]
            return Confirmed(entry, kickoff, "одна сторона", turned)
        return None

    def late_marks(self, home: str, away: str, start: datetime | None,
                   sport: str = "") -> Confirmed | None:
        """Правило 5 «метки из эталона» для показа ВНЕ окна эфира (25.10:
        sport5 ставит матч WNBA «גולדן סטייט — אטלנטה» на 03:00 при начале
        02:00 — на час позже, с значком эфира). `confirm` такому показу
        отвечает None, и это верно: эфиром он не становится, фильтры повторов
        решают как раньше. Но пара в ±`REF_WINDOW` известна эталону ТОЛЬКО с
        одной и той же меткой у обеих команд — значит, это женский (юношеский)
        матч, и без метки он шёл бы на витрину второй строкой без W рядом со
        своей же W-игрой. Условия строже правила 5, по списку:
          1. у обеих команд строки меток нет (`_marks_of`);
          2. вид спорта строки известен и у записи тот же (`sport` обязателен:
             мужское волейбольное дерби не должно взять W у женского
             баскетбольного той же пары);
          3. в ±`REF_WINDOW` НЕТ записи, сошедшейся с метками как есть
             (взрослый матч той же пары рядом — метку не гадаем);
          4. запись без своих меток (`_bare_entry`) сошлась на `canon.SURE` в
             любом порядке сторон, метка у неё одна на обе команды
             (`_entry_marks`) — и такая запись ровно ОДНА.
        Ответ — `Confirmed` с `how == LATE_MARKS_HOW` и меткой в `marks`."""
        if start is None or not self._entries or not home or not away \
                or not sport:
            return None
        if _marks_of(home) or _marks_of(away):
            return None
        when = start.replace(tzinfo=None)
        pool: set[int] = set()
        for name in (home, away):
            for word in _words(name, self._cache):
                pool |= self._home.get(word, set())
                pool |= self._away.get(word, set())
        straight = {"home": home, "away": away, "sport": sport}
        swapped = {"home": away, "away": home, "sport": sport}
        marked: list[tuple[bool, int, str]] = []
        for number in pool:
            entry, kickoff = self._entries[number]
            if abs(kickoff - when) > REF_WINDOW:
                continue
            if (entry.get("sport") or "F") != sport:
                continue
            if max(canon._pair_score(straight, entry),
                   canon._pair_score(swapped, entry)) >= canon.SURE:
                return None               # пара есть как есть — не гадаем
            marks = _entry_marks(entry)
            if not marks:
                continue
            bare = _bare_entry(entry)
            scores = (canon._pair_score(straight, bare),
                      canon._pair_score(swapped, bare))
            if max(scores) >= canon.SURE:
                marked.append((scores[1] > scores[0], number, marks))
        if len(marked) != 1:
            return None
        turned, number, marks = marked[0]
        entry, kickoff = self._entries[number]
        return Confirmed(entry, kickoff, LATE_MARKS_HOW, turned, marks)

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

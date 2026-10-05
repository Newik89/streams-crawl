# -*- coding: utf-8 -*-
"""Вид спорта строки: наш (футбол, баскетбол, теннис) или чужой (ТЗ разд. 2 и 6).

Берём только футбол, баскетбол и теннис. Всё остальное — мото, NASCAR,
гольф, регби, сёрф — в ленту не идёт, а ложится во вкладку «Other Sport»:
на одном `sporttv.pt` за сутки таких блоков больше, чем матчей.

**Всё решение — в одном месте: `Sports.decide`.** Там правила записаны
нумерованным списком в порядке применения, и ветки кода идут в том же
порядке. Остальное в этом модуле — только чтение слов из текста.

Слова лежат в `data/markers.json`, раздел `sport`, и пополняются без правки
кода:

* `F`, `B`, `T` — слова наших видов спорта. У каждой буквы две кучки:
  «вид спорта» (само слово «футбол» на языках наших сайтов) и «турниры»
  (NBA, ATP, Superliga). Слово вида спорта сильнее названия турнира:
  «Basketball Superliga» — баскетбол, хотя «Superliga» записана за футболом;
* `чужие` и `другие` — слова чужих видов спорта, `другие` разложены по
  видам («хоккей», «автоспорт») для вкладки «Other Sport». Составные виды
  («americký fotbal», «futebol de praia», «tenis stołowy») записаны здесь
  целиком — поэтому чужие слова ищутся раньше слова «футбол»;
* `кроме` — фразы, где слово спорта — часть чужого названия («AFC
  Wimbledon» — футбольный клуб, а не турнир; 07.09 игра #1455 уехала в
  теннис). Такие фразы вырезаются из текста до проверки этой буквы.

**Имя команды — не слово вида спорта** (06.10, игра #4710). Часть слов
чужих видов совпадает с именами команд: «Le Mans» — и гонка, и клуб Лиги 1;
«Remo» — и гребля, и бразильский клуб; «Gimnasia», «Marathon», «UFC
Fehring», «Box Hill»… Списка таких слов нет и заводить его не нужно. Два
способа узнать имя команды, оба без особых случаев:
  * по самой строке (правило 3): сайт назвал наш вид спорта, а слово чужого
    вида стоит внутри стороны пары — значит это имя клуба. Словарь не нужен;
  * по словарю (правила 4 и 9): сторона пары — команда из
    `data/dictionaries.json`; слова чужих видов, совпавшие с командами
    словаря, выводятся сверкой — `Sports.team_words`. Новое слово или новая
    команда подхватываются без правки кода.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import names
from .live import MARKERS_FILE, _flatten, _pattern, greek_plain

import json

#: буква вида спорта → как называем владельцу
NAMES = {"F": "футбол", "B": "баскетбол", "T": "теннис"}

#: словарь команд: по нему узнаём слова, которые бывают и видом спорта,
#: и именем команды
TEAMS_FILE = MARKERS_FILE.parent / "dictionaries.json"

#: кучка слов САМОГО вида спорта внутри буквы в `markers.json` («футбол» на
#: языках сайтов); всё остальное у буквы — названия турниров
SPORT_NAME_KEY = "вид спорта"

#: группа слов в `markers.json` → «другие», которая называет не вид спорта, а
#: жанр: передача, обзор, повтор. Такую строку не спасает даже эталон — он
#: знает матч, но не знает, что канал показывает вместо него разговор о матче
SHOW_GROUP = "передачи и повторы"

#: Насколько сторона пары — команда словаря, в имени которой стоит слово
#: чужого вида. `_EXACT` — сторона читается ровно как команда словаря
#: («Le Mans», «LE MANS», «Le Mans FC»). `_PART` — имя команды словаря стоит
#: в стороне целиком, но рядом есть другие слова («24 Horas de Le Mans»,
#: «Clube do Remo»): это может быть и клуб, и гонка.
_PART, _EXACT = 1, 2

#: сверка слов со словарём стоит нескольких секунд (75 тысяч написаний) —
#: держим итог на процесс; ключ — сами слова и версия файла словаря
_TEAM_WORDS_CACHE: dict[tuple, dict] = {}


@dataclass
class Verdict:
    """Решение по строке — ответ `Sports.decide`."""
    letter: str | None      # F | B | T — наш вид; «-» — чужой; None — не определён
    word: str = ""          # слово или источник, по которому решили
    rule: int = 0           # номер сработавшего правила из `Sports.decide`
    source: str = ""        # для нашего вида: ref | word | league | women | hint
    group: str = ""         # для чужого вида: вид спорта словами («хоккей»)
    team_word: str = ""     # слово чужого вида, признанное именем команды


@dataclass
class Sports:
    alien: object          # чужие виды спорта
    kinds: dict            # буква → шаблон всех слов нашего вида (и турниров)
    exclude: dict | None = None   # буква → шаблон фраз, которые не считаются
    groups: dict | None = None    # слово (нижний регистр) → вид спорта из «другие»
    #: буква → шаблон слов САМОГО вида спорта (кучка `SPORT_NAME_KEY`)
    sport_names: dict | None = None
    #: имена команд вместо словаря — для проверок; None — `TEAMS_FILE`
    teams: tuple | None = None
    _team_words: dict | None = field(default=None, repr=False, compare=False)

    # ── решение ──────────────────────────────────────────────────────────────

    def decide(self, text: str, head: str = "", pair=None, *, ref: str = "",
               league: tuple[str, str] | None = None, club: str = "",
               hint: str = "") -> Verdict:
        """Наш вид спорта или чужой. ВСЁ решение — здесь, правила по порядку.

        Что приходит (улики собирает `pipeline.classify`):
          text   — весь текст строки: заголовок, категория, лига, описание;
          head   — то, что сайт пишет о матче сам: заголовок, категория,
                   лига — без описания;
          pair   — стороны пары, как их написал сайт («PARIS ST GERMAIN»,
                   «LE MANS»);
          ref    — буква вида спорта из эталона flashscore для этой пары и
                   времени (`reference.Reference.sport_of`); пусто — эталон
                   пару не знает;
          league — (буква, название): лига строки нашлась в словаре лиг;
          club   — буква сугубо женского клуба (`leagues.women_team`);
          hint   — буква из действующей подсказки владельца по этой паре.

        Правила. Срабатывает первое подошедшее, его номер — в `Verdict.rule`:

          1. Слово жанра — «передача, обзор, повтор» (группа `SHOW_GROUP`).
             Это не матч → Other Sport. Эталон тут не судья: он знает матч,
             а не то, что канал показывает вместо него.
          2. Эталон flashscore знает эту пару в это время → вид спорта
             эталона. Слова на странице его не оспаривают: «PSG - Le Mans» —
             футбол, хотя «Le Mans» ещё и гонка.
          3. Сайт сам назвал наш вид спорта (само слово вида: «FUTEBOL»,
             «Piłka nożna», «Košarka» — не название турнира; сначала в
             заголовке, категории и лиге, потом в описании), а КАЖДОЕ слово
             чужого вида в тексте стоит внутри названия команды в паре →
             наш вид. Сайт сказал «футбол», а «Le Mans» у него — команда.
             Словарь команд тут не нужен.
             Составные чужие виды («FUTEBOL PRAIA», «Fútbol Sala», «Tenis
             stołowy», «Američki fudbal») сюда не проходят: их слово стоит в
             категории или лиге, а не в имени команды (`_alien_outside_pair`).
          4. В тексте есть слово чужого вида спорта, и это НЕ имя команды из
             пары → чужой вид. Сюда попадают и составные виды («американский
             футбол», «пляжный футбол», «настольный теннис»): в словаре они
             записаны чужими целиком и находятся раньше слова «футбол».
             Именем команды слово считается, только когда стоит внутри
             стороны пары, а сама сторона — команда словаря
             (`_names_in_pair`).
          5. Сайт сам назвал наш вид спорта. Сначала заголовок, категория и
             лига: слово самого вида («Basketball») сильнее названия турнира
             («Superliga»). Потом — любое слово нашего вида во всём тексте,
             включая описание.
          6. Лига строки есть в словаре лиг → её вид спорта.
          7. Одна из команд — сугубо женский клуб → его вид спорта.
          8. Владелец уже подсказал вид спорта для этой пары.
          9. Слово чужого вида стояло в стороне пары РЯДОМ с именем команды
             словаря («24 Horas de Le Mans», «Clube do Remo»): это и клуб, и
             гонка. Правила 2, 3 и 5–8 наш вид спорта не подтвердили → чужой
             вид.
         10. Никто ничего не сказал → вид спорта не определён. Строка идёт
             на досбор (`scripts/parse_live.py`: склейка с другими сайтами,
             эталон, команды эталона), а если её никто не узнал — владельцу.
        """
        # греческие ударения снимаем: в заголовках их ставят как придётся,
        # «Ποδοσφαίρου» против словарного «ποδόσφαιρο» (10.09)
        text, head = greek_plain(text or ""), greek_plain(head or "")
        alien = self._alien_hits(text)

        # 1. слово жанра: передача, обзор, повтор — не матч
        for hit in alien:
            if self.group_of(hit) == SHOW_GROUP:
                return Verdict("-", hit, rule=1, group=SHOW_GROUP)

        # 2. эталон flashscore знает эту пару в это время
        if ref:
            word = "эталон flashscore"
            if alien:
                word += f" поверх слова «{alien[0]}»"
            return Verdict(ref, word, rule=2, source="ref")

        # 3. сайт назвал наш вид спорта, а чужие слова — только в именах команд
        if alien and pair and not self._alien_outside_pair(text, pair):
            for where in (head, text):
                letter, word = self._own_word(where, self.sport_names or {})
                if letter:
                    return Verdict(letter, word, rule=3, source="word",
                                   team_word=alien[0])

        # 4. слово чужого вида спорта, которое не имя команды из пары
        team_names = self._names_in_pair(pair) if alien and pair else {}
        for hit in alien:
            if hit.lower() not in team_names:
                return Verdict("-", hit, rule=4, group=self.group_of(hit))
        # дальше все чужие слова текста (если были) — имена команд этой пары
        team_word = alien[0] if alien else ""

        # 5. сайт сам назвал наш вид спорта
        for where, patterns in ((head, self.sport_names or {}),
                                (head, self.kinds), (text, self.kinds)):
            letter, word = self._own_word(where, patterns)
            if letter:
                return Verdict(letter, word, rule=5, source="word",
                               team_word=team_word)

        # 6. лига строки есть в словаре лиг
        if league and league[0]:
            return Verdict(league[0], league[1], rule=6, source="league",
                           team_word=team_word)

        # 7. сугубо женский клуб
        if club:
            return Verdict(club, "женский клуб", rule=7, source="women",
                           team_word=team_word)

        # 8. подсказка владельца по этой паре
        if hint:
            return Verdict(hint, "подсказка владельца", rule=8, source="hint",
                           team_word=team_word)

        # 9. имя команды — лишь часть стороны, а наш вид спорта никто не назвал
        if any(team_names[hit.lower()] == _PART for hit in alien):
            return Verdict("-", team_word, rule=9,
                           group=self.group_of(team_word))

        # 10. вид спорта не определён
        return Verdict(None, "", rule=10, team_word=team_word)

    def detect(self, text: str, pair=None) -> tuple[str | None, str]:
        """Буква вида спорта и слово, по которому решили, — когда из улик
        есть только текст (пересмотр очереди, `scripts/review_queue.py`).
        Чужой спорт — `("-", слово)`. Ничего не нашли — `(None, "")`.
        Это то же `decide`, просто без эталона, лиги и подсказки."""
        verdict = self.decide(text, pair=pair)
        return verdict.letter, verdict.word

    # ── чтение слов ──────────────────────────────────────────────────────────

    def group_of(self, word: str) -> str:
        """Чужой вид спорта словами («хоккей», «плавание») по слову, которым
        он найден — для вкладки «Other Sport» (владелец 03.10). Слово из
        старого плоского списка «чужие» — «другое»."""
        key = greek_plain((word or "").lower()).strip()
        return (self.groups or {}).get(key, "другое")

    def _alien_hits(self, text: str) -> list[str]:
        """Все слова чужих видов спорта в тексте, по порядку. Текст — уже
        без греческих ударений."""
        if not self.alien or not text:
            return []
        skip = (self.exclude or {}).get("чужие")
        probe = skip.sub(" ", text) if skip else text
        return [m.group(0) for m in self.alien.finditer(probe)]

    def _alien_outside_pair(self, text: str, pair) -> list[str]:
        """Слова чужих видов спорта, которые остались в тексте, когда из него
        вырезаны обе стороны пары так, как их написал сайт. Пусто — все
        чужие слова строки стоят внутри названий команд (правило 3).
        Сторона, которую разбор пары переписал и которой в тексте дословно
        нет, не вырезается — тогда её слова считаются «снаружи», и правило 3
        осторожно молчит."""
        probe = text.lower()
        for side in pair or ():
            side = greek_plain(side or "").strip().lower()
            if side:
                probe = probe.replace(side, " ")
        return self._alien_hits(probe)

    def _own_word(self, text: str, patterns: dict) -> tuple[str | None, str]:
        """Первое слово нашего вида спорта в тексте: буква и само слово.
        Буквы проверяются по порядку F, B, T."""
        if not text:
            return None, ""
        for letter, pattern in patterns.items():
            if not pattern:
                continue
            skip = (self.exclude or {}).get(letter)
            probe = skip.sub(" ", text) if skip else text
            m = pattern.search(probe)
            if m:
                return letter, m.group(0)
        return None, ""

    def team_words(self) -> dict[str, frozenset]:
        """Слова чужих видов спорта, которые стоят в именах команд словаря:
        слово (нижний регистр) → чтения этих имён (`names.readings`).
        «le mans» → {«MANS»}, «remo» → {«REMO»}, «gimnasia» → {«GIMNASIA»,
        «GIMNASIA JUJUY», …}. Считается один раз, при первой нужде."""
        if self._team_words is not None:
            return self._team_words
        if not self.alien:
            self._team_words = {}
            return self._team_words
        key = None
        if self.teams is None:
            skip = (self.exclude or {}).get("чужие")
            try:
                stamp = TEAMS_FILE.stat().st_mtime_ns
            except OSError:
                stamp = 0
            key = (self.alien.pattern, skip.pattern if skip else "",
                   str(TEAMS_FILE), stamp)
            if key in _TEAM_WORDS_CACHE:
                self._team_words = _TEAM_WORDS_CACHE[key]
                return self._team_words
        found: dict[str, set] = {}
        for name in (self.teams if self.teams is not None else _dictionary_teams()):
            hits = self._alien_hits(greek_plain(name or ""))
            if not hits:
                continue
            reads = [r for r in names.readings(name) if r.strip()]
            for hit in hits:
                found.setdefault(hit.lower(), set()).update(reads)
        self._team_words = {w: frozenset(r) for w, r in found.items() if r}
        if key is not None:
            _TEAM_WORDS_CACHE.clear()         # старая версия словаря не нужна
            _TEAM_WORDS_CACHE[key] = self._team_words
        return self._team_words

    def _names_in_pair(self, pair) -> dict[str, int]:
        """Слова чужих видов, которые в ЭТОЙ паре — имя команды: слово
        (нижний регистр) → `_EXACT` или `_PART` (см. константы)."""
        out: dict[str, int] = {}
        for side in pair or ():
            if not side:
                continue
            hits = {h.lower() for h in self._alien_hits(greek_plain(side))}
            if not hits:
                continue
            known = self.team_words()
            reads = [set(r.split()) for r in names.readings(side)]
            for word in hits:
                level = 0
                for name in known.get(word, ()):
                    parts = set(name.split())
                    if any(parts == r for r in reads):
                        level = _EXACT
                        break
                    if any(parts <= r for r in reads):
                        level = _PART
                if level:
                    out[word] = max(out.get(word, 0), level)
        return out


def _dictionary_teams():
    """Все написания команд словаря: канон и алиасы. Файла нет — пусто, и
    тогда ни одно слово чужого вида именем команды не считается."""
    try:
        data = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for team in data.get("teams") or []:
        yield team.get("name") or ""
        yield from team.get("aliases") or ()


def load(path: Path | None = None, override: dict | None = None,
         teams=None) -> Sports:
    data = json.loads((path or MARKERS_FILE).read_text(encoding="utf-8"))
    node = (override or {}).get("sport") or data.get("sport") or {}
    skip = node.get("кроме") or {}
    # «другие» — те же чужие виды, но разложенные по видам спорта (03.10,
    # владелец: позже понадобятся для API flashscore) — пока все отсеиваются,
    # а вид спорта словами едет во вкладку «Other Sport» админки
    others = node.get("другие") or {}
    groups = {}
    for group, words in others.items():
        if group == "_":
            continue
        for w in _flatten(words):
            groups.setdefault(greek_plain(w.lower()), group)

    def sport_name_words(letter: str) -> list[str]:
        """Слова самого вида спорта у буквы; у старого плоского списка
        такой кучки нет — тогда все слова буквы равны."""
        own = node.get(letter)
        return _flatten(own.get(SPORT_NAME_KEY)) if isinstance(own, dict) else []

    return Sports(
        alien=_pattern(_flatten(node.get("чужие")) + _flatten(others)),
        kinds={letter: _pattern(_flatten(node.get(letter)))
               for letter in ("F", "B", "T")},
        exclude={letter: _pattern(_flatten(skip.get(letter)))
                 for letter in ("F", "B", "T", "чужие")},
        groups=groups,
        sport_names={letter: _pattern(sport_name_words(letter))
                     for letter in ("F", "B", "T")},
        teams=tuple(teams) if teams is not None else None,
    )

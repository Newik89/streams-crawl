# -*- coding: utf-8 -*-
"""Вопрос «Какой это вид спорта?» — может ли программа ответить сама.

**Откуда вопрос.** Обход (`scripts/parse_live.py`) не узнал вид спорта
строки — `Sports.decide` дошёл до последнего правила — и положил её в
`на_разбор`. Заливка (`scripts/games_import.py`) делает из неё вопрос
владельцу: страница «Названия», вкладка «Вид спорта».

**Почему программа может ответить сама.** У заливки и у уборки очереди
(`scripts/review_queue.py`) улик больше, чем у обхода:

* база знает свежие алиасы лиг («Torneo de Tokio» → «ATP - SINGLES:
  Tokyo (Japan), hard») и все подсказки владельца;
* эталон flashscore лежит целиком: видно, когда пара играет на самом деле,
  и если строка стоит в другой час — это не трансляция матча;
* вопрос, заданный давно, судится словарём слов, который с тех пор вырос
  (`data/markers.json`).

**Правила по порядку** (срабатывает первое):

  А. Слово записи или студии — те же списки, что у отсева эфира
     (`app/live.py`: not_live, stop_title, stop_genre): «основные моменты»,
     «összefoglaló» → не матч.
  Б. Вид спорта решает `Sports.decide` — тот же, что в обходе, со всеми
     уликами: эталон в этот час, команды эталона, лига (словарь лиг и
     алиасы базы), женский клуб, подсказка владельца, месяц строки. Чужой
     вид спорта или передача → не матч.
  В. Эталон знает эту пару, но в другой час: строка раньше матча больше
     чем на `LIVE_NEAR` или позже больше чем на `REPEAT_AFTER` — и не
     дальше `REPEAT_DEPTH` (пороги `app/reference.py`, те же, что у фильтра
     повторов обхода). Это повтор, анонс или ошибка сетки, а не трансляция
     → не матч. Исключение — время эталона «заглушка тура»
     (`Reference.round_placeholder`): тогда, скорее всего, прав сайт, и
     строка — сам матч.
  Г. Наш вид спорта по правилу Б → ответ, как если бы ответил владелец.
  Д. Ничего не решилось → вопрос остаётся владельцу.

**Как пишется ответ** — тем же путём, что кнопки админки:
`dictionary.resolve` (подсказка вида спорта с днём матча, вопрос закрыт) и
`dictionary.skip` (вкладка «Отсеянные», кнопка «Вернуть»). Пометка «ответила
программа: …» ложится в `moderation.answered_by` и видна в админке.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from . import dictionary, leagues, live, pipeline, sport
from .reference import (LIVE_NEAR, REPEAT_AFTER, REPEAT_DEPTH, Reference)

#: какое правило `Sports.decide` сработало — словами, для пометки владельцу
RULE_WORDS = {
    1: "передача или запись",
    2: "эталон flashscore",
    3: "сайт назвал вид спорта",
    4: "чужой вид спорта",
    5: "сайт назвал вид спорта",
    6: "лига из словаря",
    7: "женский клуб",
    8: "подсказка владельца",
    9: "чужой вид спорта",
}

#: буква → как назвать владельцу
SPORT_WORDS = {"F": "футбол", "B": "баскетбол", "T": "теннис"}

_WHEN = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})")
_PLACE = re.compile(r"^(?P<channel>.*?)\s*\((?P<domain>[^()]*)\)\s*$")


@dataclass
class Question:
    """Вопрос очереди, разобранный на части.

    Строка очереди (`raw_value`) — «Хозяева - Гости | лига | Канал (сайт)»,
    лиги может не быть. Подсказка (`suggestion`) — «2026-10-10 19:30 |
    заголовок, как на сайте» (`scripts/games_import.py`)."""
    raw_value: str
    suggestion: str
    pair: tuple[str, str] | None
    league: str
    channel: str
    domain: str
    when: datetime | None
    title: str

    @classmethod
    def parse(cls, raw_value: str, suggestion: str = "") -> "Question":
        parts = [x.strip() for x in (raw_value or "").split("|")]
        pair_text = parts[0]
        league = parts[1] if len(parts) > 2 else ""
        place = parts[-1] if len(parts) > 1 else ""
        m = _PLACE.match(place)
        channel, domain = (m["channel"], m["domain"]) if m else (place, "")
        home, sep, away = pair_text.partition(" - ")
        pair = ((home.strip(), away.strip())
                if sep and home.strip() and away.strip() else None)
        suggestion = suggestion or ""
        m = _WHEN.search(suggestion)
        when = None
        if m:
            try:
                when = datetime.strptime(f"{m[1]} {m[2]}", "%Y-%m-%d %H:%M")
            except ValueError:
                when = None
        title = suggestion.split("|", 1)[1].strip() \
            if m and "|" in suggestion else suggestion.strip()
        return cls(raw_value or "", suggestion, pair, league, channel,
                   domain, when, title)

    @property
    def pair_text(self) -> str:
        return " - ".join(self.pair) if self.pair else \
            (self.raw_value.split("|")[0].strip())

    @property
    def text(self) -> str:
        """Что сайт написал о матче: пара, лига, заголовок. Канал сюда не
        входит — обход его тоже не читает (`pipeline.classify`)."""
        return " ".join(x for x in (self.pair_text, self.league, self.title)
                        if x)


@dataclass
class Answer:
    """Ответ программы на вопрос. `letter`: F/B/T — наш вид спорта; «-» —
    не матч или чужой вид спорта; None — решать владельцу."""
    letter: str | None
    rule: str = ""          # коротко: «правило 5», «запись», «не в час матча»
    why: str = ""           # улика словами: «слово «FIBA»»

    @property
    def note(self) -> str:
        """Пометка в `moderation.answered_by`."""
        return f"ответила программа: {self.rule} — {self.why}"

    @property
    def plain(self) -> str:
        """Ответ одной строкой для владельца: «баскетбол — слово «FIBA»»."""
        what = SPORT_WORDS.get(self.letter or "", "не матч")
        return f"{what} — {self.why}" if self.letter else "решать владельцу"


class Judge:
    """Судья вопросов «вид спорта». Собирается один раз на прогон: эталон,
    словари и слова читаются при создании. Без базы (`conn` = None, для
    проверок) — только словари из файлов `data/`."""

    def __init__(self, conn, reference_entries: list[dict] | None = None,
                 sports: sport.Sports | None = None,
                 markers: live.Markers | None = None):
        self.sports = sports or sport.load()
        self.markers = markers or live.load()
        self.reference = Reference(reference_entries or [])
        # лига → буква: словарь `data/dictionaries.json` и сама база (она
        # свежее: алиасы, выученные последней заливкой)
        self.league_sports = dict(leagues.sports_map())
        # написание лиги → канон flashscore («≈» на странице «Названия»)
        self.league_names: dict[str, str] = {}
        # подсказки владельца: пара → (буква, день матча)
        self.hints: dict[str, tuple] = {}
        if conn is None:
            return
        for r in conn.execute(
                "SELECT l.canonical_name AS name, l.sport, a.alias "
                "FROM leagues l LEFT JOIN league_aliases a "
                "ON a.league_id = l.id WHERE l.sport IN ('F', 'B', 'T')"):
            for key in (r["name"], (r["name"] or "").partition(":")[2],
                        r["alias"]):
                key = _norm(key)
                if key:
                    self.league_sports.setdefault(key, r["sport"])
        self.league_names = dictionary.league_overrides(conn)
        self.hints = {r["pair"]: (r["sport"], r["match_day"]) for r in
                      conn.execute("SELECT pair, sport, match_day "
                                   "FROM sport_hints")}

    # ── решение ──────────────────────────────────────────────────────────────

    def answer(self, q: Question) -> Answer:
        """Правила А–Д из шапки модуля, по порядку."""
        # А. слово записи или студии — как у отсева эфира: заголовок и пара
        # стоп-словами и словами записи, рубрика (лига) — стоп-жанрами
        shown = " ".join(x for x in (q.title, q.pair_text) if x)
        stop = (self.markers.found(self.markers.stop_title, shown)
                or self.markers.found(self.markers.not_live, shown)
                or self.markers.found(self.markers.stop_genre, q.league))
        if stop:
            return Answer("-", "запись или студия", f"слово «{stop}»")

        # улики эталона: матч этой пары в час строки и в другие часы
        near, far = self._reference_times(q)
        ref = {e.get("sport") or "F" for e, _ in near}
        ref_letter = ref.pop() if len(ref) == 1 else ""

        # Б. вид спорта — тем же `Sports.decide`, что в обходе
        verdict = self._decide(q, ref_letter)
        if verdict.letter == "-":
            return Answer("-", f"правило {verdict.rule}",
                          f"{RULE_WORDS.get(verdict.rule, '')}: "
                          f"«{verdict.word}»")

        # В. эталон ставит этот матч в другой час — показ не трансляция
        if far and not near:
            entry, when = min(far, key=lambda x: abs(q.when - x[1]))
            return Answer("-", "не в час матча",
                          f"flashscore: {entry.get('home')} — "
                          f"{entry.get('away')} {when:%d.%m %H:%M}, а строка "
                          f"{q.when:%d.%m %H:%M} — повтор, анонс или ошибка "
                          f"сетки")

        # Г. наш вид спорта
        if verdict.letter in SPORT_WORDS:
            word = verdict.word
            if verdict.rule == 2 and near:
                entry, when = near[0]
                word = (f"{entry.get('home')} — {entry.get('away')} "
                        f"{when:%d.%m %H:%M}")
            return Answer(verdict.letter, f"правило {verdict.rule}",
                          f"{RULE_WORDS.get(verdict.rule, '')}: «{word}»")

        # Д. решать владельцу
        return Answer(None)

    def _reference_times(self, q: Question) -> tuple[list, list]:
        """Матчи эталона с этой парой: (в час строки, в другой час).

        «В час строки» — от `LIVE_NEAR` до матча до `REPEAT_AFTER` после
        начала (тот же матч в своём окне: разброс сеток, студия), а также
        «заглушка тура» в любой час. «В другой час» — дальше, но в пределах
        `REPEAT_DEPTH`: ещё дальше — уже другая встреча тех же команд."""
        if not q.pair or q.when is None:
            return [], []
        near, far = [], []
        for entry, when in self.reference.pair_times(*q.pair):
            gap = q.when - when              # > 0 — строка позже матча
            if -LIVE_NEAR <= gap <= REPEAT_AFTER \
                    or self.reference.round_placeholder(entry, when):
                near.append((entry, when))
            elif abs(gap) <= REPEAT_DEPTH:
                far.append((entry, when))
        return near, far

    def _decide(self, q: Question, ref_letter: str) -> sport.Verdict:
        """Улики для `Sports.decide` — как их собирает `pipeline.classify`,
        только из строки очереди и базы."""
        home, away = q.pair or ("", "")
        # лига: как написал сайт, и начало заголовка до двоеточия
        # («Bundesliga: Lepzig-Freiburg»); канон из алиасов базы идёт в
        # текст — его слова («ATP») читает правило 5
        league, canonical = None, ""
        for key in (q.league, q.title.partition(":")[0] if ":" in q.title
                    else ""):
            key = (key or "").strip()
            if not key:
                continue
            canonical = canonical or self.league_names.get(key, "")
            letter = (self.league_sports.get(_norm(key))
                      or self.league_sports.get(_norm(
                          self.league_names.get(key, ""))))
            if letter:
                league = (letter, key)
                break
        text = " ".join(x for x in (q.text, canonical) if x)
        hint = self.hints.get(dictionary.norm_pair(q.raw_value))
        by_hint = hint[0] if hint and pipeline.hint_fresh(hint[1], q.when) \
            else ""
        return self.sports.decide(
            text, q.text, q.pair,
            ref=ref_letter,
            ref_team=bool(q.pair) and any(self.reference.knows_team(x)
                                          for x in (home, away)),
            league=league,
            club=(leagues.women_team(home) or leagues.women_team(away))
            if q.pair else "",
            hint=by_hint,
            month=q.when.month if q.when else 0)


def _norm(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def settle(conn, judge: Judge, items, apply: bool) -> list[tuple]:
    """Пересудить вопросы очереди и, с `apply`, ответить на решённые тем же
    путём, что кнопки админки. `items` — пары (запись `moderation` с id и
    raw_value, `Question`). Копии одной пары с разных каналов отвечаются
    одним ответом (`dictionary.resolve` / `skip` закрывают всю пару).
    Возвращает [(запись, ответ)] — и решённые, и оставленные владельцу."""
    out, done_pairs = [], set()
    for r, q in items:
        answer = judge.answer(q)
        out.append((r, answer))
        pair = dictionary.norm_pair(r["raw_value"])
        if not apply or answer.letter is None or pair in done_pairs:
            continue
        done_pairs.add(pair)
        if answer.letter == "-":
            dictionary.skip(conn, r["id"], answered_by=answer.note)
        else:
            dictionary.resolve(conn, r["id"], answer.letter,
                               answered_by=answer.note)
    return out

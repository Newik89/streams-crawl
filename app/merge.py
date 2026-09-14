# -*- coding: utf-8 -*-
"""Склейка одной игры, пришедшей с разных сайтов (ТЗ разд. 9).

Одна игра — одна строка, каналы к ней списком. `MÓNACO — MARSELHA` с
португальского сайта, `AS Monaco — Olympique Marsylia` с польского и
`Монако — Марсилия` с болгарского — это одна запись с тремя каналами.

Игры считаются одной, когда сошлось всё:
  - **обе** команды похожи (`app/names.py`; порог там же). По худшей из двух,
    иначе `Реал — Барса` и `Реал — Бетис` сойдут за одну игру;
  - время расходится не больше чем на ±150 минут. Блок в ТВ-сетке начинается
    раньше матча, поэтому допуск такой широкий (ТЗ разд. 7);
  - совпал вид спорта.

Порядок команд не важен: `A — B` и `B — A` — одна игра, некоторые сайты
ставят хозяев вторыми.

Чего здесь СОЗНАТЕЛЬНО нет: удаления. Игра, которой не стало в источнике, не
исчезает — за это отвечает срок жизни (ТЗ разд. 10), а не склейка.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from . import names

# Допуск по времени. ТВ-сетка ставит блок раньше начала матча, а иногда
# включает в него студию — отсюда такие широкие рамки (ТЗ разд. 9).
WINDOW_MINUTES = 150

#: Вид спорта иногда определяется неверно — там, где сайт его не пишет:
#: «INTERNATIONAL TOURNAMENT» у `epg.cyta.com.cy` уехал в футбол, а тот же
#: баскетбольный матч у `skai.gr` определился верно — одна игра легла двумя
#: строками (#1100/#1506, разбор владельца 10.09). Пара, совпавшая почти
#: дословно и стоящая в ту же минуту, — одна игра, даже если буквы спорта
#: разошлись
SPORT_CLASH_SURE = 95
SPORT_CLASH_WINDOW = 30


@dataclass
class Entry:
    """Одна строка от одного сайта."""
    source: str                 # домен
    channel: str
    home: str
    away: str
    start: datetime             # киевское время
    sport: str = ""
    league: str = ""            # ядро названия лиги, как на сайте
    payload: object = None      # исходный `pipeline.Row`, если нужен дальше


@dataclass
class Game:
    """Игра после склейки: сама пара команд и все каналы, где её нашли."""
    entries: list[Entry] = field(default_factory=list)

    @property
    def first(self) -> Entry:
        return min(self.entries, key=lambda e: e.start)

    @property
    def start(self) -> datetime:
        return self.first.start

    @property
    def sport(self) -> str:
        """Вид спорта игры: тот, который назвали больше сайтов.

        Раньше брался у самой ранней записи, и одна ошибка перевешивала:
        баскетбольный `Aris - Maccabi` уходил в футбол, потому что первым
        его поставил телегид, где вид спорта не написан (#1100/#1506).
        """
        счёт: dict[str, int] = {}
        for e in self.entries:
            if e.sport:
                счёт[e.sport] = счёт.get(e.sport, 0) + 1
        if not счёт:
            return self.first.sport
        много = max(счёт.values())
        лидеры = [s for s, n in счёт.items() if n == много]
        return (self.first.sport if self.first.sport in лидеры else лидеры[0])

    @staticmethod
    def _readable(names: list[str]) -> str:
        """Какое из написаний показывать человеку.

        Одна игра приходит с сайтов на разных алфавитах: `אטאלנטה` с
        израильского, `Аталанта` с российского, `Atalanta` с чешского. Раньше
        бралось имя самой ранней записи — и в ленте оказывался иврит просто
        потому, что этот сайт первым поставил матч в сетку. Показываем то,
        что прочтёт больше людей: латиница, затем кириллица, и только потом
        всё остальное.
        """
        def rank(name: str) -> tuple:
            letters = [c for c in name if c.isalpha()]
            if not letters:
                return (3, 0)
            latin = sum(1 for c in letters if "A" <= c.upper() <= "Z")
            cyr = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
            if latin * 2 >= len(letters):
                return (0, -len(name))
            if cyr * 2 >= len(letters):
                return (1, -len(name))
            return (2, -len(name))

        return sorted([n for n in names if n], key=rank)[0] if any(names) else ""

    @property
    def home(self) -> str:
        return self._readable([e.home for e in self.entries]) or self.first.home

    @property
    def away(self) -> str:
        return self._readable([e.away for e in self.entries]) or self.first.away

    @property
    def sources(self) -> list[str]:
        return sorted({e.source for e in self.entries})

    @property
    def leagues(self) -> list[str]:
        """Как турнир назвали разные сайты — все написания, без повторов."""
        out: list[str] = []
        for e in sorted(self.entries, key=lambda x: x.start):
            if e.league and e.league not in out:
                out.append(e.league)
        return out

    @property
    def league(self) -> str:
        """Одна лига для показа — самая точная из тех, что дали источники.

        Сайты называют турнир с разной точностью: `teleman.pl` пишет
        `Liga angielska` и валит туда же Чемпионшип, а `sporttv.pt` различает
        `EFL Championship`. Поэтому страновой канон (`ENGLAND: Football`)
        уступает любому, где назван дивизион.
        """
        named = [e.league for e in self.entries if e.league]
        if not named:
            return ""
        exact = [x for x in named if not x.upper().endswith(": FOOTBALL")]
        # Лига ивритом — последней: sport5 пишет турнир ивритом, а та же игра
        # с латинского сайта названа так, как её знают словарь и эталон
        # (Red Star — Metz: «ליגה צרפתית שנייה» и «FRANCUSKA 2. LIGA», 14.09)
        return sorted(exact or named,
                      key=lambda x: any("֐" <= c <= "׿" for c in x))[0]

    @property
    def channels(self) -> list[str]:
        """Каналы без повторов, в порядке появления. Один канал, найденный на
        пяти сайтах, остаётся одной записью (ТЗ разд. 9)."""
        out: list[str] = []
        for e in sorted(self.entries, key=lambda x: x.start):
            if e.channel not in out:
                out.append(e.channel)
        return out


def _same_game(a: Entry, b: Entry, threshold: int) -> bool:
    if abs(a.start - b.start) > timedelta(minutes=WINDOW_MINUTES):
        return False
    спорт_врозь = bool(a.sport and b.sport and a.sport != b.sport)
    if спорт_врозь and abs(a.start - b.start) > timedelta(
            minutes=SPORT_CLASH_WINDOW):
        return False
    if names.category(a.home) != names.category(b.home) \
            or names.category(a.away) != names.category(b.away):
        # порядок может быть обратным — проверим и его, прежде чем отказать
        if names.category(a.home) != names.category(b.away) \
                or names.category(a.away) != names.category(b.home):
            return False
    direct = min(names.similarity(a.home, b.home),
                 names.similarity(a.away, b.away))
    swapped = min(names.similarity(a.home, b.away),
                  names.similarity(a.away, b.home))
    сходство = max(direct, swapped)
    # спорт разошёлся — спрашиваем с пары строже обычного
    return сходство >= (SPORT_CLASH_SURE if спорт_врозь else threshold)


def merge(entries: list[Entry],
          threshold: int = names.SIMILAR_ENOUGH) -> list[Game]:
    """Строки → игры. Строка цепляется к той игре, с которой сошлась лучше
    всего; не нашлось — заводит свою."""
    games: list[Game] = []
    for entry in sorted(entries, key=lambda e: e.start):
        target = None
        for game in games:
            if any(_same_game(other, entry, threshold) for other in game.entries):
                target = game
                break
        if target is None:
            games.append(Game(entries=[entry]))
        else:
            target.entries.append(_aligned(entry, target.first))
    return sorted(games, key=lambda g: g.start)


def _aligned(entry: Entry, sample: Entry) -> Entry:
    """Строка, развёрнутая под порядок команд уже собранной игры.

    Сайты пишут пару в разном порядке: у одного `FENERBAHÇE - LYON`, у
    другого `Lyon - Fenerbahçe`. Склейка это переживает (сравнение проверяет
    и обратный порядок), но если положить строку как есть, то в витрине
    хозяева берутся из одной записи, гости — из другой, и получается
    `FENERBAHÇE — Fenerbahçe`: одна и та же команда с обеих сторон
    (поймано 01.09 на матче Лиги чемпионов). Поэтому перевёрнутую строку
    разворачиваем под порядок первой записи игры.
    """
    direct = min(names.similarity(entry.home, sample.home),
                 names.similarity(entry.away, sample.away))
    swapped = min(names.similarity(entry.home, sample.away),
                  names.similarity(entry.away, sample.home))
    if swapped > direct:
        return replace(entry, home=entry.away, away=entry.home)
    return entry

# -*- coding: utf-8 -*-
"""Словари названий в базе и очередь модерации (ТЗ разд. 8).

Разделение труда со словарём слов `data/aliases.json`:

  - `aliases.json` — куски названий: `BREMA` → `BREMEN`, `SANKT` → `SAINT`.
    Одно слово чинит сразу много имён, ведёт его ассистент;
  - таблицы здесь — **целые имена**: `Мидълзбро` → `Middlesbrough`. Их
    подтверждает владелец, и подтверждённое держится навсегда.

Не опознали имя — не выбрасываем и не гадаем: строка ложится в `moderation`
как «сырое имя + предложение системы», владелец подтверждает или правит.

**Канал — это имя И страна.** `Nova Sport 1` бывает греческий и чешский, это
разные каналы (решение владельца 31.08). Поэтому у канала обязательна
страна, а алиас привязан к сайту, на котором встретился: одно и то же
написание на греческом и чешском телегиде ведёт к разным каналам.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
import unicodedata

KINDS = ("team", "league", "channel", "sport")

_SLUG_TRIM = re.compile(r"[^a-z0-9]+")


def slugify(name: str, fallback: str = "x") -> str:
    """`ENGLAND: Championship` → `england-championship`. Нужен как стабильный
    внешний идентификатор (ТЗ разд. 8)."""
    folded = unicodedata.normalize("NFKD", name or "")
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    slug = _SLUG_TRIM.sub("-", ascii_only.lower()).strip("-")
    return slug or fallback


def _unique_slug(conn: sqlite3.Connection, table: str, base: str) -> str:
    """У `slug` в схеме стоит UNIQUE: два разных клуба могут дать одинаковую
    основу, поэтому второму добавляем номер."""
    slug, n = base, 2
    while conn.execute(f"SELECT 1 FROM {table} WHERE slug = ?", (slug,)).fetchone():
        slug, n = f"{base}-{n}", n + 1
    return slug


# ── чтение словарей ──────────────────────────────────────────────────────────

#: канонические имена с таким сходством — один клуб, записанный двумя
#: командами: `Veneza`/`Venezia` дают 66, `AC Milan`/`Milan` — 100, а разные
#: клубы с общим словом — `Maccabi Haifa`/`Maccabi Rishon` 36, `CSKA Sofia`/
#: `CSKA Moscow` 44, `Slavia Sofia`/`Slavia Prague` 54 (замер 14.09)
SAME_CLUB = 60


def _kind(text: str) -> tuple[str, bool]:
    """Категория имени для спора: пол/возраст и пометка «3x3» (`_learnable`)."""
    from . import names
    return names.category(text), "3x3" in text.lower()


def _plain_words(name: str) -> set[str]:
    """Слова имени без регистра, диакритики, дефисов и точек:
    `Atl. Madrid` → {atl, madrid}, `Al-Sadd` → {al, sadd}."""
    folded = unicodedata.normalize("NFKD", name or "")
    plain = "".join(c for c in folded if not unicodedata.combining(c)).casefold()
    return set(plain.replace("-", " ").replace(".", " ").split())


def _same_club(one: str, two: str) -> bool:
    """Два канонических имени — один клуб? Карточка словаря 09.11 (случай 098):
    одного сходства ≥ SAME_CLUB мало — `Dynamo Moscow`/`Dyn. Kyiv`, `Barcelona`/
    `Baskonia` (70) и `Racing Santander`/`Racing Club` проходили как один клуб, и
    спорное написание уходило последней записи. Теперь ещё и слова одного имени
    должны целиком входить в другое (`Milan` ⊂ `AC Milan`, `Al Sadd` = `Al-Sadd`)."""
    from . import names                      # names словарь не импортирует
    if names.similarity(one, two) < SAME_CLUB:
        return False
    a, b = _plain_words(one), _plain_words(two)
    return bool(a) and bool(b) and (a <= b or b <= a)


def _clubs(canonicals: list[str]) -> int:
    """Сколько РАЗНЫХ клубов среди имён: имена одного клуба — в одну кучку."""
    groups: list[list[str]] = []
    for name in canonicals:
        for group in groups:
            if any(_same_club(name, other) for other in group):
                group.append(name)
                break
        else:
            groups.append([name])
    return len(groups)


# ── книга ошибок словаря (карточка словаря 09.11.2026) ──────────────────────

#: классы книги ошибок; первые два — карантин: словарь запись не отдаёт
ERROR_CLASSES = ("пара", "коллизия", "двусмысленно", "слито", "возможный дубль",
                 "не пара", "снято")
QUARANTINE = ("пара", "коллизия")
#: С10 (ревизия 09.11): решение «имя с тире — ОДНА команда» (`Banik Most - Sous`).
#: Пишет классификатор (flashscore или поиск с источником) и слово владельца
#: (кнопка ✎). Пока строки нет, правило С5 считает имя с тире парой матча
NOT_PAIR = "не пара"
#: С11 (ревизия 09.11): карантин, снятый словом владельца. Строка книги не
#: стирается — меняет класс, прежний класс остаётся в заметке
LIFTED = "снято"

#: пара матча, записанная одним именем: «A - B», «A – B», «A vs B», «A v B».
#: Пробелы по обе стороны обязательны — `Fleury-Merogis` одна команда
_PAIR_RE = re.compile(r"\S\s+(?:-|–|—|vs\.?|v)\s+\S", re.IGNORECASE)


def is_pair_name(text: str) -> bool:
    """Правило С5: пара — не команда."""
    return bool(_PAIR_RE.search(text or ""))


def note_error(conn: sqlite3.Connection, alias: str, cls: str,
               lang: str | None = None, team_id: int | None = None,
               source_domain: str | None = None, led_to: str | None = None,
               truth: str | None = None, note: str | None = None,
               answered_by: str = "программа") -> bool:
    """Строка в книгу ошибок. Правило С9: одна строка на (alias, lang, class) —
    повторная встреча обновляет время, не плодит строку. У карантина
    («пара», «коллизия») ключ ещё и команда: одно написание без языка
    бывает ошибочно прицеплено к двум клубам («Parma» → AS Roma и Palermo),
    и каждая такая запись — своя строка карантина (С3 читает тройку
    alias, lang, team_id). Возвращает True, если строка новая."""
    if cls not in ERROR_CLASSES:
        raise ValueError(f"класс книги ошибок: {cls!r}")
    if cls in QUARANTINE:
        row = conn.execute(
            "SELECT id FROM dictionary_errors WHERE alias = ? AND lang IS ? "
            "AND class = ? AND team_id IS ?", (alias, lang, cls, team_id)).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM dictionary_errors WHERE alias = ? AND lang IS ? "
            "AND class = ?", (alias, lang, cls)).fetchone()
    if row:
        conn.execute("UPDATE dictionary_errors SET created_at = datetime('now'), "
                     "team_id = COALESCE(?, team_id), led_to = COALESCE(?, led_to), "
                     "truth = COALESCE(?, truth) WHERE id = ?",
                     (team_id, led_to, truth, row[0]))
        return False
    conn.execute(
        "INSERT INTO dictionary_errors (alias, lang, team_id, class, source_domain, "
        "led_to, truth, note, answered_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (alias, lang, team_id, cls, source_domain, led_to, truth, note, answered_by))
    return True


def quarantined(conn: sqlite3.Connection) -> set[tuple[str, str | None, int | None]]:
    """Записи (alias, lang, team_id), которые словарь не отдаёт (С3)."""
    marks = ",".join("?" * len(QUARANTINE))
    try:
        return {(r["alias"], r["lang"], r["team_id"]) for r in conn.execute(
            f"SELECT alias, lang, team_id FROM dictionary_errors WHERE class IN ({marks})",
            QUARANTINE)}
    except sqlite3.OperationalError:        # база старше карточки, init_db ещё не было
        return set()


def _errors_stamp(conn: sqlite3.Connection) -> tuple:
    """Метка книги для кэша словаря. Третье число — сумма номеров строк
    КАРАНТИНА: снятие карантина (С11) меняет класс строки, а число строк и
    наибольший номер при этом те же — без суммы кэш перемены не заметил бы."""
    marks = ",".join("?" * len(QUARANTINE))
    try:
        return tuple(conn.execute(
            "SELECT count(*), max(id), "
            f"coalesce(sum(CASE WHEN class IN ({marks}) THEN id END), 0) "
            "FROM dictionary_errors", QUARANTINE).fetchone())
    except sqlite3.OperationalError:
        return (0, None, 0)


def is_confirmed_team_name(conn: sqlite3.Connection, text: str) -> bool:
    """С10: про этот текст с тире в книге есть решение «не пара» — одна команда."""
    try:
        return conn.execute("SELECT 1 FROM dictionary_errors WHERE alias = ? AND class = ?",
                            (text, NOT_PAIR)).fetchone() is not None
    except sqlite3.OperationalError:        # база старше карточки
        return False


def is_blocked_pair(conn: sqlite3.Connection, text: str) -> bool:
    """С5: текст — пара матча («La Duchere - Feurs»), и решения «не пара»
    (С10) про него нет. Такое имя командой не считается нигде: ни словарю,
    ни игре — даже если команда с таким именем в базе уже лежит."""
    return is_pair_name(text) and not is_confirmed_team_name(conn, text)


def confirm_team_name(conn: sqlite3.Connection, text: str, why: str,
                      answered_by: str = "программа") -> bool:
    """С10: записать решение «имя с тире — одна команда» (`why` — почему и
    источник). Строки «пара» про этот же текст БЕЗ команды («канон — пара
    матча, команда не заведена», их пишет С5) устарели — переводятся в
    «снято». Возвращает True, если решение новое."""
    conn.execute(
        "UPDATE dictionary_errors SET class = ?, "
        "note = 'было: пара; ' || coalesce(note, '') || ' → имя подтверждено: одна команда' "
        "WHERE alias = ? AND class = 'пара' AND team_id IS NULL", (LIFTED, text))
    return note_error(conn, text, NOT_PAIR, led_to=text, note=why, answered_by=answered_by)


def lift_quarantine(conn: sqlite3.Connection, alias: str, team_id: int,
                    who: str, why: str) -> int:
    """С11: слово владельца снимает карантин с написания `alias` у команды
    `team_id` (записи любого языка). Строка книги остаётся: класс → «снято»,
    прежний класс — в заметке. Возвращает, сколько строк снято."""
    marks = ",".join("?" * len(QUARANTINE))
    try:
        return conn.execute(
            "UPDATE dictionary_errors SET class = ?, answered_by = ?, "
            "note = 'было: ' || class || '; ' || coalesce(note, '') || ' → ' || ? "
            f"WHERE alias = ? AND team_id IS ? AND class IN ({marks})",
            (LIFTED, who, why, alias, team_id, *QUARANTINE)).rowcount
    except sqlite3.OperationalError:        # база старше карточки
        return 0


def alive_team(conn: sqlite3.Connection, team_id: int) -> int:
    """С6: команда слита в другую (`teams.merged_into`) — номер ВЫЖИВШЕЙ, по
    цепочке; не слита — её же номер."""
    for _ in range(10):
        try:
            row = conn.execute("SELECT merged_into FROM teams WHERE id = ?",
                               (team_id,)).fetchone()
        except sqlite3.OperationalError:    # колонки ещё нет
            return team_id
        if not row or row[0] is None:
            return team_id
        team_id = row[0]
    return team_id


def team_id_by_name(conn: sqlite3.Connection, canonical: str) -> int | None:
    """Команда по каноническому имени; слитая — ВЫЖИВШАЯ (С6). Нет — None.
    Ревизия 09.11: поиск по имени отдавал проигравшую, и игра с именем
    `Al Sadd` (flashscore пишет и `Al-Sadd`) садилась на слитую команду."""
    row = conn.execute("SELECT id FROM teams WHERE canonical_name = ?",
                       (canonical,)).fetchone()
    return alive_team(conn, row[0]) if row else None


def merged_map(conn: sqlite3.Connection) -> dict[int, int]:
    """Проигравший при слиянии → выживший (С6, `teams.merged_into`), по цепочке."""
    try:
        raw = {r["id"]: r["merged_into"] for r in conn.execute(
            "SELECT id, merged_into FROM teams WHERE merged_into IS NOT NULL")}
    except sqlite3.OperationalError:        # колонки ещё нет
        return {}
    out: dict[int, int] = {}
    for tid in raw:
        target, hops = raw[tid], 0
        while target in raw and hops < 10:
            target, hops = raw[target], hops + 1
        out[tid] = target
    return out


def team_sports_known(conn: sqlite3.Connection) -> dict[int, set[str]]:
    """Вид спорта команды (F | B | T): по событиям базы и по памяти
    `team_sports` из data/dictionaries.json (книга 097). Команда с двумя
    видами — оба (такая не сужает спор)."""
    import json
    from pathlib import Path
    out: dict[int, set[str]] = {}
    try:
        for r in conn.execute("SELECT t.id AS id, e.sport AS sport FROM events e "
                              "JOIN teams t ON t.id IN (e.team_home_id, e.team_away_id) "
                              "GROUP BY t.id, e.sport"):
            out.setdefault(r["id"], set()).add(r["sport"])
    except sqlite3.OperationalError:
        pass
    path = Path(__file__).resolve().parent.parent / "data" / "dictionaries.json"
    try:
        memory = json.loads(path.read_text(encoding="utf-8")).get("team_sports") or {}
    except (OSError, ValueError, AttributeError):
        memory = {}
    if memory:
        for r in conn.execute("SELECT id, canonical_name FROM teams"):
            sport = memory.get(r["canonical_name"])
            if isinstance(sport, str) and sport:
                out.setdefault(r["id"], set()).add(sport)
    return out


def langs_of(lang) -> frozenset[str] | None:
    """Язык сайта для словаря: один код («sr»), несколько (`site_lang.of`:
    сербохорватский сайт — hr, sr, bs, плюс английский) или None — не знаем."""
    if not lang:
        return None
    if isinstance(lang, str):
        return frozenset({lang})
    out = frozenset(x for x in lang if x)
    return out or None


#: ответы `TeamNames.decide`: «ответ», «спор» (С2), «чужой вид» (С1в),
#: «нет» — написания в словаре нет
DECIDED, DISPUTED, OTHER_SPORT, UNKNOWN = "ответ", "спор", "чужой вид", "нет"


class TeamNames:
    """Словарь команд, прочитанный из базы ОДИН раз: написание → команда с
    учётом языка сайта и вида спорта. Дальше отвечает без базы — годится и
    разбору, который соединение уже закрыл. Строит `team_names(conn)`.

    Одно написание бывает у нескольких команд: «Dinamo» — Загреб, Бухарест
    и Москва, «מכבי חיפה» — Maccabi Haifa и (ошибкой сверки) Maccabi Rishon.
    Раньше выигрывала последняя запись, и #2168 шла «Dynamo Moscow» вместо
    Загреба. Спорное написание словарь не отдаёт — такую игру решает эталон
    flashscore (пакет C, 14.09). Правила карточки словаря 09.11 — в `decide`.

    В работе (разбор, сверка, заливка, витрина) словарь спрашивают БЕЗ языка
    и вида: замер окна 49 на копии живой базы — язык сайта и вид спорта у игр
    без эталона подменяли клуб (карточка, раздел 3 «ЗАМЕР окна 49»). Язык и
    вид — по запросу (`team_alias_map(conn, lang, sport)`), для отчётов.
    Виды спорта читаются, только если их просят (`with_sports`): это 8 МБ
    памяти `team_sports` и запрос по событиям на каждую перестройку."""

    def __init__(self, conn: sqlite3.Connection, with_sports: bool = False):
        bad = quarantined(conn)
        #: проигравший при слиянии → выживший (С6, `merged_into`)
        self.merged = merged_map(conn)
        self.canon_of: dict[int, str] = {}
        #: написание → [(команда, её языки записей)], последняя запись — в конце
        self.rows: dict[str, list[tuple[int, frozenset]]] = {}
        # одинаковые наборы языков — один объект: написаний сто с лишним
        # тысяч, а наборов — десятки (словарь живёт в памяти витрины)
        pool: dict[frozenset, frozenset] = {}
        for r in conn.execute(
                "SELECT a.alias, a.lang, a.team_id FROM team_aliases a "
                "JOIN teams t ON t.id = a.team_id ORDER BY a.id"):
            if (r["alias"], r["lang"], r["team_id"]) in bad:
                continue                                      # С3
            tid = self.merged.get(r["team_id"], r["team_id"])  # С6
            per = self.rows.setdefault(r["alias"], [])
            had = frozenset()
            for i, (t, ls) in enumerate(per):
                if t == tid:
                    had = ls
                    del per[i]
                    break
            langs = had | {r["lang"]}
            per.append((tid, pool.setdefault(langs, langs)))
        for tid, canon in conn.execute("SELECT id, canonical_name FROM teams"):
            self.canon_of[tid] = canon
        #: вид спорта команды (`team_sports_known`) — только по просьбе; у
        #: выжившего — и виды проигравших: их события могли ещё не переехать
        self.sports: dict[int, set[str]] | None = None
        if with_sports:
            self.sports = team_sports_known(conn)
            for loser, winner in self.merged.items():
                if loser in self.sports:
                    self.sports.setdefault(winner, set()).update(self.sports[loser])

    def decide(self, alias: str, lang=None, sport: str | None = None) -> tuple:
        """(вердикт, команды). Правила по порядку, первое сработавшее решает:
          С3. записи карантина (книга ошибок «пара», «коллизия») не участвуют,
              слитая команда (`merged_into`) читается как выжившая — так
              словарь и прочитан (`__init__`);
          С4. написание равно каноническому имени одной из команд (без
              регистра) — она и есть ответ, чужие записи не считаются. Первым:
              иначе запись с языком уводила «Valencia Basket» (es) в Palencia
              (замер на копии живой базы 09.11, окно 49);
          С1. `lang` — язык сайта (код или несколько): из спорных остаются
              команды с записью этого языка; таких нет — с записью без языка;
              осталась одна — ответ;
          С1б. `sport` — вид спорта страницы (F | B | T): из спорных остаются
              команды, известные только в этом виде; `Milan` на баскетболе →
              Olimpia Milano, на футболе → AC Milan (владелец 09.11);
          старое: владелец чужой категории («ASTON VILLA» на Aston Villa U19)
              не считается (06.09); команды одного клуба (похожие имена) —
              последняя запись;
          С2. клубов больше одного — «спор», словарь молчит; команды спора —
              вторым элементом (книга ошибок «двусмысленно» пишет их, `canon`);
          С1в. единственный хозяин, вид страницы известен, а у хозяина вид
              известен и ДРУГОЙ (ровно один) — «чужой вид», словарь молчит.
        Без `lang` и `sport` ответ тот же, что у плоского `team_alias_map`."""
        if sport and self.sports is None:
            raise ValueError("словарь прочитан без видов спорта: team_names(conn, with_sports=True)")
        return self._decide(alias, langs_of(lang), sport or None)

    def _decide(self, alias: str, langs, sport) -> tuple:
        per = self.rows.get(alias)
        if not per:
            return UNKNOWN, []
        ids = [t for t, _ in per]
        if len(ids) > 1:                                              # С4
            own = [t for t in ids if self.canon_of[t].casefold() == alias.casefold()]
            if len(own) == 1:
                ids = own
        if len(ids) > 1 and langs:                                    # С1
            narrowed = [t for t, ls in per if ls & langs] or \
                       [t for t, ls in per if None in ls] or ids
            if len(narrowed) == 1:
                ids = narrowed
        if len(ids) > 1 and sport:                                    # С1б
            by_sport = [t for t in ids if self.sports.get(t) == {sport}]
            if len(by_sport) == 1:
                ids = by_sport
        if len(ids) > 1:
            kind = _kind(alias)
            items = [t for t in ids if _kind(self.canon_of[t]) == kind] or ids
            if len(items) > 1 and _clubs([self.canon_of[t] for t in items]) > 1:
                return DISPUTED, items                                # С2
            ids = items
        if sport:                                                     # С1в
            known = self.sports.get(ids[-1], set())
            if len(known) == 1 and sport not in known:
                return OTHER_SPORT, ids[-1:]
        return DECIDED, ids[-1:]

    def owner(self, alias: str, lang=None, sport: str | None = None) -> tuple[int, str] | None:
        """(id команды, каноническое имя) или None — словарь молчит."""
        verdict, ids = self.decide(alias, lang, sport)
        return (ids[0], self.canon_of[ids[0]]) if verdict == DECIDED else None

    def disputed(self, alias: str, lang=None, sport: str | None = None) -> list[str]:
        """Канонические имена команд спора (С2); пусто — спора нет."""
        verdict, ids = self.decide(alias, lang, sport)
        return [self.canon_of[t] for t in ids] if verdict == DISPUTED else []


def _merge_stamp(conn: sqlite3.Connection) -> tuple:
    """Слияние меняет `merged_into` и переносит написания UPDATE'ом — число
    строк при этом то же, и кэш по счёту строк не заметил бы перемены."""
    try:
        merged = tuple(conn.execute(
            "SELECT count(merged_into), coalesce(sum(merged_into), 0) FROM teams").fetchone())
    except sqlite3.OperationalError:        # колонки ещё нет
        merged = (0, 0)
    return merged + tuple(conn.execute(
        "SELECT coalesce(sum(team_id), 0) FROM team_aliases").fetchone())


def team_names(conn: sqlite3.Connection, with_sports: bool = False) -> TeamNames:
    """Словарь команд (`TeamNames`), пока таблицы не менялись — готовый."""
    return _cached(conn, "team_aliases", lambda: TeamNames(conn, with_sports),
                   extra=("TeamNames", with_sports, _errors_stamp(conn), _merge_stamp(conn)))


def team_alias_map(conn: sqlite3.Connection, lang=None,
                   sport: str | None = None) -> dict[str, tuple[int, str]]:
    """Написание → (id команды, каноническое имя) — только бесспорные
    (правила — `TeamNames.decide`). `lang` — язык сайта (С1), `sport` — вид
    спорта страницы (С1б, С1в); без них — как с 14.09."""
    def build() -> dict[str, tuple[int, str]]:
        book = team_names(conn, with_sports=bool(sport))
        out: dict[str, tuple[int, str]] = {}
        for alias in book.rows:
            hit = book.owner(alias, lang, sport)
            if hit:
                out[alias] = hit
        return out
    return _cached(conn, "team_aliases", build,
                   extra=(langs_of(lang), sport, _errors_stamp(conn), _merge_stamp(conn)))


def team_overrides(conn: sqlite3.Connection, lang=None,
                   sport: str | None = None) -> dict[str, str]:
    """Сырое имя → каноническое. Отдаём готовым словарём: в разборе он
    спрашивается на каждое имя, а ходить в базу столько раз незачем.
    `lang` — язык сайта (С1), `sport` — вид спорта страницы (С1б): спорные
    написания решаются по ним."""
    return {alias: canon for alias, (_, canon)
            in team_alias_map(conn, lang, sport).items()}


#: словари «написание → владелец» считаются заметно (у спорных имён —
#: сходство попарно), а витрина спрашивает их на каждый заход: 0,2–0,4 с на
#: заход (замер 14.09). Держим готовый, пока таблица не изменилась
_CACHE: dict[tuple, dict] = {}


def _cached(conn: sqlite3.Connection, table: str, build, extra=None):
    main = conn.execute("PRAGMA database_list").fetchone()
    key = (main[2], table, extra, *conn.execute(
        f"SELECT count(*), max(id) FROM {table}").fetchone(),
        *conn.execute("SELECT count(*), max(id) FROM teams").fetchone(),
        *conn.execute("SELECT count(*), max(id) FROM leagues").fetchone())
    if key not in _CACHE:
        if len(_CACHE) > 8:
            _CACHE.clear()
        _CACHE[key] = build()
    return _CACHE[key]


def league_alias_map(conn: sqlite3.Connection) -> dict[str, tuple[int, str]]:
    """То же для лиг. «ליגת ווינר» у maariv — футбольная лига, а висело
    написание ещё и на баскетбольном Кубке, и футбол уезжал в баскетбол
    (#2431, #2510). Спор — лиги с разной основой; стадии одного турнира
    (`… - Play Offs`) спором не считаются."""
    def build() -> dict[str, tuple[int, str]]:
        owners: dict[str, dict[int, str]] = {}
        for r in conn.execute(
                "SELECT a.alias, a.league_id, l.canonical_name "
                "FROM league_aliases a JOIN leagues l ON l.id = a.league_id "
                "ORDER BY a.id"):
            per = owners.setdefault(r["alias"], {})
            per.pop(r["league_id"], None)
            per[r["league_id"]] = r["canonical_name"]
        return {alias: list(per.items())[-1] for alias, per in owners.items()
                if len({c.split(" - ")[0] for c in per.values()}) == 1}
    return _cached(conn, "league_aliases", build)


def league_overrides(conn: sqlite3.Connection) -> dict[str, str]:
    return {alias: canon for alias, (_, canon)
            in league_alias_map(conn).items()}


def channel_overrides(conn: sqlite3.Connection) -> dict[tuple[str, int | None], dict]:
    """Ключ — пара (написание, сайт). Именно пара, а не одно написание:
    `Nova Sport 1` на греческом и на чешском телегиде — разные каналы."""
    out: dict[tuple[str, int | None], dict] = {}
    for r in conn.execute(
            "SELECT a.alias, a.source_id, c.canonical_name, c.country "
            "FROM channel_aliases a JOIN channels c ON c.id = a.channel_id"):
        out[(r["alias"], r["source_id"])] = {"name": r["canonical_name"],
                                             "country": r["country"]}
    return out


# ── запись подтверждённого ───────────────────────────────────────────────────

def _attach(conn: sqlite3.Connection, table: str, key: str, owner: int,
            raw: str, lang: str | None, sole: bool) -> None:
    """Написание → владелец, без копий. У `lang=NULL` защита UNIQUE(alias,
    lang) в SQLite не срабатывает, и каждый прогон дописывал ту же строку
    ещё раз: к 14.09 из 223 тыс. строк алиасов команд 174 тыс. были копиями
    (пакет C). `sole` — слово владельца (кнопка ✎): написание того же языка
    снимается с остальных владельцев, иначе спорное имя словарь не отдаёт."""
    if sole:
        conn.execute(f"DELETE FROM {table} WHERE alias = ? AND lang IS ? "
                     f"AND {key} <> ?", (raw, lang, owner))
    if conn.execute(f"SELECT 1 FROM {table} WHERE alias = ? AND lang IS ? "
                    f"AND {key} = ?", (raw, lang, owner)).fetchone():
        return
    conn.execute(f"INSERT OR IGNORE INTO {table} ({key}, alias, lang) "
                 f"VALUES (?, ?, ?)", (owner, raw, lang))


#: слово владельца в книге (С10, С11)
OWNER = "владелец"


def remember_team(conn: sqlite3.Connection, raw: str, canonical: str,
                  country: str | None = None, lang: str | None = None,
                  sole: bool = False, owner_word: bool = False) -> int:
    """Закрепляет «сырое имя → команда». Возвращает номер команды или 0 —
    «команды нет» (0 в событие писать нельзя: `event_team_id`).

    Правила по порядку:
      С5. пара матча — не команда. Канон с тире («La Duchere - Nimes») без
          решения «не пара» не заводится: строка в книгу, ответ 0. Написание
          с тире к обычной команде не цепляется: строка в книгу.
      С10. у имени с тире есть решение «не пара» (`confirm_team_name`:
          классификатор или владелец) — это обычная команда: заводится,
          написания (и с тире) к ней цепляются. `Banik Most - Sous`.
      С6. команда с таким именем уже есть — цепляем к ней; она слита в
          другую (`merged_into`) — к ВЫЖИВШЕЙ (`team_id_by_name`).
      С11. слово владельца: `sole` (кнопка ✎) или `owner_word` (ответ в
          очереди «Названия») снимает карантин с этого написания у этой
          команды (`lift_quarantine`). Только `sole` — ещё и решение «не
          пара» для имени с тире: ✎ — явная правка, а в очереди строка
          студии с двумя матчами не должна стать написанием (книга 094)."""
    pair_canon = is_pair_name(canonical)
    if is_blocked_pair(conn, canonical):
        if not sole:                                                   # С5
            note_error(conn, canonical, "пара", lang=lang, led_to=canonical,
                       note="каноническое имя — пара матча, команда не заведена")
            conn.commit()
            return 0
        confirm_team_name(conn, canonical, "слово владельца (кнопка ✎): "
                          "имя с тире — одна команда", OWNER)          # С10
    team_id = team_id_by_name(conn, canonical)                         # С6
    if team_id is None:
        cur = conn.execute(
            "INSERT INTO teams (canonical_name, slug, country) VALUES (?, ?, ?)",
            (canonical, _unique_slug(conn, "teams", slugify(canonical, "team")),
             country))
        team_id = cur.lastrowid
    if is_pair_name(raw) and not (sole or pair_canon
                                  or is_confirmed_team_name(conn, raw)):
        note_error(conn, raw, "пара", lang=lang, team_id=team_id, led_to=canonical,
                   note="написание — пара матча, к команде не прицеплено")    # С5
    else:
        if sole and is_pair_name(raw) and raw != canonical:
            confirm_team_name(conn, raw, "слово владельца (кнопка ✎): "
                              "написание с тире — имя одной команды", OWNER)  # С10
        _attach(conn, "team_aliases", "team_id", team_id, raw, lang, sole)
        if sole or owner_word:                                         # С11
            lift_quarantine(conn, raw, team_id, OWNER,
                            "карантин снят словом владельца")
    conn.commit()
    return team_id


def event_team_id(conn: sqlite3.Connection, canonical: str) -> int | None:
    """Номер команды для СОБЫТИЯ по имени эталона: находит или заводит
    (`remember_team`), слитая — выжившая (С6). None — команды нет: имя
    эталона — обрывок пары («La Duchere - Feurs», правило С5). Ревизия 09.11:
    в событие писался 0, и сверка падала на внешнем ключе."""
    return remember_team(conn, canonical, canonical) or None


def remember_league(conn: sqlite3.Connection, raw: str, canonical: str,
                    sport: str | None = None, country: str | None = None,
                    lang: str | None = None, sole: bool = False) -> int:
    row = conn.execute("SELECT id FROM leagues WHERE canonical_name = ?",
                       (canonical,)).fetchone()
    if row:
        league_id = row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO leagues (slug, canonical_name, sport, country) "
            "VALUES (?, ?, ?, ?)",
            (_unique_slug(conn, "leagues", slugify(canonical, "league")),
             canonical, sport, country))
        league_id = cur.lastrowid
    # без копий, как у команд: лигу sport5 мост учит на каждой заливке (14.09)
    _attach(conn, "league_aliases", "league_id", league_id, raw, lang, False)
    conn.commit()
    return league_id


def remember_channel(conn: sqlite3.Connection, raw: str, canonical: str,
                     country: str, source_id: int | None = None,
                     language: str | None = None) -> int:
    """Канал ищем по паре (имя, страна) — по одному имени нельзя, см. шапку.
    Страна обязательна: без неё греческий и чешский `Nova Sport 1` сольются."""
    if not country:
        raise ValueError("каналу нужна страна: одно имя бывает у разных каналов")
    row = conn.execute(
        "SELECT id FROM channels WHERE canonical_name = ? AND country = ?",
        (canonical, country)).fetchone()
    if row:
        channel_id = row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO channels (canonical_name, slug, country, language) "
            "VALUES (?, ?, ?, ?)",
            (canonical,
             _unique_slug(conn, "channels",
                          slugify(f"{canonical}-{country}", "channel")),
             country, language))
        channel_id = cur.lastrowid
    conn.execute("INSERT OR IGNORE INTO channel_aliases (channel_id, alias, "
                 "source_id) VALUES (?, ?, ?)", (channel_id, raw, source_id))
    conn.commit()
    return channel_id


#: «Не матч» действует вокруг дня матча: столько в обе стороны
SKIP_WINDOW = timedelta(hours=36)


def _match_moment(suggestion: str | None):
    """Момент матча из подсказки очереди («2026-10-10 19:30 | …»); нет — None."""
    try:
        return datetime.strptime((suggestion or "")[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def norm_pair(raw_label: str) -> str:
    """Пара команд из строки очереди: часть до первого « | », схлопнутые
    пробелы. Порядок команд не трогаем — так ключи совместимы с уже
    накопленными подсказками. «Kocaelispor - Samsunspor | beIN SPORTS 1
    (beinsports.com.tr)» → «Kocaelispor - Samsunspor»."""
    return " ".join((raw_label or "").split("|")[0].split())


def remember_sport(conn: sqlite3.Connection, raw_value: str,
                   letter: str, match_day: str = "") -> None:
    """Владелец сказал, какой это спорт. Ключ — пара команд, как её написал
    сайт (канал и домен отбрасываем: та же пара приходит и с других каналов).

    `match_day` — день матча из подсказки очереди: ответ действует только
    вокруг этой даты, а не вечно. Тель-авивское дерби бывает теннисным
    сегодня и футбольным через месяц — вечная буква делала бы будущий
    футбол теннисом (жалоба владельца 15.09, кейс «מכבי ת"א - הפועל ת"א»).
    Пустой день — подсказка без срока (старые записи живут как раньше).
    """
    пара = norm_pair(raw_value)
    letter = (letter or "").strip().upper()[:1]
    if not пара or letter not in ("F", "B", "T"):
        raise ValueError("нужен вид спорта: F, B или T")
    conn.execute("INSERT INTO sport_hints (pair, sport, match_day) "
                 "VALUES (?, ?, ?) "
                 "ON CONFLICT (pair) DO UPDATE SET sport = excluded.sport, "
                 "match_day = excluded.match_day",
                 (пара, letter, (match_day or "").strip() or None))
    conn.commit()


def sport_hints(conn: sqlite3.Connection) -> dict[str, str]:
    """Все подсказки владельца: пара команд → буква вида спорта."""
    return {r["pair"]: r["sport"] for r in
            conn.execute("SELECT pair, sport FROM sport_hints")}


REMEMBER = {"team": remember_team, "league": remember_league}


# ── очередь модерации ────────────────────────────────────────────────────────

def enqueue(conn: sqlite3.Connection, kind: str, raw_value: str,
            suggestion: str = "", source_id: int | None = None) -> bool:
    """Кладёт непознанное имя в очередь. Возвращает, добавилась ли новая
    строка: одно и то же имя приходит с каждым обходом, и плодить дубли
    нельзя — очередь станет нечитаемой."""
    if kind not in KINDS:
        raise ValueError(f"неизвестный вид записи: {kind}")
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return False
    if kind == "sport":
        return _enqueue_sport(conn, raw_value, suggestion)
    exists = conn.execute(
        "SELECT 1 FROM moderation WHERE kind = ? AND raw_value = ? "
        "AND (source_id IS ? OR source_id = ?) AND status IN ('open', 'later')",
        (kind, raw_value, source_id, source_id)).fetchone()
    if exists:
        return False
    # Уже разобранное второй раз не спрашиваем: владелец сказал «пропустить» —
    # значит эта строка не имя команды, и напоминать о ней каждое утро незачем.
    done = conn.execute(
        "SELECT 1 FROM moderation WHERE kind = ? AND raw_value = ? "
        "AND status IN ('done', 'skipped')", (kind, raw_value)).fetchone()
    if done:
        return False
    conn.execute("INSERT INTO moderation (kind, raw_value, source_id, suggestion) "
                 "VALUES (?, ?, ?, ?)", (kind, raw_value, source_id, suggestion))
    conn.commit()
    return True


def _enqueue_sport(conn: sqlite3.Connection, raw_value: str,
                   suggestion: str) -> bool:
    """Очередь «вид спорта» — одна строка на ПАРУ команд, а не на канал.

    Тот же матч приходит с нескольких каналов, и раньше каждый канал заводил
    свою строку — на «סופר קאפ» отвечали, а копия с соседнего канала висела
    дальше (жалоба владельца 15.09). Пары сличаем в Python: открытых строк
    единицы сотен, а LIKE потребовал бы экранировать имена команд.
    """
    пара = norm_pair(raw_value)
    if not пара:
        return False
    for r in conn.execute("SELECT id, raw_value, suggestion FROM moderation "
                          "WHERE kind = 'sport' "
                          "AND status IN ('open', 'later')"):
        if norm_pair(r["raw_value"]) != пара:
            continue
        # та же пара уже ждёт ответа: строку не плодим, но если пришёл более
        # поздний матч — освежаем дату в подсказке, чтобы чистка «прошло»
        # не закрыла вопрос по старому времени
        if (suggestion or "")[:16] > (r["suggestion"] or "")[:16]:
            conn.execute("UPDATE moderation SET suggestion = ? WHERE id = ?",
                         (suggestion, r["id"]))
            conn.commit()
        return False
    # «Не матч» (skipped) молчит только вокруг дня того матча (±1,5 суток,
    # как ответ видом спорта): та же пара в другой день бывает настоящей
    # игрой — «Le Mans - Lorient» это и гонка-слово, и футбол Лиги 2
    # (вопрос владельца 08.10). Отсеянное без даты (старые записи) молчит
    # как раньше, навсегда. Ответ Ф/Б/Т (done) держит паузу 7 дней: вид
    # спорта привязан к дате матча, в новом туре пару спросят заново.
    новый_день = _match_moment(suggestion)
    for r in conn.execute("SELECT raw_value, status, suggestion FROM moderation "
                          "WHERE kind = 'sport' AND (status = 'skipped' OR "
                          "(status = 'done' AND created_at >= "
                          "datetime('now', '-7 days')))"):
        if norm_pair(r["raw_value"]) != пара:
            continue
        if r["status"] == "skipped":
            старый_день = _match_moment(r["suggestion"])
            if новый_день and старый_день and abs(
                    новый_день - старый_день) > SKIP_WINDOW:
                continue                 # другой день — спросим заново
        return False
    conn.execute("INSERT INTO moderation (kind, raw_value, suggestion) "
                 "VALUES ('sport', ?, ?)", (raw_value, suggestion))
    conn.commit()
    return True


def _sport_siblings(conn: sqlite3.Connection, raw_value: str) -> list[int]:
    """Номера всех открытых/отложенных строк той же пары команд."""
    пара = norm_pair(raw_value)
    return [r["id"] for r in conn.execute(
        "SELECT id, raw_value FROM moderation WHERE kind = 'sport' "
        "AND status IN ('open', 'later')")
        if norm_pair(r["raw_value"]) == пара]


def open_items(conn: sqlite3.Connection, kind: str = "",
               limit: int = 200, first: int = 0,
               later: bool = False) -> list[sqlite3.Row]:
    """`first` — номер записи, которую надо показать ПЕРВОЙ: с витрины
    приходят прямо на неё (оранжевая строка игры, 10.09), и искать её среди
    двухсот других владелец не должен. Если она не попала в выборку по
    лимиту — добавляем отдельно."""
    # `later` — вкладка «Отложенные»: то, на что владелец нажал «Не знаю»
    where = "WHERE m.status = 'later'" if later else "WHERE m.status = 'open'"
    params: list = []
    if kind:
        where += " AND m.kind = ?"
        params.append(kind)
    params.append(limit)
    # Страну сайта отдаём как заготовку для канала: чаще всего канал той же
    # страны, что и телегид. Владелец правит, когда канал иностранный.
    rows = conn.execute(
        f"SELECT m.*, s.domain, s.country AS source_country FROM moderation m "
        f"LEFT JOIN sources s ON s.id = m.source_id {where} "
        f"ORDER BY m.kind, m.raw_value LIMIT ?", params).fetchall()
    if not first:
        return rows
    picked = [r for r in rows if r["id"] == first]
    if not picked:
        picked = conn.execute(
            "SELECT m.*, s.domain, s.country AS source_country FROM moderation m "
            "LEFT JOIN sources s ON s.id = m.source_id "
            "WHERE m.id = ? AND m.status IN ('open', 'later')",
            (first,)).fetchall()
    return list(picked) + [r for r in rows if r["id"] != first]


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT kind, COUNT(*) c FROM moderation "
                        "WHERE status = 'open' GROUP BY kind")
    return {r["kind"]: r["c"] for r in rows}


def resolve(conn: sqlite3.Connection, item_id: int, canonical: str,
            country: str = "", answered_by: str = "") -> None:
    """Владелец подтвердил имя: закрепляем навсегда и закрываем строку.

    `answered_by` — кто ответил, если не владелец: «ответила программа:
    правило 5 (слово «FIBA»)» (`app/sport_question.py`). Путь записи тот
    же, что у кнопки, — пометка только видна в админке."""
    item = conn.execute("SELECT * FROM moderation WHERE id = ?",
                        (item_id,)).fetchone()
    if item is None:
        raise LookupError(f"нет записи модерации {item_id}")
    canonical = (canonical or "").strip()
    if not canonical:
        raise ValueError("пустое название")

    if item["kind"] == "sport":
        # тут закрепляется не название, а вид спорта: «F», «B» или «T».
        # День матча вынимаем из подсказки ДО того, как перезапишем её буквой:
        # ответ действует вокруг этой даты, а не вечно (владелец 15.09)
        день = re.search(r"\d{4}-\d{2}-\d{2}", item["suggestion"] or "")
        remember_sport(conn, item["raw_value"], canonical,
                       день.group(0) if день else "")
        # один ответ закрывает ту же пару со всех каналов
        ids = _sport_siblings(conn, item["raw_value"]) or [item_id]
        conn.executemany("UPDATE moderation SET status = 'done', "
                         "suggestion = ?, answered_by = ? WHERE id = ?",
                         [(canonical, answered_by or None, i) for i in ids])
        conn.commit()
        return
    if item["kind"] == "channel":
        remember_channel(conn, item["raw_value"], canonical, country,
                         item["source_id"])
    else:
        remember = REMEMBER.get(item["kind"])
        if remember is None:
            raise ValueError(f"нечего закреплять для вида {item['kind']}")
        if item["kind"] == "team":
            # С11: ответил сам владелец (пометки программы нет) — его слово
            # снимает карантин с этого написания у этой команды
            remember_team(conn, item["raw_value"], canonical,
                          owner_word=not answered_by)
        else:
            remember(conn, item["raw_value"], canonical)

    conn.execute("UPDATE moderation SET status = 'done', suggestion = ?, "
                 "answered_by = ? WHERE id = ?",
                 (canonical, answered_by or None, item_id))
    conn.commit()


def _spread_sport(conn: sqlite3.Connection, item_id: int,
                  status: str, answered_by: str = "") -> list[int]:
    """У вида спорта статус ставится всей паре: тот же матч висит копиями с
    разных каналов, и решать его дважды незачем (владелец 15.09)."""
    item = conn.execute("SELECT kind, raw_value FROM moderation WHERE id = ?",
                        (item_id,)).fetchone()
    ids = ([item_id] if item is None or item["kind"] != "sport"
           else _sport_siblings(conn, item["raw_value"]) or [item_id])
    conn.executemany(f"UPDATE moderation SET status = '{status}', "
                     "answered_by = ? WHERE id = ?",
                     [(answered_by or None, i) for i in ids])
    return ids


def later(conn: sqlite3.Connection, item_id: int) -> None:
    """«Не знаю» — отложить: запись не удаляется и не считается решённой,
    просто уходит из основного списка во вкладку «Отложенные», откуда её
    можно достать и ответить позже (просьба владельца 11.09)."""
    _spread_sport(conn, item_id, "later")
    conn.commit()


def back_to_open(conn: sqlite3.Connection, item_id: int) -> None:
    """Вернуть отложенную или отсеянную запись в основной список."""
    conn.execute("UPDATE moderation SET status = 'open' WHERE id = ? "
                 "AND status IN ('later', 'skipped')", (item_id,))
    conn.commit()


def later_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM moderation "
                        "WHERE status = 'later'").fetchone()[0]


def skip(conn: sqlite3.Connection, item_id: int,
         answered_by: str = "") -> None:
    """«Это не команда» / «не матч» — например заголовок турнира вместо пары
    клубов. Строку не удаляем: иначе она вернётся следующим же обходом.
    `answered_by` — как у `resolve`: пометка, если закрыла программа."""
    _spread_sport(conn, item_id, "skipped", answered_by)
    conn.commit()


#: начало пометки `answered_by`, когда вопрос решила сама программа
#: (`app/sport_question.py`); уборка («прошло», «дубль») пишет своё
PROGRAM_MARK = "ответила программа"
#: начало пометки уборки очереди (`scripts/review_queue.py`): «уборка
#: очереди: прошло» — тоже закрыла программа, но без ответа
CLEANUP_MARK = "уборка очереди"
#: сколько дней закрытое ПРОГРАММОЙ живёт в базе и видно во вкладках
#: «Отсеянные» и «Ответила программа» (владелец 06.10: «зачем там столько
#: информации, которая уже обработана?»; решение 08.10). Ответы владельца
#: живут бессрочно — это память программы, без них она переспросит
FRESH_DAYS = 7


def auto_answered(conn: sqlite3.Connection, kind: str = "sport",
                  days: int = FRESH_DAYS, limit: int = 100) -> list[sqlite3.Row]:
    """Что программа за последние `days` дней ответила сама (пометка
    `PROGRAM_MARK`): и ответы видом спорта, и отсеянное. Вкладка «Ответила
    программа» на странице «Названия» — владелец видит, что решено без него.
    `kind` пустой — все виды."""
    return conn.execute(
        "SELECT m.*, s.domain, s.country AS source_country FROM moderation m "
        "LEFT JOIN sources s ON s.id = m.source_id "
        "WHERE (? = '' OR m.kind = ?) AND m.answered_by LIKE ? "
        "AND m.status IN ('done', 'skipped') "
        "AND m.created_at >= datetime('now', ?) "
        "ORDER BY m.id DESC LIMIT ?",
        (kind, kind, PROGRAM_MARK + "%", f"-{int(days)} days",
         limit)).fetchall()


def skipped_items(conn: sqlite3.Connection, kind: str = "sport",
                  limit: int = 100, days: int = FRESH_DAYS) -> list[sqlite3.Row]:
    """Вкладка «Отсеянные»: что закрыто без ответа — рукой («Не матч») или
    автоматической чисткой. Всё видно и возвращается кнопкой «Вернуть» —
    условие владельца 15.09 к любому автоотсеву. `kind` пустой — все виды.
    Показываем только свежее — последние `days` дней (владелец 06.10:
    вкладка разрослась до 1608 строк); старое в базе остаётся, если это
    ответ владельца, а закрытое программой стирает `purge_program_closed`."""
    return conn.execute(
        "SELECT m.*, s.domain, s.country AS source_country FROM moderation m "
        "LEFT JOIN sources s ON s.id = m.source_id "
        "WHERE m.status = 'skipped' AND (? = '' OR m.kind = ?) "
        "AND m.created_at >= datetime('now', ?) "
        "ORDER BY m.id DESC LIMIT ?",
        (kind, kind, f"-{int(days)} days", limit)).fetchall()


def skipped_count(conn: sqlite3.Connection, kind: str = "sport",
                  days: int = FRESH_DAYS) -> int:
    """Счётчик вкладки «Отсеянные» — те же свежие строки, что и в списке."""
    return conn.execute("SELECT COUNT(*) FROM moderation "
                        "WHERE status = 'skipped' AND (? = '' OR kind = ?) "
                        "AND created_at >= datetime('now', ?)",
                        (kind, kind, f"-{int(days)} days")).fetchone()[0]


def purge_program_closed(conn: sqlite3.Connection,
                         days: int = FRESH_DAYS) -> int:
    """Закрытое ПРОГРАММОЙ старше `days` дней — из базы вон (решение
    владельца 08.10: «а в чём смысл, что оно будет копиться?»).

    Трогаем только строки с пометкой программы (`PROGRAM_MARK`,
    `CLEANUP_MARK`); ответы владельца (`answered_by` пустой) живут вечно.
    Память программы лежит не здесь: ответ видом спорта — в `sport_hints`,
    имя — в словаре, а «не матч» и так молчит лишь ±1,5 суток вокруг игры.
    Стёртый вопрос программа при нужде задаст и решит заново — тем же
    правилом, что и в первый раз. Возвращает, сколько строк стёрто."""
    cur = conn.execute(
        "DELETE FROM moderation WHERE status IN ('done', 'skipped') "
        "AND (answered_by LIKE ? OR answered_by LIKE ?) "
        "AND created_at < datetime('now', ?)",
        (PROGRAM_MARK + "%", CLEANUP_MARK + "%", f"-{int(days)} days"))
    conn.commit()
    return cur.rowcount


def clear_open(conn: sqlite3.Connection, kind: str = "sport") -> int:
    """Кнопка «Очистить список»: СТЕРЕТЬ открытые строки вкладки.

    Именно удалить, а не пометить (уточнение владельца 15.09): ничего не
    запоминается и никакая игра не блокируется — если матч ещё в сетке и
    всё ещё непонятен, следующий обход принесёт строку заново. Отложенные
    («Не знаю») не трогаем."""
    cur = conn.execute("DELETE FROM moderation "
                       "WHERE kind = ? AND status = 'open'", (kind,))
    conn.commit()
    return cur.rowcount

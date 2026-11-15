# -*- coding: utf-8 -*-
"""Сборка: страница → готовые строки ленты (ТЗ разд. 5, шаги 3–5).

Здесь три шага пайплайна, которые одинаковы для всех сайтов:

    парсер сайта  →  отсев (app/live.py)  →  вид спорта (app/sport.py)  →  время

Что делает каждый — написано в своём модуле. Здесь только порядок и то, что
получается на выходе: строка `Row`, у которой уже есть время в UTC и в Киеве,
пара команд и понятная причина, если событие не взяли.

Вид спорта («наш или чужой») решается в ОДНОМ месте — `sport.Sports.decide`,
десять правил по номерам. `classify` для него только собирает улики: текст
строки, пару, ответ эталона flashscore (`app/reference.py`), лигу из словаря
лиг, подсказку владельца. Номер сработавшего правила остаётся в строке
(`Row.sport_rule`).

Названия команд остаются здесь в том виде, в каком стояли на сайте (поля
`home` / `away`, как `*_auto` в базе) — с одной поправкой: если турнир
женский или возрастной, метка (` W`, ` U19`) дописывается к именам сразу.
Иначе она теряется навсегда: дальше по конвейеру названия турнира уже нет,
а женский матч без метки склеится с мужским.

Приведением имён к канону (`Мидълзбро` → `Middlesbrough`) занимаются
`app/names.py` и словари, склейкой одинаковых игр — `app/merge.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import daytime, leagues, live, names, site_lang, sport
from .parsers import Program
from . import canon
from .reference import MARKS_HOW, Confirmed, Reference, _strip_marks


@dataclass
class Row:
    program: Program
    ok: bool                       # берём в ленту?
    reason: str = ""               # почему нет — понятной строкой
    needs_review: bool = False     # в очередь модерации, а не в мусор
    live_marker: str = ""
    home: str = ""
    away: str = ""
    league: str = ""               # ядро названия лиги, без вида спорта и сезона
    league_category: str = ""      # `W`, `U19` — из названия турнира
    sport: str = ""                # F | B | T
    sport_word: str = ""           # слово, по которому определили
    sport_source: str = ""         # откуда буква: ref (эталон flashscore) |
                                   # word (слово на сайте) | league (лига в
                                   # словаре) | women | hint
    sport_rule: int = 0            # номер сработавшего правила из
                                   # `sport.Sports.decide`
    sport_group: str = ""          # чужой вид спорта словами («хоккей») —
                                   # вкладка «Other Sport» (владелец 03.10)
    team_word: str = ""            # слово чужого вида, признанное именем
                                   # команды из пары («Le Mans», 06.10)
    by_reference: str = ""         # эталон подтвердил эфир/пару/вид спорта:
                                   # «пара», «одна сторона» (правило (в),
                                   # `Reference.confirm`, 20.10) или «метки
                                   # из эталона» (`reference.MARKS_HOW`:
                                   # пара сошлась без пола и возраста
                                   # эталона, метка дописана к именам, 24.10)
    start_utc: datetime | None = None
    start_kyiv: datetime | None = None

    @property
    def when(self) -> str:
        return self.start_kyiv.strftime("%d.%m %H:%M") if self.start_kyiv else "—:—"


def hint_fresh(day: str | None, start_kyiv: datetime | None) -> bool:
    """Действует ли подсказка владельца на матч с этим временем.

    Подсказка привязана к дню матча и живёт ±36 часов вокруг него: та же
    пара в другом туре может играть другой спорт — теннисное дерби
    Тель-Авива не должно делать теннисом будущий футбол (владелец 15.09).
    Подсказка без дня — бессрочная (записи до этой правки)."""
    if not day:
        return True
    if start_kyiv is None:
        return False
    try:
        полдень = datetime.strptime(day, "%Y-%m-%d").replace(hour=12)
    except ValueError:
        return True                      # кривую дату считаем бессрочной
    return abs(start_kyiv.replace(tzinfo=None) - полдень) <= timedelta(hours=36)


#: причины отсева, которые эталон вправе оспорить (правило (в)): сайт не
#: сказал «эфир» или пара не прочиталась. Слово записи, студия и стоп-слово —
#: прямые слова сайта, их не трогаем
ASK_REFERENCE_REASONS = ("нет маркера прямого эфира", "не видно пары команд")
#: книга 095 (#9541): сторона пары совпала с именем канала — заставка канала
CHANNEL_SIDE = "сторона пары — имя канала"


def _plain(text: str) -> str:
    """Имя без регистра, пробелов и знаков: «Sport 2» = «SPORT-2»."""
    return "".join(ch for ch in (text or "").casefold() if ch.isalnum())


def channel_side(channel: str, home: str, away: str,
                 reference: Reference | None = None) -> bool:
    """Одна из сторон пары — имя канала, на котором идёт строка («Sport 2 -
    Program Sportiv» на Sport 2, ipko #9541): это передача канала, не матч.
    Вторую сторону эталон знает как команду — клубный канал показывает свой
    матч («KB Peja»), строка остаётся."""
    key = _plain(channel)
    if not key:
        return False
    hit = [side for side, name in (("home", home), ("away", away))
           if _plain(name) and _plain(name) == key]
    if not hit:
        return False
    other = away if hit[0] == "home" else home
    return not (reference is not None and reference.knows_team(other))
#: что ставит отсев строке, эфир которой подтвердил эталон, а не сайт
REFERENCE_MARKER = "эталон"
#: сезон в подписи: «2003/04», «2019-2020», «1998/99». Прошлый сезон — это
#: классика, а не эфир: «Klasici Premijer Lige: Chelsea - Tottenham, 2003/04»
#: на Arena Sport 1 за полчаса до живого Chelsea — Tottenham эталон
#: подтвердил бы как эфир (проверка перед выкладкой, сбор #301, 20.10)
_SEASON = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[/–-]\s*(?:\d{2}|(?:19|20)\d{2})(?!\d)")


def past_season(text: str, when: datetime | None) -> bool:
    """Подпись называет ПРОШЛЫЙ сезон — показ не эфир. Текущий сезон
    начинается с июля: в марте 2026 «2025/26» — ещё текущий, в октябре 2026
    «2025/26» — уже прошлый. Год основания клуба («Grazer AK 1902») без
    второй половины сезоном не считается."""
    if when is None:
        return False
    current = when.year if when.month >= 7 else when.year - 1
    return any(int(m.group(1)) < current for m in _SEASON.finditer(text or ""))


def pair_guesses(program: Program, with_field: bool = True) -> list[tuple[str, str]]:
    """Книга 124: ВСЕ догадки о паре строки для вопроса эталону, по порядку
    надёжности. Откуда читаем:
      1. поле пары разборщика (`with_field`; у `title_over_pair` его нет —
         эту пару эталон уже не узнал);
      2. заголовок — все читатели (`live.split_candidates`);
      3. первая строка описания (`live.lead`): 47 разборщиков из 89 умеют
         брать пару из описания, каждый по-своему, — общий читатель делает
         это для всех;
      4. фразы-шаблоны «A встречается с B» в описании (`live.phrase_pairs`).
    Повторы убраны. В ленту догадка идёт, только если её подтвердил эталон."""
    texts = []
    if with_field:
        texts.append((program.match_raw or "").strip())
    texts.append((program.title or "").strip())
    texts.append(live.lead(program.description or ""))
    out: list[tuple[str, str]] = []
    for text in texts:
        for pair in live.split_candidates(text):
            if pair not in out:
                out.append(pair)
    for pair in live.phrase_pairs(program.description or ""):
        if pair not in out:
            out.append(pair)
    return out


#: книга 122: пометка строки «пару разборщика заменила пара из заголовка» —
#: в ней прежняя пара разборщика (для журнала разбора)
TITLE_PAIR = "пара_из_заголовка"


#: книга 133: пометка строки «у пары срезаны лишние слова» — словарь
#: {"где": край, "срезано": слова, "было": пара до среза, "по": "эталон" | "книга"}
TRIMMED = "обрезка"
#: книга 136: классы книги знаний (`dictionary_errors.class`) — лишние слова,
#: которые уже срезались у пар и подтвердились эталоном
KNOWN_HOME = live.KNOWN_HOME
KNOWN_AWAY = live.KNOWN_AWAY


def _entry_id(got: Confirmed) -> str:
    """Матч эталона одним ключом — чтобы понять, один ли матч дали срезы."""
    entry = got.entry or {}
    return str(entry.get("fs_id") or f"{entry.get('home')}|{entry.get('away')}|{got.start}")


#: книга 133, О9: с такого сходства слово урезанной стороны считается тем же
#: словом, что в имени команды эталона
EXACT_WORD = 90


def _junk_like(words: str) -> bool:
    """О8: срезаемое похоже на лишнее, а не на часть имени: слов не меньше
    двух либо в слове есть цифра («15/11/2026»)."""
    return len(words.split()) >= 2 or any(ch.isdigit() for ch in words)


def _team_names(got: Confirmed) -> tuple[list[str], list[str]]:
    """О9: все написания хозяев и гостей матча эталона — английское и
    местные (`canon.local_pairs`), без пометок пола и возраста, в порядке
    сторон СТРОКИ (эталон мог сойтись наоборот — `swapped`)."""
    entry = got.entry or {}
    home, away = [entry.get("home") or ""], [entry.get("away") or ""]
    for _lang, local_home, local_away in canon.local_pairs(entry):
        home.append(local_home)
        away.append(local_away)
    home = [name for name in (_strip_marks(x) for x in home) if name]
    away = [name for name in (_strip_marks(x) for x in away) if name]
    return (away, home) if got.swapped else (home, away)


def _exactly(side: str, team_names: list[str]) -> bool:
    """О9: сторона после среза — РОВНО имя команды: слов столько же, сколько
    в одном из написаний эталона, и каждое сходится со своим (`EXACT_WORD`)."""
    words = _strip_marks(side).split()
    for name in team_names:
        other = name.split()
        if len(other) == len(words) and all(
                names.similarity(a, b) >= EXACT_WORD for a, b in zip(words, other)):
            return True
    return False


#: книга 133, О10: с такого сходства срезаемое слово считается словом из
#: имени команды эталона
NAME_WORD = 80


def _in_name(words: str, team_names: list[str]) -> bool:
    """О10: какое-то из срезаемых слов стоит в имени команды эталона (в
    любом её написании). Слова в одну букву («e», «-») не в счёт; короткие
    (до трёх букв: «FC», «RC», «La») — только буква в букву; длинные —
    по сходству `NAME_WORD` («Coruna» = «Coruña», «Brasov» = «Brașov»)."""
    team_words = {word.strip(live._TRIM_EDGE).casefold()
                  for name in team_names for word in name.split()}
    for word in words.split():
        word = word.strip(live._TRIM_EDGE)
        if len(word) < 2:
            continue
        if len(word) <= 3:
            if word.casefold() in team_words:
                return True
        elif any(len(other) > 3 and names.similarity(word, other) >= NAME_WORD
                 for other in team_words):
            return True
    return False


def _cuts_name(where: str, cut: str, got: Confirmed) -> bool:
    """О10: срез задел имя команды — среди срезаемых слов есть слово из
    имени этой стороны в записи эталона."""
    home_names, away_names = _team_names(got)
    if where == live.TRIM_BOTH:
        front, _, back = cut.partition(" … ")
    else:
        front, back = (cut, "") if where == live.TRIM_HOME else ("", cut)
    return _in_name(front, home_names) or _in_name(back, away_names)


def _exact_after(where: str, new_home: str, new_away: str, got: Confirmed) -> bool:
    """О9: у каждой урезанной стороны осталось ровно имя команды эталона."""
    home_names, away_names = _team_names(got)
    if where in (live.TRIM_HOME, live.TRIM_BOTH) and not _exactly(new_home, home_names):
        return False
    if where in (live.TRIM_AWAY, live.TRIM_BOTH) and not _exactly(new_away, away_names):
        return False
    return True


def trim_by_reference(pairs: list[tuple[str, str]], reference: Reference | None,
                      start_kyiv: datetime | None, league_category: str = "",
                      agree: Confirmed | None = None, stop=None):
    """Книга 133 (общее правило для ВСЕХ сайтов и языков, слово владельца
    15.11: «все ошибки разбора, которые происходят на конкретных сайтах,
    должны быть предусмотрены для всех сайтов»).

    К паре снаружи прилипли лишние слова без разделителя (турнир, рубрика,
    стадия, дата, слова передачи) — эталон такую пару не узнаёт. Пробуем
    срезы (`live.outer_trims`) и спрашиваем эталон. Правила:
      О1. зовут в двух случаях: (а) ни одна догадка строки не сошлась с
          эталоном целиком; (б) пара сошлась целиком, но, возможно, лишь
          потому, что сравнение имён терпит лишние слова («Bayern München
          Das Spiel» = «Bayern München») — тогда срез обязан дать ТОТ ЖЕ
          матч (О4). Без (б) мусор оставался в имени и учился словарём как
          написание команды («Irland Der Countdown»);
      О2. срезы — только снаружи пары: начало хозяев, конец гостей;
      О3. срез принят, только если урезанную пару эталон подтвердил на это
          время ЦЕЛИКОМ («пара»), и ВСЕ сошедшиеся срезы строки — один и тот
          же матч. Разные срезы дали разные матчи — не гадаем, None;
      О4. строку эталон уже узнал «одной стороной» (`agree`) — срез обязан
          дать ТОТ ЖЕ матч, иначе None;
      О5. из принятых срезов (О9) берётся НАИМЕНЬШИЙ — у команды остаётся
          самое полное из её написаний («Bayern München», а не «Bayern»).
          Стороны — в порядке эталона;
      О6. сторону, которую эталон знает как команду (`knows_team`: «Real
          Madrid»), не режем: такая пара не сошлась потому, что это другой
          матч, а не потому, что к имени что-то прилипло. Иначе «Real
          Madrid - Barcelona» (повтор классики) срезом до «Madrid» ушло бы
          к идущему в тот же час «Atl. Madrid — Barcelona»;
      О7. в срезанных словах стоит стоп-слово передачи (`stop(слова)` —
          студия, обзор, «Die Pre-Game Show») — срез не берём: строка — не
          сам матч, а передача вокруг него;
      О8. одно слово без цифр по эталону НЕ срезается (`_junk_like`): так
          выглядит часть самого имени — город, спонсор, имя игрока («UBT
          Cluj», «Sheffield Wednesday», «Kauno Žalgiris», «Daniil
          Medvedev»; замер на сборе 15.11 — все семь срезов по одному слову
          были частями имён либо словом передачи «Previo»). Лишнее снаружи
          пары — это цепочка слов («ligová fáze», «Das Spiel») или слово с
          цифрами («15/11/2026»). Одиночное лишнее слово («NBA») режется
          только по книге знаний, куда его заносят данными;
      О9. ТОЧНАЯ ГРАНИЦА: срез принят, только если после него сторона —
          ровно имя команды, как его пишет эталон на одном из языков
          (`_exactly`: слов столько же, каждое сходится со своим). Сравнение
          имён терпит и лишние слова, и недостающие — без этого правила
          срезались куски настоящих имён (сбор 15.11: «Taça de Portugal -
          FC Porto» → «Porto», «Manchester C UEFA Women's Champions League»
          → «Manchester», «Enea Łaciate Astoria Bydgoszcz» → «Bydgoszcz»),
          и они ушли бы в книгу знаний как «лишние слова». Сайт пишет на
          языке, которого у эталона нет (албанский, иврит), — срезов по
          эталону нет, остаются слова из книги знаний;
      О10. срезаемые слова не встречаются в имени этой команды ни на одном
          языке эталона (`_cuts_name`). Эталон часть клубов в части языков
          пишет коротко («Bielefeld», «Brasov», «RC Deportivo») — по
          одному О9 срезались бы настоящие части имён: «DSC Arminia»,
          «CSM Corona», «La Coruna» (сбор 15.11), а датское «Før FC
          Nordsjælland» (передача перед матчем) проходило как матч.
    Возвращает (хозяева, гости, ответ эталона, пометка `TRIMMED`) или None."""
    if reference is None or start_kyiv is None:
        return None
    hits = []
    for home, away in pairs:
        if not home or not away or not reference.may_know(home, away):
            continue
        fixed = {live.TRIM_HOME: reference.knows_team(home),                  # О6
                 live.TRIM_AWAY: reference.knows_team(away)}
        fixed[live.TRIM_BOTH] = fixed[live.TRIM_HOME] or fixed[live.TRIM_AWAY]
        for where, cut, new_home, new_away in live.outer_trims(home, away):   # О2
            if fixed[where] or (stop is not None and stop(cut)):              # О6, О7
                continue
            if not all(_junk_like(part) for part in cut.split(" … ")):        # О8
                continue
            got = reference.confirm(leagues.with_category(new_home, league_category),
                                    leagues.with_category(new_away, league_category),
                                    start_kyiv)
            if got is not None and got.how == "пара" \
                    and _exact_after(where, new_home, new_away, got) \
                    and not _cuts_name(where, cut, got):                      # О3, О9, О10
                clean = " … ".join(part.strip(live._TRIM_EDGE) for part in cut.split(" … "))
                hits.append((new_home, new_away, got,
                             {"где": where, "срезано": clean,
                              "было": f"{home} - {away}", "по": "эталон"}))
    if not hits or len({_entry_id(h[2]) for h in hits}) != 1:                 # О3
        return None
    home, away, got, mark = min(                                              # О5
        hits, key=lambda h: len(h[3]["срезано"].replace(" … ", " ").split()))
    if agree is not None and _entry_id(agree) != _entry_id(got):              # О4
        return None
    if got.swapped:
        home, away = away, home
    return home, away, got, mark


def _starts_with(words: list[str], phrase: list[str]) -> bool:
    return len(words) > len(phrase) and \
        [w.casefold() for w in words[:len(phrase)]] == phrase


def trim_by_book(home: str, away: str, known: dict | None,
                 langs: frozenset | None):
    """Книга 136: срез по КНИГЕ ЗНАНИЙ — без эталона. `known` — лишние слова,
    которые уже срезались у пар и подтвердились эталоном (`known_trims`):
    {класс: {слова: языки}}. Правила:
      Б1. слова книги годятся строке, если язык записи — один из языков
          сайта строки (`langs`); языки сайта неизвестны — годятся любые;
      Б2. перед хозяевами срезается самая длинная известная цепочка слов с
          начала, после гостей — самая длинная с конца; сравнение без учёта
          регистра, целыми словами;
      Б3. от стороны должно остаться имя (`live._still_name`).
    Возвращает (хозяева, гости, пометка `TRIMMED`) или None — резать нечего."""
    if not known:
        return None

    def fits(phrase_langs: frozenset) -> bool:                                # Б1
        return langs is None or not phrase_langs or bool(phrase_langs & langs)

    def longest(words: list[str], table: dict, from_end: bool) -> int:
        """Сколько слов срезать с края: длина самой длинной известной цепочки."""
        best = 0
        for size in range(1, min(len(words), live.TRIM_WORDS + 1)):
            piece = words[-size:] if from_end else words[:size]
            phrase_langs = table.get(" ".join(w.casefold() for w in piece))
            if phrase_langs is not None and fits(phrase_langs):
                best = size
        return best

    hw, aw = home.split(), away.split()
    k = longest(hw, known.get(KNOWN_HOME) or {}, from_end=False)              # Б2
    m = longest(aw, known.get(KNOWN_AWAY) or {}, from_end=True)
    if not k and not m:
        return None
    new_home = " ".join(hw[k:]).strip(live._TRIM_EDGE)
    new_away = " ".join(aw[:len(aw) - m] if m else aw).strip(live._TRIM_EDGE)
    if not live._still_name(new_home) or not live._still_name(new_away):      # Б3
        return None
    where = live.TRIM_BOTH if k and m else live.TRIM_HOME if k else live.TRIM_AWAY
    cut = " … ".join(x for x in (" ".join(hw[:k]), " ".join(aw[len(aw) - m:]) if m else "") if x)
    return new_home, new_away, {"где": where, "срезано": cut,
                                "было": f"{home} - {away}", "по": "книга"}


_KNOWN_TRIMS: dict | None = None


def known_trims(path=None) -> dict:
    """Книга 136: лишние слова из книги знаний — раздел `dictionary_errors`
    файла `data/dictionaries.json` (его возит `scripts/dict_sync.py`), классы
    `KNOWN_HOME` и `KNOWN_AWAY`. → {класс: {слова в нижнем регистре: языки}}.
    Файла или раздела нет, файл битый — пусто: правило просто молчит."""
    global _KNOWN_TRIMS
    if path is None and _KNOWN_TRIMS is not None:
        return _KNOWN_TRIMS
    import json
    from pathlib import Path
    out: dict = {KNOWN_HOME: {}, KNOWN_AWAY: {}}
    file = Path(path) if path else Path(__file__).resolve().parent.parent / "data" / "dictionaries.json"
    try:
        rows = json.loads(file.read_text(encoding="utf-8")).get("dictionary_errors") or []
    except (OSError, ValueError, AttributeError):
        rows = []
    for row in rows:
        if not isinstance(row, dict) or row.get("class") not in out:
            continue
        words = " ".join(str(row.get("alias") or "").casefold().split())
        if words:
            langs = frozenset(str(row.get("lang") or "").split())
            out[row["class"]][words] = out[row["class"]].get(words, frozenset()) | langs
    if path is None:
        _KNOWN_TRIMS = out
    return out


def trim_over_pair(program: Program, verdict: live.Verdict,
                   reference: Reference | None, start_kyiv: datetime | None,
                   league_category: str = "", langs: frozenset | None = None,
                   known: dict | None = None, stop=None):
    """Книги 133 и 136 для строки, пару которой отсев ПРИНЯЛ (эфир пометил
    сайт, `verdict.ok`). Порядок:
      1. пара сошлась «метками из эталона» (пол и возраст дописал эталон) —
         не трогаем;
      2. срез по эталону (`trim_by_reference`) — берём его; если пара уже
         сходилась (целиком или одной стороной), срез обязан дать тот же
         матч (О1б, О4);
      3. эталон пару не узнал вовсе — срез по книге знаний (`trim_by_book`):
         строка пойдёт дальше с чистыми именами, а урезанную пару ещё раз
         спросят у эталона обычным порядком. Строку, которую эталон узнал
         «одной стороной», книга не режет: эталон главнее.
    Возвращает новый вердикт или None."""
    if not verdict.ok or not verdict.home or not verdict.away:
        return None
    got = None
    if reference is not None and start_kyiv is not None:
        got = reference.confirm(leagues.with_category(verdict.home, league_category),
                                leagues.with_category(verdict.away, league_category),
                                start_kyiv)
        if got is not None and got.how == MARKS_HOW:                          # 1
            return None
        cut = trim_by_reference([(verdict.home, verdict.away)], reference,   # 2
                                start_kyiv, league_category, agree=got, stop=stop)
        if cut is not None:
            home, away, _got, mark = cut
            program.extra[TRIMMED] = mark
            return live.Verdict(True, "", live_marker=verdict.live_marker,
                                home=home, away=away)
    if got is None:                                                           # 3
        by_book = trim_by_book(verdict.home, verdict.away,
                               known_trims() if known is None else known, langs)
        if by_book is not None:
            home, away, mark = by_book
            program.extra[TRIMMED] = mark
            return live.Verdict(True, "", live_marker=verdict.live_marker,
                                home=home, away=away)
    return None


def title_over_pair(program: Program, verdict: live.Verdict,
                    reference: Reference | None, start_kyiv: datetime | None,
                    league_category: str = ""):
    """Книга 122 (общее правило для ВСЕХ сайтов, слово владельца 14.11:
    «чтоб этот опыт был применим для всех»).

    Случай ipko.tv 13.11: сайт сменил запись, и разборщик выдал «пару» из
    обрывка описания («UEFA Nations League» — «Shikoni ndeshjen…»), хотя
    заголовок держал настоящую — «Spanje-Angli». Отсев пару принял (пометка
    эфира стояла), до вопроса эталону (`ask_reference`) дело не дошло, игра
    не узналась. Правила:
      1. зовём, когда отсев ПРИНЯЛ пару разборщика (`verdict.ok`);
      2. эталон знает хотя бы одну сторону этой пары как команду ЛИБО
         подтверждает саму пару на это время — пару не трогаем: разборщик
         прочитал верно;
      3. иначе читаем пары из ЗАГОЛОВКА всеми читателями
         (`live.split_candidates`), кроме самой пары разборщика и той же
         пары с лишними словами заголовка вокруг;
      4. пару заголовка эталон подтвердил на это время ЦЕЛИКОМ (`how` —
         «пара» или «метки из эталона») — берём её, в порядке сторон эталона;
         прежняя пара — в пометку `TITLE_PAIR`;
      5. не подтвердил — остаётся пара разборщика, как раньше: правило
         ничего не отнимает.
    Пометку эфира не трогаем: её дал сайт. Прошлый сезон в подписи — мимо.
    Возвращает (новый вердикт, ответ эталона) либо None."""
    if reference is None or start_kyiv is None or not verdict.ok:
        return None
    if reference.knows_team(verdict.home) or reference.knows_team(verdict.away):
        return None                                             # правило 2
    if reference.confirm(verdict.home, verdict.away, start_kyiv) is not None:
        # правило 2 (вторая половина): имён эталон «в лоб» не знает, но пару
        # на это время подтверждает (местные написания) — разборщик прав.
        # Проверка на сборе 14.11: у ntvplus.tv верная пара «Перт Уайлдкэтс —
        # Иллаварра Хокс» менялась на ту же с приклеенным началом заголовка
        return None
    title = (program.title or "").strip()
    if past_season(" ".join(x for x in (title, program.league_raw) if x), start_kyiv):
        return None
    mine = (_plain(verdict.home), _plain(verdict.away))
    for home, away in pair_guesses(program, with_field=False):   # правило 3
        if (_plain(home), _plain(away)) == mine:
            continue
        if mine[0] and mine[1] and mine[0] in _plain(home) and mine[1] in _plain(away):
            # та же пара разборщика, только с лишними словами заголовка
            # вокруг («Баскетбол. Прямая трансляция. Перт…») — она не лучше
            continue
        home = leagues.with_category(home, league_category)
        away = leagues.with_category(away, league_category)
        got = reference.confirm(home, away, start_kyiv)
        if got is None or got.how not in ("пара", MARKS_HOW):    # правило 4
            continue
        if got.swapped:
            home, away = away, home
        program.extra[TITLE_PAIR] = f"{verdict.home} - {verdict.away}"
        return (live.Verdict(True, "", live_marker=verdict.live_marker,
                             home=home, away=away), got)
    return None                                                  # правило 5


def ask_reference(program: Program, verdict: live.Verdict,
                  reference: Reference | None, start_kyiv: datetime | None,
                  league_category: str = "", stop=None):
    """Правило (в): строку, которую отсев не взял (`verdict`), спрашиваем у
    эталона. Пару дают все читатели (`live.split_candidates`), и пара
    строки — догадка, которую эталон подтвердил как эфир
    (`Reference.confirm`), в порядке сторон эталона. Из нескольких
    подтверждённых берётся сошедшаяся ЦЕЛИКОМ («пара», затем «метки из
    эталона» — тоже целиком, лишь без пола и возраста), а не первая по
    порядку: у rtl «2. Bundesliga Live - Topspiel: 1. FC Nürnberg - 1. FC
    Kaiserslautern» первая догадка («2. Bundesliga Live» — «Topspiel: …»)
    сходилась «одной стороной», и игра уезжала на витрину с мусорным именем
    (проверка книги 064, 20.10). Возвращает (новый вердикт, ответ эталона)
    либо None — тогда строка решается, как раньше."""
    if reference is None or start_kyiv is None \
            or verdict.reason not in ASK_REFERENCE_REASONS:
        return None
    # прошлый сезон в подписи — классика, эталон не спрашиваем
    if past_season(" ".join(x for x in (program.title, program.match_raw,
                                        program.league_raw) if x), start_kyiv):
        return None
    # догадки — и из поля пары, и из заголовка: парсер кладёт в поле « »,
    # когда пары не нашёл, а заголовок её держит («Al Nassr-Al Neom», ipko)
    # книга 124: к ним — первая строка описания и фразы-шаблоны (`pair_guesses`).
    # Догадке, которая взялась ТОЛЬКО из описания, нужна пара целиком: описание
    # — свободный текст, и «одной стороной» там сходится что угодно (на сборе
    # 14.11 «Fotbal - Liga národů» у oneplay.cz стало «игрой»)
    candidates = pair_guesses(program)
    without_description = pair_guesses(
        Program(channel_raw=program.channel_raw, title=program.title, start=program.start,
                match_raw=program.match_raw, description=""))
    only_described = [pair for pair in candidates if pair not in without_description]
    confirmed: list[tuple[str, str, Confirmed]] = []
    raw_of: dict[tuple[str, str], tuple[str, str]] = {}   # догадка с пометкой → без неё
    for home, away in candidates:
        # пол и возраст турнира — к догадке сразу: «Polska - Belgia» в женском
        # отборе должна сойтись с «Poland W — Belgium W», а не с мужской парой
        described = (home, away) in only_described
        raw = (home, away)
        home = leagues.with_category(home, league_category)
        away = leagues.with_category(away, league_category)
        got = reference.confirm(home, away, start_kyiv)
        if got is not None and described and got.how not in ("пара", MARKS_HOW):
            continue                       # из описания — только целая пара
        if got is not None:
            confirmed.append((home, away, got))
            if not described:
                raw_of[(home, away)] = raw
            if got.how == "пара":
                break                      # лучше не бывает
    # книга 133: целиком не сошлась ни одна догадка — пробуем срезать лишние
    # слова снаружи пары (догадки из одного описания не режем: там свободный
    # текст). Строка, которую эталон узнал «одной стороной», обязана дать
    # срезом тот же матч (О4)
    if not any(got.how in ("пара", MARKS_HOW) for _h, _a, got in confirmed):
        cut = trim_by_reference(
            [pair for pair in candidates if pair not in only_described],
            reference, start_kyiv, league_category,
            agree=confirmed[0][2] if confirmed else None, stop=stop)
        if cut is not None:
            home, away, got, mark = cut
            home = leagues.with_category(home, league_category)
            away = leagues.with_category(away, league_category)
            program.extra[TRIMMED] = mark
            program.extra["live_guess"] = True
            return (live.Verdict(True, "", live_marker=verdict.live_marker or REFERENCE_MARKER,
                                 home=home, away=away), got)
    if not confirmed:
        return None
    # целая пара главнее половины; среди равных — первая догадка (сорт устойчив)
    ЦЕЛИКОМ = {"пара": 0, MARKS_HOW: 1}
    home, away, got = min(confirmed, key=lambda x: ЦЕЛИКОМ.get(x[2].how, 2))
    # книга 133, О1б: пара сошлась целиком, но, возможно, с лишними словами
    # («… Das Spiel») — срез обязан дать тот же матч
    if got.how == "пара" and (home, away) in raw_of:
        cut = trim_by_reference([raw_of[(home, away)]], reference, start_kyiv,
                                league_category, agree=got, stop=stop)
        if cut is not None:
            home, away, got, mark = cut
            home = leagues.with_category(home, league_category)
            away = leagues.with_category(away, league_category)
            program.extra[TRIMMED] = mark
            program.extra["live_guess"] = True
            return (live.Verdict(True, "", live_marker=verdict.live_marker or REFERENCE_MARKER,
                                 home=home, away=away), got)
    if got.swapped:
        home, away = away, home
    # эфир угадан (эталоном, не словом сайта): дальше его проверяют те же
    # фильтры повторов, что и прочие угадайки (`parse_live.guessed`)
    program.extra["live_guess"] = True
    return (live.Verdict(True, "", live_marker=verdict.live_marker or REFERENCE_MARKER,
                         home=home, away=away), got)


def classify(program: Program, markers: live.Markers, sports: sport.Sports,
             league_sports: dict[str, str] | None = None,
             pair_sports: dict[str, str] | None = None,
             reference: Reference | None = None,
             langs: frozenset | None = None) -> Row:
    """`langs` — языки сайта строки (`site_lang.of`, слово владельца 25.10,
    книга 084): служебные слова — пол, эфир, повтор, стоп-слова — ищутся
    только на языке сайта и общие. None — все языки, как раньше. Строку
    читал одолженный разбор (`extra["borrowed"]`) — его язык тоже: он пишет
    свои пометки по-своему (датский «direkte» у шведского сайта)."""
    borrowed = (program.extra or {}).get("borrowed") if langs is not None else ""
    if borrowed:
        own = site_lang.of(borrowed)
        langs = None if own is None else langs | own
    # и письменность самой строки: русская передача на литовском сайте
    # читается по-русски (правило 6 `site_lang`, книга 086)
    langs = site_lang.of_row(langs, " ".join(
        x for x in (program.league_raw, program.title, program.description) if x))
    markers = markers.for_langs(langs)
    row = Row(program=program, ok=False,
              start_utc=daytime.to_utc(program.start),
              start_kyiv=daytime.to_kyiv(program.start))

    # Пол и возраст часто видны только по названию турнира, а команды на
    # сайте подписаны как обычно — считаем метку раньше отсева: она нужна и
    # вопросу эталону ниже (женскую пару с мужским матчем он не сведёт)
    row.league = leagues.clean(program.league_raw)
    row.league_category = leagues.category(
        " ".join(x for x in (program.league_raw, program.title,
                             program.description) if x), langs)

    verdict = live.check(program, markers)
    row.live_marker = verdict.live_marker
    row.home, row.away = verdict.home, verdict.away
    confirmed = None
    if not verdict.ok:
        # Правило (в) починки самопроверки №13 (владелец 20.10): «не уверен —
        # спроси эталон» вместо списков по сайтам. Нет пометки эфира или
        # пара не прочиталась — пару ищут все читатели (`live.split_candidates`,
        # правило (г)), а эталон отвечает, эфир ли это (`Reference.confirm`:
        # матч с такой парой начинается рядом с показом). Эфир тогда
        # угаданный (`live_guess`) — его проверят те же фильтры повторов,
        # что и прочие угадайки. Слово записи, студию и стоп-слово эталон
        # не оспаривает: это сайт сказал прямо
        rescued = ask_reference(
            program, verdict, reference, row.start_kyiv, row.league_category,
            stop=lambda words: markers.found(markers.stop_title, words))
        if rescued is None:
            row.reason = verdict.reason
            return row
        verdict, confirmed = rescued
        row.live_marker = verdict.live_marker
        row.home, row.away = verdict.home, verdict.away
        row.by_reference = confirmed.how
    else:
        # книга 122: пара разборщика эталону незнакома, а в заголовке стоит
        # пара, которую эталон подтверждает, — берём пару заголовка. Эфир
        # при этом остаётся словом сайта (не «угадан»)
        better = title_over_pair(program, verdict, reference, row.start_kyiv,
                                 row.league_category)
        if better is not None:
            verdict = better[0]
            row.home, row.away = verdict.home, verdict.away
        else:
            # книги 133 и 136: к паре снаружи прилипли лишние слова — срез
            # по эталону, а если эталон пару не знает вовсе — по книге знаний
            cut = trim_over_pair(
                program, verdict, reference, row.start_kyiv, row.league_category,
                langs, stop=lambda words: markers.found(markers.stop_title, words))
            if cut is not None:
                verdict = cut
                row.home, row.away = verdict.home, verdict.away
    rescued = confirmed is not None        # эфир строке дал эталон, не сайт
    # книга 095 (#9541): сторона пары — имя своего канала («Sport 2 - Program
    # Sportiv» у ipko) — заставка канала, а не матч: ни на витрину, ни в очередь
    if channel_side(program.channel_raw, row.home, row.away, reference):
        row.reason = CHANNEL_SIDE
        return row

    # Дописываем метку турнира к именам, иначе женский матч склеится с
    # мужским (правило проекта: лишний ` W` лучше потерянного).
    if row.league_category:
        row.home = leagues.with_category(row.home, row.league_category)
        row.away = leagues.with_category(row.away, row.league_category)
    # Пол по одной стороне (владелец 28.09, #3535): женская команда с
    # мужской не играет, и если хоть одна сторона женская — вся пара
    # женская. Возраст так НЕ переносим: в EFL Trophy «Chelsea U21» честно
    # играет со взрослым Wycombe
    клуб_спорт = ""
    if row.home and row.away:
        клуб_спорт = leagues.women_team(row.home) or leagues.women_team(row.away)
        женская = [("W" in names.category(x).split()) for x in (row.home, row.away)]
        if any(женская) or клуб_спорт:
            row.home = leagues.with_category(row.home, "W")
            row.away = leagues.with_category(row.away, "W")

    # ── Вид спорта. Здесь только собираются улики; само решение — в одном
    # месте, `sport.Sports.decide`, там правила записаны по номерам ────────
    # что сайт пишет о матче сам (без описания) и весь текст строки
    head = " ".join(x for x in (program.title, program.sport_raw,
                                program.league_raw) if x)
    text = " ".join(x for x in (head, program.description) if x)
    # эталон flashscore: знает ли он эту пару в это время (правило 2). Не на
    # 95, а на 85 (и в окне эфира, а не ±3 ч) — тоже спрашиваем (правило (в):
    # «вид неясен → совпало с эталоном»), но только ПАРОЙ ЦЕЛИКОМ: одна
    # твёрдая сторона вид спорта не решает («PSG - Lens» при эталонном
    # «PSG - Le Mans» — другая вторая команда, эталон молчит; тест правила 2).
    # Исключение — строка, которую эталон уже признал эфиром своего матча
    # (`rescued`): раз это показ того матча, вид спорта — его
    by_ref = reference.sport_of(row.home, row.away, row.start_kyiv) \
        if reference is not None else ""
    if not by_ref and reference is not None:
        if confirmed is None:
            confirmed = reference.confirm(row.home, row.away, row.start_kyiv)
        if confirmed is not None and (rescued or confirmed.how in ("пара", MARKS_HOW)):
            by_ref = confirmed.entry.get("sport") or "F"
            row.by_reference = row.by_reference or confirmed.how
    # Метки из эталона (слово владельца 24.10, книга 003): сайт написал пару
    # без пола и возраста, а эталон в эту минуту знает её только с меткой
    # («Man City – Psg» ↔ «Manchester City U19 – PSG U19», правило 5
    # `Reference.confirm`). Метку дописываем к именам сразу, как метку
    # турнира выше: дальше её увидят сверка с эталоном и фильтры повторов
    # обхода (`parse_live._in_reference`, `nearest_shows`) и склейка — иначе
    # эфир снимался как «пары нет в эталоне», а дошедший до витрины шёл бы
    # взрослой игрой рядом со своей же юношеской
    метки_эталона = confirmed.marks if confirmed is not None else ""
    if метки_эталона:
        row.home = leagues.with_category(row.home, метки_эталона)
        row.away = leagues.with_category(row.away, метки_эталона)
    # эталон знает хоть одну сторону как команду (правило 3: «пара похожа
    # на матч»)
    ref_team = reference is not None and any(
        reference.knows_team(side) for side in (verdict.home, verdict.away))
    # лига из словаря лиг (правило 6): `data/dictionaries.json` едет в git
    # и есть и у обхода
    league = None
    for key in (row.league, program.league_raw, program.sport_raw):
        letter = (league_sports or {}).get(" ".join(key.lower().split()))
        if letter:
            league = (letter, key)
            break
    # подсказка владельца для этой пары (правило 8; страница «Названия»,
    # раздел «Вид спорта») — пока не вышел её срок
    hint = (pair_sports or {}).get(f"{row.home} - {row.away}".strip())
    by_hint = hint[0] if hint and hint_fresh(hint[1], row.start_kyiv) else ""

    decision = sports.decide(text, head, (verdict.home, verdict.away),
                             ref=by_ref, ref_team=ref_team, league=league,
                             club=клуб_спорт,
                             hint=by_hint,
                             # месяц строки: турнир не в свой месяц — запись
                             # (правило 1, раздел «сезоны» markers.json)
                             month=row.start_kyiv.month if row.start_kyiv else 0)
    letter = decision.letter
    row.sport_word = decision.word
    row.sport_source = decision.source
    row.sport_rule = decision.rule
    row.team_word = decision.team_word
    if letter == "-":
        row.reason = f"другой вид спорта: {decision.word}"
        row.sport_group = decision.group
        return row
    if letter is None:
        # ТЗ разд. 6: не определился — не в мусор, а владельцу на проверку
        row.reason = "вид спорта не определён"
        row.needs_review = True
        return row
    row.sport = letter
    # Показ вне окна эфира (25.10, sport5: матч WNBA 02:00 стоит в сетке на
    # 03:00 со значком эфира): эфиром эталон его не признал (`confirm` →
    # None, фильтры повторов решают как раньше), но пару в ±3 ч знает
    # только с меткой — метку дописываем всё равно (`Reference.late_marks`,
    # вид спорта уже известен), иначе женский матч шёл бы на витрину второй
    # строкой без W рядом со своей же W-игрой. Теннису метки не пишем
    if not метки_эталона and confirmed is None and reference is not None \
            and row.home and row.away and letter != "T":
        поздний = reference.late_marks(row.home, row.away, row.start_kyiv, letter)
        if поздний is not None:
            метки_эталона = поздний.marks
            row.home = leagues.with_category(row.home, метки_эталона)
            row.away = leagues.with_category(row.away, метки_эталона)
            row.by_reference = row.by_reference or поздний.how
    if letter == "T" and (row.home, row.away) != (verdict.home, verdict.away):
        # Теннис: пол игрока задаёт турнир (WTA/ATP), к фамилии его не пишет
        # ни эталон flashscore, ни другие сайты. sportklub.hr кладёт в описание
        # «teniski turnir za žene» — и «Kraus W — Yastremska W» не сходилась с
        # эталонной «Kraus S. — Yastremska D.», все женские матчи сайта жили
        # без канона (#4597, владелец 04.10). Возраст оставляем как был —
        # и турнира, и дописанный из эталона.
        без_пола = " ".join(p for p in f"{row.league_category} {метки_эталона}".split()
                            if p != "W")
        row.home = leagues.with_category(verdict.home, без_пола)
        row.away = leagues.with_category(verdict.away, без_пола)

    if row.start_utc is None:
        row.reason = "не разобрали время"
        row.needs_review = True
        return row

    row.ok = True
    return row


def run(programs, markers: live.Markers | None = None,
        sports: sport.Sports | None = None,
        league_sports: dict[str, str] | None = None,
        pair_sports: dict[str, str] | None = None,
        reference: Reference | None = None,
        domain: str = "") -> list[Row]:
    """`reference` — эталон flashscore этого обхода (`app/reference.py`).
    Без него правило 2 (`sport.Sports.decide`) молчит, остальные работают."""
    markers = markers or live.load()
    sports = sports or sport.load()
    if league_sports is None:
        league_sports = leagues.sports_map()
    if pair_sports is None:
        pair_sports = leagues.pair_sports()
    # языки сайта — для словаря служебных слов (книга 084)
    langs = site_lang.of(domain) if domain else None
    return [classify(p, markers, sports, league_sports, pair_sports, reference,
                     langs)
            for p in programs]

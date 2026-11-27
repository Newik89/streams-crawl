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

from . import broadcast, daytime, leagues, live, names, site_lang, sport
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
#: книга 138: причины отсева строки без пары (их пишет `live.check`)
NO_PAIR = "не видно пары команд"
NO_LIVE = "нет маркера прямого эфира"
#: книга 138: пометка строки «трансляция турнира одним куском» —
#: {"тур": …, "город": … (пусто — турнир не узнан), "эталон": рядом с
#: показом в эталоне начинается матч этого турнира}
TOURNAMENT = "турнир"
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
#: {"где": край, "срезано": слова, "было": пара до среза, "по": "эталон" | "книга"
#: | "стадия" (книга 157, `BY_STAGE`)}
TRIMMED = "обрезка"
#: книга 139: поле пометки среза — [сторона после слов «перед хозяевами»,
#: сторона перед словами «после гостей»] в порядке сайта; пусто — с этого
#: края не резали
BESIDE = "у"
#: книга 139: слова книги знаний, записанные программой, становятся правилом,
#: когда срезались рядом с таким числом РАЗНЫХ команд
BOOK_TEAMS = 2
#: кто записал строку книги сам, без слова владельца (`note_error`)
BY_PROGRAM = "программа"
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
          к идущему в тот же час «Atl. Madrid — Barcelona». Срез по концу
          предложения (`live.sentence_trims`, книга 157) это правило не
          держит: за точкой стоит другая фраза, не часть имени;
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
        # книга 157: срез по концу предложения О6 не держит — за точкой стоит
        # другая фраза, а не часть имени («France. Qualifications à…»: такую
        # сторону эталон «знает» лишь потому, что сравнение терпит лишние слова)
        by_dot = {(w, h, a) for w, _c, h, a in live.sentence_trims(home, away)}
        for where, cut, new_home, new_away in live.outer_trims(home, away):   # О2
            if (fixed[where] and (where, new_home, new_away) not in by_dot) \
                    or (stop is not None and stop(cut)):                      # О6, О7
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
                # книга 139: рядом с какой стороной стояли срезанные слова —
                # по числу РАЗНЫХ таких команд книга знаний отличает лишнее
                # слово («ligová fáze» перед шестью сборными) от части имени
                # («of Midlothian» всегда после одного «Heart»)
                beside = {live.TRIM_HOME: [new_home, ""], live.TRIM_AWAY: ["", new_away],
                          live.TRIM_BOTH: [new_home, new_away]}[where]
                hits.append((new_home, new_away, got,
                             {"где": where, "срезано": clean,
                              "было": f"{home} - {away}", "по": "эталон",
                              BESIDE: beside}))
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


def seen_teams(value) -> list[str]:
    """Книга 139: команды из поля `seen_with` строки книги — список либо тот
    же список текстом JSON (так он лежит в базе); битое — пусто."""
    import json
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if not isinstance(value, list):
        return []
    return sorted({" ".join(str(x).casefold().split()) for x in value if str(x).strip()})


def book_rule(row: dict) -> bool:
    """Книга 139: строка книги знаний — уже правило (Д1, Д2 в `known_trims`).
    Книга 146: «разные команды» — разные по сходству имён, а не по буквам:
    «Bydgoszcz» и «Bydgoszcz W», «Heart» и «Hearts», «Finsko» и «Finland» —
    одна команда, записанная по-разному, и правилом слова не делают."""
    if (row.get("answered_by") or BY_PROGRAM) != BY_PROGRAM:               # Д1
        return True
    different: list[str] = []
    for team in seen_teams(row.get("seen_with")):
        bare = _strip_marks(team)
        if all(names.similarity(bare, other) < names.SIMILAR_ENOUGH for other in different):
            different.append(bare)
    return len(different) >= BOOK_TEAMS                                    # Д2


_KNOWN_TRIMS: dict | None = None


def known_trims(path=None) -> dict:
    """Книга 136: лишние слова из книги знаний — раздел `dictionary_errors`
    файла `data/dictionaries.json` (его возит `scripts/dict_sync.py`), классы
    `KNOWN_HOME` и `KNOWN_AWAY`. → {класс: {слова в нижнем регистре: языки}}.
    Файла или раздела нет, файл битый — пусто: правило просто молчит.

    Книга 139 — какая строка книги становится правилом (`book_rule`):
      Д1. строку записал владелец (`answered_by` — не «программа») — правило
          сразу: он знает, что слова лишние («Liga e Kombeve», книга 137);
      Д2. строку записала программа — правило, только когда слова срезались
          рядом с `BOOK_TEAMS` РАЗНЫМИ командами (поле `seen_with`). Слова
          рядом с одной и той же командой — скорее часть её имени, которую
          эталон пишет короче («Heart of Midlothian» → «Heart», «Enea
          Łaciate Astoria Bydgoszcz» → «Bydgoszcz», сбор 15.11): такая
          строка ждёт в книге и срезом по книге не становится."""
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
        if not isinstance(row, dict) or row.get("class") not in out \
                or not book_rule(row):                                   # Д1, Д2
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


# ── книга 157: в стороне пары — не имя ───────────────────────────────────────
#: М2, М3: одиночное слово стадии короче — не срезается и стороной-стадией не
#: считается: так выглядят и сокращения команд («LEG», «DAY», «IDA»)
STAGE_WORD_MIN = 5
_TOUR_WORDS: list = []          # слова тура и турнира (теннис) — читаются один раз


def _tour_words():
    """Слова тура и турнира («ATP», «WTA», «Open», «турнир») — раздел
    `tournament` → «тур и турнир» файла `data/markers.json`. «Пара» с таким
    словом — название теннисного турнира, у неё своя дорога (`app/broadcast.py`)."""
    if not _TOUR_WORDS:
        import json
        data = json.loads(live.MARKERS_FILE.read_text(encoding="utf-8"))
        _TOUR_WORDS.append(live._pattern(live._flatten(
            (data.get("tournament") or {}).get("тур и турнир"))))
    return _TOUR_WORDS[0]


#: книга 157: пометка среза `TRIMMED` — «по»: слова срезаны словарём стадий и
#: пометок эфира (`tidy_sides`), а не эталоном и не книгой знаний. В книгу
#: знаний такой срез не учится (`dictionary.note_trims` берёт только «эталон»)
BY_STAGE = "стадия"


def _tidy_mark(home: str, away: str, new_home: str, new_away: str) -> dict:
    """Пометка `TRIMMED` для среза `tidy_sides` — тот же вид, что у срезов по
    эталону и по книге: где, что срезано, какой была пара."""
    def gone(old: str, new: str) -> str:
        if old.endswith(new):
            old = old[:len(old) - len(new)]
        elif old.startswith(new):
            old = old[len(new):]
        return old.strip(live._TRIM_EDGE)
    parts = [(live.TRIM_HOME, gone(home, new_home)) if new_home != home else None,
             (live.TRIM_AWAY, gone(away, new_away)) if new_away != away else None]
    parts = [p for p in parts if p]
    where = live.TRIM_BOTH if len(parts) == 2 else parts[0][0]
    return {"где": where, "срезано": " … ".join(cut for _where, cut in parts),
            "было": f"{home} - {away}", "по": BY_STAGE}


def _strong_stage(words: str) -> bool:
    """Слова — стадия или тур без сомнений: только слова стадии, тура, пометки
    эфира и числа (`leagues.stage_only`), и это не одиночное короткое слово
    (`STAGE_WORD_MIN`): два слова и больше, слово с числом («Game 7», «8ª
    jornada», «FINAL 8») либо одно слово от пяти букв («csoportkör»)."""
    if not leagues.stage_only(words):
        return False
    tokens = [t for t in words.split() if any(ch.isalnum() for ch in t)]
    return len(tokens) >= 2 or sum(ch.isalpha() for ch in words) >= STAGE_WORD_MIN


def tidy_sides(home: str, away: str, markers: live.Markers | None = None,
               reference: Reference | None = None):
    """Книга 157: к стороне пары прилипло не имя — общие правила для всех
    сайтов, без эталона (то, что эталон срезать не может: матча в нём нет).

    Находки 16.11: «ligová fáze Faroe Island — Moldavsko» (tv-program.
    aktuality.sk), «Magyarország — Dánia csoportkör» (mediaklikk.hu), «8ª
    jornada Bulgaria — España» (movistarplus.es), «FINAL 8 - CHÉQUIA — CANADÁ»
    (sporttv.pt), «Unicaja — BK KVIS Pardubice Přímý přenos utkání…»
    (webtv.sk), «Eurobasket Feminino 2027 — 2ª Fase de Qualificação» (rtp.pt:
    это не пара вовсе, а турнир и стадия). Правила по порядку:
      М0. «Пара» со словом тура или турнира («ATP — Nitto ATP Finals», «ATP
          FINALS 2026 — MEIA-FINAL») — название теннисного турнира: её ведут
          правила `app/broadcast.py`, здесь не трогаем.
      М1. Пометка эфира внутри стороны (слова `live` на языке сайта): с неё и
          до конца стороны — приписка об эфире, срезается. Пометка в начале
          стороны срезается сама.
      М2. Слова стадии и тура на ВНЕШНИХ краях пары — в начале хозяев и в
          конце гостей — срезаются (`_strong_stage`; самая длинная цепочка,
          не больше `live.TRIM_WORDS` слов). Сторону, которую эталон знает
          как команду, не режем. От стороны должно остаться имя.
          То же по предложениям: за точкой предложения у гостей (перед ней у
          хозяев) стоит тур или стадия — всё за точкой не имя: «France.
          Qualifications à l'EuroBasket féminin. 3e journée. Groupe M.» →
          «France». Точка сокращения («Eintr. Frankfurt») так не режется:
          тура за ней нет.
      М3. Сторона целиком — стадия, тур или пометка эфира (`_strong_stage`):
          это не команда, и строка — не пара.
    Возвращает (хозяева, гости) либо None — пары нет (М3)."""
    tour = _tour_words()
    if tour is not None and (tour.search(live.greek_plain(home))
                             or tour.search(live.greek_plain(away))):         # М0
        return home, away

    def air_off(side: str) -> str:                                            # М1
        air = markers.live if markers is not None else None
        found = air.search(live.greek_plain(side)) if air is not None else None
        if not found:
            return side
        before = side[:found.start()].strip(live._TRIM_EDGE + "()[]")
        return before if live._still_name(before) else side[found.end():].strip(live._TRIM_EDGE + "()[]")

    home, away = air_off(home), air_off(away)
    if not live._still_name(home) or not live._still_name(away):              # М3
        return None
    # слов стадии, тура и чисел в сторонах нет вовсе — дальше смотреть нечего
    touched = [leagues._stage_rest(side) != live.greek_plain(side) for side in (home, away)]
    if not any(touched):
        return home, away
    if _strong_stage(home) or _strong_stage(away):                            # М3
        return None

    def cut(side: str, from_end: bool) -> str:                                # М2
        # по предложениям: среди фраз за точкой (перед ней) есть тур или стадия
        phrases = live._SENTENCE_END.split(side)
        if len(phrases) > 1:
            name, rest = (phrases[0], phrases[1:]) if from_end else (phrases[-1], phrases[:-1])
            name = name.strip(live._TRIM_EDGE)
            if live._still_name(name) and any(
                    _strong_stage(part.strip(live._TRIM_EDGE)) for part in rest):
                return name
        if reference is not None and reference.knows_team(side):
            return side
        words = side.split()
        for size in range(min(len(words) - 1, live.TRIM_WORDS), 0, -1):
            piece = words[-size:] if from_end else words[:size]
            rest = (" ".join(words[:-size] if from_end else words[size:])).strip(live._TRIM_EDGE)
            if _strong_stage(" ".join(piece)) and live._still_name(rest):
                return rest
        return side

    return (cut(home, from_end=False) if touched[0] else home,
            cut(away, from_end=True) if touched[1] else away)


#: книга 164: длиннее такого числа слов прилипшую лигу не ищем
LEAGUE_SIDE_WORDS = 7


def _league_key(text: str) -> str:
    """Название лиги для сравнения: строчными, пробелы по одному, апостроф один."""
    return " ".join((text or "").lower().replace("’", "'").split())


def league_off_sides(home: str, away: str, known_leagues, own_league: str = "",
                     reference: Reference | None = None) -> tuple[str, str]:
    """Книга 164: к стороне пары прилипла ЛИГА без разделителя.

    dagenstv.com пишет строку одним куском: «Häcken - Manchester C UEFA
    Women's Champions League», «NBA herrar Philadelphia 76ers - Milwaukee
    Bucks». Эталон такой матч не всегда знает (срез по эталону молчит), а
    срез слов стадии лигу не видит. Правила по порядку:
      Л1. Смотрим только внешние края пары — начало хозяев и конец гостей:
          внутри пары рубрик не бывает.
      Л2. Прилипшая лига — цепочка от двух до `LEAGUE_SIDE_WORDS` слов на
          краю, которая буква в букву (без регистра) — название лиги из
          словаря лиг (`known_leagues`, ключи `leagues.sports_map`) или лига
          самой строки (`own_league`). Одно слово не режем: в словаре лиг
          есть лиги-города («Salzburg»), а у клубов — такие же имена.
      Л3. Цепочка, которая сама страна (`names.country_of`: «Costa Rica»,
          «South Africa»), — не лига.
      Л4. От стороны должно остаться имя (`live._still_name`); сторону,
          которую эталон знает командой целиком, не режем.
      Л5. Из подходящих цепочек берётся самая длинная.
    Возвращает (хозяева, гости) — те же, если резать нечего."""
    own = _league_key(own_league)

    def is_league(words: list[str]) -> bool:
        phrase = _league_key(" ".join(words))
        if len(words) < 2 or names.country_of(phrase):                    # Л2, Л3
            return False
        return phrase == own or bool(known_leagues and known_leagues.get(phrase))

    def cut(side: str, from_end: bool) -> str:
        if reference is not None and reference.knows_team(side):          # Л4
            return side
        words = side.split()
        for size in range(min(len(words) - 1, LEAGUE_SIDE_WORDS), 1, -1):  # Л5
            piece = words[-size:] if from_end else words[:size]
            rest = " ".join(words[:-size] if from_end else words[size:]).strip(live._TRIM_EDGE)
            if is_league(piece) and live._still_name(rest):
                return rest
        return side

    return cut(home, from_end=False), cut(away, from_end=True)             # Л1


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
                  league_category: str = "", stop=None, tidy=None):
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
    либо None — тогда строка решается, как раньше.
    `tidy` (книга 157) — чистка сторон догадки (`tidy_sides`): догадка, где
    сторона — стадия турнира, а не команда, эталону не предлагается."""
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
    def tidied(pairs: list) -> list:
        if tidy is None:
            return pairs
        out = []
        for pair in (tidy(*pair) for pair in pairs):
            if pair is not None and pair not in out:
                out.append(pair)
        return out

    candidates = tidied(pair_guesses(program))
    without_description = tidied(pair_guesses(
        Program(channel_raw=program.channel_raw, title=program.title, start=program.start,
                match_raw=program.match_raw, description="")))
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


def tournament_whole(program: Program, verdict: live.Verdict,
                     sports: sport.Sports, reference: Reference | None,
                     start_kyiv: datetime | None,
                     guess_site: bool = False,
                     markers: live.Markers | None = None) -> live.Verdict | None:
    """Книга 138: теннис, турнир назван ОДНИМ КУСКОМ — пары в строке нет.

    Решение владельца 04.10: трансляцию турнира без игроков показываем
    названием турнира (`app/broadcast.py`). Оно работало, только когда
    заголовок делился по тире на «пару» («ATP 500 Tokyo - 1/4 Finale»).
    «ATP FINALS 2026», «Tenis ATP Torino 2026», «Nitto ATP Finals: Торино»
    пары не дают — строка отсеивалась как «не видно пары команд»: на сборе
    15.11 так терялись 240 прямых эфиров на 20 сайтах (слово владельца 15.11:
    «теннис, если нет имён, попадает просто названием турнира — это уже было
    решено»).

    Правила по порядку:
      Т1. Только строка без пары: причина отсева — «не видно пары команд»
          (сайт сам пометил прямой эфир) или «нет маркера прямого эфира».
          Слово записи, студию и стоп-слово сайт сказал прямо — такие строки
          сюда не доходят (`live.check`). Там слово записи ищется в
          пометках и описании; здесь — ещё и в самом заголовке, рубрике и
          лиге: «ATP Finals (herhaling)» со значком эфира — запись.
      Т2. Строка — теннис по тому, что сайт пишет о событии сам: заголовок,
          рубрика, лига. Описание не читаем: там свободный текст.
      Т3. В этих же полях назван турнир, а не один лишь вид спорта
          (`broadcast.names_tournament`): слово тура или турнира, стадия, год.
      Т0. Игроки в строке названы — это показ матча, а не турнира: хоть одна
          догадка о паре (`pair_guesses`: поле пары, заголовок, описание)
          знакома эталону по словам (`Reference.may_know`). Эталон такой
          показ эфиром не признал (иначе строка сюда бы не дошла) — значит,
          это запись: «Nitto ATP Finals: Shelton - Fils» у movistarplus.es
          наутро после матча, в минуту начала чужой встречи (сбор 15.11).
      (книга 146: в Т4 и Т5 турнир узнаётся по ГОРОДУ, в любом туре —
      `broadcast.city`; исключение Т4 действует только в днях, на которые у
      эталона уже есть теннисная сетка — `broadcast.covered`.)
      Т4. Сайт пометил эфир — берём. Исключение: тур и город узнаны, эталон
          богат теннисом (`broadcast.RICH`), а этого турнира в нём нет вовсе
          — турнир сейчас не идёт, это запись («ATP Shanghai» с пометкой
          эфира в ноябре, tring.al).
      Т5. Сайт эфир не пометил — берём, только если сайт эфир не помечает
          вовсе (`guess_site`: `parse_live.REPEAT_GUESS_DOMAINS`), тур и
          город узнаны и в эталоне есть матч этого турнира, который
          начинается рядом с показом (`broadcast.starts_near`). Эфир тогда
          угадан (`live_guess`), подтвердил его эталон. У сайта с честной
          пометкой строка без пометки — не эфир, эталон её не спасает:
          матчи турнира идут весь день, и повтор совпал бы с одним из них.
      Т6. «Пара» строки — название турнира, как написал сайт, и служебная
          вторая сторона `broadcast.SESSION`. Название — заголовок; если
          турнир назван не в нём, а в лиге («Finale» + «ATP Finals»), —
          лига и заголовок. Дальше строки сводит по туру и городу
          `parse_live` («ATP Finals - Turin»), как и заголовки с тире.

    Что узнано о турнире, кладётся в `program.extra[TOURNAMENT]` — по этой
    пометке фильтр «угаданный эфир без эталона» не снимает строку (пары у
    неё нет по определению). Возвращает новый вердикт либо None — тогда
    строка решается, как раньше."""
    if verdict.reason not in (NO_PAIR, NO_LIVE):                         # Т1
        return None
    title = (program.title or "").strip()
    league = (program.league_raw or "").strip()
    head = " ".join(x for x in (title, program.sport_raw, league) if x)
    if markers is not None and markers.found(markers.not_live, head):    # Т1
        return None
    # книга 163: слово повтора, обзора, жеребьёвки или студии в заголовке
    # трансляции турнира на любом языке — не эфир (у сайта без пометки эфира
    # такой показ в минуту матча прошёл бы трансляцией)
    if broadcast.not_live_title(head):                                   # Т1
        return None
    if sports.detect(head)[0] != "T":                                    # Т2
        return None
    if not broadcast.names_tournament(head):                             # Т3
        return None
    # Т0. Книга 146: догадка о паре — игроки, только если ни одна её сторона
    # сама не название турнира: «Теннис. WTA. Итоговый турнир. Индиан» —
    # «Уэллс. Финал» (news.by, город с дефисом) эталон «знал» по словам
    # «Индиан» и «Уэльс», и прямой эфир финала терялся
    if reference is not None and any(
            reference.may_know(home, away) for home, away in pair_guesses(program)
            if not broadcast.names_tournament(home) and not broadcast.names_tournament(away)):
        return None
    known = reference.tournaments() if reference is not None else None
    found = broadcast.key(head, known) if known else ("", "")
    # книга 146: «идёт ли турнир» спрашиваем по ГОРОДУ, в любом туре — сайт и
    # эталон зовут тур по-разному («WTA 125 Colina» у эталона — Challenger)
    where = (found[1] or broadcast.city(head, known)) if known else ""
    near = bool(where and broadcast.city_starts_near(where, start_kyiv, known))
    if verdict.reason == NO_PAIR:                                        # Т4
        if where and not broadcast.city_played(where, known) \
                and known.get("matches", 0) >= broadcast.RICH \
                and broadcast.covered(start_kyiv, known):
            return None
        marker = verdict.live_marker
    else:                                                                # Т5
        if not (guess_site and near):
            return None
        program.extra["live_guess"] = True
        marker = REFERENCE_MARKER
    name = next((text for text in (title, " ".join(x for x in (league, title) if x))
                 if broadcast.names_tournament(text)), head)              # Т6
    program.extra[TOURNAMENT] = {"тур": found[0], "город": where, "эталон": near}
    return live.Verdict(True, "", live_marker=marker, home=name,
                        away=broadcast.SESSION)


# ── книга 182: студия, внутри которой идёт матч ─────────────────────────────
#: так `live.check` начинает причину отсева по стоп-слову заголовка
STOP_IN_TITLE = "стоп-слово в заголовке: "
#: пометка строки «студия с матчем внутри»: {"слово": слово студии из
#: заголовка, "начало": начало матча по эталону, "матч": ключ матча эталона}
STUDIO = "студия_с_матчем"
#: С3: следующая передача канала начинается не раньше, чем через столько
#: после начала матча. Замер по сборам 22–27.11: у передач перед матчем — от
#: −12 до 0 минут, у студий alkass.net с матчем внутри — 150–180
STUDIO_COVER = timedelta(minutes=90)


def studio_word(reason: str, markers: live.Markers) -> str:
    """Книга 182, С1: строку отсеяло стоп-слово заголовка, и это слово
    класса «студия» (`Markers.studio`) — само слово; иначе пусто."""
    if not (reason or "").startswith(STOP_IN_TITLE):
        return ""
    word = reason[len(STOP_IN_TITLE):]
    return word if markers.found(markers.studio, word) else ""


def studio_pair(program: Program, markers: live.Markers,
                reference: Reference | None, start_kyiv: datetime | None,
                league_category: str = ""):
    """Книга 182, С2: пара из подписи передачи-студии, которую эталон
    подтверждает как эфир. Правила:
      П1. название студии из заголовка срезается (`live.studio_cut`); остатка
          нет — None;
      П2. в остатке нет другого стоп-слова, слова передачи до или после
          матча, слова записи: остаток проходит `live.check` либо не проходит
          лишь потому, что нет пометки эфира или пара не прочиталась
          (`ASK_REFERENCE_REASONS`). «Studio før Liverpool - City» после
          среза — «før Liverpool - City»: передача перед матчем, None;
      П3. прошлый сезон в подписи — классика, None (`past_season`);
      П4. пара читается ТОЛЬКО из остатка заголовка (`live.split_candidates`).
          Поле пары разборщика не берём: в нём название студии слиплось с
          командой («Mondial Studio 2 - Dominican», alkass.net). Описание не
          берём: свободный текст;
      П5. эталон подтверждает догадку как эфир ЦЕЛИКОМ — «пара» либо «метки
          из эталона» (`Reference.confirm`: матч начинается от 15 минут до
          показа до часа после него). «Одна сторона» не годится;
      П6. все подтверждённые догадки — один и тот же матч, иначе None.
    Возвращает (вердикт с парой в порядке эталона, ответ эталона) либо None.
    Сама по себе пара строку не спасает — ещё С3 и С4 (`studio_inside`)."""
    if reference is None or start_kyiv is None:
        return None
    rest = live.studio_cut(markers, program.title or "")                 # П1
    if not rest:
        return None
    bare = Program(channel_raw=program.channel_raw, title=rest, start=program.start,
                   description=program.description, league_raw=program.league_raw,
                   sport_raw=program.sport_raw, live_raw=program.live_raw, match_raw=" ")
    verdict = live.check(bare, markers)                                  # П2
    if not verdict.ok and verdict.reason not in ASK_REFERENCE_REASONS:
        return None
    if past_season(" ".join(x for x in (program.title, program.league_raw) if x),
                   start_kyiv):                                          # П3
        return None
    found: list[tuple[str, str, Confirmed]] = []
    for pair in live.split_candidates(rest):                             # П4
        pair = tidy_sides(*pair, markers, reference)
        if pair is None:
            continue
        home = leagues.with_category(pair[0], league_category)
        away = leagues.with_category(pair[1], league_category)
        got = reference.confirm(home, away, start_kyiv)
        if got is not None and got.how in ("пара", MARKS_HOW):           # П5
            found.append((home, away, got))
    if not found or len({_entry_id(got) for _h, _a, got in found}) != 1:  # П6
        return None
    home, away, got = found[0]
    if got.swapped:
        home, away = away, home
    return (live.Verdict(True, "", live_marker=verdict.live_marker or REFERENCE_MARKER,
                         home=home, away=away), got)


def studio_inside(programs: list, rows: list, markers: live.Markers,
                  reference: Reference | None, again) -> int:
    """Книга 182 (жалоба владельца 27.11.2026, #11633 «почему нет канала Al
    kass 1 ?»): студия, ВНУТРИ которой идёт матч, — показ матча.

    alkass.net подписал трёхчасовой показ «Mondial Studio 2 / Algeria ×
    Dominican»; отдельной строки матча у канала нет. Стоп-слово «Studio»
    срезало строку раньше эталона, и за день так потерялись все четыре показа
    чемпионата мира U17. Но студия перед матчем («Studio før Liverpool -
    City», «Studio: Levante - Ath Bilbao») матчем быть не должна — поэтому
    строка берётся, только когда выполнено ВСЁ:
      С1. отсев — стоп-слово заголовка класса «студия» (`studio_word`);
      С2. в подписи без названия студии есть пара, других стоп-слов нет, и
          эталон подтверждает пару как эфир целиком (`studio_pair`);
      С3. показ накрывает матч: следующая передача ЭТОГО канала на странице
          начинается не раньше `STUDIO_COVER` после начала матча. Следующей
          передачи на странице нет — конец показа неизвестен, не гадаем;
      С4. своей строки этого матча на странице нет — ни на этом канале, ни на
          другом: принятой строки, которую эталон подтверждает как тот же
          матч. Есть — студия идёт вокруг матча, а не вместо него. Судим по
          строкам ДО правила: один показ на двух каналах берётся на обоих;
      С5. строка разбирается заново (`again` — `classify(studio=True)`) и
          должна дойти до конца: вид спорта наш, время разобрано. Эфир —
          угаданный (`live_guess`): дальше его проверяют те же фильтры
          повторов, что и прочие угадайки.
    Не подошла — строка остаётся отсевом, как была. `rows` правится на месте;
    возвращает, сколько строк взято."""
    if reference is None or markers.studio is None:
        return 0
    before = list(rows)                                                  # С4
    taken = 0
    for i, (program, row) in enumerate(zip(programs, before)):
        if row.ok or row.start_kyiv is None \
                or not studio_word(row.reason, markers):                 # С1
            continue
        extra = dict(program.extra or {})
        new = again(program)                                             # С2, С5
        mark = (program.extra or {}).get(STUDIO)
        if new.ok and mark and _studio_covers(program, row, mark, programs, before) \
                and not _own_row(row, mark["матч"], before, reference):  # С3, С4
            rows[i] = new
            taken += 1
            continue
        program.extra.clear()               # не подошла: пометки разбора — долой
        program.extra.update(extra)
    return taken


def _studio_covers(program: Program, row: Row, mark: dict, programs: list,
                   rows: list) -> bool:
    """Книга 182, С3: следующая передача того же канала на странице начинается
    не раньше `STUDIO_COVER` после начала матча."""
    kickoff = datetime.fromisoformat(mark["начало"])
    later = [r.start_kyiv.replace(tzinfo=None) for p, r in zip(programs, rows)
             if r is not row and r.start_kyiv is not None
             and p.channel_raw == program.channel_raw and r.start_kyiv > row.start_kyiv]
    return bool(later) and min(later) - kickoff >= STUDIO_COVER


def _own_row(row: Row, match: str, rows: list, reference: Reference) -> bool:
    """Книга 182, С4: на странице есть другая принятая строка, которую эталон
    подтверждает как тот же матч."""
    for other in rows:
        if other is row or not other.ok or other.start_kyiv is None \
                or not other.home or not other.away:
            continue
        got = reference.confirm(other.home, other.away, other.start_kyiv)
        if got is not None and _entry_id(got) == match:
            return True
    return False


def classify(program: Program, markers: live.Markers, sports: sport.Sports,
             league_sports: dict[str, str] | None = None,
             pair_sports: dict[str, str] | None = None,
             reference: Reference | None = None,
             langs: frozenset | None = None,
             guess_site: bool = False, studio: bool = False) -> Row:
    """`studio` (книга 182) — строку-студию разбираем заново, разрешая паре
    из подписи спасти её (`studio_inside`, С2 и С5); в обычном разборе — нет.
    `langs` — языки сайта строки (`site_lang.of`, слово владельца 25.10,
    книга 084): служебные слова — пол, эфир, повтор, стоп-слова — ищутся
    только на языке сайта и общие. None — все языки, как раньше. Строку
    читал одолженный разбор (`extra["borrowed"]`) — его язык тоже: он пишет
    свои пометки по-своему (датский «direkte» у шведского сайта).
    `guess_site` — сайт эфир не помечает вовсе (книга 138, правило Т5
    `tournament_whole`)."""
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
    # поля — через «|» (книга 146): примечание в конце заголовка («начнётся
    # после женского баскетбола») не должно съесть начало описания
    row.league_category = leagues.category(
        " | ".join(x for x in (program.league_raw, program.title,
                               program.description) if x), langs)

    verdict = live.check(program, markers)
    # книга 157: к стороне прилипла стадия или приписка об эфире — чистим
    # (`tidy_sides`, М1–М2). «Пара» из турнира и стадии (М3) — не пара:
    #   а) настоящую пару ищем в заголовке и описании, её подтверждает эталон
    #      (rtp.pt: «Eurobasket Feminino 2027 - 2ª Fase de Qualificação», а
    #      в описании «Portugal x Alemanha»). Эфир при этом — слово сайта;
    #   б) не нашлась — строка идёт дальше, как шла, и если вид спорта наш
    #      (футбол, баскетбол), то пары в ней нет. Чужой вид спорта и теннис
    #      решаются по-прежнему: там «турнир — стадия» — обычная строка
    def tidy(home: str, away: str):
        return tidy_sides(home, away, markers, reference)
    stage_side = False
    if verdict.ok:
        sides = tidy(verdict.home, verdict.away)
        if sides is None:
            stage_side = True
        elif sides != (verdict.home, verdict.away):
            program.extra[TRIMMED] = _tidy_mark(verdict.home, verdict.away, *sides)
            verdict = live.Verdict(True, "", live_marker=verdict.live_marker,
                                   home=sides[0], away=sides[1])
    row.live_marker = verdict.live_marker
    row.home, row.away = verdict.home, verdict.away
    confirmed = None
    if stage_side:
        guessed = "live_guess" in program.extra
        rescued = ask_reference(
            program, live.Verdict(False, NO_PAIR, live_marker=verdict.live_marker),
            reference, row.start_kyiv, row.league_category,
            stop=lambda words: markers.found(markers.stop_title, words), tidy=tidy)
        if rescued is not None:                                             # а
            verdict, confirmed = rescued
            stage_side = False
            row.by_reference = confirmed.how
            row.home, row.away = verdict.home, verdict.away
            if not guessed:
                program.extra.pop("live_guess", None)       # эфир пометил сайт
    elif not verdict.ok:
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
            stop=lambda words: markers.found(markers.stop_title, words), tidy=tidy)
        if rescued is None and studio and studio_word(verdict.reason, markers):
            # книга 182, С2: студия, внутри которой идёт матч, — пара из
            # подписи без названия студии, подтверждённая эталоном целиком.
            # Накрывает ли показ матч и нет ли у матча своей строки (С3, С4),
            # решает `studio_inside` — у него вся страница
            rescued = studio_pair(program, markers, reference, row.start_kyiv,
                                  row.league_category)
            if rescued is not None:
                program.extra["live_guess"] = True
                program.extra[STUDIO] = {
                    "слово": studio_word(verdict.reason, markers),
                    "начало": rescued[1].start.isoformat(timespec="minutes"),
                    "матч": _entry_id(rescued[1])}
        if rescued is None:
            # книга 138: пары нет вовсе, а строка — теннисный турнир одним
            # куском («ATP FINALS 2026») — трансляция турнира без игроков
            whole = tournament_whole(program, verdict, sports, reference,
                                     row.start_kyiv, guess_site, markers)
            if whole is None:
                row.reason = verdict.reason
                return row
            no_pair_reason = verdict.reason
            verdict = whole
        else:
            verdict, confirmed = rescued
            row.by_reference = confirmed.how
        row.live_marker = verdict.live_marker
        row.home, row.away = verdict.home, verdict.away
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
    # книга 138: строка — трансляция турнира одним куском; её «пара» —
    # название турнира и служебная сторона, меток пола и возраста не носит
    whole_title = TOURNAMENT in (program.extra or {})
    # книга 156: в поле лиги — не лига (хвост заголовка, стадия, сама пара):
    # пара уже известна — лигу решают правила Л1–Л6 (`leagues.settle`)
    if not whole_title:
        row.league = leagues.settle(program.league_raw, program.title,
                                    verdict.home, verdict.away)
        # книга 164: к стороне прилипла лига («Manchester C UEFA Women's
        # Champions League», «NBA herrar Philadelphia 76ers») — срезаем и
        # решаем лигу заново, уже с чистой парой
        if verdict.home and verdict.away:
            чистые = league_off_sides(verdict.home, verdict.away, league_sports,
                                      row.league, reference)
            if чистые != (verdict.home, verdict.away):
                # что срезано: у гостей — хвост стороны, у хозяев — её начало
                срезано = (verdict.away[len(чистые[1]):] if чистые[1] != verdict.away
                           else verdict.home[:len(verdict.home) - len(чистые[0])])
                verdict = live.Verdict(True, "", live_marker=verdict.live_marker,
                                       home=чистые[0], away=чистые[1])
                row.home, row.away = verdict.home, verdict.away
                # поле лиги её не дало (в нём стояла вся строка целиком) —
                # лига строки и есть то, что срезано со стороны
                row.league = leagues.settle(program.league_raw, program.title,
                                            verdict.home, verdict.away) \
                    or leagues.clean(срезано.strip(live._TRIM_EDGE))
    # книга 095 (#9541): сторона пары — имя своего канала («Sport 2 - Program
    # Sportiv» у ipko) — заставка канала, а не матч: ни на витрину, ни в очередь
    if channel_side(program.channel_raw, row.home, row.away, reference):
        row.reason = CHANNEL_SIDE
        return row

    # Дописываем метку турнира к именам, иначе женский матч склеится с
    # мужским (правило проекта: лишний ` W` лучше потерянного).
    if row.league_category and not whole_title:
        row.home = leagues.with_category(row.home, row.league_category)
        row.away = leagues.with_category(row.away, row.league_category)
    # Пол по одной стороне (владелец 28.09, #3535): женская команда с
    # мужской не играет, и если хоть одна сторона женская — вся пара
    # женская. Возраст так НЕ переносим: в EFL Trophy «Chelsea U21» честно
    # играет со взрослым Wycombe
    клуб_спорт = ""
    if row.home and row.away and not whole_title:
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
    if whole_title and letter != "T":
        # книга 138, Т2: турнир одним куском берём только теннисом. Полное
        # решение о виде спорта (с описанием, жанром, месяцем турнира)
        # сказало иное — строка решается, как раньше: пары нет
        program.extra.pop(TOURNAMENT, None)
        program.extra.pop("live_guess", None)
        row.home = row.away = ""
        if letter != "-":
            row.reason = no_pair_reason
            return row
        # книга 150: вид спорта — чужой («Wheelchair tennis»): строка с
        # пометкой эфира идёт во вкладку «Other Sport», как и чужой вид с парой
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
    if stage_side and letter in ("F", "B"):
        # книга 157, М3 (б): «пара» — турнир и стадия, команд в строке нет
        row.home = row.away = ""
        row.reason = NO_PAIR
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
        domain: str = "", guess_site: bool = False) -> list[Row]:
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
    rows = [classify(p, markers, sports, league_sports, pair_sports, reference,
                     langs, guess_site)
            for p in programs]
    # книга 182: студия, внутри которой идёт матч, — правило видит всю
    # страницу (следующую передачу канала, свою строку матча)
    studio_inside(programs, rows, markers, reference,
                  lambda p: classify(p, markers, sports, league_sports, pair_sports,
                                     reference, langs, guess_site, studio=True))
    return rows

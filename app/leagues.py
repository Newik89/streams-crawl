# -*- coding: utf-8 -*-
"""Названия лиг: чистка сырого имени и категория турнира (ТЗ разд. 8).

Каждый сайт пишет лигу на свой лад, и мусор у всех разный:

    teleman.pl    `Piłka nożna: Liga angielska`      вид спорта спереди
    sporttv.pt    `EFL CHAMPIONSHIP - FUTEBOL`       вид спорта сзади
    nova.bg       `Висша лига 2026/2027`             сезон сзади

`clean()` снимает это обвес и оставляет ядро (`Liga angielska`,
`EFL Championship`, `Висша лига`). Ядро — ещё не канон: канон
(`ENGLAND: Premier League`) даёт словарь в базе, а чего в нём нет, уходит в
очередь модерации.

`category()` вытаскивает из названия турнира пол и возраст (`W`, `U19`) —
их потом дописывают к именам команд. Правило проекта: лишний ` W` — меньшее
зло, чем потерянный, поэтому ищем щедро.
"""

from __future__ import annotations

import re

# Вид спорта, которым сайт подписывает лигу. Спереди — через двоеточие,
# сзади — через дефис. Список пополняется вместе с источниками.
_SPORT_WORDS = (
    "piłka nożna", "pilka nozna", "koszykówka mężczyzn", "koszykówka",
    "koszykowka", "tenis", "siatkówka",
    "futebol", "ténis", "tenis", "basquetebol", "andebol",
    "футбол", "баскетбол", "тенис", "волейбол",
    "football", "basketball", "tennis", "fussball", "calcio",
)
# До двоеточия сайт иногда уточняет разряд: `Piłka nożna kobiet:`,
# `Koszykówka mężczyzn:`. Уточнение снимаем вместе с видом спорта — пол уже
# взят отдельно, функцией `category()` по СЫРОЙ строке, до этой чистки.
_SPORT_PREFIX = re.compile(
    rf"^\s*(?:{'|'.join(re.escape(w) for w in _SPORT_WORDS)})[^:：]{{0,24}}[:：]\s*",
    re.I)
_SPORT_SUFFIX = re.compile(
    rf"\s*[-–—]\s*(?:{'|'.join(re.escape(w) for w in _SPORT_WORDS)})\s*$", re.I)

# Сезон: `2026/2027`, `2026-2027`, `26/27`, одиночный год в конце.
_SEASON = re.compile(r"\s*[-–—]?\s*\b(?:19|20)\d{2}\s*[/\-–—]\s*(?:19|20)?\d{2}\b")
_SEASON_SHORT = re.compile(r"\s*\b\d{2}\s*/\s*\d{2}\b")
_YEAR_TAIL = re.compile(r"\s*\b(?:19|20)\d{2}\b\s*$")

# Хвосты вроде `- JOGOS` (пометка сайта «матчи»), пустые скобки, двойные пробелы.
_SITE_TAILS = re.compile(r"\s*[-–—]\s*(?:jogos|matches|mecze|мачове)\s*", re.I)
_EMPTY_BRACKETS = re.compile(r"\(\s*\)|\[\s*\]")
_EDGE = " -–—:.,/|"

#: возраст турнира: и коротко («U21», «U-21»), и словом — кипрский cyta
#: пишет «UEFA UNDER - 21 EURO», и матч оставался без возраста, а значит
#: не сходился с эталоном и жил двойней рядом со своей же игрой
#: (жалоба владельца 25.09: Cyprus — Romania, каналы разъехались)
#: «Sub-19», «Sub 23» — так возраст пишут португальские и испанские сайты
#: (canal11.pt, sporttv.pt, movistarplus): без него «Liga BPI Sub-19» шла
#: взрослой (12.10)
_AGE = re.compile(r"\bU-?\s?(\d{2})\b|\b(?:under|sub)[\s-]{0,3}(\d{2})\b(?![.:]\d)", re.I)
#: Слово «женский» ПО ЯЗЫКАМ (слово владельца 25.10, книга 084): ищется
#: только на языке сайта строки (`app/site_lang.py`) и общее (`None`).
#: Повод: венгерское «női», записанное и как «noi», нашлось в вьетнамском
#: «Ha Noi» на хорватском sportklub.hr — Лига чемпионов Азии стала женской
#: (#7925). Новое слово — в кучку своего языка; общая — только английское и
#: пометки, которые пишут сайты разных стран.
_WOMEN_BY_LANG: tuple = (
    # общие: английское и «(w)»
    (None, r"\bwomen'?s?\b|\(w\)"),
    (("pl",), r"\bkobiet\w*\b"),
    # испанский, португальский, румынский, французский, итальянский:
    # femenino/feminino/feminin
    (("es", "pt", "ro", "fr", "it"), r"\bfem[ei]nin[ao]?\b|\bfeminin\w*\b"),
    (("it",), r"\bdonne\b|\bfemminil\w*\b"),
    (("de",), r"\bfrauen\w*\b"),
    (("tr",), r"\bkadınlar\b"),
    # сербохорватский и словенский: «ženske», «(ž)», «za žene»
    (("hr", "sr", "bs", "sl"), r"\bžensk\w*\b|\bzensk\w*\b|\bžene?\b|\bza žene\b|\(ž\)"),
    # чешский и словацкий: «MS žen», «ženy»
    (("cs", "sk"), r"\bženy\b|\bžen\b"),
    # одиночная «Ž» («Europe Cup Ž») — сербы, хорваты, чехи
    (("hr", "sr", "bs", "sl", "cs", "sk"), r"(?<!\w)ž(?!\w)"),
    # скандинавские: damer/kvinner/kvinnor/kvinder, «(k)» — kvinder/kvinner
    # (dr.dk, allente.no, tv2.no — #205), шведское «(Dam)» в скобках
    # (tvmatchen.nu; голое «dam» — английское слово, его не берём)
    (("sv", "no", "da"), r"\bdamer\b|\bkvinn\w*\b|\bkvinder\b|\(k\)|\(dam\)"),
    (("nl", "fr"), r"\bdames\b"),
    # финское: «naiset», «Naisten Liiga»
    (("fi",), r"\bnaiset\b|\bnaisten\b"),
    # венгерское «női» — только с диакритикой (книга 083)
    (("hu",), r"\bnői\b"),
    # литовское «moterų» (tv3.lt)
    (("lt",), r"\bmoter\w*\b"),
    # кириллица: «женская», «Женщины» (vsetv), болгарское «жени», украинское
    # «жінки», одиночная «Ж»; казахское «(әйелдер)» (sports.kz, 06.10)
    (("ru", "uk", "be", "bg", "sr", "mk", "kk"),
     r"\bжени\b|\bженск\w*\b|\bженщин\w*\b|\bжінк\w*\b|(?<!\w)ж(?!\w)|\bәйел\w*"),
    # греческое: «γυναικών», одиночная «Γ»
    (("el",), r"γυναικ\w*|(?<!\w)γ(?!\w)"),
    # иврит: «הנשים» с артиклем (sport5, #2525), «לנשים» с предлогом (#2074);
    # «אנשים» («люди») не ловится: перед נ стоит א
    (("he",), r"\b[הל]?נשים\b"),
)


def _women_re(langs) -> re.Pattern:
    """Шаблон слова «женский» для языков сайта (`langs` None — все языки)."""
    parts = [pattern for own, pattern in _WOMEN_BY_LANG
             if own is None or langs is None or set(own) & set(langs)]
    return re.compile("|".join(parts), re.I)


#: все языки — для строк без известного сайта
_WOMEN = _women_re(None)
_WOMEN_CACHE: dict = {}


#: турниры, которые бывают ТОЛЬКО женскими: пол в названии не пишут вовсе,
#: а мужской турнир страны называется иначе (`Toppserien` — женская высшая
#: Норвегии, мужская зовётся `Eliteserien`). Без этого списка женский матч с
#: такого сайта потеряет ` W` и разойдётся с той же игрой с другого источника
#: (поймано на `tv2.no` 01.09.2026).
_WOMEN_LEAGUES = re.compile(
    r"\btoppserien\b|\bdamallsvenskan\b|\bkvindeligaen\b"
    r"|\bfrauen-?bundesliga\b|\bnwsl\b|\bekstraliga kobiet\b"
    # английская женская суперлига пишется без слова «женская»;
    # без страны `WSL` не берём — так зовут и лигу сёрфинга
    r"|england:\s*wsl\b"
    # Финляндия и Швеция (06.10, к заведению tvmatchen.nu/tvmatsit.com):
    # высшая женская лига Финляндии зовётся «Kansallinen Liiga» (мужская —
    # Veikkausliiga), вторая женская лига Швеции — «Elitettan»; пола в
    # названии нет, и без списка их команды шли бы мужскими
    r"|\bkansallinen liiga\b|\belitettan\b"
    # Португалия: «Liga BPI» — высшая женская (мужская — Liga Portugal
    # Betclic); canal11.pt пишет «Liga BPI» без пола, и Rio Ave — Porto
    # 17.10 не сводился с эталоном «Rio Ave W — Porto W» (владелец 12.10).
    # Следующую такую лигу найдёт самопроверка сбора, проверка 12
    r"|\bliga bpi\b"
    # Испания: «Liga F» — высшая женская (movistarplus: Athletic — Valencia
    # 17.10 шёл мужским; нашла проверка 12 в первый же прогон, 12.10).
    # «Liga Futsal» не задевает: после «f» нужна граница слова
    r"|\bliga f\b"
    # Канада: «Northern Super League» — высшая женская (с 2025); tvpassport
    # пишет «Northern Super League Soccer: Calgary Wild at Vancouver Rise»
    # без пола, и матч прилип к мужскому Cavalry — Vancouver FC #7274
    # (Calgary ≈ Cavalry, Vancouver Rise ≈ Vancouver FC; 22.10)
    r"|\bnorthern super league\b", re.I)

#: турниры, которые бывают ТОЛЬКО молодёжными, а возраст в названии сайт не
#: пишет (как `_WOMEN_LEAGUES` для пола). Значение — возраст, под которым
#: команды этой лиги записаны в эталоне flashscore. Без списка молодёжный
#: матч шёл с именами взрослых и сводился со взрослым клубом (canal11.pt:
#: «Liga Next Gen» FELGUEIRAS — ESTRELA ↔ эталон «Felgueiras U23 — Estrela
#: U23», самопроверка #205, 06.10). Правила:
#:   1. только турниры, где в эталоне У ВСЕХ команд одна метка возраста;
#:   2. название целиком, без общих слов: «Premier League 2» — да, но не
#:      «Premier League 2.» («2. kolo» — тур взрослой лиги);
#:   3. встретил новый — дописать сюда с возрастом из эталона.
_AGED_LEAGUES = (
    # Португалия: «Liga Next Gen» (до 2025 — «Liga Revelação»), U23
    (re.compile(r"\bliga next ?gen\b|\bliga revela[cç][aã]o\b", re.I), "U23"),
    # Англия: «Premier League 2», «Professional Development League» — U21
    (re.compile(r"\bpremier league 2(?![\w.])|\bprofessional development league\b",
                re.I), "U21"),
    # ЮАР: «Diski Challenge» (резервная лига ПСЛ) — U23
    (re.compile(r"\bdiski challenge\b", re.I), "U23"),
)

#: молодёжный турнир, в названии которого нет цифры возраста: teleman пишет
#: юношескую ЛЧ «Liga Młodzieżowa UEFA», и без метки юноши шли той же парой,
#: что взрослые, — взрослая трансляция HTV 2 отсекалась «поздним повтором»
#: юношеского матча (кейс Ливерпуль — Атлетико 09.09, поймано 05.09)
_YOUTH_LEAGUES = re.compile(
    r"youth league|liga m[łl]odzie[żz]owa|молод[её]жн\w*|молодіжн\w*"
    r"|юношеск\w*|юнацьк\w*|omladinsk\w*|mladežk\w*|ifjúsági|jugendliga"
    # «ליגת העל בכדורגל נוער» — юношеская высшая Израиля у sport5 (14.09)
    r"|λίγκα νέων|(?<!\w)[לה]?נוער(?!\w)", re.I)
#: клубы, у которых такое имя носит ТОЛЬКО женская команда (обычно спонсор
#: женского состава в названии): сайт пишет их без W, а без пометки матч
#: уходит в мужские (#3535, 28.09: cyta «USK Prague - Athinaikos Qualco»).
#: Дописывать сюда только бесспорных — мужской клуб с тем же именем сделал
#: бы мужской матч женским. Значение — вид спорта клуба: без него строку
#: cyta с «Mechelen» старый разбор записал ФУТБОЛОМ (Mechelen в базе —
#: футбольный клуб), а это женский баскетбол
_WOMEN_TEAMS = {
    re.compile(r"(?i)\b(athinaikos|αθηναϊκός|αθηναικος)\s+qualco\b"): "B",
}


def women_team(name: str) -> str:
    """Вид спорта (`B`…), если имя носит только женская команда
    (`_WOMEN_TEAMS`); пусто — обычная команда."""
    for pattern, letter in _WOMEN_TEAMS.items():
        if pattern.search(name or ""):
            return letter
    return ""


#: «молодёжная СБОРНАЯ» — это U21, а не U19: в русской/украинской/польской
#: традиции U19 зовут «юношеской». ntvplus пишет «Молодежные сборные» у
#: Сербия U21 — Россия U21, и игра получала U19 (#3880, 27.09)
_U21_NATIONAL = re.compile(
    r"молод[её]жн\w*\s+сборн\w*|молодіжн\w*\s+збірн\w*"
    r"|reprezentacj\w*\s+m[łl]odzie[żz]ow\w*|m[łl]odzie[żz]ow\w*\s+reprezentacj\w*",
    re.I)


def clean(raw: str) -> str:
    """Сырое название лиги без вида спорта, сезона и пометок сайта.

    Возвращает пустую строку, если после чистки ничего не осталось — значит
    сайт положил в поле лиги только вид спорта, и опираться на него нельзя.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    text = _SPORT_PREFIX.sub("", text)
    text = _SPORT_SUFFIX.sub("", text)
    text = _SITE_TAILS.sub(" ", text)
    text = _SEASON.sub(" ", text)
    text = _SEASON_SHORT.sub(" ", text)
    text = _YEAR_TAIL.sub("", text)
    text = _EMPTY_BRACKETS.sub(" ", text)
    return re.sub(r"\s{2,}", " ", text).strip(_EDGE)


def category(raw: str, langs=None) -> str:
    """Пол и возраст турнира: `W`, `U19`, `U16 W`. Пусто — взрослый мужской.

    Нужно, чтобы женский матч не склеился с мужским: у части сайтов пол виден
    только по названию турнира, а команды подписаны одинаково.
    """
    parts = []
    m = _AGE.search(raw or "")
    aged = next((age for pattern, age in _AGED_LEAGUES
                 if pattern.search(raw or "")), "")
    if m:
        parts.append(f"U{m.group(1) or m.group(2)}")
    elif aged:
        parts.append(aged)
    elif _U21_NATIONAL.search(raw or ""):
        parts.append("U21")
    elif _YOUTH_LEAGUES.search(raw or ""):
        parts.append("U19")
    # слово «женский» — на языке сайта (`langs`, книга 084), иначе все языки
    key = frozenset(langs) if langs is not None else None
    women = _WOMEN_CACHE.get(key)
    if women is None:
        women = _WOMEN_CACHE[key] = _women_re(langs)
    if women.search(raw or "") or _WOMEN_LEAGUES.search(raw or ""):
        parts.append("W")
    return " ".join(parts)


def with_category(team: str, league_category: str) -> str:
    """Дописывает категорию турнира к имени команды, если её там ещё нет.
    `Barcelona` + `W` → `Barcelona W`."""
    team = (team or "").strip()
    if not league_category or not team:
        return team
    # `Moreirense U-23` и `Moreirense U23` — одно и то же: перед проверкой
    # убираем дефис после буквы возраста, иначе метка приклеится второй раз
    # (`Moreirense U-23 U23`, поймано на liveonsat 01.09)
    have = _AGE.sub(lambda m: f"U{m.group(1) or m.group(2)}", team.upper())
    for mark in league_category.split():
        if not re.search(rf"(?<!\w){re.escape(mark)}(?!\w)", have):
            team = f"{team} {mark}"
            have = team.upper()
    return team


def team_sports(path=None) -> dict[str, str]:
    """Команда → вид спорта по нашей же базе (выгрузка `dict_sync --export`).
    Ключи — канонические имена; сравнивать их с сырыми надо через
    `names.readings`, как это делает разбор."""
    import json
    from pathlib import Path
    file = Path(path) if path else Path(__file__).resolve().parent.parent         / "data" / "dictionaries.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("team_sports") or {}


def pair_sports(path=None) -> dict[str, tuple[str, str | None]]:
    """Пара команд → (вид спорта, день матча), как сказал владелец. Лежит в
    том же `data/dictionaries.json`, поэтому доступно и обходу на GitHub.

    День ограничивает срок подсказки (владелец 15.09): та же пара в другом
    туре может играть другой спорт. `None` — бессрочная запись. Файл бывает
    двух форматов: старый `{пара: "F"}` и новый `{пара: {"sport": "F",
    "day": "2026-09-17"}}` — читаем оба."""
    import json
    from pathlib import Path
    file = Path(path) if path else Path(__file__).resolve().parent.parent         / "data" / "dictionaries.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, tuple[str, str | None]] = {}
    for k, v in (data.get("sport_hints") or {}).items():
        ключ = " ".join(k.split())
        if isinstance(v, str) and v:
            out[ключ] = (v, None)
        elif isinstance(v, dict) and v.get("sport"):
            out[ключ] = (v["sport"], v.get("day") or None)
    return out


def sports_map(path=None) -> dict[str, str]:
    """Лига → буква вида спорта по подтверждённому словарю
    `data/dictionaries.json` (выгрузка базы, едет в git — доступна и обходу
    на GitHub). Ключи — канон, его часть после `:` и все алиасы, в нижнем
    регистре со схлопнутыми пробелами. Файла нет — пустой словарь."""
    import json
    from pathlib import Path
    file = Path(path) if path else Path(__file__).resolve().parent.parent \
        / "data" / "dictionaries.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    def norm(s: str) -> str:
        return " ".join((s or "").lower().split())
    for league in data.get("leagues") or []:
        letter = league.get("sport")
        if letter not in ("F", "B", "T"):
            continue
        names = [league.get("name") or ""]
        if ":" in names[0]:
            names.append(names[0].split(":", 1)[1])
        names += league.get("aliases") or []
        for name in names:
            key = norm(name)
            if key:
                out.setdefault(key, letter)
    return out

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

_AGE = re.compile(r"\bU-?\s?(\d{2})\b", re.I)
_WOMEN = re.compile(
    r"\bwomen'?s?\b|\bkobiet\w*\b|\bfem[ei]nin[ao]?\b|\bжени\b|\bженск\w*\b"
    r"|\bdonne\b|\bfrauen\w*\b|\bkadınlar\b|\bžensk\w*\b|\bzensk\w*\b|\bfemminil\w*\b"
    r"|\bdamer\b|\bdames\b|\bnaiset\b|\bnői\b|\bnoi\b|\bfeminin\w*\b"
    r"|\bžene?\b|\bza žene\b|\bжінк\w*\b|\bwomen\b|\bkvinn\w*\b|\bkvinder\b"
    r"|\bfrauen\b|\(ž\)|\(w\)"
    # «Чемпионат мира. Женщины» (vsetv), «MS žen» (чехи), «Europe Cup Ž»
    # (сербы), одиночные «Ж»/«Γ» (кириллица, греки) — ЧМ шёл мужским (06.09);
    # «moterų» — литовский tv3.lt (FIBA moterų … čempionatas)
    r"|\bженщин\w*\b|\bženy\b|\bžen\b|(?<!\w)[žжγ](?!\w)|\bmoter\w*\b"
    r"|γυναικ\w*|\bנשים\b", re.I)


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
    r"|england:\s*wsl\b", re.I)

#: молодёжный турнир, в названии которого нет цифры возраста: teleman пишет
#: юношескую ЛЧ «Liga Młodzieżowa UEFA», и без метки юноши шли той же парой,
#: что взрослые, — взрослая трансляция HTV 2 отсекалась «поздним повтором»
#: юношеского матча (кейс Ливерпуль — Атлетико 09.09, поймано 05.09)
_YOUTH_LEAGUES = re.compile(
    r"youth league|liga m[łl]odzie[żz]owa|молод[её]жн\w*|молодіжн\w*"
    r"|юношеск\w*|юнацьк\w*|omladinsk\w*|mladežk\w*|ifjúsági|jugendliga"
    r"|λίγκα νέων", re.I)


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


def category(raw: str) -> str:
    """Пол и возраст турнира: `W`, `U19`, `U16 W`. Пусто — взрослый мужской.

    Нужно, чтобы женский матч не склеился с мужским: у части сайтов пол виден
    только по названию турнира, а команды подписаны одинаково.
    """
    parts = []
    m = _AGE.search(raw or "")
    if m:
        parts.append(f"U{m.group(1)}")
    elif _YOUTH_LEAGUES.search(raw or ""):
        parts.append("U19")
    if _WOMEN.search(raw or "") or _WOMEN_LEAGUES.search(raw or ""):
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
    have = _AGE.sub(lambda m: f"U{m.group(1)}", team.upper())
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


def pair_sports(path=None) -> dict[str, str]:
    """Пара команд → вид спорта, как сказал владелец. Лежит в том же
    `data/dictionaries.json`, поэтому доступно и обходу на GitHub."""
    import json
    from pathlib import Path
    file = Path(path) if path else Path(__file__).resolve().parent.parent         / "data" / "dictionaries.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    подсказки = data.get("sport_hints") or {}
    return {" ".join(k.split()): v for k, v in подсказки.items() if v}


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

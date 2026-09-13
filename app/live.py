# -*- coding: utf-8 -*-
"""Отсев: это прямая трансляция матча или нет (ТЗ разд. 6).

Три условия, все обязательны — двух мало, и это проверено на живых страницах:

1. **Заголовок не из стоп-списка.** `ANTEVISÃO PORTIMONENSE X LEIXÕES SC` на
   `sporttv.pt` идёт с пометкой `DIRETO` и без единого признака записи. Те же
   команды, тот же маркер — но это превью за двадцать минут до игры. Поэтому
   заголовок проверяется первым, до всяких маркеров.
2. **Есть маркер прямого эфира.** Где его взять — дело парсера сайта: на
   `nova.bg` это слово в описании, на `teleman.pl` — атрибут `title` у
   отдельного тега, на `sporttv.pt` — поле `tipoEmissao`.
3. **Нет маркера записи или студии.**

Плюс четвёртое, из того же раздела ТЗ: в строке должна читаться **пара
команд**. Здесь мы только проверяем, что пара есть; перевод названий в
канонический вид — этап 3, за него отвечают словари.

Сами слова лежат в `data/markers.json`, а не в коде: список пополняется по
мере подключения сайтов. У источника их можно перекрыть через
`selector_config` → `markers`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKERS_FILE = ROOT / "data" / "markers.json"

# разделители пары команд: `Мидълзбро - Уест Бромич`, `PORTIMONENSE X LEIXÕES`,
# `Karlsruher SC vs VfL Wolfsburg`. Дефис без пробелов не берём — он бывает
# внутри названия (`Bodø/Glimt`, `Saint-Étienne`). Двоеточие разделителем не
# считаем: через него сайты пишут не пару, а рубрику — `Piłka nożna: Liga
# niemiecka` тогда сошло бы за матч. Одинокое `v` тоже не берём — чешское
# `Fotbal v Evropě` дало бы ту же ложную пару.
_SPLIT = re.compile(r"\s+(?:[-–—]|[xX]|[vV][sS]|[vV]\.|contra)\s+")
# явные матчевые разделители — тире среди них нет: у sporttv.pt тире отделяет
# хвост стадии («BOCA JUNIORS X SÃO PAULO – QUARTOS DE FINAL 1ª MÃO»),
# и общий сплит давал три части вместо пары (кейсы #766 #908, 04.09)
_STRONG_SPLIT = re.compile(r"\s+(?:[xX]|[vV][sS]|[vV]\.|contra)\s+")
_DASH_TAIL = re.compile(r"\s+[-–—]\s+.*$", re.S)
# хвост в скобках: `(se speciálním studiem)`
_BRACKETS = re.compile(r"\s*[(\[].*?[)\]]\s*")
# то, что стоит перед первой командой: `3 кръг, `, `mecz: `, `Futebol: `
_LEFT_JUNK = re.compile(r"^.*[,:]\s+(?=\S)")
# то, что идёт после второй: `, директно`, `, 3 кръг`
_RIGHT_JUNK = re.compile(r"\s*,.*$", re.S)


def _flatten(node) -> list[str]:
    """В файле слова разложены по кучкам («проверено», «из ТЗ») — для чтения
    человеком. Коду нужен один плоский список."""
    if isinstance(node, str):
        return [] if node.startswith("Маркеры") else [node]
    if isinstance(node, list):
        return [w for x in node for w in _flatten(x)]
    if isinstance(node, dict):
        return [w for k, v in node.items() if k != "_" for w in _flatten(v)]
    return []


#: буквы иврита и греческого — по ним слово получает своё правило поиска
_HEB_LETTERS = re.compile(r"[\u0590-\u05FF]")
_GRK_LETTERS = re.compile(r"[\u0370-\u03FF\u1F00-\u1FFF]")
#: приставки иврита пишутся слитно: «בכדורעף» — это «в волейболе», и без
#: них слово не находилось вовсе (разбор владельца 10.09)
_HEB_PREFIX = "בהולמשכ"

#: греческие ударения: в заголовках их ставят как придётся, а в
#: ЗАГЛАВНЫХ не ставят вовсе («ΠΟΔΟΣΦΑΙΡΟ» против «ποδόσφαιρο»).
#: Перед поиском снимаем их и в словаре, и в тексте
_GRK_ACCENTS = str.maketrans("άέήίόύώϊϋΐΰᾶῆῖῦώ", "αεηιουωιυιυαηιυω")


def greek_plain(text: str) -> str:
    """Тот же текст, но без греческих ударений."""
    return text.translate(_GRK_ACCENTS)


def _pattern(words) -> re.Pattern | None:
    """Слово целиком, а не куском другого: `direto` не должно ловиться в
    `diretor`, а `studio` — в чешском `studiem`.

    У иврита и греческого правила свои. В иврите приставка пишется слитно
    («בכדורגל» = «в футболе»), поэтому перед словом допускается одна из
    них. В греческом слово склоняется («Ποδοσφαίρου» от «ποδόσφαιρο»),
    поэтому после основы разрешён любой хвост.
    """
    words = sorted({greek_plain(w.lower()) for w in words if w},
                   key=len, reverse=True)
    if not words:
        return None
    иврит = [w for w in words if _HEB_LETTERS.search(w)]
    греческие = [w for w in words if _GRK_LETTERS.search(w)]
    прочие = [w for w in words if w not in иврит and w not in греческие]
    куски = []
    if прочие:
        тело = "|".join(re.escape(w) for w in прочие)
        куски.append(rf"(?<!\w)(?:{тело})(?!\w)")
    if иврит:
        тело = "|".join(re.escape(w) for w in иврит)
        куски.append(rf"(?<![\u0590-\u05FF])[{_HEB_PREFIX}]?"
                     rf"(?:{тело})(?![\u0590-\u05FF])")
    if греческие:
        тело = "|".join(re.escape(w) for w in греческие)
        куски.append(rf"(?<!\w)(?:{тело})\w*")
    return re.compile("|".join(куски), re.I | re.U)


@dataclass
class Markers:
    live: re.Pattern | None
    not_live: re.Pattern | None
    stop_title: re.Pattern | None
    stop_genre: re.Pattern | None = None

    def found(self, pattern, text: str) -> str:
        if not pattern or not text:
            return ""
        # словарь хранит греческие слова без ударений (`_pattern`) — текст
        # перед поиском приводим так же, иначе «ζωντανά» не находил само
        # себя, и 11.09 все греческие сайты разом дали ноль строк
        m = pattern.search(greek_plain(text))
        return m.group(0) if m else ""


def load(path: Path | None = None, override: dict | None = None) -> Markers:
    """Читает список слов. `override` — то, что задано у самого источника."""
    data = json.loads((path or MARKERS_FILE).read_text(encoding="utf-8"))
    if override:
        data = {**data, **override}
    return Markers(live=_pattern(_flatten(data.get("live"))),
                   not_live=_pattern(_flatten(data.get("not_live"))),
                   stop_title=_pattern(_flatten(data.get("stop_title"))),
                   stop_genre=_pattern(_flatten(data.get("stop_genre"))))


def split_teams(raw: str) -> tuple[str, str] | None:
    """`3 кръг, Мидълзбро - Уест Бромич Албиън, директно` → пара названий.
    Пары не видно — None, такая строка в ленту не идёт.

    Сначала делим по разделителю и только потом счищаем обвязку с краёв:
    если резать по запятой заранее, вместе с номером тура (`3 кръг,`)
    уезжает и первая команда.
    """
    if not raw:
        return None
    cleaned = _BRACKETS.sub(" ", raw).strip()
    parts = _SPLIT.split(cleaned)
    if len(parts) != 2:
        # частей не две — возможно, после пары через явный разделитель идёт
        # хвост стадии через тире; тогда делим по явному и хвост отрезаем
        strong = _STRONG_SPLIT.split(cleaned)
        if len(strong) != 2:
            return None
        parts = [strong[0], _DASH_TAIL.sub("", strong[1])]
    home = _LEFT_JUNK.sub("", parts[0]).strip(" .-–—:\"'")
    away = _RIGHT_JUNK.sub("", parts[1]).strip(" .-–—:\"'")
    if len(home) < 2 or len(away) < 2:
        return None
    # Сама с собой команда не играет: `FENERBAHÇE - Fenerbahçe` — это не матч,
    # а заголовок вида «канал — передача» (поймано на beinsports.com.tr 01.09)
    if " ".join(home.casefold().split()) == " ".join(away.casefold().split()):
        return None
    return home, away


@dataclass
class Verdict:
    ok: bool                 # берём в ленту?
    reason: str              # почему нет — понятной строкой
    live_marker: str = ""
    home: str = ""
    away: str = ""


def check(program, markers: Markers) -> Verdict:
    """Решение по одной передаче. Порядок проверок важен — см. шапку модуля."""
    title = program.title or ""
    stop = markers.found(markers.stop_title, title)
    if stop:
        return Verdict(False, f"стоп-слово в заголовке: {stop}")

    # Жанр передачи сайты пишут не только в заголовке: у ZDF «DOKUMENTATION»
    # стоит в поле рубрики, откуда он уезжает в лигу (кейс #448 от 04.09 —
    # док-фильм о баскетболе висел на витрине матчем). Проверяем рубрику
    # своим списком: слова лиг («conference») в нём держать нельзя.
    genre = " ".join(x for x in (program.league_raw, program.sport_raw) if x)
    stop = markers.found(markers.stop_genre, genre)
    if stop:
        return Verdict(False, f"стоп-жанр в рубрике: {stop}")

    signals = program.signals()
    bad = markers.found(markers.not_live, signals)
    if bad:
        return Verdict(False, f"запись или студия: {bad}")

    live = markers.found(markers.live, program.live_raw) \
        or markers.found(markers.live, signals)
    if not live:
        return Verdict(False, "нет маркера прямого эфира")

    pair = split_teams(program.match_raw or title)
    if not pair:
        return Verdict(False, "не видно пары команд", live_marker=live)

    return Verdict(True, "", live_marker=live, home=pair[0], away=pair[1])

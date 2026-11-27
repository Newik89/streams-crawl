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

Стоп-слово бывает частью имени: «Conference League» (турнир), «Studio
Zagreb» (клуб). Такие имена перечислены в `keep_names` и вырезаются из
текста перед любым поиском (`Markers.found`) — 11.10.2026 слово
«conference» молча снимало все матчи Лиги конференций.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKERS_FILE = ROOT / "data" / "markers.json"

# разделители пары команд: `Мидълзбро - Уест Бромич`, `PORTIMONENSE X LEIXÕES`,
# `Karlsruher SC vs VfL Wolfsburg`. Дефис без пробелов не берём — он бывает
# внутри названия (`Bodø/Glimt`, `Saint-Étienne`). Двоеточие разделителем не
# считаем: через него сайты пишут не пару, а рубрику — `Piłka nożna: Liga
# niemiecka` тогда сошло бы за матч. Одинокое `v` тоже не берём — чешское
# `Fotbal v Evropě` дало бы ту же ложную пару. Знак умножения «×» (книга 182,
# alkass.net: «Algeria × Dominican») — та же буква «x», набранная знаком: его
# знал только разборщик своего сайта, и подпись, которую он не разобрал,
# общий читатель парой не видел.
_SPLIT = re.compile(r"\s+(?:[-–—]|[xX×]|[vV][sS]|[vV]\.|contra)\s+")
# явные матчевые разделители — тире среди них нет: у sporttv.pt тире отделяет
# хвост стадии («BOCA JUNIORS X SÃO PAULO – QUARTOS DE FINAL 1ª MÃO»),
# и общий сплит давал три части вместо пары (кейсы #766 #908, 04.09)
_STRONG_SPLIT = re.compile(r"\s+(?:[xX×]|[vV][sS]|[vV]\.|contra)\s+")
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
    #: книга 146: слова передач до и после матча — стоп-слово, только когда
    #: стоят в НАЧАЛЕ части заголовка (`lead_show`)
    stop_lead: re.Pattern | None = None
    #: имена со стоп-словом внутри (`keep_names`): вырезаются перед поиском
    keep: re.Pattern | None = None
    #: книга 182: слова «студия» (`studio_show`) — стоп-слово, которое не
    #: окончательно: передача-студия может накрывать сам матч (`studio_cut`,
    #: `pipeline.studio_inside`). Языком сайта не делится: класс один
    studio: re.Pattern | None = None
    #: сами слова по разделам — для словаря языка сайта (`for_langs`)
    words: dict = field(default_factory=dict, repr=False, compare=False)
    _by_langs: dict = field(default_factory=dict, repr=False, compare=False)

    def for_langs(self, langs) -> "Markers":
        """Те же слова, но только языков сайта и общие (`app/site_lang.py`,
        слово владельца 25.10, книга 084): венгерское слово не ищется на
        хорватском сайте. `langs` None — сайт неизвестен, все слова."""
        if langs is None or not self.words:
            return self
        key = frozenset(langs)
        got = self._by_langs.get(key)
        if got is None:
            from . import site_lang

            def pick(section: str):
                return _pattern([w for w in self.words.get(section, [])
                                 if site_lang.allowed(w, key)])
            got = Markers(live=pick("live"), not_live=pick("not_live"),
                          stop_title=pick("stop_title"),
                          stop_genre=pick("stop_genre"),
                          stop_lead=pick("stop_lead"), keep=self.keep,
                          studio=self.studio)
            self._by_langs[key] = got
        return got

    def found(self, pattern, text: str) -> str:
        if not pattern or not text:
            return ""
        # словарь хранит греческие слова без ударений (`_pattern`) — текст
        # перед поиском приводим так же, иначе «ζωντανά» не находил само
        # себя, и 11.09 все греческие сайты разом дали ноль строк
        text = greek_plain(text)
        if self.keep is not None:
            # «Conference League», «Studio Zagreb» — имя, а не жанр: его
            # слова не стоп-слова (шапка модуля, 11.10.2026)
            text = self.keep.sub(" ", text)
        m = pattern.search(text)
        return m.group(0) if m else ""


def load(path: Path | None = None, override: dict | None = None) -> Markers:
    """Читает список слов. `override` — то, что задано у самого источника."""
    data = json.loads((path or MARKERS_FILE).read_text(encoding="utf-8"))
    if override:
        data = {**data, **override}
    words = {section: _flatten(data.get(section))
             for section in ("live", "not_live", "stop_title", "stop_genre", "stop_lead")}
    return Markers(live=_pattern(words["live"]),
                   not_live=_pattern(words["not_live"]),
                   stop_title=_pattern(words["stop_title"]),
                   stop_genre=_pattern(words["stop_genre"]),
                   stop_lead=_pattern(words["stop_lead"]),
                   keep=_pattern(_flatten(data.get("keep_names"))),
                   studio=_pattern(_flatten(data.get("studio_show"))),
                   words=words)


#: книга 146: границы частей заголовка — «Рубрика: …», «Передача. …», «(сезон) …», «… | …»
_PART_EDGE = re.compile(r"[:|]|[.)](?=\s)")


def lead_show(markers: Markers, text: str) -> str:
    """Книги 140 и 146: заголовок — передача до или после матча, а не матч.

    Слово передачи («Før», «Efter», «Post», «Optakt», «Vorbericht», «Avant-
    match», «Pre-Match»…, раздел `stop_lead` файла `data/markers.json`, на
    языке сайта) считается, только когда стоит В НАЧАЛЕ части заголовка —
    в самом начале или сразу после «:», «|», точки, закрывающей скобки — и
    за ним что-то есть: «A-Liga: Før F.C. København-FC Midtjylland», «Juego
    de Naciones (T26/27): Post España - Inglaterra», «Pre-Match: Arsenal v
    Chelsea». То же слово в середине фразы — обычный предлог или пометка, и
    матч остаётся матчем: «Danmark - Norge (direkte efter TV Avisen)»,
    «Fußball: Österreich - Serbien; Vorberichte, das Spiel, Analysen»,
    «Arsenal v Chelsea (Build-Up 4.30pm)» (независимая проверка 16.11).
    Имена из `keep_names` («Post Wien») вырезаются, как у прочих стоп-слов.
    Возвращает найденное слово или пустую строку."""
    pattern = markers.stop_lead
    if not pattern or not text:
        return ""
    text = greek_plain(text)
    if markers.keep is not None:
        text = markers.keep.sub(" ", text)
    at = 0
    for part in _PART_EDGE.split(text) + [""]:
        lead = part.lstrip(" -–—\"'«(")
        found = pattern.match(lead)
        # за словом что-то есть — в этой же части («Før FCK-FCM») или дальше
        # («Optakt: Danmark - Norge»)
        rest = text[at + (len(part) - len(lead)) + (found.end() if found else 0):]
        if found and rest.strip(" .,:;|)-–—"):
            return found.group(0)
        at += len(part) + 1
    return ""


#: «Dinamo B.», «Nottingham F.», «Borussia M.» — tvarenasport сокращает второе
#: слово имени до заглавной буквы с точкой (Bucureşti, Forest,
#: Mönchengladbach). Точку при чистке краёв оставляем: без неё «Dinamo B»
#: читается вторым составом (`names.category` → B), и игра раздваивается —
#: CFR Cluj — Dinamo 25.10 у Arena Premium 5 легла отдельно от Digi Sport 1
#: (#7400/#7192, 21.10). Буква W — пометка пола, её не трогаем
_INITIAL_END = re.compile(r"(?<=\w)\s+(?![Ww]\.)[^\W\d_]\.$")
#: книга 157: к обвязке края добавлены знаки, которых в имени на краю не
#: бывает: «PHOENIX !», «Lakers?», «, Ayr United», «* Arsenal»
_EDGE = " .-–—:\"'!?;,*•·…"
#: книга 157: сезон на краю стороны — «2026/27,Inverness Caledonian Thistle»
#: (bbc.co.uk: сезон прилип к имени без пробела). Год основания в имени
#: («1860 München», «Schalke 04») сезоном не считается: нужна вторая половина
_SEASON_LEAD = re.compile(r"^\s*(?:19|20)\d{2}\s?[/–-]\s?(?:(?:19|20)\d{2}|\d{2})(?!\d)[\s,.:;–—-]*")
_SEASON_TAIL = re.compile(r"[\s,.:;–—-]*(?<!\d)(?:19|20)\d{2}\s?[/–-]\s?(?:(?:19|20)\d{2}|\d{2})\s*$")


def _trim(side: str) -> str:
    """Счистить обвязку с края имени, сохранив точку сокращения («Dinamo B.»).
    Книга 157: с краёв снимаются и знаки (`_EDGE`), и сезон «ГГГГ/ГГ»."""
    bare = _SEASON_TAIL.sub("", _SEASON_LEAD.sub("", side))
    if any(ch.isalpha() for ch in bare):         # от стороны что-то осталось
        side = bare
    text = side.strip(_EDGE)
    kept = side.rstrip(" -–—:\"'!?;,*•·…")
    if _INITIAL_END.search(kept) and kept[-2].isupper():
        text += "."
    return text


def _unrepeated(parts: list[str]) -> list[str]:
    """Книга 157: подпись, где пара повторена («Los Angeles Lakers – Charlotte
    Hornets – Los Angeles Lakers – Charlotte Hornets», dagenstv.com), — одна
    пара: куски между разделителями идут одной и той же серией два раза и
    больше — остаётся одна серия."""
    keys = [" ".join(p.casefold().split()).strip(_EDGE) for p in parts]
    if keys:
        # рубрика перед первым куском («Basket : Los Angeles Lakers») и хвост
        # после последнего («Charlotte Hornets, direkt») повтору не мешают
        keys[0] = _LEFT_JUNK.sub("", keys[0])
        keys[-1] = _RIGHT_JUNK.sub("", keys[-1])
    for size in range(2, len(parts) // 2 + 1):
        if len(parts) % size == 0 and all(keys[i] == keys[i % size] for i in range(len(parts))) \
                and all(keys[:size]):
            return parts[:size]
    return parts


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
    parts = _unrepeated(_SPLIT.split(cleaned))  # пара повторена — одна пара (157)
    if several_matches(parts):                 # две пары в одной подписи (094)
        return None
    if len(parts) != 2:
        # частей не две — возможно, после пары через явный разделитель идёт
        # хвост стадии через тире; тогда делим по явному и хвост отрезаем
        strong = _STRONG_SPLIT.split(cleaned)
        if len(strong) != 2:
            return None
        parts = [strong[0], _DASH_TAIL.sub("", strong[1])]
    home = _trim(_LEFT_JUNK.sub("", parts[0]))
    away = _trim(_RIGHT_JUNK.sub("", parts[1]))
    if len(home) < 2 or len(away) < 2:
        return None
    # Сама с собой команда не играет: `FENERBAHÇE - Fenerbahçe` — это не матч,
    # а заголовок вида «канал — передача» (поймано на beinsports.com.tr 01.09)
    if " ".join(home.casefold().split()) == " ".join(away.casefold().split()):
        return None
    return home, away


# ── один читатель пары: догадки, которые проверяет эталон (правило (г)) ─────
#: дефис между буквами без пробелов (или с пробелом с одной стороны: «Aston
#: Villa- Viking», tvarenasport) — разделитель пары только как ДОГАДКА: он
#: бывает и внутри имени («Saint-Étienne», «Bodø/Glimt»), верную догадку
#: выбирает эталон
_TIGHT_DASH = re.compile(r"(?<=\w)\s?[-–—]\s?(?=\w)")
#: американская запись «гости at хозяева» / «гости @ хозяева»
_AT = re.compile(r"\s+(?:at|@)\s+", re.I)
#: союз между двумя парами: «Villarreal - Paris-SG et FK Bodø/Glimt - Lille»
#: — студия programme-tv с ДВУМЯ матчами (02.11, книга 094). Правило 3 резало
#: такую подпись на каждом тире и отдавало эталону догадку «Villarreal -
#: Paris-SG et FK Bodø/Glimt» — «Lille»; та сходилась по «Lille», и мусорное
#: имя уезжало в склейку и в словарь. Союз ищется только в СРЕДНИХ кусках
#: между разделителями: в крайних он часть имени
_CONJ = re.compile(r"\s(?:et|and|&|und|dhe|ve|og|och|oraz|και|и|та|és|și|si|e|i|y|a)\s", re.I)


def several_matches(parts: list[str]) -> bool:
    """Куски подписи между разделителями: в средних стоит союз — это две
    (и больше) пары в одной передаче, а не одна пара с хвостом. Такая
    подпись не пара и не догадка (книга 094)."""
    return len(parts) >= 3 and any(_CONJ.search(p) for p in parts[1:-1])


#: книга 124 (опись 89 разборщиков, 14.11): разделители и слова «против»,
#: которые знают отдельные разборщики, а общий читатель не знал. « v » и
#: «vs.» — английские сетки (4 и 3 разборщика), « / » и « | » — по 2–3,
#: «gegen» (нем.), «ndaj» (алб.), «mot» (швед./норв.), «kontra» (польск.,
#: хорв.), «против» / «проти» / «срещу» (рус., укр., болг.), «karşı» (тур.).
#: Это ДОГАДКИ: в ленту пара идёт, только если её подтвердил эталон
_MORE_SPLIT = re.compile(
    r"\s+(?:[vV]|[vV][sS]\.|gegen|ndaj|mot|kontra|против|проти|срещу|karşı|/|\|)\s+")
#: фразы-шаблоны «A встречается с B» в описании передачи (книга 121, ipko.tv:
#: «…në të cilën Spanja përballon Angli.»). Новый язык — новая строка здесь
_FACES_PHRASES = (
    re.compile(r"\bnë\s+të\s+cilën\s+(?P<home>.+?)\s+përballon\s+(?P<away>[^.!?]+)", re.I),
)
#: первая строка описания длиннее — это уже рассказ, а не подпись матча
LEAD_MAX = 90


def phrase_pairs(text: str) -> list[tuple[str, str]]:
    """Правило 7 (книга 124): пары из фраз-шаблонов «A встречается с B» —
    где угодно в тексте (описание передачи). Только догадки для эталона."""
    out: list[tuple[str, str]] = []
    for pattern in _FACES_PHRASES:
        for m in pattern.finditer(text or ""):
            pair = _sides(m["home"], m["away"])
            if pair and pair not in out:
                out.append(pair)
    return out


def lead(text: str) -> str:
    """Первая строка описания — до конца предложения или строки; длиннее
    `LEAD_MAX` — пусто: многие сайты держат пару подзаголовком («Prishtina -
    Drita»), а длинный текст — уже рассказ о передаче."""
    first = re.split(r"(?<=[.!?])\s+|\n", (text or "").strip(), maxsplit=1)[0].strip()
    first = first.rstrip(".!? ")
    return first if 0 < len(first) <= LEAD_MAX else ""


def _sides(left: str, right: str) -> tuple[str, str] | None:
    """Пара из двух кусков подписи — обвязка счищается как в `split_teams`."""
    home = _trim(_LEFT_JUNK.sub("", left))
    away = _trim(_RIGHT_JUNK.sub("", right))
    if len(home) < 2 or len(away) < 2:
        return None
    if " ".join(home.casefold().split()) == " ".join(away.casefold().split()):
        return None
    return home, away


# ── книга 153: рубрики через точку ──────────────────────────────────────────
#: точка, за которой пробел или конец текста, — возможная граница рубрики
_RUBRIC_DOT = re.compile(r"\.(?:\s+|$)")
#: знаки, сразу после которых начинается сторона пары или игрок дуэта
_SIDE_OPENERS = "-–—/:|,"
#: кавычки вокруг названий команд («Салават Юлаев» — «Барыс», sports.kz):
#: частью имени они не бывают
_QUOTES = re.compile(r"[«»„“”]")
#: тире пары сразу за точкой («Соболенко А. - Рыбакина Е.»)
_DASH_NEXT = re.compile(r"\s*[-–—]\s")
#: правило 7 `split_candidates`: столько частей-рубрик (вид спорта, турнир)
#: должно стоять перед частью с парой. Одна точка перед парой бывает и в
#: самом имени («St. Pauli - Bochum», «At. Madrid - Bayern»), поэтому одной мало
RUBRICS_BEFORE_PAIR = 2


def rubric_parts(text: str) -> list[str]:
    """Книга 153: заголовок «рубрики через точку» → его части по порядку.

    «Теннис. WTA. Итоговый турнир. Индиан-Уэллс. А. Соболенко - Э. Свитолина.
    Прямая трансляция» → «Теннис», «WTA», «Итоговый турнир», «Индиан-Уэллс»,
    «А. Соболенко - Э. Свитолина», «Прямая трансляция». Так пишут news.by,
    ntvplus.tv, sports.kz, vsetv.com, poverkhnost.tv, tv3.lt. Раньше каждый
    из этих разборщиков резал заголовок по КАЖДОЙ точке, и пара игроков с
    инициалами разваливалась: «Соболенко - Э» (находка 16.11).

    Граница части — точка, за которой пробел или конец текста. Точка НЕ
    граница, когда:
      Р1. перед ней инициал в НАЧАЛЕ стороны — одна буква или заглавная со
          строчной: «А. Соболенко», «Р. Абильтаров - А. Г. де Кастро»,
          «М. Гранольерс/О. Себальос», «С. Ган - Дж. Хокит», «St. Pauli»;
      Р2. перед ней число из одной-двух цифр в НАЧАЛЕ стороны — номер в
          названии: «1. FC Köln - 2. …», «2. Bundesliga»;
      Р3. перед ней сокращение из букв через точку с коротким последним
          куском (одна-две буквы): «А.О.», «Γ.Σ.Σ.», «g.ta». «О.Караваева.»
          — инициал с фамилией, там граница есть; многоточие — тоже граница;
      Р4. сразу за ней стоит тире пары: «Соболенко А. - Рыбакина Е.» —
          рубрика с тире не начинается.
    «Начало стороны» — начало текста или части, место сразу после тире
    пары, косой черты, двоеточия, запятой или после другого инициала.
    Номер считается только целым словом: в «ACB league 2023/24. Baskonia»
    «24» — хвост сезона, там граница есть.
    Одна буква ПОСЛЕ слова («Серия А. Милан - Интер», «Рыбакина Е. Прямая
    трансляция») — граница. В части с парой точка остаётся при букве
    («Соболенко А. - Рыбакина Е.»): «Dinamo B» без точки читался бы вторым
    составом (см. `_INITIAL_END`).
    Пустые части выброшены, пробелы по краям сняты."""
    text = text or ""
    parts: list[str] = []
    start = 0             # где началась текущая часть
    initial_end = -1      # где кончился последний инициал (для Р1)
    for dot in _RUBRIC_DOT.finditer(text):
        before = text[start:dot.start()]
        word = re.split(r"\s", before)[-1]                # слово перед точкой
        token = word.rsplit("/", 1)[-1]                   # в дуэте — после «/»
        letter = len(token) == 1 and token.isalpha()
        # «Дж», «St»: заглавная со строчной — тоже инициал
        short = letter or (len(token) == 2 and token.isalpha()
                           and token[0].isupper() and token[1].islower())
        number = word.isdigit() and len(word) <= 2
        if not short:
            token = word
        head = before[:len(before) - len(token)].rstrip()  # что стоит до слова
        side_start = (not head or head[-1] in _SIDE_OPENERS
                      or start + len(head) == initial_end)
        if (short or number) and side_start:                         # Р1, Р2
            initial_end = dot.start() + 1
            continue
        pieces = word.split(".")
        if len(pieces) > 1 and 1 <= len(pieces[-1]) <= 2:            # Р3
            continue
        if _DASH_NEXT.match(text, dot.start() + 1):                  # Р4
            continue
        part = before.strip()
        if letter and _SPLIT.search(part):   # буква в конце имени: точка при ней
            part += "."
        if part:
            parts.append(part)
        start = dot.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def split_candidates(raw: str) -> list[tuple[str, str]]:
    """Один читатель пары (правило (г) починки самопроверки №13, владелец
    20.10): все ДОГАДКИ о паре в подписи, по порядку надёжности. Сами по себе
    в ленту они не идут — верную выбирает эталон (`reference.Reference.confirm`,
    «кандидат только по эталону»); без эталона строка решается по-старому,
    `split_teams`. Правила:

      1. обычное чтение `split_teams` (« - », « x », « vs », «contra») — первым;
      2. рубрика перед парой отрезается по последнему «: » («2. Bundesliga
         Live - Topspiel: 1. FC Nürnberg - 1. FC Kaiserslautern», rtl.de);
      3. три и больше кусков через тире («Virtus - Bologna - Baskonia»,
         tvarenasport): пара — на каждом разрезе;
      4. « at » и « @ » («Minnesota Timberwolves at Miami Heat», tvpassport):
         хозяева — после «at» (обратный порядок эталон проверяет и сам);
      5. дефис без пробелов («Al Nassr-Al Neom», «Levante-Ath Bilbao»,
         ipko.tv) или с пробелом лишь с одной стороны («Aston Villa- Viking»):
         пара — на каждом таком дефисе; тире среди пробелов при этом нет,
         иначе дефис — часть имени («Saint-Étienne - Lyon»);
      6. (книга 124, выжимка из 89 разборщиков) разделители и слова
         «против», которые знали только отдельные разборщики (`_MORE_SPLIT`:
         « v », «vs.», « / », « | », «gegen», «ndaj», «mot», «kontra»,
         «против», «срещу», «karşı»): ровно один такой разделитель — пара;
      7. (книга 153) рубрики через точку, пара — в одной из частей: «Футбол.
         Чемпионат Беларуси. 27-й тур. Динамо-Минск - Неман. Прямая
         трансляция» (news.by, ntvplus.tv, sports.kz, vsetv.com). Подпись
         делится на части (`rubric_parts`: инициал «А. Соболенко» и номер
         «1. FC» частью не считаются); пара — часть с разделителем пары,
         перед которой стоит не меньше `RUBRICS_BEFORE_PAIR` частей-рубрик.
         Части после пары («Прямая трансляция», «В перерыве Спорт-центр»)
         отпадают сами, кавычки-ёлочки вокруг названий снимаются
         («Салават Юлаев» — «Барыс»). Такая догадка идёт ПЕРВОЙ: она точнее
         чтения всей подписи, где к хозяевам прилипают рубрики, а к гостям —
         хвост.

    Повторы убраны, порядок сохранён. Скобки с хвостом («(BRA)», «(se
    speciálním studiem)») вырезаны у всех догадок, как в `split_teams`."""
    if not raw:
        return []
    cleaned = _BRACKETS.sub(" ", raw).strip()
    texts = [cleaned]
    if ": " in cleaned:                                          # правило 2
        texts.append(cleaned.rsplit(": ", 1)[1].strip())
    out: list[tuple[str, str]] = []

    def add(pair) -> None:
        if pair and pair not in out:
            out.append(pair)

    for part in rubric_parts(cleaned)[RUBRICS_BEFORE_PAIR:]:     # правило 7
        if _SPLIT.search(part):
            add(split_teams(_QUOTES.sub("", part)))

    for text in texts:
        add(split_teams(text))                                   # правило 1
        parts = _unrepeated(_SPLIT.split(text))                  # книга 157
        if several_matches(parts):                               # книга 094
            continue
        if len(parts) >= 3:                                      # правило 3
            for i in range(1, len(parts)):
                add(_sides(" - ".join(parts[:i]), " - ".join(parts[i:])))
        at = _AT.split(text)
        if len(at) == 2:                                         # правило 4
            # рубрика перед гостями («NBA Basketball: Minnesota…») — долой
            add(_sides(at[1], _LEFT_JUNK.sub("", at[0])))
        if not _SPLIT.search(text):                              # правило 5
            for m in _TIGHT_DASH.finditer(text):
                add(_sides(text[:m.start()], text[m.end():]))
        more = _MORE_SPLIT.split(text)
        if len(more) == 2:                                       # правило 6
            # рубрика перед парой через тире — долой: «SPFL 2026/27 Season,
            # League 1 - Hamilton v Ross County» (bbc.co.uk, сбор 14.11) —
            # чистая догадка «Hamilton» — «Ross County» идёт первой
            add(_sides(_SPLIT.split(more[0])[-1], more[1]))
            add(_sides(more[0], more[1]))
    return out


#: книга 133: где у пары срезаны лишние слова (эти слова — классы книги знаний)
TRIM_HOME = "начало хозяев"
TRIM_AWAY = "конец гостей"
TRIM_BOTH = "оба края"
#: книга 136: классы книги знаний (`dictionary_errors.class`) — лишние слова,
#: которые срезались у пар и подтвердились эталоном
KNOWN_HOME = "лишнее перед хозяевами"
KNOWN_AWAY = "лишнее после гостей"
#: книга 133: сколько слов самое большее срезается с одного края пары
TRIM_WORDS = 6
#: книга 133: что счищается с края стороны после среза («ženy: Slovensko»,
#: «Italia -», «Österreich,»)
_TRIM_EDGE = " \t,.:;-–—|/«»\"'„“”"


#: книга 133, правило 5: теннисный дуэт — косая черта между буквами
_DUO = re.compile(r"[^\W\d_]\.?\s*/\s*[^\W\d_]")
#: книга 157, правило 6: конец предложения внутри стороны — точка после слова
#: от трёх букв, дальше пробел
_SENTENCE_END = re.compile(r"(?<=[^\W\d_]{3})\.\s+(?=\S)")


def _still_name(side: str) -> bool:
    """После среза от стороны остаётся имя: не меньше двух букв."""
    return sum(ch.isalpha() for ch in side) >= 2


def outer_trims(home: str, away: str) -> list[tuple[str, str, str, str]]:
    """Книга 133 (общее правило для ВСЕХ сайтов и языков): догадки «к паре
    СНАРУЖИ прилипли лишние слова без разделителя».

    Случаи сбора 15.11: «Raiffeisen Liga e Pare Prishtina e Re - Liria»
    (ipko.tv: турнир перед хозяевами), «ligová fáze Finsko - San Marino»
    (webtv.sk: стадия турнира), «Israel - Österreich Das Spiel» (tv.orf.at:
    слова передачи после гостей), «Belgio - Italia - 15/11/2026» (raiplay.it:
    дата). Раньше такое срезал только разборщик своего сайта своим списком
    слов — у остальных сайтов строка шла на витрину с мусором в имени или
    терялась. Здесь списков слов нет: срезается что угодно, а верный срез
    выбирает эталон (`pipeline.trim_by_reference`). Правила:
      1. слова срезаются только с НАЧАЛА хозяев и с КОНЦА гостей — там, где
         к паре прилипает чужой текст. Конец хозяев и начало гостей не
         трогаем: там живут части самих имён («Sheffield Wednesday»,
         «ASVEL Villeurbanne») — это дело словаря имён, не этого правила;
      2. порядок — от меньшего среза к большему: одно слово с начала
         хозяев, два, …; затем слова с конца гостей; затем оба края сразу;
      3. с одного края — не больше `TRIM_WORDS` слов, и от стороны должно
         остаться имя (хотя бы одно слово, не меньше двух букв);
      4. с края урезанной стороны счищаются знаки (`_TRIM_EDGE`);
      5. теннисные дуэты («Granollers/Zeballos» — косая черта между
         буквами) не режем: игрок в один день стоит и в одиночке, и в паре.
         Косая черта в дате («15/11/2026») — не дуэт;
      6. (книга 157) ещё срезы — по концу предложения внутри стороны
         (`_SENTENCE_END`), без ограничения числа слов.
    Возвращает [(где, что срезано, хозяева, гости)]; сами по себе догадки в
    ленту не идут."""
    if _DUO.search(home) or _DUO.search(away):                   # правило 5
        return []
    hw, aw = home.split(), away.split()
    out: list[tuple[str, str, str, str]] = []

    def add(where: str, cut: str, new_home: str, new_away: str) -> None:
        new_home, new_away = new_home.strip(_TRIM_EDGE), new_away.strip(_TRIM_EDGE)
        if _still_name(new_home) and _still_name(new_away):      # правила 3–4
            out.append((where, cut, new_home, new_away))

    front = range(1, min(len(hw), TRIM_WORDS + 1))               # правило 3
    back = range(1, min(len(aw), TRIM_WORDS + 1))
    for k in front:                                              # правило 2
        add(TRIM_HOME, " ".join(hw[:k]), " ".join(hw[k:]), away)
    for m in back:
        add(TRIM_AWAY, " ".join(aw[-m:]), home, " ".join(aw[:-m]))
    for k in front:
        for m in back:
            add(TRIM_BOTH, f"{' '.join(hw[:k])} … {' '.join(aw[-m:])}",
                " ".join(hw[k:]), " ".join(aw[:-m]))
    # 6 (книга 157): срез по концу предложения — сколько бы слов за точкой ни
    # стояло: «France. Qualifications à l'EuroBasket féminin. 3e journée.
    # Groupe M.» (programme-tv.net: восемь слов после гостей, больше
    # `TRIM_WORDS`). Точка после слова от трёх букв и пробел; точка
    # сокращения («St. Pauli», «Eintr. Frankfurt») — такая же догадка, и
    # верную, как и прежде, выбирает эталон
    seen = {(where, new_home, new_away) for where, _cut, new_home, new_away in out}
    out.extend(trim for trim in sentence_trims(home, away)
               if (trim[0], trim[2], trim[3]) not in seen)
    return out


def sentence_trims(home: str, away: str) -> list[tuple[str, str, str, str]]:
    """Правило 6 `outer_trims` (книга 157): срезы по концу предложения — всё
    после точки у гостей, всё до точки у хозяев. Тот же вид, что у
    `outer_trims`: [(где, что срезано, хозяева, гости)]."""
    out: list[tuple[str, str, str, str]] = []
    for dot in _SENTENCE_END.finditer(away):
        new_home, new_away = home.strip(_TRIM_EDGE), away[:dot.start()].strip(_TRIM_EDGE)
        if _still_name(new_home) and _still_name(new_away):
            out.append((TRIM_AWAY, away[dot.end():], new_home, new_away))
    for dot in _SENTENCE_END.finditer(home):
        new_home, new_away = home[dot.end():].strip(_TRIM_EDGE), away.strip(_TRIM_EDGE)
        if _still_name(new_home) and _still_name(new_away):
            out.append((TRIM_HOME, home[:dot.start()], new_home, new_away))
    return out


#: код выпуска сериала «S5E0», «S02 E14» (сезон и серия) — так ipko.tv
#: подписывает передачи: «S5E0 - Skoci-Maqedoni» вставало вопросом владельцу
#: «Вид спорта» (книга 108). Матчи так не подписывают
_EPISODE_CODE = re.compile(r"(?<![^\W_])S\d{1,2}\s?E\d{1,3}(?![^\W_])", re.I)


def episode_code(text: str) -> str:
    """Код выпуска сериала в тексте («S5E0») или пусто."""
    m = _EPISODE_CODE.search(text or "")
    return m.group(0) if m else ""


#: книга 182: границы рубрик в подписи — « / », « | », «: »
_RUBRIC_EDGE = re.compile(r"\s+[/|]\s+|:\s+")
#: книга 182: номер студии сразу за её словом — «Studio 2», «Studio №1»
_STUDIO_NO = re.compile(r"\s*(?:№|#)?\s*\d{1,2}(?!\w)")


def studio_cut(markers: Markers, text: str) -> str:
    """Книга 182: подпись без названия передачи-студии — что осталось, то и
    читается как пара («Mondial Studio 2 / Algeria × Dominican», alkass.net:
    сайт подписал студией трёхчасовой показ, внутри которого идёт матч).
    Правила:
      Ч1. слова студии (`Markers.studio`, раздел `studio_show` файла
          `data/markers.json`) в подписи нет — пусто: строка не про это.
          Имена со словом студии внутри (`keep_names`: «Studio Zagreb»)
          студией не считаются;
      Ч2. подпись делится на части по границам рубрик: « / », « | », «: »;
      Ч3. часть со словом студии БЕЗ разделителя пары — название передачи,
          выбрасывается целиком («Mondial Studio 2», «Al-Mundial Studio 1»);
      Ч4. в части с разделителем пары слово студии стоит ПЕРЕД парой —
          срезается всё до него включительно и номер за ним («Studio 2
          Španělsko - Česko» → «Španělsko - Česko»); стоит ПОСЛЕ пары —
          срезается от него до конца («Arsenal - Chelsea Studio»);
      Ч5. оставшиеся части склеиваются через «: » — рубрику перед парой
          дальше отрезает обычное чтение (`split_candidates`, правило 2).
    Решает ли остаток судьбу строки — не здесь: его читает и проверяет
    `pipeline.studio_pair` (другие стоп-слова, эталон)."""
    if not text or not markers.found(markers.studio, text):          # Ч1
        return ""
    parts, start = [], 0
    for edge in _RUBRIC_EDGE.finditer(text):                         # Ч2
        parts.append(text[start:edge.start()])
        start = edge.end()
    parts.append(text[start:])
    kept = []
    for part in parts:
        plain = greek_plain(part)
        if markers.keep is not None:
            # имя из `keep_names` закрываем пробелами той же длины: место
            # слова в части не должно съехать
            plain = markers.keep.sub(lambda m: " " * len(m.group(0)), plain)
        word = markers.studio.search(plain)
        if word is None:
            kept.append(part.strip())
            continue
        if _SPLIT.search(part) is None:                              # Ч3
            continue
        # Ч4: «перед парой» — после слова студии ещё есть разделитель пары
        # («Fotbal - studio Jablonec - Lugano»: первый разделитель — рубрика)
        if any(m.start() >= word.end() for m in _SPLIT.finditer(part)):
            rest = part[word.end():]
            number = _STUDIO_NO.match(rest)
            kept.append((rest[number.end():] if number else rest).strip())
        else:
            kept.append(part[:word.start()].strip())
    return ": ".join(p for p in kept if p).strip(_TRIM_EDGE)         # Ч5


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
    stop = (markers.found(markers.stop_title, title)
            or episode_code(title) or episode_code(program.match_raw or ""))
    if stop:
        return Verdict(False, f"стоп-слово в заголовке: {stop}")
    # книги 140 и 146: передача до или после матча — слово в начале части
    # заголовка или в начале поля пары
    stop = lead_show(markers, title) or lead_show(markers, program.match_raw or "")
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
    # Стоп-слово или слово записи бывает и в самой строке пары: у ČT sport
    # заголовок — турнир («Liga národů UEFA mužů»), а подзаголовок —
    # «Studio Španělsko - Česko», и студия до и после матча шла на витрину
    # двумя лишними играми Испания — Чехия (регресс 02.10). Слово ищется
    # целиком (`_pattern`), «Estudiantes» не пострадает
    pair_text = program.match_raw or ""
    bad = markers.found(markers.stop_title, pair_text) \
        or markers.found(markers.not_live, pair_text)
    if bad:
        return Verdict(False, f"стоп-слово или запись в паре: {bad}")

    live = markers.found(markers.live, program.live_raw) \
        or markers.found(markers.live, signals)
    if not live:
        return Verdict(False, "нет маркера прямого эфира")

    # поле пары « » (пробел) — так парсер говорит «пары нет, в заголовок не
    # лезь» (polsatsport, teleman, novasports…): заголовок тут НЕ читаем.
    # Такую строку дальше спрашивает эталон (`pipeline.ask_reference`,
    # правило (в)) — он читает и заголовок, но каждую догадку подтверждает
    pair = split_teams(program.match_raw or title)
    if not pair:
        return Verdict(False, "не видно пары команд", live_marker=live)

    return Verdict(True, "", live_marker=live, home=pair[0], away=pair[1])

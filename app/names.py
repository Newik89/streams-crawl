# -*- coding: utf-8 -*-
"""Названия команд: приведение к сравнимому виду и похожесть (ТЗ разд. 8).

Задача одна: понять, что `FC St. Pauli` с польского сайта и `Санкт Паули` с
болгарского — одна команда, а `Манчестер Юнайтед` и `Манчестер Сити` — разные.

Четыре приёма, каждый закрывает свою беду:

1. **Два чтения кириллицы.** Таблица в `app/translit.py` украинская: «г»→h,
   «и»→y. На болгарском те же буквы читаются иначе, и `Фрайбург` становится
   `FRAIBURH` вместо `FREIBURG`. Язык источника не угадываем — даём имени оба
   чтения и берём то, которое совпало лучше.
2. **Словарь `data/aliases.json`.** Транслитерация даёт звучание, а не имя:
   `Манчестър Юнайтед` → `Manchestar Yunaited`. Плюс языки называют города
   по-своему: `Brema` = `Bremen`, `Mediolan` = `Milão` = `Milan`. Это словарь,
   а не код: он пополняется владельцем через очередь модерации.
3. **Сравнение ПОСЛОВНО, не сплошной строкой.** У клубов одного города общая
   часть имени перевешивает различие: как строки `Manchester United` и
   `Manchester City` похожи на 81, `Sparta Praga` и `Slavia Praga` — на 75,
   то есть выше любого разумного порога. Пословно `United` не находит себе
   пары — и оценка падает до 40.
4. **Категория — стена.** Женская команда, возраст и второй состав никогда не
   склеиваются со взрослой основой, какой бы похожей ни была запись:
   `Levski W` и `Levski` совпадают на 100, `SL Benfica B` и `SL Benfica` тоже.

Проверять порог только на «своих» парах нельзя — так и была пропущена
склейка Манчестеров. Рядом всегда держим список заведомо разных команд:
`scripts/merge_report.py --scale`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz

from .translit import hebrew_name_readings, to_english

ROOT = Path(__file__).resolve().parent.parent
ALIASES_FILE = ROOT / "data" / "aliases.json"

# Порог похожести: 85 и выше — одна команда. Подобран на живом обходе 30.08
# (`results/matches.md`): свои пары дают 85–100, заведомо разные — не выше 54.
SIMILAR_ENOUGH = 85

# Формы клуба и предлоги: у каждого сайта свои, к делу не относятся.
# `Real`, `Sporting`, `Athletic` НЕ трогаем — они различают клубы
# (`Real Madrid` и `Real Sociedad`).
_NOISE_WORDS = {
    "FC", "SC", "AFC", "CF", "AC", "SS", "SSC", "US", "AS", "SL", "GD", "CD",
    "BC", "CA", "SV", "CFC", "VFL", "VFB", "SK", "FK", "OGC", "OL", "OM",
    "TSV", "RC", "AJ", "CP", "MFK", "TSG", "BSC", "CLUB", "CALCIO", "KALCIO",
    "STADE", "OLYMPIQUE",
    "DE", "DEL", "DI", "DA", "LE", "LA", "EL", "LOS", "VAN", "OF", "THE",
    "AND", "I",
}

# Болгарское чтение кириллицы — второй вариант к украинскому из `translit.py`.
_BULGARIAN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "a",
    "ь": "", "ю": "yu", "я": "ya", "ы": "y", "э": "e", "ё": "e",
}

#: Третье чтение кириллицы — русское. Отличается от болгарского ровно там,
#: где расходятся сами языки: "й" русские передают через "y" ("Райо" -> "Rayo",
#: а не "Raio"), "х" через "kh". Понадобилось, когда ленту стал наполнять
#: `ntvplus.tv`: его "Райо Вальекано" не склеивался с чешским
#: "Rayo Vallecano" — 75 при пороге 85.
_RUSSIAN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "",
    "ь": "", "ю": "yu", "я": "ya", "ы": "y", "э": "e", "ё": "e",
}

_FOUNDED_RE = re.compile(r"\b(1[89]\d{2}|0[0-9]|9[0-9])\b")   # `Como 1907`
_NUM_PREFIX_RE = re.compile(r"^\s*\d+\.\s*")                  # `1. FC Magdeburg`
_NON_WORD_RE = re.compile(r"[^A-Z0-9 ]+")
_AGE_RE = re.compile(r"\bU\s?-?(\d{2})\b|\bunder[\s-]{0,3}(\d{2})\b", re.I)
# «женщин(ы)», «žen(y)» и одиночные буквы пола — сербская «ž», кириллическая
# «ж» («Австралия (Ж)»), греческая «γ» («Τουρκία Γ») — женские пометки
# источников, чьи команды шли мужскими (женский ЧМ по баскету, 06.09).
# «женск»/«жен» префиксом брать нельзя — срезал бы Женеву (Серветт Женева)
_WOMEN_RE = re.compile(r"(?<!\w)W(?!\w)|\bwomen\b|\bfem[ei]nin"
                       r"|\bженщин\w*\b|\bženy\b|\bžen\b|\bmoter\w*\b"
                       # иврит: «נשים», у sport5 с артиклем — «הנשים» (14.09)
                       r"|(?<!\w)[žжγ](?!\w)|\bה?נשים\b", re.I)
# Второй состав: `SL Benfica B`, `Werder Bremen II`. От основы отличается одной
# буквой — фаззи не различит, поэтому выносим в категорию.
_RESERVE_RE = re.compile(r"(?<=\w)\s+(B|II|2)\s*$", re.I)
# Поляки ставят номер состава в СЕРЕДИНУ имени: `Korona II Kielce`,
# `Legia II Warszawa`. Без этого дубль склеивался с основой (01.09).
_RESERVE_MID_RE = re.compile(r"(?<=\w)\s+(II|III)\s+(?=\w)")
_CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")
#: письменность иврита — по ней включаем многовариантное чтение
_HEBREW_RE = re.compile(r"[֐-׿]")
#: гласные — их выбрасывает `_skeleton` при сверке ивритских чтений
_VOWELS_RE = re.compile(r"[AEIOUY]")


# Подтверждённые владельцем имена: сырое написание → каноническое. Живут в
# базе (`team_aliases`), сюда их кладёт разбор через `set_overrides()`. Держим
# отдельно от словаря слов: те правит ассистент, эти — владелец, и они
# сильнее — если имя подтверждено, гадать по буквам уже не нужно.
_OVERRIDES: dict[str, str] = {}


def set_overrides(mapping: dict[str, str] | None) -> None:
    """Задать подтверждённые имена (`app.dictionary.team_overrides`)."""
    global _OVERRIDES
    _OVERRIDES = dict(mapping or {})
    readings.cache_clear()


@lru_cache(maxsize=1)
def aliases() -> dict[str, str]:
    """Словарь из `data/aliases.json`. В файле он разложен по кучкам («города»,
    «сокращения») — для чтения человеком; коду нужен один плоский список."""
    if not ALIASES_FILE.exists():
        return {}
    raw = json.loads(ALIASES_FILE.read_text(encoding="utf-8"))
    flat: dict[str, str] = {}
    for key, block in raw.items():
        if key.startswith("_") or not isinstance(block, dict):
            continue
        for k, v in block.items():
            if isinstance(v, str):
                flat[k.upper()] = v.upper()
    return flat


@lru_cache(maxsize=1)
def _strip_rules() -> tuple:
    """Мусор в имени (6е, A3): спонсоры (`Asteras AKTOR`), хвосты стадий
    (`csoportkör mérkőzés`, `Etapa 2`), метки `(Z)`/`(L)`. Лежат в
    `data/aliases.json`, раздел `strip` — список регулярок по уже
    ОЧИЩЕННОМУ имени: ASCII, капс, без знаков (`METRO HOLDING`, не
    `METRO HOLDİNG`)."""
    if not ALIASES_FILE.exists():
        return ()
    raw = json.loads(ALIASES_FILE.read_text(encoding="utf-8"))
    out = []
    for key, block in raw.items():
        if key.startswith("strip") and isinstance(block, list):
            out.extend(re.compile(pat) for pat in block)
    return tuple(out)


@lru_cache(maxsize=1)
def _whole_exonyms() -> dict[str, str]:
    """Экзонимы, меняющие имя только ЦЕЛИКОМ: `Magyarország` = Hungary,
    `SAD` = USA, `PSG` = Paris Saint Germain. Словом внутри имени такое
    трогать нельзя — `Novi Sad` стал бы `Novi USA`. Читаются все разделы
    `_… целиком` в `data/aliases.json` (подчёркивание прячет раздел от
    пословного словаря): сборные — 6е A3, клубы-сокращения — 6е,
    номера #90/#401/#404 владельца 04.09."""
    if not ALIASES_FILE.exists():
        return {}
    raw = json.loads(ALIASES_FILE.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for key, block in raw.items():
        if key.startswith("_") and "целиком" in key and isinstance(block, dict):
            out.update({k.upper(): v.upper() for k, v in block.items()})
    return out


def reload() -> None:
    """Перечитать `data/aliases.json`. Нужно после правки файла в живом
    процессе — админка и обход держат словарь в памяти."""
    aliases.cache_clear()
    _strip_rules.cache_clear()
    _whole_exonyms.cache_clear()
    readings.cache_clear()


#: Не имя команды, а заглушка «соперник ещё не известен». Телесетки ставят
#: такое за дни до жеребьёвки: `Francia - TBC` у movistarplus, `Winner QF1`
#: у английских каналов. Закреплять и переводить это нельзя — 10.09 канон
#: предложил владельцу закрепить «TBC W» = «Spain W», взяв единственный
#: испанский матч эталона в том же часе
_PLACEHOLDER_RE = re.compile(
    r"^(?:tbc|tbd|tba|n/?a|\?+|-+|"
    r"por determinar|a determinar|por confirmar|da definire|"
    r"(?:winner|loser|ganador|perdedor|vencedor|vincitore|perdente|"
    r"gagnant|perdant|sieger|verlierer|pobjednik|pobjeda|"
    r"победитель|проигравший)\b.*)$", re.I)


def is_country(name: str) -> bool:
    """Имя — это сборная страны, а не клуб.

    Нужно там, где вид спорта берут по одной знакомой стороне пары: клуб
    играет в одном виде, а сборная страны — во всех сразу («Japonsko - USA»
    может быть и волейболом, и баскетболом). Смотрим словарь сборных из
    `data/aliases.json` — и его ключи (местные написания), и значения
    (английские имена).
    """
    голое = "".join(c for c in unicodedata.normalize("NFKD", name or "")
                    if not unicodedata.combining(c))
    ключ = _tidy(голое, exonyms=False)
    экзонимы = _whole_exonyms()
    return bool(ключ) and (ключ in экзонимы
                           or ключ in {v.upper() for v in экзонимы.values()})


def is_placeholder(name: str) -> bool:
    """Строка вместо имени: соперник ещё не определён. Такую сторону не
    переводим, не закрепляем в словаре и не спрашиваем у владельца."""
    bare = _AGE_RE.sub(" ", _WOMEN_RE.sub(" ", (name or "")))
    return bool(_PLACEHOLDER_RE.match(" ".join(bare.split())))


def category(name: str) -> str:
    """Пол, возраст и состав: `W`, `U19`, `B`. Правило проекта — терять их
    нельзя, а склеивать через них тем более."""
    parts = []
    m = _AGE_RE.search(name)
    if m:
        parts.append(f"U{m.group(1) or m.group(2)}")
    if _WOMEN_RE.search(name):
        parts.append("W")
    if _RESERVE_RE.search(name.strip()) or _RESERVE_MID_RE.search(name.strip()):
        parts.append("B")
    return " ".join(parts)


def _bulgarian(name: str) -> str:
    return _by_table(name, _BULGARIAN)


def _russian(name: str) -> str:
    return _by_table(name, _RUSSIAN)


def _by_table(name: str, table: dict) -> str:
    return "".join(
        table.get(c, table.get(c.lower(), c).upper() if c.isupper() else c)
        for c in name)


def _tidy(text: str, exonyms: bool = True) -> str:
    text = _NUM_PREFIX_RE.sub("", text)
    text = _RESERVE_RE.sub("", text.strip())
    text = _RESERVE_MID_RE.sub(" ", text)
    text = _WOMEN_RE.sub(" ", text)
    text = _AGE_RE.sub(" ", text)
    text = _NON_WORD_RE.sub(" ", text.upper())
    for rule in _strip_rules():                     # спонсоры и хвосты (A3)
        text = rule.sub(" ", text)
    text = _FOUNDED_RE.sub(" ", text)
    table = aliases()
    words = [table.get(w, w) for w in text.split() if w and w not in _NOISE_WORDS]
    # алиас мог развернуться в слово-форму — второй проход по тому же списку
    clean = " ".join(w for w in words if w not in _NOISE_WORDS).strip()
    # экзоним сборной меняет имя только целиком (`SAD` → `USA`)
    return _whole_exonyms().get(clean, clean) if exonyms else clean


@lru_cache(maxsize=4096)
def readings(name: str) -> tuple[str, ...]:
    """Все разумные чтения названия: у кириллицы три, у латиницы одно.
    Пустой кортеж не возвращаем — иначе сравнивать будет нечего.

    У подтверждённого имени канон идёт ПЕРВЫМ, но сырые чтения остаются:
    с 6е словарь массово учит написания локалей («Селта Виго» → Celta Vigo),
    и если оставить один канон, родня выученного имени теряет мостик —
    «Селта» давала бы 80 против «CELTA VIGO» вместо 100 против «SELTA VIGO»
    (поймано на сервере 03.09)."""
    variants = []
    confirmed = _OVERRIDES.get(name.strip())
    if not confirmed:
        # подтверждена может быть основа без категории: «צ'לסי W» ищем и как
        # «צ'לסי» — категорию сравнение всё равно берёт из исходного имени,
        # а иврит без этого не читается вовсе (6е, сервер 03.09)
        bare = " ".join(_AGE_RE.sub(" ", _WOMEN_RE.sub(" ", name)).split())
        if bare != name.strip():
            confirmed = _OVERRIDES.get(bare)
    if confirmed:
        variants.append(to_english(confirmed) or confirmed)
    # пометку пола снимаем ДО транслита: кириллическая «(Ж)» и греческая «Γ»
    # иначе доезжают до сравнения буквами «Zh»/«G», которых _tidy уже не
    # узнаёт, и «Австралия (Ж)» не сходилась с «Australia W» (06.09)
    cmp_name = re.sub(r"\s{2,}", " ", _WOMEN_RE.sub(" ", name)).strip() or name
    variants.append(to_english(cmp_name) or cmp_name)
    if _HEBREW_RE.search(cmp_name):
        # у иврита нет огласовок: одна буква читается двояко («פ» — и P, и
        # F). Даём сравнению все разумные чтения, иначе «סנטה פה» остаётся
        # «SNTA PA» и своё «Santa Fe» в эталоне не узнаёт (владелец 09.09)
        variants.extend(hebrew_name_readings(cmp_name))
    if _CYRILLIC_RE.search(cmp_name):
        variants.append(to_english(_bulgarian(cmp_name)) or cmp_name)
        variants.append(to_english(_russian(cmp_name)) or cmp_name)
    out: list[str] = []
    for v in variants:
        t = _tidy(v)
        if t and t not in out:
            out.append(t)
    # точечная аббревиатура после чистки рассыпается на буквы («N.E.C» →
    # «N E C») и слитного написания эталона («NEC Nijmegen») не узнаёт —
    # добавляем чтение со склейкой таких букв (#2251, владелец 12.09)
    for t in list(out):
        folded = _fold_singles(t)
        if folded != t and folded not in out:
            out.append(folded)
    return tuple(out) or (_tidy(name) or name.upper(),)


def _fold_singles(text: str) -> str:
    """«N E C NIJMEGEN» → «NEC NIJMEGEN»: подряд идущие однобуквенные
    куски склеиваются в одно слово."""
    tokens = text.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        j = i
        while j < len(tokens) and len(tokens[j]) == 1 and tokens[j].isalpha():
            j += 1
        if j - i >= 2:
            out.append("".join(tokens[i:j]))
            i = j
        else:
            out.append(tokens[i])
            i += 1
    return " ".join(out)


_CLUB_FORMS = {
    "FC", "SC", "AFC", "CF", "AC", "SS", "SSC", "US", "AS", "SL", "GD", "CD",
    "BC", "CA", "SV", "CFC", "VFL", "VFB", "SK", "FK", "OGC", "MFK", "TSG",
    "BSC", "CLUB", "CALCIO",
    # турецкие хвосты юрлица и слова «клуб»: `Antalyaspor A.Ş`,
    # `Muğlaspor Kulübü` — для сравнения и витрины они лишние (01.09)
    "A.Ş", "A.S.", "A.Ş.", "AŞ", "KULÜBÜ", "KULUBU", "SPOR KULÜBÜ",
}
# Пишутся заглавными и в обычном тексте — `Paok` вместо `PAOK` выглядит
# ошибкой. Список короткий и пополняется по мере появления клубов.
_ABBREVIATIONS = {
    "USA", "UAE",
    "AEK", "PAOK", "PSV", "GKS", "ADO", "AFS", "TSV", "CSKA", "PSG", "LASK",
    "MOL", "OFI", "APOEL", "AZ", "NEC", "RKC", "PEC", "SVB", "TSC",
}
_VOWELS = set("AEIOUY")
# Предлоги внутри имени пишутся со строчной: `Estrela da Amadora`
_LOWER_IN_NAME = {"DA", "DE", "DEL", "DI", "DOS", "DAS", "LA", "LE", "VAN", "VON"}


#: Римские цифры в именах вторых команд: `Korona II Kielce`, `Dinamo II`.
#: Без этого `capitalize()` делал из них `Ii` (01.09).
_ROMAN = {"II", "III", "IV", "VI", "VII", "VIII", "IX", "XI"}

#: Комбинируемая точка над буквой. Турецкая заглавная `İ` при `capitalize()`
#: разваливается на `i` + точку, и в витрине выходит `Emi̇nevi̇m` (01.09).
_COMBINING_DOT = "̇"


def suggest_canonical(name: str) -> str:
    """Как показать имя человеку — заготовка для очереди модерации.

    От `readings()` отличается тем, что бережёт важное человеку и неважное
    для сравнения: год в имени клуба (`Schalke 04`, `Hannover 96` — часть
    названия, а не мусор), предлоги (`Estrela da Amadora`) и диакритику
    (`Górnik Zabrze`). Кириллицу читаем по-болгарски: наши кириллические
    источники болгарские, украинская таблица дала бы `Botev Plovdyv`.
    """
    raw = _NUM_PREFIX_RE.sub("", (name or "").strip()).strip()
    if not raw:
        return ""
    # Имя, которое словарь знает ЦЕЛИКОМ: `Francia` → `France`, `España` →
    # `Spain`. Раньше экзоним работал только при сравнении с эталоном, а на
    # витрине владелец видел испанское написание — жалоба 10.09 по игре
    # #1961 «Francia W vs TBC W». Пол и возраст сохраняем: они не переводятся
    # диакритику снимаем: в словаре ключи ASCII (`ESPANA`, `MAGYARORSZAG`),
    # а `_tidy` режет чужие буквы в пробел — «España» давала «ESPA A»
    голое = "".join(c for c in unicodedata.normalize("NFKD", raw)
                    if not unicodedata.combining(c))
    ключ = _tidy(голое, exonyms=False)
    англ = _whole_exonyms().get(ключ)
    if англ and англ != ключ:
        cat = category(raw)
        показ = suggest_canonical(англ)
        return f"{показ} {cat}".strip() if cat else показ
    table = aliases()
    out: list[str] = []

    # Идём по словам ИСХОДНОГО имени: только так видно, как слово было
    # написано. После транслитерации регистр не восстановить — `Черно`
    # превращается в `CHerno`, и по нему уже не понять, был ли это капс.
    for source_word in raw.split():
        cyrillic = _CYRILLIC_RE.search(source_word)
        if cyrillic:
            word = to_english(_bulgarian(source_word))
        elif any(ord(c) > 0x2FF for c in source_word):
            # иврит, греческий, арабский… — до 15.09 такие слова доходили
            # до страниц как есть (а греческий ещё и капсом), хотя
            # `translit.to_english` умеет их все; латиницу с диакритикой
            # (Górnik, Beşiktaş) порог 0x2FF не задевает
            word = to_english(source_word)
        else:
            word = source_word
        upper = word.upper()
        if upper in _CLUB_FORMS:
            continue
        known = table.get(upper)
        if known:                       # `LIIDS` → `LEEDS`, `MADRYT` → `MADRID`
            word = upper = known

        # гласные ищем без диакритики, иначе `ŁÓDŹ` сойдёт за аббревиатуру
        plain = "".join(c for c in unicodedata.normalize("NFKD", upper)
                        if not unicodedata.combining(c))
        if upper in _ROMAN:
            out.append(upper)                       # Korona II, Dinamo II
        elif upper in _ABBREVIATIONS or not (_VOWELS & set(plain)):
            out.append(upper)                       # PAOK, PSV, GKS
        elif out and upper in _LOWER_IN_NAME:
            out.append(word.lower())                # Estrela da Amadora
        elif source_word.isupper() or cyrillic or known \
                or (word != source_word and word.islower()):
            # BRAGA → Braga, Черно → Cherno; транслит без словаря отдаёт
            # строчные («ολυμπιακος» → «olympiakos») — поднимаем первую
            out.append(word.capitalize())
        else:
            out.append(word)                        # Górnik, Widzew — как есть
    return " ".join(out).replace(_COMBINING_DOT, "").strip() or raw


#: Огрубление написания — только для сравнения, наружу оно не выходит.
#: Одна и та же команда в разных языках пишется то через "c", то через "k"
#: (Vallecano — Валекано), с удвоенной согласной и без (Vallecano — Valekano).
#: Без огрубления такая пара набирает 82 при пороге 85 и не склеивается.
#: "CH" не трогаем: Челси и Chelsea должны остаться разными от "K"-слов.
_ROUGH_DOUBLE = re.compile(r"([BCDFGKLMNPRSTVZ])\1")


def _rough(word: str) -> str:
    word = word.replace("CH", "\1")
    word = word.replace("C", "K").replace("Q", "K").replace("W", "V")
    word = word.replace("\1", "CH")
    return _ROUGH_DOUBLE.sub(r"\1", word)



#: Экзонимы городов: один и тот же клуб на разных языках называют разными
#: словами, которые НЕ похожи побуквенно, — `Bayern Munich` у англичан,
#: `Bayern Mnichov` у чехов (поймано владельцем 02.09: игра #279/#280 легла
#: двумя строками). Перед пословным сравнением такие слова приводим к
#: одному написанию. Ключи и значения — в верхнем регистре, как слова
#: приходят в `_words_score` после `readings()`.
_EXONYMS = {
    # сокращения, которыми пишет сам эталон flashscore: «Ind. del Valle»,
    # «H. Beer Sheva», «Atl. Tucuman». Сетки каналов дают то же имя целиком
    # («INDEPENDIENTE DEL VALLE»), и без разворачивания одна игра ложилась
    # на витрину двумя-тремя строками (владелец 09.09, Инд. дель Валье —
    # Фламенго тремя записями). Точку `_tidy` уже снял, сюда слово приходит
    # голым и в верхнем регистре.
    "IND": "INDEPENDIENTE", "ATL": "ATLETICO", "DEP": "DEPORTIVO",
    "HAP": "HAPOEL", "MACC": "MACCABI", "UNIV": "UNIVERSIDAD",
    "ATH": "ATHLETIC", "SPT": "SPORTING", "NAC": "NACIONAL",
    "MNICHOV": "MUNICH", "MUNCHEN": "MUNICH", "MONACHIUM": "MUNICH",
    # "MONACO" НЕ маппим: приставки вроде AS выпадают при сравнении, и
    # `AS Monaco` приклеивался к `Bayern Monaco` со счётом 100 (проверка
    # на заведомо разных, 02.09)
    "TORINO": "TURIN", "TURIN": "TURIN",
    "MILANO": "MILAN", "MILAN": "MILAN",
    "KOLN": "COLOGNE", "KOELN": "COLOGNE", "COLONIA": "COLOGNE",
    "NAPOLI": "NAPLES",
    "ROMA": "ROME",
    "SEVILLA": "SEVILLE",
    "LISBOA": "LISBON", "LISBONA": "LISBON",
    "WARSZAWA": "WARSAW", "VARSOVIA": "WARSAW",
    "PRAHA": "PRAGUE", "PRAG": "PRAGUE",
    "WIEN": "VIENNA", "VIDEN": "VIENNA",
    "BUCURESTI": "BUCHAREST", "BUKAREST": "BUCHAREST",
    "MOSKVA": "MOSCOW", "MOSKAU": "MOSCOW",
    "KYIV": "KIEV", "KIJEV": "KIEV", "KIOW": "KIEV",
    "ATHINA": "ATHENS", "ATENY": "ATHENS", "ATENE": "ATHENS",
    "SOLUN": "SALONIKI", "THESSALONIKI": "SALONIKI",
    "BELEHRAD": "BELGRADE", "BEOGRAD": "BELGRADE",
    "ZAGREB": "ZAGREB",
    "GENEVE": "GENEVA", "GENF": "GENEVA",
    # огрехи транслитерации, вскрытые ночным аудитом базы 02.09 (пары
    # #259/260, #272/276, #281–283, #285 не клеились):
    "VENEZIA": "VENICE", "VENECIA": "VENICE", "VENETSIIA": "VENICE",
    "VENETSIYA": "VENICE",
    "MIUNKHEN": "MUNICH", "MYUNKHEN": "MUNICH",
    "ZALTSBURG": "SALZBURG",
    "REINDZHERS": "RANGERS", "REINDZHER": "RANGERS",
    "BARNLI": "BURNLEY",
    "MPAGERN": "BAYERN", "BAGERN": "BAYERN", "BAIERN": "BAYERN",
    "OSNAMBRIK": "OSNABRUCK",
}


def _exo(word: str) -> str:
    return _EXONYMS.get(word, word)

def _initial_pair(x: str, y: str) -> bool:
    """Инициал равен слову на ту же букву: flashscore сокращает «Maccabi
    Herzliya» до «M. Herzliya», у тенниса пишет «Djokovic N.» (точку к
    этому месту уже съела нормализация чтений)."""
    if len(x) == 1 and x.isalpha() and len(y) > 1:
        return y.startswith(x)
    if len(y) == 1 and y.isalpha() and len(x) > 1:
        return x.startswith(y)
    return False


def _pairwise(xs: list[str], ys: list[str], initials: bool) -> int:
    return int(min(max((100 if initials and _initial_pair(x, y)
                        else fuzz.ratio(x, y)) for y in ys) for x in xs))


def _words_score(a: str, b: str) -> int:
    """Похожесть двух названий пословно: каждому слову более КОРОТКОГО имени
    ищем лучшую пару во втором и берём худшее совпадение.

    Короткое имя целиком покрыто длинным — оценка высокая (`Brighton` против
    `Brighton Hove Albion`). Есть слово без пары — оценка падает (`United`
    против `Manchester City`).

    Инициал считается совпавшим со словом на ту же букву («M. Herzliya» =
    «Maccabi Herzliya», «Djokovic N.» = «Novak Djokovic»), но только когда
    ОСТАЛЬНЫЕ слова пары и без него сошлись почти точно — иначе
    «F.C. Kopenhagen» примазался бы к «Fenerbahce» одной буквой F
    (#2239, 12.09)."""
    xs = [_exo(w) for w in a.split()]
    ys = [_exo(w) for w in b.split()]
    if not xs or not ys:
        return 0
    if len(xs) > len(ys):
        xs, ys = ys, xs
    direct = _pairwise(xs, ys, False)
    # инициальная ветка — только когда однобуквенный токен вообще есть:
    # иначе на каждой паре имён сравнение гонялось бы трижды, и полный
    # разбор обхода удлинялся вдвое (замер 12.09)
    if not any(len(w) == 1 and w.isalpha() for w in xs) \
            and not any(len(w) == 1 and w.isalpha() for w in ys):
        boosted = direct
    else:
        boosted = _pairwise(xs, ys, True)
    if boosted > direct:
        # из «остатка» убираем ОБЕ половинки каждой инициальной пары:
        # и букву, и закрытое ею слово — иначе слово оставалось без пары
        # и честная «M. Herzliya» не проходила собственную проверку
        used_x = {i for i, x in enumerate(xs)
                  for y in ys if _initial_pair(x, y)}
        used_y = {j for j, y in enumerate(ys)
                  for x in xs if _initial_pair(x, y)}
        rest_x = [x for i, x in enumerate(xs) if i not in used_x]
        rest_y = [y for j, y in enumerate(ys) if j not in used_y]
        if rest_x and rest_y \
                and _pairwise(rest_x, rest_y, False) >= SIMILAR_ENOUGH:
            direct = boosted
    rough = int(min(max(fuzz.ratio(_rough(x), _rough(y)) for y in ys)
                    for x in xs))
    return max(direct, rough)


def _skeleton(text: str) -> str:
    """Слово без гласных: «SANTA FE» → «SNT F». Нужен ивриту — там гласные
    на письме не ставят вовсе, и чтение «SNTA FA» иначе проигрывает чужому
    «Santos» (владелец 09.09, игра #1302)."""
    return " ".join(w for w in (_VOWELS_RE.sub("", part)
                                for part in text.split()) if w)


def similarity(one: str, two: str) -> int:
    """Похожесть названий, 0–100. Берём лучшее совпадение среди чтений."""
    best = max(_words_score(x, y) for x in readings(one) for y in readings(two))
    if best >= SIMILAR_ENOUGH:
        return best
    # у иврита сверяем ещё и костяк согласных: гласные там не пишутся, и
    # побуквенное сравнение честную пару недооценивает
    if _HEBREW_RE.search(one) or _HEBREW_RE.search(two):
        bones = max(_words_score(_skeleton(x), _skeleton(y))
                    for x in readings(one) for y in readings(two))
        return max(best, bones)
    return best


def same_team(one: str, two: str, threshold: int = SIMILAR_ENOUGH) -> bool:
    """Одна ли это команда. Разная категория — сразу нет, как бы похоже ни
    было написано."""
    if category(one) != category(two):
        return False
    return similarity(one, two) >= threshold

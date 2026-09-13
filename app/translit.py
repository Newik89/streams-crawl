"""Приведение названий команд к чистой ASCII-латинице.

Взято целиком из соседнего проекта (`reference/translate_teams.py`, ТЗ
разд. 3) и намеренно не переписано: код проверен на боевых данных. Копия, а
не импорт, потому что `reference/` не уезжает в git — обход в GitHub Actions
его не увидит.

Читает только звучание. Английского имени клуба это не даёт: `Манчестър
Юнайтед` → `Manchestar Yunaited`. За имя отвечает словарь `data/aliases.json`
(см. `app/names.py`). Таблица кириллицы здесь украинская; болгарское чтение
добавлено в `app/names.py` вторым вариантом, здесь ничего менять не нужно.

Правило, которое тут реализовано: результат — всегда только латинские буквы
A-Z без диакритики, чтобы по названиям нормально работал обычный текстовый
поиск (Excel не находит "TAUBATÉ" по запросу "taubate").

  - имена в кириллице, грузинском и корейском письме транслитерируются в
    латиницу посимвольно/послогово по стандартным таблицам, китайские
    иероглифы — известные спортивные слова переводом, остаток пиньинем;
    это транслитерация, а не "официальный" английский нейминг клуба;
  - имена, уже написанные латиницей, но с диакритикой (Qarabağ, Şamaxı,
    São Paulo, TAUBATÉ), теряют диакритику (Qarabag, Samaxi, Sao Paulo,
    TAUBATE) — сама буква остаётся, форма клуба не меняется, только пропадают
    точки/чёрточки над буквами, чтобы поиск по plain-ASCII запросу находил
    строку.

Поддержаны: кириллица (украинская/русская), грузинское письмо (мхедрули),
корейский хангыль и китайские иероглифы (словами, где узнали, плюс
романизация/пиньинь на остаток), плюс снятие диакритики с любой латиницы.
"""

from __future__ import annotations

import re
import unicodedata

try:
    from pypinyin import lazy_pinyin as _lazy_pinyin
except ImportError:  # pragma: no cover — китайский тогда просто не трогаем
    _lazy_pinyin = None

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e",
    "є": "ie", "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ь": "", "ю": "iu", "я": "ia", "ъ": "",
    "ы": "y", "э": "e", "ё": "e",
    # казахские/центральноазиатские кириллические буквы, которых нет в
    # украинском/русском алфавите. "қ" -> k (не q): так пишут сами клубы и
    # спортивные СМИ ("Kairat", "Kyzylzhar", "Aktobe"), а не по академической
    # транслитерации.
    "қ": "k", "ғ": "gh", "ң": "ng", "ө": "o", "ұ": "u", "ү": "u", "һ": "h",
    "ә": "a",
}
_CYRILLIC_LOWER = dict(_CYRILLIC)
for _k, _v in list(_CYRILLIC.items()):
    _CYRILLIC[_k.upper()] = _v.capitalize() if _v else ""

# Казахские служебные слова, которые по буквам транслитерируются в мусор
# ("Лигасы" -> "Lyhasy"), а не должны. "Ә" отдельным словом сразу после
# названия команды ("Алтай Ә") — сокращение от "Әйелдер" (женская) —
# полностью убираем, а не переводим в букву: пометку "женская" команда
# получает от лиги через category_suffix() (см. clean_league.py), а не
# тут, иначе получилось бы задвоение "Altai W W".
_KZ_WORDS = {
    "ӘЙЕЛДЕР": "Women",
    "ЛИГАСЫ": "League",
    "ЛИГА": "League",
    "Ә": "",
}

# Арабский алфавит + несколько курдских (соранī) букв, которых в арабском
# нет (ڕ گ ژ ۆ ێ ە — встречаются на курдоязычных спортивных каналах).
# "ع"/"ء" (айн/хамза) на слух почти не слышны в русской/английской речи —
# спортивные СМИ их в названиях команд обычно просто опускают ("Al Ain",
# не "Al 'Ain"), так же поступаем и здесь. Огласовки (харакат) в реальных
# заголовках не встречаются, но на всякий случай тоже убираются.
_ARABIC = {
    "ء": "", "أ": "a", "إ": "i", "آ": "aa", "ؤ": "u", "ئ": "i",
    "ا": "a", "ب": "b", "ة": "a", "ت": "t", "ث": "th", "ج": "j",
    "ح": "h", "خ": "kh", "د": "d", "ذ": "dh", "ر": "r", "ز": "z",
    "س": "s", "ش": "sh", "ص": "s", "ض": "d", "ط": "t", "ظ": "z",
    "ع": "", "غ": "gh", "ف": "f", "ق": "q", "ك": "k", "ل": "l",
    "م": "m", "ن": "n", "ه": "h", "و": "w", "ي": "y", "ى": "a",
    "ڕ": "r", "ڵ": "l", "گ": "g", "ژ": "zh", "ۆ": "o", "ێ": "e", "ە": "e",
    # персидско-курдские формы тех же букв ("й" и "к"), отличаются от
    # арабских ي/ك только начертанием — встречаются в курдских заголовках
    "ی": "y", "ک": "k",
    "ً": "", "ٌ": "", "ٍ": "", "َ": "", "ُ": "", "ِ": "", "ّ": "", "ْ": "", "ـ": "",
}

# "ال" в начале слова — определённый артикль, в спортивных названиях почти
# всегда пишут отдельным словом с заглавной "Al" ("Al Ahly", "Al Zawraa"),
# а не сливают транслитерацией в одно слово.

# Греческий алфавит (ert.gr). Читается по звучанию, как и остальные таблицы:
# "Ολυμπιακός" -> "Olympiakos", "Μπάρτσα" -> "Bartsa". Двухбуквенные сочетания
# идут первыми — без них "μπ" превратилось бы в "mp" ("Bayern" -> "Mpaiern"),
# и фаззи-сравнение с латинским написанием разваливалось бы.
_GREEK_PAIRS = [
    # ου — это "u": "Ντόρτμουντ" -> "Dortmund", "Κρουζέιρο" -> "Kruzeiro"
    ("ου", "u"), ("ΟΥ", "U"), ("Ου", "U"),
    ("γγ", "ng"), ("τσ", "ts"), ("ΤΣ", "TS"), ("Τσ", "Ts"),
    ("τζ", "tz"), ("ΤΖ", "TZ"), ("Τζ", "Tz"),
    ("αυ", "av"), ("ευ", "ev"), ("αι", "e"), ("ει", "i"), ("οι", "i"),
]
#: μπ/ντ/γκ читаются по-разному в зависимости от места в слове: в начале это
#: чистые b/d/g ("Μπάρτσα" -> "Bartsa"), а внутри — носовые mb/nd/ng
#: ("Ολυμπιακός" -> "Olymbiakos", "Ντόρτμουντ" -> "Dortmund"). Без этого
#: деления получалось "Olybiakos" и "Dortmoud".
_GREEK_HEAD = [("μπ", "b"), ("ντ", "d"), ("γκ", "g"),
               ("ΜΠ", "B"), ("ΝΤ", "D"), ("ΓΚ", "G"),
               ("Μπ", "B"), ("Ντ", "D"), ("Γκ", "G")]
_GREEK_INNER = [("νγκ", "ng"), ("ΝΓΚ", "NG"),
                ("μπ", "mb"), ("ντ", "nd"), ("γκ", "ng"),
                ("ΜΠ", "MB"), ("ΝΤ", "ND"), ("ΓΚ", "NG")]

_GREEK = {
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
    "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o",
    # с ударением — то же чтение
    "ά": "a", "έ": "e", "ή": "i", "ί": "i", "ό": "o", "ύ": "y", "ώ": "o",
    "ϊ": "i", "ϋ": "y", "ΐ": "i", "ΰ": "y",
}
for _k, _v in list(_GREEK.items()):
    _GREEK[_k.upper()] = _v.capitalize() if _v else ""

# Иврит (sport1.maariv.co.il). Гласные на письме почти не обозначаются, поэтому
# читаем "матери чтения": א -> a, ו -> o, י -> i. Получается не английское имя
# клуба, а его звучание ("אסטון וילה" -> "aston vila"), и этого хватает, чтобы
# сравнение с латинским написанием сработало.
_HEBREW = {
    "א": "a", "ב": "b", "ג": "g", "ד": "d", "ה": "h", "ו": "o", "ז": "z",
    "ח": "ch", "ט": "t", "י": "i", "כ": "k", "ך": "k", "ל": "l", "מ": "m",
    "ם": "m", "נ": "n", "ן": "n", "ס": "s", "ע": "", "פ": "p", "ף": "f",
    "צ": "ts", "ץ": "ts", "ק": "k", "ר": "r", "ש": "sh", "ת": "t",
    "׳": "", "'": "'",
}

# Частые слова израильских клубов — целиком, английским написанием эталона
# flashscore: побуквенный транслит их не вытягивает (מכבי -> "mkbi" против
# "Maccabi", חיפה -> "chipa" против "Haifa"), а именно эти слова решают,
# какой из одновременных израильских матчей перед нами (6е, задание 03.09).
# Аббревиатуры городов (ת"א, ב"ש, י-ם) буквами не читаются вовсе.
_HE_WORDS = {
    'ת"א': "Tel Aviv", 'ב"ש': "Beer Sheva", "י-ם": "Jerusalem",
    'פ"ת': "Petah Tikva", 'כפ"ס': "Kfar Saba", 'ראשל"צ': "Rishon LeZion",
    'ר"ג': "Ramat Gan", 'ק"ש': "Kiryat Shmona",
    "הפועל": "Hapoel", "מכבי": "Maccabi", 'בית"ר': "Beitar",
    "ביתר": "Beitar", "עירוני": "Ironi", "בני": "Bnei",
    "קריית": "Kiryat", "קרית": "Kiryat", "כפר": "Kfar",
    "תל": "Tel", "אביב": "Aviv", "באר": "Beer", "שבע": "Sheva",
    "חיפה": "Haifa", "ירושלים": "Jerusalem", "נתניה": "Netanya",
    "אשדוד": "Ashdod", "אשקלון": "Ashkelon", "סכנין": "Sakhnin",
    "טבריה": "Tiberias", "הרצליה": "Herzliya", "רעננה": "Raanana",
    "מודיעין": "Modiin", "אילת": "Eilat", "נצרת": "Nazareth",
    "פתח": "Petah", "תקווה": "Tikva", "ראשון": "Rishon",
    "לציון": "LeZion", "רמת": "Ramat", "גן": "Gan", "יהודה": "Yehuda",
    "העמק": "HaEmek", "נס": "Nes", "ציונה": "Ziona", "קאסם": "Qasim",
    "שמונה": "Shmona", "יפו": "Jaffa",
    # европейские клубы, как их пишет израильская пресса (maariv, sport5):
    # побуквенный транслит эти имена не вытягивает (жалобы владельца 12.09,
    # #2141/#2149/#1372/#1594). «הכוכב האדום» — «красная звезда» — кладём
    # пословно: сравнение неупорядоченное, «Star Red» узнаёт парижский
    # Red Star (Лига 2); сербская Crvena zvezda этим не задевается
    'פ.ס.ז': "PSG", "פ.ס.ז׳": "PSG", "פ.ס.ז'": "PSG",
    "הכוכב": "Star", "האדום": "Red",
    "צזנה": "Cesena", "קרמונזה": "Cremonese",
    "לצ'ה": "Lecce", "לצ׳ה": "Lecce",
    "ברסט": "Brest", "מץ": "Metz",
    "וילרבאן": "Villeurbanne", "זאגרב": "Zagreb", "דינמו": "Dinamo",
}


#: буквы иврита, которые читаются двояко: огласовок в письме нет, и одна
#: буква даёт разные звуки в разных именах. «פ» — это и P (Платенсе), и F
#: (Флуминенсе, Санта-Фе); «ב» — B и V; «ו» внутри слова — O и U. Из-за
#: единственного чтения «סנטה פה» превращалось в «SNTA PA» и не узнавало
#: «Santa Fe» (жалоба владельца 09.09). Поэтому имя читаем НЕСКОЛЬКИМИ
#: способами, а сравнение берёт лучший.
_HE_ALTS = {"פ": ("p", "f"), "ף": ("f", "p"), "ב": ("b", "v"),
            "ו": ("o", "u"), "כ": ("k", "kh"), "ך": ("k", "kh"),
            "ג": ("g", "j")}
#: сколько двояких букв разворачиваем (2 варианта на каждую): 4 буквы — до
#: 16 чтений слова, дальше сравнение дорожает без пользы
_HE_ALT_LIMIT = 4


def hebrew_readings(token: str) -> list[str]:
    """Все разумные латинские чтения ивритского слова (первое — основное).

    Слово из словаря `_HE_WORDS` возвращаем как есть: там уже написание
    эталона. Для остальных перебираем двоякие буквы (`_HE_ALTS`).
    """
    bare = token.replace("״", '"').strip(",.()")
    known = _HE_WORDS.get(bare)
    if known is not None:
        return [known]
    spots = [i for i, ch in enumerate(token) if ch in _HE_ALTS][:_HE_ALT_LIMIT]
    out: list[str] = []
    for mask in range(1 << len(spots)):
        letters = []
        for i, ch in enumerate(token):
            if ch == "ו" and i == 0:
                letters.append("v")            # ו в начале слова — согласная
                continue
            if ch == "ה" and i == len(token) - 1 and len(token) > 1:
                letters.append("a")            # конечная ה — «а», не «х»
                continue
            if i in spots:
                pick = (mask >> spots.index(i)) & 1
                letters.append(_HE_ALTS[ch][pick])
                continue
            letters.append(_HEBREW.get(ch, ch))
        word = "".join(letters)
        if word and word not in out:
            out.append(word)
    return out or [token]


def hebrew_name_readings(name: str, limit: int = 12) -> list[str]:
    """Чтения ивритского НАЗВАНИЯ целиком: слова читаются каждое по-своему,
    варианты перемножаются (с потолком `limit`). Первое чтение — основное.
    Латинские куски («צ'לסי FC») остаются как есть."""
    parts: list[list[str]] = []
    for token in name.split():
        if any(_is_hebrew(c) for c in token):
            parts.append(hebrew_readings(token))
        else:
            parts.append([token])
    out = [""]
    for choices in parts:
        out = [(head + " " + tail).strip()
               for head in out for tail in choices][:limit]
    return out


_AL_PREFIX_RE = re.compile("^ال(?=.)")

_GEORGIAN = {
    "ა": "a", "ბ": "b", "გ": "g", "დ": "d", "ე": "e", "ვ": "v", "ზ": "z",
    "თ": "t", "ი": "i", "კ": "k", "ლ": "l", "მ": "m", "ნ": "n", "ო": "o",
    "პ": "p", "ჟ": "zh", "რ": "r", "ს": "s", "ტ": "t", "უ": "u", "ფ": "p",
    "ქ": "k", "ღ": "gh", "ყ": "q", "შ": "sh", "ჩ": "ch", "ც": "ts",
    "ძ": "dz", "წ": "ts", "ჭ": "ch", "ხ": "kh", "ჯ": "j", "ჰ": "h",
}

# Revised Romanization корейского — стандартные таблицы начальных/гласных/
# конечных согласных хангыля (позиции соответствуют порядку блоков Unicode)
_HAN_CHO = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "",
            "j", "jj", "ch", "k", "t", "p", "h"]
_HAN_JUNG = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae",
             "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
_HAN_JONG = ["", "g", "kk", "gs", "n", "nj", "nh", "d", "l", "lg", "lm", "lb",
             "ls", "lt", "lp", "lh", "m", "b", "bs", "s", "ss", "ng", "j",
             "ch", "k", "t", "p", "h"]


def _romanize_hangul_char(ch: str) -> str:
    cp = ord(ch)
    idx = cp - 0xAC00
    jong = idx % 28
    idx //= 28
    jung = idx % 21
    cho = idx // 21
    return _HAN_CHO[cho] + _HAN_JUNG[jung] + _HAN_JONG[jong]


# Корейские названия команд в этом списке — почти всегда "город/провинция +
# тип организации + 축구단(FC)". Слепая посимвольная романизация даёт мусор
# вроде "gyotonggongsa" вместо "Transportation Corporation". Поэтому сначала
# ищем известные слова-компоненты (длинные — первыми) и переводим их по
# смыслу, а на распознанные остатки (в основном топонимы и имена школ/клубов)
# накладываем обычную романизацию по слогам.
_KO_WORDS = [
    ("유소년축구클럽", "Youth Football Club"),
    ("스포츠클럽", "Sports Club"),
    ("축구클럽", "Football Club"),
    ("축구센터", "Football Center"),
    ("풋볼파크", "Football Park"),
    ("스포츠토토", "Sports Toto"),
    ("현대제철", "Hyundai Steel"),
    ("교통공사", "Transportation Corporation"),
    ("유나이티드", "United"),
    ("축구단", "FC"),
    ("시민", "Citizen"),
    ("시청", "City Hall"),
    ("여자", "Women's"),
    ("글로벌", "Global"),
]
# длиннее — раньше, иначе короткое совпадение сработает первым
_KO_WORDS.sort(key=lambda p: -len(p[0]))

# однослоговые суффиксы уровня учебного заведения — заменяем, только когда
# слог стоит в самом конце корейского куска (иначе можно случайно испортить
# топоним, например "중" внутри "중앙" — это не "школа", а "центральный")
_KO_SUFFIX = [("중", "Middle School"), ("고", "High School"), ("대", "University")]


def _translate_korean_run(run: str) -> str:
    """Известные слова — переводятся отдельными словами; всё остальное —
    склеенная посложная романизация (топонимы/имена школ так и остаются
    одним словом, например "Busan", а не "Bu San")."""
    chunks: list[str] = []
    buf: list[str] = []
    i, n = 0, len(run)

    def flush():
        if buf:
            chunks.append("".join(buf))
            buf.clear()

    while i < n:
        matched = next((w for w in _KO_WORDS if run.startswith(w[0], i)), None)
        if matched:
            flush()
            chunks.append(matched[1])
            i += len(matched[0])
            continue
        if i == n - 1:
            suffix = next((eng for ko, eng in _KO_SUFFIX if run[i] == ko), None)
            if suffix:
                flush()
                chunks.append(suffix)
                i += 1
                continue
        buf.append(_romanize_hangul_char(run[i]))
        i += 1
    flush()

    chunks = [c[0].upper() + c[1:] if c and c[0].islower() else c for c in chunks]
    return " ".join(chunks)


# Как и с корейским: известные спортивно-организационные слова переводим по
# смыслу, а на остаток (в основном топонимы и имена спонсоров) накладываем
# пиньинь. "队" (буквально "команда") в спортивном контексте почти всегда
# означает клуб/сборную — переводим как "FC", это ближе к принятому в
# англоязычных СМИ виду ("Guangzhou FC"), чем буквальное "Team".
_ZH_WORDS = [
    ("足球俱乐部", "FC"),
    ("篮球俱乐部", "Basketball Club"),
    ("俱乐部", "Club"),
    ("联队", "United"),
    ("女足", "Women's Football"),
    ("男足", "Men's Football"),
    ("女篮", "Women's Basketball"),
    ("男篮", "Men's Basketball"),
    ("足球", "Football"),
    ("篮球", "Basketball"),
    ("队", "FC"),
]
_ZH_WORDS.sort(key=lambda p: -len(p[0]))


def _translate_chinese_run(run: str) -> str:
    """Как _translate_korean_run, но для китайского: известные слова —
    переводом, остаток — слитным пиньинем (через pypinyin)."""
    if _lazy_pinyin is None:
        return run  # библиотека не установлена — оставляем как есть

    chunks: list[str] = []
    buf: list[str] = []
    i, n = 0, len(run)

    def flush():
        if buf:
            syllables = _lazy_pinyin("".join(buf))
            chunks.append("".join(syllables))
            buf.clear()

    while i < n:
        matched = next((w for w in _ZH_WORDS if run.startswith(w[0], i)), None)
        if matched:
            flush()
            chunks.append(matched[1])
            i += len(matched[0])
            continue
        buf.append(run[i])
        i += 1
    flush()

    chunks = [c[0].upper() + c[1:] if c and c[0].islower() else c for c in chunks]
    return " ".join(chunks)


def _is_cyrillic(ch: str) -> bool:
    return ch in _CYRILLIC


def _is_georgian(ch: str) -> bool:
    return "Ⴀ" <= ch <= "ჿ"


def _is_arabic(ch: str) -> bool:
    return ch in _ARABIC or "؀" <= ch <= "ۿ"


def _is_greek(ch: str) -> bool:
    return ch in _GREEK


def _is_hebrew(ch: str) -> bool:
    return ch in _HEBREW and ch != "'"


def _is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


def _is_han(ch: str) -> bool:
    return "一" <= ch <= "鿿"


def _needs_transliteration(token: str) -> bool:
    return any(_is_cyrillic(c) or _is_georgian(c) or _is_hangul(c) or _is_han(c)
               or _is_arabic(c) or _is_greek(c) or _is_hebrew(c)
               for c in token)


_HANGUL_RUN_RE = re.compile(r"[가-힣]+")
_HAN_RUN_RE = re.compile(r"[一-鿿]+")


def _transliterate_token(token: str) -> str:
    # Известные казахские служебные слова — целиком словом, а не по буквам
    # (см. _KZ_WORDS). Проверяем до всего остального: это отдельный токен
    # (пробелы уже разделили его от соседних слов), сравниваем как есть.
    if token.upper() in _KZ_WORDS:
        return _KZ_WORDS[token.upper()]

    # Корейский и китайский переводим отдельно (словами, где узнали,
    # романизацией/пиньинем — где нет), до кириллицы/грузинского, которые в
    # этом же токене не встречаются вместе с ними.
    if _HANGUL_RUN_RE.search(token):
        token = _HANGUL_RUN_RE.sub(lambda m: _translate_korean_run(m.group()), token)
    if _HAN_RUN_RE.search(token):
        token = _HAN_RUN_RE.sub(lambda m: _translate_chinese_run(m.group()), token)

    # Греческий и иврит — до кириллицы: в одном слове они не встречаются,
    # а таблицы у них свои (в греческой важны двухбуквенные сочетания).
    if any(_is_greek(c) for c in token):
        for pair, repl in _GREEK_HEAD:
            if token.startswith(pair):
                token = repl + token[len(pair):]
                break
        for pair, repl in _GREEK_INNER:
            token = token.replace(pair, repl)
        for pair, repl in _GREEK_PAIRS:
            token = token.replace(pair, repl)
        return "".join(_GREEK.get(c, c) for c in token)
    if any(_is_hebrew(c) for c in token):
        # известное слово или аббревиатура — целиком (см. _HE_WORDS);
        # типографский гершаим ״ сводим к прямой кавычке из таблицы
        bare = token.replace("״", '"').strip(",.()")
        known = _HE_WORDS.get(bare)
        if known is not None:
            return known
        # ו в начале слова — согласная "в" ("וילה" -> "vila"), внутри — гласная;
        # конечная ה передаёт "а" ("ברצלונה" -> "brtslona"), а не звук "х"
        out = []
        for i, ch in enumerate(token):
            if ch == "ו" and i == 0:
                out.append("v")
            elif ch == "ה" and i == len(token) - 1 and len(token) > 1:
                out.append("a")
            else:
                out.append(_HEBREW.get(ch, ch))
        return "".join(out)

    if not any(_is_cyrillic(c) or _is_georgian(c) or _is_arabic(c) for c in token):
        return token

    # Если слово набрано ЗАГЛАВНЫМИ (частый стиль в анонсах — "ҚАЙРАТ-ЖАСТАР"),
    # многобуквенные замены (ж->zh, х->kh...) переводим в верхний регистр
    # целиком, а не только их первую букву — иначе получается "ZhASTAR".
    # У арабского регистра нет вовсе, поэтому isupper() для него всегда
    # False и в эту ветку такие токены не попадают.
    if token.isupper():
        out = []
        for ch in token.lower():
            if ch in _CYRILLIC_LOWER:
                out.append(_CYRILLIC_LOWER[ch])
            elif _is_georgian(ch):
                out.append(_GEORGIAN[ch])
            else:
                out.append(ch)
        return "".join(out).upper()

    if _is_arabic(token[0]) and _AL_PREFIX_RE.match(token):
        rest = _transliterate_token(token[2:])
        rest = rest[0].upper() + rest[1:] if rest else rest
        return "Al " + rest

    out = []
    for ch in token:
        if _is_cyrillic(ch):
            out.append(_CYRILLIC[ch])
        elif _is_georgian(ch):
            out.append(_GEORGIAN[ch])
        elif _is_arabic(ch):
            out.append(_ARABIC.get(ch, ch))
        else:
            out.append(ch)
    result = "".join(out)
    # кириллица уже приходит с верной капитализацией по словарю, а грузинское
    # и арабское письмо регистра не имеют вовсе — капитализируем сами
    if any(_is_georgian(c) or _is_arabic(c) for c in token) and result:
        result = result[0].upper() + result[1:]
    return result


_WORD_RE = re.compile(r"\S+|\s+")

# "U-21" / "u-15" -> "U21" / "U15" — без дефиса, единый формат везде.
# Без \b слева намеренно: в романизированном корейском встречается вплотную
# приклеенное "...чуггуданU-15" без пробела перед U.
_U_AGE_RE = re.compile(r"U-(\d{1,2})\b", re.IGNORECASE)

# Буквы, которые unicodedata.normalize('NFKD', ...) не раскладывает на
# базовую букву + диакритику (это отдельные знаки, а не "буква + акцент"),
# поэтому их приходится заменять руками
_DIACRITIC_OVERRIDES = {
    "ı": "i", "ə": "e", "Ə": "E", "ø": "o", "Ø": "O", "ß": "ss",
    "đ": "d", "Đ": "D", "ł": "l", "Ł": "L", "æ": "ae", "Æ": "AE",
    "œ": "oe", "Œ": "OE",
}


def _fold_diacritics(s: str) -> str:
    """São Paulo -> Sao Paulo, TAUBATÉ -> TAUBATE, Qarabağ -> Qarabag —
    буква остаётся собой, пропадают только надстрочные знаки, чтобы обычный
    поиск без спецсимволов находил строку."""
    s = "".join(_DIACRITIC_OVERRIDES.get(c, c) for c in s)
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def to_english(name: str | None) -> str | None:
    """Приводит имя команды к чистой ASCII-латинице.

    Кириллица/грузинский/корейский/китайский — транслитерируются посимвольно
    или послогово (см. модульный докстринг). Латиница с диакритикой (São
    Paulo, TAUBATÉ, Qarabağ) теряет диакритику, но не саму букву. Возрастные
    пометки вида "U-21" всегда приводятся к "U21" (без дефиса).
    """
    if not name:
        return name
    result = "".join(
        _transliterate_token(piece) if _needs_transliteration(piece) else piece
        for piece in _WORD_RE.findall(name)
    )
    result = _U_AGE_RE.sub(lambda m: f"U{m.group(1)}", result)
    # слово вроде "Ә" может перевестись в пустую строку (см. _KZ_WORDS) —
    # схлопываем оставшийся двойной пробел и обрезаем края
    result = re.sub(r"\s{2,}", " ", result).strip()
    return _fold_diacritics(result)

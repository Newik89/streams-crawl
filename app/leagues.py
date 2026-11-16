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
#: хвост тура или сезона в скобках в конце: «Scottish Premiership (15.
#: Spieltag)», «ASOBAL (T26/27)» — в скобках есть цифра (книга 109: словарь
#: искал подпись целиком и лигу не находил). Возраст в скобках («(U21)»,
#: «(Sub-19)») — не хвост: это другая лига
_ROUND_TAIL = re.compile(
    r"\s*\((?!\s*(?:u|under|sub)[\s-]{0,3}\d)[^()]*\d[^()]*\)\s*$", re.I)
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
    # общие: английское, «(w)» и «(F)»/«(FEM)» — так пишут movistar, ipko,
    # allente, sporttv («Denmark - Germany (F)», книга 086)
    (None, r"\bwomen'?s?\b|\(w\)|\(f\)|\(fem\)"),
    (("pl",), r"\bkobiet\w*\b"),
    # испанский, португальский, румынский, французский, итальянский:
    # femenino/feminino/feminin
    (("es", "pt", "ro", "fr", "it"), r"\bfem[ei]nin[ao]?\b|\bfeminin\w*\b"),
    # португальское «Seniores F» — sporting.pt (женское дерби Бенфика —
    # Спортинг узнавал только эталон, книга 086)
    (("pt",), r"\bseniores f\b"),
    # албанское «femra», «femrave» — ipko, tring (книга 086)
    (("sq",), r"\bfemra\w*"),
    (("it",), r"\bdonne\b|\bfemminil\w*\b"),
    (("de",), r"\bfrauen\w*\b"),
    (("tr",), r"\bkadınlar\b"),
    # сербохорватский и словенский: «ženske», «(ž)», «za žene»
    (("hr", "sr", "bs", "sl"), r"\bžensk\w*\b|\bzensk\w*\b|\bžene?\b|\bza žene\b|\(ž\)"),
    # чешский и словацкий: «MS žen», «ženy»
    (("cs", "sk"), r"\bženy\b|\bžen\b"),
    # одиночная «Ž» («Europe Cup Ž») — сербы, хорваты, чехи; с точкой или
    # апострофом одиночная буква — сокращение, не пол (книга 086)
    (("hr", "sr", "bs", "sl", "cs", "sk"), r"(?<!\w)ž(?![\w.’'])"),
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
     r"\bжени\b|\bженск\w*\b|\bженщин\w*\b|\bжінк\w*\b|(?<!\w)ж(?![\w.’'])"
     r"|\bәйел\w*"),
    # греческое: «γυναικών», одиночная «Γ»; «Μάντσεστερ Γ.» (Манчестер
    # Юнайтед у Novasports) и «Γ’ Πρ» — сокращения (книга 086)
    (("el",), r"γυναικ\w*|(?<!\w)γ(?![\w.’'])"),
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

#: книга 144 (#10202): слова «после / по окончании» ПО ЯЗЫКАМ. Сайт дописывает
#: к строке примечание о ДРУГОЙ передаче — sport5: «השידור יחל מיד בסיום כדורסל
#: נשים» («трансляция начнётся сразу по окончании женского баскетбола») — и
#: слово «женский» оттуда становилось пометкой пола: мужская BBL «Oldenburg —
#: Alba Berlin» шла на витрину с буквой W. От такого слова до конца предложения
#: пол не читаем. Язык добавляется, когда такая приписка встретится у сайта
#: этого языка: одиночное «после» бывает и в честном описании женского матча
_AFTER_BY_LANG: tuple = (
    (("he",), r"(?:מיד\s+)?(?:בסיום|לאחר|אחרי)\s"),
)
_AFTER_CACHE: dict = {}


def without_notes(raw: str, langs=None) -> str:
    """Книга 144: текст без примечаний о другой передаче — от слова «после»
    на языке сайта (`_AFTER_BY_LANG`; `langs` None — все языки) до конца
    предложения (точка, «!», «?», «|», перевод строки). Нужен только для
    пометки пола (`category`): возраст и турнир читаются по всему тексту."""
    key = frozenset(langs) if langs is not None else None
    cut = _AFTER_CACHE.get(key)
    if cut is None:
        parts = [pattern for own, pattern in _AFTER_BY_LANG
                 if langs is None or set(own) & set(langs)]
        # книга 146: примечание кончается и на скобке, запятой, двоеточии —
        # иначе оно съедало название женской лиги, стоящее следом
        cut = _AFTER_CACHE[key] = re.compile(
            rf"(?:{'|'.join(parts)})[^.!?|\n(),:;]*", re.I) if parts else False
    return cut.sub(" ", raw or "") if cut else (raw or "")


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


#: книга 144: слово тура на языках наших сайтов. Рядом с числом («11η
#: Αγωνιστική», «7a giornata», «Spieltag 5», «10. Spieltag») — тур, а не
#: часть названия лиги. Список пополняется вместе с источниками
_ROUND_WORDS = (
    "αγωνιστική", "αγωνιστικη", "matchday", "round", "jornada", "giornata", "journée",
    "journee", "spieltag", "kolo", "kolejka", "тур", "кръг", "forduló", "fordulo",
    "omgång", "omgang", "runde", "speelronde", "hafta", "kierros", "rodada", "ronda",
    "מחזור",
)
_ROUND_WORD = "|".join(re.escape(w) for w in _ROUND_WORDS)
#: тур с числом ПОСЛЕ слова: «Journée 5», «Spieltag 5», «מחזור 6». Ищется
#: первым: в «Ligue 1 Journée 5» единица — номер лиги, а не тура (книга 146)
_ROUND_AFTER = re.compile(rf"(?<!\w)(?:{_ROUND_WORD})\s{{0,3}}\d{{1,2}}\b", re.I)
#: тур с числом ПЕРЕД словом — только когда число помечено порядковым знаком
#: («10. Spieltag», «11η Αγωνιστική», «7a giornata») или перед ним стоит
#: разделитель («Премьер-лига. 15 тур», «Cup - 3 kolo»). Голое число после
#: слова названия («Liga Portugal 2 Jornada») — номер лиги (книга 146)
_ROUND_BEFORE = re.compile(
    rf"(?:\b\d{{1,2}}\s?[.ηaªº°]\s{{0,3}}|(?<=[-–—,(|:.]\s)\d{{1,2}}\s{{1,3}})(?:{_ROUND_WORD})(?!\w)", re.I)


def _round_at(text: str) -> int:
    """Где в тексте начинается тур с числом; −1 — тура нет."""
    for pattern in (_ROUND_AFTER, _ROUND_BEFORE):
        found = pattern.search(text)
        if found:
            return found.start()
    return -1


def _tail_off(text: str) -> str:
    """Книга 144: у названия лиги снимается хвост — тур, стадия, место.

    Сайт кладёт в поле лиги всё, что стоит рядом с парой: ert.gr —
    «Superbet League 2 | 11η Αγωνιστική | Τρίπολη» (лига, тур, город),
    raiplay.it — «Serie A Women Athora - 7a giornata», start.sportdigital.de
    — «Women's Super League (10. Spieltag): Aston Villa - Birmingham City».
    С таким хвостом лигу не узнаёт словарь, а на витрине у матча без эталона
    стоит вся строка (замер по всем сайтам сбора 15.11: 12 игр из 482).
    Правила по порядку (уточнены книгой 146 по независимой проверке):
      1. части через «|»: передние, где только вид спорта («Ποδόσφαιρο |
         …»), пропускаются; хвост — часть с туром и всё после неё. Частей
         без тура не трогаем: «England | Premier League» — страна и лига,
         а не лига и хвост;
      2. тур с числом (`_round_at`) и всё после него — хвост, если ПЕРЕД
         туром есть название (хоть одна буква). Число перед словом тура без
         порядкового знака — номер лиги («Liga Portugal 2 Jornada 10» →
         «Liga Portugal 2»). Тур в начале («etapa 6 Nations League») не
         трогаем: резать было бы нечего оставить;
      3. ничего не срезано — название возвращается буква в букву; от
         названия ничего не осталось — тоже как было."""
    out = text
    if "|" in out:                                                            # 1
        parts = [p.strip() for p in out.split("|") if p.strip()]
        while len(parts) > 1 and only_sport(parts[0]):
            parts.pop(0)
        for n, part in enumerate(parts):
            if n and _round_at(part) == 0:
                parts = parts[:n]
                break
        if parts:
            out = " | ".join(parts)
    at = _round_at(out)                                                       # 2
    if at > 0 and any(ch.isalpha() for ch in out[:at]):
        out = out[:at].rstrip(_EDGE + "(")
        # тур стоял внутри скобки («(Nachholspiel, 12. Spieltag)») — скобка
        # уходит целиком, незакрытой не оставляем (проверка на данных 16.11)
        if out.count("(") > out.count(")"):
            out = out[:out.rindex("(")].rstrip(_EDGE + "(")
    if out == text or not any(ch.isalpha() for ch in out):                    # 3
        return text
    return out


def clean(raw: str) -> str:
    """Сырое название лиги без вида спорта, сезона и пометок сайта.

    Возвращает пустую строку, если после чистки ничего не осталось — значит
    сайт положил в поле лиги только вид спорта, и опираться на него нельзя.
    """
    # книга 146: пробелы — по одному. Шаблоны сезона и хвостов на длинной
    # серии пробелов (отступы, переводы строк в поле лиги) считали минутами
    text = " ".join((raw or "").split())
    if not text:
        return ""
    text = _tail_off(text)                 # книга 144: тур, стадия, место
    text = _SPORT_PREFIX.sub("", text)
    text = _SPORT_SUFFIX.sub("", text)
    text = _SITE_TAILS.sub(" ", text)
    text = _ROUND_TAIL.sub("", text)
    text = _SEASON.sub(" ", text)
    text = _SEASON_SHORT.sub(" ", text)
    text = _YEAR_TAIL.sub("", text)
    text = _EMPTY_BRACKETS.sub(" ", text)
    text = re.sub(r"\s{2,}", " ", text).strip(_EDGE)
    # книга 156: пометка эфира на краю и стадия в скобках — не название (Л1,
    # Л2); остались одни слова стадии и тура — лиги нет (Л3)
    text = _stage_tail_off(_air_off(text)).strip(_EDGE)
    if stage_only(text):
        return ""
    # книга 143: в названии только слова самого вида спорта — это жанр, а не
    # лига («futbolli» у ipko.tv, «tenis Tenis» у digisport.ro); книга 156 —
    # то же, когда к виду спорта дописана стадия («tenis Tenis Ziua 6»)
    return "" if only_sport(text) or only_sport(_stage_rest(text)) else text


# ── книга 156: в поле лиги — не лига ─────────────────────────────────────────
# Находки 16.11: на витрине на месте лиги стояли «Тур 15 Прямая трансляция»
# (ntvplus.tv: хвост заголовка вместо названия), «alapszakasz» (венгерское
# «регулярный сезон»), «Τελικός» («финал», ert.gr), сама пара игры («Philadelphia
# 76ers – Boston Celtics», dagenstv.com; «Ferencvárosi TC - ETO FC mérkőzés»,
# mediaklikk.hu), лига с парой и пометкой эфира (vsetv.com, sports.kz). Такая
# «лига» первой по времени строки становилась лигой всей игры и не давала
# взять настоящую — с другого сайта или из эталона. Правила (для ВСЕХ сайтов):
#   Л1. Пометка эфира на краю названия — не название (`_air_off`): в конце
#       срезается вместе с тем, что после неё («Кубок Португалии Прямая
#       трансляция», «ABA, direktno»), в начале — само слово («Live UEFA
#       Nations League»). Слова — раздел `live` файла `data/markers.json`.
#   Л2. Стадия в скобках в конце — не название: «CONMEBOL Sudamericana
#       (Finale)» (`_stage_tail_off`).
#   Л3. В названии остались только слова стадии, тура, пометки эфира и числа
#       («Тур 15», «alapszakasz», «(parovi) FINALE», «Τελικός») — лиги нет
#       (`stage_only`). Слова стадии — раздел `league_stage` файла
#       `data/markers.json` и раздел `tournament` → «стадия»; слова тура —
#       `_ROUND_WORDS`.
#   Л4. В названии стоит сама пара строки (обе стороны, между ними только
#       разделитель) — всё с начала пары срезается; остаток — лига, если от
#       него что-то осталось (`without_pair`).
#   Л5. Поле лиги сайт заполнил, а лиги в нём не оказалось (Л1–Л4), — лигу
#       читает общий читатель из рубрик заголовка (`from_title`): части
#       заголовка ДО пары по порядку; первая, которая после чистки осталась
#       названием, — лига. То же, когда поле лиги начинается с пометки эфира,
#       а в заголовке перед этой пометкой есть рубрика («Чемпионат мира среди
#       юношей (U-17). Прямая трансляция из Катара. Катар - Панама»).
#   Л6. Ничего не нашлось — лига пустая: игра возьмёт лигу другого сайта или
#       эталона. Поле лиги, где сайт написал только вид спорта (книга 143),
#       читателя заголовка не зовёт — там лиги и не было.
# Всё решение для строки — `settle`; его зовёт `pipeline.classify`, когда пара
# уже известна. Правила Л1–Л3 делает и сама `clean`.
_NOT_LEAGUE: list = []          # (слова стадии и тура, пометки эфира) — строятся один раз
#: края названия: знаки и кавычки; скобки — только там, где сказано
_EDGE_Q = _EDGE + "\"'«»„“”"
#: Л4: что может стоять между сторонами пары — разделитель и скобки («(BRA) -»)
_PAIR_GAP = re.compile(r"^[\s\-–—:|/,.@&\"'«»„“”xXvVsS]{1,8}$")
_BRACKETED = re.compile(r"[(\[][^()\[\]]*[)\]]")
#: Л5: границы рубрик заголовка: «:», «|», точка после буквы, запятая
_TITLE_PARTS = re.compile(r"\s*[:|]\s*|(?:(?<=[^\W\d_])|(?<=[)\]\"»“]))\.\s+|,\s+")
#: Л5: рубрика длиннее — уже рассказ, а не название
TITLE_LEAGUE_MAX = 70


def _stage_air() -> tuple:
    """(шаблон слов стадии и тура, шаблон пометок эфира) — из `data/markers.json`."""
    if not _NOT_LEAGUE:
        import json
        from .live import MARKERS_FILE, _flatten, _pattern
        data = json.loads(MARKERS_FILE.read_text(encoding="utf-8"))
        stage = (_flatten(data.get("league_stage"))
                 + _flatten((data.get("tournament") or {}).get("стадия"))
                 + list(_ROUND_WORDS))
        _NOT_LEAGUE.extend((_pattern(stage), _pattern(_flatten(data.get("live")))))
    return _NOT_LEAGUE[0], _NOT_LEAGUE[1]


def _air_off(text: str) -> str:
    """Л1: пометка эфира на краю названия срезается. Середину не трогаем:
    «MOTD Live: Women's Super League» остаётся как есть."""
    from .live import greek_plain
    air = _stage_air()[1]
    if air is None:
        return text
    for _ in range(4):                       # пометок на краях бывает две
        plain = greek_plain(text)            # те же позиции: замена буква в букву
        cut = text
        for m in air.finditer(plain):
            if plain[m.start() - 1:m.start()] == "-" and plain[m.start() - 2:m.start() - 1].isalnum():
                continue                     # «Re-Live» — часть слова, не пометка
            if not plain[:m.start()].strip(_EDGE_Q + "(["):                # в начале
                cut = text[m.end():].lstrip(_EDGE_Q + ")]")
                break
            if not plain[m.end():].strip(_EDGE_Q + ")]"):                  # в конце
                cut = text[:m.start()].rstrip(_EDGE_Q + "([")
                break
        if cut == text:
            break
        text = cut
    return text


def _stage_rest(text: str) -> str:
    """Текст без слов стадии, тура, пометок эфира и чисел (с порядковыми
    знаками: «11η», «7a», «1ª», «15-й», «2nd») — на их месте пробелы."""
    from .live import greek_plain
    stage, air = _stage_air()
    rest = greek_plain(text or "")
    for pattern in (stage, air):
        if pattern is not None:
            rest = pattern.sub(" ", rest)
    return re.sub(r"\d+\s?(?:[ηaªº°]|-?[йяе]|st|nd|rd|th)?(?!\w)", " ", rest, flags=re.I)


def stage_only(text: str) -> bool:
    """Л3: в тексте есть слова, но все они — стадия, тур или пометка эфира
    (числа и знаки не в счёт): «Тур 15», «alapszakasz», «1/8 финала»,
    «(parovi) FINALE». Пустой текст — не стадия."""
    text = (text or "").strip()
    if not any(ch.isalpha() for ch in text):
        return False
    return not any(ch.isalpha() for ch in _stage_rest(text))


def _stage_tail_off(text: str) -> str:
    """Л2: скобка в конце, где только стадия, снимается: «CONMEBOL
    Sudamericana (Finale)» → «CONMEBOL Sudamericana». Сама по себе скобка
    («(parovi) FINALE») — дело правила Л3."""
    while True:
        m = re.search(r"\s*[(\[]([^()\[\]]*)[)\]]\s*$", text)
        if not m or not m.start() or not stage_only(m.group(1)):
            return text
        text = text[:m.start()].rstrip(_EDGE)


#: пометки пола и возраста, дописанные к стороне разбором («Poland W», «Катар U17»)
_SIDE_MARKS = re.compile(r"(?:\s+(?:W|U-?\d{2}))+$")


def _side_spans(text: str, side: str) -> list[tuple[int, int]]:
    """Где в тексте стоит сторона пары — целыми словами, без учёта регистра.
    Не нашлась — ищется без дописанных пометок пола и возраста."""
    side = " ".join((side or "").split())
    for name in (side, _SIDE_MARKS.sub("", side)):
        if sum(ch.isalnum() for ch in name) < 2:
            continue
        body = r"\s+".join(re.escape(word) for word in name.split())
        spans = [m.span() for m in re.finditer(rf"(?<!\w){body}(?!\w)", text, re.I)]
        if spans:
            return spans
    return []


def _pair_start(text: str, home: str, away: str) -> int:
    """Л4: где в тексте начинается пара строки — обе стороны рядом, между
    ними только разделитель и скобки; порядок сторон любой (эталон мог их
    переставить). Пары нет — −1. Из нескольких мест берётся последнее:
    «Serbia Cup: Serbia - Montenegro» — пара после двоеточия."""
    best = -1
    for first, second in ((home, away), (away, home)):
        for start, end in _side_spans(text, first):
            for other, _ in _side_spans(text, second):
                gap = _BRACKETED.sub("", text[end:other])
                if other >= end and _PAIR_GAP.match(gap) and gap.strip():
                    best = max(best, start)
    return best


def without_pair(league: str, home: str, away: str) -> str:
    """Л4: название лиги без пары строки и всего, что после неё. Пары в
    названии нет — оно возвращается как было."""
    at = _pair_start(league or "", home, away)
    return league if at < 0 else league[:at].rstrip(_EDGE_Q + "([")


def from_title(title: str, home: str, away: str, before_air: bool = False) -> str:
    """Л5: лига из рубрик заголовка — общий читатель для всех сайтов.

      1. берётся часть заголовка ДО пары строки (`_pair_start`); пары в
         заголовке нет — до первого упоминания любой из сторон; нет и сторон
         — весь заголовок («OTP Bank Liga, műsor, élő adásban»);
      2. `before_air` — только то, что стоит до первой пометки эфира;
      3. рубрики делятся по «:», «|», точке после буквы и запятой
         (`_TITLE_PARTS`); точка после цифры — не граница («2. Liga»);
      4. каждая рубрика чистится (`clean`: вид спорта, тур, стадия, пометка
         эфира); первая, от которой осталось название не длиннее
         `TITLE_LEAGUE_MAX`, — лига. Не осталось ни одной — пусто."""
    from .live import greek_plain
    head = " ".join((title or "").split())
    at = _pair_start(head, home, away)
    if at < 0:
        spots = [span[0] for side in (home, away) for span in _side_spans(head, side)]
        at = min(spots) if spots else len(head)
    head = head[:at]
    if before_air:                                                            # 2
        air = _stage_air()[1]
        found = air.search(greek_plain(head)) if air is not None else None
        head = head[:found.start()] if found else ""
    for part in _TITLE_PARTS.split(head):                                     # 3
        name = clean(part.strip(_EDGE_Q))                                     # 4
        if name and len(name) <= TITLE_LEAGUE_MAX:
            return name
    return ""


def settle(league_raw: str, title: str, home: str, away: str) -> str:
    """Книга 156: лига строки, когда пара уже известна (правила Л1–Л6 выше).
    `home`, `away` — стороны как на сайте; дописанные пометки пола и возраста
    («Poland W») поиску не мешают (`_side_spans`)."""
    raw = " ".join((league_raw or "").split())
    name = clean(raw)                                                         # Л1–Л3
    if not raw or not home or not away:
        return name
    cut = without_pair(name, home, away)                                      # Л4
    if cut != name:
        name = clean(cut)
    if not name:
        # Л6: сайт написал в поле один вид спорта — лиги не было и нет
        return "" if only_sport(raw) else from_title(title, home, away)       # Л5
    from .live import greek_plain
    air = _stage_air()[1]
    led = air.match(greek_plain(raw.lstrip(_EDGE_Q + "(["))) if air is not None else None
    if led:                                                                   # Л5: хвост заголовка
        return from_title(title, home, away, before_air=True) or name
    return name


#: книга 143: слова, которые вместе с названием вида спорта лиги не дают
_SPORT_FILLER = ("sport", "sports", "sporti", "спорт")
_ONLY_SPORT: list = []          # шаблон слов вида спорта — строится один раз


def only_sport(text: str) -> bool:
    """Книга 143: в тексте нет ничего, кроме названия вида спорта.

    Сайт кладёт в поле лиги жанр передачи: ipko.tv — «futbolli» и
    «basketboll», digisport.ro — «tenis Tenis». У матча, который эталон
    знает, лига приходит из эталона; у остальных на витрине на месте лиги
    стояло слово «футбол» (замер по всем сайтам сбора 15.11: 7 игр из 482).
    Правила:
      1. слова вида спорта — одиночные слова раздела `sport` → F, B, T →
         «вид спорта» файла `data/markers.json` (все языки наших сайтов),
         названия вида спорта из двух слов (`_SPORT_WORDS`: «piłka nożna») и
         слово «спорт» (`_SPORT_FILLER`);
      2. длинные записи того же раздела («ליגת האלופות בכדורסל» — Лига
         чемпионов по баскетболу) — названия турниров, сюда не входят;
      3. после удаления таких слов в тексте не осталось ни одной буквы —
         это не лига. Осталось хоть слово («כדורגל איטלקי» — итальянский
         футбол, «Fotbal ženy») — лига как была."""
    text = (text or "").strip()
    if not text:
        return False
    if not _ONLY_SPORT:
        import json
        from .live import MARKERS_FILE, _flatten, _pattern
        node = json.loads(MARKERS_FILE.read_text(encoding="utf-8")).get("sport") or {}
        words = [w for letter in ("F", "B", "T")
                 for w in _flatten((node.get(letter) or {}).get("вид спорта"))
                 if len(w.split()) == 1]                                    # 1, 2
        _ONLY_SPORT.append(_pattern(words + list(_SPORT_WORDS) + list(_SPORT_FILLER)))
    from .live import greek_plain
    pattern = _ONLY_SPORT[0]
    rest = pattern.sub(" ", greek_plain(text.lower())) if pattern else text
    return not any(ch.isalpha() for ch in rest)                             # 3


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
    # книга 144: слово пола из примечания о другой передаче не в счёт
    if women.search(without_notes(raw, langs)) or _WOMEN_LEAGUES.search(raw or ""):
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
    names_by_key = _league_claims(data)
    return {key: next(iter(letters)) for key, letters in names_by_key.items()
            if len(letters) == 1}                             # К3


def _norm_key(s: str) -> str:
    return " ".join((s or "").lower().split())


def _league_claims(data: dict) -> dict[str, set[str]]:
    """Название лиги → виды спорта, у которых есть лига с таким названием.

    Правила ключей (книга 112, 13.11.2026 — «Friendly» считался баскетболом,
    и товарищеский матч Катар — Австралия сняло с витрины):
      К1. ключ — канон лиги, его часть после «:» и все алиасы;
      К2. часть после «:» — НЕ ключ, если перед «:» стоит сам вид спорта
          («BASKETBALL: Friendly»): без головы от названия остаётся общее
          слово, которое есть у любого вида;
      К3. название, которое есть у лиг РАЗНЫХ видов спорта («Superliga»,
          «Premier League», «Liga hiszpańska»), вида спорта не называет.
          Слово владельца 13.11: «мы заводили книгу, чтоб понимать, что эти
          лиги есть в разных видах спорта, и это значит, что нужно искать
          эталон в разных видах спорта». Такую строку ведёт эталон
          (`scripts/parse_live.py`: пара в эталоне любого вида → его вид;
          нет ни в одном — снята с записью в журнал, `СНЯТО_СПОРНАЯ_ЛИГА`).
          Раньше побеждала лига, стоявшая в файле первой."""
    claims: dict[str, set[str]] = {}
    for league in data.get("leagues") or []:
        letter = league.get("sport")
        if letter not in ("F", "B", "T"):
            continue
        names = [league.get("name") or ""]
        head, colon, tail = names[0].partition(":")
        if colon and _norm_key(head) not in SPORT_HEADS:      # К2
            names.append(tail)
        names += league.get("aliases") or []
        for name in names:
            key = _norm_key(name)
            if key:
                claims.setdefault(key, set()).add(letter)
    return claims


def contested(path=None) -> dict[str, set[str]]:
    """К3: названия лиг, которые есть у нескольких видов спорта → эти виды.
    Файла словаря нет — пусто."""
    import json
    from pathlib import Path
    file = Path(path) if path else Path(__file__).resolve().parent.parent         / "data" / "dictionaries.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {key: letters for key, letters in _league_claims(data).items()
            if len(letters) > 1}


def is_contested(names: tuple, table: dict[str, set[str]]) -> bool:
    """Хоть одно из названий строки (лига, сырая лига, рубрика) — спорное."""
    return any(_norm_key(name or "") in table for name in names)


#: К2: слова вида спорта, которые словарь лиг ставит перед «:» вместо страны
SPORT_HEADS = frozenset({"basketball", "football", "soccer", "tennis",
                         "futsal", "баскетбол", "футбол", "теннис"})

# -*- coding: utf-8 -*-
"""Язык сайта: служебные слова строки читаются словарём ЯЗЫКА САЙТА.

Слово владельца 25.10.2026 (жалоба #7925, книга 084): «сайт на хорватском —
к нему применяется логика, что слова нужно проверить с хорватского на
английский. Но названия самих команд могут быть уже написаны на английском».
Повод: венгерское «női» («женский»), записанное ещё и как «noi», нашлось в
вьетнамском «Ha Noi» на хорватском sportklub.hr — и азиатская Лига чемпионов
стала женской.

Правила по порядку:

1. У каждого сайта плана — свои языки (`SITE_LANGS`). Английский разрешён
   всем: «live», «replay», «women» пишут на любом сайте.
2. Служебное слово (пол, «прямой эфир», «повтор», стоп-слова передач) ищется
   в строке, только если его язык — язык сайта (`allowed`).
3. Язык слова: нелатинские буквы говорят сами (иврит, греческий, кириллица,
   арабский — `_SCRIPTS`); латинские слова размечены в `data/word_langs.json`
   по языкам; латинское слово, которого там нет, — общее (английское или
   одинаковое во многих языках: «studio», «dokument», «reportage»).
4. Сайт без строки в `SITE_LANGS` — все языки, как было до 25.10 (новый сайт
   не теряет слова, пока ему не назначили язык; тест `test_yazyk_sayta.py`
   краснеет, пока сайт плана без языка).
5. Названия команд язык сайта не трогает: их сверяет эталон flashscore во
   всех написаниях (английское имя на хорватском сайте — как есть).
6. Язык строки — язык сайта плюс письменность самой строки (`of_row`,
   книга 086): русская строка на литовском tv3.lt читается и по-русски.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORD_LANGS_FILE = ROOT / "data" / "word_langs.json"

#: сербохорватские языки — одна группа: сайты пишут вперемешку
SH = ("hr", "sr", "bs")
#: языки на кириллице (по буквам слова не различить — вся группа)
CYRILLIC = ("ru", "uk", "be", "bg", "sr", "mk", "kk")

#: сайт плана → языки его расписания (кроме английского — он у всех).
#: Новый сайт — дописать сюда; домен без строки читается всеми языками.
SITE_LANGS: dict[str, tuple[str, ...]] = {
    # арабский и английский
    "alkass.net": ("ar",),
    # Скандинавия
    "allente.no": ("no", "sv", "da", "fi"), "tv2.no": ("no",),
    "dagenstv.com": ("sv",), "tvmatchen.nu": ("sv",), "m.flashscore.se": ("sv",),
    "tvmatsit.com": ("fi", "sv"),
    "dr.dk": ("da",), "tvsporten.dk": ("da",), "tvtid.tv2.dk": ("da",),
    "m.flashscore.dk": ("da",),
    # Турция
    "aspor.com.tr": ("tr",), "atv.com.tr": ("tr",), "beinsports.com.tr": ("tr",),
    "trt.net.tr": ("tr",), "trtavaz.com.tr": ("tr",), "trtspor.com.tr": ("tr",),
    "tv8.com.tr": ("tr",), "ssport.tv": ("tr",), "m.flashscore.com.tr": ("tr",),
    # англоязычные
    "bbc.co.uk": (), "skysports.com": (), "tv24.co.uk": (), "rte.ie": (),
    "tvguidetonight.com.au": (), "livesoccertv.com": (), "sporteventz.com": (),
    "flashscore.mobi": (),
    # Канада: TVA Sports — по-французски
    "tvpassport.com": ("fr",), "canpl.ca": ("fr",),
    # Болгария
    "bnt.bg": ("bg",), "nova.bg": ("bg",), "diemaxtra.nova.bg": ("bg",),
    "tv.dir.bg": ("bg",), "maxsport.live": ("bg",), "m.flashscore.bg": ("bg",),
    # Португалия
    "canal11.pt": ("pt",), "rtp.pt": ("pt",), "sporting.pt": ("pt",),
    "sporttv.pt": ("pt",), "m.flashscore.pt": ("pt",),
    # Чехия и Словакия (словацкие сайты держат и чешские передачи)
    "ceskatelevize.cz": ("cs",), "oneplay.cz": ("cs",), "oneplaysport.cz": ("cs",),
    "sport1tv.cz": ("cs",), "m.livesport.cz": ("cs",),
    "kanal1sport.sk": ("sk", "cs"), "tv-program.aktuality.sk": ("sk", "cs"),
    "webtv.sk": ("sk", "cs"), "m.flashscore.sk": ("sk", "cs"),
    # Греция и Кипр
    "cosmotetv.gr": ("el",), "ert.gr": ("el",), "novasports.gr": ("el",),
    "skai.gr": ("el",), "m.flashscore.gr": ("el",), "epg.cyta.com.cy": ("el",),
    # Румыния
    "digisport.ro": ("ro",), "primaplay.ro": ("ro",), "programetv.ro": ("ro",),
    "m.flashscore.ro": ("ro",),
    # Албания и Косово
    "ipko.tv": ("sq",), "tring.al": ("sq",),
    # Прибалтика
    "jupiter.err.ee": ("et",), "tv3.lt": ("lt",),
    # Венгрия
    "m.eredmenyek.com": ("hu",), "mediaklikk.hu": ("hu",), "port.hu": ("hu",),
    "sport1tv.hu": ("hu",),
    # немецкоязычные
    "m.flashscore.de": ("de",), "rtl.de": ("de",), "start.sportdigital.de": ("de",),
    "tv.sport1.de": ("de",), "tv.orf.at": ("de",), "tvheute.at": ("de",),
    "srf.ch": ("de",),
    # Испания, Франция, Италия, Нидерланды, Польша
    "m.flashscore.es": ("es",), "movistarplus.es": ("es",),
    "m.flashscore.fr": ("fr",), "programme-tv.net": ("fr",),
    "m.flashscore.it": ("it",), "raiplay.it": ("it",),
    "m.flashscore.nl": ("nl",), "npo.nl": ("nl",), "ziggosport.nl": ("nl",),
    "m.flashscore.pl": ("pl",), "teleman.pl": ("pl",),
    # русский, украинский, белорусский, казахский
    "m.flashscore.ru": ("ru",), "ntvplus.tv": ("ru",), "vsetv.com": ("ru",),
    "poverkhnost.tv": ("ru",), "football-tv.ru": ("ru",),
    "news.by": ("ru", "be"), "m.flashscore.ua": ("uk",), "unian.tv": ("uk",),
    "sports.kz": ("kk", "ru"),
    # бывшая Югославия
    "m.rezultati.com": SH, "mojtv.hr": SH, "raspored.hrt.hr": SH,
    "sportklub.hr": SH, "tvarenasport.hr": SH, "tvarenasport.ba": SH,
    "tvarenasport.com": SH, "rtcg.me": SH, "rtrs.tv": SH, "rts.rs": SH,
    "tvarenasport.si": ("sl",) + SH,
    # Израиль
    "sport1.maariv.co.il": ("he",), "sport5.co.il": ("he",),
}

#: письменность слова → его языки (латиница — по `data/word_langs.json`)
_SCRIPTS = (
    (re.compile(r"[֐-׿]"), ("he",)),
    (re.compile(r"[Ͱ-Ͽἀ-῿]"), ("el",)),
    (re.compile(r"[؀-ۿ]"), ("ar",)),
    (re.compile(r"[Ѐ-ӿ]"), CYRILLIC),
)


def _bare(domain: str) -> str:
    return (domain or "").strip().lower().removeprefix("www.")


def of(domain: str) -> frozenset[str] | None:
    """Языки сайта (английский всегда с ними). None — сайт неизвестен:
    читаем всеми языками, как до 25.10 (правило 4)."""
    langs = SITE_LANGS.get(_bare(domain))
    if langs is None:
        return None
    return frozenset(langs) | {"en"}


@lru_cache(maxsize=1)
def _tagged() -> dict[str, frozenset[str]]:
    """Латинские слова с языками из `data/word_langs.json`: ключ кучки —
    языки через пробел («hr sr bs»), значение — слова."""
    data = json.loads(WORD_LANGS_FILE.read_text(encoding="utf-8"))
    out: dict[str, frozenset[str]] = {}
    for key, words in data.items():
        if key.startswith("_") or not isinstance(words, list):
            continue
        langs = frozenset(key.split())
        for word in words:
            w = " ".join(word.lower().split())
            out[w] = out.get(w, frozenset()) | langs
    return out


def word_langs(word: str) -> frozenset[str] | None:
    """Языки служебного слова (правило 3). None — общее слово, ищется везде."""
    w = " ".join((word or "").lower().split())
    for letters, langs in _SCRIPTS:
        if letters.search(w):
            return frozenset(langs)
    return _tagged().get(w)


def of_row(langs: frozenset[str] | None, text: str) -> frozenset[str] | None:
    """Правило 6 (книга 086, слово владельца 27.10): язык СТРОКИ — языки
    сайта плюс письменность самой строки. Литовский tv3.lt держит и русские
    передачи («Женщины. …») — русское слово «женщины» там не искалось, и
    женский матч шёл мужским. Нелатинские буквы язык выдают сами (иврит,
    греческий, кириллица, арабский — `_SCRIPTS`); латиница ничего не
    добавляет. Сайт неизвестен (None) — все языки, как было."""
    if langs is None:
        return None
    extra = frozenset(lang for letters, own in _SCRIPTS
                      if letters.search(text or "") for lang in own)
    return langs | extra if extra - langs else langs


def allowed(word: str, langs: frozenset[str] | None) -> bool:
    """Искать ли слово `word` у сайта с языками `langs` (правило 2)."""
    if langs is None:
        return True
    mine = word_langs(word)
    return mine is None or bool(mine & langs)

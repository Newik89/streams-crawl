# -*- coding: utf-8 -*-
"""trt.net.tr — Турция, вещатель TRT: 16 каналов одной страницей.

`/yayin-akisi` отдаёт сетку всех каналов сразу — Tabii Spor, TRT SPOR,
TRT SPOR YILDIZ и общие TRT 1 / TRT 2, где идут матчи сборной. Даты в адресе
нет: страница держит текущий день, поэтому источник заведён сеткой.

Разметка:

    div.cont
      h2.card-texts                `TRT SPOR Yayın Akışı` — имя канала
      div.livestream-conteiner
        span.livestream-time       `21.45` — время через ТОЧКУ, не двоеточие
        span.livestream-title      `Süper Lig: Galatasaray - Fenerbahçe`

Время у турок пишется через точку — своей регуляркой это не ловится, поэтому
разбираем явно. Маркера прямого эфира сайт не даёт: помечаем эфиром первый
показ пары (`mark_first_show`), как у `oneplaysport.cz`.

Один и тот же канал встречается на странице несколько раз (вкладки «ТВ»,
«радио», «цифровые»), поэтому одинаковые строки отбрасываем по паре
(канал, время, заголовок).
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "trt.net.tr"
TZ = "Europe/Istanbul"

_TIME = re.compile(r"^(\d{1,2})[.:](\d{2})$")
_HEAD_TAIL = re.compile(r"\s*Yay[ıi]n Ak[ıi][şs][ıi]\s*$", re.I)


#: Служебные слова турецкого анонса. Заголовок у TRT — это целое описание, а
#: пара стоит в самом конце: «FIFA 2026 DÜNYA KUPASI 3.LÜK MAÇI FUTBOL
#: KARŞILAŞMASI FRANSA - İNGİLTERE». Без отсечения хозяевами становится вся
#: строка. Берём то, что идёт после последнего служебного слова.
_NOISE = ("karsilasmasi", "maci", "musabakasi", "turu", "elemeleri",
          "kupasi", "ligi", "sampiyonasi", "futbol", "basketbol", "voleybol",
          "hentbol", "kadinlar", "erkekler", "final", "yari", "tur", "hafta",
          "lig", "play", "off", "rovans", "avrupa", "dunya")


#: Турецкие буквы к простой латинице. Нужно именно так, а не через lower():
#: у турок два разных «i» (İ/ı), и «KARŞILAŞMASI».lower() даёт «karşilaşmasi»
#: — со списком служебных слов оно уже не совпадает.
_TR_FOLD = str.maketrans({
    "ı": "i", "İ": "i", "I": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c", "â": "a",
})


def _fold(word: str) -> str:
    return word.translate(_TR_FOLD).lower()


def _tail_after_noise(text: str) -> str:
    """Хвост строки после последнего служебного слова — это и есть команда."""
    words = text.split()
    last = -1
    for i, w in enumerate(words):
        bare = w.strip('".,()')
        # номер тура часто слипается со словом: `5.HAFTA`, `1.TUR`. Без этого
        # он уезжал в название команды (`5.HAFTA SMS GRUP SARIYER`, 01.09)
        core = bare.lstrip("0123456789.")
        if _fold(core) in _NOISE or bare.rstrip(".").isdigit():
            last = i
    tail = " ".join(words[last + 1:]) if last >= 0 else text
    return tail.strip(' ".,') or text


#: Формы клуба, приклеенные к имени: «VAN SPOR FUTBOL KULÜBÜ», «… A.Ş.».
#: Убирать их надо ДО отсечения служебных слов — иначе «FUTBOL» внутри
#: имени клуба срезает всё до «KULÜBÜ», и командой становится само слово
#: «клуб» (поймано владельцем 02.09: «KULÜBÜ - Batman Petrol Spor»).
_CLUB_FORM = re.compile(
    r"\s*\b(?:FUTBOL\s+|SPOR\s+)?KUL[ÜU]B[ÜU]\b\.?|\s*\bA\.?Ş\.?(?=\s|$)",
    re.I)


def _pair(text: str) -> str:
    for sep in (" - ", " – ", " vs ", " VS "):
        if sep in text:
            home, _, away = text.partition(sep)
            home = _tail_after_noise(_CLUB_FORM.sub("", home).strip())
            away = _CLUB_FORM.sub("", away).strip(' ".,')
            if home and away:
                return f"{home} - {away}"
    return " "


def _league(text: str, pair: str) -> str:
    """Название турнира без самой пары и без номера тура.

    У TRT заголовок — целое предложение: «TRENDYOL 1.LİG FUTBOL KARŞILAŞMASI
    5.HAFTA SMS GRUP SARIYER - ORFA YAPI PENDİKSPOR». Если положить его в
    лигу целиком, в витрине окажется вся строка (поймано 01.09).
    """
    out = " ".join((text or "").split())
    home = (pair or " ").split(" - ")[0].strip()
    if home and home in out:
        out = out.split(home)[0]
    return re.sub(r"\s*\d+\.?\s*(?:HAFTA|TUR|HAFTASI)\s*$", "", out,
                  flags=re.I).strip(" -–—:,")


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    day = day or _date.today()
    tree = HTMLParser(html)

    out: list[Program] = []
    seen: set[tuple] = set()
    for block in tree.css("div.cont"):
        head = block.css_first("h2")
        if not head:
            continue
        channel = _HEAD_TAIL.sub("", " ".join(head.text().split())).strip()
        if not channel or (channels and channel not in channels):
            continue
        for item in block.css("div.livestream-conteiner"):
            time_node = item.css_first("span.livestream-time")
            title_node = item.css_first("span.livestream-title")
            if not time_node or not title_node:
                continue
            hm = _TIME.match(" ".join(time_node.text().split()))
            title = " ".join(title_node.text().split())
            if not hm or not title:
                continue
            key = (channel, hm.group(0), title)
            if key in seen:
                continue
            seen.add(key)
            # «Lyon - Fenerbahçe | UEFA Şampiyonlar Ligi» — пара в первом
            # куске, турнир во втором; двоеточие встречается реже
            if "|" in title:
                first, _, tail = title.partition("|")
                rest, league_text = first.strip(), tail.strip()
            else:
                head, sep, tail = title.partition(":")
                rest = tail.strip() if sep and tail.strip() else title
                league_text = head.strip() if sep and tail.strip() else title
            d = day + timedelta(days=1) if int(hm.group(1)) < 5 else day
            out.append(Program(
                channel_raw=channel, title=title,
                start=datetime(d.year, d.month, d.day,
                               int(hm.group(1)), int(hm.group(2)), tzinfo=zone),
                raw_time=hm.group(0),
                league_raw=_league(league_text, _pair(rest))[:120],
                match_raw=_pair(rest),
                source_url=url, extra={"day": d.isoformat()},
            ))
    return mark_first_show(out, "canlı")

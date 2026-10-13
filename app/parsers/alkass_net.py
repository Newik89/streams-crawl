# -*- coding: utf-8 -*-
"""alkass.net — Катар: телегид каналов Al Kass («قنوات الكأس الرياضية»).

Задание владельца 13.10.2026: «разобрать сайт и добавить расписание к нам,
всё переводить на английский, эталон — flashscore». Разведка — пробы
#257–#260 из GitHub (`dispatch --urls`).

**Что отдаёт сайт.** `https://www.alkass.net/tvguide` — обычный HTML (PHP,
защиты нет), все каналы одной страницей, ТОЛЬКО СЕГОДНЯ по часам Дохи
(`Asia/Qatar`, UTC+3 без перевода стрелок; метка «الآن» на ленте времени
сошлась с часами запроса). Вкладка «غداً» (`tvguide?day=next`, в том числе
`tvguide.php?day=next`) на 13.10 отдала ту же сегодняшнюю сетку — поэтому
источник заведён сеткой (`GRID_DOMAINS`), один запрос за обход.

**Язык.** Страница арабская, но названия передач сайт пишет ПО-АНГЛИЙСКИ:
`Doha Bank Stars League Al-Shahania vs. Lusail`, `AFC Champions League
Elite Al Sadd (Qatar) × Al Hilal (Saudi Arabia)`. Английской версии сайта
нет (`/en/tvguide` — 404; ссылка «English» ведёт на другой сайт
`alkassdigital.net`). Переводить арабский не нужно — имена приводит к
написанию эталона общая сверка с flashscore.

Разметка (мобильный блок, у него канал и строки рядом):

    div.tvguide-full-mobile
      li.has-children                         — один канал
        img[src="assets/images/one_.png"]     — канал только логотипом
        tr > td.tv-prog-name                  `Jetour League Al Khor vs Umm Salal`
             td.tv-prog-time                  `04:00`

Правила разбора по порядку:

1. Канал — по имени файла логотипа (`one_.png` → `Al Kass One`): подписи у
   канала нет, `alt` пустой. Неизвестный логотип — `Al Kass <слово>`, не
   пропускаем (каналы не отсеиваем сами). Строка «Schedule not available»
   (вкладка «online») — не передача.
2. День — `day` от обхода, иначе «сегодня» по часам Дохи (дат на странице
   нет). Время — по `daytime.walk_day`: шаг назад — уже следующие сутки.
3. Одинаковые строки (канал, время, название) сайт иногда дублирует —
   берём одну.
4. Пара — по разделителю `vs` / `vs.` / `×` / ` x ` (`_SEP`). Нет
   разделителя — строка остаётся передачей без пары (News, Golmania…).
5. Слева от пары лига и хозяева идут подряд. Граница — по порядку: серия
   из 2+ пробелов (`Elite   Al Wasl`), иначе последнее слово-окончание
   названия турнира (`_LEAGUE_END`: League, Elite, Cup, Derby, Basketball,
   ACL 2 …). Ничего не нашлось — вся левая часть — хозяева, лиги нет.
6. У стороны снимаем приписку страны, которую сайт ставит в клубных
   турнирах (`_drop_country`): `(Qatar)`, `(Iraq)`, ` of Qatar`, хвост
   ` UAE` / ` Saudi Arabia`. Страна — из словаря сборных и стран лиг
   эталона (`_countries`). Сторона целиком из страны не трогается.
7. `National Team` снимаем (сборная видна по имени страны), `U-23` пишем
   `U23` — возраст не теряем (правило проекта), пол (`Women`) не трогаем.
8. Пометки эфира у сайта нет вовсе: эфир угадывается первым показом пары
   (`mark_first_show`), домен в `REPEAT_GUESS_DOMAINS`. Угаданный эфир без
   пары во flashscore в ±3 ч `scripts/parse_live.py` снимает как запись —
   у Al Kass это большая часть сетки (повторы матчей прошлых дней).
"""

from __future__ import annotations

import json
import re
from datetime import date as _date
from functools import lru_cache
from pathlib import Path

from selectolax.parser import HTMLParser

from .. import daytime, names
from . import Program, mark_first_show, register

DOMAIN = "alkass.net"
TZ = "Asia/Qatar"

#: правило 1: слово из имени файла логотипа → имя канала
_LOGO_RE = re.compile(r"/([a-z0-9]+)_?\.(?:png|jpe?g|svg|webp)$", re.I)
_LOGO_NAMES = {"one": "One", "two": "Two", "three": "Three", "four": "Four",
               "five": "Five", "six": "Six", "seven": "Seven",
               "eight": "Eight", "nine": "Nine", "ten": "Ten",
               "online": "Online"}
_NO_SCHEDULE = "schedule not available"

_HHMM = re.compile(r"^\d{1,2}:\d{2}$")

#: правило 4: разделитель пары
_SEP = re.compile(r"\s+(?:vs\.?|×|x)\s+", re.I)

#: правило 5: серия пробелов и слова, которыми кончается название турнира
_GAP = re.compile(r"\s{2,}")
_LEAGUE_END = re.compile(
    r"\b(?:ACL\s*2|ACL|League|Elite|Cup|Derby|Basketball|Championship|"
    r"Trophy|Shield|Liga|Ligue|Supercup|Final|Friendly)\b", re.I)

#: правило 7
_NATIONAL = re.compile(r"\s+national\s+team\b", re.I)
_AGE_DASH = re.compile(r"\bU-(\d{2})\b", re.I)

#: правило 6: что не страна, хоть и стоит перед двоеточием лиги эталона
_NOT_COUNTRY = {"WORLD", "EUROPE", "ASIA", "AFRICA", "SOUTH AMERICA",
                "NORTH & CENTRAL AMERICA", "AUSTRALIA & OCEANIA",
                "TENNIS", "BASKETBALL"}
_TAIL_PAREN = re.compile(r"\s*\(([^()]{2,40})\)\s*$")
_TAIL_OF = re.compile(r"\s+of\s+([A-Za-z][A-Za-z .&'-]{1,40})$", re.I)
_CODE = re.compile(r"^[A-Za-z]{2,3}$")


@lru_cache(maxsize=1)
def _countries() -> frozenset[str]:
    """Страны капсом: из лиг эталона (`QATAR: Stars League` → QATAR) в
    `data/dictionaries.json`. Сборные из `aliases.json` проверяет
    `names.is_country` — вместе они покрывают и UAE, и Uzbekistan."""
    path = Path(__file__).resolve().parent.parent.parent / "data" / "dictionaries.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    out = set()
    for league in raw.get("leagues") or []:
        head, colon, _ = (league.get("name") or "").partition(":")
        head = head.strip().upper()
        if colon and head and "-" not in head and head not in _NOT_COUNTRY:
            out.add(head)
    return frozenset(out)


def _is_country(text: str) -> bool:
    text = " ".join(text.split())
    return bool(text) and (text.upper() in _countries() or names.is_country(text))


def _drop_country(side: str) -> str:
    """Правило 6: приписка страны у клуба. Сторона, которая сама страна
    (`Qatar U23`, `Saudi Arabia`), остаётся как есть."""
    side = " ".join(side.split())
    got = _TAIL_PAREN.search(side)
    if got and (_is_country(got.group(1)) or _CODE.match(got.group(1))):
        rest = side[:got.start()].strip()
        if rest:
            return rest
    got = _TAIL_OF.search(side)
    if got and _is_country(got.group(1)):
        rest = side[:got.start()].strip()
        if rest:
            return rest
    words = side.split()
    for n in (3, 2, 1):                       # длинный хвост — первым
        if len(words) > n and _is_country(" ".join(words[-n:])):
            return " ".join(words[:-n])
    return side


def _side(text: str) -> str:
    """Правила 6–7 для одной стороны пары."""
    text = _NATIONAL.sub("", text)
    text = _AGE_DASH.sub(lambda m: f"U{m.group(1)}", text)
    return _drop_country(text).strip(" .-")


def split_title(title: str) -> tuple[str, str]:
    """Название передачи → (лига, «Хозяева - Гости»). Пары нет — («», « »)."""
    parts = _SEP.split(title, maxsplit=1)
    if len(parts) != 2:
        return "", " "
    left, away = parts[0].rstrip(), parts[1].strip()
    league, home = "", left.strip()
    gaps = list(_GAP.finditer(left.strip()))
    if gaps:
        cut = gaps[-1]
        league, home = left.strip()[:cut.start()], left.strip()[cut.end():]
    else:
        ends = [m for m in _LEAGUE_END.finditer(left) if left[m.end():].strip()]
        if ends:
            league, home = left[:ends[-1].end()], left[ends[-1].end():]
    home, away = _side(home), _side(away)
    if len(home) < 2 or len(away) < 2:
        return "", " "
    return " ".join(league.split()), f"{home} - {away}"


def channel_name(src: str) -> str:
    """Правило 1: `assets/images/five_.png` → `Al Kass Five`."""
    got = _LOGO_RE.search(src or "")
    if not got:
        return ""
    word = got.group(1).lower()
    return f"Al Kass {_LOGO_NAMES.get(word, word.title())}"


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = tz or TZ
    page_day = day or daytime.today(zone)
    tree = HTMLParser(html)
    block = tree.css_first("div.tvguide-full-mobile")
    if block is None:
        return []
    out: list[Program] = []
    for item in block.css("li.has-children"):
        logo = item.css_first("img")
        channel = channel_name(logo.attributes.get("src") if logo else "")
        if not channel or (channels and channel not in channels):
            continue
        rows, seen = [], set()
        for tr in item.css("tr"):
            name_td = tr.css_first("td.tv-prog-name")
            time_td = tr.css_first("td.tv-prog-time")
            if name_td is None or time_td is None:
                continue
            title = " ".join(name_td.text().split())
            raw = time_td.text(strip=True)
            if not title or title.lower() == _NO_SCHEDULE \
                    or not _HHMM.match(raw):
                continue
            if (raw, title) in seen:                # правило 3
                continue
            seen.add((raw, title))
            rows.append((raw, title))
        starts = daytime.walk_day([r for r, _ in rows], page_day, zone)
        for (raw, title), start in zip(rows, starts):
            if start is None:
                continue
            league, pair = split_title(title)
            out.append(Program(
                channel_raw=channel, title=title, start=start, raw_time=raw,
                league_raw=league[:120], match_raw=pair, source_url=url,
                extra={"day": page_day.isoformat()},
            ))
    return mark_first_show(out, "live")

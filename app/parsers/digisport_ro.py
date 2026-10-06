# -*- coding: utf-8 -*-
"""digisport.ro — Румыния; Digi Sport 1–4, неделя вперёд одной страницей.

Адрес на канал: `/program-tv/digisport-1` … `-4`, даты в адресе нет — страница
сама держит семь дней, ровно то окно, которое нам нужно (сегодня и ещё шесть).
Четыре запроса на всю неделю по всем четырём каналам.

Разметка — обычные таблицы, по одной на день:

    h3                       `Luni 31 August` — заголовок дня
    table > tbody > tr
      td.schedule-icon[data-schedule]  вид передачи: `superliga`, `stiri`…
      td                                `21:30`
      td                                `<span class="tag">LIVE</span> CFR Cluj - FCSB<br>Etapa 11`

Под `<br>` — подпись: стадия (`Etapa 11`, `Grupe`) или турнир (`FIBA
Masculin Europe Cup`). Она идёт в лигу и описание, не в пару (`_cell`).

`data-schedule` — подсказка сайта, что за передача: `stiri` (новости),
`superliga`, `la liga`, `fotbal european`. Кладём её в лигу — по ней вид
спорта определяется даже там, где в заголовке одна пара команд.

`<span class="tag">…</span>` — ОДНА пометка перед заголовком, и сайт кладёт
туда что сочтёт важнее (разбор 06.10):

* `LIVE` / `Live` — прямой эфир;
* `Premiera` — первый показ записи (обзор, магазин) — не эфир;
* пусто — обычная строка сетки, не эфир;
* что угодно другое — `Etapa 4`, `Liga Florilor`, `Cupa Mondiala`: название
  тура или турнира ВЫТЕСНИЛО `LIVE`. На 30.09 матчи Лиги наций 06.10 стояли
  с `LIVE`, с 01.10 у них `etapa 4` — и у прямого эфира 21:40, и у повторов
  22:45 и 04:00; три канала Digi у #4215/#4221/#4223 пропали с витрины. Эфир
  такой строки неизвестен: его получает первый показ пары
  (`mark_first_show`), а `parse_live.py` сверяет угаданный эфир с эталоном —
  ночной повтор вчерашнего матча туда не пройдёт.

День на странице — телевизионный, 06:00 → 06:00: строки после полуночи под
заголовком `Marți 06 Octombrie` идут уже 07.10 (`daytime.walk_day`).
"""

from __future__ import annotations

import re
from datetime import date as _date

from selectolax.parser import HTMLParser

from .. import daytime
from . import Program, mark_first_show, register

DOMAIN = "digisport.ro"
TZ = "Europe/Bucharest"

#: румынские месяцы в заголовках дней (`Luni 31 August`)
_MONTHS = {"ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
           "mai": 5, "iunie": 6, "iulie": 7, "august": 8, "septembrie": 9,
           "octombrie": 10, "noiembrie": 11, "decembrie": 12}

_DAY_HEAD = re.compile(r"(\d{1,2})\s+([A-Za-zăâîșşţț]+)", re.I)
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_CHANNEL = re.compile(r"digisport-(\d)")
#: пометка прямого эфира и пометка «не эфир» (шапка модуля)
_LIVE_TAG = re.compile(r"\blive\b", re.I)
_NOT_LIVE_TAG = re.compile(r"^premier", re.I)


#: Хвост стадии турнира сайт приклеивает к имени гостей БЕЗ пробела:
#: `Superliga: Rapid-Universitatea CraiovaEtapa 7`. Снимаем до разбора пары,
#: иначе «Крайова» навсегда останется «CraiovaEtapa 7». Хвостов бывает
#: несколько через запятую (`Real Madrid-InterGrupe, etapa 1` — «группы,
#: тур 1»), поэтому снимаем их цепочкой, а не по одному (поймано 06.09).
_STAGE_TAIL = re.compile(
    r"(?:(?:Etapa\s*\d+|Grupe|Optimi|Sferturi|Semifinale|Finala|Play-?off|"
    r"Turul\s*\w+|Manșa\s*\w+)[\s,]*)+$", re.I)


def _cell(td) -> tuple[str, str, str]:
    """Ячейка передачи → (пометка, заголовок, подпись).

    Разметка: `<span class="tag"> Etapa 1 </span> Baschet: CSM CSU
    Oradea-Fribourg Olympic<br>FIBA Masculin Europe Cup`. Подпись под `<br>` —
    турнир или стадия. Сплошной текст ячейки (`td.text()`) склеивает её с
    гостями без пробела: «Fribourg OlympicFIBA Masculin Europe Cup»,
    «NorvegiaCupa Mondiala» (самопроверка #205, 06.10) — поэтому идём по
    детям ячейки и режем по `<br>`."""
    mark = ""
    parts: list[list[str]] = [[]]
    for child in td.iter(include_text=True):
        if child.tag == "br":
            parts.append([])
        elif child.tag == "span" and "tag" in (child.attributes.get("class") or "").split():
            mark = child.text(strip=True)
        else:
            parts[-1].append(child.text())
    title = " ".join(" ".join(parts[0]).split())
    note = " ".join(" ".join(" ".join(p) for p in parts[1:]).split())
    return mark, title, note


def _pair(text: str) -> str:
    text = _STAGE_TAIL.sub("", text).strip()
    for sep in (" - ", " – ", " vs ", " VS "):
        if sep in text:
            home, _, away = text.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    # у Digi дефис стоит без пробелов: `Rapid-Universitatea Craiova`
    for sep in ("-", "–"):
        if sep in text:
            home, _, away = text.partition(sep)
            home, away = home.strip(), away.strip()
            if home and away and (" " in home or " " in away
                                  or (len(home) > 3 and len(away) > 3)):
                return f"{home} - {away}"
            break
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    got = _CHANNEL.search(url or "")
    channel = f"Digi Sport {got.group(1)}" if got else "Digi Sport"
    if channels and channel not in channels:
        return []
    today = day or daytime.today(tz or TZ)
    tree = HTMLParser(html)

    # строки по телевизионным суткам: (день заголовка, [(время, вид, пометка,
    # заголовок)])
    days: list[tuple[_date, list[tuple[str, str, str, str]]]] = []
    for node in tree.root.traverse():
        if node.tag == "h3":
            head = _DAY_HEAD.search(" ".join(node.text().split()))
            month = _MONTHS.get(head.group(2).lower()) if head else None
            if head and month:
                # года на странице нет: он тот же, что у сегодняшнего дня,
                # а на переходе через Новый год — следующий
                year = today.year + (1 if month < today.month else 0)
                days.append((_date(year, month, int(head.group(1))), []))
            continue
        if node.tag != "tr" or not days:
            continue
        cells = node.css("td")
        if len(cells) < 3:
            continue
        hm = _HHMM.match(cells[1].text(strip=True))
        if not hm:
            continue
        mark, title, note = _cell(cells[2])
        if title:
            days[-1][1].append((hm.group(0),
                                (cells[0].attributes.get("data-schedule") or "").strip(),
                                mark, title, note))

    out: list[Program] = []
    unknown: list[Program] = []          # пометку вытеснило имя тура — эфир неизвестен
    for current, rows in days:
        moments = daytime.walk_day([r[0] for r in rows], current, tz or TZ)
        for (raw_time, kind, mark, title, note), moment in zip(rows, moments):
            if moment is None:
                continue
            # `Superliga: Rapid-Universitatea Craiova` — лига до двоеточия,
            # пара после; двоеточия нет — пару ищем во всём заголовке.
            # Подпись под заголовком (`FIBA Masculin Europe Cup`, `Cupa
            # Mondiala, Play-off`) — турнир: в лигу, к паре она не относится
            head, sep, rest = title.partition(":")
            league = f"{kind} {head.strip()}".strip() if sep and rest.strip() else kind
            if note and not _STAGE_TAIL.fullmatch(note):
                league = f"{league} {note}".strip()
            pair = _pair(rest) if sep and rest.strip() else _pair(title)
            program = Program(
                channel_raw=channel, title=title, start=moment,
                raw_time=raw_time, description=note, league_raw=league[:120],
                live_raw="live" if _LIVE_TAG.search(mark) else "",
                match_raw=pair, source_url=url,
                extra={"day": moment.date().isoformat()})
            out.append(program)
            if mark and not _LIVE_TAG.search(mark) \
                    and not _NOT_LIVE_TAG.match(mark):
                unknown.append(program)
    for program in mark_first_show(unknown, "live"):
        if program.live_raw:
            # эфир угадан, а не помечен сайтом — `parse_live.guessed`
            program.extra["live_guess"] = True
    return out

# -*- coding: utf-8 -*-
"""ТРЕТИЙ ЗАХОД — ЧИТАЛКИ: запасной путь для сайта, который блокирует GitHub
(книга 116, слово владельца 13.11.2026).

Цепочка владельца: «GitHub → повтор → читалки → сервер». Сервер — последний
ход, его адрес бережём. Поэтому между отказом GitHub и сервером страницу
пробуют открытые читалки (`app/fetch.py`, `READERS`) — публичные сервисы,
которые отдают разметку чужой страницы. Капчу не обходим, адрес не
подделываем.

Правила по порядку (что случилось → что делаем):

Ч1. Читалки идут ПОСЛЕ второго захода и только по страницам, которые так и
    не открылись (`crawl_fetch.py`, главный ход).
Ч2. Только когда сайт БЛОКИРУЕТ: заглушка защиты, 403, 429 (класс `ban`,
    `redo.row_class`). Сайт лежит (5xx, таймаут, нет связи) — читалки не
    трогаем: лежащему сайту они не помогут, его добирает дозабор.
Ч3. Только обычная страница по адресу. Форму (POST) и страницу с разогревом
    читалка повторить не может — пропускаем.
Ч4. Зеркала эталона (языковые версии flashscore) через читалки не берём;
    основной эталон — можно (слово владельца: «читалки — только для
    основных страниц»).
Ч5. МАССОВЫЙ СБОЙ: не дались больше `MASS_SHARE` сайтов сбора (тот же порог,
    что «провал» обхода) — это сеть GitHub, а не сайты: читалки не трогаем.
Ч6. По сайту: сперва ОДНА страница через читалки по очереди. Страница
    засчитана, только если разбор этого сайта нашёл на ней хоть одну строку
    (`parser_rows`): читалка на отказ часто отвечает бодрым «200» с
    пустышкой или чужой заглушкой.
Ч7. Читалка, взявшая первую страницу, качает остальные страницы сайта —
    другие читалки для него уже не перебираем.
Ч8. Потолок `SITE_SECONDS` (5 минут) на сайт и `MAX_SITES` сайтов за сбор:
    читалки медленные, сбор из-за них не должен встать.
Ч9. Открывшаяся страница переписывает свою строку отчёта: «расписание
    есть», в «почему» — «(через читалку <имя>)», в «чем» — `reader:<имя>`.
    Сайт, взятый читалкой, сервер считает собранным — на сервер он не едет.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from datetime import date
from typing import Callable

from . import redo

#: Ч5: доля сайтов без единой открывшейся страницы, выше которой сбой массовый
MASS_SHARE = 0.20
#: Ч5: при скольких сайтах в сборе долю уже считаем
MASS_MIN_SITES = 10
#: Ч8: потолок секунд на один сайт и сайтов за один сбор
SITE_SECONDS = 300
MAX_SITES = 8
#: Ч9: приписка в строке отчёта
NOTE = "(через читалку {name})"

BROKEN = ("не открылась", "заглушка защиты")


def _bare(domain: str) -> str:
    return (domain or "").lower().removeprefix("www.")


def is_mirror(domain: str) -> bool:
    """Ч4: языковое зеркало эталона (`flashscore_mobi.LOCALES`)."""
    from .parsers import flashscore_mobi
    return _bare(domain) in {_bare(d) for d in flashscore_mobi.LOCALES}


def eligible(job: dict, row: dict) -> bool:
    """Ч2–Ч4: эту страницу стоит пробовать читалкой."""
    if redo.row_class(row) != "ban":                              # Ч2
        return False
    if job.get("post") or job.get("post_json") or job.get("warmup"):   # Ч3
        return False
    return not is_mirror(job.get("domain") or "")                 # Ч4


def is_mass(report: list[dict]) -> bool:
    """Ч5: в сборе не дались больше `MASS_SHARE` сайтов."""
    sites: dict[str, bool] = {}
    for row in report:
        site = _bare(row.get("domain") or "")
        if site:
            sites[site] = sites.get(site, False) or row.get("итог") not in BROKEN
    if len(sites) < MASS_MIN_SITES:
        return False
    failed = sum(1 for opened in sites.values() if not opened)
    return failed > len(sites) * MASS_SHARE


def by_site(items: list[dict]) -> "OrderedDict[str, list[dict]]":
    """Упавшие страницы (`{"job", "row"}`), сложенные по сайтам, в порядке
    обхода; берём только годные (`eligible`)."""
    out: OrderedDict[str, list[dict]] = OrderedDict()
    for item in items:
        if eligible(item["job"], item["row"]):
            out.setdefault(_bare(item["job"]["domain"]), []).append(item)
    return out


def parser_rows(job: dict, html: str, setting: dict | None = None) -> int | None:
    """Ч6: сколько строк разбор сайта нашёл на странице. None — у сайта нет
    своего разбора (судить нечем). Упавший разбор — 0 строк."""
    from .parsers import get as parser_for
    setting = setting or {}
    parse = parser_for(job.get("domain") or "", setting.get("parser") or "")
    if parse is None:
        return None
    day = None
    if job.get("day"):
        try:
            day = date.fromisoformat(str(job["day"]))
        except ValueError:
            day = None
    try:
        return len(parse(html, day=day, tz=setting.get("tz"),
                         url=job.get("url") or ""))
    except Exception:                               # noqa: BLE001
        return 0


def run(items: list[dict], report: list[dict], take: Callable,
        settings: dict | None = None, clock: Callable = time.monotonic,
        say: Callable = print) -> dict:
    """Третий заход. `items` — страницы, не открывшиеся и со второго захода
    (`{"job", "row"}`); `report` — все строки сбора (для Ч5);
    `take(job, accept, only)` — взять страницу читалкой: возвращает
    `(page, verdict_row, reader)`, где `reader` — читалка, отдавшая страницу
    (для Ч7), а `accept(html)` решает, годится ли выдача (Ч6).
    Строки отчёта правит на месте. Возвращает итог:
    `{"сайтов": …, "взято": {сайт: [читалка, страниц]}, "не_взято": [...],
      "пропуск": причина}`."""
    settings = settings or {}
    итог = {"сайтов": 0, "взято": {}, "не_взято": [], "пропуск": ""}
    sites = by_site(items)
    if not sites:
        return итог
    if is_mass(report):                                           # Ч5
        итог["пропуск"] = "массовый сбой — читалки не трогаем"
        say(f"читалки: {итог['пропуск']}")
        return итог
    for n, (site, pages) in enumerate(sites.items()):
        if n >= MAX_SITES:                                        # Ч8
            итог["не_взято"].append(f"{site}: сверх {MAX_SITES} сайтов за сбор")
            continue
        итог["сайтов"] += 1
        started = clock()
        setting = settings.get(site) or settings.get(f"www.{site}") or {}
        reader, healed, имя = None, 0, ""
        for item in pages:
            if clock() - started > SITE_SECONDS:                  # Ч8
                say(f"читалки: {site} — потолок {SITE_SECONDS} с, остальное "
                    "добирает дозабор")
                break
            job = item["job"]

            def accept(html: str, job=job) -> bool:               # Ч6
                rows = parser_rows(job, html, setting)
                return rows is None or rows > 0

            page, fresh, used = take(job, accept, reader)
            if not getattr(page, "ok", False) or fresh.get("итог") in BROKEN:
                if reader is None:      # первую страницу не взял никто (Ч6)
                    break
                continue
            reader = reader or used                               # Ч7
            name = (getattr(page, "via", "") or "").removeprefix("reader:")
            имя = имя or name
            fresh["почему"] = ((fresh.get("почему") or "") + " "
                               + NOTE.format(name=name)).strip()  # Ч9
            item["row"].clear()
            item["row"].update(fresh)
            healed += 1
        if healed:
            итог["взято"][site] = [имя or "читалка", healed, len(pages)]
            say(f"читалки: {site} — взято {healed} из {len(pages)} страниц")
        else:
            итог["не_взято"].append(f"{site}: ни одна читалка не отдала "
                                    "страницу с расписанием")
            say(f"читалки: {site} — не взяла ни одна")
    return итог

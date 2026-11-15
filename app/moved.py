"""Ход «сайт переехал» (книга 126, этап 4 плана «сайт не перестаёт
разбираться», слова владельца 14.11: «а на такой случай разработать можем
ход?»).

Случай: сайт перенёс расписание на другой адрес. По старому адресу — «такой
страницы нет» (HTTP 404 / 410), и раньше сайт просто выпадал из сбора, пока
это не заметит человек.

ПРАВИЛА (что случилось → что делаем):
  А1. Сайт «переехал»: ВСЕ его страницы в сборе не открылись, и у каждой
      причина — «страницы нет» (HTTP 404 или 410). Хоть одна страница
      открылась или причина другая (защита, 5xx, сеть) — это не переезд:
      этим заняты читалки и цепочка сбоев.
  А2. Массовый сбой сбора (`reader_chain.is_mass`) — никого не ищем: беда не
      в сайтах. Страницы с формой (POST) и зеркала эталона не трогаем.
  А3. Ищем новый адрес на ГЛАВНОЙ странице сайта: ссылки того же сайта, в
      адресе или подписи которых есть слово «программа / расписание» —
      на любом из языков наших сайтов и по-английски (`WORDS`). Чем больше
      таких слов и чем короче адрес, тем выше кандидат.
  А4. Пробуем не больше `CANDIDATES` кандидатов. Кандидат принят, только
      если СВОЙ разборщик сайта прочитал на нём строки расписания
      (`reader_chain.parser_rows` > 0). Первый принятый — новый адрес.
  А5. Найденная страница дописывается в отчёт сбора отдельной строкой
      («расписание есть», пометка «новый адрес»): разбор возьмёт её как
      обычную. Строки старого адреса остаются как свидетельство.
  А6. Пределы: не больше `MAX_SITES` сайтов за сбор — у каждого главная
      страница и до `CANDIDATES` кандидатов; лишние сайты ждут следующего
      сбора. К сайту ходим как можно меньше.
  А7. Итог — раздел `REPORT_KEY` отчёта сбора; сервер пишет владельцу ОДНУ
      строку на сайт в сутки (`after_import`): «сайт переехал: был такой
      адрес, стал такой» либо «по старому адресу страниц нет, новый не
      найден». Постоянно адрес в плане обхода ход НЕ меняет: это решение —
      за владельцем, а до него ход повторяется в каждом сборе.
"""
from __future__ import annotations

import html as _html
import json
import re
from urllib.parse import urljoin, urlsplit

from . import reader_chain

#: раздел отчёта сбора (report.json)
REPORT_KEY = "переезд"
#: А6: сайтов за сбор и кандидатов на сайт
MAX_SITES = 3
CANDIDATES = 3
#: пометка строки отчёта и поле «чем»
NOTE = "новый адрес (по прежнему страницы нет: {old})"
VIA = "переезд"
BROKEN = reader_chain.BROKEN
#: А1: причина «страницы нет»
_GONE = re.compile(r"\bHTTP (404|410)\b")
#: А3: слова «программа / расписание / ТВ-гид» в адресах и подписях ссылок —
#: на языках наших сайтов и по-английски. Сравнение — по вхождению, без регистра
WORDS = (
    "schedule", "tv-guide", "tvguide", "tv_guide", "guide", "epg", "listings", "whats-on",
    "program", "programm", "programme", "programa", "programma", "programação", "programacao",
    "programación", "programacion", "program-tv", "tv-program", "programtv",
    "raspored", "rozklad", "rozkład", "ramowka", "ramówka", "spored",
    "sendeplan", "sendungen", "spielplan", "palinsesto", "guida", "grille", "grila", "orar",
    "tablå", "tabla", "ohjelma", "műsor", "musor", "saatekava", "tvkava", "programos",
    "yayin", "yayın", "akis", "akış", "skema",
    "програм", "расписан", "розклад", "телепрограм", "телегид", "распоред", "πρόγραμμα",
)
_LINK = re.compile(r"""(?is)<a\b[^>]*?href\s*=\s*["']([^"'#]+)["'][^>]*>(.*?)</a>""")
_TAG = re.compile(r"<[^>]+>")
NOTED_KEY = "moved_noted"
WHO = "ход «сайт переехал»"


def bare(domain: str) -> str:
    domain = (domain or "").lower()
    return domain[4:] if domain.startswith("www.") else domain


def gone(row: dict) -> bool:
    """А1: строка отчёта — «страницы нет» (не открылась, HTTP 404 / 410)."""
    return (isinstance(row, dict) and row.get("итог") in BROKEN
            and bool(_GONE.search(str(row.get("почему") or ""))))


def moved_sites(report: list) -> dict[str, list[dict]]:
    """А1–А2: {сайт: его строки} — сайты, у которых ВСЕ страницы «страницы
    нет». Формы (POST) и зеркала эталона не берём."""
    by_site: dict[str, list[dict]] = {}
    for row in report or []:
        if isinstance(row, dict) and row.get("domain"):
            by_site.setdefault(bare(row["domain"]), []).append(row)
    out = {}
    for site, rows in by_site.items():
        if not all(gone(r) for r in rows):
            continue
        if any(r.get("post") or r.get("post_json") or r.get("warmup") for r in rows):
            continue
        if reader_chain.is_mirror(site):
            continue
        out[site] = rows
    return out


_WORD = re.compile(r"[^\W\d_]{4,}")


def links(page: str, home: str, site: str, skip: set[str], hint: str = "") -> list[str]:
    """А3: кандидаты нового адреса с главной страницы, лучшие — первыми.
    `hint` — прежний адрес: кандидат, в пути которого есть слова прежнего
    пути (от четырёх букв), стоит выше. Случай mojtv.hr 15.11 (книга 127):
    был `/tv-program/-2/sportski/<дата>.aspx`, стал `/tv-program/sportski` —
    без подсказки первыми шли `/tv-program/`, `/tv-program/bih`,
    `/tv-program/srpski`, и до спортивного раздела очередь не дошла."""
    old_words = set(_WORD.findall(urlsplit(hint).path.lower())) if hint else set()
    found: dict[str, tuple] = {}
    for href, inner in _LINK.findall(page or ""):
        url = urljoin(home, _html.unescape(href).strip())
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or bare(parts.netloc) != site and \
                not bare(parts.netloc).endswith("." + site):
            continue
        if url in skip or url.rstrip("/") == home.rstrip("/"):
            continue
        text = (parts.path + "?" + parts.query + " " + _TAG.sub(" ", _html.unescape(inner))).lower()
        hits = sum(1 for word in WORDS if word in text)
        same = len(old_words & set(_WORD.findall(parts.path.lower())))
        if hits and url not in found:
            found[url] = (-same, -hits, len(url))
    return [url for url, _ in sorted(found.items(), key=lambda kv: kv[1])][:CANDIDATES]


def run(report: list, take, job_of, settings: dict | None = None, say=print) -> dict:
    """А1–А7. `take(job) -> (page, fresh_row)` — скачать адрес (у `page` —
    `.ok` и `.html`; открывшуюся страницу `take` сам сохраняет на диск и
    ставит строке «файл»); `job_of(row)` — задание обхода из строки отчёта
    (`redo.job_of`); `settings` — {сайт: {parser, tz}}. Найденные страницы
    дописывает в `report`. Возвращает раздел отчёта."""
    итог = {"найдено": {}, "не_найдено": [], "ждут": []}
    sites = moved_sites(report)
    if not sites or reader_chain.is_mass(report):
        return итог
    settings = settings or {}
    for n, (site, rows) in enumerate(sites.items()):
        if n >= MAX_SITES:                                           # А6
            итог["ждут"].append(site)
            continue
        setting = settings.get(site) or settings.get("www." + site) or {}
        base = job_of(rows[0])
        old = base.get("url") or ""
        home = f"{urlsplit(old).scheme or 'https'}://{urlsplit(old).netloc}/"
        page, _ = take({**base, "url": home, "browser": False})
        new_row = None
        if getattr(page, "ok", False):
            skip = {str(r.get("url") or "") for r in rows}
            for url in links(page.html, home, site, skip, hint=old):   # А3
                job = {**base, "url": url}
                candidate, fresh = take(job)
                if not getattr(candidate, "ok", False) or fresh.get("итог") in BROKEN:
                    continue
                got = reader_chain.parser_rows(job, candidate.html, setting)
                if got:                                              # А4
                    fresh["почему"] = NOTE.format(old=old)
                    fresh["чем"] = VIA
                    new_row = (fresh, got)
                    break
        if new_row is None:
            итог["не_найдено"].append(site)
            say(f"   {site}: по прежнему адресу страницы нет, новый адрес не найден")
            continue
        report.append(new_row[0])                                    # А5
        итог["найдено"][site] = {"был": old, "стал": new_row[0]["url"], "строк": new_row[1]}
        say(f"   {site}: сайт переехал — новый адрес {new_row[0]['url']}, "
            f"строк расписания {new_row[1]}")
    return итог


def words(section: dict) -> dict[str, str]:
    """А7: {сайт: строка уведомления}."""
    out = {}
    for site, rec in sorted(((section or {}).get("найдено") or {}).items()):
        out[site] = (f"{site}: сайт перенёс расписание. Был адрес {rec.get('был')}, стал "
                     f"{rec.get('стал')} — найден на главной странице, свой разборщик прочитал "
                     f"на нём {rec.get('строк')} строк. В этом сборе сайт взят по новому адресу; "
                     f"чтобы адрес закрепился, его нужно сменить в списке источников")
    for site in sorted((section or {}).get("не_найдено") or []):
        out[site] = (f"{site}: по прежнему адресу расписания страниц нет (сайт отвечает «нет "
                     f"такой страницы»), новый адрес на главной странице не найден. Сайт в сбор "
                     f"не попал — нужен новый адрес")
    return out


def after_import(conn, report: dict, today: str) -> list[str]:
    """А7 на сервере: строка в «Прогоны» — одна на сайт в сутки."""
    from . import db, watch
    lines = words((report or {}).get(REPORT_KEY) or {})
    if not lines:
        return []
    try:
        noted = json.loads(db.get_setting(conn, NOTED_KEY) or "{}")
    except ValueError:
        noted = {}
    said = []
    for site, line in lines.items():
        if noted.get(site) == today:
            continue
        watch.note(conn, line, who=WHO)
        noted[site] = today
        said.append(line)
    if said:
        db.set_setting(conn, NOTED_KEY, json.dumps(noted, ensure_ascii=False))
    return said

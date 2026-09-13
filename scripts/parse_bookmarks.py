# -*- coding: utf-8 -*-
"""Разбор экспорта закладок Opera в таблицу источников.

Вход:  data/bookmarks_*.html  (формат NETSCAPE-Bookmark-file-1)
Выход: recon/sources.csv   — источники, схлопнутые по домену
       recon/excluded.csv  — что выброшено и почему

Повторный запуск НЕ затирает разведку: если recon/sources.csv уже есть,
его строки читаются и переносятся в новый файл. У известных доменов
обновляется только список ссылок; имя, страна, пояс и колонки разведки
остаются как были — их могли править руками.

Запуск:
    python scripts/parse_bookmarks.py
"""

from __future__ import annotations

import csv
import html
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RECON = ROOT / "recon"

# --- что выбрасываем ---------------------------------------------------------

# по решению владельца: агрегатор результатов, не ТВ-расписание
EXCLUDED_DOMAINS = {
    "flashscore.com": "исключено владельцем",
    # проверены владельцем вручную и убраны 29.08.2026. Ссылки на них остались
    # в закладках, поэтому домены перечислены здесь — иначе каждый новый
    # экспорт возвращал бы их обратно. Разведка не потеряна: она лежит в
    # recon/removed_by_owner.csv, вернуть сайт можно в любой момент.
    "2plus2.ua": "удалено владельцем 29.08.2026",
    "cbcsport.az": "удалено владельцем 29.08.2026",
    "sky.at": "удалено владельцем 29.08.2026",
    "sky.de": "удалено владельцем 29.08.2026",
    "sport5.cz": "удалено владельцем 29.08.2026",
    "xsport.ua": "удалено владельцем 29.08.2026",
}

# магазины, реклама, служебные страницы — к ТВ-расписаниям отношения не имеют
JUNK_DOMAINS = {
    "temu.com", "aliexpress.com", "airbnb.de", "rewe.de", "hero-wars.com",
    "yandex.fr",
}

JUNK_SCHEMES = {"chrome", "opera", "about", "javascript", "file"}

# --- страна и часовой пояс ---------------------------------------------------

# ccTLD → (страна, часовой пояс)
TLD_MAP = {
    "ua": ("UA", "Europe/Kyiv"),
    "bg": ("BG", "Europe/Sofia"),
    "cz": ("CZ", "Europe/Prague"),
    "sk": ("SK", "Europe/Bratislava"),
    "pl": ("PL", "Europe/Warsaw"),
    "hu": ("HU", "Europe/Budapest"),
    "ro": ("RO", "Europe/Bucharest"),
    "rs": ("RS", "Europe/Belgrade"),
    "hr": ("HR", "Europe/Zagreb"),
    "si": ("SI", "Europe/Ljubljana"),
    "ba": ("BA", "Europe/Sarajevo"),
    "al": ("AL", "Europe/Tirane"),
    "gr": ("GR", "Europe/Athens"),
    "tr": ("TR", "Europe/Istanbul"),
    "az": ("AZ", "Asia/Baku"),
    "kz": ("KZ", "Asia/Almaty"),
    "ru": ("RU", "Europe/Moscow"),
    "pt": ("PT", "Europe/Lisbon"),
    "es": ("ES", "Europe/Madrid"),
    "it": ("IT", "Europe/Rome"),
    "fr": ("FR", "Europe/Paris"),
    "de": ("DE", "Europe/Berlin"),
    "at": ("AT", "Europe/Vienna"),
    "ch": ("CH", "Europe/Zurich"),
    "nl": ("NL", "Europe/Amsterdam"),
    "be": ("BE", "Europe/Brussels"),
    "dk": ("DK", "Europe/Copenhagen"),
    "no": ("NO", "Europe/Oslo"),
    "se": ("SE", "Europe/Stockholm"),
    "fi": ("FI", "Europe/Helsinki"),
    "ee": ("EE", "Europe/Tallinn"),
    "ie": ("IE", "Europe/Dublin"),
    "uk": ("UK", "Europe/London"),
    "cy": ("CY", "Asia/Nicosia"),
    "ca": ("CA", "America/Toronto"),
    "au": ("AU", "Australia/Sydney"),
}

# домены без ccTLD (.com/.tv/.live) — страна известна вручную
MANUAL_MAP = {
    "tvarenasport.com": ("RS", "Europe/Belgrade"),
    "beinsports.com": ("QA", "Asia/Qatar"),
    "sporteventz.com": ("INT", "UTC"),
    "livesoccertv.com": ("INT", "UTC"),
    "liveonsat.com": ("INT", "UTC"),
    "dagenstv.com": ("SE", "Europe/Stockholm"),
    "vsetv.com": ("RU", "Europe/Moscow"),
    "ntvplus.tv": ("RU", "Europe/Moscow"),
    "maxsport.live": ("BG", "Europe/Sofia"),
    "tvguidetonight.com.au": ("AU", "Australia/Sydney"),
    "movistarplus.es": ("ES", "Europe/Madrid"),
    "programme-tv.net": ("FR", "Europe/Paris"),
    "tsn.ca": ("CA", "America/Toronto"),
    "skysports.com": ("UK", "Europe/London"),
    "tntsports.co.uk": ("UK", "Europe/London"),
    "bbc.co.uk": ("UK", "Europe/London"),
    "poverkhnost.tv": ("UA", "Europe/Kyiv"),
    "unian.tv": ("UA", "Europe/Kyiv"),
    "ssport.tv": ("TR", "Europe/Istanbul"),
}

LINK_RE = re.compile(r'<A\s[^>]*HREF="([^"]+)"[^>]*>(.*?)</A>', re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")

# дата в имени файла закладок: bookmarks_29.08.2026.html
FILE_DATE_RE = re.compile(r"bookmarks_(\d{2})\.(\d{2})\.(\d{4})")

# порядок колонок recon/sources.csv
COLUMNS = ["domain", "name", "country", "timezone", "links_count",
           "url_primary", "urls_all", "http_status", "parse_level",
           "needs_js", "protection", "url_pattern", "notes"]

# колонки разведки: их заполняют probe/analyze, руками не восстановить
RECON_COLUMNS = ["http_status", "parse_level", "needs_js", "protection",
                 "url_pattern", "notes"]

# причины, которые скрипт выставляет сам; всё прочее в excluded.csv
# дописано руками и при перезаписи должно уцелеть
AUTO_REASONS = {"служебная ссылка", "не ТВ-расписание"} | set(EXCLUDED_DOMAINS.values())


def domain_of(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]


def geo_of(domain: str) -> tuple[str, str]:
    if domain in MANUAL_MAP:
        return MANUAL_MAP[domain]
    parts = domain.split(".")
    # tv8.com.tr → tr, tv.nova.cz → cz
    for tld in (parts[-1], parts[-2] if len(parts) > 1 else ""):
        if tld in TLD_MAP:
            return TLD_MAP[tld]
    return ("?", "?")


def newest_key(path: Path):
    """Свежесть файла закладок: сначала дата из имени (дд.мм.гггг), развёрнутая
    в гггг-мм-дд, иначе — время изменения. Просто по имени нельзя: файл за
    01.09.2026 встал бы раньше файла за 29.08.2026."""
    m = FILE_DATE_RE.search(path.name)
    if m:
        d, mo, y = m.groups()
        return (1, f"{y}-{mo}-{d}", path.name)
    return (0, f"{path.stat().st_mtime:020.0f}", path.name)


def read_previous(path: Path) -> dict[str, dict]:
    """Прошлый sources.csv: разведка и ручные правки. Нет файла — пустой словарь."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    return {r["domain"].strip(): r for r in rows if (r.get("domain") or "").strip()}


def has_recon(row: dict) -> bool:
    return any((row.get(c) or "").strip() for c in RECON_COLUMNS)


def split_urls(value) -> list[str]:
    return [u.strip() for u in (value or "").split("|") if u.strip()]


def merge_urls(prev: dict, fresh: list[str]) -> list[str]:
    """Старые адреса идут первыми, новые дописываются в хвост. Адрес, который
    разведка выбрала рабочим (url_primary), остаётся первым в списке."""
    out: list[str] = []
    for u in [(prev.get("url_primary") or "").strip()] + split_urls(prev.get("urls_all")) + fresh:
        if u and u not in out:
            out.append(u)
    return out


def main() -> int:
    files = sorted(DATA.glob("bookmarks_*.html"), key=newest_key)
    if not files:
        print(f"Не нашёл файл закладок в {DATA}")
        return 1
    src = files[-1]
    raw = src.read_text(encoding="utf-8", errors="replace")

    kept: dict[str, dict] = {}
    excluded: list[dict] = []

    for url, title in LINK_RE.findall(raw):
        url = html.unescape(url).strip()
        title = html.unescape(TAG_RE.sub("", title)).strip()
        scheme = urlsplit(url).scheme.lower()

        if scheme in JUNK_SCHEMES or not scheme:
            excluded.append({"url": url, "title": title, "reason": "служебная ссылка"})
            continue

        dom = domain_of(url)
        base = ".".join(dom.split(".")[-2:])

        if dom in EXCLUDED_DOMAINS or base in EXCLUDED_DOMAINS:
            excluded.append({"url": url, "title": title,
                             "reason": EXCLUDED_DOMAINS.get(dom) or EXCLUDED_DOMAINS[base]})
            continue
        if dom in JUNK_DOMAINS or base in JUNK_DOMAINS:
            excluded.append({"url": url, "title": title, "reason": "не ТВ-расписание"})
            continue

        country, tz = geo_of(dom)
        row = kept.setdefault(dom, {
            "domain": dom, "name": title or dom, "country": country, "timezone": tz,
            "links_count": 0, "urls": [],
        })
        row["links_count"] += 1
        if url not in row["urls"]:
            row["urls"].append(url)

    RECON.mkdir(exist_ok=True)
    out = RECON / "sources.csv"

    # --- слияние с прошлой таблицей ------------------------------------------
    previous = read_previous(out)
    merged: dict[str, dict] = {}
    added: list[str] = []
    saved = 0

    for dom in sorted(set(previous) | set(kept)):
        prev = previous.get(dom)
        fresh = kept.get(dom)

        if prev is None:
            # новый домен из закладок: колонки разведки остаются пустыми
            added.append(dom)
            merged[dom] = {
                "domain": dom, "name": fresh["name"], "country": fresh["country"],
                "timezone": fresh["timezone"], "links_count": fresh["links_count"],
                "url_primary": fresh["urls"][0], "urls_all": " | ".join(fresh["urls"]),
            }
            continue

        # известный домен: берём прошлую строку целиком, вместе с разведкой
        row = dict(prev)
        if has_recon(prev):
            saved += 1
        if fresh:
            # имя, страну и пояс не трогаем: их могли поправить руками.
            # Подставляем разобранное только там, где в таблице пусто.
            for field, value in (("name", fresh["name"]), ("country", fresh["country"]),
                                 ("timezone", fresh["timezone"])):
                if not (row.get(field) or "").strip():
                    row[field] = value
            urls = merge_urls(prev, fresh["urls"])
            row["url_primary"] = urls[0]
            row["urls_all"] = " | ".join(urls)
            row["links_count"] = fresh["links_count"]
        # домена нет в новых закладках — строка остаётся как была
        merged[dom] = row

    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(COLUMNS)
        for dom in sorted(merged):
            r = merged[dom]
            w.writerow([r.get(c) if r.get(c) is not None else "" for c in COLUMNS])

    # --- excluded.csv: дописанные руками причины не теряем --------------------
    exc = RECON / "excluded.csv"
    manual: list[dict] = []
    if exc.exists():
        with exc.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                if (r.get("reason") or "").strip() not in AUTO_REASONS:
                    manual.append(r)

    with exc.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["url", "title", "reason"])
        for r in excluded:
            w.writerow([r["url"], r["title"], r["reason"]])
        for r in manual:
            w.writerow([r.get("url", ""), r.get("title", ""), r.get("reason", "")])

    unknown = [d for d, r in merged.items() if (r.get("country") or "?") == "?"]
    print(f"источник: {src.name}")
    print(f"было доменов: {len(previous)}")
    print(f"добавлено новых: {len(added)}" + (f" ({', '.join(added)})" if added else ""))
    print(f"строк разведки сохранено: {saved}")
    print(f"источников (доменов) всего: {len(merged)}")
    print(f"выброшено ссылок: {len(excluded)}")
    if unknown:
        print(f"без страны/пояса ({len(unknown)}): {', '.join(sorted(unknown))}")
    print(f"готово: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

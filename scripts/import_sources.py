# -*- coding: utf-8 -*-
"""Заливка источников из recon/sources.csv в базу.

Повторный запуск ничего не дублирует: источник ищется по домену и
обновляется. Ручные правки владельца (часовой пояс, приоритет, вкл/выкл,
роль, доступ) при повторном запуске НЕ затираются — обновляются только
технические поля разведки.

Запуск:
    python scripts/import_sources.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "recon" / "sources.csv"

# Справочники: с них берём только названия каналов, игры не создаём (ТЗ разд. 5.1)
DIRECTORY_DOMAINS = {"liveonsat.com", "sporteventz.com", "livesoccertv.com"}

# Вес доверия: чем надёжнее данные, тем выше
PRIORITY_BY_LEVEL = {"A": 200, "B": 150, "C": 120, "D": 100}


def access_of(row: dict) -> str:
    """Доступ к расписанию. Блокировка — это не подписка, поэтому
    заблокированные сайты уходят в `unknown`, а не в `paid`: чем именно
    закрыто, решает владелец глазами (ТЗ разд. 5.2)."""
    if row["parse_level"] in ("A", "B"):
        return "open"
    return "unknown"


def status_of(row: dict) -> str:
    st = (row["http_status"] or "").strip()
    if st in ("404", "410", "ssl", "dns", "timeout"):
        return "broken"          # ссылка битая или сайт не отвечает
    if st == "403" or row["protection"]:
        return "closed"          # сайт жив, но нас не пускает
    return "new"


def main() -> int:
    if not CSV_PATH.exists():
        print(f"Нет файла {CSV_PATH}")
        return 1

    conn = db.connect()
    db.init_db(conn)

    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig"), delimiter=";"))
    added = updated = urls_added = 0

    for r in rows:
        domain = r["domain"].strip()
        role = "directory" if domain in DIRECTORY_DOMAINS else "schedule"
        level = (r["parse_level"] or "").strip()
        tech = dict(
            base_url=r["url_primary"],
            country=r["country"] or None,
            url_pattern=r["url_pattern"] or None,
            parse_level=level or None,
            needs_js=1 if r["needs_js"] == "yes" else 0,
            protection=r["protection"] or None,
            notes=r["notes"] or None,
            status=status_of(r),
        )

        cur = conn.execute("SELECT id FROM sources WHERE domain = ?", (domain,))
        found = cur.fetchone()

        if found:
            # Ручные поля (timezone, priority, enabled, role, access) не трогаем.
            conn.execute(
                "UPDATE sources SET base_url=?, country=?, url_pattern=?, "
                "parse_level=?, needs_js=?, protection=?, notes=?, status=? "
                "WHERE id=?",
                (tech["base_url"], tech["country"], tech["url_pattern"],
                 tech["parse_level"], tech["needs_js"], tech["protection"],
                 tech["notes"], tech["status"], found["id"]))
            source_id = found["id"]
            updated += 1
        else:
            cur = conn.execute(
                "INSERT INTO sources (domain, name, base_url, country, timezone, "
                "role, access, url_pattern, parse_level, needs_js, protection, "
                "priority, notes, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (domain, r["name"] or domain, r["url_primary"], r["country"] or None,
                 r["timezone"] or None, role, access_of(r), r["url_pattern"] or None,
                 level or None, tech["needs_js"], r["protection"] or None,
                 PRIORITY_BY_LEVEL.get(level, 100), r["notes"] or None, tech["status"]))
            source_id = cur.lastrowid
            added += 1

        for url in (r["urls_all"] or r["url_primary"]).split(" | "):
            url = url.strip()
            if not url:
                continue
            try:
                conn.execute(
                    "INSERT INTO source_urls (source_id, url) VALUES (?,?)",
                    (source_id, url))
                urls_added += 1
            except Exception:
                pass  # ссылка уже в базе — это и есть защита от дублей

    conn.commit()

    print(f"добавлено источников: {added}")
    print(f"обновлено:            {updated}")
    print(f"новых ссылок:         {urls_added}")
    for line in conn.execute(
            "SELECT role, status, COUNT(*) c FROM sources GROUP BY role, status "
            "ORDER BY role, status"):
        print(f"  {line['role']:10} {line['status']:8} {line['c']}")
    print(f"база: {db.db_path()}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

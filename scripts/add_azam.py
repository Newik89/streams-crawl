# -*- coding: utf-8 -*-
r"""Завести источник azamtvmax.com — программа Azam Sports 1 HD и 3 HD (книга 129).

Слово владельца 14.11.2026: «мне нужно расписание на Azam Sports» (его
записка об источнике — в ОТЛОЖЕНО.md кухни). Правила:

  1. Источник `azamtvmax.com`: страницы каналов открываются БРАУЗЕРОМ
     (`needs_js = 1`), пояс UTC — время на странице идёт по часам браузера,
     а на GitHub он живёт в UTC (как canpl.ca).
  2. Два канала, у каждого своя страница (`source_channels.page_url`):
     Azam Sports 1 HD и Azam Sports 3 HD, страна TZ. Канал с таким именем
     уже есть в базе — берём его, нет — заводим.
  3. Azam Sports 2 HD здесь не заводим: на этом сайте его нет (записка
     владельца). Его программа и матчи первого и третьего каналов на дни
     вперёд берутся страницами livesoccertv — `scripts/add_azam_lstv.py`
     (книга 131).

Скрипт на сайт не ходит, повторный запуск ничего не дублирует. Без
`--apply` — только показ.

    venv\Scripts\python.exe scripts/add_azam.py --apply
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_azam.py --apply"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402
from app.parsers import azamtvmax_com  # noqa: E402

COUNTRY = "TZ"
SOURCE = {
    "domain": azamtvmax_com.DOMAIN,
    "name": "AzamTV Max — программа каналов Azam Sports",
    "base": "https://web.azamtvmax.com/",
    "zone": azamtvmax_com.TZ,
    "notes": ("страницы каналов браузером; программа только на текущие сутки, новый день — "
              "через 1–2 часа после полуночи по Танзании; время по часам браузера — на GitHub "
              "UTC; парсер azamtvmax_com (слово владельца 14.11.2026, книга 129)"),
}
PAGE = "https://web.azamtvmax.com/channel/{}"
#: имя канала → страница (номер канала — из разборщика, чтобы не разойтись)
PAGES = {name: PAGE.format(code) for code, name in azamtvmax_com.CHANNELS.items()}


def _key(text: str) -> str:
    return "".join(c for c in (text or "").casefold() if c.isalnum())


def channel_id(conn, name: str, source_id: int) -> int:
    """Правило 2: канал Танзании по имени или написанию, иначе новый."""
    want = _key(name)
    for r in conn.execute("SELECT id, canonical_name FROM channels WHERE country = ?", (COUNTRY,)):
        if _key(r["canonical_name"]) == want:
            dictionary.remember_channel(conn, name, r["canonical_name"], COUNTRY, source_id=source_id)
            return r["id"]
    for r in conn.execute("SELECT a.channel_id, a.alias FROM channel_aliases a "
                          "JOIN channels c ON c.id = a.channel_id WHERE c.country = ?", (COUNTRY,)):
        if _key(r["alias"]) == want:
            return r["channel_id"]
    return dictionary.remember_channel(conn, name, name, COUNTRY, source_id=source_id)


def link(conn, source_id: int, name: str, page: str) -> str:
    cid = channel_id(conn, name, source_id)
    got = conn.execute("SELECT id FROM source_channels WHERE source_id = ? AND raw_name = ?",
                       (source_id, name)).fetchone()
    if got:
        conn.execute("UPDATE source_channels SET channel_id = ?, page_url = ?, include = 1 "
                     "WHERE id = ?", (cid, page, got["id"]))
        return f"обновлён (канал {cid})"
    conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, page_url, include) "
                 "VALUES (?, ?, ?, ?, 1)", (source_id, name, cid, page))
    return f"заведён (канал {cid})"


def apply(conn) -> list[str]:
    """Правила 1–2: завести или обновить источник и его каналы. → строки журнала."""
    row = conn.execute("SELECT id FROM sources WHERE domain = ?", (SOURCE["domain"],)).fetchone()
    if row:
        source_id = row["id"]
        conn.execute(
            "UPDATE sources SET name = ?, base_url = ?, country = ?, timezone = ?, "
            "role = 'schedule', access = 'open', url_pattern = ?, needs_js = 1, "
            "parse_strategy = 'structured', parse_level = 'A', enabled = 1, status = 'ok', "
            "notes = ? WHERE id = ?",
            (SOURCE["name"], SOURCE["base"], COUNTRY, SOURCE["zone"], SOURCE["base"],
             SOURCE["notes"], source_id))
    else:
        source_id = conn.execute(
            "INSERT INTO sources (domain, name, base_url, country, timezone, role, access, "
            "url_pattern, needs_js, parse_strategy, parse_level, enabled, status, notes) "
            "VALUES (?, ?, ?, ?, ?, 'schedule', 'open', ?, 1, 'structured', 'A', 1, 'ok', ?)",
            (SOURCE["domain"], SOURCE["name"], SOURCE["base"], COUNTRY, SOURCE["zone"],
             SOURCE["base"], SOURCE["notes"])).lastrowid
    said = [f"источник {SOURCE['domain']}: id {source_id}"]
    for name, page in PAGES.items():
        said.append(f"   {name}: {link(conn, source_id, name, page)}")
    conn.commit()
    return said


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="записать (без флага — показ)")
    args = ap.parse_args()
    conn = db.connect()
    row = conn.execute("SELECT id, enabled, status FROM sources WHERE domain = ?",
                       (SOURCE["domain"],)).fetchone()
    print(f"источник {SOURCE['domain']}: "
          f"{'есть, id ' + str(row['id']) if row else 'нет — заведу'}; каналов {len(PAGES)}: "
          f"{', '.join(PAGES)}")
    if not args.apply:
        print("это показ; записать — с флагом --apply")
        conn.close()
        return 0
    for line in apply(conn):
        print(line)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

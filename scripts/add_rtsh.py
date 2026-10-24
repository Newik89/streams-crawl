# -*- coding: utf-8 -*-
r"""Албания: RTSH Sport, RTSH 1, RTSH 2 — страницами каналов livesoccertv
(слово владельца 24.10.2026: «Да, заводи RTSH Sport, RTSH 1 и RTSH 2 с
livesoccertv (3 страницы), RTSH App не нужен»).

Разведка 24.10 (пробы GitHub #330/#331/#333): у RTSH открытой телепрограммы
нет нигде (ipko.tv — заглушки, rtsh.al — без программы, tvprofil — капча,
операторы — только приложения); livesoccertv ставит матчи на страницу канала,
когда объявят, кто показывает тур (RTSH Sport — высшая и первая лиги, женская
сборная; RTSH 1 — высшая лига, Лига конференций; RTSH 2 — первая лига).
Одна страница на канал, все объявленные матчи наперёд — 3 запроса за обход.
RTSH 3 (страница пуста) и RTSH App (приложение, не канал) не берём.

Правила по порядку:
1. Источник — уже заведённый `livesoccertv.com`; нет его — ничего не делать.
2. Канал — по имени в стране AL без учёта регистра и пробелов (каноническое
   имя и написания), иначе новый, страна AL (`dictionary.remember_channel`).
   Имя на витрине — по правилам `channel_rules.apply`.
3. Написание = имя канала со страницы livesoccertv (заголовок «RTSH Sport TV
   Schedule…» → «RTSH Sport»), привязано к источнику — так заливка
   (`store._channel_id`) кладёт отметку в канал AL, а не заводит новый со
   страной источника.
4. Страница канала — строка `source_channels` (raw_name = то же имя,
   page_url, include = 1); есть — обновляется адрес и include.
5. Идемпотентно; без `--apply` — только показ, база не меняется.

Гонять в ОБЕИХ базах (сначала без `--apply`):
    venv\Scripts\python.exe scripts/add_rtsh.py --apply
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_rtsh.py --apply"
К сайтам не обращается. После — пересобрать план (`crawl_plan.py`), сверить
(`plan_diff.py`) и выложить (`push_plan.py`). Тест: `scripts/test_add_rtsh.py`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import channel_rules, db, dictionary  # noqa: E402

DOMAIN = "livesoccertv.com"
COUNTRY = "AL"
BASE = "https://www.livesoccertv.com/channels/"
#: (имя канала со страницы livesoccertv, слаг страницы) — проверено 24.10
CHANNELS = [
    ("RTSH Sport", "rtsh-sport-albania"),
    ("RTSH 1", "tvsh-albania"),
    ("RTSH 2", "tvsh-2-albania"),
]


def _key(text: str) -> str:
    return "".join(c for c in (text or "").casefold() if c.isalnum())


def find_channel(conn, name: str) -> int | None:
    """Правило 2: канал страны AL по имени или написанию."""
    want = _key(name)
    for r in conn.execute("SELECT id, canonical_name FROM channels WHERE country = ?",
                          (COUNTRY,)):
        if _key(r["canonical_name"]) == want:
            return r["id"]
    for r in conn.execute("SELECT a.channel_id, a.alias FROM channel_aliases a "
                          "JOIN channels c ON c.id = a.channel_id WHERE c.country = ?",
                          (COUNTRY,)):
        if _key(r["alias"]) == want:
            return r["channel_id"]
    return None


def apply(conn, *, write: bool) -> list[str]:
    """Правила 1–5. Возвращает строки отчёта; write=False — только показ."""
    src = conn.execute("SELECT id FROM sources WHERE domain = ?", (DOMAIN,)).fetchone()
    if not src:
        return [f"источника {DOMAIN} в базе нет — ничего не сделано"]
    source_id = src["id"]
    out = []
    for name, slug in CHANNELS:
        page = f"{BASE}{slug}/"
        channel_id = find_channel(conn, name)
        was = "есть" if channel_id else "новый"
        if write:
            # правило 3: написание с источником; канал — найденный или новый
            channel_id = dictionary.remember_channel(
                conn, name,
                conn.execute("SELECT canonical_name FROM channels WHERE id = ?",
                             (channel_id,)).fetchone()["canonical_name"]
                if channel_id else channel_rules.apply(name, COUNTRY),
                COUNTRY, source_id=source_id)
            row = conn.execute("SELECT id FROM source_channels WHERE source_id = ? "
                               "AND raw_name = ?", (source_id, name)).fetchone()
            if row:
                conn.execute("UPDATE source_channels SET channel_id = ?, page_url = ?, "
                             "include = 1 WHERE id = ?", (channel_id, page, row["id"]))
                how = "страница обновлена"
            else:
                conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, "
                             "page_url, include) VALUES (?, ?, ?, ?, 1)",
                             (source_id, name, channel_id, page))
                how = "страница заведена"
            conn.commit()
            out.append(f"{name}: канал {was} → id {channel_id} ({COUNTRY}), {how}: {page}")
        else:
            have = conn.execute("SELECT 1 FROM source_channels WHERE source_id = ? "
                                "AND raw_name = ?", (source_id, name)).fetchone()
            out.append(f"{name}: канал {was}"
                       + (f" (id {channel_id})" if channel_id else "")
                       + (", страница уже есть" if have else f", страница будет: {page}"))
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="RTSH Sport / RTSH 1 / RTSH 2 с livesoccertv")
    ap.add_argument("--apply", action="store_true", help="записать (без него — показ)")
    args = ap.parse_args()
    conn = db.connect()
    try:
        print(f"база: {db.db_path()}" + ("" if args.apply else "  (только показ)"))
        for line in apply(conn, write=args.apply):
            print("  " + line)
        total = conn.execute(
            "SELECT COUNT(*) FROM source_channels sc JOIN sources s ON s.id = sc.source_id "
            "WHERE s.domain = ? AND sc.include = 1", (DOMAIN,)).fetchone()[0]
        print(f"страниц каналов {DOMAIN}: {total}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
r"""Azam Sports 1, 2 и 3 — страницами каналов livesoccertv (книга 131).

Слово владельца 15.11.2026: «завести Azam 1 2 3». На azamtvmax.com (книга
129, `scripts/add_azam.py`) есть только Azam Sports 1 HD и 3 HD, второго
канала там нет, а программа — лишь на текущие сутки. Пробы GitHub 15.11
(#479–#481): у livesoccertv есть страница на каждый из трёх каналов, матчи
стоят на дни вперёд (у первого канала — 20 матчей до декабря). Одна
страница на канал — 3 запроса за обход.

Правила по порядку:
  1. Источник — уже заведённый `livesoccertv.com`; нет его — ничего не делать.
  2. Канал — по имени в стране TZ без учёта регистра и пробелов (каноническое
     имя и написания): это тот же канал, что завёл `add_azam.py`. Нет
     такого — новый, страна TZ, имя на витрине — по `channel_rules.apply`.
  3. Первый канал livesoccertv зовёт «Azam Sports HD» (без номера). Написание
     со страницы привязывается к НАШЕМУ каналу вместе с источником — так
     заливка (`store._channel_id`) кладёт отметку в «Azam Sports 1 HD», а не
     заводит новый канал со страной источника.
  4. Написание со страницы уже привязано у этого источника к ДРУГОМУ каналу —
     канал пропускается, в отчёте строка «ЗАНЯТО»: молча переносить чужое
     написание нельзя.
  5. Страница канала — строка `source_channels` (raw_name = имя со страницы,
     page_url, include = 1); есть — обновляются канал, адрес и include.
  6. Идемпотентно; без `--apply` — только показ, база не меняется.

Не заводятся (владелец назвал 1, 2 и 3): Azam Sports 4 HD — страница у
livesoccertv есть (`azam-sports-4-hd`); Azam Sports 5 HD — есть в приложении
AzamTV Max, адрес его страницы сайт в открытом виде не показывает.

Гонять на сервере после `add_azam.py` (сначала без `--apply`):
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_azam_lstv.py --apply"
К сайтам не обращается. После — пересобрать план (`crawl_plan.py`), сверить
(`plan_diff.py`) и выложить (`push_plan.py`). Тест: `scripts/test_azam_lstv.py`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import channel_rules, db, dictionary  # noqa: E402

DOMAIN = "livesoccertv.com"
COUNTRY = "TZ"
BASE = "https://www.livesoccertv.com/channels/"
#: (канал у нас, имя со страницы livesoccertv, слаг страницы) — пробы 15.11
CHANNELS = [
    ("Azam Sports 1 HD", "Azam Sports HD", "azam-sports-hd-tanzania"),
    ("Azam Sports 2 HD", "Azam Sports 2 HD", "azam-sports-2-hd"),
    ("Azam Sports 3 HD", "Azam Sports 3 HD", "azam-sports-3-hd"),
]


def _key(text: str) -> str:
    return "".join(c for c in (text or "").casefold() if c.isalnum())


def find_channel(conn, name: str):
    """Правило 2: канал страны TZ по имени или написанию. → строка (id,
    canonical_name) или None."""
    want = _key(name)
    for r in conn.execute("SELECT id, canonical_name FROM channels WHERE country = ?",
                          (COUNTRY,)):
        if _key(r["canonical_name"]) == want:
            return r
    for r in conn.execute("SELECT c.id, c.canonical_name, a.alias FROM channel_aliases a "
                          "JOIN channels c ON c.id = a.channel_id WHERE c.country = ?",
                          (COUNTRY,)):
        if _key(r["alias"]) == want:
            return r
    return None


def taken_by(conn, page_name: str, source_id: int):
    """Правило 4: к какому каналу у этого источника уже привязано написание
    со страницы. → строка (channel_id, canonical_name, country) или None."""
    return conn.execute(
        "SELECT a.channel_id, c.canonical_name, c.country FROM channel_aliases a "
        "JOIN channels c ON c.id = a.channel_id WHERE a.alias = ? AND a.source_id = ?",
        (page_name, source_id)).fetchone()


def apply(conn, *, write: bool) -> list[str]:
    """Правила 1–6. Возвращает строки отчёта; write=False — только показ."""
    src = conn.execute("SELECT id FROM sources WHERE domain = ?", (DOMAIN,)).fetchone()
    if not src:
        return [f"источника {DOMAIN} в базе нет — ничего не сделано"]
    source_id = src["id"]
    out = []
    for name, page_name, slug in CHANNELS:
        page = f"{BASE}{slug}/"
        found = find_channel(conn, name)
        busy = taken_by(conn, page_name, source_id)
        if busy and (found is None or busy["channel_id"] != found["id"]):
            out.append(f"{name}: ЗАНЯТО — написание «{page_name}» у {DOMAIN} уже привязано "
                       f"к каналу «{busy['canonical_name']}» ({busy['country']}, "
                       f"id {busy['channel_id']}); канал пропущен")
            continue
        was = f"есть (id {found['id']})" if found else "новый"
        have = conn.execute("SELECT id FROM source_channels WHERE source_id = ? "
                            "AND raw_name = ?", (source_id, page_name)).fetchone()
        if not write:
            out.append(f"{name}: канал {was}, на странице зовётся «{page_name}»"
                       + (", страница уже есть" if have else f", страница будет: {page}"))
            continue
        # правило 3: написание со страницы — с источником; канал — найденный или новый
        channel_id = dictionary.remember_channel(
            conn, page_name,
            found["canonical_name"] if found else channel_rules.apply(name, COUNTRY),
            COUNTRY, source_id=source_id)
        if have:
            conn.execute("UPDATE source_channels SET channel_id = ?, page_url = ?, "
                         "include = 1 WHERE id = ?", (channel_id, page, have["id"]))
            how = "страница обновлена"
        else:
            conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, "
                         "page_url, include) VALUES (?, ?, ?, ?, 1)",
                         (source_id, page_name, channel_id, page))
            how = "страница заведена"
        conn.commit()
        out.append(f"{name}: канал {was} → id {channel_id} ({COUNTRY}), "
                   f"на странице зовётся «{page_name}», {how}: {page}")
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Azam Sports 1, 2, 3 с livesoccertv")
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

# -*- coding: utf-8 -*-
r"""Завести источник alkass.net и каналы Al Kass (задание владельца 13.10.2026:
«разобрать сайт и добавить расписание к нам, всё на английском, эталон —
flashscore»; пробы #257–#260).

`https://www.alkass.net/tvguide` — телегид катарских каналов Al Kass: все
каналы одной страницей, только сегодня по часам Дохи, названия передач сайт
пишет по-английски. Разбор — `app/parsers/alkass_net.py`; тип — сетка
(`GRID_DOMAINS`), один запрос за обход.

Каналы — все девять со страницы (каналы не отсеиваем, правило проекта):
Al Kass One … Eight по логотипам и Al Kass Online (у сайта «Schedule not
available»). Имена — по словам логотипов, подписи у канала на сайте нет;
переименовать — владелец (✎ в админке).

Идемпотентен: повторный запуск ничего не дублирует. Гонять в ОБЕИХ базах:
    venv\Scripts\python.exe scripts/add_alkass.py --apply
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_alkass.py --apply"

Без `--apply` только показывает, что сделает. К сайтам не обращается.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402

COUNTRY, ZONE = "QA", "Asia/Qatar"

CHANNELS = [f"Al Kass {w}" for w in ("One", "Two", "Three", "Four", "Five",
                                     "Six", "Seven", "Eight", "Online")]

SOURCE = {
    "domain": "alkass.net",
    "name": "Al Kass — телегид каналов (Катар)",
    "base": "https://www.alkass.net/tvguide",
    "pattern": "https://www.alkass.net/tvguide",
    "notes": ("сетка: все каналы одной страницей, только сегодня по часам "
              "Дохи (вкладка «завтра» отдаёт ту же сетку, 13.10); названия "
              "по-английски; пометки эфира нет — первый показ пары, сверка с "
              "эталоном; парсер alkass_net (задание владельца 13.10.2026)"),
}


def _existing(conn, name: str) -> int | None:
    """Канал Катара, который в базе уже есть: по имени или написанию, без
    учёта регистра и пробелов (`Alkass One` = `Al Kass One`)."""
    def key(text: str) -> str:
        return "".join(c for c in (text or "").casefold() if c.isalnum())
    want = key(name)
    for r in conn.execute("SELECT id, canonical_name FROM channels WHERE country = ?",
                          (COUNTRY,)):
        if key(r["canonical_name"]) == want:
            return r["id"]
    for r in conn.execute("SELECT a.channel_id, a.alias FROM channel_aliases a "
                          "JOIN channels c ON c.id = a.channel_id WHERE c.country = ?",
                          (COUNTRY,)):
        if key(r["alias"]) == want:
            return r["channel_id"]
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="записать в базу (без флага — только показ)")
    args = ap.parse_args()

    conn = db.connect()
    src = SOURCE
    row = conn.execute("SELECT id FROM sources WHERE domain = ?",
                       (src["domain"],)).fetchone()
    have = {r["raw_name"] for r in conn.execute(
        "SELECT raw_name FROM source_channels WHERE source_id = ?",
        (row["id"],))} if row else set()
    new = [name for name in CHANNELS if name not in have]
    print(f"{src['domain']}: {'есть, id ' + str(row['id']) if row else 'нет — заведу'}; "
          f"каналов в списке {len(CHANNELS)}, новых {len(new)}")
    print(f"   адрес: {src['pattern']}")
    if not args.apply:
        print("это показ; записать — с флагом --apply")
        conn.close()
        return 0
    if row:
        source_id = row["id"]
        conn.execute(
            "UPDATE sources SET name = ?, base_url = ?, country = ?, "
            "timezone = ?, role = 'schedule', access = 'open', url_pattern = ?, "
            "parse_strategy = 'structured', parse_level = 'A', enabled = 1, "
            "status = 'ok', notes = ? WHERE id = ?",
            (src["name"], src["base"], COUNTRY, ZONE, src["pattern"],
             src["notes"], source_id))
    else:
        source_id = conn.execute(
            "INSERT INTO sources (domain, name, base_url, country, timezone, "
            "role, access, url_pattern, parse_strategy, parse_level, enabled, "
            "status, notes) VALUES (?, ?, ?, ?, ?, 'schedule', 'open', ?, "
            "'structured', 'A', 1, 'ok', ?)",
            (src["domain"], src["name"], src["base"], COUNTRY, ZONE,
             src["pattern"], src["notes"])).lastrowid
    for name in CHANNELS:
        channel_id = _existing(conn, name)
        if channel_id is None:
            channel_id = dictionary.remember_channel(conn, name, name, COUNTRY,
                                                     source_id=source_id)
        got = conn.execute("SELECT id FROM source_channels WHERE source_id = ? "
                           "AND raw_name = ?", (source_id, name)).fetchone()
        if got:
            conn.execute("UPDATE source_channels SET channel_id = ?, include = 1 "
                         "WHERE id = ?", (channel_id, got["id"]))
        else:
            conn.execute("INSERT INTO source_channels (source_id, raw_name, "
                         "channel_id, page_url, include) VALUES (?, ?, ?, '', 1)",
                         (source_id, name, channel_id))
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM source_channels WHERE source_id = ?",
                         (source_id,)).fetchone()[0]
    print(f"   записано: id {source_id}, каналов у источника {total}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

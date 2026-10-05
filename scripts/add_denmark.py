# -*- coding: utf-8 -*-
r"""Завести два датских источника и их каналы (слово владельца 05.10.2026:
«заводи» — после проб #187–#192).

* `tvtid.tv2.dk` — официальный телегид TV 2: линейка TV 2 одним запросом на
  день, честный флаг эфира, пара в заголовке (`app/parsers/tvtid_tv2_dk.py`);
* `tvsporten.dk` — справочник «спорт по ТВ»: событие → каналы, пары у всех
  игр; отсюда TV3 Sport, TV3 Max, TV3+, See, Eurosport 1/2, Canal 9, Viaplay
  Sport News, у которых официальный гид пишет один турнир
  (`app/parsers/tvsporten_dk.py`).

Оба — «дневные сетки» (`DAY_GRID_DOMAINS`): один запрос на день окна.

Идемпотентен: повторный запуск ничего не дублирует. Гонять в ОБЕИХ базах:
    venv\Scripts\python.exe scripts/add_denmark.py
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_denmark.py"

Без `--apply` только показывает, что сделает. К сайтам не обращается.
Каналы не отсеиваем: у tvsporten заведены все эфирные (не стриминги) из его
справочника, полный список показан владельцу (правило проекта).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402

COUNTRY, ZONE = "DK", "Europe/Copenhagen"

#: (номер в ручке гида, имя как в разборе, имя канала на витрине)
TVTID = [
    ("77", "TV 2 Sport", "TV 2 Sport"),
    ("2147483561", "TV 2 Sport X", "TV 2 Sport X"),
    ("3", "TV 2 Danmark", "TV 2 Danmark"),
    ("4", "TV 2 Echo", "TV 2 Echo"),
    ("31", "TV 2 Charlie", "TV 2 Charlie"),
    ("12566", "TV 2 Fri", "TV 2 Fri"),
    ("133", "TV 2 News", "TV 2 News"),
]

#: (имя на сайте — поле `name` события, имя канала на витрине).
#: Имена витрины общие с гидом TV 2 и с dr.dk — канал один, сайтов несколько
TVSPORTEN = [
    ("TV 2 Sport", "TV 2 Sport"),
    ("TV 2 Sport X", "TV 2 Sport X"),
    ("TV 2 Danmark", "TV 2 Danmark"),
    ("TV 2 Echo", "TV 2 Echo"),
    ("TV 2 Charlie", "TV 2 Charlie"),
    ("TV3 Sport", "TV3 Sport"),
    ("TV3 Max", "TV3 Max"),
    ("TV3 Plus", "TV3+"),
    ("TV3 DK", "TV3"),
    ("See", "See"),
    ("Eurosport 1 DK", "Eurosport 1"),
    ("Eurosport 2 DK", "Eurosport 2"),
    ("Canal 9", "Canal 9"),
    ("Viaplay Sport News DK", "Viaplay Sport News"),
    ("V Sport Golf (DK)", "V Sport Golf"),
    ("Viasat Ultra HD", "Viasat Ultra HD"),
    ("V Sport Live 1 DK", "V Sport Live 1"),
    ("V Sport Live 2 DK", "V Sport Live 2"),
    ("V Sport Live 3 DK", "V Sport Live 3"),
    ("V Sport Live 4 DK", "V Sport Live 4"),
    ("V Sport Live 5 DK", "V Sport Live 5"),
    ("6'eren", "6'eren"),
    ("Kanal 5 (DK)", "Kanal 5"),
    ("DK4", "DK4"),
    ("SPORT LIVE", "SPORT LIVE"),
    ("DR1", "DR1"),
    ("DR2", "DR2"),
]

SOURCES = [
    {
        "domain": "tvtid.tv2.dk",
        "name": "TV 2 TV-guide (Дания)",
        "base": "https://tvtid.tv2.dk/",
        "pattern": ("https://tvtid-api.api.tv2.dk/api/tvtid/v1/epg/dayviews/"
                    "{YYYY-MM-DD}?" + "&".join(f"ch={n}" for n, _, _ in TVTID)),
        "notes": ("дневная сетка: открытая ручка гида, линейка TV 2 одним "
                  "запросом на день; время unix, флаги live/rerun честные; "
                  "пара в заголовке «Турнир: Хозяева-Гости»; глубина ≥ 10 "
                  "дней скользящим окном (проба #192); парсер tvtid_tv2_dk "
                  "(05.10.2026)"),
        "channels": [(raw, canon) for _, raw, canon in TVTID],
    },
    {
        "domain": "tvsporten.dk",
        "name": "TVsporten.dk (Дания)",
        "base": "https://www.tvsporten.dk/",
        "pattern": ("https://www.tvsporten.dk/api/fixtures/bydate?"
                    "day={YYYY-MM-DD}&dayBreakHour=5&tz=Europe%2FCopenhagen"),
        "notes": ("дневная сетка: ручка самого сайта без ключа, событие → "
                  "каналы, только прямые эфиры; стриминги (is_streaming) не "
                  "берём; сутки сайта до 05:00 — ночные игры в ответе "
                  "предыдущего дня; сайт за Cloudflare, GitHub пускает "
                  "(пробы #187–#192); парсер tvsporten_dk (05.10.2026)"),
        "channels": TVSPORTEN,
    },
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="записать в базу (без флага — только показ)")
    args = ap.parse_args()

    conn = db.connect()
    for src in SOURCES:
        row = conn.execute("SELECT id, status, enabled FROM sources "
                           "WHERE domain = ?", (src["domain"],)).fetchone()
        have = {r["raw_name"] for r in conn.execute(
            "SELECT raw_name FROM source_channels WHERE source_id = ?",
            (row["id"],))} if row else set()
        new = [raw for raw, _ in src["channels"] if raw not in have]
        print(f"{src['domain']}: "
              f"{'есть, id ' + str(row['id']) if row else 'нет — заведу'}; "
              f"каналов в списке {len(src['channels'])}, новых {len(new)}")
        print(f"   адрес: {src['pattern']}")
        if not args.apply:
            continue
        if row:
            source_id = row["id"]
            conn.execute(
                "UPDATE sources SET name = ?, base_url = ?, country = ?, "
                "timezone = ?, role = 'schedule', access = 'open', "
                "url_pattern = ?, parse_strategy = 'structured', parse_level = 'A', "
                "enabled = 1, status = 'ok', notes = ? WHERE id = ?",
                (src["name"], src["base"], COUNTRY, ZONE, src["pattern"],
                 src["notes"], source_id))
        else:
            cur = conn.execute(
                "INSERT INTO sources (domain, name, base_url, country, "
                "timezone, role, access, url_pattern, parse_strategy, "
                "parse_level, enabled, status, notes) "
                "VALUES (?, ?, ?, ?, ?, 'schedule', 'open', ?, 'structured', 'A', "
                "1, 'ok', ?)",
                (src["domain"], src["name"], src["base"], COUNTRY, ZONE,
                 src["pattern"], src["notes"]))
            source_id = cur.lastrowid
        for raw, canon in src["channels"]:
            channel_id = dictionary.remember_channel(
                conn, raw, canon, COUNTRY, source_id=source_id)
            got = conn.execute(
                "SELECT id FROM source_channels WHERE source_id = ? "
                "AND raw_name = ?", (source_id, raw)).fetchone()
            if got:
                conn.execute("UPDATE source_channels SET channel_id = ?, "
                             "include = 1 WHERE id = ?",
                             (channel_id, got["id"]))
            else:
                conn.execute(
                    "INSERT INTO source_channels (source_id, raw_name, "
                    "channel_id, page_url, include) VALUES (?, ?, ?, '', 1)",
                    (source_id, raw, channel_id))
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM source_channels "
                             "WHERE source_id = ?", (source_id,)).fetchone()[0]
        print(f"   записано: id {source_id}, каналов у источника {total}")
    if not args.apply:
        print("это показ; записать — с флагом --apply")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

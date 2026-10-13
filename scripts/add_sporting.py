# -*- coding: utf-8 -*-
r"""Завести источник sporting.pt и его каналы (просьба владельца 13.10.2026:
«на этом сайте есть расписание — добавь к нам в обход»; пробы #252–#253).

`sporting.pt` — официальный сайт «Спортинга». Берём календарь клуба
`https://www.sporting.pt/pt/ical` (весь сезон одним файлом, обычный запрос):
в описании игры сайт сам пишет «TRANSMISSÃO EM DIRECTO NA <канал>».
Разбор — `app/parsers/sporting_pt.py`; тип — сетка (`GRID_DOMAINS`).

Каналы — все, что сайт называл за сезон (каналы не отсеиваем, правило
проекта): SPORT TV 1–7 и SPORT TV + — те же каналы, что дают sporttv.pt;
«SPORT TV» без номера — сайт не уточнил; Sporting TV — канал клуба (дубль,
женщины, волейбол); FPB TV — трансляции Федерации баскетбола; canal11.pt —
сайт канала Canal 11 (футзал).

Идемпотентен: повторный запуск ничего не дублирует. Гонять в ОБЕИХ базах:
    venv\Scripts\python.exe scripts/add_sporting.py --apply
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_sporting.py --apply"

Без `--apply` только показывает, что сделает. К сайтам не обращается.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402

COUNTRY, ZONE = "PT", "Europe/Lisbon"

#: (имя, как его пишет сайт в «TRANSMISSÃO EM DIRECTO NA …», канал витрины)
CHANNELS = [
    *[(f"SPORT TV {n}", f"SPORT TV {n}") for n in range(1, 8)],
    ("SPORT TV +", "SPORT TV +"),
    ("SPORT TV", "SPORT TV"),
    ("SPORTING TV", "Sporting TV"),
    ("FPB TV", "FPB TV"),
    ("CANAL11.PT", "Canal 11"),
    ("CANAL 11", "Canal 11"),
]

SOURCE = {
    "domain": "sporting.pt",
    "name": "Sporting CP — календарь клуба (Португалия)",
    "base": "https://www.sporting.pt/pt/agenda/listagem",
    "pattern": "https://www.sporting.pt/pt/ical",
    "notes": ("сетка: календарь клуба iCal, весь сезон одним файлом, обычный "
              "запрос; канал — в описании игры «TRANSMISSÃO EM DIRECTO NA …», "
              "без канала и без часа игры не берём; пол и возраст — из "
              "скобки SUMMARY; парсер sporting_pt (просьба владельца 13.10.2026)"),
}


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
    new = [raw for raw, _ in CHANNELS if raw not in have]
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
    for raw, canon in CHANNELS:
        channel_id = dictionary.remember_channel(conn, raw, canon, COUNTRY,
                                                 source_id=source_id)
        got = conn.execute("SELECT id FROM source_channels WHERE source_id = ? "
                           "AND raw_name = ?", (source_id, raw)).fetchone()
        if got:
            conn.execute("UPDATE source_channels SET channel_id = ?, include = 1 "
                         "WHERE id = ?", (channel_id, got["id"]))
        else:
            conn.execute("INSERT INTO source_channels (source_id, raw_name, "
                         "channel_id, page_url, include) VALUES (?, ?, ?, '', 1)",
                         (source_id, raw, channel_id))
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM source_channels WHERE source_id = ?",
                         (source_id,)).fetchone()[0]
    print(f"   записано: id {source_id}, каналов у источника {total}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

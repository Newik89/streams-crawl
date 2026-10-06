# -*- coding: utf-8 -*-
r"""Завести шведский `tvmatchen.nu` и финский `tvmatsit.com` с их каналами
(задание владельца 06.10.2026: «заводим V Sport Швеции и Финляндии»).

Оба — близнецы датского `tvsporten.dk` (одна сеть, та же ручка), поэтому
своего модуля разбора им не нужно: в карточке источника стоит «одолженный»
разбор (`selector_config.parser = "tvsporten.dk"`), и обход с разбором берут
его сами (`app/parsers.get`). Ответ ручки — события дня со списком каналов,
только прямые трансляции, стриминги помечены `is_streaming` и в сетку не
идут. Сутки сайта тянутся до 05:00, поэтому день берётся из самого события.

Оба — «дневные сетки» (`app/crawl.py: DAY_GRID_DOMAINS`): один запрос на
день окна.

Чего в сетку НЕ заводим (полный список каналов сайтов показан владельцу
06.10, правило проекта «каналы сам не исключаю»):
  * `Ej fastställd (SE)` и `Ei vahvistettu` — это не канал, а «эфир ещё не
    объявлен»;
  * `DBET` — трансляции букмекера на его сайте, не телеканал (на шведском
    сайте стоит у каждой второй строки, флага `is_streaming` у него нет);
  * `MUTV` и `All Red Video` — клубные каналы; так же не заведены в Дании.

Идемпотентен: повторный запуск ничего не дублирует. Гонять в ОБЕИХ базах:
    venv\Scripts\python.exe scripts/add_sweden_finland.py
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_sweden_finland.py"

Без `--apply` только показывает, что сделает, и печатает каналы этих стран,
уже живущие в базе (канал опознаём парой «имя + страна», и чужое написание
того же канала завело бы двойника). К сайтам не обращается.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402

#: (имя канала в ответе сайта, имя канала на витрине). Технический суффикс
#: страны у общих каналов сети Viaplay/Eurosport снимаем — страна у канала
#: хранится отдельным полем; финские `… Suomi` остаются как есть: это
#: отдельные каналы, у игры «Chicago - Carolina» 10.10 сайт дал и
#: `V Sport 1 FI`, и `V Sport 1 Suomi`
SE_CHANNELS = [
    ("Eurosport 1 SE", "Eurosport 1"),
    ("Eurosport 2 SE", "Eurosport 2"),
    ("Kanal 5", "Kanal 5"),
    ("Kanal 9", "Kanal 9"),
    ("Kunskapskanalen", "Kunskapskanalen"),
    ("SVT1", "SVT1"),
    ("SVT2", "SVT2"),
    ("SVT24", "SVT24"),
    ("Sjuan", "Sjuan"),
    ("TV3", "TV3"),
    ("TV4", "TV4"),
    ("TV4 Fotboll", "TV4 Fotboll"),
    ("TV4 Hockey", "TV4 Hockey"),
    ("TV4 Motor", "TV4 Motor"),
    ("TV4 Sport Live 1", "TV4 Sport Live 1"),
    ("TV4 Sport Live 2", "TV4 Sport Live 2"),
    ("TV4 Sport Live 3", "TV4 Sport Live 3"),
    ("TV4 Sport Live 4", "TV4 Sport Live 4"),
    ("TV4 Sportkanalen", "TV4 Sportkanalen"),
    ("TV4 Tennis", "TV4 Tennis"),
    ("TV6", "TV6"),
    ("TV10", "TV10"),
    # канон «TV 12» с пробелом — так этот канал уже зовётся в базе
    # (`dagenstv.com` писал «TV12»); иначе рядом встал бы двойник
    ("TV12", "TV 12"),
    ("V Sport 1", "V Sport 1"),
    ("V Sport Extra", "V Sport Extra"),
    ("V Sport Football", "V Sport Football"),
    ("V Sport Football Live 1 SE", "V Sport Football Live 1"),
    ("V Sport Football Live 2 SE", "V Sport Football Live 2"),
    ("V Sport Football Live 3 SE", "V Sport Football Live 3"),
    ("V Sport Golf", "V Sport Golf"),
    ("V Sport Live 1 SE", "V Sport Live 1"),
    ("V Sport Live 2 SE", "V Sport Live 2"),
    ("V Sport Live 3 SE", "V Sport Live 3"),
    ("V Sport Live 4 SE", "V Sport Live 4"),
    ("V Sport Live 5 SE", "V Sport Live 5"),
    ("V Sport Motor", "V Sport Motor"),
    ("V Sport Premium", "V Sport Premium"),
    ("V Sport Vinter", "V Sport Vinter"),
    ("V Ultra HD", "V Ultra HD"),
    ("Viaplay Sport", "Viaplay Sport"),
]

FI_CHANNELS = [
    ("Eurosport 1 FI", "Eurosport 1"),
    ("Eurosport 2 FI", "Eurosport 2"),
    ("Jim", "Jim"),
    ("Kutonen", "Kutonen"),
    ("MTV3", "MTV3"),
    ("MTV Max", "MTV Max"),
    ("MTV Sub", "MTV Sub"),
    ("MTV Urheilu 1", "MTV Urheilu 1"),
    ("MTV Urheilu 2", "MTV Urheilu 2"),
    ("MTV Urheilu 3", "MTV Urheilu 3"),
    ("Nelonen", "Nelonen"),
    ("TV5 Finland", "TV5 Finland"),
    ("V Sport 1 FI", "V Sport 1"),
    ("V Sport 1 Suomi", "V Sport 1 Suomi"),
    ("V Sport 2 Suomi", "V Sport 2 Suomi"),
    ("V Sport+ Suomi", "V Sport+ Suomi"),
    ("V Sport Football FI", "V Sport Football"),
    ("V Sport Golf FI", "V Sport Golf"),
    ("V Sport Live 1 FI", "V Sport Live 1"),
    ("V Sport Live 2 FI", "V Sport Live 2"),
    ("V Sport Live 3 FI", "V Sport Live 3"),
    ("V Sport Live 4 FI", "V Sport Live 4"),
    ("V Sport Live 5 FI", "V Sport Live 5"),
    ("V Sport Motor FI", "V Sport Motor"),
    ("V Sport Premium FI", "V Sport Premium"),
    ("V Sport Ultra HD FI", "V Sport Ultra HD"),
    ("V Sport Vinter FI", "V Sport Vinter"),
    ("Viaplay TV (FI)", "Viaplay TV"),
    ("Yle TV1", "Yle TV1"),
    ("Yle TV2", "Yle TV2"),
]

ЗАМЕТКА = ("дневная сетка: ручка самого сайта без ключа, событие → каналы, "
           "только прямые эфиры; стриминги (is_streaming) и трансляции "
           "букмекера не берём; сутки сайта до 05:00 — ночные игры в ответе "
           "предыдущего дня, день берём из события; разбор одолженный "
           "(tvsporten.dk, сайты-близнецы одной сети); проба #214 "
           "(06.10.2026)")

SOURCES = [
    {
        "domain": "tvmatchen.nu",
        "name": "TVmatchen.nu (Швеция)",
        "base": "https://www.tvmatchen.nu/",
        "country": "SE",
        "zone": "Europe/Stockholm",
        "pattern": ("https://www.tvmatchen.nu/api/fixtures/bydate?"
                    "day={YYYY-MM-DD}&dayBreakHour=5&tz=Europe%2FStockholm"),
        "notes": ЗАМЕТКА,
        "channels": SE_CHANNELS,
    },
    {
        "domain": "tvmatsit.com",
        "name": "TVmatsit.com (Финляндия)",
        "base": "https://tvmatsit.com/",
        "country": "FI",
        "zone": "Europe/Helsinki",
        "pattern": ("https://tvmatsit.com/api/fixtures/bydate?"
                    "day={YYYY-MM-DD}&dayBreakHour=5&tz=Europe%2FHelsinki"),
        "notes": ЗАМЕТКА,
        "channels": FI_CHANNELS,
    },
]

#: разбор, который берём взаймы: у близнецов та же ручка и те же поля
ОДОЛЖЕННЫЙ = "tvsporten.dk"


def показать_тёзок(conn, country: str, свои: list[tuple[str, str]]) -> None:
    """Каналы этой страны, уже живущие в базе: чужое написание того же
    канала завело бы двойника (`ГРАБЛИ.md`, строка про `channels`)."""
    есть = conn.execute(
        "SELECT c.canonical_name AS имя, COUNT(a.id) AS алиасов FROM channels c "
        "LEFT JOIN channel_aliases a ON a.channel_id = c.id "
        "WHERE c.country = ? GROUP BY c.id ORDER BY c.canonical_name",
        (country,)).fetchall()
    мои = {canon for _, canon in свои}
    совпали = [r["имя"] for r in есть if r["имя"] in мои]
    прочие = [r["имя"] for r in есть if r["имя"] not in мои]
    print(f"   каналов страны {country} в базе: {len(есть)}; "
          f"из них наших по имени {len(совпали)}")
    if совпали:
        print(f"      склеим с существующими: {', '.join(совпали)}")
    if прочие:
        print(f"      прочие каналы страны: {', '.join(прочие)}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="записать в базу (без флага — только показ)")
    args = ap.parse_args()

    conn = db.connect()
    for src in SOURCES:
        country, zone = src["country"], src["zone"]
        row = conn.execute("SELECT id FROM sources WHERE domain = ?",
                           (src["domain"],)).fetchone()
        имена = {r["raw_name"] for r in conn.execute(
            "SELECT raw_name FROM source_channels WHERE source_id = ?",
            (row["id"],))} if row else set()
        новые = [raw for raw, _ in src["channels"] if raw not in имена]
        print(f"\n{src['domain']}: "
              f"{'есть, id ' + str(row['id']) if row else 'нет — заведу'}; "
              f"каналов в списке {len(src['channels'])}, новых {len(новые)}")
        print(f"   адрес: {src['pattern']}")
        показать_тёзок(conn, country, src["channels"])
        if not args.apply:
            continue
        config = json.dumps({"parser": ОДОЛЖЕННЫЙ}, ensure_ascii=False)
        if row:
            source_id = row["id"]
            conn.execute(
                "UPDATE sources SET name = ?, base_url = ?, country = ?, "
                "timezone = ?, role = 'schedule', access = 'open', "
                "url_pattern = ?, parse_strategy = 'structured', "
                "parse_level = 'A', selector_config = ?, enabled = 1, "
                "status = 'ok', notes = ? WHERE id = ?",
                (src["name"], src["base"], country, zone, src["pattern"],
                 config, src["notes"], source_id))
        else:
            cur = conn.execute(
                "INSERT INTO sources (domain, name, base_url, country, "
                "timezone, role, access, url_pattern, parse_strategy, "
                "parse_level, selector_config, enabled, status, notes) "
                "VALUES (?, ?, ?, ?, ?, 'schedule', 'open', ?, 'structured', "
                "'A', ?, 1, 'ok', ?)",
                (src["domain"], src["name"], src["base"], country, zone,
                 src["pattern"], config, src["notes"]))
            source_id = cur.lastrowid
        for raw, canon in src["channels"]:
            channel_id = dictionary.remember_channel(
                conn, raw, canon, country, source_id=source_id)
            было = conn.execute(
                "SELECT id FROM source_channels WHERE source_id = ? "
                "AND raw_name = ?", (source_id, raw)).fetchone()
            if было:
                conn.execute("UPDATE source_channels SET channel_id = ?, "
                             "include = 1 WHERE id = ?",
                             (channel_id, было["id"]))
            else:
                conn.execute(
                    "INSERT INTO source_channels (source_id, raw_name, "
                    "channel_id, page_url, include) VALUES (?, ?, ?, '', 1)",
                    (source_id, raw, channel_id))
        conn.commit()
        всего = conn.execute("SELECT COUNT(*) FROM source_channels "
                             "WHERE source_id = ?", (source_id,)).fetchone()[0]
        print(f"   записано: id {source_id}, каналов у источника {всего}")
    if not args.apply:
        print("\nэто показ; записать — с флагом --apply")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

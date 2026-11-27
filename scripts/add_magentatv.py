# -*- coding: utf-8 -*-
r"""Завести источник magentatv.de — каналы немецкого MagentaSport 1–18 (книга 183).

Слово владельца 27–28.11.2026: «почему нет информации с немецких Magenta Sport
10, 11 – 18» и «они ж должны быть помечены как DE| Magenta Sport 1-18». Правила:

  1. Источник `magentatv.de`: телегид MagentaTV, обычный запрос (не браузер),
     пояс Europe/Berlin. Ручка пускает в гостевой сессии — её открывает
     `app/fetch.py` (`SESSION_HOSTS`). Тело запроса (`post_json`) лежит в
     карточке источника: окно — от «сегодня» сайта на 7 суток вперёд, номер
     канала подставляется из адреса канала (`channel_id=`). Чужие поля
     карточки (`selector_config`) скрипт не трогает.
  2. Восемнадцать каналов «Sport N - myTeamTV» (имя в телегиде), у каждого
     свой адрес ручки (`source_channels.page_url`). Канал базы — «DE| Magenta
     Sport N», страна DE: имя дал владелец, поэтому `custom_name = 1` и
     пометка `DE` — как у его «DE| Nitro». Греческие «Magenta Sport 1–9»
     (cosmotetv.gr, страна GR) — другие каналы, их скрипт не касается.
  3. Канал, уже привязанный к написанию этого источника, остаётся как есть,
     даже если владелец его потом переименовал: повторный запуск ничего не
     дублирует и имя владельца не затирает.
  4. «MS Sport», «MS GOLF 1–2» и «MagentaSport» из того же телегида здесь не
     заводятся: владелец просил 1–18. Понадобятся — добавить в `WANTED`.

Скрипт на сайт не ходит. Без `--apply` — только показ.

    venv\Scripts\python.exe scripts/add_magentatv.py --apply
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_magentatv.py --apply"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402
from app.parsers import magentatv_de  # noqa: E402

COUNTRY = "DE"
SOURCE = {
    "domain": magentatv_de.DOMAIN,
    "name": "MagentaTV — телегид, каналы MagentaSport 1–18",
    "base": "https://web.magentatv.de/tv-guide",
    "zone": magentatv_de.TZ,
    "notes": ("ручка телегида PlayBillList в гостевой сессии (app/fetch.py SESSION_HOSTS), запрос на "
              "канал, окно неделя в теле запроса; каналы «Sport N - myTeamTV» = MagentaSport N; "
              "парсер magentatv_de (слово владельца 27–28.11.2026, книга 183)"),
}
PAGE = "https://api.prod.sngtv.magentatv.de/EPG/JSON/PlayBillList?channel_id={}"
#: правило 1: тело запроса; метки подставляет обход (`crawl_fetch.json_body`)
BODY = {"count": -1, "isFillProgram": 1, "offset": 0, "type": 2,
        "begintime": "{YYYYMMDD}000000", "endtime": "{YYYYMMDD+7}000000",
        "channelid": "{channel_id}",
        "properties": [{"include": "endtime,genres,id,name,starttime,channelid,introduce,subName",
                        "name": "playbill"}]}
#: правило 2: имя канала в телегиде — только «Sport N - myTeamTV» (правило 4)
WANTED = re.compile(r"^Sport (\d+) - myTeamTV$")
#: имя в телегиде → (имя канала базы, адрес ручки); номера — из разборщика
CHANNELS = {name: (f"DE| Magenta Sport {WANTED.match(name).group(1)}", PAGE.format(code))
            for code, name in magentatv_de.CHANNELS.items() if WANTED.match(name)}


def channel_id(conn, raw: str, canonical: str, source_id: int) -> tuple[int, str]:
    """Правила 2–3: канал этого написания. → (id, что сделано)."""
    bound = conn.execute("SELECT channel_id FROM source_channels WHERE source_id = ? AND raw_name = ? "
                         "AND channel_id IS NOT NULL", (source_id, raw)).fetchone()
    if bound:                                                     # правило 3
        return bound["channel_id"], "уже привязан"
    known = conn.execute("SELECT id FROM channels WHERE canonical_name = ? AND country = ?",
                         (canonical, COUNTRY)).fetchone()
    cid = dictionary.remember_channel(conn, raw, canonical, COUNTRY, source_id=source_id, language="de")
    if known:
        return cid, "канал был, написание привязано"
    conn.execute("UPDATE channels SET custom_name = 1, note = ? WHERE id = ?", (COUNTRY, cid))
    return cid, "заведён"


def link(conn, source_id: int, raw: str, canonical: str, page: str) -> str:
    cid, what = channel_id(conn, raw, canonical, source_id)
    got = conn.execute("SELECT id FROM source_channels WHERE source_id = ? AND raw_name = ?",
                       (source_id, raw)).fetchone()
    if got:
        conn.execute("UPDATE source_channels SET channel_id = ?, page_url = ?, include = 1 WHERE id = ?",
                     (cid, page, got["id"]))
    else:
        conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, page_url, include) "
                     "VALUES (?, ?, ?, ?, 1)", (source_id, raw, cid, page))
    name = conn.execute("SELECT canonical_name FROM channels WHERE id = ?", (cid,)).fetchone()[0]
    return f"{what} — канал {cid} «{name}»"


def apply(conn) -> list[str]:
    """Правила 1–3: завести или обновить источник и его каналы. → строки журнала."""
    row = conn.execute("SELECT id, selector_config FROM sources WHERE domain = ?",
                       (SOURCE["domain"],)).fetchone()
    config = json.loads((row["selector_config"] if row else "") or "{}") or {}
    config["post_json"] = BODY
    packed = json.dumps(config, ensure_ascii=False)
    if row:
        source_id = row["id"]
        conn.execute(
            "UPDATE sources SET name = ?, base_url = ?, country = ?, timezone = ?, "
            "role = 'schedule', access = 'open', url_pattern = ?, needs_js = 0, "
            "parse_strategy = 'structured', parse_level = 'A', enabled = 1, status = 'ok', "
            "notes = ?, selector_config = ? WHERE id = ?",
            (SOURCE["name"], SOURCE["base"], COUNTRY, SOURCE["zone"], SOURCE["base"],
             SOURCE["notes"], packed, source_id))
    else:
        source_id = conn.execute(
            "INSERT INTO sources (domain, name, base_url, country, timezone, role, access, "
            "url_pattern, needs_js, parse_strategy, parse_level, enabled, status, notes, "
            "selector_config) "
            "VALUES (?, ?, ?, ?, ?, 'schedule', 'open', ?, 0, 'structured', 'A', 1, 'ok', ?, ?)",
            (SOURCE["domain"], SOURCE["name"], SOURCE["base"], COUNTRY, SOURCE["zone"],
             SOURCE["base"], SOURCE["notes"], packed)).lastrowid
    said = [f"источник {SOURCE['domain']}: id {source_id}"]
    for raw, (canonical, page) in CHANNELS.items():
        said.append(f"   {raw}: {link(conn, source_id, raw, canonical, page)}")
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
          f"{'есть, id ' + str(row['id']) if row else 'нет — заведу'}; каналов {len(CHANNELS)}: "
          f"{', '.join(canonical for canonical, _ in CHANNELS.values())}")
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

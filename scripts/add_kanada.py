# -*- coding: utf-8 -*-
r"""Канада: TVA Sports 2, TVA Sports, OneSoccer и матчи CPL с каналами (слово
владельца 22.10.2026 — «да» на три пункта после разведки #311–#312).

Правила по порядку:
1. tvpassport.com — ещё три станции, адрес на канал и день, как у TSN:
   TVA Sports 2 (13778), TVA Sports (9824), OneSoccer (37452) — программа
   канала с `data-live`/`data-repeat`.
2. canpl.ca — новый источник: календарь Канадской премьер-лиги, у каждой игры
   её каналы (OneSoccer, TVA Sports 2, TVA Sports, TSN, CBC). Одна страница
   браузером (`needs_js`), сетка; пояс UTC — время на странице по часам
   браузера обхода на GitHub (`app/parsers/canpl_ca.py`, правило 3).
3. onesoccer.ca — выключается: на странице отрисован только виджет Opta с
   матчами АПЛ, а не программа канала (в программе OneSoccer АПЛ нет —
   tvpassport и FotMob, разведка #311); вкладки CPL/MLS сайта пусты (season
   2023). Его отметки у будущих игр гасятся (`miss_count = MISS_LIMIT`), номера
   печатаются — вернуть: `scripts/miss_repair.py --ids … --apply`, источник —
   `sources.toggle_enabled` (админка «Источники»).
4. Каналы — уже знакомые базе по имени без учёта регистра и пробелов
   («OneSoccer» = «One Soccer»), иначе новые (страна CA).

Идемпотентен. Гонять в ОБЕИХ базах (без `--apply` — только показ):
    venv\Scripts\python.exe scripts/add_kanada.py --apply
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_kanada.py --apply"
К сайтам не обращается. После — пересобрать план (`crawl_plan.py`), сверить
(`plan_diff.py`) и выложить (`push_plan.py`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402
from app.store import MISS_LIMIT  # noqa: E402

COUNTRY = "CA"
_TVP = "https://www.tvpassport.com/tv-listings/stations/{}/{{YYYY-MM-DD}}"
TVPASSPORT = [("TVA Sports 2", _TVP.format("tva-sports-2-hd/13778")),
              ("TVA Sports", _TVP.format("tva-sports-hd/9824")),
              ("OneSoccer", _TVP.format("one-soccer/37452"))]

CANPL = {
    "domain": "canpl.ca",
    "name": "Canadian Premier League — календарь с каналами",
    "base": "https://canpl.ca/schedule/",
    "pattern": "https://canpl.ca/schedule/",
    "zone": "UTC",
    "notes": ("календарь CPL браузером, одна страница на сезон: у каждой игры "
              "её каналы (onesoccer/tvas2/tva/tsn/cbc); время «My Time» по "
              "часам браузера — на GitHub UTC; парсер canpl_ca (слово "
              "владельца 22.10.2026, разведка #312)"),
}
CANPL_CHANNELS = ["OneSoccer", "TVA Sports 2", "TVA Sports", "TSN", "CBC"]

ONESOCCER = "onesoccer.ca"
ONESOCCER_NOTE = (" | ВЫКЛЮЧЕН 22.10.2026 словом владельца: на странице только "
                  "виджет АПЛ, а не программа канала (разведка #311); программа "
                  "OneSoccer — tvpassport, матчи CPL — canpl.ca")


def _key(text: str) -> str:
    return "".join(c for c in (text or "").casefold() if c.isalnum())


def _channel(conn, name: str, source_id: int) -> int:
    """Канал Канады по имени или написанию (правило 4), иначе новый."""
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
    return dictionary.remember_channel(conn, name, name, COUNTRY, source_id=source_id)


def _link(conn, source_id: int, name: str, page: str) -> str:
    channel_id = _channel(conn, name, source_id)
    got = conn.execute("SELECT id FROM source_channels WHERE source_id = ? AND raw_name = ?",
                       (source_id, name)).fetchone()
    if got:
        conn.execute("UPDATE source_channels SET channel_id = ?, page_url = ?, include = 1 "
                     "WHERE id = ?", (channel_id, page, got["id"]))
        return f"обновлён (канал {channel_id})"
    conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, page_url, "
                 "include) VALUES (?, ?, ?, ?, 1)", (source_id, name, channel_id, page))
    return f"заведён (канал {channel_id})"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="записать (без флага — показ)")
    args = ap.parse_args()
    conn = db.connect()

    tvp = conn.execute("SELECT id FROM sources WHERE domain = 'tvpassport.com'").fetchone()
    canpl = conn.execute("SELECT id FROM sources WHERE domain = ?", (CANPL["domain"],)).fetchone()
    one = conn.execute("SELECT id, enabled FROM sources WHERE domain = ?", (ONESOCCER,)).fetchone()
    marks = conn.execute(
        "SELECT ec.id FROM event_channels ec JOIN events e ON e.id = ec.event_id "
        "WHERE ec.source_id = ? AND e.start_utc > datetime('now') AND ec.miss_count < ?",
        (one["id"] if one else -1, MISS_LIMIT)).fetchall()
    print(f"1. tvpassport.com: {'id ' + str(tvp['id']) if tvp else 'НЕТ в базе'}; станций +{len(TVPASSPORT)}")
    print(f"2. canpl.ca: {'есть, id ' + str(canpl['id']) if canpl else 'нет — заведу'}; каналов {len(CANPL_CHANNELS)}")
    print(f"3. onesoccer.ca: {'включён' if one and one['enabled'] else 'выключен' if one else 'нет'}; "
          f"отметок у будущих игр погасить: {len(marks)}")
    if not args.apply:
        print("это показ; записать — с флагом --apply")
        conn.close()
        return 0
    if not tvp:
        print("источника tvpassport.com нет — ничего не пишу")
        conn.close()
        return 1

    for name, page in TVPASSPORT:                                   # правило 1
        print(f"   tvpassport {name}: {_link(conn, tvp['id'], name, page)}")

    if canpl:                                                       # правило 2
        canpl_id = canpl["id"]
        conn.execute(
            "UPDATE sources SET name = ?, base_url = ?, country = ?, timezone = ?, "
            "role = 'schedule', access = 'open', url_pattern = ?, needs_js = 1, "
            "parse_strategy = 'structured', parse_level = 'A', enabled = 1, "
            "status = 'ok', notes = ? WHERE id = ?",
            (CANPL["name"], CANPL["base"], COUNTRY, CANPL["zone"], CANPL["pattern"],
             CANPL["notes"], canpl_id))
    else:
        canpl_id = conn.execute(
            "INSERT INTO sources (domain, name, base_url, country, timezone, role, "
            "access, url_pattern, needs_js, parse_strategy, parse_level, enabled, "
            "status, notes) VALUES (?, ?, ?, ?, ?, 'schedule', 'open', ?, 1, "
            "'structured', 'A', 1, 'ok', ?)",
            (CANPL["domain"], CANPL["name"], CANPL["base"], COUNTRY, CANPL["zone"],
             CANPL["pattern"], CANPL["notes"])).lastrowid
    for name in CANPL_CHANNELS:
        print(f"   canpl.ca {name}: {_link(conn, canpl_id, name, '')}")

    if one:                                                         # правило 3
        conn.execute("UPDATE sources SET enabled = 0, notes = COALESCE(notes, '') || ? "
                     "WHERE id = ? AND COALESCE(notes, '') NOT LIKE '%ВЫКЛЮЧЕН 22.10.2026%'",
                     (ONESOCCER_NOTE, one["id"]))
        conn.execute("UPDATE sources SET enabled = 0 WHERE id = ?", (one["id"],))
        ids = [r["id"] for r in marks]
        if ids:
            conn.executemany("UPDATE event_channels SET miss_count = ? WHERE id = ?",
                             [(MISS_LIMIT, i) for i in ids])
        print(f"   onesoccer.ca выключен; погашены отметки: {','.join(map(str, ids)) or 'нет'}")
    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
r"""Показать игру по номеру и объяснить, почему две строки не стали одной.

Вопрос владельца «почему #1946 и #1947 — две строки, это одна игра» руками
разбирался долго: надо было смотреть базу, считать похожесть имён и сверять
время. Скрипт делает это сам.

    venv\Scripts\python.exe scripts/show_event.py 1946 1947
    ssh … "cd /root/streams-schedule && venv/bin/python scripts/show_event.py 1946 1947"

Только читает: базу не меняет, в сеть не ходит.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, merge, names  # noqa: E402


def event(conn, event_id: int) -> dict | None:
    row = conn.execute("""
        SELECT e.*, l.canonical_name AS league_name,
               th.canonical_name AS home_name, th.country AS home_country,
               ta.canonical_name AS away_name, ta.country AS away_country
        FROM events e
        LEFT JOIN leagues l ON l.id = e.league_id
        LEFT JOIN teams th ON th.id = e.team_home_id
        LEFT JOIN teams ta ON ta.id = e.team_away_id
        WHERE e.id = ?""", (event_id,)).fetchone()
    if row is None:
        return None
    got = dict(row)
    got["каналы"] = [dict(r) for r in conn.execute("""
        SELECT c.canonical_name AS channel, c.country, s.domain, ec.raw_title,
               ec.raw_time_local, ec.source_url, ec.miss_count
        FROM event_channels ec
        JOIN channels c ON c.id = ec.channel_id
        JOIN sources s ON s.id = ec.source_id
        WHERE ec.event_id = ? ORDER BY s.domain""", (event_id,))]
    return got


def show(got: dict) -> None:
    print(f"#{got['id']}  {got['start_kyiv']}  спорт {got['sport']}")
    print(f"   команды в базе: {got['home_name'] or '—'} — {got['away_name'] or '—'}"
          f"   (страны: {got['home_country'] or '—'}/{got['away_country'] or '—'})")
    print(f"   как было на сайте: {got['team_home_auto']} — {got['team_away_auto']}")
    print(f"   лига: {got['league_name'] or '—'} / было: {got['league_auto'] or '—'}")
    print(f"   метки: time_confidence={got['time_confidence']} flags={got['flags']}")
    for ch in got["каналы"]:
        print(f"   • {ch['domain']:<22} {ch['channel']} ({ch['country'] or '—'})"
              f"  «{ch['raw_title'] or ''}»  miss={ch['miss_count']}")


def why(a: dict, b: dict) -> None:
    """Почему склейка не признала их одной игрой (правила — app/merge.py)."""
    print("\nпочему не склеились:")
    if a["sport"] and b["sport"] and a["sport"] != b["sport"]:
        print(f"   ✗ разный вид спорта: {a['sport']} и {b['sport']}")
    else:
        print(f"   ✓ вид спорта один: {a['sport'] or '—'}")
    fmt = "%Y-%m-%d %H:%M"
    ta = datetime.strptime(a["start_kyiv"].replace("T", " ")[:16], fmt)
    tb = datetime.strptime(b["start_kyiv"].replace("T", " ")[:16], fmt)
    diff = abs((ta - tb).total_seconds()) // 60
    mark = "✓" if diff <= merge.WINDOW_MINUTES else "✗"
    print(f"   {mark} время: расходится на {int(diff)} мин "
          f"(допуск {merge.WINDOW_MINUTES})")
    pairs = [("хозяева", "home", "home"), ("гости", "away", "away"),
             ("хозяева↔гости", "home", "away"), ("гости↔хозяева", "away", "home")]
    for title, ka, kb in pairs:
        one = a[f"{ka}_name"] or a[f"team_{ka}_auto"] or ""
        two = b[f"{kb}_name"] or b[f"team_{kb}_auto"] or ""
        близость = names.similarity(one, two)
        вид = (names.category(one), names.category(two))
        mark = "✓" if близость >= names.SIMILAR_ENOUGH else "✗"
        print(f"   {mark} {title}: «{one}» ↔ «{two}» — похожесть {близость}"
              f" (нужно {names.SIMILAR_ENOUGH}), категории {вид[0]}/{вид[1]}")
    print("\n   склейка требует: один спорт + время в допуске + ОБЕ команды "
          "похожи (прямо или крест-накрест).")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+", type=int, help="номера игр")
    args = ap.parse_args()
    conn = db.connect()
    try:
        found = []
        for event_id in args.ids:
            got = event(conn, event_id)
            if got is None:
                print(f"#{event_id}: такой игры в базе нет")
                continue
            show(got)
            print()
            found.append(got)
        if len(found) == 2:
            why(found[0], found[1])
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

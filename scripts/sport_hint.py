# -*- coding: utf-8 -*-
r"""Подсказки вида спорта по паре команд (`sport_hints`): посмотреть и снять.
Снимать — поимённо и только неверные, по слову владельца (02.10: автомат
очереди записал футбол баскетбольному Еврокубку — «Balkan Botevgrad -
Bahcesehir», «Aris - Burgos»).

    venv/bin/python scripts/sport_hint.py --find Burgos            показать подсказки с этим текстом
    venv/bin/python scripts/sport_hint.py --forget "Aris - Burgos"           показать, что снимется
    venv/bin/python scripts/sport_hint.py --forget "Aris - Burgos" --apply   снять

Пара — как в словаре (`dictionary.norm_pair`: часть до « | », пробелы
схлопнуты). Без `--apply` ничего не пишется.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", default="", help="показать подсказки с этим текстом")
    ap.add_argument("--forget", action="append", default=[],
                    help="снять подсказку этой пары (можно несколько раз)")
    ap.add_argument("--apply", action="store_true", help="записать")
    args = ap.parse_args()
    conn = db.connect()
    try:
        if args.find:
            rows = conn.execute(
                "SELECT pair, sport, match_day, created_at FROM sport_hints "
                "WHERE pair LIKE ? ORDER BY created_at DESC",
                (f"%{args.find}%",)).fetchall()
            print(f"подсказок с «{args.find}»: {len(rows)}")
            for r in rows:
                print(f"   {r['sport']}  {r['pair']}  день={r['match_day'] or 'бессрочно'}  "
                      f"записана {r['created_at']}")
        if not args.forget:
            return 0
        пары = [dictionary.norm_pair(x) for x in args.forget]
        rows = conn.execute(
            "SELECT pair, sport, match_day FROM sport_hints WHERE pair IN (%s)"
            % ",".join("?" * len(пары)), пары).fetchall()
        for r in rows:
            print(f"   снять: {r['sport']}  {r['pair']}  день={r['match_day'] or 'бессрочно'}")
        не_найдено = set(пары) - {r["pair"] for r in rows}
        for x in sorted(не_найдено):
            print(f"   нет такой подсказки: {x}")
        if not rows:
            return 0
        if not args.apply:
            print(f"будет снято: {len(rows)} — добавьте --apply")
            return 0
        conn.executemany("DELETE FROM sport_hints WHERE pair = ?",
                         [(r["pair"],) for r in rows])
        conn.commit()
        print(f"снято подсказок: {len(rows)}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

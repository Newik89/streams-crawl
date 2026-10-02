# -*- coding: utf-8 -*-
r"""Очередь модерации: посмотреть, сколько чего лежит, и снять с модерации всё,
что ждёт ручного решения (владелец 03.10.2026: «большая часть должна проходить
через flashscore, а ручное — снять, я не буду сейчас этим заниматься»).

    venv/bin/python scripts/moderation_skip.py                    счётчики по видам и статусам
    venv/bin/python scripts/moderation_skip.py --kind sport        только очередь «Вид спорта»
    venv/bin/python scripts/moderation_skip.py --apply             снять все open/later (все виды)
    venv/bin/python scripts/moderation_skip.py --kind team --apply снять только один вид

Снятое не удаляется: статус `skipped` — во вкладке «Отсеянные» есть кнопка
«Вернуть». Строка в «Прогонах» говорит, сколько и когда снято.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, watch  # noqa: E402

KINDS = ("team", "league", "channel", "sport")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="", choices=("",) + KINDS,
                    help="только этот вид очереди")
    ap.add_argument("--apply", action="store_true", help="снять (status = skipped)")
    args = ap.parse_args()
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT kind, status, COUNT(*) AS n FROM moderation "
            "GROUP BY kind, status ORDER BY kind, status").fetchall()
        print("очередь модерации (вид / статус / сколько):")
        for r in rows:
            print(f"   {r['kind']:<8} {r['status']:<8} {r['n']}")
        where = "status IN ('open', 'later')"
        params: list = []
        if args.kind:
            where += " AND kind = ?"
            params.append(args.kind)
        waiting = conn.execute(f"SELECT COUNT(*) FROM moderation WHERE {where}",
                               params).fetchone()[0]
        print(f"ждут ручного решения{' (' + args.kind + ')' if args.kind else ''}: {waiting}")
        if not waiting:
            return 0
        if not args.apply:
            print("добавьте --apply, чтобы снять их с модерации (обратимо: «Вернуть»)")
            return 0
        n = conn.execute(f"UPDATE moderation SET status = 'skipped' WHERE {where}",
                         params).rowcount
        conn.commit()
        watch.note(conn, f"очередь модерации{' «' + args.kind + '»' if args.kind else ''}: "
                         f"снято {n} записей, ждавших ручного решения (слово владельца 03.10)",
                   who="автомат")
        print(f"снято с модерации: {n}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

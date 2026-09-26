# -*- coding: utf-8 -*-
r"""Написания команд: показать владельцев или прицепить к команде.

Показ говорит, спорное ли написание (у двух разных клубов словарь его не
отдаёт — игру решает эталон, механизм 14.09). Прицепить можно только к
команде, которая УЖЕ есть в базе — двойников не заводим (опечатка в
каноническом имени создала бы новый клуб).

Запуск (локально и на сервере — одним файлом):
    venv\Scripts\python.exe scripts/team_alias.py "Red Star"
    venv\Scripts\python.exe scripts/team_alias.py "Red Star" --to "Crvena Zvezda Meridianbet"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402


def _show(conn, alias: str) -> None:
    rows = conn.execute(
        "SELECT a.team_id, t.canonical_name, a.lang FROM team_aliases a "
        "JOIN teams t ON t.id = a.team_id WHERE a.alias = ? ORDER BY a.id",
        (alias,)).fetchall()
    if not rows:
        print(f"написание «{alias}» в словаре не встречается")
        return
    for r in rows:
        print(f"  #{r['team_id']:5} {r['canonical_name']}"
              f"{'  (' + r['lang'] + ')' if r['lang'] else ''}")
    verdict = dictionary.team_alias_map(conn).get(alias)
    print(f"словарь отдаёт: {verdict[1] if verdict else 'НЕ ОТДАЁТ (спорное)'}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("alias", help="написание, как пишет сайт")
    ap.add_argument("--to", metavar="КОМАНДА",
                    help="прицепить написание к этой команде (точное "
                         "каноническое имя из базы)")
    ap.add_argument("--lang", default=None, help="язык написания (иначе без языка)")
    args = ap.parse_args()

    conn = db.connect()
    try:
        if args.to:
            row = conn.execute("SELECT id FROM teams WHERE canonical_name = ?",
                               (args.to,)).fetchone()
            if not row:
                print(f"команды «{args.to}» в базе нет — двойника не завожу. "
                      f"Проверьте имя (show_event или поиск по базе).")
                return 1
            dictionary.remember_team(conn, args.alias, args.to, lang=args.lang)
            print(f"«{args.alias}» прицеплено к {args.to}")
        _show(conn, args.alias)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

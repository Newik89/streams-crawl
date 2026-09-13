# -*- coding: utf-8 -*-
r"""Привязки ярлыков к лигам: посмотреть, найти лишние, снять.

Ярлык с сайта («Карабао къп», «כדורגל נשים») хранится алиасом лиги, и по
нему игра получает каноническое название турнира. Беда, когда алиасом стал
РОДОВОЙ ярлык: «женский футбол» — это вид соревнования, а не лига, но он
успел привязаться к `ENGLAND: WSL`, и немецкий матч уехал в английскую лигу
(разбор владельца 10.09).

    venv\Scripts\python.exe scripts/league_alias.py --check
    venv\Scripts\python.exe scripts/league_alias.py --find женск
    venv\Scripts\python.exe scripts/league_alias.py --check --apply

`--check` перебирает алиасы правилом `canon.league_worthy` — тем самым,
которым обход решает, стоит ли учить ярлык. Что оно теперь отвергает, то и
предлагается снять. Сам ярлык никуда не денется: он вернётся алиасом, если
окажется настоящим названием лиги.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import canon, db  # noqa: E402

#: ярлык, который названием лиги быть не может: пометка эфира, тур, стадия
_NOT_A_LEAGUE = re.compile(
    r"прямая\s+трансляция|тур\s*\d+|\d+\s*тур|1/\d+\s+финала|"
    r"перенесённ|перенесен|повтор|обзор|highlights", re.I)


def rows(conn, где: str = "", args: tuple = ()) -> list:
    return conn.execute(
        "SELECT a.id, a.alias, l.canonical_name AS league "
        "FROM league_aliases a JOIN leagues l ON l.id = a.league_id "
        + где + " ORDER BY a.alias", args).fetchall()


def review(conn) -> dict:
    """Разложить привязки на три кучки.

    * **мусор** — ярлык вовсе не название лиги: «Прямая трансляция»,
      «Тур 7 Прямая трансляция», «1/16 финала».
    * **конфликт** — один ярлык привязан к РАЗНЫМ лигам: «Superliga» ведёт
      и в Данию, и в Румынию, и в Косово; какая из них верна — неизвестно.
    * **дубли** — та же пара «ярлык → лига» записана много раз; оставляем
      одну запись, остальные лишние.

    Родовой, но однозначный ярлык («Premier League» → ENGLAND: Premier
    League) не трогаем: он работает и лигу определяет верно.
    """
    все = rows(conn)
    каноны = {r[0] for r in conn.execute("SELECT canonical_name FROM leagues")}
    по_ярлыку: dict[str, set] = {}
    сколько: dict[tuple, int] = {}
    for r in все:
        по_ярлыку.setdefault(r["alias"], set()).add(r["league"])
        пара = (r["alias"], r["league"])
        сколько[пара] = сколько.get(пара, 0) + 1
    # у спорного ярлыка оставляем самую частую лигу — кроме случая, когда
    # ярлык САМ является названием другой лиги: такой алиас ошибочен целиком
    главная: dict[str, str] = {}
    for alias, лиги in по_ярлыку.items():
        if len(лиги) > 1 and alias not in каноны:
            главная[alias] = max(лиги, key=lambda l: сколько[(alias, l)])
    мусор, конфликт, дубли = [], [], []
    видели: set = set()
    for r in все:
        пара = (r["alias"], r["league"])
        if _NOT_A_LEAGUE.search(r["alias"] or ""):
            мусор.append(r)
        elif len(по_ярлыку[r["alias"]]) > 1 and                 главная.get(r["alias"], "") != r["league"]:
            конфликт.append(r)
        elif пара in видели:
            дубли.append(r)
        else:
            видели.add(пара)
    return {"всего": все, "мусор": мусор, "конфликт": конфликт, "дубли": дубли}


def печать_разбора(разбор: dict) -> None:
    print(f"привязок всего: {len(разбор['всего'])}")
    for имя in ("мусор", "конфликт", "дубли"):
        куча = разбор[имя]
        ярлыки = sorted({r["alias"] for r in куча})
        print(f"   {имя}: записей {len(куча)}, разных ярлыков {len(ярлыки)}")
        for a in ярлыки[:8]:
            куда = sorted({r["league"] for r in куча if r["alias"] == a})
            print(f"      «{a[:40]}» → {', '.join(куда[:3])}")
        if len(ярлыки) > 8:
            print(f"      … и ещё {len(ярлыки) - 8}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--find", default="", help="показать алиасы с этим текстом")
    ap.add_argument("--check", action="store_true",
                    help="разобрать привязки на мусор, конфликты и дубли")
    ap.add_argument("--clean", action="store_true",
                    help="снять мусор и конфликты, схлопнуть дубли")
    ap.add_argument("--drop", default="", help="снять эту привязку целиком")
    ap.add_argument("--apply", action="store_true",
                    help="без него — только показ")
    args = ap.parse_args()

    conn = db.connect()
    try:
        if args.find:
            найдено = rows(conn, "WHERE a.alias LIKE ?", (f"%{args.find}%",))
            print(f"привязок с «{args.find}»: {len(найдено)}")
            for r in найдено:
                print(f"   #{r['id']:>5}  {r['alias']}  →  {r['league']}")
            return 0

        разбор = review(conn)
        if args.check or args.clean:
            печать_разбора(разбор)
        лишние = []
        if args.clean:
            лишние = разбор["мусор"] + разбор["конфликт"] + разбор["дубли"]
        if args.drop:
            лишние = rows(conn, "WHERE a.alias = ?", (args.drop,))
            for r in лишние:
                print(f"   #{r['id']:>5}  {r['alias']}  →  {r['league']}")
        if not лишние:
            print("снимать нечего")
            return 0
        if not args.apply:
            print(f"будет снято записей: {len(лишние)} — добавьте --apply")
            return 0
        conn.executemany("DELETE FROM league_aliases WHERE id = ?",
                         [(r["id"],) for r in лишние])
        # снятая привязка уже успела попасть в сами игры: у события лежит
        # league_id той лиги. Обнуляем — сырой ярлык остаётся, и канон
        # поставит настоящую лигу по эталону при ближайшей сверке
        забыто = 0
        for ярлык in sorted({r["alias"] for r in разбор["мусор"] + разбор["конфликт"]}
                            | ({args.drop} if args.drop else set())):
            забыто += conn.execute(
                "UPDATE events SET league_id = NULL WHERE league_auto = ? "
                "AND league_id IS NOT NULL", (ярлык,)).rowcount
        conn.commit()
        print(f"снято записей: {len(лишние)}; игр отвязано: {забыто}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

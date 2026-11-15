# -*- coding: utf-8 -*-
r"""Книга 142: города теннисных турниров — засеять словарь из истории сборов.

Сервер запоминает города турниров из эталона каждого сбора сам
(`scripts/games_import.py` → `dictionary.remember_cities`). Этот скрипт нужен
один раз — чтобы словарь знал и турниры, которые прошли ДО этого правила:
эталон прошлых сборов лежит в истории git (`results/games.json`).

    python scripts/goroda_turnirov.py                    что уже в словаре базы
    python scripts/goroda_turnirov.py --iz-istorii 4     что даст история (сбор раз в 4 дня) — только показ
    python scripts/goroda_turnirov.py --iz-istorii 4 --apply     записать в базу

Правила:
  Г1. из истории берётся по одному сбору раз в `--iz-istorii` дней: турнир
      идёт неделю, чаще не нужно;
  Г2. из сбора — только теннисные записи эталона, из них тур, город и все
      написания на языках эталона (`broadcast.cities_of`);
  Г3. в базу города только ДОБАВЛЯЮТСЯ (`dictionary.remember_cities`);
  Г4. без `--apply` — показ: сколько городов и какие новые.
В сеть не ходит. На GitHub словарь возит выгрузка `scripts/dict_push.py`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import broadcast, db, dictionary                     # noqa: E402

GAMES = "results/games.json"


def _git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True).stdout


def pick(commits: list[tuple[str, str]], step: int) -> list[str]:
    """Г1: из списка (хеш, день) от нового к старому — по одному сбору раз
    в `step` дней; первый (самый новый) берётся всегда."""
    out, last = [], None
    for sha, day in commits:
        when = date.fromisoformat(day)
        if last is None or (last - when).days >= step:
            out.append(sha)
            last = when
    return out


def history(step: int) -> tuple[dict, int]:
    """Города из истории сборов. → (города, сколько сборов прочитано)."""
    lines = _git("log", "--format=%H %cd", "--date=format:%Y-%m-%d", "--", GAMES).decode().split("\n")
    commits = [tuple(line.split()) for line in lines if line.strip()]
    cities: dict = {}
    used = 0
    for sha in pick(commits, max(1, step)):
        try:
            data = json.loads(_git("show", f"{sha}:{GAMES}").decode("utf-8"))
        except (subprocess.CalledProcessError, ValueError):
            continue
        fresh = broadcast.cities_of(data.get("эталон") if isinstance(data, dict) else None)   # Г2
        if fresh:
            used += 1
            cities, _new = broadcast.merge_cities(cities, fresh)
    return cities, used


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Города теннисных турниров: словарь базы и история сборов")
    ap.add_argument("--iz-istorii", type=int, default=0, metavar="ДНЕЙ",
                    help="собрать города из истории git, по сбору раз в столько дней")
    ap.add_argument("--apply", action="store_true", help="записать найденное в базу")
    args = ap.parse_args()
    conn = db.connect()
    try:
        known = dictionary.learned_cities(conn)
        print(f"в словаре базы городов: {len(known)}")
        if not args.iz_istorii:
            return 0
        found, used = history(args.iz_istorii)
        fresh = sorted(set(found) - set(known))
        print(f"из истории: сборов прочитано {used}, городов {len(found)}, новых для словаря {len(fresh)}")
        if fresh:
            print("   " + ", ".join(fresh))
        if not args.apply:                                                    # Г4
            print("показ; записать — с ключом --apply")
            return 0
        new, total = dictionary.remember_cities(conn, found)                  # Г3
        print(f"записано: новых {new}, всего в словаре {total}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

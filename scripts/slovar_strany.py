# -*- coding: utf-8 -*-
r"""Сторож «страны в словаре команд» (книга 110, аудит 13.11.2026).

Зачем. Сверка живого словаря 13.11 нашла четыре вида записей, которые путают
сборную с другой командой. Словарь растёт на ~240 команд в день, новые такие
записи появляются сами — их надо увидеть в день появления, а не по жалобе.

Что считается (страну написания называет справочник `data/countries.json`,
и только буква в букву — `names.country_exact`):

  А. страна за ЧУЖОЙ сборной: «Island» (Исландия) → Ireland. Словарь такую
     запись не читает (правило С12), в базе она лежит;
  Б. та же страна, другая пометка пола/возраста: «Аргентина U20» →
     Argentina U20 W. Словарь не читает (правило С13);
  В. страна за клубом: «Niger» → Niger Tornadoes, «HRVATSKA» → Canberra
     Croatia. Словарь ЧИТАЕТ: часть таких записей законна (сокращение
     зеркала flashscore), поэтому их решает владелец;
  Г. клуб-тёзка: имя команды словаря буква в букву — написание страны, а
     команда не сборная («Brasilia», «Grecia», «Polonia.», «Kosova»).

Ничего не удаляет и не правит. Без ключей — только показ. С `--note`
запоминает увиденное в настройке базы и, если появились НОВЫЕ записи, пишет
одну строку в «Прогоны» админки (так её видит владелец). Первый запуск
только запоминает.

    venv/bin/python scripts/slovar_strany.py            # показ
    venv/bin/python scripts/slovar_strany.py --note     # сторож (заливка)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary, names, watch          # noqa: E402

#: настройка базы, где сторож помнит уже виденные записи
KNOWN_KEY = "slovar_strany_known"
КЛАССЫ = (("А", "страна за чужой сборной"),
          ("Б", "страна с чужой пометкой пола или возраста"),
          ("В", "страна за клубом"),
          ("Г", "клуб-тёзка страны"))


def collect(conn) -> dict[str, list[tuple[str, str]]]:
    """Класс (буква) → [(написание, команда)], без повторов, по алфавиту."""
    canon_of = {tid: canon for tid, canon in
                conn.execute("SELECT id, canonical_name FROM teams")}
    merged = dictionary.merged_map(conn)
    nation = dictionary.national_teams(canon_of)
    found: dict[str, set] = {буква: set() for буква, _ in КЛАССЫ}
    for alias, team_id in conn.execute(
            "SELECT alias, team_id FROM team_aliases ORDER BY id"):
        if not names.country_exact(alias or ""):
            continue
        tid = merged.get(team_id, team_id)
        canon = canon_of.get(tid) or ""
        if tid in nation:
            if dictionary.foreign_country(alias, nation[tid]):
                found["А"].add((alias, canon))
            elif dictionary.wrong_mark(alias, canon):
                found["Б"].add((alias, canon))
        else:
            found["В"].add((alias, canon))
    for tid, canon in canon_of.items():
        if tid in merged or tid in nation or not canon:
            continue
        if names.country_exact(canon):
            found["Г"].add((canon, names.country_exact(canon)))
    return {буква: sorted(found[буква]) for буква, _ in КЛАССЫ}


def keys(report: dict) -> set[str]:
    return {f"{буква}|{a}|{b}" for буква, rows in report.items()
            for a, b in rows}


def summary(report: dict) -> str:
    return ", ".join(f"{имя} — {len(report[буква])}" for буква, имя in КЛАССЫ)


def note_new(conn, report: dict) -> list[str]:
    """Запомнить увиденное; вернуть новые записи (первый запуск — пусто).
    Новые есть — строка в «Прогоны»."""
    now = keys(report)
    saved = db.get_setting(conn, KNOWN_KEY, "")
    try:
        known = set(json.loads(saved)) if saved else None
    except ValueError:
        known = None
    new = sorted(now - known) if known is not None else []
    if known is None or new or (known - now):
        db.set_setting(conn, KNOWN_KEY,
                       json.dumps(sorted(now), ensure_ascii=False))
        conn.commit()
    if new:
        имена = dict(КЛАССЫ)
        показ = "; ".join(
            f"{имена[x.split('|')[0]]}: «{x.split('|')[1]}» → {x.split('|')[2]}"
            for x in new[:8])
        watch.note(conn, f"словарь и страны: новых записей {len(new)} — "
                         f"{показ}{' …' if len(new) > 8 else ''}",
                   who="сторож словаря")
    return new


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--note", action="store_true",
                    help="запомнить и записать новые в «Прогоны»")
    ap.add_argument("--full", action="store_true", help="показать все записи")
    args = ap.parse_args()
    conn = db.connect()
    try:
        report = collect(conn)
        print("словарь и страны:", summary(report))
        if args.full:
            for буква, имя in КЛАССЫ:
                print(f"\n{буква}. {имя}: {len(report[буква])}")
                for a, b in report[буква]:
                    print(f"   «{a}» → {b}")
        if args.note:
            new = note_new(conn, report)
            print("   новых с прошлого раза:", len(new))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

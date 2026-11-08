# -*- coding: utf-8 -*-
r"""Отчёт по словарю команд — ТОЛЬКО ЧТЕНИЕ (карточка словаря 09.11.2026, шаг 1).

Зачем: решение владельца 08.11 — ничего не удалять, ошибки словаря — в книгу
ошибок, дубли клубов — слить, двусмысленные имена — по языку сайта. Прежде
чем что-то менять, владелец смотрит ДВА списка из этого отчёта: кандидаты на
слияние (С) и коллизии разных клубов (К). База открывается в режиме
только-чтение, скрипт ничего не пишет.

    venv/bin/python scripts/slovar_otchet.py            # на экран
    venv/bin/python scripts/slovar_otchet.py --out otchet.md --limit 50

Классы написаний (`team_aliases`, ключ alias+lang) — как в карточке:
  Д  двусмысленное: одно написание ведёт к нескольким РАЗНЫМ клубам;
  П  пара матча записана как имя («A - B», «A – B», «A vs B», «A v B»,
     пробелы по обе стороны — иначе это одна команда `Fleury-Merogis`);
  Л  лига впереди имени («Nogomet: Cibalia») — рабочее написание, оставить;
  К  написание = каноническое имя ДРУГОЙ команды, клубы разные
     (сходство < SAME_CLUB) — коллизия, ведёт матч не туда;
  С  то же, но клуб тот же (сходство ≥ SAME_CLUB) — одна команда записана
     дважды, кандидат на слияние;
  Дк дубли канонов буква в букву (без регистра) — тоже слияние.

Выживший при слиянии (С, Дк) — у кого имя эталона flashscore: больше
написаний С ЯЗЫКОМ (их пишет сверка с эталоном, `canon.py`), при равенстве —
больше событий, затем больше написаний всего, затем короче имя.
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), os.getcwd()):           # скрипт могут запустить и вне репо
    if p not in sys.path:
        sys.path.insert(0, p)

from app import db, names                                   # noqa: E402
from app.dictionary import SAME_CLUB                        # noqa: E402

PAIR_RE = re.compile(r"\S\s+(?:-|–|—|vs\.?|v)\s+\S", re.IGNORECASE)
LEAGUE_RE = re.compile(r"\S:\s+\S")


def open_ro() -> sqlite3.Connection:
    """База только для чтения: отчёт не имеет права ничего менять."""
    path = db.db_path()
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def is_pair(text: str) -> bool:
    return bool(PAIR_RE.search(text or ""))


def is_league_first(text: str) -> bool:
    return bool(LEAGUE_RE.search(text or ""))


def collect(conn: sqlite3.Connection) -> dict:
    teams = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, canonical_name, country FROM teams")}
    by_canon_ci: dict[str, list[int]] = defaultdict(list)
    for tid, t in teams.items():
        by_canon_ci[t["canonical_name"].casefold()].append(tid)
    events: dict[int, int] = defaultdict(int)
    for r in conn.execute("SELECT team_home_id AS a, team_away_id AS b FROM events"):
        for tid in (r["a"], r["b"]):
            if tid:
                events[tid] += 1
    aliases = [dict(r) for r in conn.execute(
        "SELECT alias, lang, team_id FROM team_aliases ORDER BY id")]
    alias_total: dict[int, int] = defaultdict(int)
    alias_lang: dict[int, int] = defaultdict(int)
    owners: dict[str, set[int]] = defaultdict(set)
    owners_nolang: dict[str, set[int]] = defaultdict(set)
    for a in aliases:
        alias_total[a["team_id"]] += 1
        if a["lang"]:
            alias_lang[a["team_id"]] += 1
        owners[a["alias"]].add(a["team_id"])
        if not a["lang"]:
            owners_nolang[a["alias"]].add(a["team_id"])

    def clubs(ids: set[int]) -> int:
        canons = [teams[i]["canonical_name"] for i in ids if i in teams]
        groups: list[list[str]] = []
        for name in canons:
            for g in groups:
                if any(names.similarity(name, o) >= SAME_CLUB for o in g):
                    g.append(name)
                    break
            else:
                groups.append([name])
        return len(groups)

    out: dict = {"команд": len(teams), "написаний": len(aliases),
                 "команд_в_событиях": len(events)}
    out["Д"] = sorted(((al, sorted(teams[i]["canonical_name"] for i in ids if i in teams))
                       for al, ids in owners.items()
                       if len(ids) > 1 and clubs(ids) > 1), key=lambda x: -len(x[1]))
    out["Д_без_языка"] = sum(1 for al, ids in owners_nolang.items()
                             if len(ids) > 1 and clubs(ids) > 1)
    out["П"] = [(a["alias"], a["lang"], teams[a["team_id"]]["canonical_name"])
                for a in aliases if a["team_id"] in teams and is_pair(a["alias"])]
    out["П_каноны"] = [(tid, t["canonical_name"], events.get(tid, 0))
                       for tid, t in teams.items() if is_pair(t["canonical_name"])]
    out["Л"] = sum(1 for a in aliases
                   if is_league_first(a["alias"]) and not is_pair(a["alias"]))

    def score(tid: int) -> tuple:
        return (alias_lang[tid], events.get(tid, 0), alias_total[tid],
                -len(teams[tid]["canonical_name"]))

    seen_pairs: set[tuple[int, int]] = set()
    kol: list[tuple] = []
    sli: list[tuple] = []
    for a in aliases:
        tid = a["team_id"]
        if tid not in teams:
            continue
        for other in by_canon_ci.get(a["alias"].casefold(), []):
            if other == tid:
                continue
            key = (min(tid, other), max(tid, other))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            me, him = teams[tid]["canonical_name"], teams[other]["canonical_name"]
            sim = names.similarity(me, him)
            if sim >= SAME_CLUB:
                win, lose = (tid, other) if score(tid) >= score(other) else (other, tid)
                sli.append((teams[win]["canonical_name"], teams[lose]["canonical_name"], sim,
                            f"язык {alias_lang[win]}/{alias_lang[lose]}, событий "
                            f"{events.get(win, 0)}/{events.get(lose, 0)}, написаний "
                            f"{alias_total[win]}/{alias_total[lose]}"))
            else:
                kol.append((a["alias"], a["lang"], me, him, sim))
    out["К"] = sorted(kol, key=lambda x: (x[0], x[1] or ""))
    out["С"] = sorted(sli)
    out["Дк"] = [[teams[i]["canonical_name"] for i in ids]
                 for ids in by_canon_ci.values() if len(ids) > 1]
    return out


def render(r: dict, limit: int) -> str:
    L: list[str] = []
    w = L.append
    w("# Отчёт по словарю команд (только чтение)\n")
    w("| Что | Сколько |\n|---|---|")
    w(f"| команд | {r['команд']} (в событиях {r['команд_в_событиях']}) |")
    w(f"| написаний | {r['написаний']} |")
    w(f"| Д двусмысленных написаний (разные клубы) | {len(r['Д'])}, без языка {r['Д_без_языка']} |")
    w(f"| П пара как имя | {len(r['П'])} написаний, {len(r['П_каноны'])} канонов |")
    w(f"| Л лига впереди (оставить) | {r['Л']} |")
    w(f"| К коллизии разных клубов | {len(r['К'])} |")
    w(f"| С тот же клуб дважды — слить | {len(r['С'])} |")
    w(f"| Дк дубли канонов | {len(r['Дк'])} |\n")
    w(f"## С — кандидаты на слияние (выживший ← проигравший), первые {limit}\n")
    w("| Выживший | Проигравший | Сходство | Почему выживший |\n|---|---|---|---|")
    for win, lose, sim, why in r["С"][:limit]:
        w(f"| {win} | {lose} | {sim} | {why} |")
    w(f"\n## К — коллизии: написание ведёт на чужой клуб, первые {limit}\n")
    w("| Написание | Язык | Ведёт на | А это имя команды | Сходство |\n|---|---|---|---|---|")
    for al, lang, me, him, sim in r["К"][:limit]:
        w(f"| {al} | {lang or '—'} | {me} | {him} | {sim} |")
    w("\n## П — ложные каноны-пары (событий на каждом)\n")
    for tid, name, ev in r["П_каноны"]:
        w(f"- {name} (id {tid}, событий {ev})")
    w(f"\n## Д — двусмысленные, первые {limit}\n")
    for al, canons in r["Д"][:limit]:
        w(f"- {al} → {', '.join(canons)}")
    w("\n## Дк — дубли канонов\n")
    for group in r["Дк"]:
        w(f"- {' / '.join(group)}")
    return "\n".join(L) + "\n"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="", help="записать отчёт в файл (markdown)")
    ap.add_argument("--limit", type=int, default=40, help="строк в каждом списке")
    args = ap.parse_args()
    conn = open_ro()
    try:
        text = render(collect(conn), args.limit)
    finally:
        conn.close()
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"отчёт записан: {args.out} ({text.count(chr(10))} строк)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

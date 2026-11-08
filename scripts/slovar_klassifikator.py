# -*- coding: utf-8 -*-
r"""Классификатор словаря команд — шаг 4 карточки словаря 09.11.2026.

Разовый прогон по базе. Решение владельца 08.11: ничего не удалять — ошибки
в книгу ошибок (`dictionary_errors`), дубли клубов — слить с сохранением
написаний; 09.11 — «разобрать максимально всё, чтобы владельца не спрашивать
о том, что и так понятно». Ни одна строка `team_aliases`/`teams` не стирается.

    venv/bin/python scripts/slovar_klassifikator.py              # показ: цифры, база не меняется
    venv/bin/python scripts/slovar_klassifikator.py --spisok s.md  # и список слияний в файл
    venv/bin/python scripts/slovar_klassifikator.py --apply      # записать (после копии базы и «да»)

Правила по порядку:

  К1. Слияние того же клуба (правило С6) — ПЕРВЫМ: карантин держит запись по
      команде, а слияние у записей команду меняет. Пары и решение по ним —
      из `slovar_otchet.collect` (функция `decide` перенесена туда как есть,
      одно правило в одном месте): «сливать точно» и «сливать по уликам» —
      сливать; «возможный дубль» — в книгу этим классом, команды не трогать;
      «тёзки по виду», «Д: голое имя», «разные: …» — не трогать. Дубли
      канонов буква в букву (Дк) решает тот же `decide`.
  К2. Выживший — у кого больше написаний с языком (их пишет только сверка с
      эталоном flashscore), затем больше событий, больше написаний, короче
      имя (`_выживший` отчёта). Написания проигравшего переезжают к
      выжившему; такое же написание (alias, lang) у выжившего уже есть —
      запись проигравшего остаётся на месте и идёт в книгу «слито». События
      (`team_home_id`, `team_away_id`) — на выжившего. У проигравшего
      `teams.merged_into` = выживший; кто был слит в проигравшего — тоже на
      выжившего (без цепочек).
  К3. Слияние повторяется кругами, пока находится новое (не больше
      `КРУГОВ`): переехавшие написания дают новые улики — второй прогон
      скрипта уже ничего не сливает (С7).
  К4. Пара как имя (П) — карантин «пара»: написание-пара («A - B», «A vs B»,
      `dictionary.is_pair_name`) и все написания команды с каноном-парой.
  К5. Коллизия (К) — написание X у команды A равно канону другой команды B,
      а сходство A и B ниже `SAME_CLUB` — карантин «коллизия» (alias, lang, A),
      правда — B. Карантин и пары, и коллизии — на состоянии ПОСЛЕ слияний.
  К6. Повтор ничего не портит (С7, С9): книга не плодит строк — второй
      прогон даёт 0 новых строк и 0 переездов.
  К7. Без `--apply` — показ на копии базы во временной папке: те же цифры,
      живая база не меняется вовсе (даже схема).
  К8. Сверка «игр старым/новым словарём»: у живых игр (`events`) имя на
      витрине до и после — сколько игр поменяли имя и какие.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app import db, dictionary, names  # noqa: E402
from app.dictionary import SAME_CLUB  # noqa: E402
import slovar_otchet  # noqa: E402

#: К3: кругов слияния самое большее (замер 09.11 на копии — хватает двух)
КРУГОВ = 5
#: вердикты `decide`, по которым сливаем (К1)
СЛИВАТЬ = ("сливать точно", "сливать по уликам")
ВОЗМОЖНЫЙ_ДУБЛЬ = "возможный дубль"


# ── К1–К3: слияние ───────────────────────────────────────────────────────────

def _merge(conn: sqlite3.Connection, win: int, lose: int, why: str) -> Counter:
    """К2: команда `lose` сливается в `win`. Ничего не стирается."""
    got = Counter()
    win_name = conn.execute("SELECT canonical_name FROM teams WHERE id = ?", (win,)).fetchone()[0]
    lose_name = conn.execute("SELECT canonical_name FROM teams WHERE id = ?", (lose,)).fetchone()[0]
    for a in conn.execute("SELECT id, alias, lang FROM team_aliases WHERE team_id = ?",
                          (lose,)).fetchall():
        if conn.execute("SELECT 1 FROM team_aliases WHERE team_id = ? AND alias = ? "
                        "AND lang IS ?", (win, a["alias"], a["lang"])).fetchone():
            if dictionary.note_error(conn, a["alias"], "слито", lang=a["lang"], team_id=lose,
                                     led_to=lose_name, truth=win_name,
                                     note=f"такое же написание уже у выжившего; {why}"):
                got["книга: слито"] += 1
            got["написание осталось у проигравшего"] += 1
        else:
            conn.execute("UPDATE team_aliases SET team_id = ? WHERE id = ?", (win, a["id"]))
            got["написаний переехало"] += 1
    got["событий переехало"] += conn.execute(
        "UPDATE events SET team_home_id = ? WHERE team_home_id = ?", (win, lose)).rowcount
    got["событий переехало"] += conn.execute(
        "UPDATE events SET team_away_id = ? WHERE team_away_id = ?", (win, lose)).rowcount
    conn.execute("UPDATE teams SET merged_into = ? WHERE merged_into = ?", (win, lose))
    conn.execute("UPDATE teams SET merged_into = ? WHERE id = ?", (win, lose))
    got["слияний"] += 1
    return got


def merge_round(conn: sqlite3.Connection, plan: list | None = None) -> Counter:
    """Один круг К1–К2 по текущему состоянию базы. `plan` — куда записать
    слияния (выживший, проигравший, вердикт, почему) для списка владельцу."""
    report = slovar_otchet.collect(conn)
    decide, survivor, teams = report["_решить"], report["_выживший"], report["_команды"]
    pairs = [(x, y, langs) for x, y, _sim, langs in report["_пары"]]
    for ids in report["_дк"]:                                 # дубли канонов
        pairs += [(ids[0], other, frozenset()) for other in ids[1:]]
    got = Counter()
    gone: set[int] = set()                    # слиты в этом круге — в следующем
    for x, y, langs in pairs:
        if x in gone or y in gone or x not in teams or y not in teams:
            continue
        verdict, why = decide(x, y, langs)
        if verdict == ВОЗМОЖНЫЙ_ДУБЛЬ:
            if dictionary.note_error(conn, teams[y]["canonical_name"], ВОЗМОЖНЫЙ_ДУБЛЬ,
                                     team_id=x, led_to=teams[x]["canonical_name"],
                                     truth=teams[y]["canonical_name"], note=why):
                got["книга: возможный дубль"] += 1
            continue
        if verdict not in СЛИВАТЬ:
            continue
        win, lose = survivor(x, y)
        got.update(_merge(conn, win, lose, f"{verdict}: {why}"))
        got[verdict] += 1
        gone.add(lose)
        if plan is not None:
            plan.append((teams[win]["canonical_name"], teams[lose]["canonical_name"],
                         verdict, why))
    return got


# ── К4–К5: карантин ──────────────────────────────────────────────────────────

def quarantine(conn: sqlite3.Connection) -> Counter:
    """Пары как имя (К4) и коллизии (К5) — в книгу ошибок классами карантина.
    Только активные команды (не слитые)."""
    got = Counter()
    teams = {r["id"]: r["canonical_name"] for r in conn.execute(
        "SELECT id, canonical_name FROM teams WHERE merged_into IS NULL")}
    by_canon: dict[str, list[int]] = {}
    for tid, canon in teams.items():
        by_canon.setdefault(canon.casefold(), []).append(tid)
    for a in conn.execute("SELECT alias, lang, team_id FROM team_aliases "
                          "ORDER BY id").fetchall():
        tid = a["team_id"]
        if tid not in teams:
            continue
        me = teams[tid]
        if dictionary.is_pair_name(a["alias"]) or dictionary.is_pair_name(me):
            what = ("написание — пара матча" if dictionary.is_pair_name(a["alias"])
                    else "каноническое имя команды — пара матча")
            if dictionary.note_error(conn, a["alias"], "пара", lang=a["lang"], team_id=tid,
                                     led_to=me, note=what):
                got["книга: пара"] += 1
            continue
        for other in by_canon.get(a["alias"].casefold(), []):
            him = teams[other]
            if other == tid or dictionary.is_pair_name(him):
                continue
            sim = names.similarity(me, him)
            if sim >= SAME_CLUB:
                continue                      # тот же клуб? решает слияние (К1)
            if dictionary.note_error(conn, a["alias"], "коллизия", lang=a["lang"],
                                     team_id=tid, led_to=me, truth=him,
                                     note=f"написание = имя другой команды, сходство {sim}"):
                got["книга: коллизия"] += 1
    return got


# ── К8: сверка «игр старым/новым словарём» ──────────────────────────────────

def shown_names(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    """Имя игры на витрине (как `store.schedule`): канон команды, иначе
    бесспорное написание словаря, иначе догадка транслитом."""
    known = dictionary.team_overrides(conn)

    def show(canon, raw):
        raw = (raw or "").strip()
        return canon or known.get(raw) or names.suggest_canonical(raw)

    return {r["id"]: (show(r["h"], r["team_home_auto"]), show(r["a"], r["team_away_auto"]))
            for r in conn.execute(
                "SELECT e.id, e.team_home_auto, e.team_away_auto, "
                "th.canonical_name AS h, ta.canonical_name AS a FROM events e "
                "LEFT JOIN teams th ON th.id = e.team_home_id "
                "LEFT JOIN teams ta ON ta.id = e.team_away_id")}


# ── прогон ───────────────────────────────────────────────────────────────────

def run(conn: sqlite3.Connection, plan: list | None = None) -> dict:
    """К1–К6 по базе `conn` (в транзакции; фиксирует вызывающий)."""
    db.init_db(conn)
    before = shown_names(conn)
    total = Counter()
    rounds = []
    for _ in range(КРУГОВ):
        got = merge_round(conn, plan)
        rounds.append(got["слияний"])
        total.update(got)
        if not got["слияний"]:
            break
    total.update(quarantine(conn))
    after = shown_names(conn)
    changed = [(eid, before[eid], after.get(eid)) for eid in before if before[eid] != after.get(eid)]
    return {"итог": total, "круги": rounds, "игр": len(before), "игр_с_другим_именем": changed}


def show_result(res: dict) -> None:
    t = res["итог"]
    print(f"круги слияния: {res['круги']} (слияний по кругам)")
    for key in ("слияний", "сливать точно", "сливать по уликам", "написаний переехало",
                "написание осталось у проигравшего", "событий переехало",
                "книга: слито", "книга: возможный дубль", "книга: пара", "книга: коллизия"):
        print(f"  {key}: {t.get(key, 0)}")
    print(f"игр в базе: {res['игр']}, имя на витрине поменялось у {len(res['игр_с_другим_именем'])}")
    for eid, old, new in res["игр_с_другим_именем"][:15]:
        print(f"  #{eid}: {old[0]} — {old[1]}  →  {new[0]} — {new[1]}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Классификатор словаря команд (шаг 4 карточки)")
    ap.add_argument("--apply", action="store_true", help="записать в базу (после копии и «да»)")
    ap.add_argument("--spisok", default="", help="записать список слияний в файл (markdown)")
    args = ap.parse_args()
    target = Path(db.db_path())
    if not target.exists():
        print(f"нет базы {target}")
        return 1
    work = target
    tmp = None
    if not args.apply:                                   # К7: показ — на копии
        tmp = Path(tempfile.mkdtemp(prefix="slovar-klass-"))
        work = tmp / "kopiya.db"
        src = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        dst = sqlite3.connect(work)
        src.backup(dst)
        src.close()
        dst.close()
    os.environ["STREAMS_DB"] = str(work)
    conn = db.connect(db.BUSY_TIMEOUT_SCRIPT)
    plan: list = []
    try:
        res = run(conn, plan)
        conn.commit()
    finally:
        conn.close()
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    print(("ЗАПИСАНО в " if args.apply else "ПОКАЗ (база не менялась): ") + str(target))
    show_result(res)
    if args.spisok:
        lines = ["# Слияния словаря команд (классификатор, шаг 4)\n",
                 "| Выживший | Проигравший | Вердикт | Почему |", "|---|---|---|---|"]
        lines += [f"| {w} | {l} | {v} | {why} |" for w, l, v, why in plan]
        Path(args.spisok).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"список слияний: {args.spisok} ({len(plan)} строк)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
r"""Проверка перед выкладкой — одной командой (книга случаев, владелец
13.10.2026: «чтоб новое не ломало старое»). Красный итог — в main не
выкладывать. Правила по порядку:

1. Все тесты `scripts/test_*.py` — каждый в своём процессе, без локальной
   базы. Упал только замер скорости («скорость:» в имени) — жёлтый: пишется,
   но не держит (время зависит от машины).
2. Каждый тест записан хотя бы в один случай книги (`kniga/cases`): новая
   возможность без случая в книге — красный («добавь случай»).
3. Книга случаев (`scripts/kniga.py`) — все случаи зелёные.
4. С `--sravnit <папка сбора>` — последний сбор разбирается старым кодом
   (`--base`, по умолчанию origin/main) и новым, с часами на моменте сбора.
   Новое и изменённое — печатается. ПОТЕРЯ (игра пропала или у игры пропал
   канал) — красный, если её не объясняет случай книги с «нет» или «снято»
   (та же пара ±3 ч, тот же сайт): задуманное снятие сперва пишется в книгу.

В сеть не ходит (сбор берётся готовым: `github_run.py fetch --run N`).
    python scripts/proverka.py                     # тесты + книга, ~3 мин
    python scripts/proverka.py --sravnit recon/raw_live --base origin/main
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import kniga  # noqa: E402

#: разбор полного сбора идёт 6–9 минут; дольше — завис
РАЗБОР_ТАЙМАУТ_С = 40 * 60

# разбор чужим (старым) деревом: его parse_live зовём как есть, часы стоят
_PARSE_AT = r"""
import os, runpy, sys, time_machine
from datetime import datetime, timezone
tree, folder, clock, window, out = sys.argv[1:6]
sys.path[:0] = [tree, os.path.join(tree, "scripts")]
os.chdir(tree)
moment = datetime.fromisoformat(clock.replace(" ", "T")).replace(tzinfo=timezone.utc)
sys.argv = ["parse_live.py", "--dir", folder, "--days", window,
            "--md", os.path.join(out, "matches.md")]
with time_machine.travel(moment, tick=False):
    try:
        runpy.run_path(os.path.join(tree, "scripts", "parse_live.py"), run_name="__main__")
    except SystemExit as e:
        sys.exit(e.code)
"""


# --- 1–2. тесты -----------------------------------------------------------

def all_tests() -> list[str]:
    return sorted(p.name for p in (ROOT / "scripts").glob("test_*.py"))


def run_tests() -> tuple[list[str], list[str]]:
    """→ (красные, жёлтые). По очереди, не разом: параллельный прогон грузит
    машину, и замеры скорости ложно желтеют."""
    red, yellow = [], []
    for name in all_tests():
        status, log = kniga.run_test(name)
        mark = {kniga.ЗЕЛЁНЫЙ: "✅", kniga.ЖЁЛТЫЙ: "🟡"}.get(status, "❌")
        print(f"{mark} {name}")
        if status != kniga.ЗЕЛЁНЫЙ:
            print(f"     ✗ {kniga.failed_lines(log)}")
        if status == kniga.КРАСНЫЙ:
            red.append(name)
        elif status == kniga.ЖЁЛТЫЙ:
            yellow.append(name)
    return red, yellow


def tests_without_case() -> list[str]:
    """Правило 2: тест, на который не ссылается ни один случай книги."""
    used = set()
    for case in kniga.load_cases():
        used.update(case.get("тесты") or [])
    return [t for t in all_tests() if t not in used]


# --- 4. старый и новый код на последнем сборе ------------------------------

def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout.strip()


def parse_with(tree: Path, folder: Path, clock: str, window: int, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", STREAMS_DB=str(out / "none.db"))
    run = subprocess.run([sys.executable, "-X", "utf8", "-c", _PARSE_AT, str(tree),
                          str(folder), clock, str(window), str(out)],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env, timeout=РАЗБОР_ТАЙМАУТ_С)
    (out / "log.txt").write_text(run.stdout + run.stderr, encoding="utf-8")
    games = out / "games.json"
    if not games.exists():
        raise RuntimeError(f"разбор кодом {tree} упал: "
                           + (run.stdout + run.stderr).strip()[-600:])
    return json.loads(games.read_text(encoding="utf-8"))


def _key(g: dict) -> tuple:
    return (g["start_kyiv"], g["home"], g["away"])


def _chans(g: dict) -> set:
    return {(e.get("channel") or "", kniga.bare(e.get("source") or ""))
            for e in g.get("entries") or []}


def explained(game: dict, site: str = "") -> str:
    """Номер случая книги, который объясняет потерю этой игры (или канала
    этого сайта у неё): «нет»/«снято» с той же парой ±3 ч и тем же сайтом."""
    when = kniga.kyiv(game["start_kyiv"])
    for case in kniga.load_cases():
        for exp in case.get("ждём") or []:
            text = exp.get("нет") or exp.get("снято")
            if not text or not exp.get("время"):
                continue
            if abs(kniga.kyiv(exp["время"]) - when) > timedelta(hours=kniga.ОКНО_НЕТ_Ч):
                continue
            if exp.get("сайт") and site and kniga.bare(exp["сайт"]) != site:
                continue
            if exp.get("сайт") and not site and not any(
                    s == kniga.bare(exp["сайт"]) for _, s in _chans(game)):
                continue
            if kniga.pair_score(game, text) >= kniga.ПОРОГ_ПАРЫ:
                return str(case.get("номер"))
    return ""


#: та же пара сдвинулась во времени не дальше этого — переезд, а не потеря
#: (сбор #249: Al Ittihad — Al Shabab 19:55 → 20:55, ближе к эталону)
СДВИГ_Ч = 3


def twin(gone: dict, fresh: list[dict]) -> tuple[dict | None, str]:
    """Та же игра в новом разборе, если не нашлась по имени и времени:
    «имя» — пара та же (словарь перевёл, сверка поправила), начало ±10 мин;
    «время» — пара та же, начало сдвинулось не дальше СДВИГ_Ч."""
    from app import canon
    when = kniga.kyiv(gone["start_kyiv"])
    same = [g for g in fresh
            if canon._pair_score(gone, {"home": g["home"], "away": g["away"]}) >= kniga.ПОРОГ_ПАРЫ]
    near = sorted(same, key=lambda g: abs(kniga.kyiv(g["start_kyiv"]) - when))
    for g in near:
        shift = abs(kniga.kyiv(g["start_kyiv"]) - when)
        if shift <= timedelta(minutes=kniga.ДОПУСК_МИН):
            return g, "имя"
        if shift <= timedelta(hours=СДВИГ_Ч):
            return g, "время"
    return None, ""


def compare(old: dict, new: dict) -> list[str]:
    """Печатает разницу, → потери без объяснения в книге."""
    a = {_key(g): g for g in old.get("games") or []}
    b = {_key(g): g for g in new.get("games") or []}
    print(f"игр: старым кодом {len(a)}, новым {len(b)}")
    losses = []
    pairs = [(a[k], b[k]) for k in sorted(set(a) & set(b))]
    fresh = [b[k] for k in sorted(set(b) - set(a))]
    for k in sorted(set(a) - set(b)):
        same, how = twin(a[k], fresh)
        if same:
            fresh.remove(same)
            to = (f"{same['home']} — {same['away']}" if how == "имя"
                  else same["start_kyiv"].replace("T", " "))
            print(f"  ~ {how}: {kniga._show(a[k])} → {to}")
            pairs.append((a[k], same))
            continue
        why = explained(a[k])
        if why:
            print(f"  − пропала (так и надо, случай {why}): {kniga._show(a[k])}")
        else:
            print(f"  ✗ ПРОПАЛА: {kniga._show(a[k])}")
            losses.append(f"пропала игра {kniga._show(a[k])}")
    for g in fresh:
        print(f"  + новая игра: {kniga._show(g)}")
    for was, now in pairs:
        lost, got = _chans(was) - _chans(now), _chans(now) - _chans(was)
        for ch, site in sorted(got):
            print(f"  + канал {ch}/{site}: {kniga._show(now)}")
        for ch, site in sorted(lost):
            why = explained(was, site)
            if why:
                print(f"  − канал {ch}/{site} снят (случай {why}): {kniga._show(was)}")
            else:
                print(f"  ✗ ПРОПАЛ КАНАЛ {ch}/{site}: {kniga._show(was)}")
                losses.append(f"пропал канал {ch}/{site} у {kniga._show(was)}")
    sa = {(o["домен"], o["заголовок"], o["start_kyiv"]) for o in old.get("снято") or []}
    sb = {(o["домен"], o["заголовок"], o["start_kyiv"]) for o in new.get("снято") or []}
    for x in sorted(sb - sa):
        print(f"  снято теперь (раньше нет): {x[2]} {x[0]} «{x[1][:70]}»")
    for x in sorted(sa - sb):
        print(f"  больше не снимается: {x[2]} {x[0]} «{x[1][:70]}»")
    return losses


def compare_run(folder: Path, base: str, keep: Path | None = None) -> list[str]:
    """Правило 4. → потери без объяснения. `keep` — сохранить оба разбора
    (`old.json`, `new.json`), чтобы сравнить ещё раз без 10 минут разбора:
    `--compare <keep>/old.json <keep>/new.json`."""
    games = json.loads((folder / "games.json").read_text(encoding="utf-8"))
    clock, window = games["собрано"], int(games.get("окно") or 6)
    sha = _git("rev-parse", "--short", base)
    print(f"\nсбор {folder.name}: часы {clock} UTC, окно {window}; старый код {base} ({sha})")
    tmp = Path(tempfile.mkdtemp(prefix="proverka-"))
    old_tree = tmp / "old"
    _git("worktree", "add", "--detach", str(old_tree), sha)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fo = pool.submit(parse_with, old_tree, folder, clock, window, tmp / "out-old")
            fn = pool.submit(parse_with, ROOT, folder, clock, window, tmp / "out-new")
            old, new = fo.result(), fn.result()
        if keep:
            keep.mkdir(parents=True, exist_ok=True)
            shutil.copy(tmp / "out-old" / "games.json", keep / "old.json")
            shutil.copy(tmp / "out-new" / "games.json", keep / "new.json")
        return compare(old, new)
    finally:
        _git("worktree", "remove", "--force", str(old_tree))
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sravnit", help="папка скачанного сбора (report.json, games.json, страницы)")
    ap.add_argument("--base", default="origin/main", help="старый код для сравнения")
    ap.add_argument("--keep", help="сохранить оба разбора сбора в эту папку")
    ap.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"),
                    help="только сравнить два сохранённых разбора (games.json)")
    args = ap.parse_args()

    if args.compare:
        old, new = (json.loads(Path(p).read_text(encoding="utf-8")) for p in args.compare)
        losses = compare(old, new)
        print(f"\nпотерь без случая в книге: {len(losses)}")
        return 1 if losses else 0

    print("— тесты —")
    red_tests, yellow_tests = run_tests()
    orphans = tests_without_case()
    print("\n— книга случаев —")
    total, red_cases, yellow_cases = kniga.run_book()
    losses = (compare_run(Path(args.sravnit), args.base,
                          Path(args.keep) if args.keep else None)
              if args.sravnit else [])

    red = []
    if red_tests:
        red.append(f"тесты красные: {', '.join(red_tests)}")
    if orphans:
        red.append(f"тест без случая в книге: {', '.join(orphans)} — добавь случай (kniga/README.md)")
    if red_cases:
        red.append(f"книга: красных {len(red_cases)}")
    if losses:
        red.append(f"на последнем сборе потери без случая в книге: {len(losses)}")
    print()
    for line in red:
        print("✗ " + line)
    yellow = yellow_tests + [y for y in yellow_cases]
    tail = (f"; жёлтые (только скорость): {', '.join(sorted(set(yellow_tests)))}"
            if yellow_tests else "")
    if red:
        print(f"ИТОГ: КРАСНЫЙ — выкладывать нельзя{tail}")
        return 1
    compared = "; старый и новый код на сборе — без потерь" if args.sravnit else ""
    print(f"ИТОГ: зелёный — тестов {len(all_tests())}, {kniga.summary(total, [], yellow_cases)}"
          f"{compared}{tail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
r"""Шлагбаум выкладки (книга случаев, владелец 13.10.2026: «чтоб новое не
ломало старое»). Его зовёт git перед `push` в main (`scripts/hooks/pre-push`,
включается `git config core.hooksPath <абсолютный путь>/scripts/hooks`).
Правила по порядку — пускает, только если все выполнены:

1. Прогон «Проверка перед выкладкой» на GitHub (`proverka.yml`: тесты,
   книга, старый и новый код на последнем сборе) у САМОГО выкладываемого
   коммита не красный и не идёт.
2. Есть проверенный коммит: зелёный прогон у этого коммита или у его
   родителя (ветки, которую вливаем).
3. От проверенного коммита до выкладываемого (кроме слияний) только
   коммиты АВТОМАТОВ (`БОТЫ`: обход на GitHub, сервер) и только в их файлах
   (`АВТОМАТЫ`: итоги сборов, словари ответов владельца, план) — и ни один
   из них сам не красный на GitHub. Ручная правка плана или словаря идёт
   через проверку, как код.
4. На компьютере выкладываемый коммит — это рабочая папка (HEAD = коммит,
   незакоммиченных правок нет), и `scripts/proverka.py` по ней зелёный.

Порядок работы поэтому такой: ветка (с влитым свежим main) → push ветки →
зелёная проверка на GitHub (~15–25 мин) → `git merge` в main → `git push`.
Обойти (`--no-verify`) — только по прямому слову владельца.

    python scripts/push_gate.py <коммит>      # то же, что делает git
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

WORKFLOW = "proverka.yml"
#: что пишут автоматы, а не код: сбор на GitHub (results/, recon/) и сервер
#: (ответы владельца в словарях дважды в день, план по кнопкам админки) —
#: их коммиты на main проверяет тот же proverka.yml после push
АВТОМАТЫ = ("results/", "recon/", "data/dictionaries.json", "data/crawl_plan.json")
#: кто они: обход на GitHub и сервер (git log --format=%ae)
БОТЫ = ("actions@github.com", "server@streams-schedule.local")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout.strip()


def code_only(names: list[str]) -> list[str]:
    """Из списка изменённых файлов — те, что не пишут автоматы."""
    return [n for n in names if n and not n.startswith(АВТОМАТЫ)]


def not_automata(rows: list[tuple[str, str, list[str]]]) -> list[str]:
    """Правило 3 на готовых данных: (коммит, почта автора, файлы) → что
    мешает: коммит не автомата или файл не автомата."""
    bad = []
    for sha, email, files in rows:
        if email not in БОТЫ:
            bad.append(f"{sha[:7]} — автор {email}, не автомат")
        elif code_only(files):
            bad.append(f"{sha[:7]} — автомат тронул {', '.join(code_only(files)[:3])}")
    return bad


def between(tested: str, sha: str) -> list[tuple[str, str, list[str]]]:
    """Коммиты от проверенного до выкладываемого, без слияний."""
    out = []
    for line in git("log", "--no-merges", "--format=%H %ae", f"{tested}..{sha}").splitlines():
        h, email = line.split(" ", 1)
        files = git("show", "--name-only", "--format=", h).splitlines()
        out.append((h, email.strip(), files))
    return out


def github_verdict(sha: str) -> str:
    """«зелёный» / «идёт» / «красный» / «нет» — прогон proverka.yml у коммита.
    Самый свежий прогон решает: перезапуск после красного может позеленеть."""
    import github_run
    status, data = github_run.call(
        "GET", f"/repos/{github_run.repo_slug()}/actions/workflows/{WORKFLOW}/runs"
               f"?head_sha={sha}&per_page=20")
    if status != 200:
        return f"нет (GitHub ответил {status})"
    runs = sorted(data.get("workflow_runs") or [], key=lambda r: r.get("created_at") or "")
    if not runs:
        return "нет"
    last = runs[-1]
    if last.get("status") != "completed":
        return "идёт"
    return "зелёный" if last.get("conclusion") == "success" else "красный"


def refuse(why: str, details: list[str] = ()) -> int:
    print(f"✗ НЕ ПУЩУ: {why}")
    for line in details:
        print("   ", line)
    print("  что делать: влить свежий main в ветку → push ВЕТКИ → дождаться "
          "зелёной проверки на GitHub (вкладка Actions) → слияние в main → push")
    return 1


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("нужен коммит: python scripts/push_gate.py <коммит>")
        return 2
    sha = git("rev-parse", sys.argv[1])
    print(f"шлагбаум: выкладка {sha[:7]} в main")

    own = github_verdict(sha)                                   # 1
    if own in ("красный", "идёт"):
        return refuse(f"проверка на GitHub у самого коммита — {own}")

    notes = [f"{sha[:7]}: проверка на GitHub — {own}"]
    passed = sha if own == "зелёный" else ""
    if not passed:                                              # 2–3
        for parent in git("rev-list", "--parents", "-n", "1", sha).split()[1:]:
            v = github_verdict(parent)
            notes.append(f"{parent[:7]} (родитель): проверка на GitHub — {v}")
            if v != "зелёный":
                continue
            rows = between(parent, sha)
            bad = not_automata(rows)
            bad += [f"{h[:7]} — автомат, но его проверка на GitHub красная"
                    for h, _, _ in rows if github_verdict(h) == "красный"]
            if bad:
                notes += [f"  после {parent[:7]}: {b}" for b in bad[:6]]
                continue
            passed = parent
            break
    if not passed:
        return refuse("нет зелёной «Проверки перед выкладкой» на GitHub для этого кода", notes)
    print(f"✓ GitHub: проверка зелёная у {passed[:7]}")

    head = git("rev-parse", "HEAD")                             # 4
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if head != sha or dirty:
        return refuse("на компьютере проверяется рабочая папка, а она — не этот коммит",
                      [f"HEAD {head[:7]}, выкладывается {sha[:7]}"] + dirty.splitlines()[:5])
    run = subprocess.run([sys.executable, "-X", "utf8", "scripts/proverka.py"],
                         cwd=str(ROOT), capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    tail = [ln for ln in run.stdout.splitlines() if ln.startswith(("✗", "ИТОГ", "❌"))]
    for line in tail[-12:]:
        print("   ", line)
    if run.returncode != 0:
        return refuse("проверка на компьютере красная")
    print("✓ пропускаю в main")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

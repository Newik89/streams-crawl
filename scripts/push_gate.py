# -*- coding: utf-8 -*-
r"""Шлагбаум выкладки (книга случаев, владелец 13.10.2026: «чтоб новое не
ломало старое»). Его зовёт git перед `push` в main (`scripts/hooks/pre-push`,
включается `git config core.hooksPath scripts/hooks`). Пускает, только если:

1. Здесь, на компьютере, `scripts/proverka.py` зелёный (все тесты + книга).
2. На GitHub прогон «Проверка перед выкладкой» (`proverka.yml`, он же
   сравнивает старый и новый код на последнем сборе) ЗЕЛЁНЫЙ у этого коммита
   или у его родителя (ветки, которую вливаем), и от проверенного коммита до
   выкладываемого менялись только файлы автоматов (`АВТОМАТЫ`: итоги сборов,
   словари и план, которые пушит сервер). Иначе — не пускает и пишет, что
   делать: push ветки → дождаться зелёной проверки → слияние → push main.

Порядок работы поэтому такой: ветка → push ветки → зелёная проверка на
GitHub (~15–25 мин) → `git merge` в main → `git push` (шлагбаум пропустит).
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
#: проверку их коммитов на main делает тот же proverka.yml после push сервера
АВТОМАТЫ = ("results/", "recon/", "data/dictionaries.json", "data/crawl_plan.json")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout.strip()


def code_only(names: list[str]) -> list[str]:
    """Из списка изменённых файлов — те, что не пишут автоматы."""
    return [n for n in names if n and not n.startswith(АВТОМАТЫ)]


def code_changed(tested: str, sha: str) -> list[str]:
    """Файлы кода, изменённые между проверенным и выкладываемым коммитом."""
    return code_only(git("diff", "--name-only", tested, sha).splitlines())


def github_verdict(sha: str) -> str:
    """«зелёный» / «идёт» / «красный» / «нет» — прогон proverka.yml у коммита."""
    import github_run
    status, data = github_run.call(
        "GET", f"/repos/{github_run.repo_slug()}/actions/workflows/{WORKFLOW}/runs"
               f"?head_sha={sha}&per_page=20")
    if status != 200:
        return f"нет (GitHub ответил {status})"
    runs = data.get("workflow_runs") or []
    if any(r.get("conclusion") == "success" for r in runs):
        return "зелёный"
    if any(r.get("status") != "completed" for r in runs):
        return "идёт"
    if runs:
        return "красный"
    return "нет"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("нужен коммит: python scripts/push_gate.py <коммит>")
        return 2
    sha = git("rev-parse", sys.argv[1])
    print(f"шлагбаум: выкладка {sha[:7]} в main")

    # 2 — сперва GitHub: это быстро, и без него нет смысла гонять тесты
    candidates = [sha] + git("rev-list", "--parents", "-n", "1", sha).split()[1:]
    verdicts = []
    passed = ""
    for tested in candidates:
        rest = code_changed(tested, sha)
        if rest:
            verdicts.append(f"{tested[:7]}: после него менялся код ({', '.join(rest[:4])})")
            continue
        v = github_verdict(tested)
        verdicts.append(f"{tested[:7]}: проверка на GitHub — {v}")
        if v == "зелёный":
            passed = tested
            break
    if not passed:
        print("✗ НЕ ПУЩУ: нет зелёной «Проверки перед выкладкой» на GitHub для этого кода")
        for line in verdicts:
            print("   ", line)
        print("  что делать: push ВЕТКИ → дождаться зелёной проверки на GitHub "
              "(вкладка Actions) → слияние в main → push")
        return 1
    print(f"✓ GitHub: проверка зелёная у {passed[:7]}")

    # 1 — здесь: тесты и книга на этом самом дереве
    run = subprocess.run([sys.executable, "-X", "utf8", "scripts/proverka.py"],
                         cwd=str(ROOT), capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    tail = [ln for ln in run.stdout.splitlines() if ln.startswith(("✗", "ИТОГ", "❌"))]
    for line in tail[-12:]:
        print("   ", line)
    if run.returncode != 0:
        print("✗ НЕ ПУЩУ: проверка на компьютере красная")
        return 1
    print("✓ пропускаю в main")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

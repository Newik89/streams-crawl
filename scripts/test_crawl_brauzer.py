# -*- coding: utf-8 -*-
r"""Книга 100: обход не падает из-за браузера (crawl.yml, шаг «Поставить, что
нужно»). 11.11.2026 у Ubuntu лёг DNS, `playwright install --with-deps chromium`
ронял шаг, и два обхода подряд не дошли до сайтов — а браузером берётся ~3 %
страниц. Тест вынимает текст шага из crawl.yml и прогоняет его в bash с
подставными командами (`pip`, `playwright`, `timeout`, `sleep`, `python`):

  Б0. в шаге нет `--with-deps`: браузер и системные пакеты ставятся раздельно;
  Б1. браузер скачался не с первой попытки (до трёх) — шаг зелёный, браузер готов;
  Б2. серверы пакетов Ubuntu не отвечают — шаг зелёный, браузер готов, предупреждение;
  Б3. браузер не запускается или не скачался — шаг зелёный, предупреждение
      «обход идёт без него», строка в итог прогона;
  pip упал — шаг красный (без библиотек разбор невозможен).

Сценарии идут в bash; на Windows берётся bash из Git. Нет bash — сценарии
пропускаются с пометкой (на GitHub они идут всегда).

Запуск: venv\Scripts\python.exe scripts\test_crawl_brauzer.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8")
STEP = "Поставить, что нужно"

total = green = 0


def check(name: str, ok: bool, got=None) -> None:
    global total, green
    total += 1
    green += bool(ok)
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"   ← {got!r}"))


def step_script(name: str) -> str:
    """Текст `run: |` шага `name` из crawl.yml (без отступа)."""
    lines = (ROOT / ".github" / "workflows" / "crawl.yml").read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == f"- name: {name}")
    run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip()) + 2
    body = []
    for l in lines[run + 1:]:
        if l.strip() and len(l) - len(l.lstrip()) < indent:
            break
        body.append(l[indent:])
    return "\n".join(body).rstrip() + "\n"


def find_bash() -> str | None:
    """bash для сценариев: на Windows — из Git (системный `bash.exe` — это
    WSL, он наших путей не знает)."""
    if os.name != "nt":
        return shutil.which("bash")
    for path in (os.environ.get("GIT_BASH") or "",
                 r"C:\Program Files\Git\bin\bash.exe",
                 r"C:\Program Files\Git\usr\bin\bash.exe",
                 r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if path and Path(path).exists():
            return path
    found = shutil.which("bash")
    return found if found and "system32" not in found.lower() else None


FAKES = {
    "pip": '#!/bin/bash\nexit "${FAKE_PIP:-0}"\n',
    "sleep": "#!/bin/bash\nexit 0\n",
    # `timeout --kill-after=15 180 команда…` → просто команда
    "timeout": ('#!/bin/bash\nwhile [ $# -gt 0 ]; do case "$1" in --*) shift;; '
                '[0-9]*) shift; break;; *) break;; esac; done\nexec "$@"\n'),
    # `install-deps` — код FAKE_DEPS; `install chromium` падает первые FAKE_FAILS раз
    "playwright": ('#!/bin/bash\necho "playwright $*" >> "$FAKE_LOG"\n'
                   'if [ "$1" = "install-deps" ]; then exit "${FAKE_DEPS:-0}"; fi\n'
                   'n=$(cat "$FAKE_COUNT" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$FAKE_COUNT"\n'
                   'if [ "$n" -le "${FAKE_FAILS:-0}" ]; then exit 1; fi\nexit 0\n'),
    # `python scripts/browser_check.py` — код FAKE_CHECK
    "python": '#!/bin/bash\necho "python $*" >> "$FAKE_LOG"\nexit "${FAKE_CHECK:-0}"\n',
}


def run_step(bash: str, script: str, **fake: int) -> tuple[int, str, str, str]:
    """Прогон шага с подставными командами → (код, вывод, вызовы, итог прогона)."""
    tmp = Path(tempfile.mkdtemp(prefix="crawl-brauzer-"))
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    for name, text in FAKES.items():
        (bin_dir / name).write_text(text, encoding="utf-8", newline="\n")
        os.chmod(bin_dir / name, 0o755)
    (tmp / "step.sh").write_text(script, encoding="utf-8", newline="\n")
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["FAKE_LOG"] = (tmp / "calls.log").as_posix()
    env["FAKE_COUNT"] = (tmp / "count").as_posix()
    env["GITHUB_STEP_SUMMARY"] = (tmp / "summary.md").as_posix()
    env.update({f"FAKE_{k.upper()}": str(v) for k, v in fake.items()})
    done = subprocess.run([bash, "-e", (tmp / "step.sh").as_posix()], cwd=tmp, env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")

    def read(name: str) -> str:
        path = tmp / name
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

    out = done.stdout + done.stderr
    calls, summary = read("calls.log"), read("summary.md")
    shutil.rmtree(tmp, ignore_errors=True)
    return done.returncode, out, calls, summary


script = step_script(STEP)
check("Б0 в шаге нет `--with-deps` — браузер и пакеты Ubuntu ставятся раздельно",
      "--with-deps" not in "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#")))
check("Б0 шаг ставит библиотеки, браузер, пакеты и делает пробный запуск",
      all(x in script for x in ("pip install -r requirements-crawl.txt", "playwright install chromium",
                                "playwright install-deps chromium", "python scripts/browser_check.py")))
check("Б3 пробный запуск браузера — отдельный скрипт, лежит в репозитории",
      (ROOT / "scripts" / "browser_check.py").exists())

bash = find_bash()
if not bash:
    print("  (bash не найден — сценарии шага пропущены; на GitHub они идут)")
else:
    code, out, calls, summary = run_step(bash, script)
    check("всё в порядке: шаг зелёный, браузер готов, предупреждений нет",
          code == 0 and "браузер готов" in out and "::warning::" not in out and not summary, (code, out))
    code, out, calls, summary = run_step(bash, script, fails=2)
    check("Б1 браузер скачался с третьей попытки: шаг зелёный, браузер готов",
          code == 0 and "браузер готов" in out and out.count("скачать не вышло") == 2
          and calls.count("playwright install chromium") == 3, (code, out, calls))
    code, out, calls, summary = run_step(bash, script, deps=100)
    check("Б2 серверы пакетов Ubuntu не отвечают: шаг зелёный, браузер готов, предупреждение",
          code == 0 and "браузер готов" in out and "пакеты Ubuntu" in out
          and "обход идёт без него" not in out, (code, out))
    code, out, calls, summary = run_step(bash, script, deps=100, check=1)
    check("Б3 пакетов нет и браузер не запускается: шаг зелёный, обход идёт без браузера",
          code == 0 and "обход идёт без него" in out and "браузер готов" not in out, (code, out))
    check("Б3 о браузере написано в итог прогона", "Браузер не запустился" in summary, summary)
    code, out, calls, summary = run_step(bash, script, fails=9)
    check("Б3 браузер не скачался за три попытки: шаг зелёный, пробный запуск не делается",
          code == 0 and calls.count("playwright install chromium") == 3
          and "browser_check" not in calls and "обход идёт без него" in out, (code, out, calls))
    code, out, calls, summary = run_step(bash, script, pip=1)
    check("pip упал — шаг красный, до браузера не доходит",
          code != 0 and "playwright" not in calls, (code, calls))

print(f"\n{green}/{total} зелёных")
raise SystemExit(0 if green == total else 1)

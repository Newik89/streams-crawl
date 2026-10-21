# -*- coding: utf-8 -*-
r"""Код репозиториев — в ночную полную копию, внутрь закрытого репо копий.

Требование владельца 15.10.2026: «все данные, только развернуть на новом
сервере и, если потребуется, в новых репозиториях»; две версии — последняя
и предпоследняя, поверх. Зовёт ночная копия сервера (после того, как ушли
база и данные); адреса репо и ключей она передаёт сама — здесь их нет.

Правила по порядку:
1. Код кладётся не файлом-бандлом, а ссылками git внутрь репо копий:
   refs/kod/<имя>/heads/* и refs/kod/<имя>/tags/*. GitHub не принимает файл
   больше 100 МБ, а бандл движка 20.10 — уже 67 МБ (+~8 МБ в сутки); ссылки
   каждую ночь докладывают только новые коммиты.
2. Две версии: refs/kod/<имя>/* — эта ночь, refs/kod-previous/<имя>/* — то,
   что лежало в refs/kod/<имя>/* до этой ночи.
3. Похоже на порчу — копию этого репо не трогаем: репо не скачался, на нём
   нет ветки main, или новый main не продолжает сохранённый (историю
   переписали). Обе версии остаются как были, выход с ошибкой — ночная
   копия поднимает ТРЕВОГУ.
4. Ничего не стираем: ветка или метка, удалённая на GitHub, в копии остаётся
   с последним значением.
5. Один репо сломан — остальные всё равно едут; выход с ошибкой, если сломан
   хоть один. Репо копий не читается — не трогаем ничего.
6. После отправки сверяем: main в копии = main, который скачали.

Достать код из копии (раздел 5–6 «УСТРОЙСТВО-И-ВОССТАНОВЛЕНИЕ.md» кухни):
    git init --bare engine.git
    git -C engine.git fetch <репо копий> "+refs/kod/<имя>/heads/*:refs/heads/*" "+refs/kod/<имя>/tags/*:refs/tags/*"
Прошлая ночь — то же с refs/kod-previous/<имя>/.

Запуск (сервер; ключ — файл ssh-ключа, пустая строка — ключ по умолчанию):
    venv/bin/python scripts/code_copy.py --box /root/code-copy.git \
        --backup <адрес репо копий> --backup-key <ключ записи> \
        --repo <имя> <адрес> <ключ чтения> [--repo …]
Рабочая папка --box — голый git-репо, создаётся сам. К сайтам не ходит,
только к git-репозиториям. Тест — scripts/test_code_copy.py.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ГЛАВНАЯ = "main"


def git(box: Path, *args: str, key: str = "") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("GIT_SSH_COMMAND", None)
    if key:
        env["GIT_SSH_COMMAND"] = f"ssh -i {key} -o IdentitiesOnly=yes -o BatchMode=yes"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(["git", "-C", str(box), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env)


#: что видно в выводе git → как сказать владельцу; первое найденное главнее.
#: Последняя строка git — часто хвост совета («and the repository exists.»):
#: проба 21.10 без файла ключа дала тревогу с одним этим хвостом.
ПРИЧИНЫ = (
    ("not accessible", "нет файла ключа"),
    ("Permission denied", "нет доступа — ключ не подошёл"),
    ("Repository not found", "репо не найден"),
    ("does not appear to be a git repository", "репо не найден"),
    ("Could not resolve", "нет сети"),
)


def why(r: subprocess.CompletedProcess) -> str:
    """Причина ошибки git — в журнал и в тревогу: понятными словами и строкой
    git, где это сказано; иначе первая «fatal:/error:», иначе последняя строка."""
    lines = [ln.strip() for ln in (r.stderr or r.stdout or "").splitlines() if ln.strip()]
    for знак, слова in ПРИЧИНЫ:
        for ln in lines:
            if знак in ln:
                return f"{слова}: {ln}"
    for ln in lines:
        if ln.startswith(("fatal:", "error:")):
            return ln
    return lines[-1] if lines else f"git вернул {r.returncode}"


def commit_of(box: Path, ref: str) -> str:
    r = git(box, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}")
    return r.stdout.strip() if r.returncode == 0 else ""


def count(box: Path, prefix: str) -> int:
    r = git(box, "for-each-ref", "--format=%(refname)", prefix)
    return len([ln for ln in r.stdout.splitlines() if ln.strip()])


def take(box: Path, backup: str, backup_key: str, name: str, url: str, key: str) -> str:
    """Один репо в копию (правила 1–4, 6). → '' или причина провала."""
    new = f"refs/new/{name}"
    r = git(box, "fetch", "-q", "--no-tags", "--prune", url,
            f"+refs/heads/*:{new}/heads/*", f"+refs/tags/*:{new}/tags/*", key=key)
    if r.returncode != 0:
        return f"{name}: не скачался ({why(r)}) — копия кода прежняя"
    tip = commit_of(box, f"{new}/heads/{ГЛАВНАЯ}")
    if not tip:
        return f"{name}: на нём нет ветки {ГЛАВНАЯ} — копия кода прежняя"
    old = commit_of(box, f"refs/kod-previous/{name}/heads/{ГЛАВНАЯ}")
    if old and git(box, "merge-base", "--is-ancestor", old, tip).returncode != 0:
        return (f"{name}: история {ГЛАВНАЯ} переписана (в копии {old[:7]}, "
                f"на GitHub {tip[:7]}) — копия кода прежняя, разобраться")
    specs = [f"+{new}/*:refs/kod/{name}/*"]
    if count(box, f"refs/kod-previous/{name}"):
        specs.insert(0, f"+refs/kod-previous/{name}/*:refs/kod-previous/{name}/*")
    r = git(box, "push", "-q", "--atomic", backup, *specs, key=backup_key)
    if r.returncode != 0:
        return f"{name}: не отправился в копию ({why(r)})"
    r = git(box, "ls-remote", backup, f"refs/kod/{name}/heads/{ГЛАВНАЯ}", key=backup_key)
    got = r.stdout.split()[0] if r.returncode == 0 and r.stdout.strip() else ""
    if got != tip:
        return f"{name}: в копии {ГЛАВНАЯ} = {got[:7] or 'пусто'}, ждали {tip[:7]}"
    was = f"прошлая ночь {old[:7]}" if old else "впервые"
    print(f"код {name}: {ГЛАВНАЯ} {tip[:7]} ({was}), веток {count(box, f'{new}/heads')}, "
          f"меток {count(box, f'{new}/tags')} — в копии")
    return ""


def run(box: Path, backup: str, backup_key: str, repos: list[tuple[str, str, str]]) -> list[str]:
    """Все репо (правило 5). → список причин провала, пустой — всё легло."""
    if not (box / "HEAD").exists():
        box.mkdir(parents=True, exist_ok=True)
        r = git(box, "init", "-q", "--bare")
        if r.returncode != 0:
            return [f"рабочая папка {box} не создалась ({why(r)})"]
    # правило 2: то, что лежит в копии сейчас, — «прошлая ночь»
    r = git(box, "fetch", "-q", "--no-tags", "--prune", backup,
            "+refs/kod/*:refs/kod-previous/*", key=backup_key)
    if r.returncode != 0:
        return [f"репо копий не читается ({why(r)}) — код не тронут"]
    return [p for name, url, key in repos if (p := take(box, backup, backup_key, name, url, key))]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--box", required=True, help="рабочая папка (голый git-репо)")
    ap.add_argument("--backup", required=True, help="адрес репо копий")
    ap.add_argument("--backup-key", default="", help="ssh-ключ записи в репо копий")
    ap.add_argument("--repo", nargs=3, action="append", required=True,
                    metavar=("ИМЯ", "АДРЕС", "КЛЮЧ"), help="репо кода; можно несколько")
    args = ap.parse_args()
    problems = run(Path(args.box), args.backup, args.backup_key, [tuple(x) for x in args.repo])
    if problems:
        print("ПРОВАЛ кода: " + "; ".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
r"""Автодоставка словарей: база → `data/dictionaries.json` → git → обход.

Зачем: владелец отвечает на вопросы в админке («Названия»), но обход на
GitHub читает словари из ФАЙЛА в репозитории. До 15.09 файл выгружался
только руками — ответы неделями не доезжали до обхода. Теперь сервер
выгружает и пушит их сам, по крону перед заявками обхода (06:00 и 16:00):

    venv/bin/python scripts/dict_push.py

Порядок и страховки (грабля №27: грязный `dictionaries.json` ломает
`git pull` на сервере, поэтому после ЛЮБОГО исхода дерево остаётся чистым):

1. экспорт словаря во временное имя; файл не изменился — тихий выход;
2. изменился — записать, `git add + commit`;
3. `git pull --rebase` (бот обхода коммитит results/ — конфликтов с нашим
   файлом не бывает, но на всякий случай провал = `rebase --abort` и выход);
4. `git push`; отказ (гонка с бот-коммитом) — ещё один pull --rebase + push.

Скрипт работает ТОЛЬКО на сервере (там живая база). На другой машине он
выходит сразу: локальная база устарела, её экспорт затёр бы настоящие
словари. Обойти защиту сознательно — флаг `--force`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db                                          # noqa: E402
from dict_sync import TARGET, export                        # noqa: E402


#: пишущий деплой-ключ сервера (как у кнопок обхода, app/trigger.py):
#: обычный origin сидит на ключе «только чтение», и push им отбивается
_RW_KEY = "/root/.ssh/deploy_streams_rw"


def git(*args: str) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    if Path(_RW_KEY).exists():
        env["GIT_SSH_COMMAND"] = (f"ssh -i {_RW_KEY} "
                                  "-o StrictHostKeyChecking=accept-new")
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, timeout=120, env=env)


def clean_tree() -> None:
    """Файл словаря — обратно к версии git, чтобы pull сервера жил."""
    git("checkout", "--", str(TARGET.relative_to(ROOT)))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    # живая база — на сервере; экспорт с другой машины затёр бы словари
    if "--force" not in sys.argv and not Path("/etc/streams-schedule.env").exists():
        print("это не сервер — выгружать нечего (обойти: --force)")
        return 0
    rel = str(TARGET.relative_to(ROOT))

    conn = db.connect()
    try:
        db.init_db(conn)                    # досыпает свежие колонки
        export(conn, TARGET)
    finally:
        conn.close()

    changed = git("status", "--porcelain", "--", rel).stdout.strip()
    if not changed:
        # прошлый запуск мог закоммитить, но не дотолкнуть (сеть, гонка) —
        # дотолкнём хвост, иначе коммит завис бы до новых ответов
        git("fetch", "-q", "origin")
        ahead = git("rev-list", "--count", "origin/main..HEAD").stdout.strip()
        if ahead and ahead != "0":
            pull = git("pull", "--rebase", "origin", "main")
            if pull.returncode != 0:
                git("rebase", "--abort")
                return 1
            if git("push", "origin", "main").returncode == 0:
                print("дотолкнул незапушенный коммит словарей")
                return 0
            return 1
        print("словари не менялись — выгружать нечего")
        return 0

    if git("add", rel).returncode != 0:
        clean_tree()
        print("git add не прошёл")
        return 1
    commit = git("commit", "-m", "Словари: автовыгрузка ответов владельца")
    if commit.returncode != 0:
        clean_tree()
        print(f"commit не прошёл: {commit.stderr.strip()[:200]}")
        return 1

    for попытка in (1, 2):
        pull = git("pull", "--rebase", "origin", "main")
        if pull.returncode != 0:
            git("rebase", "--abort")
            print(f"pull --rebase не прошёл: {pull.stderr.strip()[:200]}")
            return 1
        push = git("push", "origin", "main")
        if push.returncode == 0:
            print("словари выгружены и отправлены: " + rel)
            return 0
        if попытка == 1:
            print("push отбит (гонка с бот-коммитом) — повторяю")
    print(f"push не прошёл: {push.stderr.strip()[:200]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

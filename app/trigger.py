# -*- coding: utf-8 -*-
"""Запуск обхода кнопкой из админки и с сайта (ТЗ разд. 12 и 14).

Сам обход всегда идёт из GitHub Actions (решение 29.08 — домашний и
серверный IP к сайтам не ходят). Кнопка лишь даёт GitHub команду — тот же
дозволенный путь, что `scripts/github_run.py dispatch`.

Ключ GitHub: сперва переменная `STREAMS_GITHUB_TOKEN` (так будет на сервере),
иначе — у `git credential fill`, как у обычного `git push` (так на машине
владельца). Ключ никуда не выводится и не сохраняется.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"
WORKFLOW = "crawl.yml"
DELAY = 3            # пауза обхода при запуске кнопкой — как у планового


def _token() -> str:
    env = os.environ.get("STREAMS_GITHUB_TOKEN", "").strip()
    if env:
        return env
    # ключ, вставленный владельцем в админке (Настройки → Ключ GitHub):
    # переносить секреты на сервер терминалом нельзя, поле на сайте — можно
    try:
        from . import db as _db
        conn = _db.connect()
        try:
            saved = _db.get_setting(conn, "github_token").strip()
        finally:
            conn.close()
        if saved:
            return saved
    except Exception:
        pass
    answer = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, cwd=ROOT)
    for line in answer.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise RuntimeError("нет ключа GitHub: ни STREAMS_GITHUB_TOKEN, ни git")


def _repo_slug() -> str:
    out = subprocess.run(["git", "remote", "get-url", "origin"],
                         capture_output=True, text=True, cwd=ROOT).stdout.strip()
    if not out:
        raise RuntimeError("у репозитория нет origin")
    # у origin два написания: https://github.com/User/repo.git и
    # git@github.com:User/repo.git (на сервере — второе, 05.09)
    for mark in ("github.com/", "github.com:"):
        if mark in out:
            return out.rsplit(mark, 1)[-1].removesuffix(".git")
    raise RuntimeError(f"origin не похож на GitHub: {out}")


#: деплой-ключ кнопок: рождён на сервере, наружу ушла только публичная
#: половинка (добавлена в deploy keys репозитория с write, 05.09)
_BUTTON_KEY = "/root/.ssh/deploy_streams_rw"


def encode_probe_url(url: str) -> str:
    """Адрес → base32 без «=»: слэши в имени тега жить не могут, а base32
    (A–Z, 2–7) — валидное имя. Разжимает его `queue.yml` (base32 -d)."""
    import base64
    packed = base64.b32encode(url.encode("utf-8")).decode("ascii")
    return packed.rstrip("=")


def push_request_tag(kind: str, value: str) -> tuple[bool, str]:
    """Заявка кнопки БЕЗ ключа GitHub: пуш пустого тега `btn-…` деплой-
    ключом сервера; workflow `queue.yml` ловит тег и сам запускает обход.
    Секретов в сети нет — тег это просто имя."""
    import time as _time
    tag = f"btn-{kind}-{value}-{int(_time.time())}"
    env = dict(os.environ)
    env["GIT_SSH_COMMAND"] = (f"ssh -i {_BUTTON_KEY} "
                              "-o StrictHostKeyChecking=accept-new")
    r = subprocess.run(
        ["git", "push", f"git@github.com:{_repo_slug()}.git",
         f"HEAD:refs/tags/{tag}"],
        capture_output=True, text=True, cwd=ROOT, env=env, timeout=40)
    if r.returncode == 0:
        return True, "обход заказан — GitHub запускает его"
    return False, "заявка не прошла: " + (r.stderr or "?").strip()[:160]


def dispatch_crawl(days: int, date: str = "", only: str = "") -> tuple[bool, str]:
    """Полный обход на `days` суток; `date` — скан одной даты ГГГГ-ММ-ДД
    (календарь владельца); `only` — точечный прогон одного сайта (кнопка
    «Обойти сайт», 20.09). Возвращает (получилось, слова для человека)."""
    try:
        inputs = {"mode": "full", "days": str(days), "delay": str(DELAY),
                  "only": only, "urls": ""}
        if date:
            # окно при скане даты не используется, но поле-выбор GitHub
            # принимает только «2» и «5» — шлём допустимое
            inputs["date"] = date
            inputs["days"] = "2"
        body = json.dumps({"ref": "main", "inputs": inputs}).encode()
        request = urllib.request.Request(
            f"{API}/repos/{_repo_slug()}/actions/workflows/{WORKFLOW}/dispatches",
            data=body, method="POST", headers={
                "Authorization": f"Bearer {_token()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "streams-schedule",
                "Content-Type": "application/json",
            })
        with urllib.request.urlopen(request, timeout=20) as answer:
            ok = answer.status == 204
        return ok, "обход запущен" if ok else f"GitHub ответил {answer.status}"
    except (urllib.error.URLError, RuntimeError, OSError) as e:
        return False, f"не запустилось: {e}"

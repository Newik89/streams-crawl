# -*- coding: utf-8 -*-
r"""Кнопочный перевод источника «GitHub ↔ сервер» — с доставкой плана в git.

Владелец 20.09: «нужно, чтобы я мог сам вручную переводить обход на сервер
и возвращать на GitHub». До этого перевод делал ассистент тремя руками:
`source_mode.py` в базе, правка `data/crawl_plan.json`, git push.

Здесь всё это одной функцией `set_mode()`:
  1) пометки `by_server`/`manual_only` в базе (`sources.selector_config`);
  2) те же два поля ТОЧЕЧНО в `data/crawl_plan.json` — план не
     перегенерируется целиком (грабля №23: пересборка тянула расхождения
     копий настроек), меняются только поля одного домена;
  3) коммит и push плана — тем же порядком и ключом, что автодоставка
     словарей (`scripts/dict_push.py`): add → commit → pull --rebase → push,
     при провале дерево возвращается к чистому.

Не на сервере (нет /etc/streams-schedule.env) пуш пропускается — так
локальный тест кнопок не трогает настоящий план на GitHub.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "data" / "crawl_plan.json"
#: пишущий деплой-ключ сервера — как у кнопок обхода и dict_push
_RW_KEY = "/root/.ssh/deploy_streams_rw"


def _git(*args: str) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    if Path(_RW_KEY).exists():
        env["GIT_SSH_COMMAND"] = (f"ssh -i {_RW_KEY} "
                                  "-o StrictHostKeyChecking=accept-new")
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, timeout=120, env=env)


def _on_server() -> bool:
    return Path("/etc/streams-schedule.env").exists()


def _edit_plan(domain: str, by_server: bool) -> bool:
    """Два поля одного домена в файле плана. Домена в плане нет — False."""
    raw = PLAN.read_text(encoding="utf-8")
    plan = json.loads(raw)
    hit = False
    for s in plan.get("sources") or []:
        if s.get("domain") == domain:
            s["by_server"] = by_server
            s["manual_only"] = by_server
            hit = True
    if hit:
        PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=1)
                        + ("\n" if raw.endswith("\n") else ""),
                        encoding="utf-8")
    return hit


def _push_plan(message: str) -> str:
    """Коммит и push плана; вернёт человеческую строку итога."""
    rel = str(PLAN.relative_to(ROOT))
    if not _git("status", "--porcelain", "--", rel).stdout.strip():
        return "план не изменился"
    if not _on_server():
        # локальная обкатка: файл правим, наружу не толкаем
        return "локальная копия: план записан, push пропущен"
    if _git("add", rel).returncode != 0 or \
            _git("commit", "-m", message).returncode != 0:
        _git("checkout", "--", rel)
        return "не удалось закоммитить план — файл возвращён"
    for attempt in (1, 2):
        pull = _git("pull", "--rebase", "origin", "main")
        if pull.returncode != 0:
            _git("rebase", "--abort")
            return "pull --rebase не прошёл — план уедет со следующей выгрузкой"
        if _git("push", "origin", "main").returncode == 0:
            return "план отправлен на GitHub"
        if attempt == 1:
            continue
    return "push не прошёл — план уедет со следующей выгрузкой словарей"


def probe_url(domain: str) -> str:
    """Адрес для разовой пробы с сервера — тот же, каким ходит обход:
    первая строка домена в плане с подставленной сегодняшней датой.
    У POST-источников (тело запроса) пробуем страницу-витрину."""
    from datetime import date
    from . import urls
    try:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    for s in plan.get("sources") or []:
        if s.get("domain") != domain:
            continue
        if s.get("post_json") or s.get("post_fields"):
            return s.get("base_url") or ""
        channels = s.get("channels") or []
        pattern = (channels[0].get("pattern") if channels else "") or ""
        return urls.resolve(pattern, s.get("base_url") or "",
                            day=date.today(), **(s.get("marks") or {}))
    return ""


def set_mode(conn, domain: str, by_server: bool) -> str:
    """Перевести источник: True — качает сервер, False — обычный GitHub-обход.
    Возвращает строку для показа владельцу."""
    row = conn.execute("SELECT id, selector_config FROM sources "
                       "WHERE domain = ?", (domain,)).fetchone()
    if row is None:
        return f"источника {domain} нет в базе"
    config = json.loads(row["selector_config"] or "{}") or {}
    if by_server:
        config["by_server"] = True
        config["manual_only"] = True
    else:
        config.pop("by_server", None)
        config.pop("manual_only", None)
    conn.execute("UPDATE sources SET selector_config = ? WHERE id = ?",
                 (json.dumps(config, ensure_ascii=False), row["id"]))
    conn.commit()
    kuda = "качает сервер (раз в сутки, 06:40)" if by_server \
        else "обычный обход с GitHub"
    if not _edit_plan(domain, by_server):
        return f"{domain} → {kuda}; в плане обхода домена нет — только база"
    sent = _push_plan(f"{domain}: {'качает сервер' if by_server else 'вернулся в GitHub-обход'} (кнопка владельца)")
    return f"{domain} → {kuda}; {sent}"

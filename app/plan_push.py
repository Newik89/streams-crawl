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


def _edit_plan(domain: str, by_server: bool, manual_only: bool | None = None,
               max_days: int | None = None) -> bool:
    """Поля одного домена в файле плана: by_server и manual_only (без
    `manual_only` — как by_server), `max_days` — если задан (возврат с
    восстановлением режима, `app/site_move.py`). Домена в плане нет —
    False."""
    raw = PLAN.read_text(encoding="utf-8")
    plan = json.loads(raw)
    hit = False
    for s in plan.get("sources") or []:
        if s.get("domain") == domain:
            s["by_server"] = by_server
            s["manual_only"] = by_server if manual_only is None else manual_only
            if max_days is not None:
                s["max_days"] = max_days
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
        # день — «сегодня» сайта по его часам (`urls.resolve`, tz)
        return urls.resolve(pattern, s.get("base_url") or "",
                            tz=s.get("timezone"), **(s.get("marks") or {}))
    return ""


def set_mode(conn, domain: str, by_server: bool, by: str = "owner",
             why: str = "", restore: dict | None = None) -> str:
    """Перевести источник: True — качает сервер, False — обычный GitHub-обход.
    `by` — кто переводит: owner (кнопка владельца, по умолчанию) или auto
    (`app/site_move.py`, схема сбоев шаг 11); `why` — слова для коммита
    плана; `restore` — при возврате на GitHub вернуть режим владельца
    {manual_only, max_days} (автоматический возврат, `site_move.restore_of`;
    без него «только по кнопке» снимается, как кнопкой). Счёт срывов,
    пометки перевода и режим до перевода ведёт `site_move.on_mode_change`.
    Возвращает строку для показа владельцу."""
    from . import site_move
    row = conn.execute("SELECT id, selector_config FROM sources "
                       "WHERE domain = ?", (domain,)).fetchone()
    if row is None:
        return f"источника {domain} нет в базе"
    config = json.loads(row["selector_config"] or "{}") or {}
    # ДО смены пометок: кто и когда перевёл, режим до перевода, счёт срывов
    # GitHub — с нуля (шаг 11 схемы сбоев)
    site_move.on_mode_change(config, by_server, by)
    manual, cap = None, None
    if by_server:
        config["by_server"] = True
        config["manual_only"] = True
    else:
        config.pop("by_server", None)
        config.pop("manual_only", None)
        if restore is not None:
            manual = bool(restore.get("manual_only"))
            cap = int(restore.get("max_days") or 0)
            if manual:
                config["manual_only"] = True
            if cap:
                config["max_days"] = cap
            else:
                config.pop("max_days", None)
    conn.execute("UPDATE sources SET selector_config = ? WHERE id = ?",
                 (json.dumps(config, ensure_ascii=False), row["id"]))
    conn.commit()
    kuda = "качает сервер (раз в сутки, 06:40)" if by_server \
        else "обычный обход с GitHub"
    if not _edit_plan(domain, by_server, manual_only=manual, max_days=cap):
        return f"{domain} → {kuda}; в плане обхода домена нет — только база"
    sent = _push_plan(f"{domain}: {'качает сервер' if by_server else 'вернулся в GitHub-обход'} "
                      f"({why or 'кнопка владельца'})")
    return f"{domain} → {kuda}; {sent}"


# ── Кнопка «включить / выключить» источник доходит до плана обхода ──────────
#
# Книга 135 (слово владельца 15.11.2026: «если я её нажал, значит сайт не
# должен ходить к выключенному»). Случай: sporting.pt был выключен кнопкой в
# админке, а GitHub продолжал к нему ходить. Кнопка меняла только базу
# (`sources.enabled`), а обход на GitHub идёт по файлу плана
# `data/crawl_plan.json` — в нём сайт остался.
#
# ПРАВИЛА (что случилось → что делаем):
#   К1. Источник ВЫКЛЮЧИЛИ → его запись убирается из файла плана (точечно,
#       без пересборки остального) и план отправляется на GitHub. В плане
#       его не было — ничего не делаем, так и говорим.
#   К2. Источник ВКЛЮЧИЛИ → его запись собирается из базы тем же кодом, что
#       у полной пересборки (`crawl.templates`), встаёт в конец плана, план
#       отправляется. В план НЕ встаёт, и слова говорят почему: сайт уже в
#       плане; сайта нет в списке ежедневного обхода (`PILOTS` в
#       `scripts/crawl_plan.py` — справочники и необкатанные туда не входят);
#       сайт не проходит отбор плана (не расписание, закрыт, отложен, новый).
#   К3. Отправка — `_push_plan`, как у перевода «GitHub ↔ сервер»: на
#       сервере — коммит и push, локально — только файл.
#   К4. Владелец видит итог словами рядом с «Источник выключен / включён».
#   К5. СТОРОЖ (`heal_plan`, зовёт заливка сбора): сайт стоит в плане, а в
#       базе выключен — как бы так ни вышло (кнопка до этой починки, скрипт,
#       правка базы) — он убирается из плана, план отправляется, владельцу
#       одна строка в «Прогоны». Сайт, которого в базе нет вовсе, сторож не
#       трогает: судить не по чему.

def _pilots() -> list[str]:
    """К2: сайты ежедневного обхода — тот же список `PILOTS`, по которому
    план собирает полная пересборка (`scripts/crawl_plan.py`)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "crawl_plan_pilots", ROOT / "scripts" / "crawl_plan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.PILOTS)


def _read_plan() -> tuple[dict, str]:
    raw = PLAN.read_text(encoding="utf-8")
    return json.loads(raw), raw


def _write_plan(plan: dict, raw: str) -> None:
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=1)
                    + ("\n" if raw.endswith("\n") else ""), encoding="utf-8")


def plan_domains() -> list[str]:
    """Сайты, что стоят в файле плана обхода; файла нет или он битый — пусто."""
    try:
        plan, _ = _read_plan()
    except (OSError, ValueError):
        return []
    return [s.get("domain") for s in plan.get("sources") or [] if s.get("domain")]


def _drop_from_plan(domains) -> list[str]:
    """К1, К5: убрать записи сайтов из файла плана. → кого убрали."""
    domains = set(domains)
    plan, raw = _read_plan()
    kept = [s for s in plan.get("sources") or [] if s.get("domain") not in domains]
    dropped = [s.get("domain") for s in plan.get("sources") or []
               if s.get("domain") in domains]
    if dropped:
        plan["sources"] = kept
        _write_plan(plan, raw)
    return dropped


def set_enabled(conn, domain: str, enabled: bool, why: str = "кнопка владельца") -> str:
    """К1–К4: довести включение или выключение источника до плана обхода.
    Саму пометку `enabled` в базе ставит `sources.toggle_enabled` — здесь
    только план. Возвращает слова для владельца."""
    from . import crawl
    in_plan = domain in plan_domains()
    if not enabled:                                                    # К1
        if not in_plan:
            return "в плане обхода его и не было"
        _drop_from_plan([domain])
        return ("из плана обхода убран — GitHub к нему больше не ходит; "
                + _push_plan(f"План обхода: {domain} выключен ({why})"))
    if in_plan:                                                        # К2
        return "в плане обхода уже стоит"
    if domain not in _pilots():
        return ("в ежедневный обход не входит (его нет в списке сайтов обхода) — "
                "план не менялся")
    entries = crawl.templates(conn, [domain])
    if not entries:
        return ("в план обхода не встал: сайт не проходит отбор (не расписание, "
                "закрыт, отложен или ещё не обкатан)")
    plan, raw = _read_plan()
    plan.setdefault("sources", []).append(entries[0])
    _write_plan(plan, raw)
    return ("в план обхода возвращён; "
            + _push_plan(f"План обхода: {domain} включён ({why})"))


def disabled_in_plan(conn) -> list[str]:
    """К5: сайты, что стоят в плане обхода, а в базе выключены."""
    off = {r["domain"] for r in conn.execute(
        "SELECT domain FROM sources WHERE enabled = 0")}
    return [d for d in plan_domains() if d in off]


def heal_plan(conn, apply: bool | None = None) -> list[str]:
    """К5: сторож после заливки сбора. Выключенные в базе сайты убираются из
    плана, план отправляется, владельцу — одна строка в «Прогоны».
    `apply` — править ли файл (по умолчанию — только на сервере: локальная
    база — черновик, по ней настоящий план не чистим). → строки журнала."""
    from . import watch
    found = disabled_in_plan(conn)
    if not found:
        return []
    names = ", ".join(found)
    if not (_on_server() if apply is None else apply):
        return [f"в плане обхода стоят выключенные в базе сайты: {names} "
                f"(локальная копия — план не трогаю)"]
    _drop_from_plan(found)
    sent = _push_plan(f"План обхода: убраны выключенные в базе сайты — {names}")
    line = (f"в плане обхода стояли сайты, выключенные в базе: {names} — убраны из "
            f"плана, GitHub к ним больше не ходит ({sent})")
    watch.note(conn, line, who="план обхода")
    return [line]

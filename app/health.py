# -*- coding: utf-8 -*-
"""Здоровье сбора: когда последний обход, что он принёс, всё ли живо.

Аудит 07.09 (A5) и просьба владельца 09.09: «на дашборде должно быть видно,
когда сбор закончен и что получилось, а не просто пропадать надпись; на
витрине внизу — когда был последний сбор».

Считает только по базе — в сеть не ходит, файлов не читает. Всё, что нужно,
кладут туда обход и заливка: `last_crawl` (метка «собрано» из games.json),
`last_import` (когда заливка отработала), `crawl_request` (заказ кнопкой).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import db

KYIV = ZoneInfo("Europe/Kyiv")
#: данные считаются несвежими, если заливки не было столько часов
STALE_HOURS = 26


def _parse(text: str | None) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime((text or "").strip(), fmt)
        except (ValueError, TypeError):
            continue
    return None


def _from_utc(text: str | None) -> datetime | None:
    """Метку обхода пишет GitHub своими часами (UTC) — переводим в киевские."""
    made = _parse(text)
    if made is None:
        return None
    return made.replace(tzinfo=timezone.utc).astimezone(KYIV).replace(tzinfo=None)


def _what(run: dict) -> str:
    """Что собирал прогон, словами: «6 сут.» или «дата 2026-09-13»."""
    import json
    try:
        mode = (json.loads(run.get("log") or "{}") or {}).get("режим") or ""
    except (ValueError, TypeError):
        mode = ""
    if "скан даты" in mode:
        return "дата " + mode.replace("скан даты", "").strip()
    if run.get("window_days"):
        return f"{run['window_days']} сут."
    return mode or "—"


def _ago(when: datetime | None, now: datetime) -> str:
    if when is None:
        return ""
    minutes = int((now - when).total_seconds() // 60)
    if minutes < 0:
        return "только что"
    if minutes < 60:
        return f"{minutes} мин назад"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} ч назад"
    return f"{hours // 24} дн назад"


#: сколько букв причины храним: в карточку длиннее всё равно не влезет,
#: а полный текст лежит на сервере в /var/log/streams-update.log
WHY_LIMIT = 300


def mark(step: str, ok: bool, why: str = "", now: datetime | None = None) -> str:
    """Отметить, как прошёл шаг забора на сервере: `pull` или `import`.

    Зовут двое: `scripts/mark_health.py` из `/root/streams-update.sh` и сама
    заливка, когда падает. Возвращает то, что легло в настройку.
    """
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    why = " ".join((why or "").split())[:WHY_LIMIT]
    conn = db.connect()
    try:
        if step == "pull":
            value = f"{stamp}|ok" if ok else f"{stamp}|fail|{why}"
            db.set_setting(conn, "last_pull", value)
        else:
            value = "" if ok else f"{stamp}|{why}"
            db.set_setting(conn, "last_import_error", value)
        return value
    finally:
        conn.close()


def _server(conn: sqlite3.Connection, now: datetime) -> dict:
    """Здоровье САМОГО сервера: дошёл ли до него новый код и легли ли игры.

    Отметки ставит `scripts/mark_health.py` из `/root/streams-update.sh`
    вокруг `git pull` и заливки (аудит 07.09, A5). Раньше провал этих двух
    шагов был виден только в `/var/log/streams-update.log`: сайт спокойно
    показывал вчерашние цифры, будто всё в порядке.

    Отметок ещё нет (сервер со старым скриптом) — молчим: `bad` False,
    в карточке пусто, поведение прежнее.
    """
    pull = (db.get_setting(conn, "last_pull") or "").split("|")
    pulled = _parse(pull[0]) if pull[0] else None
    pull_ok = None if len(pull) < 2 else pull[1] == "ok"
    failed = (db.get_setting(conn, "last_import_error") or "").split("|")
    return {
        "pull": pulled,
        "pull_ago": _ago(pulled, now),
        "pull_ok": pull_ok,
        "pull_why": pull[2] if len(pull) > 2 else "",
        # отдельным ключом, чтобы шаблон не сравнивал с False: `pull_ok`
        # бывает и None — «отметок ещё нет», а это не провал
        "pull_bad": pull_ok is False,
        "import_error": failed[1] if len(failed) > 1 else "",
        "import_error_ago": _ago(_parse(failed[0]) if failed[0] else None, now),
        "bad": pull_ok is False or len(failed) > 1,
    }


def summary(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Короткая сводка для дашборда и витрины."""
    now = now or datetime.now()
    crawl = _from_utc(db.get_setting(conn, "last_crawl"))
    imported = _parse(db.get_setting(conn, "last_import"))
    games = conn.execute(
        "SELECT COUNT(*) FROM events WHERE start_kyiv >= ?",
        (now.strftime("%Y-%m-%d %H:%M"),)).fetchone()[0]
    last_day = conn.execute(
        "SELECT MAX(substr(start_kyiv, 1, 10)) FROM events").fetchone()[0] or ""
    статусы = {row[0] or "": row[1] for row in conn.execute(
        "SELECT status, COUNT(*) FROM sources WHERE enabled = 1 GROUP BY status")}
    runs = [dict(r) for r in conn.execute(
        "SELECT id, finished_at, window_days, sources_ok, sources_failed, "
        "rows_found, events_upserted, log FROM runs ORDER BY id DESC LIMIT 3")]
    for r in runs:
        r["what"] = _what(r)
    run = runs[0] if runs else None
    server = _server(conn, now)
    # несвежесть — это не только «давно не заливали»: сервер мог не забрать
    # новый код или уронить заливку, и тогда цифры на экране врут (A5)
    stale = (imported is None
             or (now - imported) > timedelta(hours=STALE_HOURS)
             or server["bad"])
    return {
        "crawl": crawl, "crawl_ago": _ago(crawl, now),
        "import": imported, "import_ago": _ago(imported, now),
        "games": games, "last_day": last_day,
        "ok": статусы.get("ok", 0), "broken": статусы.get("broken", 0),
        "closed": статусы.get("closed", 0),
        "run": run,
        "runs": runs,
        "server": server,
        "stale": stale,
        "stale_hours": STALE_HOURS,
    }


def request_line(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Заказ обхода кнопкой: что заказали, когда, и приехал ли результат.

    Раньше надпись «обход заказан» просто исчезала при перезагрузке страницы,
    и владелец не понимал, дошло ли дело до конца (жалоба 09.09).
    """
    now = now or datetime.now()
    raw = db.get_setting(conn, "crawl_request") or ""
    parts = raw.split("|")
    if len(parts) < 2:
        return {}
    what, asked_at = parts[0], parts[1]
    asked = _parse(asked_at)
    crawl = _from_utc(db.get_setting(conn, "last_crawl"))
    imported = _parse(db.get_setting(conn, "last_import"))
    done = bool(asked and crawl and crawl >= asked)
    return {
        "what": what, "asked": asked_at, "done": done,
        "crawl": crawl.strftime("%d.%m %H:%M") if crawl else "",
        "import": imported.strftime("%d.%m %H:%M") if imported else "",
        "waiting": _ago(asked, now) if asked and not done else "",
    }

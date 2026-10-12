# -*- coding: utf-8 -*-
"""Каждая ТРЕВОГА сервера — ещё и письмом владельцу (схема сбоев, шаг 9).

Слово владельца 06.10.2026: «ТРЕВОГА ещё и письмом (issue на GitHub →
почта владельца) — да». Тревоги сервера — строки «Прогонов» со словом
ТРЕВОГА (`watch.note`: сторож заказов, сторож витрины). Как они доходят:
сторож витрины (`scripts/web_watch.py`, cron */5) в конце каждого запуска
зовёт `flush` → новые строки с тревогой уходят одним ТЕГОМ-ПИСЬМОМ
`alarm-<время>` с их текстом (деплой-ключ сервера, как заявки кнопок —
`trigger.push_alarm_tag`; ключа API GitHub на сервере нет и не нужно) →
workflow `alarm.yml` на GitHub (`scripts/alarm_issue.py`) заводит issue
«Тревоги сервера — ДД.ММ.ГГГГ» (одна на день, дальше — комментарии) и
убирает тег → GitHub шлёт владельцу письмо. Письмо уходит не позже чем
через 5 минут после тревоги.

Правила (`flush`), по порядку:
  М1. Памяти нет (первый запуск) → запомнить номер последней строки
      «Прогонов» и ничего не слать: старые тревоги — не новость.
  М2. Новых строк с тревогой нет → молчим.
  М3. Есть новые → одно письмо со всеми (не больше `MAX_LINES` строк,
      остальные — числом); тег ушёл → память = номер последней из них.
  М4. Тег не ушёл (или git не ответил вовремя) → память не двигаем,
      следующий запуск повторит; первая неудача ставит `waiting_since` — по
      ней `/alive` (правило Ж4, `app/alive.py`) скажет GitHub-у, что письма
      не уходят дольше часа. Лишнее письмо лучше потерянного.
Память — настройка `alarm_mail` (JSON {last_id, sent_at, waiting_since}).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from . import watch

KEY = "alarm_mail"
WORD = "ТРЕВОГА"
#: строк тревоги в одном письме; остальные — числом
MAX_LINES = 20
#: знаков в одной строке письма
LINE_CHARS = 500


def last_row_id(conn: sqlite3.Connection) -> int:
    """Номер последней строки «Прогонов» (0 — пусто)."""
    row = conn.execute("SELECT MAX(id) FROM runs").fetchone()
    return int(row[0] or 0)


def new_alarms(conn: sqlite3.Connection, after_id: int) -> list[dict]:
    """Строки «Прогонов» с тревогой после строки `after_id`, по порядку:
    [{id, at (`ГГГГ-ММ-ДД ЧЧ:ММ` по Киеву), text}]."""
    rows = conn.execute(
        "SELECT id, started_at, log FROM runs WHERE id > ? AND log LIKE ? "
        "ORDER BY id", (after_id, f"%{WORD}%")).fetchall()
    found = []
    for row in rows:
        try:
            text = (json.loads(row["log"] or "{}") or {}).get("режим") or ""
        except (ValueError, AttributeError):
            text = row["log"] or ""
        if WORD in text:
            found.append({"id": int(row["id"]), "at": row["started_at"] or "",
                          "text": str(text)})
    return found


def message(alarms: list[dict]) -> str:
    """Текст письма: по строке на тревогу, `ДД.ММ ЧЧ:ММ <слова>`."""
    lines = [f"Тревоги сервера Streams Schedule: {len(alarms)}", ""]
    for alarm in alarms[:MAX_LINES]:
        at = alarm["at"]
        when = f"{at[8:10]}.{at[5:7]} {at[11:16]}" if len(at) >= 16 else at
        lines.append(f"{when} {alarm['text'][:LINE_CHARS]}")
    if len(alarms) > MAX_LINES:
        lines.append(f"…и ещё {len(alarms) - MAX_LINES} — в «Прогонах» админки")
    return "\n".join(lines)


def flush(conn: sqlite3.Connection, now: datetime, send=None,
          check: bool = False) -> str:
    """Правила М1–М4. `send(text)` → (ушло ли: True / False / None, слова);
    по умолчанию — `trigger.push_alarm_tag`. Возвращает строку для журнала
    cron (пусто — сказать нечего)."""
    memory = watch.load_json(conn, KEY)
    if "last_id" not in memory:                                   # М1
        if not check:
            watch.save_json(conn, KEY, {"last_id": last_row_id(conn)})
        return "письма тревог: первый запуск — старые тревоги не шлю"
    alarms = new_alarms(conn, int(memory.get("last_id") or 0))
    if not alarms:                                                # М2
        return ""
    if check:
        return f"письмо тревог ушло бы: {len(alarms)} шт."
    if send is None:
        from .trigger import push_alarm_tag as send
    try:
        sent, words = send(message(alarms))
    except Exception as e:                    # noqa: BLE001 — письмо не роняет сторожа
        sent, words = False, f"{type(e).__name__}: {e}"[:200]
    if sent:                                                      # М3
        watch.save_json(conn, KEY, {"last_id": alarms[-1]["id"],
                                    "sent_at": watch.when(now)})
        return f"письмо тревог ушло ({len(alarms)} шт.): {words}"
    memory = dict(memory)                                         # М4
    memory.setdefault("waiting_since", watch.when(now))
    watch.save_json(conn, KEY, memory)
    return f"письмо тревог НЕ ушло ({words}) — повторю на следующем запуске"

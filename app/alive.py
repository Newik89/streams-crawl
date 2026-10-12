# -*- coding: utf-8 -*-
"""Жив ли сервер: кто из сторожей давно молчит (схема сбоев, шаг 9).

Схема сбоев (`deploy/СБОИ-СХЕМА.md`, принята владельцем 06.10.2026):
«сторож молчит 40 мин → запустить и тревога; сервер лежит → GitHub пишет
issue (письмо)». Сторожей сервера запускает cron. Встал cron или сторож
падает на каждом запуске — молчат все, и строки ТРЕВОГА в «Прогонах» не
будет. Поэтому каждый сторож в конце удачного запуска ставит ОТМЕТКУ «жив»
(`beat`, настройка `beat:<имя>`), а на отметки смотрят двое:
  - сторож витрины (`scripts/web_watch.py`, cron */5) — правило В5: молчит
    сторож заказов → запустить его и ТРЕВОГА;
  - GitHub (`scripts/server_alive.py`, workflow `alive.yml`) открывает
    страницу `/alive` (её ответ — `report`): сервер не ответил или кто-то
    молчит → issue, письмо владельцу.

Правила (`report`), по порядку:
  Ж1. Отметка моложе своего порога (`BEATS`) → сторож в порядке.
  Ж2. Отметка старше порога → «<кто> молчит N мин».
  Ж3. Отметки нет вовсе (код только приехал) → в порядке: она появится на
      первом же запуске. Сторож витрины ждёт её сам (В5, `missing_since`).
  Ж4. Письма тревог (`app/alarm_mail.py`) не уходят дольше
      `MAIL_SILENT_MINUTES` → «письма тревог не уходят N мин».
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import db, watch

#: кто ставит отметку → (как его назвать владельцу, через сколько минут без
#: отметки он «молчит»). Сторож заказов ходит раз в 15 мин и может до 7 мин
#: ждать общий замок (`watch.LOCK_WAIT_WATCH`) — 40 мин из схемы владельца;
#: сторож витрины ходит раз в 5 мин — 20 мин
BEATS = {
    "crawl_watch": ("сторож заказов", 40),
    "web_watch": ("сторож витрины", 20),
}
#: тревога ждёт отправки письмом дольше этого — письма не уходят (Ж4)
MAIL_SILENT_MINUTES = 60
BEAT_PREFIX = "beat:"


def beat(conn: sqlite3.Connection, name: str, now: datetime | None = None) -> None:
    """Отметка «жив»: сторож `name` дошёл до конца запуска."""
    db.set_setting(conn, BEAT_PREFIX + name,
                   watch.when(now or datetime.now(timezone.utc)))


def beat_at(conn: sqlite3.Connection, name: str) -> datetime | None:
    """Когда сторож `name` последний раз отметился (UTC); None — ни разу."""
    return watch.moment(db.get_setting(conn, BEAT_PREFIX + name))


def minutes_since(at: datetime | None, now: datetime) -> int | None:
    if at is None:
        return None
    return int((watch.utc(now) - watch.utc(at)).total_seconds() // 60)


def report(conn: sqlite3.Connection, now: datetime) -> dict:
    """Ответ страницы `/alive`: {"жив": всё ли в порядке, "молчат": [слова],
    "минут": {имя: минут с отметки или None}}. Правила Ж1–Ж4."""
    silent: list[str] = []
    ages: dict[str, int | None] = {}
    for name, (words, limit) in BEATS.items():
        age = minutes_since(beat_at(conn, name), now)
        ages[name] = age
        if age is not None and age > limit:                       # Ж2
            silent.append(f"{words} молчит {age} мин")
    from . import alarm_mail                                       # Ж4
    waiting = minutes_since(watch.moment(
        watch.load_json(conn, alarm_mail.KEY).get("waiting_since") or ""), now)
    if waiting is not None and waiting > MAIL_SILENT_MINUTES:
        silent.append(f"письма тревог не уходят {waiting} мин")
    return {"жив": not silent, "молчат": silent, "минут": ages}

# -*- coding: utf-8 -*-
"""Жив ли сервер: кто из сторожей давно молчит (схема сбоев, шаг 9).

Схема сбоев (`deploy/СБОИ-СХЕМА.md`, принята владельцем 06.10.2026):
«сторож молчит 40 мин → запустить и тревога; сервер лежит → GitHub пишет
issue (письмо)». Сторожей сервера запускает cron. Встал cron или сторож
падает на каждом запуске — молчат все, и строки ТРЕВОГА в «Прогонах» не
будет. Поэтому каждый сторож в конце удачного запуска ИЗ CRON ставит
ОТМЕТКУ «жив» (`beat`, настройка `beat:<имя>`), а на отметки смотрят двое:
  - сторож витрины (`scripts/web_watch.py`, cron */5) — правило В5: молчит
    сторож заказов → запустить его и ТРЕВОГА. Запуск «пинком» отметку не
    ставит (`KICKED_ENV`): иначе мёртвый cron прятался бы за ежечасными
    пинками;
  - GitHub (`scripts/server_alive.py`, workflow `alive.yml`) открывает
    страницу `/alive` (её ответ — `report`): сервер не ответил или кто-то
    молчит → issue, письмо владельцу.

Правила (`silent_minutes`, `report`), по порядку:
  Ж1. Отметка моложе своего порога (`BEATS`) → сторож в порядке.
  Ж2. Отметка старше порога → «<кто> молчит N мин».
  Ж3. Отметки нет вовсе (код только приехал) → молчанием считается время с
      первого раза, когда её не нашли (настройка `beat_missing:<имя>`
      ставится тогда же): до порога — в порядке, дальше — «молчит, отметок
      не было ни одной». Сторож, падающий с первого запуска, так не спрячется.
  Ж3б. Молчание не длиннее времени работы сервера с загрузки
      (`uptime_minutes`, /proc/uptime): после долгого простоя отметке часы,
      но сторожа просто ещё не успели пройти — это не их вина.
  Ж4. Письма тревог (`app/alarm_mail.py`) не уходят дольше
      `MAIL_SILENT_MINUTES` → «письма тревог не уходят N мин».
В ответе и слова для человека («молчат»), и имена для GitHub («кто»: имена
сторожей и `mail`) — по смене состава GitHub пишет письмо сразу.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

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
MISSING_PREFIX = "beat_missing:"
#: переменная окружения запуска «пинком» (В5): такой запуск отметку не ставит
KICKED_ENV = "STREAMS_KICKED"
UPTIME_FILE = Path("/proc/uptime")


def beat(conn: sqlite3.Connection, name: str, now: datetime | None = None) -> None:
    """Отметка «жив»: сторож `name` дошёл до конца запуска из cron."""
    db.set_setting(conn, BEAT_PREFIX + name,
                   watch.when(now or datetime.now(timezone.utc)))


def beat_at(conn: sqlite3.Connection, name: str) -> datetime | None:
    """Когда сторож `name` последний раз отметился (UTC); None — ни разу."""
    return watch.moment(db.get_setting(conn, BEAT_PREFIX + name))


def minutes_since(at: datetime | None, now: datetime) -> int | None:
    if at is None:
        return None
    return int((watch.utc(now) - watch.utc(at)).total_seconds() // 60)


def uptime_minutes(path: Path = UPTIME_FILE) -> int | None:
    """Сколько минут сервер работает с загрузки (Ж3б); None — не узнать
    (не Linux, нет файла)."""
    try:
        return int(float(path.read_text().split()[0]) // 60)
    except (OSError, ValueError, IndexError):
        return None


def silent_minutes(conn: sqlite3.Connection, name: str, now: datetime,
                   write: bool = True, uptime: int | None = -1) -> tuple[int, bool]:
    """Ж1–Ж3б: (сколько минут сторож `name` молчит, были ли отметки вообще).
    Отметки нет — с первого раза, когда её не нашли (и запомнить этот раз,
    если `write`; `--check` не пишет). `uptime` — минуты с загрузки (по
    умолчанию — с сервера; None — не ограничивать)."""
    if uptime == -1:
        uptime = uptime_minutes()
    at = beat_at(conn, name)
    if at is not None:
        age, seen = minutes_since(at, now), True
    else:
        seen = False
        first = watch.moment(db.get_setting(conn, MISSING_PREFIX + name))
        if first is None:
            if write:
                db.set_setting(conn, MISSING_PREFIX + name, watch.when(now))
            age = 0
        else:
            age = minutes_since(first, now)
    if uptime is not None:
        age = min(age, uptime)
    return age, seen


def report(conn: sqlite3.Connection, now: datetime, uptime: int | None = -1) -> dict:
    """Ответ страницы `/alive`: {"жив": всё ли в порядке, "молчат": [слова],
    "кто": [имена молчащих], "минут": {имя: сколько минут молчит}}.
    Правила Ж1–Ж4."""
    silent: list[str] = []
    who: list[str] = []
    ages: dict[str, int] = {}
    for name, (words, limit) in BEATS.items():
        age, seen = silent_minutes(conn, name, now, uptime=uptime)
        ages[name] = age
        if age > limit:                                           # Ж2, Ж3
            who.append(name)
            silent.append(f"{words} молчит {age} мин"
                          + ("" if seen else " (отметок не было ни одной)"))
    from . import alarm_mail                                       # Ж4
    waiting = minutes_since(watch.moment(
        watch.load_json(conn, alarm_mail.KEY).get("waiting_since") or ""), now)
    if waiting is not None and waiting > MAIL_SILENT_MINUTES:
        who.append("mail")
        silent.append(f"письма тревог не уходят {waiting} мин")
    return {"жив": not silent, "молчат": silent, "кто": who, "минут": ages}

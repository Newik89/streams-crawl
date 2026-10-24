# -*- coding: utf-8 -*-
"""Работа с базой: подключение, создание схемы, мелкие помощники.

База — файл `data/channel_schedule.db` (ТЗ разд. 19, решение от 28.08.2026:
обкатываем локально). Путь можно переопределить переменной окружения
`STREAMS_DB` — понадобится, когда проект уедет на сервер.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "channel_schedule.db"
SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def db_path() -> Path:
    return Path(os.environ.get("STREAMS_DB") or DEFAULT_DB)


#: сколько секунд ждать базу, занятую чужой записью. Страницы сайта — 5 с
#: (как было у sqlite по умолчанию): дольше странице висеть незачем, а
#: gunicorn сам обрывает запрос через 30 с…
BUSY_TIMEOUT_WEB = 5
#: …кнопка сбора, когда тег уже ушёл и заказ надо записать в книгу, — 15 с
#: (дольше, но в пределах 30 с gunicorn)…
BUSY_TIMEOUT_ORDER = 15
#: …скрипты сторожа, заявки и заливки — 30 с: заливка игр (`save_games`)
#: пишет одной длинной транзакцией, и запись заявки или решения сторожа не
#: должна из-за неё падать «database is locked»
BUSY_TIMEOUT_SCRIPT = 30


def connect(timeout: float = BUSY_TIMEOUT_WEB) -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL: чтение не блокируется записью — пригодится, когда парсер пишет,
    # а владелец в это время смотрит админку.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> Path:
    """Создаёт таблицы, которых ещё нет. Существующие данные не трогает."""
    own = conn is None
    conn = conn or connect()
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        _add_missing_columns(conn)
        _add_triggers(conn)
        conn.commit()
    finally:
        if own:
            conn.close()
    return db_path()


#: колонки, добавленные после первой версии схемы: `CREATE TABLE IF NOT
#: EXISTS` их в существующую таблицу не принесёт, поэтому досыпаем вручную
_LATE_COLUMNS = {
    "channels": [("custom_name", "INTEGER NOT NULL DEFAULT 0"),
                 ("note", "TEXT")],
    # 14.09: время у сайта разошлось с эталоном flashscore, канал прилип к
    # игре по командам — на витрине красная пометка «перепроверить».
    # 22.09: клик владельца по зелёному каналу гасит его «new» насовсем,
    # с любого устройства — как `events.seen` у игр
    "event_channels": [("time_off", "INTEGER NOT NULL DEFAULT 0"),
                       ("seen", "INTEGER NOT NULL DEFAULT 0")],
    # 15.09: ответ «какой это спорт» привязан к дню матча, а не навечно
    "sport_hints": [("match_day", "TEXT")],
    # 21.09: игра «новая», пока владелец её не прочитал — клик по строке или
    # кнопка «Прочитано всё» (просьба владельца: новизна по часам гасла сама)
    # 24.10: прежнее время перенесённой игры — пометка «перенесён с …» на
    # витрине (#7836/#6792: эталон перенёс матч на сутки, каналы уехали
    # вместе с игрой, а владелец искал их в прежнем дне). Ставит триггер
    # `events_moved_from` (см. `_add_triggers`), а не код заливки
    "events": [("seen", "INTEGER NOT NULL DEFAULT 0"),
               ("moved_from", "TEXT")],
    # 04.10: у канала на вкладке «Other Sport» — та же ссылка «открыть
    # расписание канала», что и у матчей; для неё нужна страница строки
    "other_sport": [("source_url", "TEXT")],
    # 06.10: кто закрыл вопрос очереди «Названия». Пусто — владелец кнопкой;
    # иначе «ответила программа: …» с правилом и уликой
    # (`app/sport_question.py`) — видно во вкладках админки
    "moderation": [("answered_by", "TEXT")],
}


#: сдвиг начала игры, с которого это ПЕРЕНОС, а не поправка (часов):
#: поправки эталона — минуты, перевод часов — 1 ч, перенос матча — сутки
MOVED_HOURS = 3


def _add_triggers(conn: sqlite3.Connection) -> None:
    """Пометка «перенесён с …» (владелец 24.10). Правила по порядку:
    1. Время начала игры сдвинулось на `MOVED_HOURS` и больше — запоминаем
       прежнее время в `events.moved_from` (кто бы ни сдвинул: заливка,
       сверка с эталоном — правило одно, в самой базе).
    2. Уже переносили — храним самое первое время (перенос за переносом
       показывает, откуда матч уехал изначально).
    3. Матч вернули к прежнему времени (ближе `MOVED_HOURS`) — пометка
       снимается.
    4. Сдвиг меньше порога пометку не трогает (поправка на минуты после
       переноса остаётся переносом)."""
    new = "julianday(replace(NEW.start_kyiv, 'T', ' '))"
    old = "julianday(replace(OLD.start_kyiv, 'T', ' '))"
    # версия в имени: правило поменяется — новое имя, старое снять DROP'ом
    # здесь же (пересоздавать при каждом открытии базы — лишняя запись)
    conn.execute(f"""
        CREATE TRIGGER IF NOT EXISTS events_moved_from_v1
        AFTER UPDATE OF start_kyiv ON events
        WHEN {new} IS NOT NULL AND {old} IS NOT NULL
             AND abs({new} - {old}) * 24 >= {MOVED_HOURS}
        BEGIN
            UPDATE events SET moved_from = CASE
                WHEN OLD.moved_from IS NULL
                    THEN substr(replace(OLD.start_kyiv, 'T', ' '), 1, 16)
                WHEN abs({new} - julianday(OLD.moved_from)) * 24 < {MOVED_HOURS}
                    THEN NULL
                ELSE OLD.moved_from END
            WHERE id = NEW.id;
        END""")


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, columns in _LATE_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                if table == "events" and name == "seen":
                    # колонка только родилась: старые игры считаем прочитанными,
                    # иначе вся витрина разом вспыхнула бы «новой»
                    conn.execute("UPDATE events SET seen = 1")


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                 (key, value))
    conn.commit()


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Сколько строк в каждой таблице — для дашборда и проверок."""
    names = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {n: conn.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0] for n in names}

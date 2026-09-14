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


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
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
    # игре по командам — на витрине красная пометка «перепроверить»
    "event_channels": [("time_off", "INTEGER NOT NULL DEFAULT 0")],
}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, columns in _LATE_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


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

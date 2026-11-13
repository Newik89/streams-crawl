# -*- coding: utf-8 -*-
"""Нужно ли повторить заливку, хотя нового на GitHub нет (аудит 13.11.2026).

Повод: забор кода прошёл, а заливка игр после него упала. Следующий стук
GitHub видел «нового нет» и уходил — результат сбора лежал невлитым до
забора по часам (вечерний сбор — до утра). Зовёт `scripts/hook_pull.sh`.

Правила по порядку:

1. Прошлая заливка прошла (настройка `last_import_error` пустая) — повтор
   не нужен; счётчик повторов обнуляется.
2. Прошлая заливка упала — повторить, но не больше `MAX_RETRIES` раз подряд:
   если ошибка постоянная, каждый стук не должен гонять полный забор.
3. Базу прочитать не вышло — повтор не нужен (сломанной базе он не поможет,
   о ней скажут сторожа).

Код выхода: 0 — повторить, 1 — не надо.

    venv/bin/python scripts/import_retry.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: правило 2: сколько раз подряд повторяем упавшую заливку по стуку
MAX_RETRIES = 2
#: настройка со счётчиком повторов
RETRIES_KEY = "import_retries"


def should_retry(conn) -> bool:
    """Правила 1–2. Счётчик в базе двигает сама."""
    from app import db
    error = (db.get_setting(conn, "last_import_error") or "").strip()
    if not error:                                             # правило 1
        if db.get_setting(conn, RETRIES_KEY) not in ("", "0"):
            db.set_setting(conn, RETRIES_KEY, "0")
        return False
    try:
        done = int(db.get_setting(conn, RETRIES_KEY) or 0)
    except ValueError:
        done = 0
    if done >= MAX_RETRIES:                                   # правило 2
        return False
    db.set_setting(conn, RETRIES_KEY, str(done + 1))
    return True


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        from app import db
        conn = db.connect()
        try:
            return 0 if should_retry(conn) else 1
        finally:
            conn.close()
    except Exception as beda:                                 # правило 3
        print(f"повтор заливки: базу прочитать не вышло ({beda})")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

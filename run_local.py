# -*- coding: utf-8 -*-
"""Локальный запуск админки.

    python run_local.py

Откроется http://127.0.0.1:5057 — вход по паролю `admin`, если не задана
переменная окружения STREAMS_ADMIN_PASSWORD.

Слушает только 127.0.0.1: снаружи, из сети, админка недоступна. Это
сознательно — пароль по умолчанию допустим только на своём компьютере.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("STREAMS_LOCAL", "1")

from app.db import db_path, init_db  # noqa: E402
from app.web import create_app       # noqa: E402

if __name__ == "__main__":
    init_db()
    # Порт 5057; переменная PORT (её ставит предпросмотр Claude Code) сильнее.
    port = int(os.environ.get("PORT") or 5057)
    print(f"База:   {db_path()}")
    print(f"Адрес:  http://127.0.0.1:{port}")
    print("Пароль: admin (или значение STREAMS_ADMIN_PASSWORD)")
    create_app().run(host="127.0.0.1", port=port, debug=True)

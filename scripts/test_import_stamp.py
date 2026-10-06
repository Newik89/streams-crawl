# -*- coding: utf-8 -*-
"""Метка последнего сбора не едет назад (`last_crawl`).

07.10: заливка серверного сбора одного сайта (`mojtv.hr`, собран в 03:40)
переписала метку поверх вечернего полного обхода (21:49), и страница «Сбор
расписания» показала красное «итог так и не доехал», хотя обход прошёл и
влился. Правило: метку двигаем только вперёд.

Запуск: venv\\Scripts\\python.exe scripts/test_import_stamp.py
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="stamp-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")

from app import db, health  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def файл(имя: str, метка: str) -> Path:
    папка = TMP / имя
    папка.mkdir(exist_ok=True)
    io.open(папка / "games.json", "w", encoding="utf-8").write(
        json.dumps({"собрано": метка, "игр": 0, "games": []},
                   ensure_ascii=False))
    return папка / "games.json"


def залить(путь: Path) -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "games_import.py"),
                    "--file", str(путь), "--who", "тест"],
                   capture_output=True, text=True, env=os.environ)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("Метка последнего сбора")
    conn = db.connect()
    db.init_db(conn)
    conn.close()

    залить(файл("вечерний", "2026-10-06 18:49"))
    conn = db.connect()
    проверка("метка встала по первому файлу",
             db.get_setting(conn, "last_crawl"), "2026-10-06 18:49")
    db.set_setting(conn, "crawl_request", "обход 6 сут.|2026-10-06 20:30")
    conn.close()

    залить(файл("серверный", "2026-10-06 03:40"))
    conn = db.connect()
    проверка("старый файл метку не сдвинул",
             db.get_setting(conn, "last_crawl"), "2026-10-06 18:49")
    проверка("заказ обхода считается выполненным",
             health.request_line(conn)["done"], True)
    conn.close()

    залить(файл("утренний", "2026-10-07 05:20"))
    conn = db.connect()
    проверка("свежий файл метку сдвинул",
             db.get_setting(conn, "last_crawl"), "2026-10-07 05:20")
    conn.close()

    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, "
          f"красных: {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

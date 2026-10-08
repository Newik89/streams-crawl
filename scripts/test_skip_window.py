# -*- coding: utf-8 -*-
"""«Не матч» молчит только вокруг дня матча (`dictionary.enqueue`), и в
вопросе очереди доезжает адрес страницы канала (`sport_question.Question`).

Вопрос владельца 08.10: «а если будет такая же пара, но уже реальная игра?»
— раньше «Не матч» молчал навсегда.

Запуск: venv\\Scripts\\python.exe scripts/test_skip_window.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="skip-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")

from app import db, dictionary, sport_question  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


ПАРА = "Le Mans - Lorient | beIN SPORTS 4 (beinsports.com.tr)"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("«Не матч» вокруг дня матча и адрес страницы в вопросе")
    conn = db.connect()
    db.init_db(conn)

    проверка("первый вопрос встаёт в очередь",
             dictionary.enqueue(conn, "sport", ПАРА,
                                suggestion="2026-10-09 09:30 | Le Mans - Lorient"),
             True)
    item = conn.execute("SELECT id FROM moderation WHERE raw_value = ?",
                        (ПАРА,)).fetchone()
    dictionary.skip(conn, item["id"])
    проверка("тот же день — молчит",
             dictionary.enqueue(conn, "sport", ПАРА,
                                suggestion="2026-10-09 20:00 | Le Mans - Lorient"),
             False)
    проверка("сутки спустя — ещё молчит (±1,5 суток)",
             dictionary.enqueue(conn, "sport", ПАРА,
                                suggestion="2026-10-10 12:00 | Le Mans - Lorient"),
             False)
    проверка("через пять дней — спрашивает заново",
             dictionary.enqueue(conn, "sport", ПАРА,
                                suggestion="2026-10-14 20:00 | Le Mans - Lorient"),
             True)

    # старое отсеянное без даты — как раньше, навсегда
    conn.execute("INSERT INTO moderation (kind, raw_value, suggestion, status) "
                 "VALUES ('sport', 'MotoGP - Sprint | X (y.z)', '', 'skipped')")
    conn.commit()
    проверка("отсеянное без даты молчит навсегда",
             dictionary.enqueue(conn, "sport", "MotoGP - Sprint | X (y.z)",
                                suggestion="2026-11-01 10:00 | MotoGP"),
             False)

    q = sport_question.Question.parse(
        ПАРА, "2026-10-09 09:30 | Le Mans - Lorient | "
              "https://beinsports.com.tr/yayin-akisi?d=2026-10-09")
    проверка("адрес страницы отделён от заголовка",
             (q.title, q.url),
             ("Le Mans - Lorient",
              "https://beinsports.com.tr/yayin-akisi?d=2026-10-09"))
    q2 = sport_question.Question.parse(ПАРА, "2026-10-09 09:30 | Le Mans - Lorient")
    проверка("старая подсказка без адреса — как раньше",
             (q2.title, q2.url), ("Le Mans - Lorient", ""))
    conn.close()
    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, "
          f"красных: {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

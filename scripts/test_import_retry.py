# -*- coding: utf-8 -*-
r"""Повтор упавшей заливки по стуку (аудит 13.11.2026).

Правила — в шапке `scripts/import_retry.py`:

1. прошлая заливка прошла — повтор не нужен, счётчик обнулён;
2. прошлая заливка упала — повторить, но не больше двух раз подряд;
и что `hook_pull.sh` зовёт проверку именно в ветке «нового нет».

В сеть не ходит, база — пустая временная:

    python scripts/test_import_retry.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="import-retry-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")

from app import db, health  # noqa: E402
import import_retry         # noqa: E402

db.init_db()
passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


conn = db.connect()
print("1. Заливка прошла — повтор не нужен")
check("чистая база — не повторять", not import_retry.should_retry(conn))
health.mark("import", True)
check("отметка «заливка прошла» — не повторять",
      not import_retry.should_retry(conn))

print("2. Заливка упала — повторить, но не больше двух раз подряд")
health.mark("import", False, "games_import.py вернул ошибку")
check("первый стук после падения — повторить", import_retry.should_retry(conn))
health.mark("import", False, "games_import.py вернул ошибку")
check("второй стук, заливка снова упала — повторить",
      import_retry.should_retry(conn))
health.mark("import", False, "games_import.py вернул ошибку")
check("третий стук — уже не повторять (ошибка постоянная)",
      not import_retry.should_retry(conn))
health.mark("import", True)
check("заливка прошла — счётчик обнулён",
      not import_retry.should_retry(conn)
      and db.get_setting(conn, import_retry.RETRIES_KEY) == "0")
health.mark("import", False, "снова упала")
check("новое падение после удачи — снова повторить",
      import_retry.should_retry(conn))
conn.close()

print("3. Скрипт стука зовёт проверку в ветке «нового нет»")
sh = (ROOT / "scripts" / "hook_pull.sh").read_text(encoding="utf-8")
ветка = sh.split('if [ "$remote" = "$(git rev-parse HEAD)" ]; then', 1)[1]
ветка = ветка.split("\nfi\n", 2)
check("проверка стоит до «нового на GitHub нет»",
      "scripts/import_retry.py" in sh
      and sh.index("scripts/import_retry.py") < sh.index("стук: нового на GitHub нет"))
check("повтор идёт под общим замком заборов",
      sh.count("flock -w 900 /run/streams-update.lock /root/streams-update.sh") == 2)

print(f"\nпройдено: {passed}, провалено: {len(failed)}")
for name in failed:
    print("  ✖", name)
sys.exit(1 if failed else 0)

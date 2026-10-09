# -*- coding: utf-8 -*-
"""Самопроверка прогона доезжает до «Прогонов» списком (задание владельца
06.10: «чтобы не ходить кругами»).

Цепочка: `audit_run.py --json` пишет `audit.json` рядом с `games.json` →
заливка (`games_import.py` → `store.log_run`) кладёт его в строку `runs`
ключом «самопроверка», если метка «собрано» та же → страница «Прогоны»
показывает раскрывающийся список, а сырой лог — без него.

В сеть не ходит. База — пустая, во временной папке. Запуск:

    venv\\Scripts\\python.exe scripts/test_audit_runs.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="audit-runs-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")
os.environ["STREAMS_ADMIN_PASSWORD"] = "adm-test-1"

from app import db  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True, extra="") -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r} {extra}")


def папка_прогона(имя: str, собрано: str) -> Path:
    п = TMP / имя
    п.mkdir(exist_ok=True)
    (п / "report.json").write_text(json.dumps({"строки": [], "режим": "полный обход, окно 2 суток"},
                                              ensure_ascii=False), encoding="utf-8")
    (п / "games.json").write_text(json.dumps({"собрано": собрано, "игр": 0, "окно": 2,
                                              "games": []}, ensure_ascii=False),
                                  encoding="utf-8")
    return п


def залить(п: Path) -> str:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "games_import.py"),
                        "--file", str(п / "games.json"), "--who", "тест"],
                       capture_output=True, text=True, env=os.environ)
    return r.stdout + r.stderr


def последний_лог() -> dict:
    conn = db.connect()
    try:
        row = conn.execute("SELECT log FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row["log"]) if row else {}
    finally:
        conn.close()


def main() -> int:
    conn = db.connect()
    db.init_db(conn)
    conn.close()

    print("1. audit_run.py --json пишет итог для админки")
    п = папка_прогона("пустой", "2026-10-09 05:00")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "audit_run.py"),
                        "--dir", str(п), "--json", str(п / "audit.json")],
                       capture_output=True, text=True, env=os.environ)
    проверка("скрипт отработал", r.returncode, 0, r.stderr[-300:])
    итог = json.loads((п / "audit.json").read_text(encoding="utf-8"))
    проверка("метка «собрано» переписана из games.json", итог.get("собрано"), "2026-10-09 05:00")
    проверка("пустой прогон — подозрений 0 и разделов нет",
             (итог.get("подозрений"), итог.get("разделы")), (0, []))

    print("2. заливка кладёт самопроверку в строку «Прогоны»")
    (п / "audit.json").write_text(json.dumps({
        "прогон": "пустой", "собрано": "2026-10-09 05:00", "подозрений": 3,
        "разделы": [
            {"название": "2. Слово эфира не в словаре markers.json",
             "строки": ["err.ee: «otseülekanne» — 4 раза"]},
            {"название": "5. Передачи легли не на свой день",
             "строки": ["sport1tv.ro: страница 09.10 начинается с 23:30 08.10",
                        "digisport.ro: «Marți 06» — день назад"]},
        ],
        "справка": ["tv2.no: data-live проверено 06.10"],
    }, ensure_ascii=False), encoding="utf-8")
    залить(п)
    лог = последний_лог()
    сп = лог.get("самопроверка") or {}
    проверка("ключ «самопроверка» в логе", bool(сп))
    проверка("подозрений 3, разделов 2", (сп.get("подозрений"), len(сп.get("разделы") or [])), (3, 2))
    проверка("строки раздела на месте",
             (сп.get("разделы") or [{}])[1].get("строки", [None])[0],
             "sport1tv.ro: страница 09.10 начинается с 23:30 08.10")
    проверка("справка в базу не едет", "справка" in сп, False)

    print("3. чужая самопроверка (другая метка «собрано») не клеится")
    п2 = папка_прогона("другой", "2026-10-09 09:00")
    shutil.copy(п / "audit.json", п2 / "audit.json")     # метка 05:00 ≠ 09:00
    залить(п2)
    проверка("без самопроверки", "самопроверка" in последний_лог(), False)

    print("4. прогон без audit.json — лог как раньше")
    п3 = папка_прогона("без", "2026-10-09 13:00")
    залить(п3)
    лог = последний_лог()
    проверка("ключа нет, остальные ключи целы",
             ("самопроверка" not in лог, "сбои" in лог and "режим" in лог), (True, True))

    print("5. страница «Прогоны»: список раскрывается, сырой лог без него")
    from app import web
    app = web.create_app() if hasattr(web, "create_app") else web.app
    c = app.test_client()
    c.post("/login", data={"password": "adm-test-1"})
    page = c.get("/runs").get_data(as_text=True)
    plain = re.sub(r"<[^>]+>", " ", page)
    проверка("страница открылась", "Прогоны" in plain)
    проверка("сводка «подозрений 3»", "самопроверка: подозрений 3" in plain)
    проверка("строка подозрения видна", "digisport.ro: «Marți 06» — день назад" in plain)
    проверка("название раздела с числом", "5. Передачи легли не на свой день — 2" in plain)
    код = re.findall(r"<code[^>]*>(.*?)</code>", page, re.S)
    проверка("в сыром логе самопроверки нет", any("самопроверка" in x for x in код), False)
    проверка("сырой лог на месте (режим)", any("полный обход" in x for x in код))

    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

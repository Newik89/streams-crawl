# -*- coding: utf-8 -*-
"""Самопроверка №13 после склейки на сервере (`scripts/audit_merge.py`).

Правило (б) починки самопроверки №13 (20.10): сверка списка «показано_нет»
с витриной ПОСЛЕ склейки, память прошлых сборов (красное — только новое),
счёт матчами, в строке — шаг потери. Каждое правило шапки `audit_merge.py`
проверяется здесь.

В сеть не ходит. База — пустая, во временной папке. Запуск:

    venv\\Scripts\\python.exe scripts/test_audit_merge.py
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

TMP = Path(tempfile.mkdtemp(prefix="audit-merge-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")
os.environ["STREAMS_ADMIN_PASSWORD"] = "adm-test-1"

from app import db, store  # noqa: E402

зелёных = красных = 0

ШАГ_СНЯТО = ("снято фильтром «угаданный эфир без эталона»: эфир угадан, "
             "а пары нет в эталоне ±3 ч")
ШАГ_ОТСЕВ = "отсев: запись или студия: «REL»"


def проверка(имя: str, вышло, ждём=True, extra="") -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r} {extra}")


def sql(запрос: str, *арг):
    conn = db.connect()
    try:
        cur = conn.execute(запрос, арг)
        rows = cur.fetchall()
        conn.commit()
        return rows if запрос.lstrip().startswith("SELECT") else cur.lastrowid
    finally:
        conn.close()


def матч(сайт, канал, fs_id, эталон, начало, шаг=ШАГ_СНЯТО, подпись="") -> dict:
    return {"сайт": сайт, "канал": канал, "показ": начало, "подпись": подпись or эталон,
            "fs_id": fs_id, "эталон": эталон, "начало": начало, "шаг": шаг}


def прогон(собрано: str, строк13: int) -> int:
    """Строка `runs`, как её пишет `store.log_run` с самопроверкой GitHub:
    раздел 2 (одна строка) и раздел 13 (`строк13` строк по сайтам)."""
    разделы = [{"название": "2. Слово эфира не в словаре markers.json",
                "строки": ["err.ee: «otseülekanne» — 4 раза"]}]
    if строк13:
        разделы.append({"название": "13. Сайт показал матч эталона в эфир, а канала "
                                    "у игры на витрине нет",
                        "строки": [f"сайт{i}.ro: старая строка" for i in range(строк13)]})
    лог = {"режим": "полный обход, окно 6 суток",
           "самопроверка": {"подозрений": 1 + строк13, "разделы": разделы}}
    return sql("INSERT INTO runs (finished_at, log) VALUES (?, ?)",
               store.kyiv_from_utc(собрано), json.dumps(лог, ensure_ascii=False))


def аудит(имя: str, собрано: str, матчи: list) -> Path:
    п = TMP / f"{имя}.json"
    п.write_text(json.dumps({"собрано": собрано, "подозрений": 0, "разделы": [],
                             "показано_нет": матчи}, ensure_ascii=False), encoding="utf-8")
    return п


def слить(п: Path, *ещё: str) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "audit_merge.py"),
                        "--file", str(п), *ещё],
                       capture_output=True, text=True, encoding="utf-8", env=os.environ)
    return r.returncode, (r.stdout + r.stderr).strip()


def самопроверка(run_id: int) -> dict:
    return json.loads(sql("SELECT log FROM runs WHERE id = ?", run_id)[0]["log"])["самопроверка"]


def раздел13(сп: dict) -> dict | None:
    return next((r for r in сп["разделы"] if r["название"].startswith("13.")), None)


def память() -> dict:
    conn = db.connect()
    try:
        return json.loads(db.get_setting(conn, "audit13_seen", "{}"))
    finally:
        conn.close()


def снимок() -> tuple:
    return ([tuple(r) for r in sql("SELECT id, log FROM runs ORDER BY id") or []],
            [tuple(r) for r in sql("SELECT key, value FROM settings ORDER BY key") or []])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = db.connect()
    db.init_db(conn)
    conn.close()

    # витрина после склейки
    prima = sql("INSERT INTO sources (domain, name, base_url) VALUES ('primaplay.ro', 'p', 'x')")
    progr = sql("INSERT INTO sources (domain, name, base_url) "
                "VALUES ('www.programetv.ro', 'p', 'x')")
    digi = sql("INSERT INTO sources (domain, name, base_url) VALUES ('digisport.ro', 'd', 'x')")
    sportro = sql("INSERT INTO sources (domain, name, base_url) VALUES ('sport.ro', 's', 'x')")
    ps5 = sql("INSERT INTO channels (canonical_name, slug) VALUES ('Prima Sport 5', 'ps5')")
    ps1 = sql("INSERT INTO channels (canonical_name, slug) VALUES ('Prima Sport 1', 'ps1')")
    ds1 = sql("INSERT INTO channels (canonical_name, slug) VALUES ('Digi Sport 1', 'ds1')")
    os2 = sql("INSERT INTO channels (canonical_name, slug) VALUES ('Orange Sport 2', 'os2')")

    def игра(дом, гости, начало, флаг=None) -> int:
        return sql("INSERT INTO events (sport, team_home_auto, team_away_auto, start_utc, "
                   "start_kyiv, flags) VALUES ('F', ?, ?, ?, ?, ?)",
                   дом, гости, начало, начало, флаг)

    def отметка(игра_id, канал, сайт, промахов=0):
        sql("INSERT INTO event_channels (event_id, channel_id, source_id, miss_count) "
            "VALUES (?, ?, ?, ?)", игра_id, канал, сайт, промахов)

    отметка(игра("Stuttgart", "Atletico Madrid", "2026-10-20 22:00", "fs:AAA"), ps5, prima)
    отметка(игра("Rapid Wien", "Sturm Graz", "2026-10-20 19:00", "fs:BBB"), ps1, progr)
    отметка(игра("CFR Cluj", "FCSB", "2026-10-21 18:00", "fs:CCC"), ds1, digi,
            промахов=store.MISS_LIMIT)
    отметка(игра("Dinamo Bucuresti", "Rapid Bucuresti", "2026-10-21 20:00"), os2, sportro)

    A = матч("primaplay.ro", "Prima Sport 5", "AAA", "Stuttgart — Atl. Madrid", "2026-10-20T22:00")
    B = матч("primaplay.ro", "PRIMA SPORT 1", "BBB", "Rapid Wien — Sturm", "2026-10-20T19:00")
    C = матч("digisport.ro", "Digi Sport 1", "CCC", "CFR Cluj — FCSB", "2026-10-21T18:00")
    D = матч("sport.ro", "Orange Sport 2", "", "Rapid Bucuresti — Dinamo Bucuresti",
             "2026-10-21T21:30")
    E = матч("digisport.ro", "Digi Sport 2", "DDD", "Petrolul — Otelul", "2026-10-21T15:00",
             шаг=ШАГ_ОТСЕВ)
    F = матч("sport.ro", "Orange Sport 2", "", "Rapid Bucuresti — Dinamo Bucuresti",
             "2026-10-22T03:00")

    print("1. --dry-run: итог печатается, база не тронута (правило 7)")
    run1 = прогон("2026-10-20 05:00", 3)
    ф1 = аудит("сбор1", "2026-10-20 05:00", [A, B, C, D, E, F])
    до = снимок()
    код, вывод = слить(ф1, "--dry-run")
    проверка("код 0", код, 0, вывод)
    проверка("итог одной строкой",
             "самопроверка после склейки: матчей 6, новых 3, старых 0, склейка добрала 3" in вывод,
             True, вывод)
    проверка("память и лог не записаны", снимок(), до)

    print("2. первый сбор: сверка с витриной и новые (правила 2, 3, 4)")
    код, вывод = слить(ф1)
    проверка("код 0", код, 0, вывод)
    сп = самопроверка(run1)
    р = раздел13(сп) or {"название": "", "строки": []}
    текст = " | ".join(р["строки"])
    проверка("название с числами матчей",
             р["название"].endswith("после склейки: матчей 6, новых 3, старых 0, "
                                    "склейка добрала 3"), True, р["название"])
    проверка("добрала по своему сайту (A) и тем же каналу с другого сайта (B)",
             "primaplay.ro" in текст, False, текст)
    проверка("перечёркнутая отметка не считается (C потерян)", "CFR Cluj" in текст, True)
    проверка("без fs_id: пара в ±3 ч добрана (D), вне окна потеряна (F)",
             ("21.10 21:30" in текст, "22.10 03:00" in текст), (False, True), текст)
    проверка("строка по сайту: новых/старых и шаги",
             р["строки"][0].startswith("digisport.ro: новых 2, старых 0 — шаги: ")
             and "отсев: запись или студия ×1" in р["строки"][0]
             and "снято фильтром «угаданный эфир без эталона» ×1" in р["строки"][0],
             True, р["строки"][0] if р["строки"] else "")
    проверка("подозрений пересчитано: 1 + 3 − 3 + 2 = 3, новых_13 = 3",
             (сп["подозрений"], сп.get("новых_13")), (3, 3))
    проверка("в памяти три потерянных с датой сбора",
             память(), {"CCC|digisport.ro": "2026-10-20 08:00",
                        "DDD|digisport.ro": "2026-10-20 08:00",
                        "Rapid Bucuresti — Dinamo Bucuresti|2026-10-22T03:00|sport.ro":
                            "2026-10-20 08:00"})

    print("3. тот же сбор второй раз — ничего не удваивается (правило 5)")
    код, вывод = слить(ф1)
    сп2 = самопроверка(run1)
    проверка("те же числа, матчи всё ещё новые",
             (код, сп2["подозрений"], сп2.get("новых_13"), len(сп2["разделы"])), (0, 3, 3, 2),
             вывод)
    проверка("раздел тот же слово в слово", раздел13(сп2), раздел13(сп))

    print("4. второй сбор: старые с датой первого, чистка памяти (правило 3)")
    conn = db.connect()
    стара = память()
    стара["OLD|x.ro"] = "2026-10-05 08:00"      # старше 10 суток — вычистить
    стара["MID|x.ro"] = "2026-10-15 08:00"      # 5 суток — оставить
    db.set_setting(conn, "audit13_seen", json.dumps(стара, ensure_ascii=False))
    conn.close()
    run2 = прогон("2026-10-20 14:00", 1)
    G = матч("digisport.ro", "Digi Sport 1", "EEE", "Farul — Hermannstadt", "2026-10-22T19:00")
    код, вывод = слить(аудит("сбор2", "2026-10-20 14:00", [C, E, G]))
    сп = самопроверка(run2)
    р = раздел13(сп) or {"название": "", "строки": [""]}
    проверка("итог: новых 1, старых 2",
             "матчей 3, новых 1, старых 2, склейка добрала 0" in вывод, True, вывод)
    проверка("строка сайта: новых 1, старых 2, у старых дата первого сбора",
             р["строки"][0].startswith("digisport.ro: новых 1, старых 2")
             and "; старые: " in р["строки"][0] and "с 20.10 08:00" in р["строки"][0],
             True, р["строки"][0])
    проверка("первый сбор (run1) не тронут", самопроверка(run1)["новых_13"], 3)
    п = память()
    проверка("память: старше 10 суток вычищено, 5 суток и прежние на месте",
             ("OLD|x.ro" in п, п.get("MID|x.ro"), п.get("CCC|digisport.ro"),
              п.get("EEE|digisport.ro")),
             (False, "2026-10-15 08:00", "2026-10-20 08:00", "2026-10-20 17:00"))
    проверка("подозрений 1 + 1 − 1 + 1 = 2, новых_13 = 1",
             (сп["подозрений"], сп["новых_13"]), (2, 1))

    print("5. всё добрала склейка — раздела нет (правило 4)")
    run3 = прогон("2026-10-21 05:00", 2)
    код, вывод = слить(аудит("сбор3", "2026-10-21 05:00", [A, B]))
    сп = самопроверка(run3)
    проверка("раздела 13 нет, подозрений 3 − 2 = 1, новых_13 = 0",
             (раздел13(сп), сп["подозрений"], сп["новых_13"], код), (None, 1, 0, 0), вывод)

    print("6. нет строки «Прогоны» — код 0, база не тронута (правило 1)")
    до = снимок()
    код, вывод = слить(аудит("чужой", "2026-01-01 00:00", [C]))
    проверка("код 0 и пояснение", (код, "ничего не меняю" in вывод), (0, True), вывод)
    проверка("база не тронута", снимок(), до)

    print("7. битый файл — код 1 и понятная строка (правило 6)")
    битый = TMP / "битый.json"
    битый.write_text("{не json", encoding="utf-8")
    код, вывод = слить(битый)
    проверка("код 1, база не тронута", (код, "не прочитать" in вывод, снимок() == до),
             (1, True, True), вывод)

    print("8. «Прогоны»: в сводке «новых в 13» (красным, если есть)")
    from app import web
    app = web.create_app() if hasattr(web, "create_app") else web.app
    c = app.test_client()
    c.post("/login", data={"password": "adm-test-1"})
    page = c.get("/runs").get_data(as_text=True)
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
    проверка("сводка второго сбора", "подозрений 2 , новых в 13: 1" in plain
             or "подозрений 2, новых в 13: 1" in plain, True)
    проверка("новые красным, ноль обычным",
             ('class="new13">1<' in page, 'class="old13">0<' in page), (True, True))

    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

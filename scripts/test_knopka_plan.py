# -*- coding: utf-8 -*-
r"""Книга 135 (15.11.2026): кнопка «включить / выключить» источник доходит до
плана обхода.

Слово владельца 15.11: «если я её нажал, значит сайт не должен ходить к
выключенному». Случай: sporting.pt был выключен кнопкой, а GitHub продолжал
к нему ходить — кнопка меняла только базу, а обход идёт по файлу плана.
Правила К1–К5 — в `app/plan_push.py`.

В сеть не ходит, настоящий план не трогает: файл плана и база — временные,
отправка плана подменена. Запуск: python scripts/test_knopka_plan.py
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="knopka-plan-test-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import crawl, db, plan_push, sources, web  # noqa: E402
import add_azam  # noqa: E402
import games_import  # noqa: E402

зелёных = красных = 0
САЙТ = "azamtvmax.com"                       # есть в списке обхода `PILOTS`
ОТПРАВЛЕНО: list[str] = []


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


# временный файл плана и подменённая отправка: настоящий план не трогаем
plan_push.PLAN = TMP / "crawl_plan.json"
plan_push._push_plan = lambda message: (ОТПРАВЛЕНО.append(message) or "тест: план отправлен")


def план(*домены: str) -> None:
    plan_push.PLAN.write_text(json.dumps(
        {"days": 2, "sources": [{"domain": d, "channels": []} for d in домены]},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def в_плане() -> list[str]:
    return plan_push.plan_domains()


db.init_db()
conn = db.connect()
add_azam.apply(conn)                         # источник с двумя страницами каналов
ид = conn.execute("SELECT id FROM sources WHERE domain = ?", (САЙТ,)).fetchone()["id"]
conn.execute("INSERT INTO sources (domain, name, base_url, country, timezone, enabled, role, "
             "access, status) VALUES ('drugoy.tv', 'Другой', 'https://drugoy.tv/', 'XX', 'UTC', "
             "1, 'schedule', 'open', 'ok')")
conn.commit()

print("К1. Источник выключили — он уходит из плана обхода")
план("nova.bg", САЙТ, "teleman.pl")
sources.toggle_enabled(conn, ид)
сказано = plan_push.set_enabled(conn, САЙТ, False)
проверка("запись сайта убрана из плана, остальные на месте и в том же порядке",
         в_плане(), ["nova.bg", "teleman.pl"])
проверка("план отправлен, владельцу сказано, что GitHub к сайту больше не ходит",
         (len(ОТПРАВЛЕНО), САЙТ in ОТПРАВЛЕНО[-1], "выключен" in ОТПРАВЛЕНО[-1],
          "GitHub к нему больше не ходит" in сказано), (1, True, True, True))
сказано = plan_push.set_enabled(conn, САЙТ, False)
проверка("сайта в плане и не было — ничего не делаем, план не отправляем",
         (сказано, len(ОТПРАВЛЕНО)), ("в плане обхода его и не было", 1))

print("К2. Источник включили — он возвращается в план")
sources.toggle_enabled(conn, ид)
сказано = plan_push.set_enabled(conn, САЙТ, True)
запись = json.loads(plan_push.PLAN.read_text(encoding="utf-8"))["sources"][-1]
проверка("запись сайта встала в конец плана — та же, что дала бы полная пересборка",
         (в_плане(), запись == crawl.templates(conn, [САЙТ])[0], len(запись["channels"])),
         (["nova.bg", "teleman.pl", САЙТ], True, 2))
проверка("план отправлен, владельцу сказано «возвращён»",
         (len(ОТПРАВЛЕНО), "включён" in ОТПРАВЛЕНО[-1], "в план обхода возвращён" in сказано),
         (2, True, True))
проверка("сайт уже в плане — второй раз не добавляется",
         (plan_push.set_enabled(conn, САЙТ, True), в_плане().count(САЙТ), len(ОТПРАВЛЕНО)),
         ("в плане обхода уже стоит", 1, 2))
проверка("сайта нет в списке ежедневного обхода (справочник, необкатанный) — в план не встаёт",
         ("не входит" in plan_push.set_enabled(conn, "drugoy.tv", True), "drugoy.tv" in в_плане(),
          len(ОТПРАВЛЕНО)), (True, False, 2))
план("nova.bg")
conn.execute("UPDATE sources SET status = 'deferred' WHERE id = ?", (ид,))
conn.commit()
проверка("сайт отложен владельцем (не проходит отбор плана) — в план не встаёт",
         ("не проходит отбор" in plan_push.set_enabled(conn, САЙТ, True), в_плане(), len(ОТПРАВЛЕНО)),
         (True, ["nova.bg"], 2))
conn.execute("UPDATE sources SET status = 'ok' WHERE id = ?", (ид,))
conn.commit()

print("К5. Сторож после заливки: сайт в плане, а в базе выключен")
план("nova.bg", САЙТ, "netu-v-baze.tv")
conn.execute("UPDATE sources SET enabled = 0 WHERE id = ?", (ид,))
conn.commit()
проверка("сторож видит выключенный сайт в плане; сайт, которого в базе нет, не трогает",
         plan_push.disabled_in_plan(conn), [САЙТ])
до = plan_push.PLAN.read_text(encoding="utf-8")
строки = plan_push.heal_plan(conn, apply=False)
проверка("локальная копия: сторож только говорит, файл плана не меняет",
         (len(строки), САЙТ in строки[0], plan_push.PLAN.read_text(encoding="utf-8") == до,
          len(ОТПРАВЛЕНО)), (1, True, True, 2))
строки = plan_push.heal_plan(conn, apply=True)
запись_прогонов = conn.execute("SELECT log FROM runs ORDER BY id DESC LIMIT 1").fetchone()
проверка("на сервере: сайт убран из плана, план отправлен, владельцу строка в «Прогоны»",
         (в_плане(), len(ОТПРАВЛЕНО), САЙТ in ОТПРАВЛЕНО[-1],
          запись_прогонов is not None and САЙТ in запись_прогонов["log"]
          and "GitHub к ним больше не ходит" in запись_прогонов["log"]),
         (["nova.bg", "netu-v-baze.tv"], 3, True, True))
проверка("в плане чисто — сторож молчит и ничего не отправляет",
         (plan_push.heal_plan(conn, apply=True), len(ОТПРАВЛЕНО)), ([], 3))
plan_push.PLAN.write_text("{битый файл", encoding="utf-8")
проверка("файл плана битый — сторож не падает", plan_push.heal_plan(conn, apply=True), [])
conn.close()

print("Подключение: кнопка админки и заливка сбора зовут новые правила")
проверка("кнопка «включить / выключить» доводит решение до плана (`set_enabled`)",
         "plan_push.set_enabled(conn, row[\"domain\"], bool(new))" in inspect.getsource(web))
проверка("заливка сбора зовёт сторожа (`heal_plan`), его ошибка заливку не роняет",
         ("plan_push.heal_plan(conn)" in inspect.getsource(games_import),
          "сверка плана с выключенными сайтами не прошла" in inspect.getsource(games_import)),
         (True, True))
проверка("список сайтов обхода — тот же, что у полной пересборки",
         САЙТ in plan_push._pilots() and "nova.bg" in plan_push._pilots())

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

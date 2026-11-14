"""Книга 123 (14.11): сторож «канал замолчал» (`app/silence.py`, М1–М5).

Случай: ipko.tv 13.11 сменил запись матчей на каналах SuperSport — страницы
открывались, а игр с этих каналов не стало, и узнал об этом владелец сам.

Запуск: python scripts/test_silence.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="silence-test-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import db, silence  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def игра(*строки) -> dict:
    """Игра сбора: строки — (сайт, канал)."""
    return {"entries": [{"source": s, "channel": c} for s, c in строки]}


def сбор(каналы: dict, молчат: list | None = None) -> dict:
    """Прошлый games.json: счёт каналов и записи о молчащих."""
    return {silence.COUNTS_KEY: каналы, silence.SILENT_KEY: молчат or []}


print("Счёт игр по каналам")
счёт = silence.channel_counts([
    игра(("ipko.tv", "SuperSport 1"), ("ipko.tv", "SuperSport 1"), ("www.ipko.tv", "Sport 1")),
    игра(("ipko.tv", "SuperSport 1"), ("nova.bg", "Diema Sport")),
    игра(("", "Пусто"), ("ipko.tv", "")),
])
проверка("игра засчитана каналу один раз, сайт — без www.",
         счёт, {"ipko.tv": {"SuperSport 1": 2, "Sport 1": 1}, "nova.bg": {"Diema Sport": 1}})

print("М1. Канал замолчал: давал игры, теперь ноль, а сайт прочитан")
БЫЛО = {"ipko.tv": {"SuperSport 1": 4, "SuperSport 2": 3, "Sport 1": 5, "Tring 9": 1}}
СЕЙЧАС = {"ipko.tv": {"Sport 1": 6}}
ПРОЧИТАНО = {"ipko.tv": 626}
первый = silence.check(СЕЙЧАС, сбор(БЫЛО), ПРОЧИТАНО)
проверка("случай ipko.tv: SuperSport 1 и 2 замолчали, сбор первый",
         первый, [{"сайт": "ipko.tv", "канал": "SuperSport 1", "было": 4, "подряд": 1},
                  {"сайт": "ipko.tv", "канал": "SuperSport 2", "было": 3, "подряд": 1}])
проверка("канал с одной игрой в прошлом сборе — не в счёт (игр и так было мало)",
         any(r["канал"] == "Tring 9" for r in первый), False)
проверка("сайт не прочитан (сбой сбора) — это не тишина, записей нет",
         silence.check(СЕЙЧАС, сбор(БЫЛО), {"ipko.tv": 0}), [])
проверка("прошлого сбора нет — сравнивать не с чем", silence.check(СЕЙЧАС, {}, ПРОЧИТАНО), [])

print("М2. Тишина считается сборами подряд; канал вернулся — запись снята")
второй = silence.check(СЕЙЧАС, сбор(СЕЙЧАС, первый), ПРОЧИТАНО)
проверка("второй сбор тишины: подряд 2, «было» — число до тишины",
         [(r["канал"], r["было"], r["подряд"]) for r in второй],
         [("SuperSport 1", 4, 2), ("SuperSport 2", 3, 2)])
третий = silence.check(СЕЙЧАС, сбор(СЕЙЧАС, второй), ПРОЧИТАНО)
проверка("третий сбор тишины: подряд 3", [r["подряд"] for r in третий], [3, 3])
вернулся = silence.check({"ipko.tv": {"Sport 1": 6, "SuperSport 1": 2}}, сбор(СЕЙЧАС, третий), ПРОЧИТАНО)
проверка("SuperSport 1 дал игру — его запись снята, SuperSport 2 молчит дальше",
         [(r["канал"], r["подряд"]) for r in вернулся], [("SuperSport 2", 4)])
сбой = silence.check(СЕЙЧАС, сбор(СЕЙЧАС, второй), {"ipko.tv": 0})
проверка("посреди тишины сайт не прочитан — счёт не растёт и не теряется",
         [r["подряд"] for r in сбой], [2, 2])

print("М3–М4. Уведомление — одно, на третьем сборе тишины")
проверка("первый и второй сбор — слов нет",
         (silence.words(первый, СЕЙЧАС), silence.words(второй, СЕЙЧАС)), ([], []))
слова = silence.words(третий, СЕЙЧАС)
проверка("третий сбор — одна строка на сайт, оба канала в ней",
         (len(слова), "SuperSport 1 (было игр: 4)" in слова[0], "SuperSport 2" in слова[0]),
         (1, True, True))
проверка("…сказано, что с остальных каналов сайта игры идут",
         "с остальных каналов сайта игры идут" in слова[0], True)
четвёртый = silence.check(СЕЙЧАС, сбор(СЕЙЧАС, третий), ПРОЧИТАНО)
проверка("четвёртый сбор — слов нет: об этой тишине уже сказано",
         silence.words(четвёртый, СЕЙЧАС), [])
весь = [{"сайт": "tv8.com.tr", "канал": "TV8", "было": 5, "подряд": 3}]
проверка("замолчали все каналы сайта — «игр с сайта нет совсем»",
         "игр с сайта нет совсем" in silence.words(весь, {})[0], True)

print("М3 на сервере: строка в «Прогоны», перезаливка того же файла молчит")
db.init_db()
conn = db.connect()


def строк_в_прогонах() -> int:
    return conn.execute("SELECT COUNT(*) FROM runs WHERE log LIKE '%каналы замолчали%'").fetchone()[0]


файл = {"собрано": "2026-11-14 14:49", silence.SILENT_KEY: третий, silence.COUNTS_KEY: СЕЙЧАС}
проверка("заливка сбора с тишиной на пороге — одна строка",
         (len(silence.after_import(conn, файл)), строк_в_прогонах()), (1, 1))
проверка("перезаливка того же файла — второй строки нет",
         (silence.after_import(conn, файл), строк_в_прогонах()), ([], 1))
проверка("сбор без тишины — строк нет",
         silence.after_import(conn, {"собрано": "2026-11-14 18:49", silence.SILENT_KEY: [],
                                     silence.COUNTS_KEY: СЕЙЧАС}), [])
проверка("файл сбора сервера без этих ключей — без падения, строк нет",
         silence.after_import(conn, {"собрано": "2026-11-14 06:40", "games": []}), [])
conn.close()

print("М5. Разбор: полный сбор считает заново, неполный переносит как есть")
sys.path.insert(0, str(ROOT / "scripts"))
import parse_live  # noqa: E402

итог = {"games": [игра(("ipko.tv", "Sport 1"))] * 6}
записи = parse_live.silence_keys(итог, сбор(БЫЛО), ПРОЧИТАНО, full=True)
проверка("полный сбор: счёт каналов посчитан, замолчавшие найдены",
         (итог[silence.COUNTS_KEY], [r["канал"] for r in записи]),
         ({"ipko.tv": {"Sport 1": 6}}, ["SuperSport 1", "SuperSport 2"]))
итог = {"games": [игра(("ipko.tv", "Sport 1"))]}
parse_live.silence_keys(итог, сбор(БЫЛО, первый), ПРОЧИТАНО, full=False)
проверка("дозабор или скан даты: счёт и записи перенесены из прошлого сбора без изменений",
         (итог[silence.COUNTS_KEY], итог[silence.SILENT_KEY]), (БЫЛО, первый))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

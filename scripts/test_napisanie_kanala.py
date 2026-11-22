# -*- coding: utf-8 -*-
r"""Синоним канала по написанию (книга 174, слова владельца 22.11.2026: «если
поменялось написание его тоже добавить в синоним, например было 2 пробела стал
1 или убрался знак восклицания»; «Tvr Sport HD» / «TVR Sport HD» — «так это
тоже синоним»).

Повод (сбор 20.11.2026): ntvplus.tv пишет «МАТЧ! АРЕНА  (HD)» с двумя
пробелами, в списке владельца — с одним: 128 строк не доходили до базы;
programetv.ro: «Tvr Sport HD» против «TVR Sport HD» — 58 строк.

Что сторожится (правила Н1–Н6 `app/channel_spelling.py`):

1. Н2: написание — без регистра, пробелов и знаков препинания; знаки, которыми
   каналы различаются («+», «&», «/»), остаются;
2. Н1–Н3: `Listed` — `имя in список` верно для другого написания; двусмысленное
   написание не угадывается; обычные действия с множеством работают;
3. Н4: `apply` ставит строке имя из списка и помнит написание сайта;
4. Н6: любой разборщик со сверкой `channel not in channels` берёт такой канал,
   не меняясь сам; `parse_live` даёт разборщикам `Listed` и зовёт `apply`;
5. Н5: сервер записывает написание синонимом канала — один раз, с одной
   строкой в «Прогоны»; канал не найден — молчит.

В сеть не ходит, база — временная:

    python scripts/test_napisanie_kanala.py
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="napisanie-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import channel_spelling, db  # noqa: E402
from app.channel_spelling import Listed, key  # noqa: E402
from app.parsers import Program  # noqa: E402
import games_import  # noqa: E402
import parse_live  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


print("1. Написание (Н2)")
проверка("два пробела и один — одно написание", key("МАТЧ! АРЕНА  (HD)"), key("МАТЧ! АРЕНА (HD)"))
проверка("пропал восклицательный знак — одно написание", key("МАТЧ АРЕНА (HD)"), key("МАТЧ! АРЕНА (HD)"))
проверка("регистр — одно написание", key("Tvr Sport HD"), key("TVR Sport HD"))
проверка("дефис и пробел — одно написание", key("Sport-Klub 1"), key("Sport Klub 1"))
проверка("«+» различает каналы", key("ספורט 5+") != key("ספורט 5"))
проверка("«Canal+ Sport» и «Canal Sport» — разные", key("Canal+ Sport") != key("Canal Sport"))
проверка("номер различает каналы", key("Arena Sport 1") != key("Arena Sport 11"))
проверка("«HD» различает каналы", key("TVR Sport") != key("TVR Sport HD"))
проверка("имя из одних знаков — пустое написание", key("—!?"), "")

print("2. Список сайта (Н1–Н3)")
список = Listed({"МАТЧ! АРЕНА (HD)", "МАТЧ! ФУТБОЛ 1 (HD)", "TVR Sport HD", "ספורט 5"})
проверка("буква в букву — в списке", "МАТЧ! АРЕНА (HD)" in список)
проверка("другое написание — в списке", ["МАТЧ! АРЕНА  (HD)" in список, "Tvr Sport HD" in список, "матч арена hd" in список],
         [True, True, True])
проверка("имя из списка для написания сайта", список.listed("Tvr Sport HD"), "TVR Sport HD")
проверка("другой канал — не в списке", ["МАТЧ! ФУТБОЛ 2 (HD)" in список, "ספורט 5+" in список, "" in список, None in список],
         [False, False, False, False])
двойной = Listed({"DAZN LALIGA", "DAZN LaLiga", "DAZN 1"})
проверка("написание общее для двух имён списка — не угадываем",
         ["Dazn Laliga" in двойной, двойной.listed("dazn laliga"), "DAZN LaLiga" in двойной, "dazn 1" in двойной],
         [False, "", True, True])
проверка("это множество: длина, перебор, объединение, пустой список — ложь",
         [len(список), sorted(список)[0], len(список | {"X"}), bool(Listed()), bool(Listed(None))],
         [4, "TVR Sport HD", 5, False, False])

print("3. Строке — имя из списка (Н4)")


def строка(канал: str) -> Program:
    return Program(channel_raw=канал, title="Футбол. Зенит - Спартак", start=datetime(2026, 11, 22, 19, 0, tzinfo=KYIV))


строки = [строка("МАТЧ! АРЕНА  (HD)"), строка("МАТЧ! АРЕНА (HD)"), строка("Чужой канал"), строка("Tvr Sport HD")]
найдено: dict = {}
проверка("поправлено две строки из четырёх", channel_spelling.apply(строки, список, найдено), 2)
проверка("имена строк — из списка, чужой канал не тронут", [p.channel_raw for p in строки],
         ["МАТЧ! АРЕНА (HD)", "МАТЧ! АРЕНА (HD)", "Чужой канал", "TVR Sport HD"])
проверка("написание сайта осталось в строке",
         [(p.extra or {}).get(channel_spelling.SPELLED) for p in строки], ["МАТЧ! АРЕНА  (HD)", None, None, "Tvr Sport HD"])
проверка("что найдено — для games.json", найдено,
         {"МАТЧ! АРЕНА  (HD)": "МАТЧ! АРЕНА (HD)", "Tvr Sport HD": "TVR Sport HD"})
проверка("обычное множество вместо списка — ничего не делаем",
         channel_spelling.apply([строка("Tvr Sport HD")], {"TVR Sport HD"}, {}), 0)
проверка("слова для лога", channel_spelling.words({"programetv.ro": {"Tvr Sport HD": "TVR Sport HD"}}),
         ["programetv.ro: «Tvr Sport HD» = «TVR Sport HD»"])

print("4. Одно место для всех разборщиков (Н6)")


def разборщик(text, day=None, tz=None, url="", channels=None):
    """Как 72 разборщика сайтов: канал не из списка — мимо."""
    out = []
    for channel in text.split("|"):
        if channels and channel not in channels:
            continue
        out.append(строка(channel))
    return out


проверка("разборщик со сверкой «channel not in channels» берёт другое написание",
         [p.channel_raw for p in разборщик("МАТЧ! АРЕНА  (HD)|Чужой|Tvr Sport HD", channels=список)],
         ["МАТЧ! АРЕНА  (HD)", "Tvr Sport HD"])
план = TMP / "plan.json"
план.write_text(json.dumps({"sources": [{"domain": "programetv.ro", "timezone": "Europe/Bucharest",
                                         "include": ["TVR Sport HD", "Digi Sport 1"]}]}), encoding="utf-8")
настройки = parse_live.source_settings(план)
проверка("`parse_live.source_settings` отдаёт список сайта как `Listed`",
         [isinstance(настройки["programetv.ro"]["include"], Listed), "Tvr Sport HD" in настройки["programetv.ro"]["include"]],
         [True, True])
код = inspect.getsource(parse_live)
проверка("детектор: `parse_live` зовёт `channel_spelling.apply` и кладёт находки в итог сбора",
         ["channel_spelling.apply(" in код, "payload[channel_spelling.KEY]" in код], [True, True])
проверка("детектор: заливка на сервере зовёт `channel_spelling.after_import`",
         "channel_spelling.after_import(" in inspect.getsource(games_import))

print("5. Сервер: написание — синонимом канала (Н5)")
db.init_db()
conn = db.connect()
conn.execute("INSERT INTO sources (domain, name, base_url, country, timezone, enabled, role, access, status) "
             "VALUES ('ntvplus.tv', 'ntv', 'https://ntvplus.tv/', 'RU', 'Europe/Moscow', 1, 'schedule', 'open', 'ok')")
conn.execute("INSERT INTO sources (domain, name, base_url, country, timezone, enabled, role, access, status) "
             "VALUES ('programetv.ro', 'p', 'https://www.programetv.ro/', 'RO', 'Europe/Bucharest', 1, 'schedule', 'open', 'ok')")
ntv = conn.execute("SELECT id FROM sources WHERE domain = 'ntvplus.tv'").fetchone()[0]
ro = conn.execute("SELECT id FROM sources WHERE domain = 'programetv.ro'").fetchone()[0]
conn.execute("INSERT INTO channels (id, canonical_name, slug, country) VALUES (73, 'МАТЧ! АРЕНА (HD)', 'match-arena-hd', 'RU')")
conn.execute("INSERT INTO channel_aliases (channel_id, alias, source_id) VALUES (73, 'МАТЧ! АРЕНА (HD)', ?)", (ntv,))
conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, include) VALUES (?, 'МАТЧ! АРЕНА (HD)', 73, 1)", (ntv,))
conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, include) VALUES (?, 'TVR Sport HD', NULL, 1)", (ro,))
conn.commit()
итог = {channel_spelling.KEY: {"ntvplus.tv": {"МАТЧ! АРЕНА  (HD)": "МАТЧ! АРЕНА (HD)"},
                               "programetv.ro": {"Tvr Sport HD": "TVR Sport HD"},
                               "neizvestnyy.sayt": {"A": "B"}}}
сказано = channel_spelling.after_import(conn, итог)
проверка("записан один синоним — у канала, который в базе есть", len(сказано), 1)
проверка("синоним — у того же канала и сайта",
         conn.execute("SELECT channel_id FROM channel_aliases WHERE alias = 'МАТЧ! АРЕНА  (HD)' AND source_id = ?",
                      (ntv,)).fetchone()[0], 73)
проверка("канал, которого в базе ещё нет, и неизвестный сайт — молчим",
         conn.execute("SELECT count(*) FROM channel_aliases").fetchone()[0], 2)
проверка("строка в «Прогоны» — одна",
         conn.execute("SELECT count(*) FROM runs WHERE log LIKE '%написание канала%'").fetchone()[0], 1)
проверка("вторая заливка — молчим", channel_spelling.after_import(conn, итог), [])
проверка("итог сбора без находок — без падения", channel_spelling.after_import(conn, {}), [])
conn.close()

print(f"\nИТОГ: зелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

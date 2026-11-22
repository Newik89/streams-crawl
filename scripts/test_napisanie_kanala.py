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
3. Н4: `note` — детектор: написание сайта замечено, строки не меняются;
4. Н4: любой разборщик со сверкой `channel not in channels` берёт такой канал,
   не меняясь сам; `parse_live` даёт разборщикам `Listed` и зовёт `note`;
5. Н5: сервер (`store._channel_id` → `resolve`): написание без своего синонима
   идёт на канал списка сайта и записывается его синонимом — один раз, с одной
   строкой в «Прогоны»; канал списка ни разу не читался — заводится с именем
   из списка; у написания свой синоним уже есть — привязка не трогается;
   написание общее для двух имён списка — не угадывается.

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

from app import channel_spelling, db, store  # noqa: E402
from app.channel_spelling import Listed, key  # noqa: E402
from app.parsers import Program  # noqa: E402
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

print("3. Детектор написаний (Н4)")


def строка(канал: str) -> Program:
    return Program(channel_raw=канал, title="Футбол. Зенит - Спартак", start=datetime(2026, 11, 22, 19, 0, tzinfo=KYIV))


строки = [строка("МАТЧ! АРЕНА  (HD)"), строка("МАТЧ! АРЕНА (HD)"), строка("Чужой канал"), строка("Tvr Sport HD")]
найдено: dict = {}
проверка("замечено две строки из четырёх", channel_spelling.note(строки, список, найдено), 2)
проверка("строки не меняются — идут с написанием сайта", [p.channel_raw for p in строки],
         ["МАТЧ! АРЕНА  (HD)", "МАТЧ! АРЕНА (HD)", "Чужой канал", "Tvr Sport HD"])
проверка("что найдено — для лога и games.json", найдено,
         {"МАТЧ! АРЕНА  (HD)": "МАТЧ! АРЕНА (HD)", "Tvr Sport HD": "TVR Sport HD"})
проверка("обычное множество вместо списка — ничего не делаем",
         channel_spelling.note([строка("Tvr Sport HD")], {"TVR Sport HD"}, {}), 0)
проверка("слова для лога", channel_spelling.words({"programetv.ro": {"Tvr Sport HD": "TVR Sport HD"}}),
         ["programetv.ro: «Tvr Sport HD» = «TVR Sport HD»"])

print("4. Одно место для всех разборщиков (Н4)")


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
проверка("детектор: `parse_live` зовёт `channel_spelling.note` и кладёт находки в итог сбора",
         ["channel_spelling.note(" in код, "payload[channel_spelling.KEY]" in код], [True, True])
проверка("детектор: сервер зовёт `channel_spelling.resolve` там, где опознаёт канал строки",
         "channel_spelling.resolve(conn, raw, source)" in inspect.getsource(store._channel_id))

print("5. Сервер: канал для написания сайта (Н5)")
db.init_db()
conn = db.connect()


def сайт(domain: str, country: str):
    conn.execute("INSERT INTO sources (domain, name, base_url, country, timezone, enabled, role, access, status) "
                 "VALUES (?, ?, ?, ?, 'UTC', 1, 'schedule', 'open', 'ok')", (domain, domain, f"https://{domain}/", country))
    return conn.execute("SELECT * FROM sources WHERE domain = ?", (domain,)).fetchone()


def каналов() -> int:
    return conn.execute("SELECT count(*) FROM channels").fetchone()[0]


ntv, ro, es = сайт("ntvplus.tv", "RU"), сайт("programetv.ro", "RO"), сайт("movistarplus.es", "ES")
conn.execute("INSERT INTO channels (id, canonical_name, slug, country) VALUES (73, 'МАТЧ! АРЕНА (HD)', 'match-arena-hd', 'RU')")
conn.execute("INSERT INTO channel_aliases (channel_id, alias, source_id) VALUES (73, 'МАТЧ! АРЕНА (HD)', ?)", (ntv["id"],))
conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, include) VALUES (?, 'МАТЧ! АРЕНА (HD)', 73, 1)", (ntv["id"],))
conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, include) VALUES (?, 'TVR Sport HD', NULL, 1)", (ro["id"],))
conn.execute("INSERT INTO channels (id, canonical_name, slug, country) VALUES (203, 'DAZN LaLiga', 'dazn-laliga', 'ES')")
conn.execute("INSERT INTO channels (id, canonical_name, slug, country) VALUES (323, 'DAZN LALIGA', 'dazn-laliga-2', 'ES')")
conn.execute("INSERT INTO channel_aliases (channel_id, alias, source_id) VALUES (203, 'DAZN LaLiga', ?)", (es["id"],))
conn.execute("INSERT INTO channel_aliases (channel_id, alias, source_id) VALUES (323, 'DAZN LALIGA', ?)", (es["id"],))
conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, include) VALUES (?, 'DAZN LaLiga', 203, 1)", (es["id"],))
conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, include) VALUES (?, 'M+ Deportes', NULL, 1)", (es["id"],))
conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, include) VALUES (?, 'M+ DEPORTES', NULL, 1)", (es["id"],))
conn.commit()
было = каналов()
проверка("два пробела вместо одного — тот же канал, новый не заводится",
         [store._channel_id(conn, "МАТЧ! АРЕНА  (HD)", ntv), каналов()], [73, было])
проверка("написание записано синонимом этого канала",
         conn.execute("SELECT channel_id FROM channel_aliases WHERE alias = 'МАТЧ! АРЕНА  (HD)' AND source_id = ?",
                      (ntv["id"],)).fetchone()[0], 73)
проверка("строка в «Прогоны» — одна, второй раз молчим",
         [store._channel_id(conn, "МАТЧ! АРЕНА  (HD)", ntv),
          conn.execute("SELECT count(*) FROM runs WHERE log LIKE '%написание канала%'").fetchone()[0]], [73, 1])
новый = store._channel_id(conn, "Tvr Sport HD", ro)
проверка("канал списка ни разу не читался — заводится один канал, с именем из списка",
         [каналов(), conn.execute("SELECT canonical_name FROM channels WHERE id = ?", (новый,)).fetchone()[0].endswith("TVR Sport HD"),
          sorted(r[0] for r in conn.execute("SELECT alias FROM channel_aliases WHERE channel_id = ?", (новый,)))],
         [было + 1, True, ["TVR Sport HD", "Tvr Sport HD"]])
проверка("у написания сайта уже есть свой синоним — канал прежний, привязка не трогается",
         [store._channel_id(conn, "DAZN LALIGA", es), store._channel_id(conn, "DAZN LaLiga", es)], [323, 203])
до = каналов()
двойной_канал = store._channel_id(conn, "m+ deportes", es)
проверка("написание общее для двух имён списка сайта — не угадываем: канал заводится, как раньше",
         [каналов(), conn.execute("SELECT count(*) FROM runs WHERE log LIKE '%написание канала%'").fetchone()[0]], [до + 1, 2])
проверка("канал вне списка сайта — как раньше", каналов() + 1,
         (store._channel_id(conn, "Совсем другой", ntv), каналов())[1])
проверка("без сайта и пустое имя — без падения",
         [channel_spelling.resolve(conn, "X", None), channel_spelling.resolve(conn, "", ntv)], [None, None])
conn.close()

print(f"\nИТОГ: зелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

# -*- coding: utf-8 -*-
r"""Книга 162 (16.11.2026): ложная стадия «Final» у строки турнира на витрине.

ОШИБКА АССИСТЕНТА, пойманная на витрине после выкладки 16.11 13:57. Правило
книги 160 (`broadcast.show_stage`) вынимало из заголовка ОДНО слово события
турнира и искало стадию в остатке. primaplay.ro и programetv.ro зовут турнир
в заголовке дважды, на двух языках: «Turneul Campionilor Tenis: ATP Finals
Torino» — после первого слова оставалось «Finals», и три сессии группового
этапа (16.11 12:30, 16.11 19:00, 17.11 12:30) встали на витрину как «ATP
Finals Turin — Final».

Почему не поймано до выкладки (урок, слово владельца 16.11: «не просто
исправить, а внести в книгу ошибок, которые не должны повторяться»):
  * тест правила был на придуманных заголовках и нескольких с одного сайта, а
    не на ПОЛНОМ списке живых заголовков всех сайтов;
  * пробная заливка в копию базы смотрела строки базы, а подпись рисует
    витрина (`store.schedule`) — её пробный прогон не смотрел.

Что сторожит этот тест — класс, а не один заголовок:
  1. все 47 настоящих заголовков 13 сессий «ATP Finals Turin» с витрины 16.11
     (20 сайтов, 12 языков), прогнанные через ту же дорогу, что на сервере:
     заливка `store.save_games` → витрина `store.schedule`;
  2. ни одна сессия группового этапа (16–20.11) и дневная сессия 22.11 не
     несёт стадии; обе сессии 21.11 — «Semifinals»; вечерняя 22.11 — «Final»;
  3. то же по каждому заголовку отдельно (`broadcast.show_stage`): виноватый
     заголовок виден по имени, а не только итог сессии.
Новый сайт или новое написание турнира — дописать заголовок сюда.
В сеть не ходит, база временная. Запуск: python scripts/test_stadiya_zhivye_zagolovki.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="stadiya-zagolovki-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import broadcast, db, store  # noqa: E402

зелёных = красных = 0
ИМЯ = "ATP Finals Turin"
ЧАСЫ = datetime(2026, 11, 16, 0, 0)

#: сессия (начало по Киеву) → живые заголовки её отметок на витрине 16.11.2026
ЗАГОЛОВКИ = {
 "2026-11-16 19:00": [
  "2026 Nitto ATP Finals: Round Robin, Day 2",
  "ATP FINALS 2026",
  "ATP Finale (Torino): Parovi",
  "ATP: Nitto ATP Finals (2. den - čtyřhra)",
  "Dubl, dan 2, večernja sesija",
  "NITTO ATP FINALS (MATCH 2)",
  "Nitto ATP Finals",
  "Nitto ATP Finals: Groepsfase",
  "Nitto ATP Finals: Торино",
  "Tenis ATP Torino 2026",
  "Tenis Atp: Turneul Campionilor",
  "Tenis M - ATP: Torino - Turneul Campionilor",
  "Tenis: Turniej ATP Finals w Turynie",
  "Tenisz: Nitto ATP Finals, férfi világbajnokság",
  "Turneul Campionilor Tenis: ATP Finals Torino"
 ],
 "2026-11-17 12:30": [
  "2026 Nitto ATP Finals: Round Robin, Day 3",
  "ATP FINALS 2026",
  "ATP Finale (Torino): Parovi",
  "ATP Finals",
  "ATP: Nitto ATP Finals (3. den - čtyřhra)",
  "Dubl, dan 3, popodnevna sesija",
  "NITTO ATP FINALS (MATCH 1)",
  "Nitto ATP Finals",
  "Nitto ATP Finals 2026 (T2026): TBC",
  "Nitto ATP Finals: Groepsfase",
  "Nitto ATP Finals: Торино",
  "Tenis ATP Torino 2026",
  "Tenis Atp: Turneul Campionilor",
  "Tenis M - ATP: Torino - Turneul Campionilor",
  "Tenis: Turniej ATP Finals w Turynie",
  "Tenisz: Nitto ATP Finals, férfi világbajnokság",
  "Turneul Campionilor Tenis: ATP Finals Torino",
  "Τένις: Nitto ATP Finals 2026 (Ζ)"
 ],
 "2026-11-17 19:00": [
  "2026 Nitto ATP Finals: Round Robin, Day 3",
  "ATP FINALS 2026",
  "ATP Finale (Torino): Parovi",
  "ATP Finals",
  "ATP: Nitto ATP Finals (3. den - čtyřhra)",
  "Dubl, dan 3, večernja sesija",
  "NITTO ATP FINALS (MATCH 2)",
  "Nitto ATP Finals",
  "Nitto ATP Finals: Groepsfase",
  "Nitto ATP Finals: Торино",
  "Tenis: Turniej ATP Finals w Turynie",
  "Tenisz: Nitto ATP Finals, férfi világbajnokság",
  "Τένις: Nitto ATP Finals 2026 (Ζ)"
 ],
 "2026-11-18 12:30": [
  "2026 Nitto ATP Finals: Round Robin, Day 4",
  "ATP FINALS 2026",
  "ATP Finals",
  "ATP: Nitto ATP Finals (4. den - čtyřhra)",
  "Dubl, dan 4, popodnevna sesija",
  "NITTO ATP FINALS (MATCH 1)",
  "Nitto ATP Finals",
  "Nitto ATP Finals: Groepsfase",
  "Nitto ATP Finals: Торино",
  "Tenis: Turniej ATP Finals w Turynie",
  "Tenisz: Nitto ATP Finals, férfi világbajnokság",
  "Τένις: Nitto ATP Finals 2026 (Ζ)"
 ],
 "2026-11-18 19:00": [
  "2026 Nitto ATP Finals: Round Robin, Day 4",
  "ATP FINALS 2026",
  "ATP Finals",
  "ATP: Nitto ATP Finals (4. den - čtyřhra)",
  "Dubl, dan 4, večernja sesija",
  "NITTO ATP FINALS (MATCH 2)",
  "Nitto ATP Finals",
  "Nitto ATP Finals: Groepsfase",
  "Nitto ATP Finals: Торино",
  "Tenis: Turniej ATP Finals w Turynie",
  "Tenisz: Nitto ATP Finals, férfi világbajnokság",
  "Τένις: Nitto ATP Finals 2026 (Ζ)"
 ],
 "2026-11-19 12:30": [
  "2026 Nitto ATP Finals: Round Robin, Day 5",
  "ATP FINALS 2026",
  "ATP Finals",
  "ATP: Nitto ATP Finals (5. den - čtyřhra)",
  "Dubl, dan 5, popodnevna sesija",
  "NITTO ATP FINALS (MATCH 1)",
  "Nitto ATP Finals",
  "Nitto ATP Finals: Groepsfase",
  "Nitto ATP Finals: Торино",
  "Tenis: Turniej ATP Finals w Turynie",
  "Tenisz: Nitto ATP Finals, férfi világbajnokság",
  "Τένις: Nitto ATP Finals 2026 (Ζ)"
 ],
 "2026-11-19 19:00": [
  "2026 Nitto ATP Finals: Round Robin, Day 5",
  "ATP FINALS 2026",
  "ATP Finals",
  "ATP: Nitto ATP Finals (5. den - čtyřhra)",
  "Dubl, dan 5, večernja sesija",
  "NITTO ATP FINALS (MATCH 2)",
  "Nitto ATP Finals",
  "Nitto ATP Finals: Groepsfase",
  "Nitto ATP Finals: Торино",
  "Tenis: Turniej ATP Finals w Turynie",
  "Tenisz: Nitto ATP Finals, férfi világbajnokság",
  "Τένις: Nitto ATP Finals 2026 (Ζ)"
 ],
 "2026-11-20 12:30": [
  "2026 Nitto ATP Finals: Round Robin, Day 6",
  "ATP FINALS 2026",
  "ATP Finals",
  "ATP: Nitto ATP Finals (6. den - čtyřhra)",
  "Dubl, dan 6, popodnevna sesija",
  "Nitto ATP Finals",
  "Nitto ATP Finals: Groepsfase",
  "Nitto ATP Finals: Торино",
  "Tenis: ATP Finals, Torino",
  "Tenis: Turniej ATP Finals w Turynie",
  "Tenisz: Nitto ATP Finals, férfi világbajnokság",
  "Τένις: Nitto ATP Finals 2026 (Ζ)"
 ],
 "2026-11-20 19:00": [
  "2026 Nitto ATP Finals: Round Robin, Day 6",
  "ATP FINALS 2026",
  "ATP Finals",
  "ATP: Nitto ATP Finals (6. den - čtyřhra)",
  "Dubl, dan 6, večernja sesija",
  "Nitto ATP Finals",
  "Nitto ATP Finals: Groepsfase",
  "Nitto ATP Finals: Торино",
  "Tenis: ATP Finals",
  "Tenis: ATP Finals Torino",
  "Tenis: Turniej ATP Finals w Turynie",
  "Tenisz: Nitto ATP Finals, férfi világbajnokság",
  "Τένις: Nitto ATP Finals 2026 (Ζ)"
 ],
 "2026-11-21 13:00": [
  "2026 Nitto ATP Finals: Semifinals",
  "ATP FINALS 2026 - MEIA-FINAL",
  "ATP Finals: Semifinale",
  "ATP: Nitto ATP Finals (1. semifinále čtyřhry)",
  "Nitto ATP Finals",
  "Nitto ATP Finals: Halve Finale",
  "Nitto ATP Finals: Торино",
  "Polufinale 1 dubl",
  "Tenis: ATP Finals, Torino",
  "Tenis: Turniej ATP Finals w Turynie",
  "Τένις: Nitto ATP Finals 2026 (Ζ)"
 ],
 "2026-11-21 19:00": [
  "2026 Nitto ATP Finals: Semifinals",
  "ATP FINALS 2026 - MEIA-FINAL",
  "ATP Finals: Semifinale",
  "ATP: Nitto ATP Finals (2. semifinále čtyřhry)",
  "Nitto ATP Finals",
  "Nitto ATP Finals: Halve Finale",
  "Nitto ATP Finals: Торино",
  "Polufinale 2 dubl",
  "Tenis: ATP Finals Torino",
  "Tenis: Turniej ATP Finals w Turynie",
  "Τένις: Nitto ATP Finals 2026 (Ζ)"
 ],
 "2026-11-22 16:00": [
  "Tenis: ATP Finals Torino",
  "Tenis: Turniej ATP Finals w Turynie"
 ],
 "2026-11-22 19:00": [
  "ATP FINALS 2026 - FINAL",
  "Tenis: ATP Finals, Torino",
  "Tenis: Turniej ATP Finals w Turynie"
 ]
}


def ждём(начало: str) -> str:
    """Стадия сессии по календарю турнира: 16–20.11 — группы, 21.11 —
    полуфиналы, 22.11 16:00 — финал пар (сайты стадию не называют), 19:00 —
    финал."""
    if начало.startswith("2026-11-21"):
        return "Semifinals"
    return "Final" if начало == "2026-11-22 19:00" else ""


def проверка(имя: str, вышло, ждали=True) -> None:
    global зелёных, красных
    if вышло == ждали:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждали!r}")


print("1–2. Витрина: заливка и показ настоящих заголовков (`store.save_games` → `store.schedule`)")
db.init_db()
conn = db.connect()
все = sorted({t for titles in ЗАГОЛОВКИ.values() for t in titles})
for n, _title in enumerate(все, 1):
    conn.execute("INSERT INTO sources (id, domain, name, base_url, country, enabled) VALUES (?, ?, ?, ?, 'XX', 1)",
                 (n, f"sayt-{n}.test", f"Сайт {n}", f"https://sayt-{n}.test/"))
conn.commit()
номер = {title: n for n, title in enumerate(все, 1)}
игры = [{"sport": "T", "league": "", "home": ИМЯ, "away": broadcast.SESSION,
         "start_kyiv": начало.replace(" ", "T"), "start_utc": "",
         "entries": [{"source": f"sayt-{номер[t]}.test", "channel": f"Канал {номер[t]}", "url": "", "raw_title": t}
                     for t in titles]}
        for начало, titles in ЗАГОЛОВКИ.items()]
store.save_games(conn, игры, now=ЧАСЫ)
показано = {f"{g['date']} {g['time']}": g for g in store.schedule(conn, now=ЧАСЫ)}
проверка("на витрине все 13 сессий, каждая — строкой турнира", (len(показано), all(g["title"] for g in показано.values())),
         (13, True))
for начало in ЗАГОЛОВКИ:
    g = показано.get(начало) or {}
    проверка(f"сессия {начало[5:]}: подпись «{ИМЯ}»" + (f" — {ждём(начало)}" if ждём(начало) else ", стадии нет"),
             (g.get("home"), g.get("away")), (ИМЯ, ждём(начало)))
conn.close()

print("3. Каждый заголовок отдельно (`broadcast.show_stage`): стадия — только та, что у его сессии")
знаем = broadcast.tournaments(None)
чужие = sorted({f"{начало[5:]} «{t}» → {broadcast.show_stage(ИМЯ, t, знаем)}"
                for начало, titles in ЗАГОЛОВКИ.items() for t in titles
                if broadcast.show_stage(ИМЯ, t, знаем) not in ("", ждём(начало))})
проверка("ни один из 47 заголовков не даёт стадию, которой у его сессии нет", чужие, [])
проверка("виновник 16.11 назван по имени: турнир в заголовке дважды, на двух языках, — не финал",
         broadcast.show_stage(ИМЯ, "Turneul Campionilor Tenis: ATP Finals Torino", знаем), "")

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

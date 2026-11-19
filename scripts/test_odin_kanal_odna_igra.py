# -*- coding: utf-8 -*-
"""Книга 167 (19.11.2026): один канал в одну минуту показывает одну игру.

yallakora.com пишет команды по-арабски, livesoccertv — по-английски; буквами
имена не сравнить, арабского эталона нет. Без правила на витрине две игры на
одном канале в одну минуту (`channel_grid.fold_same_channel`).

Строки — настоящие, со страниц пробы GitHub #508 и сбора #507 (19.11.2026).

Запуск: python scripts/test_odin_kanal_odna_igra.py — в сеть не ходит.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import channel_grid as G, merge  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


ON1, MAX, PLUS = ("AR ON Sport 1", "EG"), ("ar ON Sport Max", "EG"), ("ar ON Sport Plus", "EG")
#: словарь каналов, как его отдаёт сервер после `add_on_sport_stc.py`
CMAP = {("livesoccertv.com", "on sport 1"): ON1, ("yallakora.com", "on sport"): ON1,
        ("livesoccertv.com", "on sport max"): MAX, ("yallakora.com", "on sport max"): MAX,
        ("livesoccertv.com", "on sport plus"): PLUS, ("yallakora.com", "on sport plus"): PLUS}


def строка(сайт, канал, дом, гости, время, вид="F"):
    return merge.Entry(source=сайт, channel=канал, home=дом, away=гости,
                       start=datetime.strptime("2026-11-19 " + время, "%Y-%m-%d %H:%M"), sport=вид)


def игры(*строки):
    return merge.merge(list(строки))


def вид(games):
    return sorted((g.start.strftime("%H:%M"), g.home, g.away, sorted(f"{e.source}/{e.channel}" for e in g.entries))
                  for g in games)


LSTV, YK = "livesoccertv.com", "yallakora.com"

print("Письменность имени")
проверка("арабское и ивритское имя сверка не читает",
         (G.unreadable("بترول أسيوط"), G.unreadable("מכבי תל אביב")), (True, True))
проверка("латиницу, кириллицу и греческий читает",
         (G.unreadable("Al Masry"), G.unreadable("Кремонезе"), G.unreadable("Ολυμπιακός")), (False, False, False))
проверка("пустое имя и цифры — не «непрочитанное»", (G.unreadable(""), G.unreadable("1899")), (False, False))

print("Кубок Египта 19.11: yallakora по-арабски, livesoccertv по-английски")
день = игры(
    строка(LSTV, "ON Sport 1", "Al Masry", "Asyut Petrol", "17:00"),
    строка(LSTV, "ON Sport Max", "Al Mokawloon", "El Qanah", "17:00"),
    строка(LSTV, "ON Sport Max", "ZED", "Smouha", "20:00"),
    строка(YK, "ON Sport", "المصري", "بترول أسيوط", "17:00"),
    строка(YK, "ON Sport Max", "المقاولون العرب", "القناة", "17:00"),
    строка(YK, "ON Sport Max", "زد", "سموحة", "20:00"),
    строка(YK, "ON Sport Plus", "الأهلي", "الزمالك", "18:30", "H"),
)
проверка("до правила — семь игр: арабские записи лежат отдельно", len(день), 7)
после, влитые = G.fold_same_channel(день, CMAP)
проверка("после — четыре: три арабские влились в игры того же канала и минуты, имена остались английские",
         вид(после),
         [("17:00", "Al Masry", "Asyut Petrol", ["livesoccertv.com/ON Sport 1", "yallakora.com/ON Sport"]),
          ("17:00", "Al Mokawloon", "El Qanah", ["livesoccertv.com/ON Sport Max", "yallakora.com/ON Sport Max"]),
          ("18:30", "الأهلي", "الزمالك", ["yallakora.com/ON Sport Plus"]),
          ("20:00", "ZED", "Smouha", ["livesoccertv.com/ON Sport Max", "yallakora.com/ON Sport Max"])])
проверка("в журнал идёт, что во что влито",
         sorted((имена, g.home) for имена, g in влитые),
         [("المصري — بترول أسيوط", "Al Masry"), ("المقاولون العرب — القناة", "Al Mokawloon"), ("زد — سموحة", "ZED")])
проверка("гандбол, которого у другого сайта нет, остаётся своей игрой",
         [g.home for g in после if g.sport == "H"], ["الأهلي"])

print("Когда правило молчит")


def после_правила(*строки, cmap=CMAP):
    return вид(G.fold_same_channel(игры(*строки), cmap)[0])


пара = (строка(LSTV, "ON Sport 1", "Al Masry", "Asyut Petrol", "17:00"),
        строка(YK, "ON Sport", "المصري", "بترول أسيوط", "17:00"))
проверка("канал словарю не знаком — не судим", len(после_правила(*пара, cmap={})), 2)
проверка("начала расходятся больше чем на 15 минут — разные показы",
         len(после_правила(пара[0], строка(YK, "ON Sport", "المصري", "بترول أسيوط", "17:20"))), 2)
проверка("…а на 10 минут — один показ",
         len(после_правила(пара[0], строка(YK, "ON Sport", "المصري", "بترول أسيوط", "17:10"))), 1)
проверка("вид спорта спорит — не вливаем",
         len(после_правила(пара[0], строка(YK, "ON Sport", "المصري", "بترول أسيوط", "17:00", "H"))), 2)
проверка("другой канал в ту же минуту — не пара",
         len(после_правила(пара[0], строка(YK, "ON Sport Max", "المصري", "بترول أسيوط", "17:00"))), 2)
проверка("обе строки одного сайта (сайт сам пишет две игры на канале) — не вливаем",
         len(после_правила(строка(YK, "ON Sport", "Al Masry", "Asyut Petrol", "17:00"), пара[1])), 2)
проверка("две прочитанные игры на том же канале в ту же минуту — пара не одна, не гадаем",
         len(после_правила(пара[0], строка("filgoal.com", "ON Sport", "Pyramids", "Zamalek", "17:05"), пара[1],
                           cmap={**CMAP, ("filgoal.com", "on sport"): ON1})), 3)
проверка("обе игры прочитаны, имена разные — правило не для них (спор сайтов не решаем)",
         len(после_правила(пара[0], строка(YK, "ON Sport", "Pyramids", "Zamalek", "17:00"))), 2)
проверка("одна сторона по-арабски, другая латиницей — имена сверка сравнила сама, правило не трогает",
         len(после_правила(пара[0], строка(YK, "ON Sport", "المصري", "Zamalek", "17:00"))), 2)

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

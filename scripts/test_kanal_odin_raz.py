# -*- coding: utf-8 -*-
r"""Книга 152 (16.11.2026): канал одного сайта стоит у игры ОДИН раз.

Находка: Digi Sport 1 у digisport.ro стоял у игры дважды, второй раз со
сдвигом +60 минут. Причина — на странице: сайт пишет матч двумя строками,
первый тайм `14:30 LIVE Liga a 2-a: Bihor Oradea-Gloria Bistrita`, вставка
`15:15 Stirile Digi Sport`, второй тайм `15:30 LIVE` с тем же заголовком.
Обе строки помечены эфиром и обе в окне склейки.

Замер по витрине сбора #491 (игры с парой): лишних строк «канал сайта
дважды у одной игры» — 31: digisport.ro 12 (сдвиг 60–65 мин), tvmatsit.com 8
и sporttv.pt 3 (блоки по два часа), dr.dk 2 (55 и 60 мин), novasports.gr 2,
sport5.co.il 2 (в одну минуту), teleman.pl 1, tv24.co.uk 1; в сборе #475
ещё rtcg.me (65 мин).

Правило общее (`parse_live.one_row_per_channel`, четыре правила в описании).
Игры собраны здесь. В сеть не ходит, база не нужна, от даты не зависит.
Запуск: python scripts/test_kanal_odin_raz.py
"""
from __future__ import annotations

import inspect
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
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.gettempdir()) / "kanal-odin-raz-none.db"))

import parse_live  # noqa: E402
from app import broadcast  # noqa: E402
from app.merge import Entry, Game  # noqa: E402

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


def в(время: str) -> datetime:
    """`"14:30"` → 20.11.2026 14:30 по Киеву."""
    return datetime(2026, 11, 20, int(время[:2]), int(время[3:]), tzinfo=KYIV)


def игра(home: str, away: str, *строки: tuple[str, str, str]) -> Game:
    """Игра из строк (сайт, канал, время начала показа)."""
    return Game(entries=[Entry(source=s, channel=c, home=home, away=away, start=в(t), sport="F")
                         for s, c, t in строки])


def каналы(game: Game) -> list[str]:
    return sorted(f"{e.channel}/{e.source} {e.start.strftime('%H:%M')}" for e in game.entries)


print("1. Случай digisport.ro: первый тайм, вставка новостей, второй тайм")
bihor = игра("Bihor Oradea", "Gloria Bistrita",
             ("digisport.ro", "Digi Sport 1", "14:30"), ("digisport.ro", "Digi Sport 1", "15:30"))
игры, снято = parse_live.one_row_per_channel([bihor])
проверка("Digi Sport 1 остался у игры один раз — строкой первого тайма 14:30",
         каналы(игры[0]), ["Digi Sport 1/digisport.ro 14:30"])
проверка("снятая строка ушла в журнал: (игра, снятая 15:30, оставленная 14:30)",
         [(g is bihor, e.start.strftime("%H:%M"), keep.start.strftime("%H:%M")) for g, e, keep in снято],
         [(True, "15:30", "14:30")])
проверка("время начала игры не изменилось", игры[0].start, в("14:30"))

print("2. Правило 1: судим по одному сайту и одному каналу")
farul = игра("Farul", "U Cluj",
             ("digisport.ro", "Digi Sport 1", "20:30"), ("digisport.ro", "Digi Sport 1", "21:30"),
             ("programetv.ro", "Digi Sport 1", "20:30"), ("www.digisport.ro", "Digi Sport 1", "21:35"),
             ("digisport.ro", "Digi Sport 2", "21:30"), ("tvarenasport.hr", "Arena Sport 6", "20:30"))
игры, снято = parse_live.one_row_per_channel([farul])
проверка("тот же канал у другого сайта и другой канал того же сайта остались; `www.` у сайта не в счёт",
         каналы(игры[0]),
         ["Arena Sport 6/tvarenasport.hr 20:30", "Digi Sport 1/digisport.ro 20:30",
          "Digi Sport 1/programetv.ro 20:30", "Digi Sport 2/digisport.ro 21:30"])
проверка("снято две строки Digi Sport 1 сайта digisport.ro", len(снято), 2)

print("3. Правило 2: трансляция турнира без пары — сессии не трогаем")
турнир = игра("ATP Finals Turin", broadcast.SESSION,
              ("maxsport.live", "MAX Sport 1", "12:30"), ("maxsport.live", "MAX Sport 1", "15:00"))
игры, снято = parse_live.one_row_per_channel([турнир])
проверка("две сессии турнира на одном канале остались обе",
         (каналы(игры[0]), снято),
         (["MAX Sport 1/maxsport.live 12:30", "MAX Sport 1/maxsport.live 15:00"], []))

print("4. Правило 3: остаётся самая ранняя строка канала — начало игры не меняется")
три = игра("Άρης", "Λε Μαν",
           ("novasports.gr", "Novasports Prime", "20:00"), ("novasports.gr", "Novasports Prime", "22:00"),
           ("novasports.gr", "Novasports Prime", "19:30"), ("sport1.maariv.co.il", "Sport1 1", "19:55"))
начало_было = три.start
игры, снято = parse_live.one_row_per_channel([три])
проверка("из трёх строк канала (в любом порядке) осталась самая ранняя, 19:30",
         каналы(игры[0]), ["Novasports Prime/novasports.gr 19:30", "Sport1 1/sport1.maariv.co.il 19:55"])
проверка("время начала игры то же, что до правила", (игры[0].start, начало_было), (в("19:30"), в("19:30")))
в_одну_минуту = игра("Valencia", "Virtus",
                     ("sport5.co.il", "ספורט 5+", "21:55"), ("sport5.co.il", "ספורט 5+", "21:55"))
первая = в_одну_минуту.entries[0]
игры, снято = parse_live.one_row_per_channel([в_одну_минуту])
проверка("две строки в одну минуту — остаётся первая по порядку страницы",
         (len(игры[0].entries), игры[0].entries[0] is первая), (1, True))

print("5. Правило 4: игра и канал остаются; игры без повторов канала не меняются")
одна = игра("Botosani", "Voluntari", ("digisport.ro", "Digi Sport 1", "17:30"),
            ("tvarenasport.ba", "Arena Premium 1", "17:30"))
двойная = игра("Paris FC W", "HB Koge W", ("dr.dk", "DR2", "19:30"), ("dr.dk", "DR2", "20:30"))
игры, снято = parse_live.one_row_per_channel([одна, двойная])
проверка("игр осталось столько же, порядок прежний", [g is x for g, x in zip(игры, [одна, двойная])],
         [True, True])
проверка("игра без повторов канала не тронута",
         каналы(одна), ["Arena Premium 1/tvarenasport.ba 17:30", "Digi Sport 1/digisport.ro 17:30"])
проверка("у игры с двумя таймами канал остался — один раз", каналы(двойная), ["DR2/dr.dk 19:30"])
проверка("пустой список игр — пустой итог", parse_live.one_row_per_channel([]), ([], []))

print("6. Правило включено в разбор: после мультикаста, со своим именем в журнале снятого")
main = inspect.getsource(parse_live.main)
проверка("разбор зовёт `one_row_per_channel` после `drop_multicast` и пишет снятое в журнал",
         [0 < main.find("drop_multicast(games)") < main.find("one_row_per_channel(games)"),
          "СНЯТО_ВТОРАЯ_ЧАСТЬ" in main], [True, True])
проверка("имя фильтра не начинается словами фильтров, по которым заливка гасит отметки "
         "(«мультикаст», «повтор по flashscore»)",
         parse_live.СНЯТО_ВТОРАЯ_ЧАСТЬ.startswith(("мультикаст", "повтор по flashscore")), False)

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

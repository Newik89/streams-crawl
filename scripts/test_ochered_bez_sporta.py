# -*- coding: utf-8 -*-
r"""Очередь «Вид спорта» вместо молчаливого снятия (книга 081, 25.10.2026):
строка Al Kass «Gulf U-17 Cup: Egypt - Kuwait» на каналах One, Four, Eight
(20.10) не имела вида спорта (турнира нет в словаре, пары нет во flashscore)
и выбрасывалась молча — сито очереди пускало только каналы со словом
«sport» и израильские строки. Правило 3 `parse_live.worth_asking` (25.10):
сайт сам назвал турнир (`league_raw`) и пара прочитана — спросить человека.

Что сторожится (`parse_live.worth_asking`, правила списком):

1. канал без слова «sport», турнир назван, пара есть — в очередь;
2. тот же канал, турнира нет — снять молча, как раньше (сито от передач
   BBC, скачек и биржевых сводок, 04.09);
3. турнир назван, а второй команды нет — не пара, снять;
4. канал со словом «sport» — в очередь, как и раньше (правило 1);
5. израильская строка — в очередь, как и раньше (правило 2).

В сеть не ходит, база не нужна:

    python scripts/test_ochered_bez_sporta.py

Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.gettempdir()) / "ochered-none.db"))

import parse_live  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✗ {имя}: вышло {вышло!r}, ждали {ждём!r}")


def строка(канал: str, турнир: str = "", дом: str = "Egypt", гость: str = "Kuwait"):
    """Нерешённая строка разбора: вид спорта не дан (`ok` = False)."""
    return SimpleNamespace(
        ok=False, home=дом, away=гость, league="",
        program=SimpleNamespace(channel_raw=канал, league_raw=турнир))


СПОРТИВНЫЕ = {"alkass.net"}
спросить = lambda r, sporty=СПОРТИВНЫЕ: parse_live.worth_asking("alkass.net", r, sporty)  # noqa: E731

print("1. Турнир назван спортивным сайтом — спросить человека")
проверка("«Gulf U-17 Cup: Egypt - Kuwait» на Al Kass One → в очередь",
         спросить(строка("Al Kass One", "Gulf U-17 Cup")), True)
проверка("то же на Al Kass Eight → в очередь",
         спросить(строка("Al Kass Eight", "Gulf U-17 Cup")), True)
проверка("тот же турнир, но сайт не спортивный вещатель (общий телегид) → молча",
         спросить(строка("Al Kass One", "Gulf U-17 Cup"), set()), False)

print("1а. Спортивный вещатель — по доле строк с найденным видом спорта")


def сайт(домен: str, всего: int, решено: int) -> list:
    return [(домен, SimpleNamespace(ok=i < решено)) for i in range(всего)]


проверка("Al Kass: 13 строк с парой, 12 с видом спорта → спортивный",
         parse_live.sporty_sites(сайт("alkass.net", 13, 12)), {"alkass.net"})
проверка("raiplay: 37 строк, вид спорта у 5 → общий телегид, не спрашиваем",
         parse_live.sporty_sites(сайт("raiplay.it", 37, 5)), set())
проверка("мало строк (6 из 6) — доля ничего не значит, не спортивный",
         parse_live.sporty_sites(сайт("tv.kz", 6, 6)), set())
проверка("домен с www. считается тем же сайтом",
         parse_live.sporty_sites(сайт("www.alkass.net", 10, 9)), {"alkass.net"})

print("2. Без турнира у канала без слова «sport» — снять молча, как раньше")
проверка("Al Kass One, турнира нет → молча",
         спросить(строка("Al Kass One")), False)
проверка("BBC One, турнира нет → молча",
         спросить(строка("BBC One", дом="Antiques", гость="Road Trip")), False)
проверка("турнир из одних пробелов → как без турнира",
         спросить(строка("Al Kass One", "   ")), False)

print("3. Турнир назван, а пары нет — не спорт-строка")
проверка("второй команды нет → молча",
         спросить(строка("Al Kass One", "Gulf U-17 Cup", гость="")), False)

print("4. Прежние правила сита живы")
проверка("канал со словом «sport» → в очередь без турнира",
         спросить(строка("Sport TV 1")), True)
проверка("«Спорт 1» кириллицей → в очередь",
         спросить(строка("Спорт 1")), True)
проверка("израильская строка (Маккаби Хайфа — Хапоэль Беэр-Шева) → в очередь",
         спросить(строка("ערוץ 11", дом="מכבי חיפה", гость="הפועל באר שבע")), True)

print(f"\nзелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

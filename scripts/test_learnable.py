# -*- coding: utf-8 -*-
"""Что словарь имеет право выучить навсегда (`canon._learnable`).

08.10: в словаре нашлись 125 написаний вида «Лига: Хозяева - Гости» и 636
вида «Лига: Клуб», записанных как имена команд, — учёба брала строку сайта
целиком. Правило: в написании должен быть один клуб, без лиги впереди.
08.10 вдогонку: голландская пометка женской сборной « V » («Marokko V WO»)
читалась как «vs», и чистка `dict_clean.py --only матчи` снимала честные
алиасы эталона — одиночная «v» теперь «vs» только перед именем соперника.

Запуск: venv\\Scripts\\python.exe scripts/test_learnable.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import canon  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("Учёба словаря: один клуб, без лиги впереди")
    у = canon._learnable
    проверка("обычное написание — учим", у("Le Mans FC", "Le Mans"), True)
    проверка("кириллица — учим", у("Барселона", "Barcelona"), True)
    проверка("весь матч с лигой — не учим",
             у("Eurocup: Tortona - Le Mans", "Le Mans"), False)
    проверка("весь матч через «vs» — не учим",
             у("EVERTON vs WOLVERHAMPTON", "Everton"), False)
    проверка("«Лига: клуб» — не учим", у("Premier League: Hull City", "Hull"),
             False)
    проверка("двоеточие есть и в каноне — учим",
             у("Team: X", "Team: X"), True)
    проверка("дефис внутри имени клуба — учим",
             у("Z. Moravce-Vrable", "Z. Moravce-Vrable"), True)
    проверка("пол обязан совпасть (как и раньше)",
             у("Germany", "Germany W"), False)
    проверка("заглушка — не учим", у("TBC", "Real Madrid"), False)
    print("Голландская « V » женской сборной — не «vs» (08.10)")
    о = canon._one_team
    проверка("«Marokko V WO» — один клуб, не матч",
             о("Marokko V WO", "Morocco W WO"), True)
    проверка("«Kameroen V WO» — тоже", о("Kameroen V WO", "Cameroon W WO"),
             True)
    проверка("«Marokko V» без хвоста — один клуб", о("Marokko V", "Morocco W"),
             True)
    проверка("« V » между двумя именами — весь матч",
             о("EVERTON V WOLVERHAMPTON", "Everton"), False)
    проверка("«vs» между именами — по-прежнему матч",
             о("Ajax vs PSV", "Ajax"), False)
    проверка("соперник с короткого слова («St Mirren») — матч",
             о("Rangers v St Mirren", "Rangers"), False)
    проверка("«Al Hilal v Al Nassr» — матч", о("Al Hilal v Al Nassr", "Al Hilal"),
             False)
    проверка("два пробела после «v» — матч", о("Lech v  Wisla", "Lech"), False)
    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, "
          f"красных: {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

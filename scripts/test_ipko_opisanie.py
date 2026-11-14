"""Книга 121 (14.11): ipko.tv, каналы SuperSport — матч по описанию-шаблону.

С 13.11 у каналов SuperSport заголовок матча — «Spanje-Angli» (дефис без
пробелов), описание — шаблон «UEFA Nations League - Shikoni ndeshjen e
futbollit në të cilën Spanja përballon Angli.». Разбор брал «пару» из
описания по первому тире, игра не узнавалась, каналы SuperSport пропали с
витрины (жалоба владельца 14.11: «поменялись каналы местами SuperSport 1–5»).

Запуск: python scripts/test_ipko_opisanie.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.parsers import ipko_tv  # noqa: E402

зелёных = красных = 0
ШАБЛОН = "UEFA Nations League - Shikoni ndeshjen e futbollit në të cilën {a} përballon {b}."


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def строка(title: str, summary: str = "", channel: str = "supersport-1", genres=("futbolli",)):
    sample = json.dumps({"shows": [{"title": title, "show_start": 1794771900,
                                    "show_end": 1794779100, "genres": list(genres),
                                    "categories": "Sport", "summary": summary}]})
    programs = ipko_tv.parse(
        sample, url=f"https://stargate.ipko.tv/api/titan.tv.WebEpg/GetWebEpgData?channel_id={channel}")
    assert len(programs) == 1, programs
    return programs[0]


print("Правила 1–4: матч по описанию-шаблону")
p = строка("Spanje-Angli", ШАБЛОН.format(a="Spanja", b="Angli"))
проверка("живой случай: «Spanje-Angli» — пара из заголовка, а не обрывок описания",
         p.match_raw, "Spanje - Angli")
проверка("…лига — из описания, до тире", p.league_raw, "UEFA Nations League")
проверка("…канал и пометка эфира на месте", (p.channel_raw, bool(p.live_raw)),
         ("SuperSport 1", True))
p = строка("France-Turqi", ШАБЛОН.format(a="Francë", b="Turqia"), "supersport-4")
проверка("второй живой случай: «France-Turqi»", (p.match_raw, p.channel_raw),
         ("France - Turqi", "SuperSport 4"))
p = строка("Ndeshja e javës", ШАБЛОН.format(a="Spanja", b="Angli"))
проверка("в заголовке пары нет — имена берутся из описания", p.match_raw, "Spanja - Angli")
p = строка("Bodo-Glimt-Lille", ШАБЛОН.format(a="Bodo-Glimt", b="Lille"))
проверка("в заголовке два дефиса — не гадаем, имена из описания", p.match_raw, "Bodo-Glimt - Lille")

print("Прежнее поведение не тронуто")
p = строка("TIKI-TAKA", "Emision sportiv me të ftuar në studio.")
проверка("«TIKI-TAKA» без шаблона в описании — не матч (ГРАБЛИ)", p.match_raw.strip(), "")
p = строка("Futboll: Liga e Kombeve Spanje - Angli", "Ndeshje nga Liga e Kombeve. Sezoni 26-27.",
           "sport-1")
проверка("пара в заголовке через « - » — как раньше, описание не читается",
         (p.match_raw, p.league_raw), ("Spanje - Angli", "futbolli"))
p = строка("Sport News", "Lajmet më të fundit nga vendi dhe bota.", genres=("sporte të tjera",))
проверка("передача без пары — не матч", p.match_raw.strip(), "")
p = строка("Magazina", "Prishtina - Drita, përmbledhje e ndeshjes")
проверка("описание не по шаблону — прежний путь: пара из описания по тире",
         p.match_raw, "Prishtina - Drita")
проверка("шаблон без обеих команд — пусто",
         ipko_tv._match_by_summary("X", "Liga - Shikoni ndeshjen në të cilën  përballon ."), ("", ""))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

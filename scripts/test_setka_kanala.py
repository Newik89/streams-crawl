# -*- coding: utf-8 -*-
r"""Полная программа канала главнее чужой строки про этот канал (книга 085,
слово владельца 26.10.2026, #7042 PSG — Лион: ipko.tv поставил матч на
SuperSport 2, а агрегатор livesoccertv держал SuperSport 3).

Что сторожится (`app/channel_grid.py`, правила по номерам):

1. канал узнаётся по словарю каналов: «SuperSport 3» у ipko, «SS3» у
   tring.al и «SuperSport 3 Digitalb» у livesoccertv — один канал;
2. сплошная сетка: ≥3 передач за 6 ч до начала, разрывы ≤3 ч; страница
   агрегатора (только матчи) — не сетка;
3. строка агрегатора про канал K снимается, если сайт с полной сеткой K
   показывает этот матч на другом канале, а в его сетке K в это время другое;
   не снимается: сайт-сетка показывает матч и на K; в его сетке рядом есть
   передача с именем команды; сам агрегатор — тоже сплошная сетка; сайт-сетка
   этот матч вообще не показывает; канал не узнан словарём;
4. `same_match`: игры одного матча эталона — одна игра для правила 3.

В сеть не ходит, база не нужна:

    python scripts/test_setka_kanala.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.gettempdir()) / "setka-none.db"))

from app import channel_grid as cg, merge  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✗ {имя}: вышло {вышло!r}, ждали {ждём!r}")


def t(hhmm: str, day: int = 26) -> datetime:
    return datetime(2026, 10, day, int(hhmm[:2]), int(hhmm[3:]), tzinfo=KYIV)


def показ(канал: str, hhmm: str, заголовок: str):
    return SimpleNamespace(channel_raw=канал, start=t(hhmm), title=заголовок)


def строка(сайт: str, канал: str, hhmm: str, дом="PSG", гость="Lyon") -> merge.Entry:
    return merge.Entry(source=сайт, channel=канал, home=дом, away=гость,
                       start=t(hhmm).replace(tzinfo=None), sport="F")


def игра(*строки) -> merge.Game:
    return merge.Game(entries=list(строки))


CMAP = cg.load_map()
#: полная сетка ipko: SuperSport 2 — матч, SuperSport 3 — «Premier League Channel»
IPKO = ("ipko.tv", [
    показ("SuperSport 2", "16:00", "Football Nation"), показ("SuperSport 2", "18:00", "Rizespor-Trabzonspor"),
    показ("SuperSport 2", "20:00", "Wimbledon 2026"), показ("SuperSport 2", "21:00", "Football Nation"),
    показ("SuperSport 2", "21:30", "PSG-Lyon"),
    показ("SuperSport 3", "16:00", "Besiktas-Basaksehir"), показ("SuperSport 3", "18:00", "Premier League Channel"),
    показ("SuperSport 3", "20:00", "Premier League Channel"), показ("SuperSport 3", "21:00", "Premier League Channel"),
])
#: агрегатор: только матчи, через часы
LSTV = ("livesoccertv.com", [
    показ("SuperSport 2 Digitalb", "18:00", "Rizespor vs Trabzonspor"),
    показ("SuperSport 2 Digitalb", "21:30", "PSG vs Olympique Lyonnais"),
    показ("SuperSport 3 Digitalb", "18:00", "Beşiktaş vs İstanbul Başakşehir"),
    показ("SuperSport 3 Digitalb", "21:30", "PSG vs Olympique Lyonnais"),
])


def прогон(игры, страницы=(IPKO, LSTV), эталон=None):
    оставлено, снято = cg.drop_contradicted(игры, cg.Grids(list(страницы), CMAP), эталон)
    return sorted((e.source, e.channel) for g in оставлено for e in g.entries), \
        sorted((e.source, e.channel, b) for _, e, b in снято)


print("1. Канал узнаётся по словарю каналов")
проверка("ipko «SuperSport 3» = livesoccertv «SuperSport 3 Digitalb»",
         cg.channel_key(CMAP, "ipko.tv", "SuperSport 3"),
         cg.channel_key(CMAP, "livesoccertv.com", "SuperSport 3 Digitalb"))
проверка("tring.al «SS3» — тот же канал",
         cg.channel_key(CMAP, "tring.al", "SS3"), cg.channel_key(CMAP, "ipko.tv", "SuperSport 3"))
проверка("незнакомое написание — None", cg.channel_key(CMAP, "ipko.tv", "Нет такого"), None)

print("2. Сплошная сетка")
G = cg.Grids([IPKO, LSTV], CMAP)
K3 = cg.channel_key(CMAP, "ipko.tv", "SuperSport 3")
проверка("ipko SuperSport 3 в 21:30 — сплошная", G.full("ipko.tv", K3, t("21:30").timestamp()), True)
проверка("livesoccertv SuperSport 3 в 21:30 — не сетка (два матча за 6 ч)",
         G.full("livesoccertv.com", K3, t("21:30").timestamp()), False)
проверка("ipko SuperSport 3 в 03:00 следующего дня — последняя передача давно, не сетка",
         G.full("ipko.tv", K3, t("03:00", 27).timestamp()), False)

print("3. Строка агрегатора против полной сетки")
psg = игра(строка("ipko.tv", "SuperSport 2", "21:30"),
           строка("livesoccertv.com", "SuperSport 2 Digitalb", "21:30"),
           строка("livesoccertv.com", "SuperSport 3 Digitalb", "21:30"))
оставлено, снято = прогон([psg])
проверка("#7042: SuperSport 3 у livesoccertv снят — у ipko там «Premier League Channel»",
         снято, [("livesoccertv.com", "SuperSport 3 Digitalb", "ipko.tv")])
проверка("…SuperSport 2 у обоих остался",
         оставлено, [("ipko.tv", "SuperSport 2"), ("livesoccertv.com", "SuperSport 2 Digitalb")])
оставлено, снято = прогон([игра(строка("livesoccertv.com", "SuperSport 3 Digitalb", "21:30"))])
проверка("ipko этот матч не показывает вовсе — агрегатор не трогаем", снято, [])
ipko_both = ("ipko.tv", IPKO[1] + [показ("SuperSport 3", "21:30", "PSG-Lyon")])
оставлено, снято = прогон([игра(строка("ipko.tv", "SuperSport 2", "21:30"),
                                строка("ipko.tv", "SuperSport 3", "21:30"),
                                строка("livesoccertv.com", "SuperSport 3 Digitalb", "21:30"))],
                          (ipko_both, LSTV))
проверка("ipko показывает матч и на SuperSport 3 — агрегатор согласен, не снимаем", снято, [])
студия = ("ipko.tv", IPKO[1] + [показ("SuperSport 3", "21:15", "Paris Saint-Germain - studio")])
оставлено, снято = прогон([игра(строка("ipko.tv", "SuperSport 2", "21:30"),
                                строка("livesoccertv.com", "SuperSport 3 Digitalb", "21:30",
                                       дом="Paris Saint-Germain"))], (студия, LSTV))
проверка("в сетке K рядом передача с именем команды — не снимаем", снято, [])
сетка_агр = ("livesoccertv.com", LSTV[1] + [показ("SuperSport 3 Digitalb", h, "x")
                                            for h in ("16:30", "17:00", "19:00", "20:30")])
оставлено, снято = прогон([игра(строка("ipko.tv", "SuperSport 2", "21:30"),
                                строка("livesoccertv.com", "SuperSport 3 Digitalb", "21:30"))],
                          (IPKO, сетка_агр))
проверка("у второго сайта тоже сплошная сетка — две сетки спорят, не судим", снято, [])
оставлено, снято = прогон([игра(строка("ipko.tv", "SuperSport 2", "21:30"),
                                строка("livesoccertv.com", "Неизвестный канал", "21:30"))])
проверка("канал не узнан словарём — не судим", снято, [])

print("3а. Заглушка — не сетка (сбор 26.10 20:08: ipko расписал каналы Tring Sport пустышками)")
заглушка = ("ipko.tv", [показ("Tring Sport 1", h, "Unknown show")
                        for h in ("16:00", "17:00", "18:00", "19:00", "20:00", "21:00")]
            + [показ("Tring Sport 2", "19:25", "Venezia - Inter")])
tring = игра(строка("ipko.tv", "Tring Sport 2", "19:25", дом="Venezia", гость="Inter"),
             строка("tring.al", "Tring Sport 1", "19:30", дом="Venezia", гость="INTER DE MILÃO"))
оставлено, снято = прогон([tring], (заглушка,))
проверка("«Unknown show» каждый час — не сетка, строку tring.al не снимаем", снято, [])
имя_канала = ("ipko.tv", [показ("Tring Sport 3", h, "Tring Sport 3 HD")
                          for h in ("14:00", "16:00", "18:00", "20:00")]
              + [показ("Tring Sport 2", "21:00", "Portland - Utah")])
nba = игра(строка("ipko.tv", "Tring Sport 2", "21:00", дом="Portland", гость="Utah"),
           строка("tring.al", "Tring Sport 3", "21:00", дом="Portland Trail Blazers", гость="Utah Jazz"))
оставлено, снято = прогон([nba], (имя_канала,))
проверка("в сетке только имя канала («Tring Sport 3 HD») — не сетка", снято, [])
проверка("placeholder: «Programet e TS4 HD» — заглушка",
         cg.placeholder("Programet e TS4 HD", ("Tring Sport 4", "AL")), True)
проверка("placeholder: «Premier League Channel» — настоящая передача",
         cg.placeholder("Premier League Channel", ("SuperSport 3", "AL")), False)

print("4. Один матч эталона — одна игра, даже если строки не склеились")
ipko_игра = игра(строка("ipko.tv", "SuperSport 2", "21:18", дом="PARIS SAINT-GERMAIN", гость="Olympique Lyon"))
lstv_игра = игра(строка("livesoccertv.com", "SuperSport 2 Digitalb", "21:30", гость="Olympique Lyonnais"),
                 строка("livesoccertv.com", "SuperSport 3 Digitalb", "21:30", гость="Olympique Lyonnais"))
эталон = [{"sport": "F", "home": "PSG", "away": "Lyon", "league": "FRANCE: Ligue 1",
           "fs_id": "zyZq2xcL", "start_kyiv": "2026-10-26T21:30",
           "names": {"fr": ["Paris SG", "Lyon"]}}]
оставлено, снято = прогон([ipko_игра, lstv_игра], эталон=эталон)
проверка("с эталоном: SuperSport 3 у livesoccertv снят", снято,
         [("livesoccertv.com", "SuperSport 3 Digitalb", "ipko.tv")])
оставлено, снято = прогон([игра(*ipko_игра.entries), игра(*[строка("livesoccertv.com", "SuperSport 3 Digitalb", "21:30", гость="Olympique Lyonnais")])])
проверка("без эталона две разные игры — не судим", снято, [])

print(f"\nзелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

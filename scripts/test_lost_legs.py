# -*- coding: utf-8 -*-
r"""Пропавшие ответные матчи (вопросы владельца 13.10.2026): женский отбор
ЧМ Польша — Бельгия на TVP Sport (teleman) и Италия — Беларусь на Rai 2
(raiplay) не попали на витрину. По проверке на каждое новое правило:

1. teleman: пара команд берётся, если перед двоеточием подписи есть слово
   «mecz» где угодно («rewanżowy mecz barażowy: Polska - Belgia»), а не
   только первым; бои («walka:», «waga…:») — без пары, как раньше.
2. эталон: местные пометки пола flashscore («Italia D», «Polska K», «Polen
   F», …) у женской английской записи — наша «W» (`canon.local_name`);
   мужская запись буквы не теряет («Real Madrid C»).
3. разбор: у сайта без честного флага эфир — показ пары, ближайший к началу
   матча по эталону; одновременные показы на двух каналах — оба эфир
   (`parse_live.nearest_shows`).

В сеть не ходит:
    python scripts/test_lost_legs.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.mkdtemp()) / "none.db"))

from app import canon, names, pipeline                            # noqa: E402
from app.parsers import Program, get, site_says                  # noqa: E402
import parse_live                                                 # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


print("1. teleman: «mecz» в подписи — не обязательно первым словом")
СТРОКА = ('<table class="sport-table"><tr class="odd"><td>dziś, 13 października</td>'
          '<td>17:55</td><td><a href="/program-tv/stacje/TVP-Sport">TVP Sport</a></td>'
          '<td><a href="/tv/x" class="prog-title">Piłka nożna kobiet: Eliminacje '
          'mistrzostw świata</a> <img src="i.png" alt="na żywo" class="live" '
          'title="program na żywo" /> <em>{em}</em></td>'
          '<td class="tags"><a href="/sport/x">Piłka nożna</a></td></tr></table>')
teleman = get("teleman.pl")
for подпись, ждём in (
        ("rewanżowy mecz barażowy: Polska - Belgia", "Polska - Belgia"),
        ("rewanżowy mecz półfinałowy: CR Flamengo - Estudiantes De La Plata",
         "CR Flamengo - Estudiantes De La Plata"),
        ("mecz 1/8 finału: Holandia - Słowenia", "Holandia - Słowenia"),
        ("mecz: GKS Tychy - Tappara Tampere", "GKS Tychy - Tappara Tampere"),
        ("walka: Krzysztof Włodarczyk - Marcin Sianos", " "),
        ("waga średnia: Karol Welter - Stephen Danyo", " "),
        ("prolog", " ")):
    строки = teleman(СТРОКА.replace("{em}", подпись),
                     url="https://www.teleman.pl/sport?live=1&stations=all&page=1")
    проверка(f"«{подпись[:45]}» → «{ждём.strip()}»",
             строки[0].match_raw if строки else None, ждём)

print("2. эталон: местные пометки пола и возраста — наши")
for местное, английское, язык, ждём in (
        ("Italia D", "Italy W", "it", "Italia W"),
        ("Bielorussia U19 D", "Belarus U19 W", "it", "Bielorussia U19 W"),
        ("Polska K", "Poland W", "pl", "Polska W"),
        ("Polen F", "Poland W", "de", "Polen W"),
        ("België V", "Belgium W", "nl", "België W"),
        ("Lengyelország N", "Poland W", "hu", "Lengyelország W"),
        ("Biélorussie -17", "Belarus U17", "fr", "Biélorussie U17"),
        ("Real Madrid C", "Real Madrid C", "es", "Real Madrid C"),
        ("Jong Ajax", "Jong Ajax", "nl", "Jong Ajax"),
        ("Inter D", "Inter", "it", "Inter D")):          # мужская — буква остаётся
    проверка(f"{местное} ({язык}, {английское}) → {ждём}",
             canon.local_name(местное, английское, язык), ждём)
запись = {"home": "Italy W", "away": "Belarus W",
          "names": {"it": ["Italia D", "Bielorussia D"], "ru": ["Италия (Ж)", "Беларусь (Ж)"]}}
проверка("итальянское написание эталона сходится со строкой Rai 2",
         any(names.same_team("Italia W", h) and names.same_team("Bielorussia W", a)
             for _l, h, a in canon.local_pairs(запись)), True)

print("3. ближайший к матчу показ — эфир")


def показ(канал: str, час: int, минута: int, пара: str, угадан: bool = True,
          сайт: str = "raiplay.it"):
    p = Program(channel_raw=канал, title=пара, match_raw=пара,
                start=datetime(2026, 10, 13, час, минута, tzinfo=KYIV))
    if угадан:
        p.extra["live_guess"] = True
    else:
        site_says(p, True)
    home, _, away = пара.partition(" - ")
    return (сайт, pipeline.Row(program=p, ok=True, home=home, away=away,
                               sport="F", start_kyiv=p.start))


начало = datetime(2026, 10, 13, 19, 15, tzinfo=KYIV)


def матч(r):
    пара = {r.home, r.away}
    return начало if пара == {"Italia W", "Bielorussia W"} else None


found = [показ("Rai Sport", 17, 25, "Bielorussia W - Italia W"),   # запись 1-го матча
         показ("Rai 2", 19, 5, "Italia W - Bielorussia W"),        # живой ответный
         показ("Rai Sport", 19, 10, "Italia W - Bielorussia W"),   # тот же эфир, 2-й канал
         показ("Rai 1", 20, 0, "Inter - Milan")]                   # эталон не знает
остались, сняты = parse_live.nearest_shows(found, матч, parse_live.guessed)
проверка("запись 17:25 снята, эфир 19:05 и одновременный 19:10 — оставлены",
         [r.program.channel_raw + r.start_kyiv.strftime(" %H:%M") for _d, r in остались],
         ["Rai 2 19:05", "Rai Sport 19:10", "Rai 1 20:00"])
проверка("причина снятия — показ ближе к началу матча",
         [почему for _x, почему in сняты],
         ["у сайта есть показ ближе к началу матча (13.10 19:15): 13.10 19:10"])
помечен = [показ("TVP Sport", 17, 55, "Polska W - Belgia W", угадан=False, сайт="teleman.pl"),
           показ("TVP Sport", 23, 0, "Polska W - Belgia W", угадан=False, сайт="teleman.pl")]
остались, _ = parse_live.nearest_shows(
    помечен, lambda r: datetime(2026, 10, 13, 19, 0, tzinfo=KYIV), parse_live.guessed)
проверка("эфир, помеченный самим сайтом, правило не трогает", len(остались), 2)
один = [показ("Rai 2", 19, 5, "Italia W - Bielorussia W")]
проверка("единственный показ пары остаётся",
         len(parse_live.nearest_shows(один, матч, parse_live.guessed)[0]), 1)

print(f"\nзелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

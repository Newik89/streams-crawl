# -*- coding: utf-8 -*-
r"""Книга 138 (15.11.2026): теннис — турнир назван ОДНИМ КУСКОМ, пары нет вовсе.

Решение владельца 04.10: трансляцию турнира без игроков показываем названием
турнира. Оно работало, только когда заголовок делился по тире на «пару»
(«ATP 500 Tokyo - 1/4 Finale»). «ATP FINALS 2026», «Tenis ATP Torino 2026»
пары не дают и отсеивались: на сборе 15.11 — 240 прямых эфиров на 20 сайтах.
Слова владельца 15.11: «теннис у нас, если нет имён, попадает просто названием
турнира — это уже было решено».

Правила: `pipeline.tournament_whole` (Т0–Т6), `broadcast.key` (1–6),
`broadcast.names_tournament`, `broadcast.starts_near`, `broadcast.played`.
В сеть не ходит, базу не трогает. Запуск: python scripts/test_turnir_kuskom.py
"""
from __future__ import annotations

import inspect
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import broadcast, live, pipeline, sport, store  # noqa: E402
from app.live import _pattern  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import Reference  # noqa: E402
import parse_live  # noqa: E402
import proverka  # noqa: E402

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


# ── эталон: итоговые турниры ATP и WTA, челленджеры для «богатства» ──────────
ТУРИН = "ATP - SINGLES: Finals - Turin (World), hard (indoor)"
ТУРИН_ПАРЫ = "ATP - DOUBLES: Finals - Turin (World), hard (indoor)"
ТУРИН_МЕСТНЫЕ = {"hu": "ATP - EGYÉNI: Finals - Torino (Világ), kemény (fedettpályás)",
                 "ru": "ATP - ОДИНОЧНЫЙ РАЗРЯД: Итоговый турнир - Турин (Мир), хард (в помещении)",
                 "cs": "ATP - DVOUHRY: Turnaj mistrů - Turín (Svět), tvrdý povrch (hala)"}
УЭЛЛС = "WTA - SINGLES: Finals - Indian Wells (World), hard"


def матч(home, away, league, start, местные=None):
    return {"sport": "T", "home": home, "away": away, "league": league,
            "start_kyiv": start, "leagues": местные or {}}


ЭТАЛОН = [
    матч("Alcaraz C.", "Tiafoe F.", ТУРИН, "2026-11-16T15:00", ТУРИН_МЕСТНЫЕ),
    матч("Medvedev D.", "Cobolli F.", ТУРИН, "2026-11-16T21:30", ТУРИН_МЕСТНЫЕ),
    матч("Granollers M./Zeballos H.", "Bolelli S./Vavassori A.", ТУРИН_ПАРЫ, "2026-11-17T12:30"),
    матч("Sabalenka A.", "Gauff C.", УЭЛЛС, "2026-11-15T22:00"),
] + [матч(f"Player{i} A.", f"Rival{i} B.", "CHALLENGER MEN - SINGLES: Sydney (Australia), hard",
          f"2026-11-16T{4 + i % 6:02d}:00") for i in range(40)]
БЕДНЫЙ = ЭТАЛОН[:4]
судья, бедный = Reference(ЭТАЛОН), Reference(БЕДНЫЙ)
известно = судья.tournaments()
метки, виды = live.load(), sport.load()
ФИНАЛ_ATP = ("ATP", "Finals - Turin")


def строка(title, when, *, эфир="", league="", sport_raw="", match="", канал="Sport 1"):
    return Program(channel_raw=канал, title=title, start=datetime(*when, tzinfo=KYIV),
                   live_raw=эфир, league_raw=league, sport_raw=sport_raw, match_raw=match)


def разбор(program, *, эталон=судья, угадайка=False):
    row = pipeline.classify(program, метки, виды, reference=эталон, guess_site=угадайка)
    return row.ok, row.home, row.away, row.sport


print("Что известно о турнирах (`broadcast.tournaments`)")
проверка("двойное имя эталона «Finals - Turin»: событие и город — отдельно; обычное — только город",
         (broadcast._name_parts("Finals - Turin"), broadcast._name_parts("Beijing")),
         ((["Finals"], "Turin"), ([], "Beijing")))
проверка("начала матчей и туры собраны по турнирам; матчей тенниса сосчитано",
         (sorted(x.strftime("%d %H:%M") for x in известно["starts"][ФИНАЛ_ATP]),
          известно["tours"]["Finals - Turin"], известно["matches"]),
         (["16 15:00", "16 21:30", "17 12:30"], {"ATP"}, 44))

print("Турнир по заголовку (`broadcast.key`), правила 1–6")
проверка("правило 1: названы и ATP, и WTA — не сводим",
         broadcast.key("ATP Finals & WTA Finals", известно), ("", ""))
проверка("правило 2: город двойного имени — на языках эталона («Torino» из венгерского, «Турин» из русского)",
         (broadcast.key("Tenis ATP Torino 2026", известно), broadcast.key("Теннис. ATP. Турин", известно)),
         (ФИНАЛ_ATP, ФИНАЛ_ATP))
проверка("правило 3: города нет, тур назван — слово события: «ATP Finals» → Турин, «WTA Finals» → Индиан-Уэллс, "
         "чешское «Turnaj mistrů» — тоже",
         (broadcast.key("Nitto ATP Finals: Groepsfase", известно), broadcast.key("Tennis: WTA Finals 2026", известно),
          broadcast.key("ATP: Turnaj mistrů", известно)),
         (ФИНАЛ_ATP, ("WTA", "Finals - Indian Wells"), ФИНАЛ_ATP))
проверка("правило 3: слово события без названного тура — ничей («Davis Cup Finals»)",
         broadcast.key("Tennis: Davis Cup Finals", известно), ("", ""))
свои = {"cities": {"Turin": _pattern(["torino"]), "Finals - Turin": _pattern(["torino"]),
                   "Sydney": _pattern(["sydney"])},
        "events": {}, "tours": {"Finals - Turin": {"ATP"}, "Sydney": {"Challenger"}}}
проверка("правило 4: город словаря и турнир эталона с тем же городом — одно: остаётся турнир названного тура",
         broadcast.key("ATP Torino", свои), ФИНАЛ_ATP)
проверка("правило 5: два города одного тура в блоке — не сводим",
         broadcast.key("ATP Finals Torino, Finals Indian Wells",
                       {**известно, "tours": {**известно["tours"], "Finals - Indian Wells": {"ATP"}}}), ("", ""))
проверка("правило 6: тур не назван — единственный тур города в эталоне; имя для сведения — «тур город»",
         (broadcast.key("Sydney 2026", известно), broadcast.tournament("Tenis ATP Torino 2026", известно)),
         (("Challenger", "Sydney"), "ATP Finals Turin"))

print("Назван ли турнир (`broadcast.names_tournament`)")
проверка("одно слово вида спорта — не турнир; тур, слово турнира, стадия, год — турнир",
         [broadcast.names_tournament(x) for x in
          ("Tenis", "Τένις", "Теннис", "Tenis ATP Torino 2026", "Tennis: Finale", "Tenis 2026", "Mutua Madrid Open")],
         [False, False, False, True, True, True, True])

print("Эфир турнира по эталону (`broadcast.starts_near`, `broadcast.played`)")
проверка("матч турнира начинается от 15 минут до показа до часа после него — эфир; иначе нет",
         [broadcast.starts_near(ФИНАЛ_ATP, datetime(2026, 11, 16, h, m), известно)
          for h, m in ((15, 0), (14, 0), (13, 59), (15, 15), (15, 16), (3, 0))],
         [True, True, False, True, False, False])
проверка("показ со своим поясом сверяется так же; турнира нет в эталоне — он не идёт",
         (broadcast.starts_near(ФИНАЛ_ATP, datetime(2026, 11, 16, 15, 0, tzinfo=KYIV), известно),
          broadcast.played(ФИНАЛ_ATP, известно), broadcast.played(("ATP", "Shanghai"), известно)),
         (True, True, False))

print("Турнир одним куском (`pipeline.tournament_whole`), правила Т0–Т6")
p = строка("ATP FINALS 2026", (2026, 11, 18, 15, 0), эфир="live")
проверка("Т4, Т6: сайт пометил эфир, пары нет, турнир назван — трансляция турнира: заголовок и служебная сторона",
         (разбор(p), p.extra.get(pipeline.TOURNAMENT), p.extra.get("live_guess"),
          broadcast.is_title("T", "ATP FINALS 2026", broadcast.SESSION)),
         ((True, "ATP FINALS 2026", broadcast.SESSION, "T"),
          {"тур": "ATP", "город": "Finals - Turin", "эталон": False}, None, True))
проверка("Т4: тур и город узнаны, эталон богат, а турнира в нём нет — запись («ATP Shanghai» в ноябре)",
         разбор(строка("ATP Shanghai", (2026, 11, 16, 15, 0), эфир="live broadcast"))[:1], (False,))
проверка("Т4: эталон беден теннисом — о турнире судить нечем, слову сайта верим",
         разбор(строка("ATP Shanghai", (2026, 11, 16, 15, 0), эфир="live broadcast"), эталон=бедный)[:3],
         (True, "ATP Shanghai", broadcast.SESSION))
проверка("Т4: турнир не узнан (город неизвестен) — слову сайта верим",
         разбор(строка("TENIS ATP: STOCKHOLM OPEN", (2026, 11, 16, 15, 0), эфир="live"))[:3],
         (True, "TENIS ATP: STOCKHOLM OPEN", broadcast.SESSION))
p = строка("Tenis ATP Torino 2026", (2026, 11, 16, 15, 0), канал="SuperSport 4")
проверка("Т5: сайт эфир не помечает, а в эталоне матч турнира начинается рядом — эфир угадан, подтвердил эталон",
         (разбор(p, угадайка=True), p.extra.get(pipeline.TOURNAMENT), p.extra.get("live_guess")),
         ((True, "Tenis ATP Torino 2026", broadcast.SESSION, "T"),
          {"тур": "ATP", "город": "Finals - Turin", "эталон": True}, True))
проверка("Т5: тот же показ ночью (матча рядом нет) — запись",
         разбор(строка("Tenis ATP Torino 2026", (2026, 11, 16, 3, 0)), угадайка=True)[:1], (False,))
проверка("Т5: сайт с честной пометкой эфира, а у строки её нет — эталон не спасает",
         разбор(строка("Tenis ATP Torino 2026", (2026, 11, 16, 15, 0)), угадайка=False)[:1], (False,))
проверка("Т5: турнир не узнан — без пометки сайта не берём",
         разбор(строка("Tenis ATP 2026", (2026, 11, 16, 15, 0)), угадайка=True)[:1], (False,))
p = строка("Nitto ATP Finals 2026 (T2026): Alcaraz - Tiafoe", (2026, 11, 17, 12, 40))
проверка("Т0: игроки названы, эталон показ эфиром не признал — запись, а не трансляция турнира "
         "(наутро после матча, в минуту начала чужой встречи)",
         (разбор(p, угадайка=True)[:1], pipeline.TOURNAMENT in p.extra), ((False,), False))
проверка("Т1: слово записи в самом заголовке при значке эфира — запись; без него тот же заголовок — трансляция",
         (разбор(строка("Nitto ATP Finals: Groepsfase (herhaling)", (2026, 11, 16, 15, 0), эфир="live"))[:1],
          разбор(строка("Nitto ATP Finals: Groepsfase", (2026, 11, 16, 15, 0), эфир="live"))[:1]),
         ((False,), (True,)))
проверка("Т2: не теннис — не берём (марафон с годом в названии)",
         разбор(строка("Maratona e Tiranes 2026", (2026, 11, 16, 15, 0), эфир="live"))[:1], (False,))
проверка("Т3: одно слово «теннис» — турнир не назван",
         разбор(строка("Tenis", (2026, 11, 16, 15, 0), эфир="live"))[:1], (False,))
проверка("Т6: турнир назван в лиге, а не в заголовке — имя из лиги и заголовка",
         разбор(строка("Evening Session", (2026, 11, 18, 19, 0), эфир="live", league="ATP Finals", sport_raw="Tenis"))[:3],
         (True, "ATP Finals Evening Session", broadcast.SESSION))
проверка("Т6: меток пола и возраста название турнира не носит (женский турнир — без « W»)",
         разбор(строка("WTA Finals 2026", (2026, 11, 15, 22, 0), эфир="live", league="Women's tennis"))[:3],
         (True, "WTA Finals 2026", broadcast.SESSION))
проверка("прежнее правило цело: заголовок с тире идёт своей дорогой, пометки «турнир одним куском» у него нет",
         [(row.ok, pipeline.TOURNAMENT in prog.extra) for prog in
          [строка("ATP 500 Tokyo - 1/4 Finale", (2026, 11, 16, 15, 0), эфир="live")]
          for row in [pipeline.classify(prog, метки, виды, reference=судья)]], [(True, False)])

print("Подключение")
проверка("разбор сбора говорит разбору строк, что сайт эфир не помечает; пометка турнира спасает строку "
         "от фильтра «угаданный эфир без эталона»",
         ("guess_site=_bare_domain(domain)" in inspect.getsource(parse_live),
          "get(pipeline.TOURNAMENT) or {}).get(\"эталон\")" in inspect.getsource(parse_live)), (True, True))
проверка("сессии турнира у сайта без пометки эфира — не «поздний показ»: строку с подтверждённым турниром "
         "фильтр позднего показа не снимает",
         inspect.getsource(parse_live).count("get(pipeline.TOURNAMENT) or {}).get(\"эталон\")"), 2)


def игра(start, home, away, каналы, sport="T"):
    return {"start_kyiv": start, "home": home, "away": away, "sport": sport,
            "entries": [{"channel": ch, "source": site} for ch, site in каналы]}


старая = игра("2026-11-21T15:30", "ATP FINALS 2026", "MEIA-FINAL", [("SPORT.TV6", "sporttv.pt")])
общая = игра("2026-11-21T13:00", "ATP Finals Turin", broadcast.SESSION,
             [("Digi Sport 2", "digisport.ro"), ("SPORT.TV6", "sporttv.pt")])
проверка("сравнение сборов: показ турнира вошёл в новую сведённую строку с тем же каналом — не пропажа; "
         "канала при ней нет, строка дальше трёх часов, не теннис или новая строка не турнир — пропажа",
         [proverka.merged_session(старая, [общая]) is общая,
          proverka.merged_session(старая, [игра("2026-11-21T13:00", "ATP Finals Turin", broadcast.SESSION,
                                               [("Digi Sport 2", "digisport.ro")])]),
          proverka.merged_session(старая, [dict(общая, start_kyiv="2026-11-21T09:00")]),
          proverka.merged_session(dict(старая, sport="F"), [общая]),
          proverka.merged_session(старая, [dict(общая, away="Sinner J.")])],
         [True, None, None, None, None])
своё = broadcast.stage("ATP Finals Turin")
проверка("витрина: стадию, которую даёт само имя турнира («ATP Finals» → Final), стадией показа не пишем; "
         "настоящую стадию — пишем",
         (своё,
          next((s for s in map(broadcast.stage, ["Nitto ATP Finals: Groepsfase"]) if s and s != своё), ""),
          next((s for s in map(broadcast.stage, ["ATP Finals: Polufinale 1"]) if s and s != своё), ""),
          "if s and s != own" in inspect.getsource(store.schedule)),
         ("Final", "", "Semifinals", True))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

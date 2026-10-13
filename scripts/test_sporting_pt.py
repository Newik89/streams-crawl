# -*- coding: utf-8 -*-
r"""Разбор календаря «Спортинга» (`app/parsers/sporting_pt.py`, просьба
владельца 13.10.2026). По проверке на каждое правило модуля; примеры —
настоящие события из календаря сайта (проба #253).

В сеть не ходит:
    python scripts/test_sporting_pt.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import leagues, parsers  # noqa: E402
from app.parsers import SITE_FLAG, SITE_LIVE  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def событие(start: str, summary: str, location: str, description: str) -> str:
    return ("BEGIN:VEVENT\r\nUID:calendar.1@www.sporting.pt\r\n"
            f"DESCRIPTION:{description}\r\n{start}\r\n"
            f"LOCATION:{location}\r\nSUMMARY:{summary}\r\n"
            "URL;TYPE=URI:https://www.sporting.pt/pt/jogos/x\r\nEND:VEVENT\r\n")


КАЛЕНДАРЬ = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join([
    # 1. первая команда, ЛЧ, SPORT TV 5 (описание перенесено строкой с пробелом)
    событие("DTSTART;TZID=Europe/London:20261013T174500",
            "Futebol (Seniores M): RC Lens vs. SPORTING CP",
            "2.ª jornada da Fase de Liga da Liga dos Campeões da UEFA",
            "Equipa visitada: \\n\\nRC Lens\\n\\nStade Bollaert-Delelis (Lens\\, França)"
            " - TRANSMISSÃO EM\r\n  DIRECTO NA SPORT TV 5\\n\\nDestaque: \\n"),
    # 2. женская команда — Sporting TV, «e em exclusivo»
    событие("DTSTART;TZID=Europe/London:20260923T170000",
            "Futebol (Seniores F): Brøndby IF vs. SPORTING CP",
            "1.ª mão da 2.ª Pré-eliminatória da Europa Cup da UEFA",
            "Brøndby - TRANSMISSÃO EM DIRECTO E EM EXCLUSIVO NA SPORTING TV\\n"),
    # 3. юниорки Sub-19 — канал «EM CANAL11.PT»
    событие("DTSTART;TZID=Europe/London:20261018T110000",
            "Futebol (Sub-19 F): Vitória SC vs. SPORTING CP",
            "5.ª jornada da 1.ª fase da Liga Sub-19",
            "Guimarães - TRANSMISSÃO EM DIRECTO EM CANAL11.PT\\n"),
    # 4. без трансляции — не берём
    событие("DTSTART;TZID=Europe/London:20261013T183000",
            "Andebol (Seniores M): SPORTING CP vs. Póvoa AC",
            "10.ª jornada da 1.ª fase do Campeonato Nacional",
            "Pavilhão João Rocha\\n"),
    # 5. время не назначено (только дата) — не берём
    событие("DTSTART;VALUE=DATE:20261206",
            "Futebol (Seniores M): SPORTING CP vs. CS Marítimo",
            "13.ª jornada da Liga Portugal",
            "Alvalade - TRANSMISSÃO EM DIRECTO NA SPORT TV 1\\n"),
    # 6. не игра двух команд (турнир) — не берём
    событие("DTSTART;TZID=Europe/London:20261020T100000",
            "Karate - Lion Cup", "Lion Cup",
            "Lisboa - TRANSMISSÃO EM DIRECTO NA SPORTING TV\\n"),
]) + "END:VCALENDAR\r\n")

parse = parsers.get("www.sporting.pt")
строки = parse(КАЛЕНДАРЬ, url="https://www.sporting.pt/pt/ical")
по_паре = {p.match_raw: p for p in строки}

print("правило 1–3: только трансляции с часом игры, только пары")
проверка("взято 3 события из 6", sorted(по_паре),
         ["Brøndby IF - SPORTING CP", "RC Lens - SPORTING CP", "Vitória SC - SPORTING CP"])

print("правило 2: канал — как написал сайт")
проверка("перенесённая строка описания склеена: SPORT TV 5",
         по_паре["RC Lens - SPORTING CP"].channel_raw, "SPORT TV 5")
проверка("«e em exclusivo na» → SPORTING TV",
         по_паре["Brøndby IF - SPORTING CP"].channel_raw, "SPORTING TV")
проверка("«em canal11.pt» → CANAL11.PT",
         по_паре["Vitória SC - SPORTING CP"].channel_raw, "CANAL11.PT")
проверка("фильтр каналов карточки",
         [p.match_raw for p in parse(КАЛЕНДАРЬ, channels={"SPORT TV 5"})],
         ["RC Lens - SPORTING CP"])

print("правило 3: время с поясом календаря")
lens = по_паре["RC Lens - SPORTING CP"]
проверка("17:45 по Лиссабону/Лондону = 16:45 UTC",
         lens.start.astimezone().utcoffset() is not None
         and lens.start.strftime("%Y-%m-%d %H:%M %z"), "2026-10-13 17:45 +0100")

print("правило 4: вид спорта — слово до скобки")
проверка("Futebol → futebol", lens.sport_raw, "futebol")

print("правило 5: пол и возраст — суффиксы W и U19")
проверка("мужская первая команда — без суффикса", leagues.category(lens.league_raw), "")
проверка("женская команда — W",
         leagues.category(по_паре["Brøndby IF - SPORTING CP"].league_raw), "W")
проверка("юниорки Sub-19 — U19 W",
         leagues.category(по_паре["Vitória SC - SPORTING CP"].league_raw), "U19 W")

print("правило 6: эфир — пометка сайта")
проверка("live_raw = directo, флаг сайта", (lens.live_raw, lens.extra.get(SITE_FLAG)),
         ("directo", SITE_LIVE))

print("пустой или чужой ответ")
проверка("не календарь — пусто", parse("<html>Agenda</html>"), [])

print(f"\nзелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

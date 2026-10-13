# -*- coding: utf-8 -*-
r"""Самопроверка, проверка 13: сайт показал матч эталона в эфир, а канала у
игры на витрине нет (книга случаев 13.10.2026: Польша W — Бельгия W на TVP
Sport у teleman, Италия W — Беларусь W на Rai 2 у raiplay — оба матча сайт
показывал, а на витрину они не попали, и ни одна проверка этого не видела).

Правила (`audit_run.check_seen_not_shown`):
1. пару ищем в подписи передачи по написаниям эталона на всех языках без
   пометок пола и возраста («Polska K» → «polska») — целыми словами;
2. показ — эфир, если он от часа до начала матча до 15 мин после;
   запись/повтор (слово not_live) — не эфир;
3. подозрение — только если у игры витрины (та же пара ±3 ч) нет НИ ОДНОГО
   канала этого сайта.

В сеть не ходит:
    python scripts/test_seen_not_shown.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import live  # noqa: E402
from app.parsers import Program  # noqa: E402
import audit_run  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
WARSAW = ZoneInfo("Europe/Warsaw")
MARKERS = live.load()
зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✗ {имя}: вышло {вышло!r}, ждали {ждём!r}")


ПОЛЬША = {"sport": "F", "home": "Poland W", "away": "Belgium W", "fs_id": "IXTSTJ1s",
          "start_kyiv": "2026-10-13T19:00",
          "names": {"pl": ["Polska K", "Belgia K"], "it": ["Polonia D", "Belgio D"],
                    "ru": ["Польша (Ж)", "Бельгия (Ж)"]}}
ИТАЛИЯ = {"sport": "F", "home": "Italy W", "away": "Belarus W", "fs_id": "fNdOFx8s",
          "start_kyiv": "2026-10-13T19:15",
          "names": {"it": ["Italia D", "Bielorussia D"], "pl": ["Włochy K", "Białoruś K"]}}


def показ(канал: str, заголовок: str, когда: str, пояс=KYIV, **ещё) -> Program:
    return Program(channel_raw=канал, title=заголовок,
                   start=datetime.fromisoformat(когда).replace(tzinfo=пояс), **ещё)


def сайт(домен: str, *показы: Program) -> dict:
    s = audit_run.Site(домен)
    s.shows = list(показы)
    return {домен: s}


def игра(дом, гость, когда, *каналы) -> dict:
    return {"home": дом, "away": гость, "start_kyiv": когда, "sport": "F", "league": "",
            "entries": [{"source": src, "channel": ch} for src, ch in каналы]}


def витрина(*игры, эталон=(ПОЛЬША, ИТАЛИЯ)) -> dict:
    return {"собрано": "2026-10-13 06:32", "окно": 6, "games": list(игры),
            "эталон": list(эталон)}


def сторож(сайты, games) -> list[str]:
    return audit_run.check_seen_not_shown(сайты, games, MARKERS)


print("1. пара по написаниям эталона на всех языках, без пометок пола")
teleman = сайт("teleman.pl", показ("TVP Sport", "Piłka nożna kobiet: rewanżowy mecz "
                                    "barażowy: Polska - Belgia", "2026-10-13T17:55", WARSAW))
вышло = сторож(teleman, витрина())
проверка("teleman: матч показан, игры на витрине нет — подозрение", len(вышло), 1)
проверка("в подозрении — сайт, канал и эталон",
         all(x in (вышло or [""])[0] for x in ("teleman.pl", "TVP Sport", "Poland W", "IXTSTJ1s")), True)
raiplay = сайт("raiplay.it", показ("Rai 2", "Calcio: Qualificazioni Mondiali femminili 2027 - "
                                    "Spareggi (ritorno): Italia - Bielorussia", "2026-10-13T19:05"))
проверка("raiplay: «Italia - Bielorussia» узнана по итальянскому написанию",
         len(сторож(raiplay, витрина())), 1)
проверка("кириллица: «Польша — Бельгия» узнана по русскому написанию",
         len(сторож(сайт("x.ru", показ("Матч ТВ", "Футбол. Польша — Бельгия", "2026-10-13T18:55")),
                    витрина())), 1)
проверка("«Italiano» — не «Italia»: целыми словами",
         сторож(сайт("x.it", показ("Rai 2", "Italiano - Bielorussia", "2026-10-13T19:05")),
                витрина()), [])
проверка("одна команда в подписи — не пара",
         сторож(сайт("x.it", показ("Rai 2", "Speciale Italia", "2026-10-13T19:05")), витрина()), [])

print("2. окно эфира: от часа до начала до 15 мин после")
проверка("показ за 95 мин (запись 17:25 у Rai Sport) — не эфир",
         сторож(сайт("raiplay.it", показ("Rai Sport", "Bielorussia - Italia", "2026-10-13T17:40")),
                витрина()), [])
проверка("показ за час — эфир (блок с предматчевой)",
         len(сторож(сайт("raiplay.it", показ("Rai 2", "Italia - Bielorussia", "2026-10-13T18:15")),
                    витрина())), 1)
проверка("показ через 20 мин после начала — уже не эфир",
         сторож(сайт("raiplay.it", показ("Rai 2", "Italia - Bielorussia", "2026-10-13T19:35")),
                витрина()), [])
проверка("слово записи («powtórka») — не эфир",
         сторож(сайт("teleman.pl", показ("TVP Sport", "Polska - Belgia", "2026-10-13T18:55",
                                         live_raw="powtórka")), витрина()), [])
проверка("день вне окна сбора — не судим",
         сторож(сайт("teleman.pl", показ("TVP Sport", "Polska - Belgia", "2026-10-25T18:55")),
                витрина(эталон=({**ПОЛЬША, "start_kyiv": "2026-10-25T19:00"},))), [])

print("3. подозрение — только если у игры нет НИ ОДНОГО канала сайта")
есть = витрина(игра("Polska W", "Belgia W", "2026-10-13T18:55", ("teleman.pl", "TVP Sport")))
проверка("игра с каналом сайта на витрине — тихо", сторож(teleman, есть), [])
чужой = витрина(игра("Poland W", "Belgium W", "2026-10-13T19:00", ("tvp.pl", "TVP Sport")))
проверка("игра есть, но канала этого сайта нет — подозрение", len(сторож(teleman, чужой)), 1)
два = сайт("teleman.pl",
           показ("TVP Sport", "Polska - Belgia", "2026-10-13T18:55"),
           показ("TVP Sport 2", "Studio: Polska - Belgia", "2026-10-13T18:30"))
проверка("второй канал сайта со студией не шумит, если первый на витрине",
         сторож(два, есть), [])
проверка("мужская игра той же вывески — не та игра (пол не совпал)",
         len(сторож(teleman, витрина(игра("Poland", "Belgium", "2026-10-13T19:00",
                                          ("teleman.pl", "Polsat Sport 1"))))), 1)
проверка("без games.json проверка молчит", сторож(teleman, None), [])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

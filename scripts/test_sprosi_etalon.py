# -*- coding: utf-8 -*-
r"""Починка самопроверки №13 (владелец 20.10.2026), правила (в) и (г):

(в) «не уверен — спроси эталон» вместо списков по сайтам: нет пометки эфира,
    пара неясна или вид спорта неясен → совпало с эталоном → эфир
    (`reference.Reference.confirm`, `pipeline.ask_reference`, `classify`);
(г) один читатель пары: дефис без пробелов, « at » с перестановкой, скобки,
    три тире, рубрика в заголовке — все догадки даёт `live.split_candidates`,
    а верную выбирает только эталон.

Эталоны маленькие и собраны прямо здесь (по образцу сбора #301, все
времена — киевские). В сеть не ходит, база не нужна:

    python scripts/test_sprosi_etalon.py

Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
# базу не открываем, но на всякий случай — не боевая
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.gettempdir()) / "sprosi-etalon-none.db"))

from app import live, pipeline, sport  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import Reference  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
MARKERS = live.load()
#: словарь команд пустой — сценарии не зависят от data/dictionaries.json
SPORTS = sport.load(teams=())
зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✗ {имя}: вышло {вышло!r}, ждали {ждём!r}")


def матч(вид: str, дом: str, гость: str, когда: str, **написания) -> dict:
    """Запись эталона в том виде, в каком её кладёт сбор (`games.json`)."""
    return {"sport": вид, "home": дом, "away": гость, "league": "",
            "fs_id": (дом[:4] + гость[:4]).replace(" ", ""),
            "start_kyiv": когда, "names": написания}


def момент(когда: str) -> datetime:
    return datetime.fromisoformat(когда)


# ── эталон по образцу сбора #301 ─────────────────────────────────────────────
ЭТАЛОН = Reference([
    матч("F", "Levante", "Ath Bilbao", "2026-10-21T21:00",
         es=["Levante", "Athletic Club"]),
    матч("F", "Al Nassr", "Neom SC", "2026-10-20T21:00"),
    матч("B", "Miami Heat", "Minnesota Timberwolves", "2026-10-22T02:30"),
    матч("B", "Zalgiris Kaunas", "Lyon-Villeurbanne", "2026-10-23T20:00"),
    матч("F", "Stuttgart", "Atl. Madrid", "2026-10-20T22:00",
         de=["VfB Stuttgart", "Atletico Madrid"]),
    матч("F", "Nurnberg", "Kaiserslautern", "2026-10-24T21:30"),
    матч("F", "Vasco", "Boca Juniors", "2026-10-21T03:30"),
    матч("T", "Sinner J.", "Alcaraz C.", "2026-10-22T15:00"),
    матч("F", "Poland", "Belgium", "2026-10-24T19:00"),
    # дерби одних клубов в один вечер и в футболе, и в баскетболе
    матч("F", "Partizan", "Crvena zvezda", "2026-10-25T20:00"),
    матч("B", "Partizan", "Crvena zvezda", "2026-10-25T20:30"),
    матч("F", "PSG", "Le Mans", "2026-10-10T21:45"),
])


def ответ(дом, гость, когда, вид="", эталон=ЭТАЛОН):
    """Что сказал эталон: (хозяева эталона, гости, как сошлось, обратный ли
    порядок, начало) — или None."""
    got = эталон.confirm(дом, гость, момент(когда) if когда else None, вид)
    if got is None:
        return None
    return (got.entry["home"], got.entry["away"], got.how, got.swapped,
            got.start.strftime("%d.%m %H:%M"))


# ═════════════════════════════════════════════════════════════════════════════
print("(г) live.split_candidates — один читатель пары")
проверка("правило 1: обычная пара « - » — одна догадка",
         live.split_candidates("Stuttgart - Atletico Madrid"),
         [("Stuttgart", "Atletico Madrid")])
проверка("правило 1: « vs » и обвязка с краёв, как у split_teams",
         live.split_candidates("3 кръг, Levante vs Ath Bilbao, директно"),
         [("Levante", "Ath Bilbao")])
проверка("правило 1 первым: «Topspiel: 1. FC Nürnberg - 1. FC Kaiser» — "
         "чтение split_teams (обвязка до «: » счищена) стоит первой догадкой",
         live.split_candidates("Topspiel: 1. FC Nürnberg - 1. FC Kaiser")[0],
         ("1. FC Nürnberg", "1. FC Kaiser"))
кандидаты = live.split_candidates(
    "2. Bundesliga Live - Topspiel: 1. FC Nürnberg - 1. FC Kaiserslautern")
проверка("правило 2: рубрика до последнего «: » отрезана — пара rtl.de есть",
         ("1. FC Nürnberg", "1. FC Kaiserslautern") in кандидаты, True)
проверка("правило 2+3: три куска через тире — разрез, дающий ту же пару, не "
         "повторяется", кандидаты.count(("1. FC Nürnberg", "1. FC Kaiserslautern")), 1)
проверка("правило 3: «Virtus - Bologna - Baskonia» — пара на каждом разрезе, "
         "по порядку",
         live.split_candidates("Virtus - Bologna - Baskonia"),
         [("Virtus", "Bologna - Baskonia"), ("Virtus - Bologna", "Baskonia")])
проверка("правило 4: « at » — хозяева после «at» (догадка с рубрикой и без)",
         live.split_candidates("NBA Basketball: Minnesota Timberwolves at Miami Heat")[-1],
         ("Miami Heat", "Minnesota Timberwolves"))
проверка("правило 4: « @ » — так же",
         live.split_candidates("Celtics @ Knicks"), [("Knicks", "Celtics")])
проверка("правило 5: дефис без пробелов «Al Nassr-Al Neom» (ipko.tv)",
         live.split_candidates("Al Nassr-Al Neom"), [("Al Nassr", "Al Neom")])
проверка("правило 5: на каждом дефисе, по порядку",
         live.split_candidates("Real-Barca-Live"),
         [("Real", "Barca-Live"), ("Real-Barca", "Live")])
проверка("правило 5: пробел лишь с одной стороны «Aston Villa- Viking» (tvarenasport)",
         live.split_candidates("Aston Villa- Viking"), [("Aston Villa", "Viking")])
проверка("правило 5 молчит при тире среди пробелов: «Saint-Étienne - Lyon» — "
         "одна обычная пара, дефис в имени не режется",
         live.split_candidates("Saint-Étienne - Lyon"), [("Saint-Étienne", "Lyon")])
проверка("скобки с хвостом вырезаны: «Vasco da Gama (BRA) - Boca Juniors (ARG)»",
         live.split_candidates("Vasco da Gama (BRA) - Boca Juniors (ARG)"),
         [("Vasco da Gama", "Boca Juniors")])
проверка("пустая строка — нет догадок", live.split_candidates(""), [])
проверка("одно имя без разделителя — нет догадок",
         live.split_candidates("Fußball Bundesliga"), [])
проверка("сама с собой команда не играет: «Fenerbahçe-Fenerbahçe» — нет догадок",
         live.split_candidates("Fenerbahçe-Fenerbahçe"), [])
все = live.split_candidates(
    "NBA Basketball: Minnesota Timberwolves at Miami Heat - Live - Studio")
проверка("повторов нет ни в одном списке догадок", len(все), len(set(все)))

# ═════════════════════════════════════════════════════════════════════════════
print("(в) Reference.confirm — правило 1: окно эфира −15…+60 мин")
проверка("показ в минуту начала → «пара»",
         ответ("Levante", "Ath Bilbao", "2026-10-21T21:00"),
         ("Levante", "Ath Bilbao", "пара", False, "21.10 21:00"))
проверка("показ за час до матча — ещё эфир (сетка ставит блок раньше)",
         ответ("Levante", "Ath Bilbao", "2026-10-21T20:00") is not None, True)
проверка("показ через 14 мин после начала — ещё эфир",
         ответ("Levante", "Ath Bilbao", "2026-10-21T21:14") is not None, True)
проверка("показ за 2 ч до матча — не эфир этого матча",
         ответ("Levante", "Ath Bilbao", "2026-10-21T19:00"), None)
проверка("показ через 20 мин после начала — запись, не эфир",
         ответ("Levante", "Ath Bilbao", "2026-10-21T21:20"), None)
проверка("показ без времени — эталон молчит",
         ответ("Levante", "Ath Bilbao", ""), None)
проверка("пустой эталон — молчит",
         ответ("Levante", "Ath Bilbao", "2026-10-21T21:00", эталон=Reference([])), None)
проверка("запись эталона без времени не заводится и не отвечает",
         ответ("Levante", "Ath Bilbao", "2026-10-21T21:00",
               эталон=Reference([матч("F", "Levante", "Ath Bilbao", "")])), None)

print("(в) Reference.confirm — правило 3: пара целиком")
проверка("обратный порядок «гости at хозяева» → «пара», swapped",
         ответ("Ath Bilbao", "Levante", "2026-10-21T21:00"),
         ("Levante", "Ath Bilbao", "пара", True, "21.10 21:00"))
проверка("местное написание (names.es «Athletic Club») → «пара»",
         ответ("Levante", "Athletic Club", "2026-10-21T21:00"),
         ("Levante", "Ath Bilbao", "пара", False, "21.10 21:00"))
проверка("немецкое написание «Atletico Madrid» → Stuttgart — Atl. Madrid",
         ответ("Stuttgart", "Atletico Madrid", "2026-10-20T22:00"),
         ("Stuttgart", "Atl. Madrid", "пара", False, "20.10 22:00"))
проверка("«Al Nassr - Al Neom» → Al Nassr — Neom SC «пара»",
         ответ("Al Nassr", "Al Neom", "2026-10-20T21:00"),
         ("Al Nassr", "Neom SC", "пара", False, "20.10 21:00"))
проверка("та же пара в футболе и баскетболе в окне — эталон не судья",
         ответ("Partizan", "Crvena zvezda", "2026-10-25T20:00"), None)

print("(в) Reference.confirm — правило 2: вид спорта, если назван")
проверка("названный «B» берёт баскетбольное дерби",
         ответ("Partizan", "Crvena zvezda", "2026-10-25T20:00", "B"),
         ("Partizan", "Crvena zvezda", "пара", False, "25.10 20:30"))
проверка("названный «F» — футбольное",
         ответ("Partizan", "Crvena zvezda", "2026-10-25T20:00", "F"),
         ("Partizan", "Crvena zvezda", "пара", False, "25.10 20:00"))
проверка("названный чужой вид отсекает матч: Levante — Ath Bilbao как «B» → None",
         ответ("Levante", "Ath Bilbao", "2026-10-21T21:00", "B"), None)

print("(в) Reference.confirm — правило 4: одна сторона")
проверка("одна сторона твёрдо + вторая буквами ≥ 40: «1. FC Kaiser» → "
         "Nurnberg — Kaiserslautern «одна сторона»",
         ответ("1. FC Nürnberg", "1. FC Kaiser", "2026-10-24T21:15"),
         ("Nurnberg", "Kaiserslautern", "одна сторона", False, "24.10 21:30"))
проверка("одна сторона + общее слово: ASVEL Villeurbanne vs Lyon-Villeurbanne",
         ответ("Zalgiris Kaunas", "ASVEL Villeurbanne", "2026-10-23T20:00"),
         ("Zalgiris Kaunas", "Lyon-Villeurbanne", "одна сторона", False, "23.10 20:00"))
проверка("одна сторона, а вторая спорит и общего слова нет → None",
         ответ("Zalgiris Kaunas", "Real Madrid", "2026-10-23T20:00"), None)
проверка("вторая спорит буквами (22), слова общего нет: «FC Porto» → None",
         ответ("Zalgiris Kaunas", "FC Porto", "2026-10-23T20:00"), None)
КОРОТКОЕ = Reference([матч("F", "Al Hilal", "Al Ahli", "2026-10-23T20:00")])
проверка("короткое общее слово («Al») — не общее: «Al Hilal - Al Qadsiah» → None",
         ответ("Al Hilal", "Al Qadsiah", "2026-10-23T20:00", эталон=КОРОТКОЕ), None)
#: у Жальгириса в окне два матча, вторая сторона («ASVEL Villeurbanne»)
#: делит слово «Villeurbanne» с обоими соперниками
ДВА_МАТЧА = Reference([матч("B", "Zalgiris Kaunas", "Lyon-Villeurbanne", "2026-10-23T20:00"),
                       матч("B", "Zalgiris Kaunas", "Villeurbanne Sud", "2026-10-23T20:30")])
проверка("два кандидата с той же твёрдой стороной в окне → None",
         ответ("Zalgiris Kaunas", "ASVEL Villeurbanne", "2026-10-23T20:00",
               эталон=ДВА_МАТЧА), None)
проверка("тот же случай, кандидат в окне один → «одна сторона»",
         ответ("Zalgiris Kaunas", "ASVEL Villeurbanne", "2026-10-23T20:00",
               эталон=Reference([матч("B", "Zalgiris Kaunas", "Lyon-Villeurbanne",
                                      "2026-10-23T20:00")]))[2],
         "одна сторона")
проверка("теннис — только пара целиком: «Sinner - Medvedev» при Sinner — Alcaraz → None",
         ответ("Sinner J.", "Medvedev D.", "2026-10-22T15:00"), None)
проверка("теннис парой целиком — «пара»",
         ответ("Sinner J.", "Alcaraz C.", "2026-10-22T15:00")[2], "пара")
проверка("теннис: одна твёрдая сторона и вторая похожа буквами — всё равно None",
         ответ("Sinner J.", "Alcantara C.", "2026-10-22T15:00"), None)
проверка("тот же случай в футболе — «одна сторона» (стена только у тенниса)",
         ответ("Sinner J.", "Alcantara C.", "2026-10-22T15:00",
               эталон=Reference([матч("F", "Sinner J.", "Alcaraz C.", "2026-10-22T15:00")]))[2],
         "одна сторона")

print("(в) Reference.confirm — стена по полу и возрасту")
проверка("женская пара с мужским матчем → None",
         ответ("Poland W", "Belgium W", "2026-10-24T19:00"), None)
проверка("мужская пара с женским матчем → None",
         ответ("Poland", "Belgium", "2026-10-24T19:00",
               эталон=Reference([матч("F", "Poland W", "Belgium W", "2026-10-24T19:00")])), None)
проверка("мужская пара с мужским — «пара»",
         ответ("Poland", "Belgium", "2026-10-24T19:00")[2], "пара")
проверка("одна сторона: женская пара не цепляет мужской матч и по слову",
         ответ("Zalgiris Kaunas W", "ASVEL Villeurbanne W", "2026-10-23T20:00"), None)


# ═════════════════════════════════════════════════════════════════════════════
def строка(заголовок: str, когда: str, *, пара: str = "", эфир: str = "",
           описание: str = "", лига: str = "", эталон: Reference | None = ЭТАЛОН):
    program = Program(channel_raw="Тест Sport 1", title=заголовок,
                      start=момент(когда).replace(tzinfo=KYIV),
                      description=описание, league_raw=лига,
                      live_raw=эфир, match_raw=пара)
    return pipeline.classify(program, MARKERS, SPORTS, {}, {}, эталон)


print("(в) pipeline.classify — строку без пометки эфира спрашиваем у эталона")
row = строка("Levante - Ath Bilbao", "2026-10-21T21:00")
проверка("без маркера эфира, эталон знает пару → ok", (row.ok, row.reason), (True, ""))
проверка("by_reference = «пара»", row.by_reference, "пара")
проверка("эфир угаданный: live_guess в program.extra",
         row.program.extra.get("live_guess"), True)
проверка("маркер эфира — «эталон»", row.live_marker, pipeline.REFERENCE_MARKER)
проверка("вид спорта — от эталона (правило 2)", (row.sport, row.sport_rule), ("F", 2))
проверка("пара — имена сайта", (row.home, row.away), ("Levante", "Ath Bilbao"))
row = строка("Minnesota Timberwolves at Miami Heat", "2026-10-22T02:30")
проверка("« at » без маркера эфира: хозяева эталона первыми, вид B",
         (row.ok, row.home, row.away, row.sport),
         (True, "Miami Heat", "Minnesota Timberwolves", "B"))
row = строка("Levante - Ath Bilbao", "2026-10-21T21:00", эталон=None)
проверка("без эталона — отсев, как раньше",
         (row.ok, row.reason), (False, "нет маркера прямого эфира"))
row = строка("Levante - Ath Bilbao", "2026-10-21T18:00")
проверка("показ за 3 ч — эталон не спасает",
         (row.ok, row.reason), (False, "нет маркера прямого эфира"))

print("(в)+(г) «не видно пары команд» — пару даёт догадка, выбирает эталон")
row = строка("Al Nassr-Al Neom", "2026-10-20T21:00", эфир="live")
проверка("«Al Nassr-Al Neom» с live → ok", (row.ok, row.reason), (True, ""))
проверка("пара — из догадки (имена сайта)", (row.home, row.away), ("Al Nassr", "Al Neom"))
проверка("by_reference = «пара», маркер — честный «live»",
         (row.by_reference, row.live_marker), ("пара", "live"))
row = строка("Al Nassr-Al Neom", "2026-10-20T21:00", эфир="live", эталон=None)
проверка("без эталона — «не видно пары команд», как раньше",
         (row.ok, row.reason), (False, "не видно пары команд"))
row = строка("2. Bundesliga Live - Topspiel: 1. FC Nürnberg - 1. FC Kaiser",
             "2026-10-24T21:15")
проверка("рубрика rtl.de, вторая сторона обрезана → ok по одной стороне",
         (row.ok, row.by_reference, row.home), (True, "одна сторона", "1. FC Nürnberg"))
проверка("спасённая по одной стороне строка получает вид матча эталона",
         (row.sport, row.sport_rule), ("F", 2))

print("(в) прямые слова сайта эталон не оспаривает")
row = строка("Studio: Levante - Ath Bilbao", "2026-10-21T21:00", эфир="live")
проверка("стоп-слово «Studio» в заголовке — отсев, эталон не спрошен",
         (row.ok, row.reason.startswith("стоп-слово"), row.by_reference), (False, True, ""))
row = строка("Levante - Ath Bilbao", "2026-10-21T21:00", описание="Wiederholung")
проверка("слово записи «Wiederholung» — отсев, эталон не спрошен",
         (row.ok, row.reason.startswith("запись или студия"), row.by_reference),
         (False, True, ""))
проверка("…и live_guess не поставлен", row.program.extra.get("live_guess"), None)

print("(в) прошлый сезон в подписи — классика, эталон не спрашиваем")
когда = момент("2026-10-24T19:00")
проверка("«2003/04» в октябре 2026 — прошлый сезон",
         pipeline.past_season("Klasici Premijer Lige: Chelsea - Tottenham, 2003/04", когда), True)
проверка("«2025/26» в октябре 2026 — уже прошлый",
         pipeline.past_season("Finale 2025/26", когда), True)
проверка("«2025/26» в марте 2026 — ещё текущий",
         pipeline.past_season("Finale 2025/26", момент("2026-03-10T19:00")), False)
проверка("«(T26/27)» — не сезон из четырёх цифр, не прошлый",
         pipeline.past_season("UEFA Champions League (T26/27): Real Madrid - Leipzig", когда), False)
проверка("год основания «Grazer AK 1902» — не сезон",
         pipeline.past_season("WSG Tirol - Grazer AK 1902", когда), False)
проверка("«2026 WNBA Finals» — не прошлый",
         pipeline.past_season("2026 WNBA Finals: Valkyries at Dream", когда), False)
row = строка("Klasici: Levante - Ath Bilbao, 2003/04", "2026-10-21T21:00")
проверка("классика «2003/04» без маркера эфира — отсев, эталон не спрошен",
         (row.ok, row.reason, row.by_reference), (False, "нет маркера прямого эфира", ""))

print("(в) вид неясен — эталон решает только парой целиком")
row = строка("PSG - Lens", "2026-10-10T21:45", эфир="live")
проверка("«PSG - Lens» при эталонном «PSG - Le Mans»: вид не от эталона",
         (row.sport_rule != 2, row.by_reference), (True, ""))
row = строка("PSG - Le Mans", "2026-10-10T21:45", эфир="live")
проверка("«PSG - Le Mans» с live — вид от эталона (пара)", (row.sport, row.sport_rule), ("F", 2))

print()
print(f"проверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

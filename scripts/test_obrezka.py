# -*- coding: utf-8 -*-
r"""Книги 133 и 136 (15.11.2026): к паре снаружи прилипли лишние слова —
общее правило для ВСЕХ сайтов и языков и книга знаний.

Слова владельца 15.11: «все ошибки разбора, которые происходят на конкретных
сайтах, должны быть предусмотрены для всех сайтов»; «все варианты ошибок
должны накапливать опыт и решение для всего проекта»; «сайт должен проверить
через базу ошибок и решений».

Правила: `live.outer_trims` (1–5), `pipeline.trim_by_reference` (О1–О7),
`pipeline.trim_by_book` (Б1–Б3), `dictionary.note_trims` (З1–З4).
В сеть не ходит, база временная. Запуск: python scripts/test_obrezka.py
"""
from __future__ import annotations

import inspect
import json
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
TMP = Path(tempfile.mkdtemp(prefix="obrezka-test-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import db, dictionary, live, pipeline, site_lang  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import Confirmed, Reference  # noqa: E402
import games_import  # noqa: E402
import parse_live  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
T = datetime(2026, 11, 15, 19, 0)
зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


print("Срезы слов (`live.outer_trims`), правила 1–5")
проверка("правила 1–2: только начало хозяев и конец гостей, от меньшего среза к большему, потом оба края",
         live.outer_trims("Alfa Beta Gama", "Delta Epsilon"),
         [(live.TRIM_HOME, "Alfa", "Beta Gama", "Delta Epsilon"),
          (live.TRIM_HOME, "Alfa Beta", "Gama", "Delta Epsilon"),
          (live.TRIM_AWAY, "Epsilon", "Alfa Beta Gama", "Delta"),
          (live.TRIM_BOTH, "Alfa … Epsilon", "Beta Gama", "Delta"),
          (live.TRIM_BOTH, "Alfa Beta … Epsilon", "Gama", "Delta")])
проверка("правило 3: от стороны остаётся имя — пару из одиночных слов резать некуда",
         live.outer_trims("Sparta", "Slavia"), [])
длинная = live.outer_trims(" ".join(f"w{i}" for i in range(12)) + " Team", "Guest")
проверка(f"правило 3: с одного края — не больше {live.TRIM_WORDS} слов",
         max(len(cut.split()) for _w, cut, _h, _a in длинная), live.TRIM_WORDS)
проверка("правило 4: знаки с края урезанной стороны счищаются («ženy: Slovensko», «Italia -»)",
         (("ženy: Slovensko", "Srbsko") in [(h, a) for _w, _c, h, a in
                                           live.outer_trims("Kvalifikácia na ME 2027 ženy: Slovensko", "Srbsko")],
          [(h, a) for w, _c, h, a in live.outer_trims("Belgio", "Italia - 15/11/2026") if w == live.TRIM_AWAY]),
         (True, [("Belgio", "Italia"), ("Belgio", "Italia")]))
проверка("правило 5: теннисный дуэт не режем; косая черта в дате — не дуэт",
         (live.outer_trims("Marcel Granollers/Horacio Zeballos", "Simone Bolelli/Andrea Vavassori"),
          bool(live.outer_trims("Belgio", "Italia - 15/11/2026"))), ([], True))


class Эталон:
    """Вместо эталона: {(хозяева, гости): (матч, как сошлось, наоборот)};
    `known` — команды, которые он знает; что спросили — в `asked`."""

    def __init__(self, answers: dict, known=(), aware: bool = True):
        self.answers, self.known, self.aware = answers, set(known), aware
        self.asked: list[tuple[str, str]] = []

    def may_know(self, home, away):
        return self.aware

    def knows_team(self, name):
        return name in self.known

    def confirm(self, home, away, start, sport=""):
        self.asked.append((home, away))
        got = self.answers.get((home, away))
        if got is None:
            return None
        match, how, swapped = got
        entry = match if isinstance(match, dict) else {"fs_id": match}
        return Confirmed(entry=entry, start=start, how=how, swapped=swapped)


def срез(пары, эталон, **ещё):
    got = pipeline.trim_by_reference(пары, эталон, T, **ещё)
    return None if got is None else (got[0], got[1], got[3]["где"], got[3]["срезано"])


print("Срез по эталону (`pipeline.trim_by_reference`), правила О1–О7")
лига = ("Raiffeisen Liga e Pare Drita", "Liria")
проверка("О2–О3, О5: урезанная пара сошлась целиком — берём наименьший сошедшийся срез",
         срез([лига], Эталон({("Drita", "Liria"): ("m1", "пара", False),
                              ("Pare Drita", "Liria"): ("m1", "пара", False)})),
         ("Pare Drita", "Liria", live.TRIM_HOME, "Raiffeisen Liga e"))
проверка("О3: урезанная пара сошлась только «одной стороной» — не берём",
         срез([лига], Эталон({("Drita", "Liria"): ("m1", "одна сторона", False)})), None)
проверка("О3: разные срезы дали РАЗНЫЕ матчи — не гадаем",
         срез([лига], Эталон({("Drita", "Liria"): ("m1", "пара", False),
                              ("e Pare Drita", "Liria"): ("m2", "пара", False)})), None)
проверка("О4: эталон уже узнал строку «одной стороной» — срез обязан дать тот же матч",
         (срез([лига], Эталон({("Drita", "Liria"): ("m1", "пара", False)}),
               agree=Confirmed(entry={"fs_id": "m1"}, start=T, how="одна сторона")),
          срез([лига], Эталон({("Drita", "Liria"): ("m1", "пара", False)}),
               agree=Confirmed(entry={"fs_id": "другой"}, start=T, how="одна сторона"))),
         (("Drita", "Liria", live.TRIM_HOME, "Raiffeisen Liga e Pare"), None))
проверка("О5: эталон держит пару в обратном порядке — стороны в порядке эталона",
         срез([("Israel", "Österreich Das Spiel")],
              Эталон({("Israel", "Österreich"): ("m3", "пара", True)})),
         ("Österreich", "Israel", live.TRIM_AWAY, "Das Spiel"))
классика = Эталон({("Madrid", "Barcelona"): ("atletico", "пара", False)}, known={"Real Madrid"})
проверка("О6: сторону, которую эталон знает как команду, не режем («Real Madrid» не становится «Madrid»)",
         (срез([("Real Madrid", "Barcelona")], классика), классика.asked), (None, []))
шоу = Эталон({("Israel", "Österreich"): ("m3", "пара", False)})
проверка("О7: в срезанных словах стоп-слово передачи — срез не берём",
         (срез([("Israel", "Österreich Die Pre-Game Show")], шоу, stop=lambda words: "Pre-Game" in words),
          срез([("Israel", "Österreich Das Spiel")], шоу, stop=lambda words: "Pre-Game" in words)),
         (None, ("Israel", "Österreich", live.TRIM_AWAY, "Das Spiel")))
одно = Эталон({("Dallas", "Cleveland"): ("nba", "пара", False), ("Alcaraz", "Tiafoe"): ("atp", "пара", False)})
проверка("О8: одно слово без цифр по эталону не срезается («NBA», «Previo») — так выглядит часть имени",
         [срез([("NBA Dallas", "Cleveland")], одно), срез([("Previo Alcaraz", "Tiafoe")], одно)], [None, None])
проверка("О8: слово с цифрами — лишнее («15/11/2026»), оно срезается и в одиночку",
         срез([("Belgio", "Italia - 15/11/2026")], Эталон({("Belgio", "Italia"): ("bel", "пара", False)})),
         ("Belgio", "Italia", live.TRIM_AWAY, "15/11/2026"))
клуж = {"fs_id": "cluj", "home": "Cluj-Napoca", "away": "Maxima Roma",
        "names": {"ro": ["U-BT Cluj-Napoca", "Maxima Roma"]}}
проверка("О9: срезаемое слово похоже на слово имени команды в эталоне («UBT» — «U-BT») — это часть имени",
         (срез([("Baschet UBT Cluj", "Maxima Roma")], Эталон({("Cluj", "Maxima Roma"): (клуж, "пара", False)})),
          срез([("Cupa Europei Cluj", "Maxima Roma")], Эталон({("Cluj", "Maxima Roma"): (клуж, "пара", False)}))),
         (None, ("Cluj", "Maxima Roma", live.TRIM_HOME, "Cupa Europei")))
чужое = Эталон({}, aware=False)
проверка("слова пары эталону незнакомы (передача не про спорт) — эталон срезами не спрашиваем",
         (срез([("Kuchyně plná", "Vaříme s láskou")], чужое), чужое.asked), (None, []))

print("Срез по книге знаний (`pipeline.trim_by_book`), правила Б1–Б3")
книга = {pipeline.KNOWN_HOME: {"ligová fáze": frozenset({"cs", "sk"}), "liga e pare": frozenset({"sq"}),
                               "raiffeisen liga e pare": frozenset({"sq"})},
         pipeline.KNOWN_AWAY: {"das spiel": frozenset({"de"})}}
проверка("Б2: перед хозяевами срезается самая длинная известная цепочка, регистр не важен",
         pipeline.trim_by_book("RAIFFEISEN Liga e Pare Drita B", "Vushtrria", книга, frozenset({"sq", "en"}))[:2],
         ("Drita B", "Vushtrria"))
проверка("Б2: после гостей — с конца; оба края сразу",
         pipeline.trim_by_book("Ligová fáze Česko", "Gruzie Das Spiel", книга, None),
         ("Česko", "Gruzie", {"где": live.TRIM_BOTH, "срезано": "Ligová fáze … Das Spiel",
                              "было": "Ligová fáze Česko - Gruzie Das Spiel", "по": "книга"}))
проверка("Б1: слова другого языка сайту не годятся; языки сайта неизвестны — годятся любые",
         (pipeline.trim_by_book("ligová fáze Česko", "Gruzie", книга, frozenset({"it", "en"})),
          pipeline.trim_by_book("ligová fáze Česko", "Gruzie", книга, None)[:2]),
         (None, ("Česko", "Gruzie")))
проверка("Б3: от стороны должно остаться имя; резать нечего или книги нет — None",
         [pipeline.trim_by_book("ligová fáze", "Gruzie", книга, None),
          pipeline.trim_by_book("Sparta", "Slavia", книга, None),
          pipeline.trim_by_book("ligová fáze Česko", "Gruzie", {}, None)], [None, None, None])

print("Весь путь: строка сайта → общий конвейер (настоящий эталон)")
эталон = Reference([
    {"sport": "F", "home": "Finland", "away": "San Marino", "league": "EUROPE: UEFA Nations League",
     "fs_id": "fin", "start_kyiv": "2026-11-15T19:00", "names": {"cs": ["Finsko", "San Marino"]}},
    {"sport": "F", "home": "Belgium", "away": "Italy", "league": "EUROPE: UEFA Nations League",
     "fs_id": "bel", "start_kyiv": "2026-11-15T21:45", "names": {"it": ["Belgio", "Italia"]}},
    {"sport": "F", "home": "Atl. Madrid", "away": "Barcelona", "league": "SPAIN: LaLiga",
     "fs_id": "atl", "start_kyiv": "2026-11-15T22:00"},
    {"sport": "F", "home": "Real Madrid", "away": "Sevilla", "league": "SPAIN: LaLiga",
     "fs_id": "rma", "start_kyiv": "2026-11-16T22:00"},
])


def строка(сайт: str, пара: str, когда: str, эфир: str = "live"):
    p = Program(channel_raw="Канал 1", title=пара, start=datetime.fromisoformat(когда).replace(tzinfo=KYIV),
                raw_time="", match_raw=пара, live_raw=эфир, league_raw="", sport_raw="", source_url="",
                extra={})
    row = pipeline.run([p], reference=эталон, domain=сайт)[0]
    return row.home, row.away, (p.extra.get(pipeline.TRIMMED) or {}).get("по")


проверка("webtv.sk: «ligová fáze Finsko - San Marino» (стадия турнира перед хозяевами) → пара без неё, по эталону",
         строка("webtv.sk", "ligová fáze Finsko - San Marino", "2026-11-15T18:45"),
         ("Finsko", "San Marino", "эталон"))
проверка("raiplay.it: «Belgio - Italia - 15/11/2026» (дата после гостей) → пара без даты",
         строка("raiplay.it", "Belgio - Italia - 15/11/2026", "2026-11-15T21:30"),
         ("Belgio", "Italia", "эталон"))
проверка("О1: пара и так сходится целиком — правило её не трогает",
         строка("webtv.sk", "Finsko - San Marino", "2026-11-15T18:45"), ("Finsko", "San Marino", None))
проверка("О6 на живом эталоне: повтор «Real Madrid - Barcelona» в час матча «Atl. Madrid — Barcelona» не режется",
         строка("webtv.sk", "Real Madrid - Barcelona", "2026-11-15T22:00"),
         ("Real Madrid", "Barcelona", None))

print("Попутные находки сравнения на сборе 15.11")
from datetime import timedelta  # noqa: E402
from types import SimpleNamespace as NS  # noqa: E402


def игра(когда, *пары):
    записи = [NS(sport="F", home=h, away=a) for h, a in пары]
    return NS(start=когда, first=записи[0], entries=записи)


вчера = datetime(2026, 11, 15, 21, 30)
проверка("«поздний повтор»: пол и возраст — стена. Товарищеский U21 — не повтор вчерашнего матча взрослых сборных",
         [parse_live._looks_repeat(игра(вчера, ("Belgio", "Italia")),
                                   игра(вчера + timedelta(hours=22), ("Italia U21", "Belgio U21"))),
          parse_live._looks_repeat(игра(вчера, ("Belgio", "Italia")),
                                   игра(вчера + timedelta(hours=22), ("Italia", "Belgio")))], [False, True])
проверка("«поздний повтор»: у части сайтов пометки нет — повтор женского матча по-прежнему повтор",
         parse_live._looks_repeat(игра(вчера, ("Arsenal", "Chelsea"), ("Arsenal W", "Chelsea W")),
                                  игра(вчера + timedelta(hours=12), ("Arsenal W", "Chelsea W"))), True)
слова = live.load()


def стоп(сайт: str, заголовок: str) -> str:
    своё = слова.for_langs(site_lang.of(сайт))
    return своё.found(своё.stop_title, заголовок).lower()


проверка("предматчевые передачи — стоп-слова на языке своего сайта: Countdown, Previa, Previo, Štúdio",
         [стоп("tv.orf.at", "UEFA Nations League Spieltag 6 Gruppe B3: Israel - Österreich Der Countdown"),
          стоп("movistarplus.es", "La Casa del Fútbol Previa (T26/27): Athletic Club - RCD Espanyol de Barcelona"),
          стоп("movistarplus.es", "La pista del Tenis. Nitto ATP Finals (T2026): Previo Alcaraz - Tiafoe"),
          стоп("webtv.sk", "Štúdio Hokej")], ["countdown", "previa", "previo", "štúdio"])
проверка("сам матч стоп-словом не задет; испанское «previo» у немецкого сайта не ищется",
         [стоп("tv.orf.at", "UEFA Nations League Spieltag 6 Gruppe B3: Israel - Österreich Das Spiel"),
          стоп("movistarplus.es", "LALIGA EA SPORTS (T26/27): Athletic Club - RCD Espanyol de Barcelona"),
          стоп("tv.orf.at", "Previo Alcaraz - Tiafoe")], ["", "", ""])

print("Книга знаний (`dictionary.note_trims`), правила З1–З4")
db.init_db()
conn = db.connect()
итог_сбора = {"webtv.sk": [
    {"где": live.TRIM_HOME, "срезано": "ligová fáze", "по": "эталон", "раз": 4,
     "пример": "ligová fáze Finsko - San Marino → Finsko - San Marino"},
    {"где": live.TRIM_HOME, "срезано": "Liga majstrov", "по": "книга", "раз": 1, "пример": "x → y"}],
    "tv.orf.at": [{"где": live.TRIM_BOTH, "срезано": "Bundesliga … Das Spiel", "по": "эталон", "раз": 2,
                   "пример": "Bundesliga Rapid - Sturm Das Spiel → Rapid - Sturm"}]}
новых = dictionary.note_trims(conn, итог_сбора)
записи = {(r["alias"], r["class"]): (r["lang"], r["source_domain"], r["truth"]) for r in conn.execute(
    "SELECT * FROM dictionary_errors WHERE class IN (?, ?)", (live.KNOWN_HOME, live.KNOWN_AWAY))}
словацкий = " ".join(sorted(site_lang.of("webtv.sk") - {"en"}))
проверка("З1–З3: в книгу идут только срезы по эталону; срез с двух краёв — две строки; язык — языки сайта",
         (новых, записи),
         (3, {("ligová fáze", live.KNOWN_HOME): (словацкий, "webtv.sk", "Finsko - San Marino"),
              ("Bundesliga", live.KNOWN_HOME): ("de", "tv.orf.at", "Rapid - Sturm"),
              ("Das Spiel", live.KNOWN_AWAY): ("de", "tv.orf.at", "Rapid - Sturm")}))
проверка("З4: повторная встреча строк не плодит; битый вход не роняет",
         [dictionary.note_trims(conn, итог_сбора), dictionary.note_trims(conn, None),
          dictionary.note_trims(conn, {"a.tv": "x", "b.tv": [5, {"где": "?"}]})], [0, 0, 0])
файл = TMP / "dictionaries.json"
файл.write_text(json.dumps({"dictionary_errors": [
    {"alias": r["alias"], "lang": r["lang"], "class": r["class"]} for r in conn.execute(
        "SELECT alias, lang, class FROM dictionary_errors")] + [{"alias": "AEK", "class": "двусмысленно"}, 7]},
    ensure_ascii=False), encoding="utf-8")
известное = pipeline.known_trims(файл)
проверка("книга едет файлом словаря: разбор читает из него только свои классы; битая запись не роняет",
         (sorted(известное[pipeline.KNOWN_HOME]), sorted(известное[pipeline.KNOWN_AWAY]),
          известное[pipeline.KNOWN_AWAY]["das spiel"]), (["bundesliga", "ligová fáze"], ["das spiel"], frozenset({"de"})))
проверка("файла книги нет или он битый — правило молчит",
         [pipeline.known_trims(TMP / "нет.json"), pipeline.known_trims(TMP / "t.db")],
         [{pipeline.KNOWN_HOME: {}, pipeline.KNOWN_AWAY: {}}] * 2)
p = Program(channel_raw="Канал 1", title="ligová fáze Česko - Gruzie",
            start=datetime(2026, 11, 18, 20, 45, tzinfo=KYIV), raw_time="",
            match_raw="ligová fáze Česko - Gruzie", live_raw="live", league_raw="", sport_raw="",
            source_url="", extra={})
вердикт = pipeline.trim_over_pair(p, live.Verdict(True, "", live_marker="live", home="ligová fáze Česko", away="Gruzie"),
                                 эталон, datetime(2026, 11, 18, 20, 45), langs=site_lang.of("webtv.sk"),
                                 known=известное)
проверка("опыт работает дальше: матча эталон не знает, а слова уже в книге — пара идёт с чистыми именами",
         (вердикт.home, вердикт.away, p.extra[pipeline.TRIMMED]["по"]), ("Česko", "Gruzie", "книга"))
conn.close()

print("Подключение")
проверка("классы книги — одни и те же у разбора и у базы",
         (pipeline.KNOWN_HOME in dictionary.ERROR_CLASSES, pipeline.KNOWN_AWAY in dictionary.ERROR_CLASSES),
         (True, True))
проверка("разбор сбора считает срезы по сайтам в итог («обрезка»), заливка кладёт их в книгу знаний",
         ("pipeline.TRIMMED: {" in inspect.getsource(parse_live),
          "dictionary.note_trims(conn" in inspect.getsource(games_import)), (True, True))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

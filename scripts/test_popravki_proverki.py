# -*- coding: utf-8 -*-
r"""Книга 146 (16.11.2026): поправки по независимой проверке кода книг 138–144.

Проверяющий агент воспроизвёл запуском шестнадцать находок; здесь — по
проверке на каждую исправленную:
  1. теннисное правило брало строку-трансляцию турнира — словарь выучил бы
     слово «tournament» именем игрока (`canon.tennis_one_side`, Т1);
  2. …сводило запись другого матча и матч однофамильца (Т6, Т7);
  3. чистка лиги резала номер самой лиги и часть до «|» (`leagues._tail_off`);
  5. «WTA 125 Colina» со значком эфира снималась: эталон зовёт тур иначе
     (`broadcast.city`, `city_played`, `covered`);
  6. шаблон тура — кубический перебор на длинной серии пробелов;
  7. фильтр «грязные минуты» не знал пометку трансляции турнира;
  8. «две разные команды» книги знаний считались по буквам (`pipeline.book_rule`);
  9. греческий инициал читался как «D»/«B» и не у людей («Ν. Κορέα»);
 10. счётчик загрузки словаря; 11. база без новой колонки;
 12. примечание без точки съедало название женской лиги (`leagues.without_notes`);
 14. аудит звал разбор без признака «сайт эфир не помечает»;
 15. слова передач до и после матча — только в начале части заголовка
     (`live.lead_show`; проверки — в `test_peredachi_do_i_posle.py`).
В сеть не ходит, база временная. Запуск: python scripts/test_popravki_proverki.py
"""
from __future__ import annotations

import inspect
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="popravki-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import broadcast, canon, dictionary, leagues, live, names, pipeline, site_lang, sport  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import Reference  # noqa: E402
import audit_run  # noqa: E402
import dict_sync  # noqa: E402
import parse_live  # noqa: E402

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


def матч(home, away, start, league="ATP - SINGLES: Finals - Turin (World), hard (indoor)", **местные):
    return {"sport": "T", "home": home, "away": away, "start_kyiv": start, "fs_id": home[:3] + away[:3],
            "league": league, "names": местные}


ЭТАЛОН = [
    матч("Sabalenka A.", "Rybakina E.", "2026-11-15T15:00", "WTA - SINGLES: Finals - Indian Wells (World), hard",
         ru=["Соболенко А.", "Рыбакина Е."]),
    матч("Djokovic N.", "Zverev A.", "2026-11-15T19:00"),
    матч("Alcaraz C.", "Tiafoe F.", "2026-11-16T15:00", el=["Αλκαράζ Γκαρφία Κ. (Ισπ)", "Τιαφόε Φ. (Ηπα)"]),
    матч("Shelton B.", "Zverev A.", "2026-11-16T15:30"),
    матч("Cerundolo J. M.", "Paul T.", "2026-11-17T15:00"),
    матч("Cerundolo F.", "Ruud C.", "2026-11-17T17:10"),
]


def игрок(home, away, start):
    when = datetime.fromisoformat(start)
    near = [(r, datetime.fromisoformat(r["start_kyiv"])) for r in ЭТАЛОН
            if abs(datetime.fromisoformat(r["start_kyiv"]) - when) <= canon.WINDOW]
    got = canon.tennis_one_side({"sport": "T", "home": home, "away": away, "start_kyiv": start}, near, when)
    return None if got is None else got[0]["home"]


print("1–2. Теннисное правило (`canon.tennis_one_side`)")
проверка("Т1: строка-трансляция турнира (вторая сторона служебная) — не матч, даже если в заголовке назван игрок",
         [игрок("Теннис. WTA. Играет Арина Соболенко", broadcast.SESSION, "2026-11-15T15:00"),
          игрок("Nitto ATP Finals: Djokovic en directo", broadcast.SESSION, "2026-11-15T19:00"),
          игрок("ATP 500 Tokyo", "1/4 Finale", "2026-11-15T19:00")], [None, None, None])
проверка("Т7: вторая сторона латиницей и не похожа на эталон — другой игрок (запись старого матча), не берём",
         [игрок("Carlos Alcaraz", "Novak Djokovic", "2026-11-16T15:00"), игрок("Shelton", "Fils", "2026-11-16T15:30")],
         [None, None])
проверка("Т7 не мешает другой письменности: греческий перевод фамилии по-прежнему сводится",
         игрок("Κάρλος Αλκαράθ", "Φράνσις Τιαφό", "2026-11-16T15:00"), "Alcaraz C.")
проверка("Т6: фамилия без инициала подходит двум матчам рядом (братья) — не знаем, даже если в окне эфира один",
         [игрок("Cerundolo", "Ρουντ", "2026-11-17T15:00"), игрок("Cerundolo", "Ρουντ", "2026-11-17T17:10")],
         [None, None])
a = canon.align([{"sport": "T", "home": "WTA Finals Indian Wells", "away": broadcast.SESSION, "league": "",
                  "start_kyiv": "2026-11-15T15:00"}], ЭТАЛОН)
проверка("сверка: трансляция турнира в час матча остаётся трансляцией («мимо»), стороны не переставлены",
         (len(a["sure"]), a["missed"][0]["away"] if a["missed"] else None), (0, broadcast.SESSION))

print("3, 6. Хвост лиги (`leagues._tail_off`)")
проверка("число перед словом тура без порядкового знака — номер самой лиги",
         [leagues.clean(x) for x in ("Ligue 1 Journée 5", "Liga Portugal 2 Jornada 10", "Premier League 2 Matchday 3",
                                     "League 1 Round 5", "Division 1 Round 2", "ABA liga 2 kolo 3",
                                     "Ligue 1 - Journée 5")],
         ["Ligue 1", "Liga Portugal 2", "Premier League 2", "League 1", "Division 1", "ABA liga 2", "Ligue 1"])
проверка("ничего не срезано — название буква в букву (скобка в начале цела)",
         [leagues._tail_off(x) for x in ("(Parovi) 1/2 Finale", "LIVE | Serie A", "Liga Portugal 2")],
         ["(Parovi) 1/2 Finale", "LIVE | Serie A", "Liga Portugal 2"])
начало = time.perf_counter()
leagues.clean("Serie A" + " " * 3000 + "x")
проверка("длинная серия пробелов шаблон тура не вешает (меньше секунды на 3000 пробелов)",
         time.perf_counter() - начало < 1.0)

проверка("проверка на данных: тур стоял внутри скобки — скобка уходит целиком, незакрытой не остаётся",
         [leagues.clean(x) for x in ("Scottish Premiership (Nachholspiel, 12. Spieltag)",
                                     "AFC Champions League Two (Gruppenphase, 5. Spieltag): A - B")],
         ["Scottish Premiership", "AFC Champions League Two"])

print("5, 16. Турнир по городу, в любом туре (`broadcast.city`, `city_played`, `covered`)")
КОЛИНА = матч("A B.", "C D.", "2026-11-16T15:00", "CHALLENGER WOMEN - SINGLES: Colina (Chile), clay")
ШЛЕМЫ = [матч("A B.", "C D.", "2026-05-28T12:00", "ATP - SINGLES: French Open (France), clay"),
         матч("E F.", "G H.", "2026-05-28T12:00", "WTA - SINGLES: French Open (France), clay")]
известно = broadcast.tournaments([КОЛИНА], learned={})
проверка("«WTA 125 Colina»: по туру турнир «не идёт» (у эталона он Challenger), по городу — идёт",
         (broadcast.played(broadcast.key("WTA 125 Colina", известно), известно), broadcast.city("WTA 125 Colina", известно),
          broadcast.city_played("Colina", известно),
          broadcast.city_starts_near("Colina", datetime(2026, 11, 16, 15, 0), известно)),
         (False, "Colina", True, True))
шлем = broadcast.tournaments(ШЛЕМЫ, learned={"Paris": {"tours": ["ATP"], "words": ["paris", "париж"]}})
проверка("большой турнир без названного тура узнаётся по городу: «Roland Garros 2027 - Paris» — French Open из эталона",
         (broadcast.city("Roland Garros 2027 - Paris", шлем), broadcast.city("Теннис. Ролан Гаррос. Париж", шлем),
          broadcast.key("Roland Garros 2027 - Paris", шлем)), ("French Open", "French Open", ("", "")))
проверка("эталон судит о турнире только в днях, на которые у него есть теннисная сетка",
         [broadcast.covered(datetime(2026, 11, 16, 12, 0), известно), broadcast.covered(datetime(2026, 11, 19, 12, 0), известно),
          broadcast.covered(None, известно)], [True, False, False])
M, виды = live.load(), sport.load()
БОГАТЫЙ = Reference([КОЛИНА] + [матч(f"P{i} A.", f"R{i} B.", f"2026-11-16T{4 + i % 6:02d}:00",
                                     "CHALLENGER MEN - SINGLES: Sydney (Australia), hard") for i in range(40)])


def разбор(заголовок, when, выучено=None):
    broadcast._LEARNED = выучено or {}
    p = Program(channel_raw="SS5", title=заголовок, start=datetime(*when, tzinfo=KYIV), live_raw="live broadcast")
    try:
        return pipeline.classify(p, M, виды, reference=БОГАТЫЙ).ok
    finally:
        broadcast._LEARNED = None


ШАНХАЙ = {"Shanghai": {"tours": ["ATP"], "words": ["shanghai"]}}
проверка("«WTA 125 Colina» со значком эфира — берём; турнир, которого в эталоне нет, в днях с сеткой — запись, "
         "а дальше сетки — слову сайта верим",
         [разбор("WTA 125 Colina", (2026, 11, 16, 15, 0)), разбор("ATP Shanghai 2026", (2026, 11, 16, 15, 0), ШАНХАЙ),
          разбор("ATP Shanghai 2026", (2026, 11, 19, 15, 0), ШАНХАЙ)], [True, False, True])

УЭЛЛС = Reference([матч("Sabalenka A.", "Gauff C.", "2026-11-15T22:00", "WTA - SINGLES: Finals - Indian Wells (World), hard",
                        ru=["Соболенко А.", "Гауфф К."]),
                   {"sport": "F", "home": "Wales", "away": "India", "league": "WORLD: Friendly", "start_kyiv": "2026-11-15T21:00",
                    "names": {"ru": ["Уэльс", "Индия"]}}])
p = Program(channel_raw="Беларусь 5", title="Теннис. WTA. Итоговый турнир. Индиан-Уэллс. Финал. Прямая трансляция",
            start=datetime(2026, 11, 15, 22, 0, tzinfo=KYIV), live_raw="Прямая трансляция")
строка = pipeline.classify(p, M, виды, reference=УЭЛЛС, langs=site_lang.of("news.by"))
проверка("проверка на данных (news.by): город с дефисом — не пара игроков; прямой эфир финала идёт трансляцией турнира",
         (строка.ok, строка.away, p.extra.get(pipeline.TOURNAMENT, {}).get("город")),
         (True, broadcast.SESSION, "Finals - Indian Wells"))
de = M.for_langs(site_lang.of("tv.orf.at"))
проверка("проверка на данных (tv.orf.at): «… Israel - Österreich Die Analyse» — передача после матча, стоп-слово",
         de.found(de.stop_title, "UEFA Nations League Spieltag 6 Gruppe B3: Israel - Österreich Die Analyse").casefold(),
         "die analyse")
проверка("у сведённой трансляции турнира лига пустая, а не лига первого сайта",
         "r.league = \"\"" in inspect.getsource(parse_live))

print("7, 14. Фильтры сбора и аудит")
проверка("фильтр «грязные минуты» не снимает трансляцию турнира, подтверждённую эталоном; аудит передаёт разбору "
         "признак «сайт эфир не помечает»",
         ("or bool(((r.program.extra or {}).get(pipeline.TOURNAMENT) or {}).get(\"эталон\"))" in inspect.getsource(parse_live),
          inspect.getsource(audit_run).count("in parse_live.REPEAT_GUESS_DOMAINS)")), (True, 2))

print("8. Книга знаний: «две разные команды» — разные по сходству имён (`pipeline.book_rule`)")
проверка("одна команда, записанная по-разному, правилом слова не делает; две настоящие — делают",
         [pipeline.book_rule({"seen_with": x}) for x in (["Bydgoszcz", "Bydgoszcz W"], ["Brasov", "Brașov"],
                                                         ["Heart", "Hearts"], ["Finsko", "Finland"],
                                                         ["Finsko", "Lotyšsko"], ["Rapid", "LASK", "Rapid W"])],
         [False, False, False, False, True, True])

print("9. Греческий инициал — только после фамилии (`names._letter_readings`)")
проверка("буква в начале названия — не инициал человека: у «Ν. Κορέα» второго чтения «D KOREA» нет; игроки — сводятся",
         (names.readings("Ν. Κορέα") == ("N KOREA",), names.similarity("Ν. Ιωνία", "Dafni Ionia") < canon.SURE,
          names.similarity("Ντανιίλ Μεντβέντεφ", "Μεντβέντεφ Ν. (Κοσ)"), names.similarity("Μπεν Σέλτον", "Σέλτον Μ. (Ηπα)"),
          names.similarity("Μαρσέλο Αρέβαλο/Μέιτ Πάβιτς", "Αρεβάλο Μ./Πάβιτς Μ.")), (True, True, 100, 100, 100))

print("10–11. Словарь: счётчик загрузки и база без новой колонки")
старая = sqlite3.connect(":memory:")
старая.row_factory = sqlite3.Row
старая.execute("CREATE TABLE dictionary_errors (id INTEGER PRIMARY KEY, alias TEXT, lang TEXT, class TEXT)")
старая.execute("INSERT INTO dictionary_errors (alias, lang, class) VALUES ('Das Spiel', 'de', ?)", (live.KNOWN_AWAY,))
проверка("база до миграции (колонки `seen_with` нет) — запоминание команд молчит, а не падает; одна команда строкой "
         "— одна команда, не буквы",
         (dictionary.remember_beside(старая, "Das Spiel", live.KNOWN_AWAY, "de", ["Sturm"]),
          pipeline.seen_teams(["Finsko"])), (0, ["finsko"]))
проверка("счётчик «ошибок в книге» при загрузке словаря считает строки книги, а не раздел городов",
         "added[\"ошибок в книге\"] += 1\n    if isinstance(data.get(broadcast.LEARNED_KEY), dict)" in inspect.getsource(dict_sync.load))

print("12. Пол и примечание о другой передаче (`leagues.without_notes`)")
иврит = site_lang.of("sport5.co.il")
проверка("примечание в скобках или до запятой не съедает название женской лиги следом; поля строки разделены",
         [leagues.category("מכבי - הפועל (מיד בסיום כדורסל נשים) ליגת העל לנשים, מחזור 5", иврит),
          leagues.category("ליגה גרמנית: אולדנבורג - אלבה ברלין. השידור יחל מיד בסיום כדורסל נשים", иврит),
          leagues.category("אולדנבורג - אלבה. השידור יחל מיד בסיום כדורסל נשים | ליגת העל לנשים", иврит),
          "\" | \".join(x for x in (program.league_raw, program.title," in inspect.getsource(pipeline.classify)],
         ["W", "", "W", True])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

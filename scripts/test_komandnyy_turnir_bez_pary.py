# -*- coding: utf-8 -*-
r"""Книга 176 (22.11.2026): командный теннисный турнир без пары — одной строкой.

Жалоба владельца 22.11: «почему теннис не свёлся в одну строку?» — полуфинал
Кубка Дэвиса 27.11 17:00 стоял на витрине семью строками (#11568–#11570,
#11636–#11639): каждый сайт зовёт показ по-своему, пары ещё нет, в эталоне
полуфинала нет, а сведение по туру и городу (`broadcast.key`) командный
турнир не берёт. Правила:
  0. К0 (`broadcast.no_pair`): только строка без пары — показ матча («страна
     — страна и слово стадии») остаётся парой, его сводит эталон;
  1. К1–К3 (`broadcast.team_show`): название турнира ищется в заголовке, лиге
     и рубрике строки написаниями словаря лиг (`data/league_words.json`,
     книга 159) → строка получает имя «Davis Cup» и служебную сторону
     `broadcast.SESSION`; два разных турнира в одной строке — не сводим;
     лига — лига эталона, если она у турнира одна, иначе перевод словаря;
  2. `parse_live`: правило стоит после сведения по туру и городу, игра из
     сведённых строк уходит в итог с меткой `broadcast.MERGED`;
  3. `store.tournament_renamed`, 2в: прежняя строка базы под заголовком сайта
     получает сведённое имя только по метке файла; остальные строки той же
     минуты вливаются (`store._fold_title_twins`, книга 148);
  4. `broadcast.shows_stage`: стадию сведённой строки называют все живые
     заголовки вместе — самая ранняя; «Davis Cup Finals» — имя турнира.
В сеть не ходит, база временная. Запуск: python scripts/test_komandnyy_turnir_bez_pary.py
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="komandnyy-turnir-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import broadcast, db, store  # noqa: E402
import parse_live  # noqa: E402

зелёных = красных = 0
ДЕНЬ = (date.today() + timedelta(days=5)).isoformat()
ЧАСЫ = datetime.combine(date.today(), datetime.min.time()).replace(hour=12)
ЛИГА = "TEAMS - MEN: Davis Cup - World Group (World)"
ЭТАЛОН = [{"sport": "T", "league": ЛИГА, "home": "Italy", "away": "South Korea"},
          {"sport": "T", "league": "ATP - SINGLES: Finals - Turin (World), hard (indoor)", "home": "Sinner J.", "away": "Zverev A."},
          {"sport": "F", "league": "TEAMS - MEN: Not Tennis Cup", "home": "A", "away": "B"}]


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


print("1. Название командного турнира в заголовке сайта (`broadcast.team_show`, К1–К3)")
# заголовок + лига + рубрика строк полуфинала 27.11 17:00, как их отдали сайты (сборы 21–22.11)
ЖИВЫЕ = {
    "digisport.ro": "Tenis: Cupa Davis",
    "epg.cyta.com.cy": "Tennis: 2026 Davis Cup",
    "novasports.gr": "Τένις: Davis Cup 2026, Ημιτελικός",
    "sporttv.pt": "FINAL 8 - MEIA-FINAL TAÇA DAVIS",
    "tvarenasport.com": "Polufinale 1 DAVIS CUP",
    "ziggosport.nl": "Davis Cup Finals 2026:",
    "sport5.co.il": "גביע דיוויס - גמר: חצי גמר גביע דיוויס - גמר",
    "tvpassport.com": "Tennis: Coupe Davis 2026: Demi-finale: équipes à communiquer Coupe Davis",
    "teleman.pl": "Tenis: Puchar Davisa",
    "mediaklikk.hu": "Tenisz Davis Kupa, műsor, élő adásban",
}
проверка("К1: десять сайтов, десять написаний — одно название",
         {broadcast.team_show(текст, ЭТАЛОН)[0] for текст in ЖИВЫЕ.values()}, {"Davis Cup"})
проверка("К1: греческое без ударений, кириллица, иврит с другим написанием",
         [broadcast.team_show(t, None)[0] for t in ("ΚΥΠΕΛΛΟ ΝΤΕΙΒΙΣ", "Теннис. Кубок Дэвиса. Полуфинал", "גביע דייויס")],
         ["Davis Cup"] * 3)
проверка("К1: женский турнир и турниры без «TEAMS» в названии эталона",
         [broadcast.team_show(t, None) for t in ("Puchar Billie Jean King", "United Cup: Day 3", "Кубок Лейвера")],
         [("Billie Jean King Cup", "TEAMS - WOMEN: Billie Jean King Cup"), ("United Cup", "United Cup"),
          ("Laver Cup", "Laver Cup")])
проверка("К1: турнир, которого нет в словаре, узнаётся по названию из лиг эталона",
         broadcast.team_show("Tennis: Fed Masters Cup, day 2",
                             [{"sport": "T", "league": "TEAMS - MIXED: Fed Masters Cup - Finals"}]),
         ("Fed Masters Cup", "TEAMS - MIXED: Fed Masters Cup - Finals"))
проверка("К1: слово целиком — «Davis Cupid», стадия без названия турнира, турнир ATP — не командный турнир",
         [broadcast.team_show(t, ЭТАЛОН) for t in ("Davis Cupid Show", "Полуфинал 1", "ATP Finals Turin", "")],
         [("", "")] * 4)
проверка("К1: лига эталона другого вида спорта названием турнира не становится",
         broadcast.team_show("Not Tennis Cup", ЭТАЛОН), ("", ""))
проверка("К2: названы два разных турнира — не сводим",
         broadcast.team_show("Davis Cup & Billie Jean King Cup: preview", ЭТАЛОН), ("", ""))
проверка("К3: лига — лига эталона, когда она у турнира одна", broadcast.team_show("Tenis: Cupa Davis", ЭТАЛОН)[1], ЛИГА)
проверка("К3: эталон турнир не ведёт — перевод словаря", broadcast.team_show("Tenis: Cupa Davis", [])[1],
         "TEAMS - MEN: Davis Cup")
проверка("К3: эталон зовёт турнир двумя лигами — перевод словаря",
         broadcast.team_show("Tenis: Cupa Davis", ЭТАЛОН + [{"sport": "T", "league": ЛИГА + " - Qualifications"}])[1],
         "TEAMS - MEN: Davis Cup")

print("1б. Только строка без пары (`broadcast.no_pair`, К0)")
проверка("служебная вторая сторона и две стороны из слов турнира и стадии — пары нет",
         [broadcast.no_pair("Polufinale 1", broadcast.SESSION), broadcast.no_pair("FINAL 8", "MEIA-FINAL")], [True, True])
проверка("страна и страна со словом стадии (port.hu, четвертьфинал 26.11) — показ матча, не трогаем",
         broadcast.no_pair("Ausztria", "Spanyolország negyeddöntő"), False)
проверка("игрок и слово стадии, пустые стороны — не строка турнира",
         [broadcast.no_pair("Alcaraz C.", "Final"), broadcast.no_pair("", broadcast.SESSION), broadcast.no_pair("", "")],
         [False, False, False])

print("2. Место правила в разборе (`parse_live`)")
код = inspect.getsource(parse_live)
блок = код[код.index("known_tournaments = broadcast.tournaments(reference_full)"):]
проверка("детектор: сначала сведение по туру и городу, потом командный турнир",
         0 < блок.index("broadcast.tournament(заголовок, known_tournaments)")
         < блок.index("broadcast.team_show(заголовок, reference_full)"))
проверка("детектор: командный турнир ищется только у строки без пары",
         "if broadcast.no_pair(r.home, r.away) else" in блок)
проверка("детектор: строка командного турнира получает название и служебную сторону",
         "r.home, r.away = командный, broadcast.SESSION" in блок)
проверка("детектор: игра из сведённых строк уходит в итог с меткой",
         "{broadcast.MERGED: 1}" in код and "сведённые_строки.add(id(r))" in блок)

print("3. Заливка: семь строк одной минуты становятся одной (`store.tournament_renamed`, 2в)")
САЙТЫ = ("digisport.ro", "epg.cyta.com.cy", "novasports.gr", "sporttv.pt", "nova.bg", "tvarenasport.com",
         "ziggosport.nl", "sport5.co.il", "tvpassport.com")


def игра(home, away, строки, час="17:00", league="", сведена=False):
    запись = {"sport": "T", "league": league, "home": home, "away": away,
              "start_kyiv": f"{ДЕНЬ}T{час}", "start_utc": f"{ДЕНЬ}T15:00",
              "entries": [{"source": сайт, "channel": канал, "url": "", "raw_title": заголовок}
                          for сайт, канал, заголовок in строки]}
    if сведена:
        запись[broadcast.MERGED] = 1
    return запись


def новая_база():
    path = TMP / f"t{len(list(TMP.glob('*.db')))}.db"
    os.environ["STREAMS_DB"] = str(path)
    db.init_db()
    conn = db.connect()
    for n, домен in enumerate(САЙТЫ, 1):
        conn.execute("INSERT INTO sources (id, domain, name, base_url, country, enabled) VALUES (?, ?, ?, ?, 'XX', 1)",
                     (n, домен, домен, f"https://{домен}/"))
    conn.commit()
    return conn


def события(conn):
    return [(r["team_home_auto"], r["team_away_auto"], r["n"]) for r in conn.execute(
        "SELECT e.team_home_auto, e.team_away_auto, COUNT(ec.id) AS n FROM events e "
        "LEFT JOIN event_channels ec ON ec.event_id = e.id GROUP BY e.id ORDER BY e.id")]


# база сервера 22.11: семь строк полуфинала, как их завели сборы 21.11 и 22.11
БЫЛО = [
    ("tenis Tenis Final 8 – semifinale Tenis: Cupa Davis", broadcast.SESSION, [("digisport.ro", "Digi Sport 2", "Tenis: Cupa Davis")]),
    ("Tennis: 2026 Davis Cup", broadcast.SESSION, [("epg.cyta.com.cy", "Novasports 6 HD", "Tennis: 2026 Davis Cup"),
                                                   ("novasports.gr", "Novasports 6", "Τένις: Davis Cup 2026, Ημιτελικός")]),
    ("FINAL 8", "MEIA-FINAL", [("sporttv.pt", "SPORT.TV6", "FINAL 8 - MEIA-FINAL")]),
    ("Polufinale 1", broadcast.SESSION, [("nova.bg", "Nova Sport", "Полуфинал 1"),
                                         ("tvarenasport.com", "Arena Tenis", "Polufinale 1")]),
    ("Davis Cup Finals 2026:", broadcast.SESSION, [("ziggosport.nl", "Ziggo Sport 4", "Davis Cup Finals 2026:")]),
    ("גביע דיוויס - גמר: חצי גמר", broadcast.SESSION, [("sport5.co.il", "Sport 5 Live", "גביע דיוויס - גמר: חצי גמר")]),
    ("Tennis: Coupe Davis 2026: Demi-finale: équipes à communiquer", broadcast.SESSION,
     [("tvpassport.com", "TVA Sports 2", "Tennis: Coupe Davis 2026: Demi-finale: équipes à communiquer")]),
]
ВСЕ_СТРОКИ = [строка for _h, _a, строки in БЫЛО for строка in строки]
conn = новая_база()
for home, away, строки in БЫЛО:
    store.save_games(conn, [игра(home, away, строки)], now=ЧАСЫ, punish=False)
проверка("до заливки в базе семь строк одной минуты", len(события(conn)), 7)
stats = store.save_games(conn, [игра("Davis Cup", broadcast.SESSION, ВСЕ_СТРОКИ, league=ЛИГА, сведена=True)],
                         now=ЧАСЫ, punish=False)
проверка("после сбора строка одна, с названием турнира и всеми девятью отметками; шесть двойников влиты",
         (события(conn), stats.titles_folded), ([("Davis Cup", broadcast.SESSION, 9)], 6))
проверка("лига строки — из файла", conn.execute("SELECT league_auto FROM events").fetchone()[0], ЛИГА)
store.save_games(conn, [игра("Davis Cup", broadcast.SESSION, ВСЕ_СТРОКИ, league=ЛИГА, сведена=True)], now=ЧАСЫ, punish=False)
проверка("следующий сбор садится в ту же строку по имени — второй не заводит",
         события(conn), [("Davis Cup", broadcast.SESSION, 9)])
store.save_games(conn, [игра("Полуфинал 1", broadcast.SESSION, [("nova.bg", "Nova Sport", "Полуфинал 1")])],
                 now=ЧАСЫ, punish=False)
проверка("2в: точечный обход с неузнанным заголовком (без метки файла) строку обратно не переименовывает",
         события(conn), [("Davis Cup", broadcast.SESSION, 9)])
conn.close()


class Строка(dict):
    """Игра базы для проверки правила без заливки."""


сведённая = игра("Davis Cup", broadcast.SESSION, [], сведена=True)
проверка("2в: строка турнира под заголовком сайта → да; уже с этим именем → нет; с меткой эталона → нет; "
         "без метки файла → нет",
         [store.tournament_renamed(сведённая, Строка(team_home_auto="Polufinale 1", team_away_auto=broadcast.SESSION, flags=None)),
          store.tournament_renamed(сведённая, Строка(team_home_auto="Davis Cup", team_away_auto=broadcast.SESSION, flags=None)),
          store.tournament_renamed(сведённая, Строка(team_home_auto="Polufinale 1", team_away_auto=broadcast.SESSION, flags="fs:abc")),
          store.tournament_renamed(игра("Davis Cup", broadcast.SESSION, []),
                                   Строка(team_home_auto="Polufinale 1", team_away_auto=broadcast.SESSION, flags=None))],
         [True, False, False, False])
проверка("прежние правила книг 145 и 149 целы: заголовок, разрезанный по тире, и пара стран",
         [store.tournament_renamed(игра("ATP Finals Turin", broadcast.SESSION, []),
                                   Строка(team_home_auto="ATP", team_away_auto="Nitto ATP Finals", flags=None)),
          store.tournament_renamed(игра("Billie Jean King Cup", broadcast.SESSION, []),
                                   Строка(team_home_auto="Polska", team_away_auto="Szwecja", flags=None)),
          store.tournament_renamed(игра("Billie Jean King Cup", broadcast.SESSION, []),
                                   Строка(team_home_auto="Alcaraz C.", team_away_auto="Tiafoe F.", flags=None))],
         [True, True, False])

print("4. Стадия сведённой строки (`broadcast.shows_stage`)")
ЗАГОЛОВКИ = [заголовок for _с, _к, заголовок in ВСЕ_СТРОКИ]
проверка("правила 2 и 3: «Davis Cup Finals 2026:» первым — всё равно полуфинал",
         broadcast.shows_stage("Davis Cup", ["Davis Cup Finals 2026:"] + ЗАГОЛОВКИ, None), "Semifinals")
проверка("правило 2: один «Davis Cup Finals 2026:» — стадии нет",
         broadcast.shows_stage("Davis Cup", ["Davis Cup Finals 2026:", "Tenis: Cupa Davis"], None), "")
проверка("настоящий финал называется финалом",
         broadcast.shows_stage("Davis Cup", ["Davis Cup Finals 2026: Final", "FINAL 8 - FINAL", "Tenis: Cupa Davis"], None),
         "Final")
проверка("правило 3: четвертьфинал раньше слова «Final 8»",
         broadcast.shows_stage("Davis Cup", ["FINAL 8", "FINAL 8 - CHÉQUIA X CANADÁ - 1/4 FINAL"], None), "Quarterfinals")
проверка("правило 4: никто стадию не назвал — пусто", broadcast.shows_stage("Davis Cup", ["Tenis: Puchar Davisa", ""], None), "")
известные = broadcast.tournaments(None)
проверка("турнир ATP: имя турнира по-прежнему не стадия, финал в день финала — стадия (книги 138 и 160)",
         [broadcast.shows_stage("ATP Finals Turin", ["Nitto ATP Finals", "ATP Finals"], известные),
          broadcast.shows_stage("ATP Finals Turin", ["Nitto ATP Finals", "ATP FINALS 2026 - FINAL"], известные)],
         [broadcast.show_stage("ATP Finals Turin", "Nitto ATP Finals", известные),
          broadcast.show_stage("ATP Finals Turin", "ATP FINALS 2026 - FINAL", известные)])
проверка("детектор: витрина зовёт `shows_stage`",
         "broadcast.shows_stage(home_shown, live_titles, known_titles)" in inspect.getsource(store.schedule))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

# -*- coding: utf-8 -*-
r"""Классификатор словаря команд (шаг 4 карточки словаря 09.11.2026) на
временной базе и маленьком каталоге flashscore. Одно правило — один блок.

  С6 (decide) отсеивает: тёзки по виду, игравшие между собой, голое имя AEK,
       игрок и клуб — не сливать;
  Ф0 хвост WO у теннисной пары — сливать;
  Ф1 виды известны и не пересекаются (Oldenburg B / VfB Oldenburg F) — нет;
  Ф2 одно имя после нормализации (Lech Poznań / Lech Poznan) — сливать в
     написание flashscore; имя flashscore у нескольких стран (Platense) — поиск;
  Ф3 две команды flashscore (Rangers / Rangers FC) — НЕ сливать;
  Ф4 перевод flashscore («ADO Den Haag» de → Den Haag; «Wisła Kraków» → Wisla) —
     сливать в имя flashscore; перевод другого клуба (Wisła Płock) — нет;
     перевод женской команды (Wisla Krakow W) не мешает мужской; имя у
     нескольких стран (Rangers) — поиск;
  Ф5 оба — переводы одного имени — сливать;
  Ф6 нет на flashscore (Al Taawoun, Arenal, Fukushima) — книга «возможный
     дубль» + список «на поиск»; решение поиска «один клуб» (Gornik) — сливать;
  К2 переезд написаний и событий, merged_into, книга «слито» с причиной;
  П1 «Βράμπλε - Ζβόλεν» у Zvolen — обрывок пары; П2 Genoa - Milan, «Ла Дюшер -
     Ним» — пара, карантин; П3 «Banik Most - Sous», «Фльори – Мерожи» — команды;
     П4 «Лион - Ла Дюшер», неизвестная пара — поиск, решение поиска «пара» — карантин;
  Кл1 «Spartak Subotica» (hu) — перевод flashscore «Sp. Subotica»: своё;
  Кл3 «Bayer Leverkusen» у Bayern Munich — карантин; Кл4 неизвестные — поиск;
  К6 второй прогон: 0 новых строк книги, 0 переездов (С7);
  ничего не удалено: строк team_aliases и teams столько же.

Запуск: venv\Scripts\python.exe scripts\test_slovar_klassifikator.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="slovar-klass-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")

from app import db, dictionary  # noqa: E402
import fs_katalog  # noqa: E402
import slovar_klassifikator as K  # noqa: E402

total = green = 0


def check(name: str, ok: bool, got=None) -> None:
    global total, green
    total += 1
    green += bool(ok)
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"   ← {got!r}"))


conn = db.connect()
db.init_db(conn)
R = dictionary.remember_team


def team(name: str) -> int:
    return conn.execute("SELECT id FROM teams WHERE canonical_name = ?", (name,)).fetchone()[0]


def event(home: int, away: int, sport: str = "F", league: int | None = None,
          flags: str | None = None) -> int:
    return conn.execute(
        "INSERT INTO events (sport, league_id, team_home_id, team_away_id, flags, "
        "start_utc, start_kyiv) VALUES (?, ?, ?, ?, ?, '2026-11-09 18:00:00', "
        "'2026-11-09 20:00:00')", (sport, league, home, away, flags)).lastrowid


def merged(name: str) -> int | None:
    return conn.execute("SELECT merged_into FROM teams WHERE canonical_name = ?",
                        (name,)).fetchone()[0]


# ── маленький каталог flashscore (как из истории эталона) ───────────────────
kat = fs_katalog.Katalog(min_games=1)        # в учебном каталоге каждая игра одна
for g in [
    {"sport": "F", "home": "Lech Poznan", "away": "Legia", "league": "POLAND: Ekstraklasa",
     "names": {"ru": ["Лех Познань", "Легия"]}},
    {"sport": "F", "home": "Rangers", "away": "Celtic", "league": "SCOTLAND: Premiership",
     "names": {"de": ["Rangers Glasgow", "Celtic Glasgow"]}},
    {"sport": "F", "home": "Rangers", "away": "Colo Colo", "league": "CHILE: Primera Division"},
    {"sport": "F", "home": "Rangers FC", "away": "Mbabane Swallows", "league": "ESWATINI: Premier League"},
    {"sport": "F", "home": "Den Haag", "away": "Ajax", "league": "NETHERLANDS: Eredivisie",
     "names": {"de": ["ADO Den Haag", "Ajax Amsterdam"]}},
    {"sport": "B", "home": "Oldenburg", "away": "Bamberg", "league": "GERMANY: BBL"},
    {"sport": "F", "home": "VfB Oldenburg", "away": "Meppen", "league": "GERMANY: Regionalliga"},
    {"sport": "F", "home": "Gornik Zabrze", "away": "Legia", "league": "POLAND: Ekstraklasa"},
    {"sport": "F", "home": "Al Taawon", "away": "Al Hilal", "league": "SAUDI ARABIA: Saudi Pro League"},
    {"sport": "F", "home": "Arsenal", "away": "Chelsea", "league": "ENGLAND: Premier League",
     "names": {"ru": ["Арсенал", "Челси"], "el": ["Άρσεναλ", "Τσέλσι"]}},
    {"sport": "F", "home": "Genoa", "away": "Milan", "league": "ITALY: Serie A"},
    {"sport": "F", "home": "La Duchere", "away": "Nimes", "league": "FRANCE: National 2",
     "names": {"ru": ["Ла Дюшер", "Ним"]}},
    {"sport": "F", "home": "Banik Most - Sous", "away": "Usti", "league": "CZECH REPUBLIC: CFL"},
    {"sport": "F", "home": "Bayer Leverkusen", "away": "Bayern Munich", "league": "GERMANY: Bundesliga"},
    {"sport": "F", "home": "Sp. Subotica", "away": "Partizan", "league": "SERBIA: Super Liga",
     "names": {"hu": ["Spartak Subotica", "Partizan"]}},
    {"sport": "B", "home": "Spartak Subotica", "away": "Cholet", "league": "EUROPE: Champions League"},
    {"sport": "F", "home": "Wisla", "away": "Legia", "league": "POLAND: Ekstraklasa",
     "names": {"pl": ["Wisła Kraków", "Legia Warszawa"], "ru": ["Висла Краков", "Легия"]}},
    {"sport": "B", "home": "Wisla Krakow W", "away": "Lublin W", "league": "POLAND: Basket Liga Kobiet",
     "names": {"pl": ["Wisła Kraków", "Lublin"]}},
    {"sport": "F", "home": "Wisla Plock", "away": "Legia", "league": "POLAND: Ekstraklasa",
     "names": {"pl": ["Wisła Płock", "Legia Warszawa"]}},
    {"sport": "F", "home": "Platense", "away": "Boca", "league": "ARGENTINA: Liga Profesional"},
    {"sport": "F", "home": "Platense", "away": "Olimpia", "league": "HONDURAS: Liga Nacional"},
    {"sport": "F", "home": "Lech Poznan", "away": "Rangers", "league": "EUROPE: Europa League"},
    # обрывок: греческое зеркало разрезало «Ζλάτε Μόραφτσε - Βράμπλε - Ζβόλεν» по первому тире
    {"sport": "F", "home": "Z. Moravce-Vrable", "away": "Zvolen", "league": "SLOVAKIA: 2. liga",
     "names": {"el": ["Ζλάτε Μόραφτσε", "Βράμπλε - Ζβόλεν"]}},
    {"sport": "F", "home": "Zvolen", "away": "Petrzalka", "league": "SLOVAKIA: 2. liga",
     "names": {"el": ["Ζβόλεν", "Περτζάλκα"]}},
    {"sport": "F", "home": "Fleury-Merogis", "away": "Lyon - La Duchere", "league": "FRANCE: National 2",
     "names": {"bg": ["Фльори – Мерожи", "Лион - Ла Дюшер"]}},
    {"sport": "F", "home": "Lyon", "away": "Nimes", "league": "FRANCE: Ligue 1",
     "names": {"bg": ["Лион", "Ним"]}},
    # обрывок в английском эталоне: «La Duchere - Feurs» — на деле пара
    {"sport": "F", "home": "La Duchere - Feurs", "away": "Moulins", "league": "FRANCE: National 3",
     "names": {"el": ["Λα Ντουσέρ - Φερ", "Μουλέν"]}},
    {"sport": "F", "home": "Feurs", "away": "Moulins", "league": "FRANCE: National 3"},
    {"sport": "F", "home": "Lyon", "away": "La Duchere - Toulon", "league": "FRANCE: National 2"},
    {"sport": "F", "home": "Banik Most - Sous B", "away": "Louny", "league": "CZECH REPUBLIC: Divize B"},
    {"sport": "F", "home": "Banik Most - Sous W", "away": "Slavia W", "league": "CZECH REPUBLIC: 1. liga zeny"},
    {"sport": "F", "home": "Napoli", "away": "Bologna", "league": "ITALY: Serie A"},
    {"sport": "F", "home": "Al Shabab", "away": "Al Hilal", "league": "SAUDI ARABIA: Saudi Pro League"},
    {"sport": "F", "home": "Al-Shabab", "away": "Dhofar", "league": "OMAN: Professional League"},
    {"sport": "F", "home": "Gijon", "away": "Sporting", "league": "SPAIN: LaLiga2",
     "names": {"es": ["Sporting Gijón", "Sporting"]}},
    {"sport": "F", "home": "Sporting", "away": "Dakota", "league": "ARUBA: Division di Honor"},
]:
    kat.add_game(g)

# ── правила Ф, П, Кл по отдельности ─────────────────────────────────────────
V = K.fs_verdict
check("Ф-к2 турнир части света — не страна (у Lech Poznan только POLAND)",
      kat.countries_of("Lech Poznan") == {"POLAND"}, kat.countries_of("Lech Poznan"))
check("Ф1 виды не пересекаются — разные", V(kat, "Oldenburg", "VfB Oldenburg", {"B"}, {"F"})[0] == K.РАЗНЫЕ)
check("Ф2 одно имя — сливать в написание flashscore",
      V(kat, "Lech Poznań", "Lech Poznan", set(), set())[::2] == (K.СЛИВАТЬ, "lech poznan"),
      V(kat, "Lech Poznań", "Lech Poznan", set(), set()))
check("Ф2 имя flashscore у нескольких стран (Platense) — поиск",
      V(kat, "Platense", "Platense (Arg)", set(), set())[0] == K.ПОИСК)
check("Ф2а Al Shabab / Al-Shabab — у flashscore оба написания: поиск",
      V(kat, "Al Shabab", "Al-Shabab", set(), set())[0] == K.ПОИСК, V(kat, "Al Shabab", "Al-Shabab", set(), set()))
check("Ф3 Rangers / Rangers FC — у flashscore две команды, не сливать",
      V(kat, "Rangers", "Rangers FC", set(), set())[0] == K.РАЗНЫЕ)
check("Ф4 «Wisła Kraków» — перевод Wisla: сливать (женская Wisla Krakow W не мешает)",
      V(kat, "Wisla", "Wisła Kraków", set(), set())[::2] == (K.СЛИВАТЬ, "wisla"),
      V(kat, "Wisla", "Wisła Kraków", set(), set()))
check("Ф4 «Wisła Płock» — перевод другого клуба: не сливать с Wisla",
      V(kat, "Wisla", "Wisła Płock", set(), set())[0] == K.РАЗНЫЕ)
check("Ф4 «Rangers Glasgow» — перевод, но Rangers у двух стран: поиск",
      V(kat, "Rangers", "Rangers Glasgow", set(), set())[0] == K.ПОИСК)
check("Ф4 перевод того же имени, но наш вид другой (B) — не сливать",
      V(kat, "Wisla", "Wisła Kraków", set(), {"B"})[0] in (K.РАЗНЫЕ, K.ПОИСК))
check("Ф5 оба — переводы одного имени flashscore — сливать",
      V(kat, "Wisła Kraków", "Висла Краков", set(), set())[0] == K.СЛИВАТЬ)
check("Ф6 обоих нет на flashscore — поиск", V(kat, "Fukushima", "Fukushima Utd", set(), set())[0] == K.ПОИСК)
check("Ф0 хвост WO — сливать", V(kat, "A B./C D.", "A B./C D. WO", set(), set(), tails=True)[0] == K.СЛИВАТЬ)
check("П1 «Βράμπλε - Ζβόλεν» у Zvolen — обрывок пары (половина — сам Zvolen)",
      K.pair_verdict(kat, "Βράμπλε - Ζβόλεν", "Zvolen")[0] == "пара", K.pair_verdict(kat, "Βράμπλε - Ζβόλεν", "Zvolen"))
check("П2 «Genoa - Milan» у Filler — пара", K.pair_verdict(kat, "Genoa - Milan", "Filler")[0] == "пара")
check("П2 «Ла Дюшер - Ним» — пара по переводам",
      K.pair_verdict(kat, "Ла Дюшер - Ним", "La Duchere - Nimes")[0] == "пара")
check("П3 «Banik Most - Sous» — имя команды flashscore, половины не команды: не пара",
      K.pair_verdict(kat, "Banik Most - Sous", "Banik Most - Sous")[0] == "команда")
check("П3 «Фльори – Мерожи» у Fleury-Merogis — перевод имени с тире: не пара",
      K.pair_verdict(kat, "Фльори – Мерожи", "Fleury-Merogis")[0] == "команда",
      K.pair_verdict(kat, "Фльори – Мерожи", "Fleury-Merogis"))
check("П4 «Лион - Ла Дюшер» у Lyon - La Duchere — половины тоже клубы: поиск",
      K.pair_verdict(kat, "Лион - Ла Дюшер", "Lyon - La Duchere")[0] == K.ПОИСК,
      K.pair_verdict(kat, "Лион - Ла Дюшер", "Lyon - La Duchere"))
check("П4 неизвестная пара — поиск", K.pair_verdict(kat, "Foo - Bar", "Filler")[0] == K.ПОИСК)
check("Кл1 «Spartak Subotica» — перевод flashscore «Sp. Subotica»: своё",
      K.collision_verdict(kat, "Spartak Subotica", "Sp. Subotica", "Spartak Subotica")[0] == "своё")
check("Кл3 «Bayer Leverkusen» у Bayern Munich — чужое",
      K.collision_verdict(kat, "Bayer Leverkusen", "Bayern Munich", "Bayer Leverkusen")[0] == "чужое")
check("Кл3а «Sporting» у Gijon (там же «Sporting Gijon») — короткая форма: поиск",
      K.collision_verdict(kat, "Sporting", "Gijon", "Sporting", ["Gijon", "Sporting Gijón", "Sporting"])[0] == K.ПОИСК)
check("Кл3 «Bayer Leverkusen» у Bayern Munich при чужом «Bayer 04 Leverkusen» там же — всё равно чужое",
      K.collision_verdict(kat, "Bayer Leverkusen", "Bayern Munich", "Bayer Leverkusen",
                          ["Bayern Munich", "Bayer 04 Leverkusen"])[0] == "чужое")
check("П2б «Λα Ντουσέρ - Φερ» у La Duchere - Feurs — La Duchere с разными соперниками: пара",
      K.pair_verdict(kat, "Λα Ντουσέρ - Φερ", "La Duchere - Feurs")[0] == "пара",
      K.pair_verdict(kat, "Λα Ντουσέρ - Φερ", "La Duchere - Feurs"))
check("П2б составы одного клуба (Sous, Sous B, Sous W) — не серия: Banik Most - Sous B не пара",
      K.pair_verdict(kat, "Banik Most - Sous B", "Banik Most - Sous B")[0] != "пара",
      K.pair_verdict(kat, "Banik Most - Sous B", "Banik Most - Sous B"))
check("П1 кавычки в половинах не мешают: Italijos lyga. \"Napoli\" - \"Bologna у Bologna — пара",
      K.pair_verdict(kat, 'Italijos lyga. "Napoli" - "Bologna', "Bologna")[0] == "пара",
      K.pair_verdict(kat, 'Italijos lyga. "Napoli" - "Bologna', "Bologna"))
check("Кл4 неизвестные — поиск", K.collision_verdict(kat, "Zeta", "Alpha Club", "Zeta")[0] == K.ПОИСК)
check("решение поиска: ключ слияния не зависит от порядка имён",
      K.poisk_key("слияние", "Gornik", "Gornik Zabrze") == K.poisk_key("слияние", "Gornik Zabrze", "Gornik"))

# ── Ф-к5: перевод — только из двух и больше разных игр; перестановка сторон ──
k2 = fs_katalog.Katalog()                         # порог по умолчанию — 2 игры
k2.add_game({"sport": "F", "home": "Congo U20", "away": "Gabon U20", "league": "AFRICA: U20",
             "fs_id": "g1", "names": {"sv": ["Gabon U20", "Congo U20"]}})        # зеркало переставило
k2.add_game({"sport": "F", "home": "Wisla", "away": "Legia", "league": "POLAND: Ekstraklasa",
             "fs_id": "w1", "names": {"pl": ["Wisła Kraków", "Legia Warszawa"]}})
check("Ф-к5 перестановка сторон в зеркале — перевод не записан",
      not k2.is_translation_of("Gabon U20", "Congo U20"))
check("Ф-к5 перевод из одной игры ещё не засчитан", not k2.is_translation_of("Wisła Kraków", "Wisla"))
k2.add_game({"sport": "F", "home": "Wisla", "away": "Lech Poznan", "league": "POLAND: Ekstraklasa",
             "fs_id": "w2", "names": {"pl": ["Wisła Kraków", "Lech Poznań"]}})
check("Ф-к5 перевод из двух игр засчитан", k2.is_translation_of("Wisła Kraków", "Wisla"))
k3 = fs_katalog.Katalog.from_json(__import__("json").loads(__import__("json").dumps(k2.to_json())))
check("Ф-к5 каталог через файл помнит число игр перевода", k3.is_translation_of("Wisła Kraków", "Wisla")
      and not k3.is_translation_of("Legia Warszawa", "Legia"))

# ── база ────────────────────────────────────────────────────────────────────
filler = R(conn, "Filler", "Filler")
league = conn.execute("INSERT INTO leagues (slug, canonical_name, sport) "
                      "VALUES ('saudi', 'SAUDI ARABIA: Saudi Pro League', 'F')").lastrowid
R(conn, "Avellino", "Avellino")                    # С6.1 тёзки по виду
R(conn, "Avellino", "Avellino Basket")
event(team("Avellino"), filler, "F")
R(conn, "Sparta", "Sparta")                        # С6.2 играли между собой
R(conn, "Sparta", "Sparta Praha")
event(team("Sparta"), team("Sparta Praha"), "F")
R(conn, "AEK", "AEK")                              # С6.3 голое имя
R(conn, "AEK", "AEK Athens")
R(conn, "AEK", "AEK Larnaca")
R(conn, "Osaka", "Osaka")                          # С6.5 игрок и клуб
R(conn, "Osaka", "Osaka N.")
R(conn, "Lech Poznań", "Lech Poznań")              # Ф2
R(conn, "Lech Poznań", "Lech Poznan")
R(conn, "Лех Познань", "Lech Poznan", lang="ru")
R(conn, "Rangers", "Rangers")                      # Ф3
R(conn, "Rangers", "Rangers FC")
event(team("Rangers"), filler, "F")
R(conn, "Oldenburg", "Oldenburg")                  # Ф1/Ф3
R(conn, "Oldenburg", "VfB Oldenburg")
event(team("Oldenburg"), filler, "B")
R(conn, "Fukushima", "Fukushima")                  # Ф6
R(conn, "Fukushima", "Fukushima Utd")
R(conn, "Bucsa C./Melichar-Martinez N.", "Bucsa C./Melichar-Martinez N.")      # Ф0
R(conn, "Bucsa C./Melichar-Martinez N.", "Bucsa C./Melichar-Martinez N. WO")
R(conn, "Den Haag", "Den Haag")                    # Ф4: выживший — имя flashscore
R(conn, "Den Haag", "ADO Den Haag", lang="de")
ev_haag = event(team("ADO Den Haag"), filler, "F")
R(conn, "Gornik", "Gornik")                        # Ф6 + решение поиска «один клуб»
R(conn, "Gornik", "Gornik Zabrze")
for extra in ("Gornik Z.", "Górnik", "GKS Gornik"):
    R(conn, extra, "Gornik")
event(team("Gornik"), filler, "F", flags="fs:abc")
event(team("Gornik Zabrze"), filler, "F", flags="fs:abc")
R(conn, "Al Taawon", "Al Taawon")                  # Ф6 без решения поиска
R(conn, "Al Taawon", "Al Taawoun")
for extra in ("Al-Taawon", "Taawon", "Al Ta'awon"):
    R(conn, extra, "Al Taawon")
event(team("Al Taawon"), filler, "F", league=league)
event(team("Al Taawoun"), filler, "F", league=league)
R(conn, "Arsenal", "Arsenal")                      # С6.9 → Ф6
R(conn, "Арсенал", "Arsenal", lang="ru")
R(conn, "Άρσεναλ", "Arsenal", lang="el")
R(conn, "Arsenal", "Arenal")
# пары (мимо remember_team — С5 не пустил бы, а старая база такое держит)
for alias in ("Genoa - Milan", "Foo - Bar", "Qux - Zed"):
    conn.execute("INSERT INTO team_aliases (team_id, alias, lang) VALUES (?, ?, NULL)",
                 (filler, alias))
pair_team = conn.execute("INSERT INTO teams (canonical_name, slug) VALUES "
                         "('La Duchere - Nimes', 'la-duchere-nimes')").lastrowid
conn.execute("INSERT INTO team_aliases (team_id, alias, lang) VALUES (?, 'Ла Дюшер - Ним', 'ru')",
             (pair_team,))
banik = conn.execute("INSERT INTO teams (canonical_name, slug) VALUES "
                     "('Banik Most - Sous', 'banik-most-sous')").lastrowid
conn.execute("INSERT INTO team_aliases (team_id, alias, lang) VALUES (?, 'Μπανικ Μοστ-Σου', 'el')",
             (banik,))
R(conn, "Bayer Leverkusen", "Bayer Leverkusen")    # Кл3
R(conn, "Bayer Leverkusen", "Bayern Munich")
R(conn, "Spartak Subotica", "Spartak Subotica")    # Кл1
R(conn, "Spartak Subotica", "Sp. Subotica", lang="hu")
R(conn, "Zeta", "Zeta")                            # Кл4
R(conn, "Zeta", "Alpha Club")
conn.commit()

poisk = K.poisk_index([
    {"вид": "слияние", "имена": ["Gornik Zabrze", "Gornik"], "решение": "один клуб",
     "источник": "https://example.org/gornik", "почему": "тест"},
    {"вид": "пара", "имена": ["Qux - Zed"], "решение": "пара", "источник": "https://example.org/qux",
     "почему": "тест"},
])
aliases_before = conn.execute("SELECT count(*) FROM team_aliases").fetchone()[0]
teams_before = conn.execute("SELECT count(*) FROM teams").fetchone()[0]
plan: list = []
na_poisk: list = []
res = K.run(conn, kat, poisk, plan, na_poisk)
conn.commit()
verdicts = {(w, l): v for w, l, v, _ in plan}
print(f"  (слияния: {plan})")
asked = {(it["вид"], tuple(it["имена"])) for it in na_poisk}

check("С6 тёзки по виду, игравшие, голое имя, игрок — не слиты",
      all(merged(n) is None for n in ("Avellino", "Avellino Basket", "Sparta", "Sparta Praha",
                                       "AEK", "AEK Athens", "AEK Larnaca", "Osaka", "Osaka N.")))
check("Ф2 Lech Poznań → Lech Poznan (написание flashscore)",
      merged("Lech Poznań") == team("Lech Poznan")
      and verdicts.get(("Lech Poznan", "Lech Poznań")) == "сливать: flashscore", verdicts)
check("Ф3 Rangers и Rangers FC не слиты", merged("Rangers") is None and merged("Rangers FC") is None)
check("Ф1/Ф3 Oldenburg и VfB Oldenburg не слиты",
      merged("Oldenburg") is None and merged("VfB Oldenburg") is None)
check("Ф0 хвост WO слит",
      {merged("Bucsa C./Melichar-Martinez N."), merged("Bucsa C./Melichar-Martinez N. WO")} - {None})
check("Ф4 ADO Den Haag → Den Haag (имя flashscore выжило)",
      merged("ADO Den Haag") == team("Den Haag") and merged("Den Haag") is None, verdicts)
check("Ф6 + поиск «один клуб»: Gornik / Gornik Zabrze слиты",
      {merged("Gornik"), merged("Gornik Zabrze")} - {None}
      and "сливать: поиск" in {verdicts.get(("Gornik", "Gornik Zabrze")),
                                verdicts.get(("Gornik Zabrze", "Gornik"))}, verdicts)
check("Ф6 Al Taawon / Al Taawoun без решения поиска — не слиты, в списке «на поиск»",
      merged("Al Taawon") is None and merged("Al Taawoun") is None
      and any(k == "слияние" and set(v) == {"Al Taawon", "Al Taawoun"} for k, v in asked), asked)
for a, b in (("Fukushima", "Fukushima Utd"), ("Arsenal", "Arenal")):
    row = conn.execute("SELECT note FROM dictionary_errors WHERE class='возможный дубль' "
                       "AND alias IN (?, ?)", (a, b)).fetchone()
    check(f"Ф6 {a} / {b} — не слиты, книга «возможный дубль» с пометкой поиска",
          merged(a) is None and merged(b) is None and row is not None
          and "ждёт проверки поиском" in row[0], row and row[0])

# К2 — переезд написаний и событий, книга «слито»
haag = team("Den Haag")
check("К2 написание «Den Haag» (de) команды ADO Den Haag переехало к Den Haag",
      conn.execute("SELECT count(*) FROM team_aliases WHERE alias='Den Haag' AND lang='de' "
                   "AND team_id=?", (haag,)).fetchone()[0] == 1)
check("К2 событие ADO Den Haag — на выжившем Den Haag",
      conn.execute("SELECT team_home_id FROM events WHERE id=?", (ev_haag,)).fetchone()[0] == haag)
row = conn.execute("SELECT truth, note FROM dictionary_errors WHERE class='слито' "
                   "AND alias='ADO Den Haag' AND lang IS NULL").fetchone()
check("К2 слияние записано в книгу «слито» с причиной flashscore",
      row is not None and row[0] == "Den Haag" and "Ф4" in row[1], row and tuple(row))
row = conn.execute("SELECT note FROM dictionary_errors WHERE class='слито' "
                   "AND alias IN ('Gornik', 'Gornik Zabrze') AND lang IS NULL").fetchone()
check("К2 слияние по поиску — в книге источник", row is not None and "example.org/gornik" in row[0],
      row and row[0])
check("К2 словарь: «Lech Poznań» → Lech Poznan",
      dictionary.team_alias_map(conn).get("Lech Poznań", (0, ""))[1] == "Lech Poznan",
      dictionary.team_alias_map(conn).get("Lech Poznań"))

# К4, К5 — карантин
q = dictionary.quarantined(conn)
check("П2 «Genoa - Milan» в карантине", ("Genoa - Milan", None, filler) in q)
check("П2 «Ла Дюшер - Ним» в карантине", ("Ла Дюшер - Ним", "ru", pair_team) in q)
check("П3 Banik Most - Sous НЕ в карантине", ("Μπανικ Μοστ-Σου", "el", banik) not in q)
check("П4 «Foo - Bar» без решения — не в карантине, в списке «на поиск»",
      ("Foo - Bar", None, filler) not in q and ("пара", ("Foo - Bar",)) in asked)
check("П4 «Qux - Zed» — поиск сказал «пара»: карантин", ("Qux - Zed", None, filler) in q)
check("Кл3 Bayer Leverkusen → Bayern Munich в карантине",
      ("Bayer Leverkusen", None, team("Bayern Munich")) in q)
check("Кл3 не задел Bayer Leverkusen → Bayer Leverkusen",
      ("Bayer Leverkusen", None, team("Bayer Leverkusen")) not in q)
check("Кл1 «Spartak Subotica» (hu) у Sp. Subotica — не в карантине",
      ("Spartak Subotica", "hu", team("Sp. Subotica")) not in q)
check("Кл4 «Zeta» у Alpha Club — не в карантине, в списке «на поиск»",
      ("Zeta", None, team("Alpha Club")) not in q and ("коллизия", ("Zeta", "Alpha Club")) in asked, asked)

# ничего не удалено
check("ничего не удалено: написаний столько же",
      conn.execute("SELECT count(*) FROM team_aliases").fetchone()[0] == aliases_before)
check("ничего не удалено: команд столько же",
      conn.execute("SELECT count(*) FROM teams").fetchone()[0] == teams_before)
check("К8 сверка игр посчитана", res["игр"] == conn.execute("SELECT count(*) FROM events").fetchone()[0])

# К6 — второй прогон
book_before = conn.execute("SELECT count(*) FROM dictionary_errors").fetchone()[0]
res2 = K.run(conn, kat, poisk)
conn.commit()
t2 = res2["итог"]
book_after = conn.execute("SELECT count(*) FROM dictionary_errors").fetchone()[0]
check("К6 второй прогон: 0 слияний, 0 переездов",
      t2.get("слияний", 0) == 0 and t2.get("написаний переехало", 0) == 0
      and t2.get("событий переехало", 0) == 0, dict(t2))
check("К6 второй прогон: 0 новых строк книги", book_after == book_before, (book_before, book_after))

conn.close()
print(f"\n{green}/{total} зелёных")
raise SystemExit(0 if green == total else 1)

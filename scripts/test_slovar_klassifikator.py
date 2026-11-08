# -*- coding: utf-8 -*-
r"""Классификатор словаря команд (шаг 4 карточки словаря 09.11.2026) на
временной базе. Одно правило — один блок; примеры — из карточки (правило С6
и классы П, К).

  С6.1 тёзки по виду (Avellino / Avellino Basket) — не сливать;
  С6.2 играли между собой — не сливать;
  С6.3 голое имя тянут ≥ 2 команд (AEK) — не сливать;
  С6.5 игрок и клуб (Osaka / Osaka N.) — не сливать;
  С6 п. 4а имена разные на вид, вид известен не у обеих и футбола нет
       (Oldenburg баскетбол / VfB Oldenburg; Fukushima / Fukushima Utd) — не
       сливать, в книгу «возможный дубль»;
  С6.7 сливать точно: диакритика (Lech Poznań), клубные слова (Rangers FC),
       хвост WO у теннисной пары;
  С6.8 сливать по уликам: перевод эталона (Den Haag ⊂ ADO Den Haag, de),
       один матч fs: под двумя именами (Gornik), костяк + одна лига (Al Taawon);
  С6.9 возможный дубль (Arsenal / Arenal) — в книгу, команды целы;
  К2  после слияния написания переехали, событие на выжившем, merged_into;
       такое же написание у выжившего — осталось у проигравшего, книга «слито»;
  К4  пара как имя — карантин «пара»; К5 коллизия — карантин «коллизия»;
  К6  второй прогон: 0 новых строк книги, 0 переездов (С7);
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


filler = R(conn, "Filler", "Filler")
league = conn.execute("INSERT INTO leagues (slug, canonical_name, sport) "
                      "VALUES ('saudi', 'SAUDI ARABIA: Saudi Pro League', 'F')").lastrowid

# С6.1 тёзки по виду
R(conn, "Avellino", "Avellino")
R(conn, "Avellino", "Avellino Basket")
event(team("Avellino"), filler, "F")
# С6.2 играли между собой
R(conn, "Sparta", "Sparta")
R(conn, "Sparta", "Sparta Praha")
event(team("Sparta"), team("Sparta Praha"), "F")
# С6.3 голое имя
R(conn, "AEK", "AEK")
R(conn, "AEK", "AEK Athens")
R(conn, "AEK", "AEK Larnaca")
# С6.5 игрок и клуб
R(conn, "Osaka", "Osaka")
R(conn, "Osaka", "Osaka N.")
# С6.7 сливать точно
R(conn, "Lech Poznań", "Lech Poznań")
R(conn, "Lech Poznań", "Lech Poznan")
R(conn, "Лех Познань", "Lech Poznan", lang="ru")
R(conn, "Rangers", "Rangers")
R(conn, "Rangers", "Rangers FC")
event(team("Rangers"), filler, "F")
# С6 п. 4а: баскетбольный город и футбольный клуб с клубным словом — не сливать
R(conn, "Oldenburg", "Oldenburg")
R(conn, "Oldenburg", "VfB Oldenburg")
event(team("Oldenburg"), filler, "B")
# и вида нет ни у одной стороны — тоже не сливать (Fukushima / Fukushima Utd)
R(conn, "Fukushima", "Fukushima")
R(conn, "Fukushima", "Fukushima Utd")
R(conn, "Bucsa C./Melichar-Martinez N.", "Bucsa C./Melichar-Martinez N.")
R(conn, "Bucsa C./Melichar-Martinez N.", "Bucsa C./Melichar-Martinez N. WO")
# С6.8 по уликам: перевод эталона
R(conn, "Den Haag", "Den Haag")
R(conn, "Den Haag", "ADO Den Haag", lang="de")
ev_haag = event(team("Den Haag"), filler, "F")
# С6.8 по уликам: один матч fs: под двумя именами
R(conn, "Gornik", "Gornik")
R(conn, "Gornik", "Gornik Zabrze")
for extra in ("Gornik Z.", "Górnik", "GKS Gornik"):          # не «родилась из строки сайта»
    R(conn, extra, "Gornik")
event(team("Gornik"), filler, "F", flags="fs:abc")
event(team("Gornik Zabrze"), filler, "F", flags="fs:abc")
# С6.8 по уликам: костяк согласных + одна лига
R(conn, "Al Taawon", "Al Taawon")
R(conn, "Al Taawon", "Al Taawoun")
for extra in ("Al-Taawon", "Taawon", "Al Ta'awon"):
    R(conn, extra, "Al Taawon")
event(team("Al Taawon"), filler, "F", league=league)
event(team("Al Taawoun"), filler, "F", league=league)
# С6.9 возможный дубль: Arsenal знает эталон (переводы), Arenal — нет
R(conn, "Arsenal", "Arsenal")
R(conn, "Арсенал", "Arsenal", lang="ru")
R(conn, "Άρσεναλ", "Arsenal", lang="el")
R(conn, "Arsenal", "Arenal")                                   # ошибка сверки
# К4 пара как имя: написание-пара и канон-пара (кладём мимо remember_team — С5
# не пустил бы, а старая база такое держит)
conn.execute("INSERT INTO team_aliases (team_id, alias, lang) VALUES (?, 'Genoa - Milan', NULL)",
             (filler,))
pair_team = conn.execute("INSERT INTO teams (canonical_name, slug) VALUES "
                         "('La Duchere - Nimes', 'la-duchere-nimes')").lastrowid
conn.execute("INSERT INTO team_aliases (team_id, alias, lang) VALUES (?, 'Ла Дюшер - Ним', 'ru')",
             (pair_team,))
# К5 коллизия
R(conn, "Bayer Leverkusen", "Bayer Leverkusen")
R(conn, "Bayer Leverkusen", "Bayern Munich")
conn.commit()

aliases_before = conn.execute("SELECT count(*) FROM team_aliases").fetchone()[0]
teams_before = conn.execute("SELECT count(*) FROM teams").fetchone()[0]
plan: list = []
res = K.run(conn, plan)
conn.commit()
verdicts = {(w, l): v for w, l, v, _ in plan}
print(f"  (слияния: {plan})")

check("С6.1 тёзки по виду не слиты", merged("Avellino") is None and merged("Avellino Basket") is None)
check("С6.2 игравшие между собой не слиты", merged("Sparta") is None and merged("Sparta Praha") is None)
check("С6.3 голое имя AEK не слито", all(merged(n) is None for n in ("AEK", "AEK Athens", "AEK Larnaca")))
check("С6.5 игрок и клуб не слиты", merged("Osaka") is None and merged("Osaka N.") is None)
check("С6.7 Lech Poznań → Lech Poznan (диакритика, выживший с переводом)",
      merged("Lech Poznań") == team("Lech Poznan") and verdicts.get(("Lech Poznan", "Lech Poznań")) == "сливать точно",
      (merged("Lech Poznań"), verdicts))
check("С6.7 Rangers и Rangers FC слиты точно",
      {merged("Rangers"), merged("Rangers FC")} - {None} and
      "сливать точно" in {verdicts.get(("Rangers", "Rangers FC")), verdicts.get(("Rangers FC", "Rangers"))},
      verdicts)
check("С6 п. 4а Oldenburg (баскетбол) и VfB Oldenburg (вид неизвестен) не слиты",
      merged("Oldenburg") is None and merged("VfB Oldenburg") is None)
check("С6 п. 4а Fukushima / Fukushima Utd без вида не слиты, в книге «возможный дубль»",
      merged("Fukushima") is None and merged("Fukushima Utd") is None
      and conn.execute("SELECT 1 FROM dictionary_errors WHERE class='возможный дубль' "
                       "AND alias='Fukushima'").fetchone() is not None)
check("С6.7 хвост WO у пары слит точно",
      {merged("Bucsa C./Melichar-Martinez N."), merged("Bucsa C./Melichar-Martinez N. WO")} - {None})
check("С6.8 Den Haag → ADO Den Haag по переводу эталона",
      merged("Den Haag") == team("ADO Den Haag")
      and verdicts.get(("ADO Den Haag", "Den Haag")) == "сливать по уликам", verdicts)
check("С6.8 Gornik / Gornik Zabrze — один матч fs:, слиты по уликам",
      {merged("Gornik"), merged("Gornik Zabrze")} - {None}
      and "сливать по уликам" in {verdicts.get(("Gornik", "Gornik Zabrze")),
                                  verdicts.get(("Gornik Zabrze", "Gornik"))}, verdicts)
check("С6.8 Al Taawon / Al Taawoun — костяк и одна лига, слиты по уликам",
      {merged("Al Taawon"), merged("Al Taawoun")} - {None}, verdicts)
check("С6.9 Arsenal / Arenal не слиты", merged("Arsenal") is None and merged("Arenal") is None)
row = conn.execute("SELECT * FROM dictionary_errors WHERE class='возможный дубль' "
                   "AND alias='Arsenal'").fetchone()
check("С6.9 Arsenal / Arenal — в книге «возможный дубль»", row is not None, row)

# К2 — переезд написаний и событий
haag = team("ADO Den Haag")
check("К2 написание «Den Haag» команды Den Haag переехало к ADO Den Haag",
      conn.execute("SELECT count(*) FROM team_aliases WHERE alias='Den Haag' AND lang IS NULL "
                   "AND team_id=?", (haag,)).fetchone()[0] == 1)
check("К2 событие Den Haag — на выжившем",
      conn.execute("SELECT team_home_id FROM events WHERE id=?", (ev_haag,)).fetchone()[0] == haag)
lech_left = conn.execute("SELECT count(*) FROM team_aliases a JOIN teams t ON t.id=a.team_id "
                         "WHERE a.alias='Lech Poznań' AND t.canonical_name='Lech Poznań'").fetchone()[0]
slito = conn.execute("SELECT count(*) FROM dictionary_errors WHERE class='слито' "
                     "AND alias='Lech Poznań'").fetchone()[0]
check("К2 такое же написание у выжившего — осталось у проигравшего, книга «слито»",
      lech_left == 1 and slito == 1, (lech_left, slito))
check("К2 словарь: «Lech Poznań» → Lech Poznan",
      dictionary.team_alias_map(conn).get("Lech Poznań", (0, ""))[1] == "Lech Poznan",
      dictionary.team_alias_map(conn).get("Lech Poznań"))

# К4, К5 — карантин
q = dictionary.quarantined(conn)
check("К4 написание-пара в карантине", ("Genoa - Milan", None, filler) in q)
check("К4 написание команды-пары в карантине", ("Ла Дюшер - Ним", "ru", pair_team) in q)
check("К5 коллизия Bayer Leverkusen → Bayern Munich в карантине",
      ("Bayer Leverkusen", None, team("Bayern Munich")) in q)
check("К5 карантин не задел Bayer Leverkusen → Bayer Leverkusen",
      ("Bayer Leverkusen", None, team("Bayer Leverkusen")) not in q)

# ничего не удалено
check("ничего не удалено: написаний столько же",
      conn.execute("SELECT count(*) FROM team_aliases").fetchone()[0] == aliases_before)
check("ничего не удалено: команд столько же",
      conn.execute("SELECT count(*) FROM teams").fetchone()[0] == teams_before)
check("К8 сверка игр посчитана", res["игр"] == conn.execute("SELECT count(*) FROM events").fetchone()[0])

# К6 — второй прогон
book_before = conn.execute("SELECT count(*) FROM dictionary_errors").fetchone()[0]
res2 = K.run(conn)
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

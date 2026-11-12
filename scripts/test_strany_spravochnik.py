# -*- coding: utf-8 -*-
r"""Книга 102: сборные по справочнику стран — написание уходит в словарь.

Жалоба владельца 12.11.2026: «Scotia», «Suomi», «Liettua» витрина переводила
(справочник сборных в `data/aliases.json`), но в словарь они не попадали —
сторона оставалась без команды, игра висела в «Names to fix»: «ты уже давно
должен был определить язык, перевести на английский и внести в словарь».
Правила (`app/dictionary.py`, `learn_country_sides`):

  Э1. имя стороны ЦЕЛИКОМ — страна из справочника сборных (любой язык,
      пометки пола и возраста не в счёт) — это сборная этой страны;
  Э2. команда — только известная словарю сборная; с пометкой («W») —
      «страна + пометка», нет её — заводится рядом со сборной без пометки;
      сборной нет вовсе — ничего не заводим;
  Э3. на одну страну две команды — не решаем;
  Э4. написание уже занято другой командой — не трогаем;
  Э5. написание без пометки учится заодно.

Сквозная проверка — прогон `canon_backfill.py`: игра «Anglia — Scotia» без
эталона получает обе команды. В сеть не ходит, база — во временной папке.

Запуск: venv\Scripts\python.exe scripts\test_strany_spravochnik.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="strany-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")

from app import db, dictionary, names  # noqa: E402

total = green = 0


def check(name: str, ok: bool, got=None) -> None:
    global total, green
    total += 1
    green += bool(ok)
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"   ← {got!r}"))


def owner(conn, alias: str) -> list[str]:
    return sorted(r[0] for r in conn.execute(
        "SELECT t.canonical_name FROM team_aliases a JOIN teams t ON t.id = a.team_id "
        "WHERE a.alias = ?", (alias,)))


def team(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM teams WHERE canonical_name = ?", (name,)).fetchone() is not None


print("Э1: страна из справочника, имя целиком")
check("«Scotia» (румынский без значков) — Шотландия", names.country_of("Scotia") == "SCOTLAND",
      names.country_of("Scotia"))
check("«Suomi», «Liettua W» (финский) — Финляндия и Литва",
      (names.country_of("Suomi"), names.country_of("Liettua W")) == ("FINLAND", "LITHUANIA"),
      (names.country_of("Suomi"), names.country_of("Liettua W")))
check("английское имя с пометкой — тоже страна: «Scotland U21»",
      names.country_of("Scotland U21") == "SCOTLAND", names.country_of("Scotland U21"))
check("клубное сокращение не страна: «PSG», «Paris SG»",
      names.country_of("PSG") == "" and names.country_of("Paris SG") == "",
      (names.country_of("PSG"), names.country_of("Paris SG")))
check("страна словом внутри имени не считается: «Novi Sad», «Suomi N»",
      names.country_of("Novi Sad") == "" and names.country_of("Suomi N") == "",
      (names.country_of("Novi Sad"), names.country_of("Suomi N")))
check("пустое и мусор — не страна", names.country_of("") == "" and names.country_of(" - ") == "")

conn = db.connect()
db.init_db(conn)
for name in ("Scotland", "England", "Finland", "Lithuania", "Sweden", "Sweden W", "Celtic"):
    dictionary.remember_team(conn, name, name)

print("Э2: команда — известная словарю сборная")
got = dictionary.learn_country_sides(conn, ["Scotia", "Suomi", "Celtic Glasgow", "", None, "Scotia"])
check("«Scotia» → Scotland, «Suomi» → Finland — в словаре",
      owner(conn, "Scotia") == ["Scotland"] and owner(conn, "Suomi") == ["Finland"],
      (owner(conn, "Scotia"), owner(conn, "Suomi")))
check("отчёт называет выученное; клуб и пустое не тронуты",
      sorted(got["выучено"]) == [("Scotia", "Scotland"), ("Suomi", "Finland")]
      and owner(conn, "Celtic Glasgow") == [], got)
check("словарь теперь отдаёт написание как бесспорное",
      dictionary.team_overrides(conn).get("Scotia") == "Scotland",
      dictionary.team_overrides(conn).get("Scotia"))
got = dictionary.learn_country_sides(conn, ["Ruotsi W"])
check("с пометкой — готовая команда «страна + пометка»: «Ruotsi W» → Sweden W",
      owner(conn, "Ruotsi W") == ["Sweden W"], (owner(conn, "Ruotsi W"), got))
got = dictionary.learn_country_sides(conn, ["Liettua W"])
check("такой команды ещё нет — заводится рядом со сборной: «Liettua W» → Lithuania W",
      owner(conn, "Liettua W") == ["Lithuania W"] and team(conn, "Lithuania W"),
      (owner(conn, "Liettua W"), got))
got = dictionary.learn_country_sides(conn, ["Viro", "Viro W"])
check("сборной в словаре нет вовсе (Эстония) — ничего не заводим",
      got["нет сборной"] == ["Viro", "Viro W"] and not team(conn, "Estonia")
      and not team(conn, "Estonia W") and owner(conn, "Viro") == [], got)

print("Э5: написание без пометки учится заодно")
check("«Liettua» → Lithuania, «Ruotsi» → Sweden",
      owner(conn, "Liettua") == ["Lithuania"] and owner(conn, "Ruotsi") == ["Sweden"],
      (owner(conn, "Liettua"), owner(conn, "Ruotsi")))

print("Э3: на одну страну две команды — не решаем")
dictionary.remember_team(conn, "Bosnia & Herzegovina", "Bosnia & Herzegovina")
dictionary.remember_team(conn, "Bosnia and Herzegovina", "Bosnia and Herzegovina")
both = (names.country_of("Bosnia & Herzegovina"), names.country_of("Bosnia and Herzegovina"))
got = dictionary.learn_country_sides(conn, ["BiH"])
check("«BiH» при двойниках Боснии не учится", both[0] == both[1] != "" and got["спор"] == ["BiH"]
      and owner(conn, "BiH") == [], (both, got))

print("Э4: написание занято другой командой — не трогаем")
dictionary.remember_team(conn, "Anglia", "Anglia Ruskin")
got = dictionary.learn_country_sides(conn, ["Anglia"])
check("«Anglia» уже за клубом — остаётся за ним", got["занято"] == ["Anglia"]
      and owner(conn, "Anglia") == ["Anglia Ruskin"], (got, owner(conn, "Anglia")))
got = dictionary.learn_country_sides(conn, ["Scotia"])
check("повтор ничего не дублирует", conn.execute(
    "SELECT COUNT(*) FROM team_aliases WHERE alias = 'Scotia'").fetchone()[0] == 1, got)

print("слитая сборная — написание уходит выжившей")
dictionary.remember_team(conn, "Türkiye", "Türkiye")
dictionary.remember_team(conn, "Turkey", "Turkey")
loser = dictionary.team_id_by_name(conn, "Türkiye")
winner = dictionary.team_id_by_name(conn, "Turkey")
conn.execute("UPDATE teams SET merged_into = ? WHERE id = ?", (winner, loser))
conn.commit()
got = dictionary.learn_country_sides(conn, ["Turkki"])
check("«Turkki» → Turkey (Türkiye слита в неё)", owner(conn, "Turkki") == ["Turkey"],
      (owner(conn, "Turkki"), got, names.country_of("Turkki"), names.country_of("Türkiye")))
conn.close()

print("сквозная: сверка имён ставит сборные игре без эталона")
os.environ["STREAMS_DB"] = str(TMP / "backfill.db")
bf = db.connect()
db.init_db(bf)
for name in ("Scotland", "England", "Lyon"):
    dictionary.remember_team(bf, name, name)
bf.execute("INSERT INTO events (sport, start_utc, start_kyiv, team_home_auto, team_away_auto) "
           "VALUES ('F', '2026-11-12 19:45', '2026-11-12 21:45', 'Anglia', 'Scotia')")
bf.execute("INSERT INTO events (sport, start_utc, start_kyiv, team_home_auto, team_away_auto) "
           "VALUES ('F', '2026-11-13 19:45', '2026-11-13 21:45', 'Lyon', 'Neznamy Klub')")
bf.commit()
bf.close()
games_file = TMP / "games.json"
games_file.write_text(json.dumps({"games": [], "эталон": [{
    "sport": "F", "home": "Arsenal", "away": "Chelsea", "fs_id": "zzz00001",
    "league": "ENGLAND: Premier League", "start_kyiv": "2026-11-14T18:30", "names": {}}]},
    ensure_ascii=False), encoding="utf-8")
run = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "canon_backfill.py"),
                      "--file", str(games_file)], capture_output=True, text=True,
                     encoding="utf-8", errors="replace", env=dict(os.environ))
bf = db.connect()
row = bf.execute("SELECT th.canonical_name, ta.canonical_name FROM events e "
                 "LEFT JOIN teams th ON th.id = e.team_home_id LEFT JOIN teams ta ON ta.id = e.team_away_id "
                 "WHERE e.team_home_auto = 'Anglia'").fetchone()
row2 = bf.execute("SELECT th.canonical_name, e.team_away_id FROM events e "
                  "LEFT JOIN teams th ON th.id = e.team_home_id WHERE e.team_home_auto = 'Lyon'").fetchone()
check("сверка не падает и пишет, что выучила", run.returncode == 0
      and "сборные по справочнику стран" in run.stdout, (run.stdout + run.stderr)[-700:])
check("«Anglia — Scotia» → England — Scotland", row is not None and tuple(row) == ("England", "Scotland"),
      row and tuple(row))
check("незнакомый клуб остался без команды — не выдуман", row2 is not None and row2[1] is None
      and row2[0] == "Lyon", row2 and tuple(row2))
check("в словаре — оба написания", owner(bf, "Anglia") == ["England"] and owner(bf, "Scotia") == ["Scotland"],
      (owner(bf, "Anglia"), owner(bf, "Scotia")))
bf.close()

print(f"\n{green}/{total} зелёных")
raise SystemExit(0 if green == total else 1)

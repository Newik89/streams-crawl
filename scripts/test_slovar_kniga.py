# -*- coding: utf-8 -*-
r"""Карточка словаря 09.11.2026 — книга ошибок без удалений. Тесты правил
словаря (`app/dictionary.py`) на временной базе. Одно правило — один блок.

  С1. язык сайта первым: спорное написание с `lang` сайта решается им;
  С2. спор остаётся спором: без языка «Динамо» молчит;
  С3. карантин («пара», «коллизия» в dictionary_errors) не отдаётся,
      запись в team_aliases при этом жива;
  С4. канон сильнее чужого написания: «Bayer Leverkusen» → Bayer Leverkusen,
      хотя запись ведёт и на Bayern Munich;
  С5. пара — не команда: каноническое имя-пара не заводится (ответ 0),
      написание-пара не цепляется; обе — в книгу классом «пара»;
  С6. слитая команда (`merged_into`) читается как выжившая;
  С8. схема: init_db создаёт dictionary_errors и teams.merged_into;
  С9. книга без мусора: вторая встреча не плодит строку.

Запуск: venv\Scripts\python.exe scripts\test_slovar_kniga.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="slovar-kniga-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")

from app import db, dictionary  # noqa: E402

total = green = 0


def check(name: str, ok: bool, got=None) -> None:
    global total, green
    total += 1
    green += bool(ok)
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"   ← {got!r}"))


conn = db.connect()
db.init_db(conn)

# С8 — схема
cols = {r[1] for r in conn.execute("PRAGMA table_info(teams)")}
check("С8 teams.merged_into появилась", "merged_into" in cols, cols)
check("С8 dictionary_errors создана",
      conn.execute("SELECT 1 FROM sqlite_master WHERE name='dictionary_errors'").fetchone() is not None)

# заготовка: команды и написания
R = dictionary.remember_team
tuzla = R(conn, "Sloboda", "Sloboda Tuzla", lang="bs")
uzice = R(conn, "Sloboda", "Sloboda Uzice", lang="sr")
R(conn, "Sloboda", "Sloboda DT", lang=None)
R(conn, "Динамо", "Dynamo Moscow")
R(conn, "Динамо", "Dyn. Kyiv")
bayern = R(conn, "Bayern Munich", "Bayern Munich")
R(conn, "Bayer Leverkusen", "Bayern Munich")           # ошибка сверки
bayer = R(conn, "Bayer Leverkusen", "Bayer Leverkusen")

# С1 — язык сайта
m_sr = dictionary.team_alias_map(conn, lang="sr")
m_bs = dictionary.team_alias_map(conn, lang="bs")
check("С1 Sloboda на сербском сайте → Sloboda Uzice", m_sr.get("Sloboda", (0, ""))[1] == "Sloboda Uzice", m_sr.get("Sloboda"))
check("С1 Sloboda на боснийском сайте → Sloboda Tuzla", m_bs.get("Sloboda", (0, ""))[1] == "Sloboda Tuzla", m_bs.get("Sloboda"))

# С2 — спор без языка молчит
m0 = dictionary.team_alias_map(conn)
check("С2 «Динамо» без языка словарь не отдаёт", "Динамо" not in m0, m0.get("Динамо"))
check("С2 «Sloboda» без языка словарь не отдаёт", "Sloboda" not in m0, m0.get("Sloboda"))

# С4 — канон сильнее чужого написания
check("С4 Bayer Leverkusen → Bayer Leverkusen, не Bayern", m0.get("Bayer Leverkusen", (0, ""))[1] == "Bayer Leverkusen", m0.get("Bayer Leverkusen"))

# С3 — карантин
dictionary.note_error(conn, "Bayer Leverkusen", "коллизия", lang=None, team_id=bayern,
                      led_to="Bayern Munich", truth="Bayer Leverkusen")
conn.commit()
alive = conn.execute("SELECT count(*) FROM team_aliases WHERE alias='Bayer Leverkusen'").fetchone()[0]
check("С3 запись в team_aliases не удалена", alive == 2, alive)
m1 = dictionary.team_alias_map(conn)
check("С3 карантинная запись не участвует, ответ Bayer Leverkusen", m1.get("Bayer Leverkusen", (0, ""))[1] == "Bayer Leverkusen", m1.get("Bayer Leverkusen"))
dictionary.note_error(conn, "Sloboda", "коллизия", lang=None, team_id=None)
conn.commit()
# карантин по (alias, lang=None, team_id=None) не трогает записи с team_id — проверяем точечность
sloboda_dt = conn.execute("SELECT id FROM teams WHERE canonical_name='Sloboda DT'").fetchone()[0]
dictionary.note_error(conn, "Sloboda", "коллизия", lang=None, team_id=sloboda_dt)
conn.commit()
m2 = dictionary.team_alias_map(conn, lang="sr")
check("С3 карантин точечный: Sloboda/sr по-прежнему Uzice", m2.get("Sloboda", (0, ""))[1] == "Sloboda Uzice", m2.get("Sloboda"))

# С5 — пара не команда
before = conn.execute("SELECT count(*) FROM teams").fetchone()[0]
rc = R(conn, "Ла Дюшер - Ним", "La Duchere - Nimes")
after = conn.execute("SELECT count(*) FROM teams").fetchone()[0]
check("С5 канон-пара не заводится, ответ 0", rc == 0 and after == before, (rc, before, after))
genoa = R(conn, "Genoa - Milan", "Genoa")
att = conn.execute("SELECT count(*) FROM team_aliases WHERE alias='Genoa - Milan'").fetchone()[0]
check("С5 написание-пара к Genoa не прицеплено", genoa > 0 and att == 0, (genoa, att))
pairs = conn.execute("SELECT count(*) FROM dictionary_errors WHERE class='пара'").fetchone()[0]
check("С5 обе пары в книге", pairs == 2, pairs)
check("С5 Fleury-Merogis — одна команда", not dictionary.is_pair_name("Fleury-Merogis"))

# С6 — слитая команда читается как выжившая
milan = R(conn, "AC Milan", "AC Milan")
short = R(conn, "Milan", "Milan")
conn.execute("UPDATE teams SET merged_into=? WHERE id=?", (milan, short))
conn.commit()
m3 = dictionary.team_alias_map(conn)
check("С6 «Milan» после слияния → AC Milan", m3.get("Milan", (0, ""))[1] == "AC Milan", m3.get("Milan"))

# С1б — вид спорта страницы
olimpia = R(conn, "Milan", "Olimpia Milano")
other_b = R(conn, "Virtus Bologna", "Virtus Bologna")
other_f = R(conn, "Inter", "Inter")
# команда «Milan» остаётся слитой в AC Milan (С6) — иначе С4 отдаст её саму
conn.execute("INSERT INTO events (sport, team_home_id, team_away_id, start_utc, start_kyiv) "
             "VALUES ('B', ?, ?, '2026-11-09 18:00:00', '2026-11-09 20:00:00')", (olimpia, other_b))
conn.execute("INSERT INTO events (sport, team_home_id, team_away_id, start_utc, start_kyiv) "
             "VALUES ('F', ?, ?, '2026-11-09 18:00:00', '2026-11-09 20:00:00')", (milan, other_f))
conn.commit()
mb = dictionary.team_alias_map(conn, sport="B")
mf = dictionary.team_alias_map(conn, sport="F")
mn = dictionary.team_alias_map(conn)
check("С1б Milan на баскетбольной странице → Olimpia Milano", mb.get("Milan", (0, ""))[1] == "Olimpia Milano", mb.get("Milan"))
check("С1б Milan на футбольной странице → AC Milan", mf.get("Milan", (0, ""))[1] == "AC Milan", mf.get("Milan"))
check("С1б Milan без вида — молчит", "Milan" not in mn, mn.get("Milan"))

# С1в — единственный хозяин чужого вида
hsv = R(conn, "Αμβούργο", "Hamburger SV", lang="el")
R(conn, "Τίγρεις", "Towers", lang="el")                        # вид неизвестен
conn.execute("INSERT INTO events (sport, team_home_id, team_away_id, start_utc, start_kyiv) "
             "VALUES ('F', ?, ?, '2026-11-09 18:00:00', '2026-11-09 20:00:00')", (hsv, other_f))
conn.commit()
mb = dictionary.team_alias_map(conn, sport="B")
mf = dictionary.team_alias_map(conn, sport="F")
check("С1в Αμβούργο (только Hamburger SV, футбол) на баскетболе — молчит", "Αμβούργο" not in mb, mb.get("Αμβούργο"))
check("С1в Αμβούργο на футболе → Hamburger SV", mf.get("Αμβούργο", (0, ""))[1] == "Hamburger SV", mf.get("Αμβούργο"))
check("С1в вид хозяина неизвестен — отдаётся как раньше", mb.get("Τίγρεις", (0, ""))[1] == "Towers", mb.get("Τίγρεις"))

# С9 — книга без мусора
n1 = dictionary.note_error(conn, "Динамо", "двусмысленно")
n2 = dictionary.note_error(conn, "Динамо", "двусмысленно")
rows = conn.execute("SELECT count(*) FROM dictionary_errors WHERE alias='Динамо'").fetchone()[0]
check("С9 вторая встреча не плодит строку", n1 and not n2 and rows == 1, (n1, n2, rows))

conn.close()
print(f"\n{green}/{total} зелёных")
raise SystemExit(0 if green == total else 1)

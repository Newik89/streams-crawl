# -*- coding: utf-8 -*-
r"""Карточка словаря 09.11.2026 — книга ошибок без удалений. Тесты правил
словаря (`app/dictionary.py`) на временной базе. Одно правило — один блок.

  С1. язык сайта: спорное написание с `lang` сайта решается им (язык — из
      любой записи команды; язык сайта — набором `site_lang.of`). Это ответ
      словаря по запросу (`team_alias_map(conn, lang, sport)`); в работе —
      разбор, сверка, заливка — словарь плоский (замер окна 49), заливка
      это и проверяет;
  С1б/С1в. вид спорта страницы — так же;
  С2. спор остаётся спором: без языка «Динамо» молчит; спорное имя пишет в
      книгу «двусмысленно» разбор (`canon.note_disputed`), один раз;
  С4 первым: точное имя команды сильнее записи с языком («Valencia Basket»);
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
roma = R(conn, "Parma", "AS Roma")                     # две ошибки сверки
palermo = R(conn, "Parma", "Palermo")
parma = R(conn, "Parma", "Parma")
dictionary.note_error(conn, "Parma", "коллизия", team_id=roma, led_to="AS Roma", truth="Parma")
dictionary.note_error(conn, "Parma", "коллизия", team_id=palermo, led_to="Palermo", truth="Parma")
conn.commit()
q = dictionary.quarantined(conn)
check("С3 два чужих хозяина одного написания — две строки карантина",
      ("Parma", None, roma) in q and ("Parma", None, palermo) in q, q)
check("С3 после карантина «Parma» → Parma", dictionary.team_alias_map(conn).get("Parma", (0, ""))[1] == "Parma")

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

# ── Остаток шага 3: язык сайта, книга спорных имён из разбора ──
from app import canon, site_lang, store  # noqa: E402

# С1 — язык берётся из ЛЮБОЙ записи команды, не только из последней
surd = R(conn, "Radnik", "Radnik Surdulica", lang="sr")
R(conn, "Radnik", "Radnik Surdulica", lang=None)
R(conn, "Radnik", "Radnik Bijeljina", lang=None)
book = dictionary.team_names(conn)
check("С1 Radnik на сербском → Surdulica (запись sr — не последняя у команды)",
      book.owner("Radnik", "sr") == (surd, "Radnik Surdulica"), book.owner("Radnik", "sr"))
check("С1 Radnik без языка — молчит", book.owner("Radnik") is None, book.owner("Radnik"))

# С1 — язык сайта несколькими кодами (`site_lang.of`)
spm = R(conn, "Спартак", "Spartak Moscow", lang="ru")
R(conn, "Спартак", "Spartak Trnava", lang=None)
spv = R(conn, "Спартак", "Spartak Varna", lang="bg")
book = dictionary.team_names(conn)
check("С1 «Спартак» на ntvplus.tv (ru + en) → Spartak Moscow",
      book.owner("Спартак", site_lang.of("ntvplus.tv")) == (spm, "Spartak Moscow"),
      book.owner("Спартак", site_lang.of("ntvplus.tv")))
check("С1 «Спартак» на nova.bg → Spartak Varna",
      book.owner("Спартак", site_lang.of("nova.bg")) == (spv, "Spartak Varna"),
      book.owner("Спартак", site_lang.of("nova.bg")))
check("С2 «Спартак» без сайта — молчит", book.owner("Спартак") is None, book.owner("Спартак"))
check("С2 команды спора названы", sorted(book.disputed("Спартак")) ==
      ["Spartak Moscow", "Spartak Trnava", "Spartak Varna"], book.disputed("Спартак"))

# языки игры — по сайтам её записей
check("языки игры: ntvplus.tv + unian.tv → ru, uk, en",
      site_lang.of_game({"entries": [{"source": "ntvplus.tv"}, {"source": "unian.tv"}]})
      == frozenset({"ru", "uk", "en"}))
check("языки игры: сайт без языка → None (все языки)",
      site_lang.of_game({"entries": [{"source": "ntvplus.tv"}, {"source": "neizvestno.xx"}]}) is None)
check("языки игры: записей нет → None", site_lang.of_game({"entries": []}) is None)

# заливка ставит id команды ПЛОСКИМ словарём: язык и вид там не решают
# (замер 09.11 на копии живой базы: «ЦСКА» с русского сайта ушла бы в CSKA
# Sofia, «FC Barcelona» в баскетболе — в Baskonia; см. HANDOFF окно 49)
ids = store._team_ids(conn)
check("заливка: спорный «Спартак» id не получает",
      store._team_id(ids, "Спартак") is None, store._team_id(ids, "Спартак"))
check("заливка: бесспорный «Αμβούργο» → Hamburger SV, как раньше",
      store._team_id(ids, "Αμβούργο") == hsv)

# С4 — точное имя первым: запись с языком не уводит к чужому клубу
valencia = R(conn, "Valencia Basket", "Valencia Basket")
R(conn, "Valencia Basket", "Palencia", lang="es")              # ошибка сверки
book = dictionary.team_names(conn, with_sports=True)
check("С4 первым: «Valencia Basket» на испанском сайте → Valencia Basket",
      book.owner("Valencia Basket", site_lang.of("movistarplus.es"), "B") == (valencia, "Valencia Basket"),
      book.owner("Valencia Basket", site_lang.of("movistarplus.es"), "B"))
try:
    dictionary.team_names(conn).owner("Milan", None, "B")
    asked = False
except ValueError:
    asked = True
check("словарь без видов спорта на вопрос с видом не отвечает молча, а ругается", asked)

# С2 — спорное имя пишет в книгу разбор (`canon.note_disputed`), один раз
loko_m = R(conn, "Локомотив", "Lokomotiv Moscow")
R(conn, "Локомотив", "Lokomotiv Plovdiv")
game_l = {"sport": "F", "home": "Локомотив", "away": "Зенит", "league": "",
          "start_kyiv": "2026-11-11T18:00",
          "entries": [{"source": "vsetv.com", "raw_title": "Локомотив - Зенит"}]}
ref_l = {"sport": "F", "home": "Lokomotiv Moscow", "away": "Zenit", "fs_id": "t2",
         "start_kyiv": "2026-11-11T18:00"}
aligned = {"sure": [(game_l, ref_l, 90)], "ask": [], "missed": []}
new1 = canon.note_disputed(conn, aligned)
new2 = canon.note_disputed(conn, aligned)
conn.commit()
row = conn.execute("SELECT * FROM dictionary_errors WHERE alias='Локомотив'").fetchone()
check("С2 спорное «Локомотив» — строка книги «двусмысленно»",
      row is not None and row["class"] == "двусмысленно" and row["lang"] == "ru"
      and row["source_domain"] == "vsetv.com" and row["truth"] == "Lokomotiv Moscow"
      and "Lokomotiv Plovdiv" in (row["led_to"] or ""), dict(row) if row else None)
check("С2/С9 вторая встреча строку не плодит", new1 == 1 and new2 == 0, (new1, new2))
check("С2 неизвестное словарю «Зенит» в книгу не идёт",
      conn.execute("SELECT 1 FROM dictionary_errors WHERE alias='Зенит'").fetchone() is None)
check("С2 язык книги: ru + en → «ru», SH → «bs hr sr», en → «en»",
      (canon.book_lang(site_lang.of("vsetv.com")), canon.book_lang(site_lang.of("rts.rs")),
       canon.book_lang(site_lang.of("bbc.co.uk")), canon.book_lang(None))
      == ("ru", "bs hr sr", "en", None))
check("С2 строка книги из разбора словарь не глушит: «Локомотив» по-прежнему спор",
      dictionary.team_names(conn).owner("Локомотив") is None and loko_m > 0)

# С6 — слияние без новых строк (UPDATE) видно сразу: кэш словаря его замечает
getafe_cf = R(conn, "Getafe CF", "Getafe CF")
getafe = R(conn, "Getafe", "Getafe")
check("кэш: до слияния Getafe → Getafe", dictionary.team_alias_map(conn).get("Getafe", (0, ""))[1] == "Getafe")
conn.execute("UPDATE teams SET merged_into=? WHERE id=?", (getafe_cf, getafe))
conn.commit()
check("кэш: после слияния (UPDATE) Getafe → Getafe CF",
      dictionary.team_alias_map(conn).get("Getafe", (0, ""))[1] == "Getafe CF",
      dictionary.team_alias_map(conn).get("Getafe"))

# С9 — книга без мусора
n1 = dictionary.note_error(conn, "Динамо", "двусмысленно")
n2 = dictionary.note_error(conn, "Динамо", "двусмысленно")
rows = conn.execute("SELECT count(*) FROM dictionary_errors WHERE alias='Динамо'").fetchone()[0]
check("С9 вторая встреча не плодит строку", n1 and not n2 and rows == 1, (n1, n2, rows))

# С8 — выгрузка/загрузка: книга едет с словарями, слитая команда не выгружается
sys.path.insert(0, str(ROOT / "scripts"))
import json  # noqa: E402
import dict_sync  # noqa: E402
out = TMP / "dictionaries.json"
counts = dict_sync.export(conn, out)
dumped = json.loads(out.read_text(encoding="utf-8"))
names_out = {t["name"] for t in dumped["teams"]}
check("С8 выгрузка: книга ошибок в файле", counts["ошибок в книге"] >= 4 and len(dumped["dictionary_errors"]) == counts["ошибок в книге"], counts)
check("С8 выгрузка: слитая «Milan» не выгружена, AC Milan — да", "Milan" not in names_out and "AC Milan" in names_out, sorted(names_out)[:5])
conn.close()
os.environ["STREAMS_DB"] = str(TMP / "fresh.db")
fresh = db.connect()
db.init_db(fresh)
dict_sync.load(fresh, out)
q = dictionary.quarantined(fresh)
bayern_fresh = fresh.execute("SELECT id FROM teams WHERE canonical_name='Bayern Munich'").fetchone()[0]
check("С8 загрузка в чистую базу: карантин восстановлен с командой",
      ("Bayer Leverkusen", None, bayern_fresh) in q, q)
m_fresh = dictionary.team_alias_map(fresh)
check("С8 после загрузки Bayer Leverkusen → Bayer Leverkusen", m_fresh.get("Bayer Leverkusen", (0, ""))[1] == "Bayer Leverkusen", m_fresh.get("Bayer Leverkusen"))
dict_sync.load(fresh, out)
n_err = fresh.execute("SELECT count(*) FROM dictionary_errors").fetchone()[0]
check("С8/С9 повторная загрузка не плодит строки книги", n_err == counts["ошибок в книге"], n_err)
fresh.close()
print(f"\n{green}/{total} зелёных")
raise SystemExit(0 if green == total else 1)

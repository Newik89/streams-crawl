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

# ── ревизия 09.11 (вечер): С6 по имени, С5 без нуля в событии, С10, С11 ──

# С6 — имя слитой команды ведёт к ВЫЖИВШЕЙ (flashscore пишет и Al-Sadd, и Al Sadd)
sadd = R(conn, "Al-Sadd", "Al-Sadd")
sadd_lose = R(conn, "Al Sadd", "Al Sadd")
conn.execute("UPDATE team_aliases SET team_id=? WHERE team_id=?", (sadd, sadd_lose))
conn.execute("UPDATE teams SET merged_into=? WHERE id=?", (sadd, sadd_lose))
conn.commit()
got = R(conn, "Al Sadd", "Al Sadd")
check("С6 remember_team по имени слитой команды → выжившая", got == sadd, (got, sadd, sadd_lose))
check("С6 team_id_by_name: слитая → выжившая, нет такой → None",
      dictionary.team_id_by_name(conn, "Al Sadd") == sadd
      and dictionary.team_id_by_name(conn, "Нет Такой Команды") is None)
R(conn, "السد", "Al Sadd", lang="ar")
owner = conn.execute("SELECT team_id FROM team_aliases WHERE alias='السد'").fetchone()[0]
check("С6 новое написание к имени слитой ложится выжившей", owner == sadd, (owner, sadd))
check("С6 event_team_id по имени слитой → выжившая",
      dictionary.event_team_id(conn, "Al Sadd") == sadd)

# С5 — обрывок пары: номера команды для события нет (None, не 0)
check("С5 event_team_id: обрывок пары «La Duchere - Feurs» → None",
      dictionary.event_team_id(conn, "La Duchere - Feurs") is None)

# С10 — «не пара»: имя с тире, признанное одной командой
rc = R(conn, "Banik Most - Sous", "Banik Most - Sous")
old_rows = conn.execute("SELECT count(*) FROM dictionary_errors WHERE alias='Banik Most - Sous' "
                        "AND class='пара'").fetchone()[0]
check("С10 до решения имя с тире не заводится (С5), строка «пара» в книге",
      rc == 0 and old_rows == 1, (rc, old_rows))
new = dictionary.confirm_team_name(conn, "Banik Most - Sous",
                                   "поиск: клуб из Моста — https://example.org/banik")
conn.commit()
banik = R(conn, "Banik Most - Sous", "Banik Most - Sous")
check("С10 после решения «не пара» команда заводится", new and banik > 0, (new, banik))
got = R(conn, "Баник Мост - Соуш", "Banik Most - Sous", lang="ru")
check("С10 написание с тире к такой команде цепляется и отдаётся словарём",
      got == banik and dictionary.team_alias_map(conn).get("Баник Мост - Соуш", (0, ""))[1]
      == "Banik Most - Sous", dictionary.team_alias_map(conn).get("Баник Мост - Соуш"))
left = {r[0]: r[1] for r in conn.execute(
    "SELECT class, count(*) FROM dictionary_errors WHERE alias='Banik Most - Sous' GROUP BY class")}
check("С10 прежняя строка «пара» про это имя переведена в «снято», решение — одно",
      left == {"снято": 1, "не пара": 1}, left)
check("С10 повтор решения строку не плодит",
      not dictionary.confirm_team_name(conn, "Banik Most - Sous", "повтор"))
att = conn.execute("SELECT count(*) FROM team_aliases WHERE alias='Genoa - Milan'").fetchone()[0]
R(conn, "Genoa - Milan", "Genoa")
check("С10 чужая пара матча по-прежнему не цепляется (С5)",
      conn.execute("SELECT count(*) FROM team_aliases WHERE alias='Genoa - Milan'").fetchone()[0]
      == att == 0, att)

# С11 — слово владельца снимает карантин
sociedad = R(conn, "Real Sociedad", "Real Sociedad")
R(conn, "Реал С.", "Real Sociedad")
dictionary.note_error(conn, "Реал С.", "коллизия", team_id=sociedad,
                      led_to="Real Sociedad", truth="Real Madrid")
conn.commit()
check("С11 до слова владельца написание в карантине молчит",
      "Реал С." not in dictionary.team_alias_map(conn))
R(conn, "Реал С.", "Real Sociedad", sole=True)                # кнопка ✎, та же команда
check("С11 кнопка ✎ в ту же команду снимает карантин — словарь отвечает",
      dictionary.team_alias_map(conn).get("Реал С.", (0, ""))[1] == "Real Sociedad",
      dictionary.team_alias_map(conn).get("Реал С."))
row = conn.execute("SELECT class, note, answered_by FROM dictionary_errors "
                   "WHERE alias='Реал С.'").fetchone()
check("С11 строка книги не стёрта: «снято», прежний класс в заметке, ответил владелец",
      row is not None and row[0] == "снято" and "было: коллизия" in row[1]
      and row[2] == "владелец", row and tuple(row))
osasuna = R(conn, "Osasuna", "Osasuna")
R(conn, "Осасуна П.", "Osasuna")
R(conn, "Осасуна Б.", "Osasuna")
for alias in ("Осасуна П.", "Осасуна Б."):
    dictionary.note_error(conn, alias, "коллизия", team_id=osasuna, led_to="Osasuna")
    dictionary.enqueue(conn, "team", alias, suggestion="Osasuna")
conn.commit()
ids = {r["raw_value"]: r["id"] for r in conn.execute(
    "SELECT id, raw_value FROM moderation WHERE raw_value LIKE 'Осасуна%'")}
dictionary.resolve(conn, ids["Осасуна П."], "Osasuna",
                   answered_by="ответила программа: проба")
dictionary.resolve(conn, ids["Осасуна Б."], "Osasuna")        # ответил владелец
m_q = dictionary.team_alias_map(conn)
check("С11 ответ ПРОГРАММЫ в очереди карантин не снимает", "Осасуна П." not in m_q)
check("С11 ответ ВЛАДЕЛЬЦА в очереди карантин снимает",
      m_q.get("Осасуна Б.", (0, ""))[1] == "Osasuna", m_q.get("Осасуна Б."))
dictionary.enqueue(conn, "team", "Villarreal - Paris-SG", suggestion="Villarreal")
studio = conn.execute("SELECT id FROM moderation WHERE raw_value='Villarreal - Paris-SG'").fetchone()[0]
dictionary.resolve(conn, studio, "Villarreal")
check("С11 ответ в очереди строку с парой написанием не делает (книга 094)",
      conn.execute("SELECT count(*) FROM team_aliases WHERE alias='Villarreal - Paris-SG'").fetchone()[0] == 0)
duchere = R(conn, "Lyon - La Duchère", "Lyon-La Duchere", sole=True)   # ✎: явная правка
check("С11/С10 кнопка ✎ цепляет написание с тире и пишет решение «не пара» от владельца",
      conn.execute("SELECT team_id FROM team_aliases WHERE alias='Lyon - La Duchère'").fetchone()[0] == duchere
      and conn.execute("SELECT answered_by FROM dictionary_errors WHERE alias='Lyon - La Duchère' "
                       "AND class='не пара'").fetchone()[0] == "владелец")

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
check("С10 загрузка в чистую базу: команда с тире заведена, её написание с тире — при ней",
      fresh.execute("SELECT count(*) FROM team_aliases a JOIN teams t ON t.id = a.team_id "
                    "WHERE t.canonical_name='Banik Most - Sous' AND a.alias='Баник Мост - Соуш'"
                    ).fetchone()[0] == 1)
fresh.close()

# С5 — сверка (`canon_backfill.py`) на игре, где сторона эталона — обрывок пары:
# не падает, стороне-обрывку команду не ставит, обычной — ставит (ревизия 09.11:
# раньше в событие шёл 0 и UPDATE падал на внешнем ключе)
import subprocess  # noqa: E402
os.environ["STREAMS_DB"] = str(TMP / "backfill.db")
bf = db.connect()
db.init_db(bf)
bf.execute("INSERT INTO events (sport, start_utc, start_kyiv, team_home_auto, team_away_auto, flags) "
           "VALUES ('F', '2026-11-15 14:00', '2026-11-15 16:00', 'Lyon', 'La Duchere - Feurs', 'fs:abc12345')")
# вторая игра: «команда» с именем-обрывком в базе УЖЕ лежит (заведена до карточки)
bf.execute("INSERT INTO teams (canonical_name, slug) VALUES ('Sous B - Nestemice', 'sous-b-nestemice')")
bf.execute("INSERT INTO events (sport, start_utc, start_kyiv, team_home_auto, team_away_auto, flags) "
           "VALUES ('F', '2026-11-15 11:00', '2026-11-15 13:00', 'Banik Most', 'Sous B - Nestemice', 'fs:def67890')")
bf.commit()
bf.close()
games_file = TMP / "games.json"
games_file.write_text(json.dumps({"games": [], "эталон": [{
    "sport": "F", "home": "Lyon", "away": "La Duchere - Feurs", "fs_id": "abc12345",
    "league": "FRANCE: Coupe de France", "start_kyiv": "2026-11-15T16:00", "names": {}}, {
    "sport": "F", "home": "Banik Most", "away": "Sous B - Nestemice", "fs_id": "def67890",
    "league": "CZECH REPUBLIC: Ustecky KP", "start_kyiv": "2026-11-15T13:00", "names": {}}]},
    ensure_ascii=False), encoding="utf-8")
run = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "canon_backfill.py"),
                      "--file", str(games_file)], capture_output=True, text=True,
                     encoding="utf-8", errors="replace", env=dict(os.environ))
bf = db.connect()
row = bf.execute("SELECT th.canonical_name, e.team_away_id FROM events e "
                 "LEFT JOIN teams th ON th.id = e.team_home_id WHERE e.flags = 'fs:abc12345'").fetchone()
row2 = bf.execute("SELECT th.canonical_name, e.team_away_id FROM events e "
                  "LEFT JOIN teams th ON th.id = e.team_home_id WHERE e.flags = 'fs:def67890'").fetchone()
bf.close()
check("С5 сверка на обрывке пары не падает", run.returncode == 0, (run.stdout + run.stderr)[-600:])
check("С5 сверка: обычной стороне команда поставлена, обрывку — нет",
      row is not None and row[0] == "Lyon" and row[1] is None, row and tuple(row))
check("С5 сверка: «команда»-обрывок, уже лежащая в базе, игре тоже не ставится",
      row2 is not None and row2[0] == "Banik Most" and row2[1] is None, row2 and tuple(row2))
print(f"\n{green}/{total} зелёных")
raise SystemExit(0 if green == total else 1)

# -*- coding: utf-8 -*-
r"""Проверки очереди «Названия» по командам (разбор 06.10, #2100).

Владелец: «почему эта игра попадает в этот отчёт с такой кривой
информацией, если на витрине правильное написание?» — запись «Igokea» с
подсказкой «Slavia Prague ERA NBK». Эталон дня был сдвинут, своей игры в
нём не нашлось, и сопоставитель отдал паре «с сомнением» соседний матч
того же часа. Правила постановки в очередь — `app/canon.py:
queue_decision`, уборка открытых записей — `scripts/review_queue.py
--kind team`. Каждому правилу — сценарий с говорящим именем.

В сеть не ходит. База — пустая, во временной папке. Запуск:

    python scripts/test_queue.py

Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="queue-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test0.db")

from app import canon, db, names  # noqa: E402
import review_queue  # noqa: E402

passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def fresh_db():
    # своя база на сценарий: прошлую Windows держит открытой до конца
    fresh_db.n = getattr(fresh_db, "n", 0) + 1
    os.environ["STREAMS_DB"] = str(TMP / f"test{fresh_db.n}.db")
    conn = db.connect()
    db.init_db(conn)
    names.set_overrides({})
    return conn


def team(conn, canonical, *aliases):
    team_id = conn.execute(
        "INSERT INTO teams (canonical_name, slug) VALUES (?, ?)",
        (canonical, canonical.lower().replace(" ", "-"))).lastrowid
    for alias in aliases:
        conn.execute("INSERT INTO team_aliases (team_id, alias) VALUES (?, ?)",
                     (team_id, alias))
    conn.commit()
    return team_id


def event(conn, sport, home, away, start_kyiv, flags=None, home_id=None,
          away_id=None):
    return conn.execute(
        "INSERT INTO events (sport, team_home_auto, team_away_auto, "
        "team_home_id, team_away_id, start_utc, start_kyiv, flags) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (sport, home, away, home_id, away_id, start_kyiv, start_kyiv,
         flags)).lastrowid


def game(home, away, start="2026-10-06T21:00", sport="F", league=""):
    return {"sport": sport, "league": league, "home": home, "away": away,
            "start_kyiv": start, "start_utc": "", "entries": []}


def ref(home, away, start="2026-10-06T21:00", sport="F", league="",
        fs_id="fs1"):
    return {"sport": sport, "home": home, "away": away, "league": league,
            "start_kyiv": start, "fs_id": fs_id}


def queued(conn):
    return [(r["raw_value"], r["suggestion"]) for r in conn.execute(
        "SELECT raw_value, suggestion FROM moderation WHERE kind = 'team' "
        "AND status = 'open' ORDER BY id")]


def ask_only(game_, ref_):
    """Пара «с сомнением» как её отдаёт `align` — для правил по одному."""
    return {"sure": [], "ask": [(game_, ref_, canon.LONE_HE)], "missed": []}


# ── случай владельца: Igokea — Bilbao (скан #204, 06.10) ──────────────────────

# эталон дня был сдвинут: матча Igokea — Bilbao в нём нет, а в окне ±3 ч
# стоят восемь чужих матчей той же Лиги чемпионов (выписка из #204)
CL = "EUROPE: Champions League"
CL_SITE = "Лига Чемпионов Прямая трансляция"
REF_204 = [ref(h, a, f"2026-10-06T{t}", "B", CL, i) for h, a, t, i in (
    ("AEK Athens", "Salon Vilpas", "19:00", "Ikowaebt"),
    ("Slavia Prague ERA NBK", "Alba Berlin", "19:00", "xEGk1Ms3"),
    ("Trabzonspor", "Nanterre", "19:00", "8OJZzBB7"),
    ("Juventus", "Unicaja", "20:00", "xfvEn2BC"),
    ("Antwerp Giants", "Szombathely", "21:00", "Eaav9eNj"),
    ("Bonn", "FC Porto", "21:00", "tSn4FC2D"),
    ("Spartak Subotica", "Vechta", "21:00", "8xNfwuxK"),
    ("Murcia", "Varese", "21:30", "EJkYUxpA"))]
IGOKEA = game("Igokea", "Bilbao", "2026-10-06T20:55", "B", CL_SITE)

print("Случай владельца #2100")
conn = fresh_db()
igokea_id = team(conn, "Igokea", "Igokea")
bilbao_id = team(conn, "Bilbao", "Bilbao")
team(conn, "Slavia Prague ERA NBK")
event(conn, "B", "Igokea", "Bilbao", "2026-10-06 21:00", "fs:Ol1G4ele",
      igokea_id, bilbao_id)
conn.commit()
aligned = canon.align([dict(IGOKEA)], REF_204, {CL_SITE: CL})
pair = [(g["home"], r["home"]) for g, r, _ in aligned["ask"]]
check("igokea_сопоставитель_отдаёт_соседний_матч_с_сомнением",
      pair == [("Igokea", "Slavia Prague ERA NBK")], pair)
canon.apply(conn, aligned)
check("igokea_в_очередь_не_ложится", queued(conn) == [], queued(conn))
g, r, _ = aligned["ask"][0]
check("igokea_причина_имя_уже_в_библиотеке",
      canon.queue_decision(conn, g, r, "home")
      == (False, "имя уже в библиотеке"),
      canon.queue_decision(conn, g, r, "home"))

# та же пара, но имён в библиотеке нет и события нет: спасает правило 5 —
# Bilbao против Alba Berlin (60) не совпал, значит это другая игра
conn = fresh_db()
aligned = canon.align([dict(IGOKEA)], REF_204, {CL_SITE: CL})
canon.apply(conn, aligned)
check("igokea_без_словаря_тоже_не_ложится__вторая_не_совпала",
      queued(conn) == [], queued(conn))
g, r, _ = aligned["ask"][0]
check("igokea_без_словаря_причина",
      canon.queue_decision(conn, g, r, "home")
      == (False, "вторая команда не совпала — другая игра"),
      canon.queue_decision(conn, g, r, "home"))

# ── правила по одному ───────────────────────────────────────────────────────

print("Правила queue_decision")
# настоящий вопрос: соперник узнан дословно, а «Queens Park Rangers» у
# flashscore пишется «QPR» — это новое написание реальной команды
QPR = game("Queens Park Rangers", "West Ham")
QPR_REF = ref("QPR", "West Ham")
conn = fresh_db()
canon.apply(conn, ask_only(dict(QPR), QPR_REF))
check("настоящий_вопрос_по_прежнему_в_очередь",
      queued(conn) == [("Queens Park Rangers", "QPR")], queued(conn))

# имя — канон команды
conn = fresh_db()
team(conn, "Queens Park Rangers")
check("имя_канон_не_спрашиваем",
      canon.queue_decision(conn, dict(QPR), QPR_REF, "home")
      == (False, "имя уже в библиотеке"))
# имя — алиас команды
conn = fresh_db()
team(conn, "Queens Park", "Queens Park Rangers")
check("имя_алиас_не_спрашиваем",
      canon.queue_decision(conn, dict(QPR), QPR_REF, "home")
      == (False, "имя уже в библиотеке"))
# канон есть, но команда другого вида спорта — имя этому виду не известно
conn = fresh_db()
other = team(conn, "Queens Park Rangers")
event(conn, "B", "Queens Park Rangers", "Somebody", "2026-09-01 20:00",
      None, other, None)
conn.commit()
check("канон_чужого_вида_спорта_не_мешает_вопросу",
      canon.queue_decision(conn, dict(QPR), QPR_REF, "home") == (True, ""),
      canon.queue_decision(conn, dict(QPR), QPR_REF, "home"))

# игра уже с меткой flashscore (событие в базе, время в окне, имена те же)
conn = fresh_db()
event(conn, "F", "Queens Park Rangers", "West Ham", "2026-10-06 21:00",
      "fs:abc")
conn.commit()
canon.apply(conn, ask_only(dict(QPR), QPR_REF))
check("игра_с_fs_не_спрашиваем", queued(conn) == [], queued(conn))
check("игра_с_fs_причина",
      canon.queue_decision(conn, dict(QPR), QPR_REF, "home")
      == (False, "игра уже сопоставлена с эталоном"))
# метка у события сверки задним числом — по номеру события
conn = fresh_db()
eid = event(conn, "F", "Queens Park Rangers", "West Ham", "2026-10-06 21:00",
            "fs:abc")
conn.commit()
check("игра_с_fs_по_номеру_события",
      canon.queue_decision(conn, dict(QPR, id=eid), QPR_REF, "home")[0]
      is False)
# метка у матча ДРУГОГО дня тех же команд — не наша игра, вопрос остаётся
conn = fresh_db()
event(conn, "F", "Queens Park Rangers", "West Ham", "2026-12-20 18:00",
      "fs:xyz")
conn.commit()
check("fs_у_ответного_матча_не_мешает",
      canon.queue_decision(conn, dict(QPR), QPR_REF, "home") == (True, ""))
# та же пара в этом же прогоне уже легла в «уверенные»
conn = fresh_db()
twin = dict(QPR, start_kyiv="2026-10-06T20:45")
check("пара_в_sure_не_спрашиваем",
      canon.queue_decision(conn, dict(QPR), QPR_REF, "home",
                           canon._sure_times([(twin, QPR_REF, 100)]))
      == (False, "игра уже сопоставлена с эталоном"))

# вторая команда не совпала — другая игра того же часа (скан даты 03.10:
# «Zwitserland — Slowenien» легла на «Netherlands — Serbia», 63 и 57)
conn = fresh_db()
canon.apply(conn, ask_only(game("Zwitserland", "Slowenien"),
                           ref("Netherlands", "Serbia")))
check("вторая_не_совпала_не_спрашиваем", queued(conn) == [], queued(conn))
# вторая — заглушка: подтвердить игру нечем
check("вторая_заглушка_не_спрашиваем",
      canon.queue_decision(conn, game("Queens Park Rangers", "TBC"),
                           ref("QPR", "West Ham"), "home")
      == (False, "вторая команда не совпала — другая игра"))
# подсказка совсем не похожа на имя (Denizli → Karsiyaka: 12)
check("подсказка_не_похожа_не_спрашиваем",
      canon.queue_decision(conn, game("Denizli", "West Ham"),
                           ref("Karsiyaka", "West Ham"), "home")
      == (False, "подсказка не похожа на имя"))
# заглушка вместо имени
check("заглушка_не_спрашиваем",
      canon.queue_decision(conn, game("TBC", "West Ham"),
                           ref("QPR", "West Ham"), "home")
      == (False, "не имя команды"))
# пороги — именованные константы
check("пороги_константы",
      canon.QUEUE_OTHER_SIDE == canon.SURE and canon.QUEUE_HINT_MIN == 50)

# ── уборка открытых записей: review_queue.py --kind team ─────────────────────

print("Уборка очереди «Команды»")
conn = fresh_db()
igokea_id = team(conn, "Igokea", "Igokea")
event(conn, "B", "Igokea", "Bilbao", "2026-10-06 21:00", "fs:Ol1G4ele",
      igokea_id, None)
# имя не в словаре, но все его игры уже сопоставлены с эталоном
event(conn, "F", "Sparta Rotterdam Jong", "Ajax", "2026-10-06 18:00",
      "fs:q1")
# настоящий вопрос: имени нет в словаре, игра без метки
event(conn, "F", "Queens Park Rangers", "West Ham", "2026-10-06 21:00")
# имя в словаре, но запись «Не знаю» (отложена) — тоже отпала
team(conn, "Lithuania", "Λιθουανία")
for raw, hint, status in (("Igokea", "Slavia Prague ERA NBK", "open"),
                          ("Sparta Rotterdam Jong", "Feyenoord", "open"),
                          ("Queens Park Rangers", "QPR", "open"),
                          ("Λιθουανία", "Andorra", "later"),
                          ("Igokea", "что-то", "done")):
    conn.execute("INSERT INTO moderation (kind, raw_value, suggestion, status) "
                 "VALUES ('team', ?, ?, ?)", (raw, hint, status))
conn.commit()
res = review_queue.team_closures(conn)
got = {k: sorted(r["raw_value"] for r in v) for k, v in res.items()}
check("уборка_имя_в_словаре",
      got["имя уже в словаре"] == ["Igokea", "Λιθουανία"], got)
check("уборка_игра_с_fs",
      got["игра с меткой flashscore"] == ["Sparta Rotterdam Jong"], got)
review_queue.review_teams(conn, apply=False)
check("уборка_без_apply_ничего_не_меняет",
      conn.execute("SELECT COUNT(*) FROM moderation WHERE kind = 'team' "
                   "AND status IN ('open', 'later')").fetchone()[0] == 4)
review_queue.review_teams(conn, apply=True)
left = [r["raw_value"] for r in conn.execute(
    "SELECT raw_value FROM moderation WHERE kind = 'team' "
    "AND status IN ('open', 'later')")]
check("уборка_настоящий_вопрос_остался", left == ["Queens Park Rangers"], left)
check("уборка_закрывает_в_отсеянные",
      conn.execute("SELECT COUNT(*) FROM moderation WHERE kind = 'team' "
                   "AND status = 'skipped'").fetchone()[0] == 3)
check("уборка_пишет_строку_в_прогоны",
      "закрыто 3" in (conn.execute("SELECT log FROM runs ORDER BY id DESC "
                                   "LIMIT 1").fetchone()[0] or ""))
check("уборка_решённое_не_трогает",
      conn.execute("SELECT status FROM moderation WHERE suggestion = 'что-то'"
                   ).fetchone()[0] == "done")

print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, красных: {len(failed)}")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)

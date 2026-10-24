# -*- coding: utf-8 -*-
r"""Перенос матча эталоном (слово владельца 24.10.2026 после #7836):
«строка сайта со старой датой — канал у перенесённой игры с «время?», и
пометка «перенесён с …» у перенесённой игры».

Кейс: flashscore перенёс Toulouse — Troyes с субботы на воскресенье; игра
#6792 уехала со всеми каналами, а tvarenasport.ba ещё писал субботу — его
строка завела вторую игру (#7836) с одним каналом.

Проверяет:
 A. триггер `events_moved_from_v1` (`app/db.py`, правила 1–4);
 B. заливку `store.save_games` с правилом переноса (`store._moved_event`,
    правила 1–4, и `_fold_ghost` — тень вливается, чужие отметки целы);
 C. витрину: «перенесён с …» под матчем.

Запуск: python scripts/test_perenos.py — в сеть не ходит, база временная.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="perenos-test-"))
(TMP / "visits").mkdir()
os.environ.update(STREAMS_DB=str(TMP / "test.db"), STREAMS_ADMIN_PASSWORD="adm-test-1",
                  SECRET_KEY="k" * 32, STREAMS_VISITS_DIR=str(TMP / "visits"))
os.environ.pop("STREAMS_LOCAL", None)

from app import db, dictionary, store, visits  # noqa: E402

visits.write = lambda *a, **k: None

passed, failed = 0, []
NOW = datetime(2026, 12, 4, 10, 0)     # сбор — до обеих дат матча
SAT, SUN = "2026-12-05 18:15", "2026-12-06 18:15"


def check(name: str, cond: bool, extra="") -> None:
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def fresh(name: str = "test.db"):
    """Новая база: сайты BA, CY, HR и их каналы. `name` — свой файл, когда
    прежний ещё держит открытым сайт из раздела C."""
    path = TMP / name
    os.environ["STREAMS_DB"] = str(path)
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    conn = db.connect()
    db.init_db(conn)
    for dom, cc in (("tvarenasport.ba", "BA"), ("epg.cyta.com.cy", "CY"),
                    ("tvarenasport.hr", "HR")):
        conn.execute("INSERT INTO sources (domain, name, base_url, country, timezone, "
                     "enabled, role, access, status) VALUES (?, ?, ?, ?, 'Europe/Belgrade', "
                     "1, 'schedule', 'open', 'ok')", (dom, dom, f"https://{dom}/", cc))
    src = {r["domain"]: r["id"] for r in conn.execute("SELECT id, domain FROM sources")}
    ch = {
        "ba": dictionary.remember_channel(conn, "Arena Sport 4", "Arena Sport 4", "BA",
                                          source_id=src["tvarenasport.ba"]),
        "cy": dictionary.remember_channel(conn, "Cablenet Sport 2", "Cablenet Sport 2", "CY",
                                          source_id=src["epg.cyta.com.cy"]),
        "hr": dictionary.remember_channel(conn, "Arena Sport 10", "Arena Sport 10", "HR",
                                          source_id=src["tvarenasport.hr"]),
    }
    conn.commit()
    return conn, src, ch


def event(conn, start, home="TOULOUSE", away="TROYES", flags="fs:EqTN") -> int:
    cur = conn.execute(
        "INSERT INTO events (sport, league_auto, team_home_auto, team_away_auto, "
        "start_utc, start_kyiv, first_seen, last_seen, flags, seen) "
        "VALUES ('F', 'FRANCUSKA LIGA', ?, ?, ?, ?, '2026-12-01 07:00:00', ?, ?, 1)",
        (home, away, start, start, start, flags))
    conn.commit()
    return cur.lastrowid


def mark(conn, event_id, source_id, channel_id, miss=0):
    conn.execute("INSERT INTO event_channels (event_id, channel_id, source_id, source_url, "
                 "raw_title, first_seen, last_seen, miss_count, seen) "
                 "VALUES (?, ?, ?, '', 'Toulouse - Troyes', '2026-12-01 07:00:00', "
                 "'2026-12-02 07:00:00', ?, 1)", (event_id, channel_id, source_id, miss))
    conn.commit()


def row(start, source="tvarenasport.ba", channel="Arena Sport 4", home="Toulouse",
        away="Troyes"):
    return {"sport": "F", "league": "FRANCUSKA LIGA", "home": home, "away": away,
            "start_kyiv": start, "entries": [{"source": source, "channel": channel,
                                              "url": f"https://{source}/", "raw_title":
                                              f"{home} - {away}"}]}


def marks(conn, event_id):
    return {(r["source_id"], r["channel_id"]): (r["miss_count"], r["time_off"]) for r in
            conn.execute("SELECT * FROM event_channels WHERE event_id = ?", (event_id,))}


def events(conn):
    return [r["id"] for r in conn.execute("SELECT id FROM events ORDER BY id")]


def main() -> int:
    print("A. триггер «перенесён с …»")
    conn, src, ch = fresh()
    e = event(conn, SAT)
    moved = lambda: conn.execute("SELECT moved_from FROM events WHERE id = ?",  # noqa: E731
                                 (e,)).fetchone()[0]
    conn.execute("UPDATE events SET start_kyiv = ? WHERE id = ?", ("2026-12-05T18:15", e))
    check("то же время с «T» — не перенос", moved() is None, moved())
    conn.execute("UPDATE events SET start_kyiv = ? WHERE id = ?", ("2026-12-05 17:15", e))
    check("сдвиг на 1 ч (перевод часов) — не перенос", moved() is None, moved())
    conn.execute("UPDATE events SET start_kyiv = ? WHERE id = ?", (SAT, e))
    conn.execute("UPDATE events SET start_kyiv = ? WHERE id = ?", (SUN, e))
    check("перенос на сутки — прежнее время запомнено", moved() == SAT, moved())
    conn.execute("UPDATE events SET start_kyiv = ? WHERE id = ?", ("2026-12-06 18:00", e))
    check("поправка на 15 мин после переноса — пометка остаётся", moved() == SAT, moved())
    conn.execute("UPDATE events SET start_kyiv = ? WHERE id = ?", ("2026-12-07 21:00", e))
    check("второй перенос — хранится самое первое время", moved() == SAT, moved())
    conn.execute("UPDATE events SET start_kyiv = ? WHERE id = ?", ("2026-12-05 19:00", e))
    check("вернули к прежнему (ближе 3 ч) — пометка снята", moved() is None, moved())
    conn.execute("UPDATE events SET start_kyiv = ? WHERE id = ?", ("2026-12-05 22:00", e))
    check("сдвиг ровно на 3 ч — уже перенос", moved() == "2026-12-05 19:00", moved())
    conn.close()

    print("B1. строка со старой датой, тени ещё нет")
    conn, src, ch = fresh()
    e = event(conn, SUN)
    mark(conn, e, src["tvarenasport.ba"], ch["ba"], miss=2)
    before = events(conn)
    st = store.save_games(conn, [row(SAT)], now=NOW)
    check("вторая игра не заведена", events(conn) == before, events(conn))
    m = marks(conn, e).get((src["tvarenasport.ba"], ch["ba"]))
    check("канал BA у перенесённой игры ожил с «время?»", m == (0, 1), m)
    check("время игры — эталонное (воскресенье)",
          conn.execute("SELECT start_kyiv FROM events WHERE id = ?", (e,)).fetchone()[0] == SUN)
    check("счётчики: перенос 1, «время?» 1", st.moved == 1 and st.time_off == 1,
          (st.moved, st.time_off))
    conn.close()

    print("B2. тень уже есть (её завела строка прошлым сбором)")
    conn, src, ch = fresh()
    e = event(conn, SUN)
    mark(conn, e, src["tvarenasport.ba"], ch["ba"], miss=2)
    ghost = event(conn, SAT, home="Toulouse", away="Troyes", flags=None)
    mark(conn, ghost, src["tvarenasport.ba"], ch["ba"], miss=0)
    st = store.save_games(conn, [row(SAT)], now=NOW)
    check("тень влита и убрана", ghost not in events(conn) and st.ghosts == 1,
          (events(conn), st.ghosts))
    check("у перенесённой игры канал BA живой с «время?»",
          marks(conn, e).get((src["tvarenasport.ba"], ch["ba"])) == (0, 1), marks(conn, e))
    conn.close()

    print("B3. у тени есть канал другого сайта — его не трогаем")
    conn, src, ch = fresh()
    e = event(conn, SUN)
    mark(conn, e, src["tvarenasport.ba"], ch["ba"], miss=2)
    ghost = event(conn, SAT, home="Toulouse", away="Troyes", flags=None)
    mark(conn, ghost, src["tvarenasport.ba"], ch["ba"])
    mark(conn, ghost, src["epg.cyta.com.cy"], ch["cy"])
    st = store.save_games(conn, [row(SAT)], now=NOW)
    gm = marks(conn, ghost)
    check("тень осталась с каналом CY, без BA",
          ghost in events(conn) and set(gm) == {(src["epg.cyta.com.cy"], ch["cy"])}, gm)
    check("BA — у перенесённой игры", (src["tvarenasport.ba"], ch["ba"]) in marks(conn, e))
    conn.close()

    print("B4. другой сайт, у игры эталона его отметки не было — не перенос")
    conn, src, ch = fresh()
    e = event(conn, SUN)
    mark(conn, e, src["tvarenasport.ba"], ch["ba"], miss=2)
    before = events(conn)
    st = store.save_games(conn, [row(SAT, source="epg.cyta.com.cy",
                                     channel="Cablenet Sport 2")], now=NOW)
    check("строка CY завела свою игру (как раньше)", len(events(conn)) == len(before) + 1
          and st.moved == 0, (events(conn), st.moved))
    check("канал BA у игры эталона не тронут",
          marks(conn, e).get((src["tvarenasport.ba"], ch["ba"])) == (2, 0))
    conn.close()

    print("B5. два кандидата (лига и кубок) — не гадаем")
    conn, src, ch = fresh()
    e1 = event(conn, SUN, flags="fs:AAA")
    e2 = event(conn, "2026-12-04 20:00", flags="fs:BBB")
    for x in (e1, e2):
        mark(conn, x, src["tvarenasport.ba"], ch["ba"], miss=1)
    st = store.save_games(conn, [row(SAT)], now=NOW)
    check("ни к одной не прилипло", st.moved == 0
          and marks(conn, e1)[(src["tvarenasport.ba"], ch["ba"])] == (1, 0)
          and marks(conn, e2)[(src["tvarenasport.ba"], ch["ba"])] == (1, 0))
    conn.close()

    print("B6. другие команды — не перенос")
    conn, src, ch = fresh()
    e = event(conn, SUN)
    mark(conn, e, src["tvarenasport.ba"], ch["ba"], miss=2)
    st = store.save_games(conn, [row(SAT, home="Lens", away="Nantes")], now=NOW)
    check("не прилипло", st.moved == 0
          and marks(conn, e)[(src["tvarenasport.ba"], ch["ba"])] == (2, 0))
    conn.close()

    print("B7. дальше двух суток — не перенос")
    conn, src, ch = fresh()
    e = event(conn, "2026-12-08 18:15")
    mark(conn, e, src["tvarenasport.ba"], ch["ba"], miss=2)
    st = store.save_games(conn, [row(SAT)], now=NOW)
    check("не прилипло", st.moved == 0)
    conn.close()

    print("B8. обычная строка в окне склейки — как раньше")
    conn, src, ch = fresh()
    e = event(conn, SUN)
    mark(conn, e, src["tvarenasport.ba"], ch["ba"], miss=2)
    st = store.save_games(conn, [row("2026-12-06 18:30", source="tvarenasport.hr",
                                     channel="Arena Sport 10")], now=NOW)
    check("строка HR легла к игре без «время?», перенос не сработал",
          st.moved == 0 and marks(conn, e).get((src["tvarenasport.hr"], ch["hr"])) == (0, 0),
          marks(conn, e))
    conn.close()

    print("C. витрина")
    conn, src, ch = fresh()
    e = event(conn, SAT)
    mark(conn, e, src["tvarenasport.hr"], ch["hr"])
    conn.execute("UPDATE events SET start_kyiv = ?, start_utc = ? WHERE id = ?", (SUN, SUN, e))
    conn.commit()
    games = {g["id"]: g for g in store.schedule(conn)}
    check("в данных витрины — «05.12 18:15»", games.get(e, {}).get("moved_from") == "05.12 18:15",
          games.get(e, {}).get("moved_from"))
    conn.close()
    from app import web
    page = web.create_app().test_client().get("/schedule").get_data(as_text=True)
    check("на странице — «перенесён с 05.12 18:15»", "перенесён с 05.12 18:15" in page)

    print("D. разовая пометка по снимкам (`moved_backfill.py`)")
    import importlib.util

    spec = importlib.util.spec_from_file_location("moved_backfill",
                                                  ROOT / "scripts" / "moved_backfill.py")
    mb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mb)
    conn, src, ch = fresh("d.db")
    a = event(conn, SAT)                          # потом перенесут на сутки
    b = event(conn, "2026-12-05 20:00")           # потом поправят на 1 ч
    c = event(conn, "2026-12-05 21:00")           # перенесут и вернут назад
    conn.commit()
    snap1 = TMP / "snap1.db"
    conn.execute(f"VACUUM INTO '{snap1.as_posix()}'")
    # сдвиги «в прошлом», до триггера: снимаем его на время подготовки
    conn.execute("DROP TRIGGER IF EXISTS events_moved_from_v1")
    conn.execute("UPDATE events SET start_kyiv = ? WHERE id = ?", (SUN, a))
    conn.execute("UPDATE events SET start_kyiv = '2026-12-05 21:00' WHERE id = ?", (b,))
    conn.execute("UPDATE events SET start_kyiv = '2026-12-06 21:00' WHERE id = ?", (c,))
    conn.commit()
    snap2 = TMP / "snap2.db"
    conn.execute(f"VACUUM INTO '{snap2.as_posix()}'")
    conn.execute("UPDATE events SET start_kyiv = '2026-12-05 21:30' WHERE id = ?", (c,))
    conn.commit()
    first = mb.earliest([str(snap1), str(snap2)])
    check("самое раннее время — из первого снимка", first.get(a) == SAT, first.get(a))
    todo = {x[0]: x for x in mb.plan(conn, first, NOW)}
    check("перенос на сутки — в списке", a in todo and todo[a][1] == SAT, todo.get(a))
    check("поправка на 1 ч — не перенос", b not in todo)
    check("вернули назад (ближе 3 ч) — не перенос", c not in todo)
    check("прошедшая игра не трогается", not mb.plan(conn, first, datetime(2027, 1, 1)))
    conn.close()

    print(f"\nПроверок: {passed + len(failed)}, провалов: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

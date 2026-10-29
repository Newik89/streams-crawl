# -*- coding: utf-8 -*-
r"""«Время?» у канала — по времени самого канала; строки старой сетки у
перенесённой игры (пачка 28.10, слово владельца 29.10).

A. #8223 Ливерпуль — Арсенал 01.11: teleman.pl ставил матч на 15:55, все
   остальные сайты и flashscore — на 18:30. Строка teleman слиплась с игрой,
   время склейки стало 15:55, и пометку «время?» получили все 20 каналов.
   Теперь пометку ставит `store._time_off` по времени КАЖДОЙ строки.
B. #7999 Ницца — Ренн: flashscore перенёс игру с сб 31.10 18:15 на пт 30.10
   20:00; сайты ещё держали субботу, разбор снимал их строки как повтор
   сыгранного матча, и каналы на витрине стали «снят». Теперь
   `store._keep_moved` оставляет канал у игры с «время?» (правила 1–4).

Запуск: python scripts/test_vremya_kanala.py — в сеть не ходит, база временная.
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

TMP = Path(tempfile.mkdtemp(prefix="vremya-kanala-test-"))
(TMP / "visits").mkdir()
os.environ.update(STREAMS_DB=str(TMP / "test.db"), STREAMS_ADMIN_PASSWORD="adm-test-1",
                  SECRET_KEY="k" * 32, STREAMS_VISITS_DIR=str(TMP / "visits"))
os.environ.pop("STREAMS_LOCAL", None)

from app import db, dictionary, store, visits  # noqa: E402

visits.write = lambda *a, **k: None

passed, failed = 0, []
NOW = datetime(2026, 12, 3, 10, 0)          # сбор — до обеих дат матча
SAT, FRI = "2026-12-05 18:15", "2026-12-04 20:00"
SITES = (("teleman.pl", "PL", "Eleven Sports 4"), ("tvarenasport.ba", "BA", "Arena Sport 4"),
         ("epg.cyta.com.cy", "CY", "Cablenet Sport 2"), ("tvarenasport.com", "RS", "Arena Sport 6"))


def check(name: str, cond: bool, extra="") -> None:
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def fresh(name: str):
    path = TMP / name
    os.environ["STREAMS_DB"] = str(path)
    conn = db.connect()
    db.init_db(conn)
    for dom, cc, _ in SITES:
        conn.execute("INSERT INTO sources (domain, name, base_url, country, timezone, "
                     "enabled, role, access, status) VALUES (?, ?, ?, ?, 'Europe/Belgrade', "
                     "1, 'schedule', 'open', 'ok')", (dom, dom, f"https://{dom}/", cc))
    src = {r["domain"]: r["id"] for r in conn.execute("SELECT id, domain FROM sources")}
    ch = {dom: dictionary.remember_channel(conn, chan, chan, cc, source_id=src[dom])
          for dom, cc, chan in SITES}
    conn.commit()
    return conn, src, ch


def event(conn, start, flags="fs:dOOA5B3D") -> int:
    cur = conn.execute(
        "INSERT INTO events (sport, league_auto, team_home_auto, team_away_auto, "
        "start_utc, start_kyiv, first_seen, last_seen, flags, seen) "
        "VALUES ('F', 'FRANCUSKA LIGA', 'Nice', 'Rennes', ?, ?, '2026-12-01 07:00:00', ?, ?, 1)",
        (start, start, start, flags))
    conn.commit()
    return cur.lastrowid


def moved_event(conn) -> int:
    """Игра, которую эталон перенёс с субботы на пятницу (триггер пишет
    `moved_from`)."""
    e = event(conn, SAT)
    conn.execute("UPDATE events SET start_kyiv = ? WHERE id = ?", (FRI, e))
    conn.commit()
    return e


def mark(conn, event_id, source_id, channel_id, miss=0):
    conn.execute("INSERT INTO event_channels (event_id, channel_id, source_id, source_url, "
                 "raw_title, first_seen, last_seen, miss_count, seen) "
                 "VALUES (?, ?, ?, '', 'Nice - Rennes', '2026-12-01 07:00:00', "
                 "'2026-12-02 07:00:00', ?, 1)", (event_id, channel_id, source_id, miss))
    conn.commit()


def marks(conn, event_id):
    return {r["source_id"]: (r["miss_count"], r["time_off"]) for r in
            conn.execute("SELECT * FROM event_channels WHERE event_id = ?", (event_id,))}


def entry(source, start=None):
    chan = {d: c for d, _, c in SITES}[source]
    out = {"source": source, "channel": chan, "url": f"https://{source}/",
           "raw_title": "Liverpool - Arsenal"}
    if start:
        out["start_kyiv"] = start
    return out


def game(entries, start, fs="xxDTaeAO", fs_start="2026-12-06T18:30"):
    """Игра файла, как её отдаёт `games_import` после сверки с эталоном."""
    return {"sport": "F", "league": "Premier League", "home": "Liverpool",
            "away": "Arsenal", "start_kyiv": start, "fs_id": fs, "fs_start": fs_start,
            "entries": entries}


def snyato(domain, chan, when, fs="dOOA5B3D", filtr=store.ПОВТОР_СЫГРАН + ": матч уже сыгран"):
    return {"фильтр": filtr, "домен": domain, "канал": chan, "заголовок": "Nice - Rennes",
            "start_kyiv": when.replace(" ", "T"), "почему": "эталон", "fs_id": fs}


def main() -> int:
    print("A1. #8223: красным — только канал, чьё время другое")
    conn, src, ch = fresh("a1.db")
    e = event(conn, "2026-12-06 18:30", flags="fs:xxDTaeAO")
    g = game([entry("teleman.pl", "2026-12-06T15:55"),
              entry("tvarenasport.ba", "2026-12-06T18:30"),
              entry("epg.cyta.com.cy", "2026-12-06T18:25")], "2026-12-06T15:55")
    st = store.save_games(conn, [g], now=NOW)
    m = marks(conn, e)
    check("teleman (15:55 при эталоне 18:30) — «время?»", m.get(src["teleman.pl"]) == (0, 1), m)
    check("Arena 18:30 — без пометки", m.get(src["tvarenasport.ba"]) == (0, 0), m)
    check("Cyta 18:25 — без пометки", m.get(src["epg.cyta.com.cy"]) == (0, 0), m)
    check("счётчик «время?» — одна строка", st.time_off == 1, st.time_off)
    check("время игры — эталонное 18:30",
          conn.execute("SELECT start_kyiv FROM events WHERE id = ?", (e,)).fetchone()[0]
          == "2026-12-06 18:30")
    conn.close()

    print("A2. файл до 29.10 (у строк нет своего времени) — как было: по времени игры")
    conn, src, ch = fresh("a2.db")
    e = event(conn, "2026-12-06 18:30", flags="fs:xxDTaeAO")
    store.save_games(conn, [game([entry("teleman.pl"), entry("tvarenasport.ba")],
                                 "2026-12-06T15:55")], now=NOW)
    m = marks(conn, e)
    check("обе строки — «время?» (старое поведение)",
          m.get(src["teleman.pl"]) == (0, 1) and m.get(src["tvarenasport.ba"]) == (0, 1), m)
    conn.close()

    print("A3. эталона у игры нет — пометок нет вовсе")
    conn, src, ch = fresh("a3.db")
    g = game([entry("teleman.pl", "2026-12-06T15:55"),
              entry("tvarenasport.ba", "2026-12-06T18:30")], "2026-12-06T15:55",
             fs="", fs_start="")
    st = store.save_games(conn, [g], now=NOW)
    check("ни одной «время?»", st.time_off == 0 and not conn.execute(
        "SELECT 1 FROM event_channels WHERE time_off = 1").fetchone(), st.time_off)
    conn.close()

    print("B0. разбор строк «снято»")
    rows = store.moved_repeat_rows({"снято": [
        snyato("www.tvarenasport.ba", "Arena Sport 4", SAT),
        snyato("teleman.pl", "Eleven Sports 4", SAT, fs=""),
        snyato("teleman.pl", "Eleven Sports 4", SAT, filtr="мультикаст: …")]})
    check("берётся только «повтор по flashscore» с fs_id, домен без www",
          rows == [("tvarenasport.ba", "Arena Sport 4", SAT, "dOOA5B3D")], rows)

    print("B1. #7999: строка старой сетки — канал остаётся у игры с «время?»")
    conn, src, ch = fresh("b1.db")
    e = moved_event(conn)
    check("эталон перенёс игру — прежнее время запомнено",
          conn.execute("SELECT moved_from FROM events WHERE id = ?", (e,)).fetchone()[0] == SAT)
    mark(conn, e, src["tvarenasport.ba"], ch["tvarenasport.ba"], miss=1)
    mark(conn, e, src["epg.cyta.com.cy"], ch["epg.cyta.com.cy"], miss=1)
    st = store.save_games(conn, [], now=NOW,
                          moved_rows=[("tvarenasport.ba", "Arena Sport 4", "2026-12-05 18:10",
                                       "dOOA5B3D")])
    m = marks(conn, e)
    check("Arena BA ожила с «время?»", m.get(src["tvarenasport.ba"]) == (0, 1), m)
    check("Cyta (её строки нет) не тронута", m.get(src["epg.cyta.com.cy"]) == (1, 0), m)
    check("счётчик — 1", st.moved_kept == 1, st.moved_kept)
    conn.close()

    print("B2. игра есть в файле с другим сайтом (новое время) — оба канала живы")
    conn, src, ch = fresh("b2.db")
    e = moved_event(conn)
    mark(conn, e, src["tvarenasport.ba"], ch["tvarenasport.ba"], miss=0)
    mark(conn, e, src["tvarenasport.com"], ch["tvarenasport.com"], miss=0)
    g = {"sport": "F", "league": "FRANCUSKA LIGA", "home": "Nice", "away": "Rennes",
         "start_kyiv": "2026-12-04T20:00", "fs_id": "dOOA5B3D", "fs_start": FRI,
         "entries": [entry("tvarenasport.com", "2026-12-04T20:00")]}
    store.save_games(conn, [g], now=NOW,
                     moved_rows=[("tvarenasport.ba", "Arena Sport 4", SAT, "dOOA5B3D")])
    m = marks(conn, e)
    check("Arena RS (новое время) — живая без пометки", m.get(src["tvarenasport.com"]) == (0, 0), m)
    check("Arena BA (старая сетка) — живая с «время?»", m.get(src["tvarenasport.ba"]) == (0, 1), m)
    conn.close()

    print("B3. не трогаем: повтор не на старом времени, новый канал, игра без переноса, дозабор")
    conn, src, ch = fresh("b3.db")
    e = moved_event(conn)
    mark(conn, e, src["tvarenasport.ba"], ch["tvarenasport.ba"], miss=1)
    st = store.save_games(conn, [], now=NOW,
                          moved_rows=[("tvarenasport.ba", "Arena Sport 4", "2026-12-06 21:00",
                                       "dOOA5B3D")])
    check("правило 3: строка через сутки после старого времени — настоящий повтор",
          marks(conn, e).get(src["tvarenasport.ba"]) == (1, 0) and st.moved_kept == 0,
          marks(conn, e))
    st = store.save_games(conn, [], now=NOW,
                          moved_rows=[("teleman.pl", "Eleven Sports 4", SAT, "dOOA5B3D")])
    check("правило 4: канала у игры не было — новой отметки нет",
          src["teleman.pl"] not in marks(conn, e) and st.moved_kept == 0, marks(conn, e))
    st = store.save_games(conn, [], now=NOW, add_only=True,
                          moved_rows=[("tvarenasport.ba", "Arena Sport 4", SAT, "dOOA5B3D")])
    check("дозабор старого файла не оживляет", marks(conn, e).get(src["tvarenasport.ba"])
          == (1, 0) and st.moved_kept == 0, marks(conn, e))
    other = event(conn, SAT, flags="fs:NoMove1")
    mark(conn, other, src["tvarenasport.ba"], ch["tvarenasport.ba"], miss=1)
    st = store.save_games(conn, [], now=NOW,
                          moved_rows=[("tvarenasport.ba", "Arena Sport 4", SAT, "NoMove1")])
    check("правило 2: эталон игру не переносил — не трогаем",
          marks(conn, other).get(src["tvarenasport.ba"]) == (1, 0) and st.moved_kept == 0,
          marks(conn, other))
    conn.close()

    print(f"\nПроверок: {passed + len(failed)}, провалов: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

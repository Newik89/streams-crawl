# -*- coding: utf-8 -*-
r"""Книга 103: сайт канала назвал не того соперника сборной — строка остаётся
как на сайте, витрина красит её розовым и ставит знак вопроса.

Жалоба владельца 12.11.2026 (#9937): digisport.ro подписал матч Лиги наций
«Anglia-Scotia» на 21:45, а у flashscore в эту минуту England - Croatia
(Шотландия играет на день позже с Северной Македонией). Решение владельца:
«оставлять как на сайте канала и помечать у нас на витрине знаком вопроса и
выделить розовым строку с таким матчем» — сайт ближе к дате может исправиться.

Правило (е) (`app/canon.py`, `_rival_slip`) находит матч, с которым строка
спорит, только если всё сразу:
  1. обе стороны игры — сборные из справочника стран, разные;
  2. у эталона в ту же минуту (± 15 мин) играет одна из них;
  3. пол и возраст те же;
  4. такой матч один на обе названные страны;
  5. не теннис.
Игра не склеивается с матчем эталона («мимо») и получает пометку
`canon.RIVAL_DOUBT`; сверка (`canon_backfill.py`) пишет список таких игр в
настройку `rival_doubts`, витрина (`store.schedule`, `schedule.html`) красит.

Стена словаря: написание одной страны алиасом другой не становится
(`_learnable`) — «Scotia» не учится как Croatia никаким правилом.

В сеть не ходит, база — во временной папке.

Запуск: venv\Scripts\python.exe scripts\test_sopernik_oshibka.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="sopernik-"))
(TMP / "visits").mkdir()
os.environ.update(STREAMS_DB=str(TMP / "test.db"), STREAMS_ADMIN_PASSWORD="adm-test-1",
                  STREAMS_FRIEND_PASSWORD="fr-test-1", SECRET_KEY="k" * 32,
                  STREAMS_VISITS_DIR=str(TMP / "visits"))
os.environ.pop("STREAMS_LOCAL", None)

from app import canon, db, dictionary, store  # noqa: E402

total = green = 0
# матч — завтра и послезавтра: витрина прошедшие игры не показывает
D1 = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
D2 = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")


def check(name: str, ok: bool, got=None) -> None:
    global total, green
    total += 1
    green += bool(ok)
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"   ← {got!r}"))


def ref(home: str, away: str, start: str, league: str, fs: str, sport: str = "F") -> dict:
    return {"sport": sport, "home": home, "away": away, "start_kyiv": start, "league": league,
            "fs_id": fs, "names": {}}


def game(home: str, away: str, start: str = f"{D1} 21:45", sport: str = "F",
         league: str = "liga natiunilor Nations League Grupe (etapa 5)") -> dict:
    return {"id": 1, "sport": sport, "home": home, "away": away, "league": league,
            "start_kyiv": start, "entries": []}


def verdict(g: dict, reference: list[dict]) -> tuple[str, str, str]:
    """(куда легла, с каким матчем эталона склеена, с каким матчем спорит)."""
    res = canon.align([g], reference, {})
    doubt = g.get(canon.RIVAL_DOUBT) or ""
    for kind in ("sure", "ask"):
        if res[kind]:
            _, r, _ = res[kind][0]
            return kind, f"{r['home']} - {r['away']}", doubt
    return "missed", "", doubt


A = "EUROPE: UEFA Nations League - League A"
B = "EUROPE: UEFA Nations League - League B"
DAY = [ref("England", "Croatia", f"{D1}T21:45", A, "OKNATSve"),
       ref("Italy", "France", f"{D1}T21:45", A, "itfr0001"),
       ref("Scotland", "North Macedonia", f"{D2}T21:45", B, "KAogLGHG")]

print("правило (е): сайт назвал не того соперника — как на сайте, с пометкой")
got = verdict(game("Anglia", "Scotia"), DAY)
check("«Anglia - Scotia» 21:45 с матчем эталона НЕ склеена, пометка называет England - Croatia",
      got == ("missed", "", "England - Croatia"), got)
got = verdict(game("Scotia", "Anglia"), DAY)
check("стороны у сайта наоборот — та же пометка", got == ("missed", "", "England - Croatia"), got)
youth = DAY + [ref("England U20", "Czech Republic U20", f"{D1}T21:30", "EUROPE: Elite League U20", "Usb0mUdn"),
               ref("Scotland U21", "Ukraine U21", f"{D1}T21:45", "WORLD: Friendly International", "EoQMHIfo")]
got = verdict(game("Anglia", "Scotia"), youth)
check("молодёжные матчи тех же стран в те же минуты взрослому не мешают",
      got == ("missed", "", "England - Croatia"), got)
g = game("Anglia", "Croatia")
got = verdict(g, DAY)
check("сайт назвал верного соперника — обычная пара по буквам, пометки нет",
      got == ("sure", "England - Croatia", "") and not g.get("канон_как"), (got, g.get("канон_как")))
g = game("Anglia", "Scotia")
canon.align([g], DAY, {})
fixed = [ref("England", "Scotland", f"{D1}T21:45", A, "ensc0001")]
canon.align([g], fixed, {})
check("сайт исправился (или эталон узнал матч) — пометка с игры снимается",
      not g.get(canon.RIVAL_DOUBT), g.get(canon.RIVAL_DOUBT))

print("когда пометки нет")
both = DAY[:2] + [ref("Scotland", "North Macedonia", f"{D1}T21:45", B, "KAogLGHG")]
got = verdict(game("Anglia", "Scotia"), both)
check("в эту минуту играют ОБЕ названные сборные — не знаем, с чем спорит", got == ("missed", "", ""), got)
got = verdict(game("Anglia", "Scotia", start=f"{D1} 19:30"), DAY)
check("время не то (матч эталона через два часа)", got == ("missed", "", ""), got)
got = verdict(game("Anglia U21", "Scotia U21"), DAY)
check("молодёжные сборные со взрослым матчем не спорят", got == ("missed", "", ""), got)
got = verdict(game("Anglia", "Neznamy Klub"), DAY)
check("вторая сторона — не страна: правило (е) молчит", got[2] == "", got)
got = verdict(game("Suomi", "Viro"), DAY)
check("названные сборные в эту минуту не играют", got == ("missed", "", ""), got)
tennis = [ref("Italy", "Spain", f"{D1}T21:45", "DAVIS CUP: World Group", "dc000001", sport="T")]
got = verdict(game("Italia", "Scotia", sport="T"), tennis)
check("теннис правило не трогает", got == ("missed", "", ""), got)

print("стена словаря: страна не становится алиасом другой страны")
check("«Scotia» → Croatia учить нельзя", not canon._learnable("Scotia", "Croatia"))
check("«Scotia» → Scotland и «Hrvatska» → Croatia — можно",
      canon._learnable("Scotia", "Scotland") and canon._learnable("Hrvatska", "Croatia"))
check("клуб со страной в имени стена не задевает: «Estrela» → Estrela Amadora",
      canon._learnable("Estrela", "Estrela Amadora"))

conn = db.connect()
db.init_db(conn)
for name in ("England", "Croatia", "Scotland"):
    dictionary.remember_team(conn, name, name)
g = game("Anglia", "Scotia")
canon.apply(conn, canon.align([g], DAY, {}))
scotia = sorted(r[0] for r in conn.execute(
    "SELECT t.canonical_name FROM team_aliases x JOIN teams t ON t.id = x.team_id WHERE x.alias = 'Scotia'"))
check("после сверки «Scotia» за Croatia не записана и в очередь «Названия» не попала",
      "Croatia" not in scotia and conn.execute(
          "SELECT COUNT(*) FROM moderation WHERE kind = 'team' AND raw_value = 'Scotia'").fetchone()[0] == 0,
      scotia)
conn.close()

print("сквозная: сверка оставляет игру как на сайте, витрина её помечает")
os.environ["STREAMS_DB"] = str(TMP / "backfill.db")
bf = db.connect()
db.init_db(bf)
ids = {name: dictionary.remember_team(bf, name, name) for name in ("England", "Croatia", "Scotland")}
utc = (datetime.strptime(f"{D1} 21:45", "%Y-%m-%d %H:%M") - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
bf.execute("INSERT INTO events (sport, start_utc, start_kyiv, team_home_auto, team_away_auto, "
           "team_home_id, team_away_id, flags) VALUES ('F', ?, ?, 'England', 'Croatia', ?, ?, 'fs:OKNATSve')",
           (utc, f"{D1} 21:45", ids["England"], ids["Croatia"]))
real_id = bf.execute("SELECT last_insert_rowid()").fetchone()[0]
bf.execute("INSERT INTO events (sport, start_utc, start_kyiv, league_auto, team_home_auto, team_away_auto, "
           "team_home_id) VALUES ('F', ?, ?, 'liga natiunilor Nations League Grupe (etapa 5)', "
           "'Anglia', 'Scotia', ?)", (utc, f"{D1} 21:45", ids["England"]))
site_id = bf.execute("SELECT last_insert_rowid()").fetchone()[0]
bf.commit()
bf.close()
games_file = TMP / "games.json"
games_file.write_text(json.dumps({"games": [], "эталон": DAY}, ensure_ascii=False), encoding="utf-8")


def backfill() -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "canon_backfill.py"),
                           "--file", str(games_file)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=dict(os.environ))


run = backfill()
bf = db.connect()
rows = {r["id"]: (r["h"], r["a"], r["flags"]) for r in bf.execute(
    "SELECT e.id, th.canonical_name h, ta.canonical_name a, e.flags FROM events e "
    "LEFT JOIN teams th ON th.id = e.team_home_id LEFT JOIN teams ta ON ta.id = e.team_away_id")}
doubts = json.loads(db.get_setting(bf, "rival_doubts") or "{}")
shown = {g["id"]: g for g in store.schedule(bf)}
check("сверка не падает", run.returncode == 0, (run.stdout + run.stderr)[-700:])
check("игра сайта осталась своей строкой: England — Scotland, без метки flashscore",
      rows.get(site_id) == ("England", "Scotland", None), rows)
check("настоящий матч England — Croatia не тронут",
      rows.get(real_id) == ("England", "Croatia", "fs:OKNATSve") and len(rows) == 2, rows)
check("сверка записала пометку: игра сайта спорит с England - Croatia",
      doubts == {str(site_id): "England - Croatia"}, doubts)
check("витрина: у игры сайта пометка, у настоящего матча её нет",
      shown.get(site_id, {}).get("doubt") == "England - Croatia"
      and shown.get(real_id, {}).get("doubt") == "",
      {k: v.get("doubt") for k, v in shown.items()})
bf.close()

from app import visits, web  # noqa: E402
visits.write = lambda *a, **k: None
html = web.create_app().test_client().get("/schedule").get_data(as_text=True)
row_at = html.find(f'id="g{site_id}"')
row_html = html[row_at:html.find("</tr>", row_at)] if row_at >= 0 else ""
real_at = html.find(f'id="g{real_id}"')
real_html = html[real_at:html.find("</tr>", real_at)] if real_at >= 0 else ""
check("страница: строка игры сайта розовая (класс doubt) и со знаком вопроса",
      " doubt" in row_html.split(">")[0] and 'class="doubt-mark"' in row_html
      and "England - Croatia" in row_html, row_html[:300])
check("страница: у настоящего матча ни розового, ни знака вопроса",
      real_html and " doubt" not in real_html.split(">")[0] and "doubt-mark" not in real_html, real_html[:200])

# сайт исправил соперника: строка сайта теперь «Anglia - Croatia»
bf = db.connect()
bf.execute("UPDATE events SET team_away_auto = 'Croatia', team_away_id = ? WHERE id = ?",
           (ids["Croatia"], site_id))
bf.commit()
bf.close()
run = backfill()
bf = db.connect()
doubts = json.loads(db.get_setting(bf, "rival_doubts") or "{}")
left = bf.execute("SELECT COUNT(*) FROM events").fetchone()[0]
bf.close()
check("сайт исправился — следующая сверка пометку снимает, строки сливаются в один матч",
      run.returncode == 0 and doubts == {} and left == 1, (doubts, left, (run.stdout + run.stderr)[-300:]))

print(f"\n{green}/{total} зелёных")
raise SystemExit(0 if green == total else 1)

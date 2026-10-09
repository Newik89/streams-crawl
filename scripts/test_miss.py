# -*- coding: utf-8 -*-
r"""Проверки гашения каналов и чтения дат (разбор 06.10.2026, #4224/#4223).

Гашение — правила `app/miss.py`: каждому правилу — сценарий с говорящим
именем. Даты — `app/daytime.py` и teleman: страница дня, начатая хвостом
прошлого вечера; наложение передач; «dziś» при сборе в 22:30 UTC; ночь
перевода часов 25.10; «сегодня» по часам сайта — `?d=`, окно полного
обхода, `{AU_DAYPATH}` Сиднея, добор дней ORF; часы flashscore и его
локалей — из разбора, а не из карточки (проверка 06.10). digisport.ro — имя тура
вместо LIVE и ночные строки; tvpassport.com — пояс страницы главнее
карточки.

В сеть не ходит. База — пустая, во временной папке. Запуск:

    python scripts/test_miss.py

Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="miss-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test0.db")

from app import daytime, db, miss, store  # noqa: E402
from app.parsers import teleman_pl  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
WARSAW = ZoneInfo("Europe/Warsaw")
DAY = "2026-10-06"
NOW = datetime(2026, 10, 6, 1, 0)          # заливка — ночью, игры вечером
COLLECTED = "2026-10-06 01:00"             # момент сбора по Киеву

passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


# ── заготовки для гашения ────────────────────────────────────────────────────

GRID = "grid.test"          # сетка: одна страница на все каналы
PAGES = "pages.test"        # страница на канал и день
OTHER = "other.test"        # другой сайт, подтверждает, что игра есть
LIST = "list.test"          # листаемый список на всё окно (teleman /sport?page=N)
URL = {GRID: "https://grid.test/epg?date=2026-10-06",
       OTHER: "https://other.test/tv?date=2026-10-06",
       LIST: "https://list.test/sport?live=1&page=3"}


def page_url(channel: str) -> str:
    return f"https://pages.test/channel/{channel.replace(' ', '-')}?date={DAY}"


def fresh_db():
    # своя база на сценарий: прошлую Windows держит открытой до конца
    fresh_db.n = getattr(fresh_db, "n", 0) + 1
    os.environ["STREAMS_DB"] = str(TMP / f"test{fresh_db.n}.db")
    conn = db.connect()
    db.init_db(conn)
    for domain in (GRID, PAGES, OTHER, LIST):
        conn.execute("INSERT INTO sources (domain, name, base_url, country) "
                     "VALUES (?, ?, ?, 'XX')", (domain, domain, f"https://{domain}/"))
    conn.commit()
    return conn


def game(home, away, hhmm, *entries, day=DAY):
    return {"sport": "F", "league": "", "home": home, "away": away,
            "start_kyiv": f"{day}T{hhmm}", "start_utc": "",
            "entries": [{"source": domain, "channel": channel,
                         "url": page_url(channel) if domain == PAGES else URL[domain],
                         "raw_title": ""} for domain, channel in entries]}


def row(domain, channel="", verdict="расписание есть", day=DAY, url="",
        window=False):
    out = {"domain": domain, "channel": channel, "day": day, "итог": verdict,
           "url": url or (page_url(channel) if domain == PAGES else URL[domain])}
    if window:
        out["window"] = True          # листаемый список (crawl_fetch)
    return out


def import_twice(first, second, rows, punish=True, collected=COLLECTED):
    """Первая заливка заводит игры и отметки (отчёта нет — не гасит
    ничего), вторая — проверяемый сбор."""
    conn = fresh_db()
    store.save_games(conn, first, now=NOW)
    store.save_games(conn, second, now=NOW, punish=punish,
                     coverage=miss.покрытие_из_отчёта(rows), collected=collected)
    return conn


def miss_of(conn, channel, home):
    r = conn.execute(
        "SELECT ec.miss_count FROM event_channels ec "
        "JOIN channel_aliases ca ON ca.channel_id = ec.channel_id "
        "AND ca.source_id = ec.source_id "
        "JOIN events e ON e.id = ec.event_id "
        "WHERE ca.alias = ? AND e.team_home_auto = ?", (channel, home)).fetchone()
    return r[0] if r else None


A1 = ("Arsenal", "Chelsea", "21:45")
A2 = ("Liverpool", "Everton", "20:00")
A3 = ("Juventus", "Milan", "19:00")
A4 = ("Ajax", "Feyenoord", "18:00")

# ── гашение: правила app/miss.py ─────────────────────────────────────────────
print("Гашение каналов")

# правило владельца 03.10 (#2579): сайт перенёс матч на другой канал
first = [game(*A1, (GRID, "Max 4"), (OTHER, "Other 1")),
         game(*A2, (GRID, "Max 2"), (OTHER, "Other 2"))]
moved = [game(*A1, (GRID, "Max 1"), (OTHER, "Other 1")),
         game(*A2, (GRID, "Max 2"), (OTHER, "Other 2"))]
ok_rows = [row(GRID), row(OTHER)]
conn = import_twice(first, moved, ok_rows)
check("сайт_перенёс_матч_на_другой_канал_старый_гаснет",
      miss_of(conn, "Max 4", "Arsenal") == store.MISS_LIMIT
      and miss_of(conn, "Max 1", "Arsenal") == 0,
      (miss_of(conn, "Max 4", "Arsenal"), miss_of(conn, "Max 1", "Arsenal")))

conn = import_twice(first, moved, ok_rows, punish=False)
check("правило1_повторная_заливка_не_гасит",
      miss_of(conn, "Max 4", "Arsenal") == 0)

# сирота (09.10, #5104): игры в сборе нет вовсе, а страницы её дня у обоих
# сайтов целы и игры на день они дали — каналы гаснут (слово владельца
# 09.10: «проверить её на сайте и снять, хотя бы канал перечеркнуть»)
conn = import_twice(first, moved[1:], ok_rows)
check("сирота_игры_нет_в_сборе_страницы_дня_целы_каналы_гаснут",
      miss_of(conn, "Max 4", "Arsenal") == store.MISS_LIMIT
      and miss_of(conn, "Other 1", "Arsenal") == store.MISS_LIMIT
      and miss_of(conn, "Max 2", "Liverpool") == 0,
      (miss_of(conn, "Max 4", "Arsenal"), miss_of(conn, "Other 1", "Arsenal")))
conn = import_twice(first, moved[1:], [row(GRID, day="2026-10-07"), row(OTHER)])
check("сирота_страница_её_дня_не_скачана_канал_живёт",
      miss_of(conn, "Max 4", "Arsenal") == 0
      and miss_of(conn, "Other 1", "Arsenal") == store.MISS_LIMIT)
conn = import_twice(first, moved[1:], ok_rows, collected=f"{DAY} 22:00")
check("сирота_уже_началась_не_гаснет", miss_of(conn, "Max 4", "Arsenal") == 0)
conn = import_twice(first, moved[1:], ok_rows, punish=False)
check("сирота_повторная_заливка_не_гасит", miss_of(conn, "Max 4", "Arsenal") == 0)
conn = import_twice(first, [], ok_rows)
check("сирота_сайт_не_дал_игр_на_день_не_гаснет (правило 6)",
      miss_of(conn, "Max 4", "Arsenal") == 0 and miss_of(conn, "Max 2", "Liverpool") == 0)

# правило 5в: листаемый список (teleman /sport?page=N) — страницы на всё
# окно, день в отчёте — якорь сбора (#5104, 09.10)
NEXT = "2026-10-07"
list_rows = [row(LIST, url="https://list.test/sport?live=1&page=1", window=True),
             row(LIST, url="https://list.test/sport?live=1&page=2", window=True)]
list_first = [game(*A1, (LIST, "Lst 1")), game(*A2, (LIST, "Lst 2")),
         game(*A3, (LIST, "Lst 3"), day=NEXT)]
reached = [game(*A2, (LIST, "Lst 2")), game(*A3, (LIST, "Lst 3"), day=NEXT)]
conn = import_twice(list_first, reached, list_rows)
check("5в_листаемый_список_дошёл_до_следующего_дня_сирота_гаснет",
      miss_of(conn, "Lst 1", "Arsenal") == store.MISS_LIMIT
      and miss_of(conn, "Lst 2", "Liverpool") == 0
      and miss_of(conn, "Lst 3", "Juventus") == 0,
      (miss_of(conn, "Lst 1", "Arsenal"), miss_of(conn, "Lst 2", "Liverpool")))
conn = import_twice(list_first, reached[:1], list_rows)
check("5в_список_оборвался_на_дне_игры_не_гаснет",
      miss_of(conn, "Lst 1", "Arsenal") == 0)
conn = import_twice(list_first, reached, [row(LIST, url="https://list.test/sport?live=1&page=1",
                                         window=True),
                                     row(LIST, url="https://list.test/sport?live=1&page=2",
                                         verdict="не открылась", window=True)])
check("5в_одна_страница_списка_упала_не_гаснет",
      miss_of(conn, "Lst 1", "Arsenal") == 0)
conn = import_twice(list_first, reached, [row(LIST, url="https://list.test/sport?live=1&page=1"),
                                     row(LIST, url="https://list.test/sport?live=1&page=2")])
check("без_пометки_window_список_считается_страницей_дня_сбора (как раньше)",
      miss_of(conn, "Lst 1", "Arsenal") == store.MISS_LIMIT
      and miss_of(conn, "Lst 3", "Juventus") == 0)

conn = import_twice(first, moved, ok_rows, collected=f"{DAY} 22:00")
check("правило3_игра_началась_до_сбора_не_гаснет",
      miss_of(conn, "Max 4", "Arsenal") == 0)

conn = import_twice(first, moved, [row(GRID, verdict="не открылась"), row(OTHER)])
check("правило4_сайт_не_ответил_не_гасит",
      miss_of(conn, "Max 4", "Arsenal") == 0)

conn = import_twice(first, moved, [row(GRID, day="2026-10-07"), row(OTHER)])
check("правило5_сетка_другого_дня_не_гасит",
      miss_of(conn, "Max 4", "Arsenal") == 0)

conn = import_twice(first, moved, [
    row(GRID, url="https://grid.test/sport-list?page=1"), row(OTHER)])
check("правило5_страница_другого_вида_не_гасит (скан даты teleman: каналы, а не /sport)",
      miss_of(conn, "Max 4", "Arsenal") == 0)

# правило 5 у сайта «страница на канал»: упала страница канала A, B открылась
first = [game(*A1, (PAGES, "Kanal A"), (OTHER, "Other 1")),
         game(*A2, (PAGES, "Kanal B"), (OTHER, "Other 2"))]
second = [game(*A1, (OTHER, "Other 1")),
          game(*A2, (PAGES, "Kanal B"), (OTHER, "Other 2"))]
conn = import_twice(first, second, [row(PAGES, "Kanal A", verdict="пусто"),
                                    row(PAGES, "Kanal B"), row(OTHER)])
check("правило5_страница_канала_A_упала_B_открылась_A_не_гаснет",
      miss_of(conn, "Kanal A", "Arsenal") == 0)
conn = import_twice(first, second, [row(PAGES, "Kanal A"), row(PAGES, "Kanal B"),
                                    row(OTHER)])
check("правило5_страница_канала_A_цела_матча_нет_A_гаснет",
      miss_of(conn, "Kanal A", "Arsenal") == store.MISS_LIMIT)

# правило 6: скан даты, «расписание есть», а игр 0 (#4224)
first = [game(*A1, (PAGES, "Kanal A"), (OTHER, "Other 1"))]
second = [game(*A1, (OTHER, "Other 1"))]
conn = import_twice(first, second, [row(PAGES, "Kanal A"), row(PAGES, "Kanal B"),
                                    row(OTHER)])
check("правило6_скан_даты_с_нулём_игр_у_сайта_не_гасит",
      miss_of(conn, "Kanal A", "Arsenal") == 0)

first = [game(*A1, (GRID, "Max 1"), (OTHER, "Other 1")),
         game(*A2, (GRID, "Max 2"), (OTHER, "Other 2")),
         game(*A3, (GRID, "Max 3"), (OTHER, "Other 3")),
         game(*A4, (GRID, "Max 4"), (OTHER, "Other 4"))]
second = [game(*A1, (GRID, "Max 5"), (OTHER, "Other 1")),
          game(*A2, (OTHER, "Other 2")), game(*A3, (OTHER, "Other 3")),
          game(*A4, (OTHER, "Other 4"))]
conn = import_twice(first, second, ok_rows)
check("правило6_сайт_дал_вчетверо_меньше_игр_не_гасит",
      [miss_of(conn, f"Max {i}", h) for i, h in
       ((1, "Arsenal"), (2, "Liverpool"), (3, "Juventus"), (4, "Ajax"))]
      == [0, 0, 0, 0])

# правило 5: день страницы — тот, с которого пришла отметка, а не киевская
# дата игры. Argentina — Benin 07.10 01:50 Киева ziggosport отдал со
# страницы 06.10; скан даты 07.10 качал только 07.10 и гасил отметку (06.10)
def night_game(home, away, when, *entries):
    """Игра с явными адресами отметок: entries — (сайт, канал, адрес)."""
    return {"sport": "F", "league": "", "home": home, "away": away,
            "start_kyiv": when, "start_utc": "",
            "entries": [{"source": domain, "channel": channel, "url": url,
                         "raw_title": ""} for domain, channel, url in entries]}


Z06 = "https://pages.test/epg/epg-2026-10-06.json"
Z07 = "https://pages.test/epg/epg-2026-10-07.json"
O07 = "https://other.test/tv?date=2026-10-07"
NIGHT = ("Argentina", "Benin", "2026-10-07T01:50")
EVENING = ("Ajax", "PSV", "2026-10-07T21:00")    # сайт отдал на 07.10 игру —
first = [night_game(*NIGHT, (PAGES, "Ziggo", Z06), (OTHER, "Other 1", O07)),
         night_game(*EVENING, (PAGES, "Ziggo", Z07), (OTHER, "Other 2", O07))]
second = [night_game(*NIGHT, (OTHER, "Other 1", O07)),     # правило 6 молчит
          night_game(*EVENING, (PAGES, "Ziggo", Z07), (OTHER, "Other 2", O07))]
scan07 = [row(PAGES, "Ziggo", day="2026-10-07", url=Z07),
          row(OTHER, day="2026-10-07", url=O07)]
conn = import_twice(first, second, scan07)
check("правило5а_скан_07_10_не_гасит_ночную_игру_со_страницы_06_10 (Argentina — Benin)",
      miss_of(conn, "Ziggo", "Argentina") == 0, miss_of(conn, "Ziggo", "Argentina"))
conn = import_twice(first, second, scan07 + [row(PAGES, "Ziggo", day=DAY, url=Z06)])
check("правило5а_сбор_скачал_страницу_06_10_целой_матча_нет_гаснет",
      miss_of(conn, "Ziggo", "Argentina") == store.MISS_LIMIT,
      miss_of(conn, "Ziggo", "Argentina"))

# адрес без даты: день страницы не узнать — ночной игре нужны обе страницы
U = "https://pages.test/live/ziggo"
first = [night_game(*NIGHT, (PAGES, "Ziggo", U), (OTHER, "Other 1", O07)),
         night_game(*EVENING, (PAGES, "Ziggo", U), (OTHER, "Other 2", O07))]
second = [night_game(*NIGHT, (OTHER, "Other 1", O07)),
          night_game(*EVENING, (PAGES, "Ziggo", U), (OTHER, "Other 2", O07))]
only07 = [row(PAGES, "Ziggo", day="2026-10-07", url=U), row(OTHER, day="2026-10-07", url=O07)]
conn = import_twice(first, second, only07)
check("правило5б_адрес_без_даты_ночная_игра_без_страницы_накануне_не_гаснет",
      miss_of(conn, "Ziggo", "Argentina") == 0)
conn = import_twice(first, second, only07 + [row(PAGES, "Ziggo", day=DAY, url=U)])
check("правило5б_адрес_без_даты_обе_страницы_целы_гаснет",
      miss_of(conn, "Ziggo", "Argentina") == store.MISS_LIMIT)

check("дата_в_адресе: форматы сайтов плана; номер дня — не дата",
      [miss.дата_в_адресе(u) for u in (
          Z06, "https://ntvplus.tv/tv/ajax/tv?genre=sport&date=06.10.2026&tz=0",
          "https://www.sport5.co.il/Ajax/GetBroadcastSheetData.aspx?date=06%2F10%2F2026",
          "https://nova.bg/schedule/index/4/2026/10/06/",
          "https://tv.orf.at/program/orfs/index~_day-06-10-2026_-d8b2f4c4.html",
          "https://port.hu/tvapi?i_datetime_from=2026-10-06&i_datetime_to=2026-10-07",
          "https://www.flashscore.mobi/?d=1", "https://www.sporttv.pt/guia")]
      == ["2026-10-06"] * 6 + ["", ""])
cov = miss.покрытие_из_отчёта([row(PAGES, "Ziggo", day="2026-10-07", url=Z06)])
check("правило5а_вид_не_датирован_если_дата_адреса_не_день_строки",
      cov.датированы == {miss.вид_адреса(Z06): False}
      and cov.дни_страницы(Z06, "2026-10-07 01:50") == ["2026-10-06", "2026-10-07"]
      and cov.дни_страницы(Z06, "2026-10-07 21:00") == ["2026-10-07"])

# ── разовая уборка двойников ±24 ч (scripts/clean_shifted_twins.py) ─────────
print("Уборка двойников ночных игр")
sys.path.insert(0, str(ROOT / "scripts"))
import clean_shifted_twins as twins  # noqa: E402

S5, DK = "sport5.co.il", "tvsporten.dk"
conn = fresh_db()
for domain in (S5, DK):
    conn.execute("INSERT INTO sources (domain, name, base_url, country) "
                 "VALUES (?, ?, ?, 'XX')", (domain, domain, f"https://{domain}/"))
conn.commit()


def s5(home, away, when, title, domain=S5, channel="SPORT 5 STAR"):
    return {"sport": "B", "league": "", "home": home, "away": away,
            "start_kyiv": when, "start_utc": "",
            "entries": [{"source": domain, "channel": channel, "raw_title": title,
                         "url": f"https://{domain}/day?date={when[:10]}"}]}


T1, T2, T3 = "NBA: CHA - BKN", "WNBA: NY - ATL, game 2", "WNBA: NY - ATL, game 3"
old = [s5("CHA", "BKN", "2026-10-08T02:00", T1),       # двойник: сдвинут на сутки
       s5("NY", "ATL", "2026-10-11T02:30", T3),        # своя игра: заголовок другой
       s5("CHI", "MEM", "2026-10-09T03:00", "NBA: CHI - MEM"),
       s5("CHI", "MEM", "2026-10-09T03:00", "CHI - MEM", domain=DK, channel="TV3"),
       s5("LAL", "SAC", "2026-10-12T02:00", "NBA: LAL - SAC")]  # −23 ч, не сутки
fresh = [s5("CHA", "BKN", "2026-10-07T02:00", T1),
         s5("NY", "ATL", "2026-10-10T02:30", T2),
         s5("CHI", "MEM", "2026-10-08T03:00", "NBA: CHI - MEM"),
         s5("LAL", "SAC", "2026-10-11T03:00", "NBA: LAL - SAC")]
store.save_games(conn, old, now=datetime(2026, 10, 5, 22, 0))
store.save_games(conn, fresh, now=NOW)
found = twins.найти(conn, COLLECTED, COLLECTED)
check("двойник_ровно_на_сутки_с_тем_же_заголовком_найден, прочие — нет "
      "(игра 3 ≠ игра 2, отметка не только sport5, сдвиг 23 ч)",
      [(d.start, [t for *_, t in d.отметки]) for d in found]
      == [("2026-10-08 02:00", [T1])], [(d.start, d.отметки) for d in found])
gone = twins.погасить(conn, found)
check("уборка_гасит_отметку_как_заливка_событие_не_удаляет",
      len(gone) == 1 and miss_of(conn, "SPORT 5 STAR", "CHA") is not None
      and conn.execute("SELECT miss_count FROM event_channels WHERE id = ?",
                       (gone[0],)).fetchone()[0] == store.MISS_LIMIT
      and conn.execute("SELECT COUNT(*) FROM events WHERE start_kyiv = "
                       "'2026-10-08 02:00'").fetchone()[0] == 1)
check("уборка_повторно_ничего_не_находит", twins.найти(conn, COLLECTED, COLLECTED) == [])

check("вид_адреса_без_чисел_и_запроса",
      miss.вид_адреса("https://www.teleman.pl/program-tv/stacje/Polsat-Sport-2"
                      "?date=2026-10-06") == "teleman.pl/program-tv/stacje/Polsat-Sport-#"
      and miss.вид_адреса("https://www.teleman.pl/sport?live=1&page=3")
      == "teleman.pl/sport")

# ── даты: страница дня, полночь, «сегодня» ───────────────────────────────────
print("Даты")


def kyiv(moment):
    return moment.astimezone(KYIV).strftime("%Y-%m-%d %H:%M")


page = (ROOT / "scripts" / "testdata" / "teleman_polsat_sport_2026-10-06.html") \
    .read_text(encoding="utf-8")
progs = teleman_pl.parse(page, day=date(2026, 10, 6), tz=teleman_pl.TZ,
                         url="https://www.teleman.pl/program-tv/stacje/Polsat-Sport"
                             "?date=2026-10-06")
match = [p for p in progs if p.match_raw == "Chorwacja - Hiszpania"]
check("teleman_страница_дня_начата_хвостом_вечера: 20:35 Варшава → 06.10 21:35 Киев (#4223)",
      len(match) == 1 and match[0].start.strftime("%Y-%m-%d %H:%M") == "2026-10-06 20:35"
      and kyiv(match[0].start) == "2026-10-06 21:35",
      [(p.raw_time, kyiv(p.start)) for p in match])
check("teleman_хвост_вечера_первая_строка_накануне",
      kyiv(progs[0].start) == "2026-10-06 00:30" and kyiv(progs[-1].start) == "2026-10-07 02:00",
      (kyiv(progs[0].start), kyiv(progs[-1].start)))


def walk(times, day="2026-10-06", tz="Europe/Warsaw"):
    return [m.strftime("%Y-%m-%d %H:%M") for m in
            daytime.walk_day(times, date.fromisoformat(day), tz)]


check("обычная_страница_дня_06_00_до_04_00_как_раньше",
      walk(["6:00", "20:35", "23:45", "0:30", "4:00"])
      == ["2026-10-06 06:00", "2026-10-06 20:35", "2026-10-06 23:45",
          "2026-10-07 00:30", "2026-10-07 04:00"])
check("остаток_дня_вечером_nova_bg_не_сдвигается",
      walk(["23:00", "0:30", "2:00"])
      == ["2026-10-06 23:00", "2026-10-07 00:30", "2026-10-07 02:00"])
check("наложение_передач_5_00_потом_2_45_не_полночь",
      walk(["23:30", "1:45", "5:00", "2:45", "7:00", "20:00", "22:15", "0:30"])
      == ["2026-10-05 23:30", "2026-10-06 01:45", "2026-10-06 05:00",
          "2026-10-06 02:45", "2026-10-06 07:00", "2026-10-06 20:00",
          "2026-10-06 22:15", "2026-10-07 00:30"])

# ночь перевода часов 25.10.2026: в Варшаве 03:00 CEST → 02:00 CET,
# в Киеве 04:00 EEST → 03:00 EET; страница дня 25.10 начата хвостом 24.10
dst = daytime.walk_day(["23:00", "1:00", "2:30", "6:00", "20:35", "23:00", "1:00"],
                       date(2026, 10, 25), "Europe/Warsaw")
check("ночь_перевода_часов_25_10: Варшава → Киев",
      [kyiv(m) for m in dst] == ["2026-10-25 00:00", "2026-10-25 02:00",
                                 "2026-10-25 03:30", "2026-10-25 07:00",
                                 "2026-10-25 21:35", "2026-10-26 00:00",
                                 "2026-10-26 02:00"],
      [kyiv(m) for m in dst])


def frozen_utc(*moment):
    """Часы машины (GitHub), остановленные на этом моменте UTC."""
    utc = datetime(*moment, tzinfo=timezone.utc)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc.astimezone(tz) if tz else utc.replace(tzinfo=None)
    return Frozen


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crawl_fetch = load_script("crawl_fetch")
parse_live = load_script("parse_live")


def source(domain, tz, pattern, name=""):
    return {"domain": domain, "timezone": tz, "grid": False, "marks": {},
            "base_url": "", "channels": [{"name": name, "pattern": pattern}]}


SYDNEY = source("tvguidetonight.com.au", "Australia/Sydney",
                "https://www.tvguidetonight.com.au/channels/7mate-hd-sydney{AU_DAYPATH}")
POLAND = source("pages.pl", "Europe/Warsaw", "https://pages.pl/kanal?date={YYYY-MM-DD}")
API_UTC = source("api.test", "UTC", "https://api.test/epg/{YYYY-MM-DD}")


def jobs_of(plan_sources, days=2, **kw):
    return [(j["domain"], j["day"], j["url"]) for j in
            crawl_fetch.targets({"sources": plan_sources}, days, False, **kw)]


real_datetime = daytime.datetime
try:
    daytime.datetime = frozen_utc(2026, 10, 5, 22, 30)
    check("сегодня_по_часам_сайта: в 22:30 UTC в Варшаве уже 06.10",
          daytime.today("Europe/Warsaw") == date(2026, 10, 6)
          and daytime.today("UTC") == date(2026, 10, 5))
    flash = source("flashscore.mobi", "Etc/GMT-2", "https://www.flashscore.mobi/?d={DAYNUM}",
                   "football")
    got = jobs_of([flash], 1, start=date(2026, 10, 6), single=True)
    check("скан_даты_06_10_в_22_30_UTC_просит_у_сайта_d0 (#204 просил d=1 и получил 07.10)",
          [u for *_, u in got] == ["https://www.flashscore.mobi/?d=0"], got)
    got = jobs_of([POLAND, API_UTC, SYDNEY])
    check("полный_обход_в_22_30_UTC: окно каждого сайта — с его «сегодня»",
          got == [("pages.pl", "2026-10-06", "https://pages.pl/kanal?date=2026-10-06"),
                  ("pages.pl", "2026-10-07", "https://pages.pl/kanal?date=2026-10-07"),
                  ("api.test", "2026-10-05", "https://api.test/epg/2026-10-05"),
                  ("api.test", "2026-10-06", "https://api.test/epg/2026-10-06"),
                  ("tvguidetonight.com.au", "2026-10-06",
                   "https://www.tvguidetonight.com.au/channels/7mate-hd-sydney"),
                  ("tvguidetonight.com.au", "2026-10-07",
                   "https://www.tvguidetonight.com.au/channels/7mate-hd-sydney/tomorrow")],
          got)
    check("добор_дней_ORF_в_22_30_UTC: от «сегодня» Вены (06.10)",
          crawl_fetch.link_days(daytime.today("Europe/Vienna"), 3, None)
          == [date(2026, 10, 7), date(2026, 10, 8)]
          and crawl_fetch.link_days(daytime.today("Europe/Vienna"), 3, date(2026, 10, 6)) == []
          and crawl_fetch.link_days(daytime.today("Europe/Vienna"), 3, date(2026, 10, 7))
          == [date(2026, 10, 7)])
    # ночь по часам сайта (00:30 Вены): страница «сегодня» у ORF ещё держит
    # вчерашние телесутки — сегодняшний день тоже берём ссылкой (#205)
    check("ночь_ORF_в_22_30_UTC: tv_night, и сегодня 06.10 добирается ссылкой",
          daytime.tv_night("Europe/Vienna")
          and crawl_fetch.link_days(daytime.today("Europe/Vienna"), 3, None, night=True)
          == [date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8)]
          and crawl_fetch.link_days(daytime.today("Europe/Vienna"), 3,
                                    date(2026, 10, 6), night=True) == [date(2026, 10, 6)])
    # kolla.tv (dagenstv.com): день номером от сегодня, `?dat=` ручка не знает
    kolla = source("dagenstv.com", "Europe/Stockholm",
                   "https://www.kolla.tv/api/es/channels/listWithPrograms?day={DAYNUM}")
    got = jobs_of([kolla], 3)
    check("kolla_день_номером: окно 06.10–08.10 → day=0,1,2 (у Стокгольма уже 06.10)",
          [u.rsplit("=", 1)[1] for *_, u in got] == ["0", "1", "2"]
          and [d for _, d, _ in got] == ["2026-10-06", "2026-10-07", "2026-10-08"], got)

    # утренний сбор 03:15 UTC (#205): Вена 05:15 — ещё ночь, днём — нет
    daytime.datetime = frozen_utc(2026, 10, 6, 3, 15)
    morning = daytime.tv_night("Europe/Vienna") and daytime.tv_night("Europe/Bucharest")
    daytime.datetime = frozen_utc(2026, 10, 6, 13, 15)
    check("tv_night: 03:15 UTC — ночь у Вены и Бухареста, 13:15 UTC — день",
          morning and not daytime.tv_night("Europe/Vienna")
          and crawl_fetch.link_days(daytime.today("Europe/Vienna"), 3, None,
                                    night=daytime.tv_night("Europe/Vienna"))
          == [date(2026, 10, 7), date(2026, 10, 8)])

    # Сидней: «завтра» наступает раньше всех — в 14:00 UTC там уже 01:00 06.10
    daytime.datetime = frozen_utc(2026, 10, 5, 14, 0)
    got = jobs_of([POLAND, SYDNEY])
    check("сидней_в_14_00_UTC: у него уже 06.10, у Варшавы ещё 05.10",
          got == [("pages.pl", "2026-10-05", "https://pages.pl/kanal?date=2026-10-05"),
                  ("pages.pl", "2026-10-06", "https://pages.pl/kanal?date=2026-10-06"),
                  ("tvguidetonight.com.au", "2026-10-06",
                   "https://www.tvguidetonight.com.au/channels/7mate-hd-sydney"),
                  ("tvguidetonight.com.au", "2026-10-07",
                   "https://www.tvguidetonight.com.au/channels/7mate-hd-sydney/tomorrow")],
          got)

    # flashscore: часы сайта знает разбор (`flashscore_mobi.SITE_TZ`), а не
    # карточка — в базе у локалей стояло «UTC», у mobi «Etc/GMT-2» (06.10)
    def fs(domain, card_tz):
        return source(domain, card_tz, f"https://{domain}/?d={{DAYNUM}}", "football")

    daytime.datetime = frozen_utc(2026, 10, 5, 22, 30)
    got = jobs_of([fs("m.flashscore.de", "UTC")], 1)
    check("flashscore_локаль_с_карточкой_UTC_в_22_30_UTC: день 06.10 (Париж), d=0",
          got == [("m.flashscore.de", "2026-10-06", "https://m.flashscore.de/?d=0")], got)
    daytime.datetime = frozen_utc(2026, 10, 5, 21, 30)
    got = jobs_of([fs("m.flashscore.gr", "UTC"), fs("flashscore.mobi", "Etc/GMT-2")], 1)
    check("flashscore_gr_в_21_30_UTC: в Афинах уже 06.10, в Париже ещё 05.10",
          got == [("m.flashscore.gr", "2026-10-06", "https://m.flashscore.gr/?d=0"),
                  ("flashscore.mobi", "2026-10-05", "https://flashscore.mobi/?d=0")], got)
    # после перевода часов 25.10 Париж = UTC+1: в 22:30 UTC там ещё 26.10,
    # а «Etc/GMT-2» карточки давал 27.10 — вчерашняя страница под меткой
    # сегодняшней (как #204)
    daytime.datetime = frozen_utc(2026, 10, 26, 22, 30)
    got = jobs_of([fs("flashscore.mobi", "Etc/GMT-2")], 2)
    check("flashscore_mobi_зимой_в_22_30_UTC: день 26.10 и d=0, а не 27.10",
          got == [("flashscore.mobi", "2026-10-26", "https://flashscore.mobi/?d=0"),
                  ("flashscore.mobi", "2026-10-27", "https://flashscore.mobi/?d=1")], got)
finally:
    daytime.datetime = real_datetime

from app.parsers import flashscore_mobi  # noqa: E402

fs_row = ('<html lang="xx"><h4>EUROPE: Test</h4><span>20:30</span>Alpha - Beta '
          '<a href="/match/AbCd1234/" class="sched">-</a>')
fs_time = {domain: kyiv(flashscore_mobi.parse(
    fs_row, day=date(2026, 10, 6), tz="UTC", url=f"https://{domain}/?d=0")[0].start)
    for domain in ("www.flashscore.mobi", "m.flashscore.gr", "m.flashscore.pt",
                   "m.flashscore.ru")}
check("flashscore_время_по_часам_версии_сайта: 20:30 Париж/Афины/Лиссабон/Алматы",
      fs_time == {"www.flashscore.mobi": "2026-10-06 21:30",
                  "m.flashscore.gr": "2026-10-06 20:30",
                  "m.flashscore.pt": "2026-10-06 22:30",
                  "m.flashscore.ru": "2026-10-06 18:30"}, fs_time)
check("flashscore_часы_только_у_своих_доменов: прочим — карточка",
      crawl_fetch.site_tz(fs("m.flashscore.bg", "UTC")) == "Europe/Sofia"
      and crawl_fetch.site_tz(POLAND) == "Europe/Warsaw"
      and set(flashscore_mobi.SITE_TZ) == set(flashscore_mobi.LOCALES)
      | {flashscore_mobi.DOMAIN})

cell = ('<table><tr><td>dziś, 6 października</td><td>20:35</td><td>Polsat Sport 1</td>'
        '<td><a class="prog-title">Piłka nożna: Liga Narodów</a>'
        '<em>mecz: Chorwacja - Hiszpania</em><img class="live" title="na żywo"></td>'
        '<td>piłka nożna</td></tr></table>')
# день-якорь строки отчёта — дата запуска по UTC (05.10), а в Варшаве уже 06.10
sport = teleman_pl.parse(cell, day=date(2026, 10, 5), tz=teleman_pl.TZ,
                         url="https://www.teleman.pl/sport?live=1&stations=all&page=1")
check("teleman_dziś_при_сборе_в_22_30_UTC: 06.10 20:35 Варшава → 06.10 21:35 Киев",
      len(sport) == 1 and sport[0].start.strftime("%Y-%m-%d %H:%M") == "2026-10-06 20:35"
      and kyiv(sport[0].start) == "2026-10-06 21:35",
      [(p.start, kyiv(p.start)) for p in sport])

# ── digisport.ro: имя тура вытеснило LIVE; ночные строки — следующий день ──
print("digisport.ro и tvpassport.com")


def digi_row(hhmm, kind, tag, title):
    mark = f'<span class="tag"> {tag} </span> ' if tag else ""
    return (f'<tr class=""> <td class="schedule-icon" data-schedule="{kind}"></td> '
            f'<td>{hhmm}</td> <td> {mark}{title} </td> </tr>')


digi = ('<div class="schedule-wrapper"><h3>Marți 06 Octombrie</h3>'
        '<table class="schedule-table">'
        + digi_row("21:00", "digisport", "LIVE", "Euro Fotbal")
        + digi_row("21:40", "liga natiunilor", "etapa 4",
                   "Nations League: Croatia-Spania<br>Grupe")
        + digi_row("22:45", "liga natiunilor", "etapa 4",
                   "Nations League: Croatia-Spania<br>Grupe")
        + digi_row("23:30", "digisport", "Premiera", "Liga 2: Rezumat")
        + digi_row("02:00", "digisport", "LIVE", "Fotbal Amical: Argentina-Benin")
        + digi_row("04:00", "liga natiunilor", "etapa 4",
                   "Nations League: Croatia-Spania<br>Grupe")
        + '</table></div>')
from app.parsers import digisport_ro, tvpassport_com  # noqa: E402
rows = {(p.raw_time, p.match_raw): p for p in digisport_ro.parse(
    digi, day=date(2026, 10, 5), tz=digisport_ro.TZ,
    url="https://www.digisport.ro/program-tv/digisport-1")}
first = rows[("21:40", "Croatia - Spania")]
check("digisport_имя_тура_вместо_LIVE: первый показ пары — угаданный эфир",
      first.live_raw == "live" and first.extra.get("live_guess")
      and kyiv(first.start) == "2026-10-06 21:40",
      (first.live_raw, first.extra, kyiv(first.start)))
check("digisport_повторы_той_же_пары_не_эфир",
      rows[("22:45", "Croatia - Spania")].live_raw == ""
      and rows[("04:00", "Croatia - Spania")].live_raw == "")
night = rows[("02:00", "Argentina - Benin")]
check("digisport_ночная_строка_под_заголовком_06_10 — это 07.10; LIVE честный",
      kyiv(night.start) == "2026-10-07 02:00" and night.live_raw == "live"
      and not night.extra.get("live_guess")
      and kyiv(rows[("04:00", "Croatia - Spania")].start) == "2026-10-07 04:00",
      (kyiv(night.start), night.extra))
check("digisport_Premiera_не_эфир",
      all(p.live_raw == "" for (t, _), p in rows.items() if t == "23:30"))

# подпись под <br> — турнир или стадия; сплошной текст ячейки клеил её к
# гостям: «Fribourg OlympicFIBA Masculin Europe Cup» (самопроверка #205)
glued = ('<div class="schedule-wrapper"><h3>Miercuri 07 Octombrie</h3>'
         '<table class="schedule-table">'
         + digi_row("19:00", "baschet", "Etapa 1",
                    "Baschet: CSM CSU Oradea-Fribourg Olympic<br>FIBA Masculin Europe Cup")
         + digi_row("20:00", "digisport", "LIVE",
                    "Fotbal Feminin: Romania-Norvegia<br>Cupa Mondiala, Play-off")
         + '</table></div>')
got = {p.raw_time: p for p in digisport_ro.parse(
    glued, day=date(2026, 10, 7), tz=digisport_ro.TZ,
    url="https://www.digisport.ro/program-tv/digisport-3")}
check("digisport_подпись_под_br_не_клеится_к_гостям, а уходит в лигу",
      got["19:00"].match_raw == "CSM CSU Oradea - Fribourg Olympic"
      and "FIBA Masculin Europe Cup" in got["19:00"].league_raw
      and got["20:00"].match_raw == "Romania - Norvegia"
      and "Cupa Mondiala" in got["20:00"].league_raw,
      [(p.match_raw, p.league_raw) for p in got.values()])

# diemaxtra: имя канала — из подписи страницы, не из адреса: `/schedule`
# отдаёт страницу Diema Sport, а звался «Diema Xtra» (лишний канал у 11 игр)
from app.parsers import diemaxtra_bg  # noqa: E402
diema = ('<html><head><title>Програма - Diemasport - Diema xtra</title></head><body>'
         '<a data-toggle="tab" href="#tuesday"><span class="day">вт</span>'
         '<span class="date">06 окт</span></a><div id="tuesday"><ul class="tv_content">'
         '<li><p class="time">21.45</p><p class="title">Хърватия - Испания</p>'
         '<p class="description">4 кръг, Футбол: УЕФА Лига на нациите, директно</p>'
         '</li></ul></div></body></html>')
named = {p.channel_raw for p in diemaxtra_bg.parse(
    diema, day=date(2026, 10, 6), url="https://diemaxtra.nova.bg/schedule")}
check("diemaxtra_канал_по_подписи_страницы: /schedule — это Diema Sport",
      named == {"Diema Sport"}
      and not diemaxtra_bg.parse(diema, day=date(2026, 10, 6),
                                 url="https://diemaxtra.nova.bg/schedule",
                                 channels={"Diema Xtra"}), named)


class _Result:
    """Строка отсева, как её видит parse_live: `.program`."""
    def __init__(self, program):
        self.program = program


check("эфир_угадан_у_строки_сверяется_с_эталоном_даже_у_сайта_с_флагом",
      parse_live.guessed("www.digisport.ro", _Result(first))
      and not parse_live.guessed("www.digisport.ro", _Result(night))
      and parse_live.guessed("www.movistarplus.es", _Result(night)))


def passport(zone, stamp):
    return (f'<select id="timezone_selector"><option value="America/New_York">Eastern'
            f'</option><option value="{zone}" selected>X</option></select>'
            f'<div class="list-group-item" data-st="{stamp}" '
            f'data-showName="UEFA Nations League Soccer" '
            f'data-episodeTitle="Scotland vs. Slovenia" data-live="1"></div>')


url_fsp = "https://www.tvpassport.com/tv-listings/stations/fox-soccer-plus/7538/2026-10-06"
# пояс карточки передаёт разбор (`parse_live`: tz из плана) — страница главнее
got = [kyiv(p.start) for page in (passport("America/Denver", "2026-10-06 12:30:00"),
                                  passport("Europe/London", "2026-10-06 19:30:00"))
       for p in tvpassport_com.parse(page, tz="America/New_York", url=url_fsp)]
check("tvpassport_пояс_страницы_главнее_карточки: Денвер 12:30 и Лондон 19:30 → 21:30 Киев",
      got == ["2026-10-06 21:30", "2026-10-06 21:30"], got)

print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, красных: {len(failed)}")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)

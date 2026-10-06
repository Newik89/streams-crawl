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
URL = {GRID: "https://grid.test/epg?date=2026-10-06",
       OTHER: "https://other.test/tv?date=2026-10-06"}


def page_url(channel: str) -> str:
    return f"https://pages.test/channel/{channel.replace(' ', '-')}?date={DAY}"


def fresh_db():
    # своя база на сценарий: прошлую Windows держит открытой до конца
    fresh_db.n = getattr(fresh_db, "n", 0) + 1
    os.environ["STREAMS_DB"] = str(TMP / f"test{fresh_db.n}.db")
    conn = db.connect()
    db.init_db(conn)
    for domain in (GRID, PAGES, OTHER):
        conn.execute("INSERT INTO sources (domain, name, base_url, country) "
                     "VALUES (?, ?, ?, 'XX')", (domain, domain, f"https://{domain}/"))
    conn.commit()
    return conn


def game(home, away, hhmm, *entries):
    return {"sport": "F", "league": "", "home": home, "away": away,
            "start_kyiv": f"{DAY}T{hhmm}", "start_utc": "",
            "entries": [{"source": domain, "channel": channel,
                         "url": page_url(channel) if domain == PAGES else URL[domain],
                         "raw_title": ""} for domain, channel in entries]}


def row(domain, channel="", verdict="расписание есть", day=DAY, url=""):
    return {"domain": domain, "channel": channel, "day": day, "итог": verdict,
            "url": url or (page_url(channel) if domain == PAGES else URL[domain])}


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

conn = import_twice(first, moved[1:], ok_rows)
check("правило2_игры_нет_в_сборе_её_каналы_не_гаснут",
      miss_of(conn, "Max 4", "Arsenal") == 0)

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

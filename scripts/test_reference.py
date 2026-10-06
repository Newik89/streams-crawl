# -*- coding: utf-8 -*-
r"""Проверки эталона flashscore.mobi и фильтра «матч уже сыгран» (07.10).

Сбор #205: страница «09.10» в блоке Аргентины даёт `19:30, 23:00, 00:30`,
и последний матч (Instituto — Boca Juniors) получал дату страницы — 09.10.
Страница «10.10» давала ему верное 10.10, в эталоне у одного fs_id стояло
два времени, и живой эфир SPORT.TV1 10.10 01:25 (DIRETO) снимался как
повтор «уже сыгранного» матча 09.10. Здесь:

* разбор страницы с переходом через полночь — урезанные настоящие страницы
  `d=3` и `d=4` из `scripts/testdata/`;
* окно страницы в `daytime.walk_day` (хвост прошлого вечера в начале блока);
* `flashscore_mobi.settle` — один матч, одно время (две соседние страницы,
  большинство, живая минута);
* фильтр «матч уже сыгран» (`parse_live.played_before`): живой эфир при
  двойном эталоне не снимается, настоящий повтор — снимается;
* журнал снятого поимённо (`parse_live.sift`, `removed_row`).

В сеть не ходит, база не нужна. Запуск:

    python scripts/test_reference.py

Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
# базу не открываем, но на всякий случай — не боевая
os.environ["STREAMS_DB"] = str(Path(tempfile.gettempdir()) / "reference-test-none.db")

from app import daytime, merge  # noqa: E402
from app.parsers import Program, flashscore_mobi  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
PARIS = ZoneInfo("Europe/Paris")
DATA = ROOT / "scripts" / "testdata"

passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def kyiv(moment) -> str:
    return moment.astimezone(KYIV).strftime("%Y-%m-%d %H:%M")


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parse_live = load_script("parse_live")

# ── окно страницы в walk_day ─────────────────────────────────────────────────
print("walk_day: окно страницы")


def walk(times, day, **kw):
    return [m.strftime("%m-%d %H:%M") for m in
            daytime.walk_day(times, date.fromisoformat(day), "Europe/Paris", **kw)]


WINDOW = dict(overlap=flashscore_mobi.ПОЛНОЧЬ_ЛЮБОЙ_ШАГ,
              window=(flashscore_mobi.ОКНО_С, flashscore_mobi.ОКНО_ДО))
check("блок_начат_хвостом_вечера: 23:00 — накануне, 00:15 — после второй полуночи",
      walk(["23:00", "00:30", "02:45", "20:45", "22:00", "00:15"], "2026-10-10", **WINDOW)
      == ["10-09 23:00", "10-10 00:30", "10-10 02:45", "10-10 20:45",
          "10-10 22:00", "10-11 00:15"])
check("блок_дня_с_ночным_хвостом: 00:30 после 23:00 — уже следующие сутки",
      walk(["19:30", "23:00", "00:30"], "2026-10-09", **WINDOW)
      == ["10-09 19:30", "10-09 23:00", "10-10 00:30"])
check("короткий_шаг_назад_тоже_полночь: 02:35 → 00:30 (без overlap=1 не видно)",
      walk(["00:30", "01:30", "02:35", "00:30"], "2026-10-07", **WINDOW)
      == ["10-07 00:30", "10-07 01:30", "10-07 02:35", "10-08 00:30"])
check("хвост_вечера_без_полудня: 23:00, 00:00 … 04:00 — первая строка накануне",
      walk(["23:00", "00:00", "01:00", "03:00", "04:00"], "2026-10-11", **WINDOW)
      == ["10-10 23:00", "10-11 00:00", "10-11 01:00", "10-11 03:00", "10-11 04:00"])
check("живая_минута_не_сбивает_счёт: пустое время — None на своём месте",
      [m and m.strftime("%m-%d %H:%M") for m in daytime.walk_day(
          ["23:00", "", "02:00"], date(2026, 10, 6), "Europe/Paris", **WINDOW)]
      == ["10-05 23:00", None, "10-06 02:00"])
check("без_окна_как_раньше: остаток дня nova.bg не сдвигается",
      walk(["23:00", "0:30", "2:00"], "2026-10-06")
      == ["10-06 23:00", "10-07 00:30", "10-07 02:00"])

# ── разбор настоящих страниц d=3 и d=4 (урезаны) ─────────────────────────────
print("flashscore.mobi: страницы 09.10 и 10.10 сбора #205")
d3 = flashscore_mobi.parse((DATA / "flashscore_mobi_2026-10-09_d3.html").read_text(encoding="utf-8"),
                           day=date(2026, 10, 9), url="https://www.flashscore.mobi/?d=3")
d4 = flashscore_mobi.parse((DATA / "flashscore_mobi_2026-10-10_d4.html").read_text(encoding="utf-8"),
                           day=date(2026, 10, 10), url="https://www.flashscore.mobi/?d=4")
p3 = {p.extra["fs_id"]: p for p in d3}
p4 = {p.extra["fs_id"]: p for p in d4}
check("d3_Instituto_Boca_00_30_это_10_10 (01:30 Киев), а не дата страницы",
      kyiv(p3["Cv4icMr4"].start) == "2026-10-10 01:30", kyiv(p3["Cv4icMr4"].start))
check("d3_вечер_своего_дня: Aldosivi 19:30 и Gimnasia 23:00 — 09.10",
      kyiv(p3["YDGs8wcM"].start) == "2026-10-09 20:30"
      and kyiv(p3["QsUQBLcc"].start) == "2026-10-10 00:00")
check("d4_Gimnasia_23_00_в_начале_блока_это_09_10",
      kyiv(p4["QsUQBLcc"].start) == "2026-10-10 00:00", kyiv(p4["QsUQBLcc"].start))
check("d4_Tigre_Banfield_00_15_в_конце_блока_это_11_10",
      kyiv(p4["vie8gvrT"].start) == "2026-10-11 01:15", kyiv(p4["vie8gvrT"].start))
check("d4_USL_01_30_23_00_00_00: 00:00 — уже 11.10",
      kyiv(p4["ULuOvHat"].start) == "2026-10-11 01:00", kyiv(p4["ULuOvHat"].start))
check("день_страницы_в_extra",
      p3["Cv4icMr4"].extra["page_day"] == "2026-10-09"
      and p4["Cv4icMr4"].extra["page_day"] == "2026-10-10")

# ── settle: один матч — одно время ───────────────────────────────────────────
print("settle")
allp = d3 + d4
settled = flashscore_mobi.settle(allp)
ids = [p.extra["fs_id"] for p in settled]
by = {p.extra["fs_id"]: p for p in settled}
check("одна_запись_на_fs_id", len(ids) == len(set(ids)) == len({p.extra["fs_id"] for p in allp}))
check("Instituto_Boca_одно_время_10_10_01_30_Киев",
      kyiv(by["Cv4icMr4"].start) == "2026-10-10 01:30")
# Гондурас: «09.10» даёт [23:00 Platense], «10.10» — [23:00 Platense, 23:00
# Genesis]; Platense — вечер 09.10 (на обеих страницах), Genesis — 10.10.
# Без settle страница «10.10» ставила обоих на 10.10
check("Гондурас_одинаковые_23_00_разных_суток: Platense 09.10, Genesis 10.10",
      kyiv(by["G6bUACS9"].start) == "2026-10-10 00:00"
      and kyiv(by["fJO9jrse"].start) == "2026-10-11 00:00",
      (kyiv(by["G6bUACS9"].start), kyiv(by["fJO9jrse"].start)))


def fake(fs_id, wall, page_day, clock=True):
    """Запись разбора: время страницы `wall` (Париж), день страницы."""
    start = datetime.fromisoformat(wall).replace(tzinfo=PARIS)
    return Program(channel_raw="flashscore", title="A - B", start=start,
                   match_raw="A - B", extra={"fs_id": fs_id, "page_day": page_day,
                                             "clock": clock})


twin = flashscore_mobi.settle([fake("X", "2026-10-09 00:30", "2026-10-09"),
                               fake("X", "2026-10-10 00:30", "2026-10-10")])
check("правило_1_ночь: 00:30 на страницах 09.10 и 10.10 — это 10.10",
      len(twin) == 1 and twin[0].start.strftime("%m-%d %H:%M") == "10-10 00:30")
twin = flashscore_mobi.settle([fake("Y", "2026-10-10 23:00", "2026-10-09"),
                               fake("Y", "2026-10-10 23:00", "2026-10-10"),
                               fake("Y", "2026-10-09 23:00", "2026-10-09")])
check("правило_1_вечер: 23:00 на страницах 09.10 и 10.10 — это 09.10",
      len(twin) == 1 and twin[0].start.strftime("%m-%d %H:%M") == "10-09 23:00")
many = flashscore_mobi.settle([fake("Z", "2026-10-12 21:00", "2026-10-12"),
                               fake("Z", "2026-10-12 21:00", "2026-10-12"),
                               fake("Z", "2026-10-14 21:00", "2026-10-14")])
check("правило_2_большинство: страницы не соседние — время большинства",
      many[0].start.strftime("%m-%d %H:%M") == "10-12 21:00")
live = flashscore_mobi.settle([fake("L", "2026-10-06 18:40", "2026-10-06", clock=False),
                               fake("L", "2026-10-06 17:00", "2026-10-07")])
check("правило_3_живая_минута_уступает_настоящему_времени",
      live[0].start.strftime("%m-%d %H:%M") == "10-06 17:00")

# ── эталон и фильтр «матч уже сыгран» ────────────────────────────────────────
print("фильтр «матч уже сыгран»")
reference, reference_full = [], []
parse_live.add_reference(settled, reference, reference_full)
inst = [r for r in reference_full if r["home"] == "Instituto"]
check("эталон_Instituto_одна_запись_2026_10_10T01_30",
      [r["start_kyiv"] for r in inst] == ["2026-10-10T01:30"], inst)


def game(home, away, when, source="sporttv.pt", channel="SPORT.TV1"):
    start = datetime.fromisoformat(when).replace(tzinfo=KYIV)
    return merge.Game(entries=[merge.Entry(
        source=source, channel=channel, home=home, away=away, start=start,
        sport="F", league="CAMPEONATO DA ARGENTINA")])


def ref(when, fs_id="Cv4icMr4", home="Instituto", away="Boca Juniors"):
    return {"sport": "F", "home": home, "away": away,
            "league": "ARGENTINA: Liga Profesional - Clausura",
            "fs_id": fs_id, "start_kyiv": when}


# живой эфир SPORT.TV1 (DIRETO): 22:25 UTC 09.10 = 10.10 01:25 Киев
direto = game("Instituto", "Boca Juniors", "2026-10-10 01:25")
double = [ref("2026-10-09T01:30"), ref("2026-10-10T01:30")]
kept, gone = parse_live.drop_reference_repeats([direto], double)
check("живой_эфир_при_двойном_эталоне_не_снят (тот же матч в ±3 ч)",
      kept == [direto] and gone == [], gone)
kept, gone = parse_live.drop_reference_repeats([direto], reference_full)
check("живой_эфир_с_исправленным_эталоном_не_снят", kept == [direto] and gone == [])
record = game("Instituto", "Boca Juniors", "2026-10-10 14:00", "oneplaysport.cz", "Sport 1")
kept, gone = parse_live.drop_reference_repeats([direto, record], reference_full)
check("настоящий_повтор_снят: запись в 14:00 после матча в 01:30",
      kept == [direto] and len(gone) == 1 and gone[0][0] is record
      and gone[0][1]["start_kyiv"] == "2026-10-10T01:30", gone)
studio = game("Instituto", "Boca Juniors", "2026-10-10 05:00")
kept, gone = parse_live.drop_reference_repeats([studio], [ref("2026-10-10T01:30")])
check("меньше_4_часов_после_матча_не_повтор (как раньше)", kept == [studio])
tbc = game("Instituto", "TBC", "2026-10-10 14:00")
kept, gone = parse_live.drop_reference_repeats([tbc], reference_full)
check("соперник_не_назван_не_судим", kept == [tbc])
index = parse_live.reference_index(double)
check("очередь_модерации_то_же_правило: при двойном эталоне не «уже сыгран»",
      not parse_live.already_played("Instituto", "Boca Juniors",
                                    datetime(2026, 10, 10, 1, 25, tzinfo=KYIV), index)
      and parse_live.already_played("Instituto", "Boca Juniors",
                                    datetime(2026, 10, 10, 14, 0, tzinfo=KYIV),
                                    parse_live.reference_index([ref("2026-10-10T01:30")])))

# ── журнал снятого ───────────────────────────────────────────────────────────
print("журнал снятого")


class Row:
    """Строка отсева, как её видит parse_live: `.program`, `.start_kyiv`."""
    def __init__(self, channel, title, when):
        self.program = Program(channel_raw=channel, title=title, start=None)
        self.start_kyiv = datetime.fromisoformat(when).replace(tzinfo=KYIV)


снято: list = []
left = parse_live.sift([("tv2.no", Row("TV 2 Sport 1", "Spurs - Newcastle", "2026-10-10 14:32")),
                        ("tv2.no", Row("TV 2 Sport 1", "Brann - Molde", "2026-10-10 18:00"))],
                       lambda d, r: r.start_kyiv.minute % 5 == 0, снято,
                       parse_live.СНЯТО_ГРЯЗНЫЕ_МИНУТЫ, "не на ровной минуте")
check("sift_оставляет_и_пишет_снятое_поимённо",
      len(left) == 1 and снято == [{
          "фильтр": parse_live.СНЯТО_ГРЯЗНЫЕ_МИНУТЫ, "домен": "tv2.no",
          "канал": "TV 2 Sport 1", "заголовок": "Spurs - Newcastle",
          "start_kyiv": "2026-10-10T14:32", "почему": "не на ровной минуте"}], снято)
check("текст_записи_эталона_для_журнала",
      parse_live._ref_text(ref("2026-10-09T01:30"))
      == "Instituto - Boca Juniors 09.10 01:30 (fs_id Cv4icMr4)")

# ── ночные строки ТВ-сеток: «час < 6 → завтра» заменён порядком страницы ────
print("ночные строки телегидов (ntvplus, sport5, общее правило)")
from app.parsers import ntvplus_tv, sport5_co_il  # noqa: E402

MSK = ZoneInfo("Europe/Moscow")
viju = ntvplus_tv.parse((DATA / "ntvplus_2026-10-06_viju.html").read_text(encoding="utf-8"),
                        url="https://ntvplus.tv/tv/ajax/tv?genre=sport&date=06.10.2026"
                            "&tz=0&search=&channel=&offset=0")
first = viju[0]
check("ntvplus_прямой_эфир_02_50_в_начале_страницы_06_10 — это 06.10, как в ts=",
      "Медельин" in first.title and first.extra.get("ts") == 1791244200
      and first.start == datetime(2026, 10, 6, 2, 50, tzinfo=MSK),
      (first.title[:40], first.start))
check("ntvplus_ts_главнее: время строки = unix-метка ссылки",
      all(p.start.timestamp() == p.extra["ts"] for p in viju if p.extra.get("ts")))
check("ntvplus_ночь_в_конце_страницы — уже 07.10 (00:00, 02:15, 04:30)",
      [p.start.strftime("%m-%d %H:%M") for p in viju[-3:]]
      == ["10-07 00:00", "10-07 02:15", "10-07 04:30"])
s5 = sport5_co_il.parse((DATA / "sport5_2026-10-07.html").read_text(encoding="utf-8"),
                        url="https://www.sport5.co.il/Ajax/GetBroadcastSheetData.aspx"
                            "?date=07%2F10%2F2026")
benin = [p for p in s5 if "בנין" in p.title]
check("sport5_календарные_сутки: Аргентина — Бенин 01:50 на странице 07.10 — это 07.10",
      len(benin) == 1 and kyiv(benin[0].start) == "2026-10-07 01:50",
      [kyiv(p.start) for p in benin])
check("sport5_весь_день_в_дату_страницы (00:20 … 23:50)",
      {p.start.date() for p in s5} == {date(2026, 10, 7)})
night = sport5_co_il.parse(
    '<table><tr class="tr-header"><th><img alt="ערוץ הספורט"></th></tr>'
    '<tr><td class="date"><div>23:50</div></td><td class="text">א</td></tr>'
    '<tr><td class="date"><div>00:30</div></td><td class="text">ב</td></tr></table>',
    url="https://www.sport5.co.il/Ajax/GetBroadcastSheetData.aspx?date=07%2F10%2F2026")
check("sport5_переход_через_полночь_по_порядку: 23:50, потом 00:30 — уже 08.10",
      [p.start.strftime("%m-%d %H:%M") for p in night] == ["10-07 23:50", "10-08 00:30"])


def tv_rows(times, channel="TRT SPOR"):
    return [Program(channel_raw=channel, title=t, extra={"day": "2026-10-06"},
                    start=datetime.fromisoformat(f"2026-10-06 {t}").replace(
                        tzinfo=ZoneInfo("Europe/Istanbul"))) for t in times]


edges = daytime.walk_programs(tv_rows(["04:58", "05:00", "19:00", "23:00", "00:30",
                                       "05:15", "06:30"]),
                              date(2026, 10, 6), "Europe/Istanbul")
check("общее_правило_краёв_суток: 04:58 в начале — сегодня, 05:15/06:30 после полуночи — завтра",
      [p.start.strftime("%d %H:%M") for p in edges]
      == ["06 04:58", "06 05:00", "06 19:00", "06 23:00", "07 00:30", "07 05:15", "07 06:30"]
      and edges[-1].extra["day"] == "2026-10-07")

# ── местные имена эталона и для латиницы ─────────────────────────────────────
print("местные имена эталона (латиница, баскет/теннис)")
hu = [{"sport": "F", "home": "Ferencvaros", "away": "Debrecen", "league": "HUNGARY: NB I",
       "fs_id": "abc", "start_kyiv": "2026-10-10T18:00",
       "names": {"hu": ["Ferencvárosi TC", "Debreceni VSC"], "de": ["Ferencvaros", "Debrecen"]}},
      {"sport": "B", "home": "Szolnoki Olajbanyasz", "away": "Falco", "league": "HUNGARY: NB I. A",
       "fs_id": "bcd", "start_kyiv": "2026-10-10T19:00",
       "names": {"hu": ["Szolnoki Olajbányász", "Falco-Vulcano Szombathely"]}}]
local = parse_live.local_reference(hu)
at = datetime(2026, 10, 10, 17, 55, tzinfo=KYIV)
check("латиница_DVSC_находит_венгерское_Debreceni_VSC",
      parse_live.in_local_reference("Ferencvárosi TC", "DVSC", at, "F", local)
      and parse_live.in_local_reference("DVSC", "Ferencvárosi TC", at, "F", local))
check("латиница_другой_вид_спорта_и_далеко_по_времени — нет",
      not parse_live.in_local_reference("Ferencvárosi TC", "DVSC", at, "B", local)
      and not parse_live.in_local_reference("Ferencvárosi TC", "DVSC",
                                            datetime(2026, 10, 10, 23, 0, tzinfo=KYIV),
                                            "F", local))
check("баскет_по_местным_именам: Szolnoki Olajbányász — Falco-Vulcano",
      parse_live.in_local_reference("Szolnoki Olajbányász", "Falco-Vulcano Szombathely",
                                    datetime(2026, 10, 10, 19, 0, tzinfo=KYIV), "B", local))
check("местное_равное_английскому_не_дублируется",
      sum(len(v) for v in local.values()) == 2)
class _Result:
    """Строка отсева для `parse_live.guessed`: нужен только `.program`."""
    def __init__(self, program):
        self.program = program


port_guess = Program(channel_raw="Spíler1", title="x", start=at, extra={"live_guess": True})
port_flag = Program(channel_raw="M4 Sport", title="x", start=at, live_raw="élő")
check("port.hu_вне_списка_угадаек: угадан только live_guess, флаг сайта — честный",
      "port.hu" not in parse_live.REPEAT_GUESS_DOMAINS
      and parse_live.guessed("port.hu", _Result(port_guess))
      and not parse_live.guessed("port.hu", _Result(port_flag)))

print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, красных: {len(failed)}")
sys.exit(1 if failed else 0)

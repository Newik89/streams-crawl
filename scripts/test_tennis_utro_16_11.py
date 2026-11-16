# -*- coding: utf-8 -*-
r"""Книги 147, 149, 150 и 160 (16.11.2026): находки проверки утреннего сбора
на новом коде, слово владельца «чини всё остальное».

  147. пометка эфира только у передач дня обхода — это «сейчас в эфире», а не
       прямая трансляция (`parse_live.now_flag_sites`, правила 1–4;
       primaplay.ro: утренний повтор «TENIS ATP: TURNEUL CAMPIONILOR» прошёл
       трансляцией турнира);
  149. следующая игра командной встречи с пометкой эфира — строкой турнира на
       своё время (`parse_live.next_tie_games`, правила 1–6; слово владельца
       16.11 про Thailand — Switzerland 07:00 и 11:05);
  150. спорт на колясках — во вкладку «Other Sport», вид по-английски
       («Wheelchair tennis»; `sport.Sports.decide`, правило 1б);
  160. стадия показа сведённой трансляции (`broadcast.show_stage`): «Final» у
       «ATP Finals» — только в день финала; слова стадий на языках сайтов;
       турнир, названный по спонсору («HPP Open» — Хельсинки); подпись лиги
       сведённой строки — название турнира у эталона (книга 148).
В сеть не ходит, базу не трогает. Запуск: python scripts/test_tennis_utro_16_11.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import broadcast, live, pipeline, site_lang, sport  # noqa: E402
from app.parsers import Program, site_says  # noqa: E402
from app.reference import Reference  # noqa: E402
import parse_live  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def когда(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=KYIV)


def строка(start: str, marker: str = "", ok: bool = True, by_reference: str = "",
           home: str = "A", away: str = "B", sport_letter: str = "F", league: str = "",
           channel: str = "Канал", title: str = "", flag: bool | None = None) -> pipeline.Row:
    """Строка разбора без самого разбора: только то, на что смотрят правила."""
    program = Program(channel_raw=channel, title=title or f"{home} - {away}", start=когда(start),
                      live_raw=marker if marker != pipeline.REFERENCE_MARKER else "")
    if flag is not None:
        site_says(program, flag)
    return pipeline.Row(program=program, ok=ok, live_marker=marker, home=home, away=away,
                        sport=sport_letter, league=league, by_reference=by_reference,
                        start_kyiv=когда(start), start_utc=когда(start))


# ── книга 147 ────────────────────────────────────────────────────────────────
print("147. Пометка «сейчас в эфире» (`parse_live.now_flag_sites`)")
ДЕНЬ = date(2026, 11, 16)
сегодня = [строка(f"2026-11-16T0{h}:30", "vezi live") for h in (5, 6, 7)]
завтра_без = [строка(f"2026-11-17T{h}:00", pipeline.REFERENCE_MARKER, by_reference="пара") for h in (18, 19, 20)]
проверка("правила 2–4: помечено только сегодняшнее, завтрашние матчи эталона без пометки — «сейчас в эфире»",
         parse_live.now_flag_sites([("www.primaplay.ro", сегодня + завтра_без)], ДЕНЬ), {"primaplay.ro"})
проверка("правило 3: помечена и завтрашняя трансляция — пометка честная",
         parse_live.now_flag_sites([("primaplay.ro", сегодня + завтра_без + [строка("2026-11-17T21:00", "vezi live")])],
                                   ДЕНЬ), set())
проверка("правило 2: помеченных строк меньше трёх — судить не по чему",
         parse_live.now_flag_sites([("primaplay.ro", сегодня[:2] + завтра_без)], ДЕНЬ), set())
проверка("правило 4: завтрашних матчей эталона без пометки меньше трёх — сайт просто не знает завтрашней программы",
         parse_live.now_flag_sites([("primaplay.ro", сегодня + завтра_без[:2])], ДЕНЬ), set())
проверка("правило 4: завтрашняя строка без пометки, которую эталон НЕ подтвердил, — не улика",
         parse_live.now_flag_sites([("primaplay.ro", сегодня + [строка(f"2026-11-17T{h}:00", "", ok=False)
                                                                 for h in (18, 19, 20)])], ДЕНЬ), set())
свой = next(iter(parse_live.REPEAT_GUESS_DOMAINS))
проверка("правило 1: сайт из списка «эфир не помечает» не смотрим",
         parse_live.now_flag_sites([(свой, сегодня + завтра_без)], ДЕНЬ), set())
проверка("страницы одного сайта считаются вместе (с www и без)",
         parse_live.now_flag_sites([("www.primaplay.ro", сегодня), ("primaplay.ro", завтра_без)], ДЕНЬ), {"primaplay.ro"})
p1 = Program(channel_raw="Prima Sport 4", title="TENIS ATP: TURNEUL CAMPIONILOR", start=когда("2026-11-16T07:30"),
             live_raw="vezi live", extra={"day": "2026-11-16", "турнир": {"x": 1}, "live_guess": True})
p2 = site_says(Program(channel_raw="Prima Sport 1", title="A - B", start=когда("2026-11-16T07:30")), True)
parse_live.unmark_now_flag([p1, p2], [{"day": "2026-11-16"}, dict(p2.extra)])
проверка("снятие пометки: слово сайта уходит из `live_raw` в `extra`, дописанное первым разбором стирается",
         (p1.live_raw, p1.extra, p2.live_raw, p2.extra.get("site_flag")),
         ("", {"day": "2026-11-16", parse_live.NOW_FLAG: "vezi live"}, "", None))

M, ВИДЫ = live.load(), sport.load()
ТУРИН = "ATP - SINGLES: Finals - Turin (World), hard (indoor)"
ЭТАЛОН = [{"sport": "T", "home": "Alcaraz C.", "away": "Tiafoe F.", "league": ТУРИН, "fs_id": "t1",
           "start_kyiv": "2026-11-16T12:30"},
          {"sport": "T", "home": "Medvedev D.", "away": "Cobolli F.", "league": ТУРИН, "fs_id": "t2",
           "start_kyiv": "2026-11-16T21:30"}]
судья = Reference(ЭТАЛОН)


def разбор(start: str, title: str, marker: str, guess_site: bool):
    program = Program(channel_raw="Prima Sport 4", title=title, start=когда(start), live_raw=marker)
    row = pipeline.classify(program, M, ВИДЫ, reference=судья, langs=site_lang.of("primaplay.ro"),
                            guess_site=guess_site)
    return row.ok, row.away


проверка("до правила: утренний повтор с пометкой «vezi live» шёл трансляцией турнира",
         разбор("2026-11-16T07:30", "TENIS ATP: TURNEUL CAMPIONILOR", "vezi live", False), (True, broadcast.SESSION))
проверка("после (пометка снята, эфир подтверждает эталон): повтор в 07:30 не проходит, сессия в 12:30 — проходит",
         [разбор("2026-11-16T07:30", "TENIS ATP: TURNEUL CAMPIONILOR", "", True),
          разбор("2026-11-16T12:30", "Tenis M - ATP: Torino - Turneul Campionilor", "", True)],
         [(False, ""), (True, broadcast.SESSION)])

# ── книга 149 ────────────────────────────────────────────────────────────────
print("149. Следующая игра командной встречи (`parse_live.next_tie_games`)")
БДК = "TEAMS - WOMEN: Billie Jean King Cup - World Group (World) - Relegation - Play Offs"
ВСТРЕЧИ = [{"sport": "T", "home": "Poland W", "away": "Sweden W", "league": БДК, "fs_id": "pl-se",
            "start_kyiv": "2026-11-20T18:00"},
           {"sport": "T", "home": "Thailand W", "away": "Switzerland W", "league": БДК, "fs_id": "th-ch",
            "start_kyiv": "2026-11-22T08:00"},
           {"sport": "T", "home": "Alcaraz C.", "away": "Tiafoe F.", "league": ТУРИН, "fs_id": "t1",
            "start_kyiv": "2026-11-21T15:00"}]


def встреча(start: str, home: str, away: str, flag: bool | None = True, домен: str = "teleman.pl"):
    return домен, строка(start, "program na żywo" if flag else pipeline.REFERENCE_MARKER, home=home, away=away,
                         sport_letter="T", league="Puchar Billie Jean King", flag=flag)


найдено = [встреча("2026-11-20T17:00", "פולין", "שוודיה", домен="sport5.co.il"),
           встреча("2026-11-20T18:00", "Polska", "Szwecja"), встреча("2026-11-20T20:00", "Polska", "Szwecja"),
           встреча("2026-11-21T14:00", "Polska", "Szwecja"), встреча("2026-11-21T16:00", "Polska", "Szwecja"),
           встреча("2026-11-21T07:00", "Thailand", "Schweiz", домен="srf.ch"),
           встреча("2026-11-21T11:05", "Thailand", "Schweiz", домен="srf.ch"),
           встреча("2026-11-21T15:00", "Alcaraz", "Tiafoe"),
           встреча("2026-11-21T23:00", "Polska", "Szwecja", flag=None, домен="oneplaysport.cz")]
сколько = parse_live.next_tie_games(найдено, ВСТРЕЧИ)
вид = [(r.start_kyiv.strftime("%d %H:%M"), r.home, r.away) for _d, r in найдено]
проверка("правила 3–4: первый показ встречи у всех сайтов и показы в окне склейки от него — сама встреча, пара как была",
         вид[:3], [("20 17:00", "פולין", "שוודיה"), ("20 18:00", "Polska", "Szwecja"),
                   ("20 20:00", "Billie Jean King Cup", broadcast.SESSION)][:2] + [вид[2]])
проверка("правило 5: показ позже окна с честной пометкой эфира — строка турнира на своё время, лига эталона",
         [(вид[2], вид[3], вид[4]), найдено[3][1].league, сколько],
         [(("20 20:00", "Billie Jean King Cup", broadcast.SESSION), ("21 14:00", "Billie Jean King Cup", broadcast.SESSION),
           ("21 16:00", "Billie Jean King Cup", broadcast.SESSION)), БДК, 4])
проверка("слово владельца: Thailand — Schweiz 07:00 — встреча, 11:05 с пометкой эфира — строка турнира (эталон сдвинут на сутки)",
         (вид[5], вид[6]), (("21 07:00", "Thailand", "Schweiz"), ("21 11:05", "Billie Jean King Cup", broadcast.SESSION)))
проверка("правило 1: игроки, а не страны, — не командная встреча", вид[7], ("21 15:00", "Alcaraz", "Tiafoe"))
проверка("правило 6: поздний показ без честной пометки сайта не трогаем — его судят фильтры повторов",
         вид[8], ("21 23:00", "Polska", "Szwecja"))
проверка("правило 2: встречи нет в эталоне — строки не трогаем",
         parse_live.next_tie_games([встреча("2026-11-21T07:00", "Japan", "Argentina"),
                                    встреча("2026-11-21T14:00", "Japan", "Argentina")], ВСТРЕЧИ), 0)
проверка("строка со служебной второй стороной — трансляция турнира, какими бы словами ни звалась; не теннис — нет",
         [broadcast.is_title("T", "Billie Jean King Cup", broadcast.SESSION), broadcast.is_title("T", "Polska", "Szwecja"),
          broadcast.is_title("F", "Billie Jean King Cup", broadcast.SESSION)], [True, False, False])
проверка("название командного турнира из лиги эталона",
         [broadcast.team_tournament(БДК), broadcast.team_tournament("TEAMS - MEN: Davis Cup"),
          broadcast.team_tournament(ТУРИН)], ["Billie Jean King Cup", "Davis Cup", ""])

# ── книга 150 ────────────────────────────────────────────────────────────────
print("150. Спорт на колясках — в «Other Sport» (`sport.Sports.decide`, правило 1б)")


def вид_спорта(text: str):
    v = ВИДЫ.decide(text, text)
    return v.letter, v.group


проверка("теннис на колясках на языках сайтов — «Wheelchair tennis»",
         [вид_спорта(x) for x in ("גמר המאסטרס בטניס כיסאות גלגלים: יחידים וזוגות", "Wheelchair Tennis Masters",
                                  "Rollstuhltennis: Masters", "Tenis na wózkach: Masters", "Теннис на колясках. Мастерс",
                                  "Tennis en fauteuil: Masters")],
         [("-", "Wheelchair tennis")] * 6)
проверка("баскетбол на колясках — «Wheelchair basketball»; базовый вид не назван — «Wheelchair sports»",
         [вид_спорта("Basket in carrozzina - Finale SuperCoppa Italiana 2026"), вид_спорта("Basket με Αμαξίδιο | Super Cup"),
          вид_спорта("Wheelchair rugby")],
         [("-", "Wheelchair basketball"), ("-", "Wheelchair basketball"), ("-", "Wheelchair sports")])
проверка("обычный теннис и баскетбол — как раньше",
         [вид_спорта("Tenis: ATP Finals")[0], вид_спорта("Basket: Serie A")[0]], ["T", "B"])
v = ВИДЫ.decide("Football: Arsenal - Chelsea. Wheelchair access at the stadium", "Football: Arsenal - Chelsea",
                ("Arsenal", "Chelsea"))
проверка("слово коляски только в описании — не улика: футбол остаётся футболом", v.letter, "F")
p = Program(channel_raw="ספורט 5 Gold", title="גמר המאסטרס בטניס כיסאות גלגלים: יחידים וזוגות",
            start=когда("2026-11-16T11:00"), live_raw="ישיר", league_raw="גמר המאסטרס בטניס כיסאות גלגלים")
row = pipeline.classify(p, M, ВИДЫ, reference=судья, langs=site_lang.of("sport5.co.il"))
проверка("трансляция турнира на колясках с пометкой эфира — не на витрину, а во вкладку Other Sport с видом по-английски",
         (row.ok, row.reason.startswith("другой вид спорта"), row.sport_group, pipeline.TOURNAMENT in p.extra),
         (False, True, "Wheelchair tennis", False))

# ── книга 160 ────────────────────────────────────────────────────────────────
print("160. Стадия показа, слова стадий, спонсорское имя, подпись лиги")
ХЕЛЬСИНКИ = "CHALLENGER MEN - SINGLES: Helsinki (Finland), hard (indoor)"
знаем = broadcast.tournaments(ЭТАЛОН + [
    {"sport": "T", "home": "Ivashka I.", "away": "Samuel T.", "league": ХЕЛЬСИНКИ, "start_kyiv": "2026-11-16T17:00"},
    {"sport": "T", "home": "A/B", "away": "C/D", "league": "ATP - DOUBLES: Finals - Turin (World), hard (indoor)",
     "start_kyiv": "2026-11-16T11:00"}], learned={})
имя = "ATP Finals Turin"
проверка("правило 1: слово события вынимается из заголовка один раз — стадия ищется в остатке",
         [broadcast.show_stage(имя, t, знаем) for t in (
             "ATP FINALS 2026 - FINAL", "Nitto ATP Finals", "ATP Finale (Torino): Finale", "ATP Finale (Torino): Parovi",
             "Tenis: Turniej ATP Finals w Turynie", "TENIS ATP: TURNEUL CAMPIONILOR", "Tenis ATP: Turneul Campionilor - finala",
             "ATP Finals: Semifinale", "Теннис. ATP. Итоговый турнир. Турин. Финал", "Nitto ATP Finals: Halve Finale")],
         ["Final", "", "Final", "", "", "", "Final", "Semifinals", "Final", "Semifinals"])
проверка("правило 1 (витрина 16.11): турнир назван в заголовке дважды на разных языках — это имя, не финал; "
         "повтор того же написания — стадия",
         [broadcast.show_stage(имя, "Turneul Campionilor Tenis: ATP Finals Torino", знаем),
          broadcast.show_stage(имя, "Turneul Campionilor Tenis: ATP Finals Torino - finala", знаем),
          broadcast.show_stage(имя, "ATP Finals: Finals", знаем)], ["", "Final", "Final"])
проверка("правило 2: имя турнира в незнакомом написании — стадии нет", broadcast.show_stage(имя, "Finali ATP", знаем), "")
проверка("правило 3: обычный турнир — стадия заголовка как есть",
         [broadcast.show_stage("ATP Beijing", "ATP 500 Beijing - Final", знаем),
          broadcast.show_stage("ATP Beijing", "ATP 500 Beijing", знаем)], ["Final", ""])
проверка("слова стадий на языках сайтов (порядок: четвертьфинал, полуфинал, финал)",
         [broadcast.stage(x) for x in ("Halve finale", "Kwartfinale", "Viertelfinale", "Demi-finale", "Cuartos de final",
                                       "Elődöntő", "Döntő", "Yarı final", "Çeyrek final", "Välierä", "Semifinala",
                                       "Sferturi de finală", "Четвъртфинал", "Полуфинале", "Finaali", "Quarti di finale")],
         ["Semifinals", "Quarterfinals", "Quarterfinals", "Semifinals", "Quarterfinals", "Semifinals", "Final",
          "Semifinals", "Quarterfinals", "Semifinals", "Semifinals", "Quarterfinals", "Quarterfinals", "Semifinals",
          "Final", "Quarterfinals"])
проверка("турнир назван по спонсору («HPP Open», tvmatsit.com) — словарь знает город, строка сводится с эталоном",
         (broadcast.key("HPP Open ATP Challenger Tour", знаем), broadcast.tournament("HPP Open ATP Challenger Tour", знаем)),
         (("Challenger", "Helsinki"), "Challenger Helsinki"))
проверка("книга 148: подпись лиги сведённой строки — название турнира у эталона, одиночный разряд главнее парного",
         [знаем["leagues"].get(("ATP", "Finals - Turin")), знаем["leagues"].get(("Challenger", "Helsinki")),
          знаем["leagues"].get(("ATP", "Beijing"))], [ТУРИН, ХЕЛЬСИНКИ, None])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

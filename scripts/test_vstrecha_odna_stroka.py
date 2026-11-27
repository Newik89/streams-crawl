# -*- coding: utf-8 -*-
r"""Книга 181 (27.11.2026): встреча командного турнира — одной строкой; повтор не бережёт прежнюю игру.

Свои промахи книг 178 и 180, найдены проверкой вживую 27.11 (первый сбор на новом коде, 08:15): у полуфинала Кубка
Дэвиса 27.11 рядом с матчем «Italy — Czech Republic» 17:00 стояла вторая строка «Davis Cup» 18:59 (#11568, пять
каналов, все уже при матче); полуфинал 28.11 стоял «Davis Cup» 14:59 вместо «Great Britain — Spain» 13:00 (#11670);
три повтора, заведённые до правила книги 180, оставались живыми (#12066, #12087, #11797). Слово владельца на три
правки 27.11 — «Да, делаем». Правила:
  1. К5 (`broadcast.team_tie`): в час показа встреч нет — строка без пары показывает встречу, начавшуюся не раньше
     `TIE_LONG` минут до показа; встреча у турнира в эти сутки одна (`TIE_ALONE`), иначе не гадаем;
  2. 5а (`parse_live.next_tie_games`): следующая игра встречи с парой и честной пометкой эфира в часы самой встречи
     по эталону — та же встреча (пара остаётся); показ другого дня — строка турнира, как велел владелец 16.11;
  3. `parse_live.fold_ties`: строки, помеченные показом одной встречи эталона (`same_tie`), — одна игра; вторую
     строку того же канала снимает `one_row_per_channel`; игра несёт в итог метку `broadcast.TIE`;
  4. `store.tie_named`: прежняя строка этого турнира без пары в базе (под названием турнира или под заголовком
     сайта) становится матчем — по метке файла; `store._fold_tie_twins`: прежняя строка турнира с живыми отметками
     вливается во встречу (находки пробной заливки в копию базы сервера);
  5. `store.withheld_rows`: строка, снятая как повтор сыгранного матча, прежнюю игру от гашения не бережёт;
  6. `proverka.tie_channel`: сравнение сборов понимает, что канал поздней строки стоит при встрече;
  7. справочник стран: Чехия по-французски, по-итальянски, по-испански, по-португальски, по-турецки.
В сеть не ходит, база временная. Запуск: python scripts/test_vstrecha_odna_stroka.py
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="vstrecha-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import broadcast, db, merge, miss, names, pipeline, store  # noqa: E402
from app.parsers import Program, site_says  # noqa: E402
import parse_live  # noqa: E402
import proverka  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
зелёных = красных = 0
ЛИГА = "TEAMS - MEN: Davis Cup - World Group (World)"


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def час(text: str) -> datetime:
    return datetime.fromisoformat(text)


def встреча(home: str, away: str, start: str, fs: str) -> dict:
    return {"sport": "T", "league": ЛИГА, "home": home, "away": away, "start_kyiv": start, "fs_id": fs}


# эталон сбора 27.11 08:15: два полуфинала Кубка Дэвиса
ИТАЛИЯ = встреча("Italy", "Czech Republic", "2026-11-27T17:00", "Uct9heHk")
БРИТАНИЯ = встреча("Great Britain", "Spain", "2026-11-28T13:00", "Ack5u9r1")
ЭТАЛОН = [ИТАЛИЯ, БРИТАНИЯ,
          {"sport": "T", "league": "ATP - SINGLES: Finals - Turin (World), hard (indoor)", "home": "Sinner J.",
           "away": "Zverev A.", "start_kyiv": "2026-11-27T19:00", "fs_id": "atp1"}]

print("1. К5: строка без пары показывает идущую встречу (`broadcast.team_tie`)")
# живые строки 27.11: sporttv.pt «FINAL 8 - MEIA-FINAL» 18:59 и 20:59, digisport.ro «Tenis: Cupa Davis» 19:00 и 20:30,
# oneplay.cz «Davis Cup 2026, Tenis» 20:30 и 22:30 — при встрече 17:00
проверка("поздние строки полуфинала 27.11 (18:59 … 22:30 при встрече 17:00) — та же встреча",
         {broadcast.team_tie("Davis Cup", час(f"2026-11-27T{t}"), ЭТАЛОН)["fs_id"]
          for t in ("18:59", "19:00", "20:30", "20:59", "22:30")}, {"Uct9heHk"})
проверка("поздние строки полуфинала 28.11 (14:59 и 17:00 при встрече 13:00) — вторая встреча, не вчерашняя",
         [broadcast.team_tie("Davis Cup", час(f"2026-11-28T{t}"), ЭТАЛОН)["fs_id"] for t in ("14:59", "17:00")],
         ["Ack5u9r1"] * 2)
проверка("К4 цел: строка в час встречи — она (12:58 при встрече 13:00)",
         broadcast.team_tie("Davis Cup", час("2026-11-28T12:58"), ЭТАЛОН), БРИТАНИЯ)
проверка("встреча кончилась (позже семи часов от начала), показ задолго до встречи, пары ещё нет (финал 29.11) — None",
         [broadcast.team_tie("Davis Cup", час("2026-11-28T00:01"), ЭТАЛОН),
          broadcast.team_tie("Davis Cup", час("2026-11-27T12:00"), ЭТАЛОН),
          broadcast.team_tie("Davis Cup", час("2026-11-29T17:59"), ЭТАЛОН)], [None] * 3)
проверка("другой командный турнир и одиночный турнир встречей Кубка Дэвиса не становятся",
         [broadcast.team_tie("Billie Jean King Cup", час("2026-11-27T19:00"), ЭТАЛОН),
          broadcast.team_tie("ATP Finals Turin", час("2026-11-27T20:00"), ЭТАЛОН)], [None, None])
# 26.11, четвертьфиналы: две встречи в один день (11:00 и 18:00)
ДВЕ = [встреча("Great Britain", "Germany", "2026-11-26T11:00", "qf3"), встреча("Austria", "Spain", "2026-11-26T18:00", "qf4")]
проверка("в сутках две встречи: в час начала — К4 (17:30 → вторая), между ними и после — не гадаем",
         [(broadcast.team_tie("Davis Cup", час("2026-11-26T17:30"), ДВЕ) or {}).get("fs_id"),
          broadcast.team_tie("Davis Cup", час("2026-11-26T14:00"), ДВЕ),
          broadcast.team_tie("Davis Cup", час("2026-11-26T20:59"), ДВЕ)], ["qf4", None, None])
# отборочный круг: три встречи в разных городах в один день
ТРИ = [встреча("Poland", "Sweden", "2026-11-21T12:00", "a"), встреча("Brazil", "Canada", "2026-11-21T15:00", "b"),
       встреча("France", "Australia", "2026-11-21T19:00", "c")]
проверка("встречи идут разом в разных городах — по времени не угадать, чью показывает сайт",
         broadcast.team_tie("Davis Cup", час("2026-11-21T17:00"), ТРИ), None)
проверка("та же встреча в эталоне дважды (одна метка) — одна встреча",
         broadcast.team_tie("Davis Cup", час("2026-11-27T20:59"), [ИТАЛИЯ, dict(ИТАЛИЯ)]), ИТАЛИЯ)
проверка("часы встречи (`tie_show`): час до начала — да, раньше — нет; семь часов после — да, позже — нет",
         [broadcast.tie_show(час("2026-11-27T17:00"), час(t)) for t in
          ("2026-11-27T16:00", "2026-11-27T15:59", "2026-11-28T00:00", "2026-11-28T00:01")], [True, False, True, False])
проверка("ключ встречи — метка flashscore, без неё — пара имён",
         [broadcast.tie_key(ИТАЛИЯ), broadcast.tie_key({"home": "Italy", "away": "Czech Republic"})],
         ["Uct9heHk", "Italy — Czech Republic"])

print("2. 5а: следующая игра встречи в её же часы — та же встреча (`parse_live.next_tie_games`)")


def когда(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=KYIV)


def показ(start: str, home: str, away: str, домен: str = "nova.bg", канал: str = "nova sport", эфир: bool = True):
    """Строка сайта с парой: `эфир` — сайт сам пометил её прямым эфиром."""
    program = Program(channel_raw=канал, title=f"{home} - {away}", start=когда(start), live_raw="на живо" if эфир else "")
    if эфир:
        program = site_says(program, True)
    return домен, pipeline.Row(program=program, ok=True,
                               live_marker="на живо" if эфир else pipeline.REFERENCE_MARKER,
                               home=home, away=away, sport="T", league="Купа Дейвис",
                               start_kyiv=когда(start), start_utc=когда(start))


# живые строки 27.11: nova.bg «Италия - Чехия» 17:00 и 21:00 (обе с пометкой эфира); 28.11 — показ другого дня
найдено = [показ("2026-11-27T17:00", "Италия", "Чехия"), показ("2026-11-27T21:00", "Италия", "Чехия"),
           показ("2026-11-28T10:00", "Италия", "Чехия"),
           показ("2026-11-27T21:30", "Italia", "Cechia", "raiplay.it", "Rai 1", эфир=False)]
сколько = parse_live.next_tie_games(найдено, ЭТАЛОН)
первая, вторая, завтра, без_пометки = (r for _d, r in найдено)
проверка("правило 4: первый показ — сама встреча, помечен её показом",
         (первая.home, первая.away, parse_live.tie_mark(первая)), ("Италия", "Чехия", ("Uct9heHk", "Davis Cup")))
проверка("правило 5а: показ через четыре часа с пометкой эфира — та же встреча: пара остаётся, лига эталона, "
         "эфир подтверждён эталоном",
         (вторая.home, вторая.away, вторая.league, parse_live.tie_mark(вторая),
          (вторая.program.extra.get(pipeline.TOURNAMENT) or {}).get("эталон")),
         ("Италия", "Чехия", ЛИГА, ("Uct9heHk", "Davis Cup"), True))
проверка("правило 5 цело (слово владельца 16.11): показ другого дня с пометкой эфира — строка турнира на своё время",
         (завтра.home, завтра.away, parse_live.tie_mark(завтра), сколько),
         ("Davis Cup", broadcast.SESSION, ("", ""), 1))
проверка("правило 6 цело: поздний показ без честной пометки сайта не трогаем и не помечаем",
         (без_пометки.home, без_пометки.away, parse_live.tie_mark(без_пометки)), ("Italia", "Cechia", ("", "")))
# книга 165: эталон ставит встречу на соседний день — пара остаётся (правило 4), но показом встречи строка не
# помечается: «часы встречи» по такому эталону не посчитать
сдвиг = [показ("2026-11-21T04:00", "יפן", "ארגנטינה", "sport5.co.il", "ספורט 5")]
parse_live.next_tie_games(сдвиг, [{"sport": "T", "home": "Japan W", "away": "Argentina W", "fs_id": "jp-ar",
                                   "league": "TEAMS - WOMEN: Billie Jean King Cup - World Group",
                                   "start_kyiv": "2026-11-22T05:00"}])
проверка("эталон сдвинут на сутки: пара и пометка W — как в книге 165, показом встречи строка не помечена",
         (сдвиг[0][1].home, сдвиг[0][1].away, parse_live.tie_mark(сдвиг[0][1])), ("יפן W", "ארגנטינה W", ("", "")))

print("3. Строки одной встречи — одна игра (`parse_live.fold_ties`, `tie_field`)")


def строка(start: str, home: str, away: str, домен: str, канал: str, ключ: str = "Uct9heHk", турнир: str = "Davis Cup"):
    """Запись склейки из строки сайта; `ключ` — строка помечена показом встречи (`same_tie`)."""
    _d, r = показ(start, home, away, домен, канал)
    if ключ:
        parse_live.same_tie(r, ключ, турнир)
    return merge.Entry(source=домен, channel=канал, home=r.home, away=r.away, start=r.start_kyiv, sport="T",
                       league=ЛИГА, payload=r)


записи = [
    # строки без пары, получившие пару эталона (К4): sporttv.pt 16:58, oneplay.cz 16:30
    строка("2026-11-27T16:58", "Italy", "Czech Republic", "sporttv.pt", "SPORT.TV6"),
    строка("2026-11-27T16:30", "Italy", "Czech Republic", "oneplay.cz", "ČT2"),
    # поздняя строка того же канала (К5) — в окне склейки от первой
    строка("2026-11-27T18:59", "Italy", "Czech Republic", "sporttv.pt", "SPORT.TV6"),
    # поздняя строка дальше окна склейки от всех прочих (К5): без правила — отдельная игра
    строка("2026-11-27T22:30", "Italy", "Czech Republic", "oneplay.cz", "ČT2"),
    # имена на языке, которого склейка не знает, но строка помечена показом той же встречи
    строка("2026-11-27T17:00", "Команда хозяев", "Команда гостей", "tvpassport.com", "TVA Sports 2"),
    # другая встреча и игра без пометки — не трогаются
    строка("2026-11-28T13:00", "Great Britain", "Spain", "nova.bg", "nova sport", ключ="Ack5u9r1"),
    строка("2026-11-27T19:00", "Sinner J.", "Zverev A.", "sporttv.pt", "SPORT.TV1", ключ=""),
    # строка турнира другого дня (правило 5 книги 149) — не помечена, остаётся своей строкой
    строка("2026-11-28T10:00", "Davis Cup", broadcast.SESSION, "nova.bg", "nova sport", ключ=""),
]
до = merge.merge(list(записи))
игры, влито = parse_live.fold_ties(до)
матч = next(g for g in игры if g.home == "Italy")
проверка("склейка одна оставляет встречу тремя играми (дальний показ и чужие имена) — правило сводит в одну",
         (len([g for g in до if any(parse_live.tie_mark(e.payload)[0] == "Uct9heHk" for e in g.entries)]), влито,
          len(матч.entries), матч.start.strftime("%d %H:%M")), (3, 2, 5, "27 16:30"))
проверка("прочие игры на месте: вторая встреча, одиночный матч, строка турнира другого дня",
         sorted((g.home, len(g.entries)) for g in игры if g is not матч),
         [("Davis Cup", 1), ("Great Britain", 1), ("Sinner J.", 1)])
игры, снятые = parse_live.one_row_per_channel(игры)
проверка("вторые строки тех же каналов сняты в журнал, у матча каждый канал один раз",
         (sorted((e.source, e.start.strftime("%H:%M")) for _g, e, _keep in снятые),
          sorted((e.source, e.channel) for e in матч.entries)),
         ([("oneplay.cz", "22:30"), ("sporttv.pt", "18:59")],
          [("oneplay.cz", "ČT2"), ("sporttv.pt", "SPORT.TV6"), ("tvpassport.com", "TVA Sports 2")]))
проверка("метка итога: у встречи — название турнира; у игры без пометки и у строки турнира без пары — нет",
         [parse_live.tie_field(матч), parse_live.tie_field(next(g for g in игры if g.home == "Sinner J.")),
          parse_live.tie_field(next(g for g in игры if g.home == "Davis Cup"))],
         [{broadcast.TIE: "Davis Cup"}, {}, {}])
код = inspect.getsource(parse_live)
проверка("детектор: сведение встреч стоит сразу после склейки, до снятия повторов; метка уходит в итог",
         [0 < код.index("games, встреч_сведено = fold_ties(games)")
          < код.index("games, повторы = drop_reference_repeats(games, reference_full)"),
          "**tie_field(g)," in код], [True, True])
блок = код[код.index("встреча = broadcast.team_tie(командный, r.start_kyiv, reference_full)"):][:600]
проверка("детектор: строка без пары, получившая пару эталона, помечается показом встречи",
         "same_tie(r, broadcast.tie_key(встреча), командный)" in блок)

print("4. Заливка: строка турнира без пары становится матчем (`store.tie_named`)")
САЙТЫ = ("sporttv.pt", "epg.cyta.com.cy", "nova.bg", "tvarenasport.com", "ziggosport.nl", "sportklub.hr",
         "novasports.gr")
ДЕНЬ = (date.today() + timedelta(days=5)).isoformat()
ЧАСЫ = datetime.combine(date.today(), datetime.min.time()).replace(hour=12)
# строки полуфинала 28.11 13:00, как их отдали сайты 27.11
СТРОКИ = [("sporttv.pt", "SPORT.TV6", "FINAL 8 - MEIA-FINAL"), ("epg.cyta.com.cy", "Novasports 6 HD", "Tennis: 2026 Davis Cup"),
          ("nova.bg", "nova sport", "Полуфинал"), ("tvarenasport.com", "Arena Tenis", "Polufinale 2"),
          ("ziggosport.nl", "Ziggo Sport 4", "Davis Cup Finals 2026:"), ("sportklub.hr", "Sport Klub 2", "Davis Cup: 1/2 Finale B")]
ПОЗДНИЕ = [("sporttv.pt", "SPORT.TV6", "FINAL 8 - MEIA-FINAL"), ("novasports.gr", "Novasports6HD", "Τένις: Davis Cup 2026, Ημιτελικός")]


def игра(home, away, строки, время="13:00", league=ЛИГА, **метки):
    return {"sport": "T", "league": league, "home": home, "away": away, "start_kyiv": f"{ДЕНЬ}T{время}",
            "start_utc": f"{ДЕНЬ}T11:00", **метки,
            "entries": [{"source": сайт, "channel": канал, "url": "", "raw_title": заголовок}
                        for сайт, канал, заголовок in строки]}


def новая_база():
    path = TMP / f"t{len(list(TMP.glob('*.db')))}.db"
    os.environ["STREAMS_DB"] = str(path)
    db.init_db()
    conn = db.connect()
    for n, домен in enumerate(САЙТЫ, 1):
        conn.execute("INSERT INTO sources (id, domain, name, base_url, country, enabled) VALUES (?, ?, ?, ?, 'XX', 1)",
                     (n, домен, домен, f"https://{домен}/"))
    conn.commit()
    return conn


def события(conn):
    return [(r["team_home_auto"], r["team_away_auto"], r["start_kyiv"][11:16], r["n"]) for r in conn.execute(
        "SELECT e.team_home_auto, e.team_away_auto, e.start_kyiv, COUNT(ec.id) AS n FROM events e "
        "LEFT JOIN event_channels ec ON ec.event_id = e.id GROUP BY e.id ORDER BY e.id")]


# база сервера утром 27.11: полуфинал 28.11 — строка турнира (пары ещё не было)
conn = новая_база()
store.save_games(conn, [игра("Davis Cup", broadcast.SESSION, СТРОКИ, **{broadcast.MERGED: 1})], now=ЧАСЫ, punish=False)
проверка("до: в базе одна строка турнира без пары", события(conn), [("Davis Cup", broadcast.SESSION, "13:00", 6)])
# эталон назвал пару: те же строки сайтов приходят матчем с меткой встречи
матч_файла = игра("Great Britain", "Spain", СТРОКИ, время="12:58", **{broadcast.TIE: "Davis Cup"})
store.save_games(conn, [матч_файла], now=ЧАСЫ, punish=False)
проверка("после: та же строка базы стала матчем — имена пары, время матча, все шесть отметок, второй игры нет",
         события(conn), [("Great Britain", "Spain", "12:58", 6)])
проверка("лига матча — из файла", conn.execute("SELECT league_auto FROM events").fetchone()[0], ЛИГА)
# остаток строки турнира (такой отдавал прежний разбор) матч по имени уже не находит и время ему не сдвигает
store.save_games(conn, [матч_файла, игра("Davis Cup", broadcast.SESSION, ПОЗДНИЕ, время="14:59", **{broadcast.MERGED: 1})],
                 now=ЧАСЫ, punish=False)
проверка("остаток строки турнира время матча не сдвигает (27.11 так вышло «Davis Cup» 14:59 вместо 13:00)",
         события(conn)[0], ("Great Britain", "Spain", "12:58", 6))
conn.close()
# без метки файла (игра не узнана встречей турнира) — как раньше: имя строки не трогаем
conn = новая_база()
store.save_games(conn, [игра("Davis Cup", broadcast.SESSION, СТРОКИ, **{broadcast.MERGED: 1})], now=ЧАСЫ, punish=False)
store.save_games(conn, [игра("Great Britain", "Spain", СТРОКИ, время="12:58")], now=ЧАСЫ, punish=False)
проверка("правило 1: без метки встречи имя строки турнира не меняется", события(conn)[0][:2], ("Davis Cup", broadcast.SESSION))
conn.close()


class Строка(dict):
    """Игра базы для проверки правила без заливки."""


встреча_файла = игра("Great Britain", "Spain", [], **{broadcast.TIE: "Davis Cup"})
проверка("правило 2: строка ЭТОГО турнира без пары → да; другого турнира, пара, с меткой эталона → нет",
         [store.tie_named(встреча_файла, Строка(team_home_auto="Davis Cup", team_away_auto=broadcast.SESSION, flags=None)),
          store.tie_named(встреча_файла, Строка(team_home_auto="Billie Jean King Cup", team_away_auto=broadcast.SESSION, flags=None)),
          store.tie_named(встреча_файла, Строка(team_home_auto="Davis Cup", team_away_auto="finále", flags=None)),
          store.tie_named(встреча_файла, Строка(team_home_auto="Davis Cup", team_away_auto=broadcast.SESSION, flags="fs:abc"))],
         [True, False, False, False])
проверка("правило 1: строка турнира без пары, игра без метки и не теннис матчем не делают; игра базы без поля меток читается",
         [store.tie_named(игра("Davis Cup", broadcast.SESSION, [], **{broadcast.TIE: "Davis Cup"}),
                          Строка(team_home_auto="Davis Cup", team_away_auto=broadcast.SESSION, flags=None)),
          store.tie_named(игра("Great Britain", "Spain", []),
                          Строка(team_home_auto="Davis Cup", team_away_auto=broadcast.SESSION, flags=None)),
          store.tie_named(dict(встреча_файла, sport="F"),
                          Строка(team_home_auto="Davis Cup", team_away_auto=broadcast.SESSION, flags=None)),
          store.tie_named(встреча_файла, Строка(team_home_auto="Davis Cup", team_away_auto=broadcast.SESSION))],
         [False, False, False, True])
проверка("прежние правила переименования целы: сведённое имя вытесняет заголовок сайта только по своей метке",
         [store.tournament_renamed(игра("Davis Cup", broadcast.SESSION, [], **{broadcast.MERGED: 1}),
                                   Строка(team_home_auto="Polufinale 1", team_away_auto=broadcast.SESSION, flags=None)),
          store.tournament_renamed(встреча_файла, Строка(team_home_auto="Davis Cup", team_away_auto=broadcast.SESSION, flags=None))],
         [True, False])

проверка("правило 2: строка под заголовком сайта («Elődöntő — Bologna», port.hu) — матч, когда турнир назван в её "
         "лиге или заголовке отметки; не назван или назван другой — нет",
         [store.tie_named(встреча_файла, Строка(team_home_auto="Elődöntő", team_away_auto="Bologna", flags=None),
                          ["Tenisz Davis Kupa: Elődöntő - Bologna"]),
          store.tie_named(встреча_файла, Строка(team_home_auto="Elődöntő", team_away_auto="Bologna", flags=None), []),
          store.tie_named(встреча_файла, Строка(team_home_auto="Elődöntő", team_away_auto="Bologna", flags=None),
                          ["Tenisz Billie Jean King-kupa: Elődöntő"]),
          store.tie_named(встреча_файла, Строка(team_home_auto="Alcaraz C.", team_away_auto="Tiafoe F.", flags=None),
                          ["Tenisz Davis Kupa"])],
         [True, False, False, False])

# проба на копии базы сервера 27.11: в базе — погашенная строка port.hu под своим заголовком, большая строка турнира
# (её время сдвинул остаток — 14:59) и строка турнира другого дня; приходит матч с парой
ВЕНГРИЯ = ("port.hu", "M4 Sport", "Tenisz Davis Kupa: Elődöntő - Bologna")
САЙТЫ = САЙТЫ + ("port.hu",)
conn = новая_база()
store.save_games(conn, [игра("Elődöntő", "Bologna", [ВЕНГРИЯ], league="Tenisz Davis Kupa")], now=ЧАСЫ, punish=False)
store.save_games(conn, [игра("Davis Cup", broadcast.SESSION, СТРОКИ, время="14:59", **{broadcast.MERGED: 1})],
                 now=ЧАСЫ, punish=False)
завтра = (date.today() + timedelta(days=6)).isoformat()
другой_день = dict(игра("Davis Cup", broadcast.SESSION, СТРОКИ[:2], время="16:00", **{broadcast.MERGED: 1}),
                   start_kyiv=f"{завтра}T16:00", start_utc=f"{завтра}T14:00")
store.save_games(conn, [другой_день], now=ЧАСЫ, punish=False)
проверка("до: строка под заголовком сайта, строка турнира 14:59 и строка турнира другого дня",
         события(conn), [("Elődöntő", "Bologna", "13:00", 1), ("Davis Cup", broadcast.SESSION, "14:59", 6),
                         ("Davis Cup", broadcast.SESSION, "16:00", 2)])
stats = store.save_games(conn, [игра("Great Britain", "Spain", СТРОКИ + [ВЕНГРИЯ], время="12:58",
                                     **{broadcast.TIE: "Davis Cup"}), другой_день], now=ЧАСЫ, punish=False)
проверка("после: матч сел на строку port.hu и дал ей имя пары; прежняя строка турнира 14:59 влита во встречу — "
         "на витрине одна строка; строка другого дня цела",
         (события(conn), stats.ties_folded),
         ([("Great Britain", "Spain", "12:58", 7), ("Davis Cup", broadcast.SESSION, "16:00", 2)], 1))
conn.close()
# у прежней строки турнира есть живой канал, которого у встречи нет, — это не её двойник
conn = новая_база()
ЧУЖОЙ_КАНАЛ = ("novasports.gr", "Novasports Prime", "Τένις: Davis Cup 2026")
store.save_games(conn, [игра("Davis Cup", broadcast.SESSION, СТРОКИ + [ЧУЖОЙ_КАНАЛ], время="14:59", **{broadcast.MERGED: 1})],
                 now=ЧАСЫ, punish=False)
stats = store.save_games(conn, [игра("Great Britain", "Spain", СТРОКИ, время="12:58", **{broadcast.TIE: "Davis Cup"})],
                         now=ЧАСЫ, punish=False)
проверка("правило 2 вливания: у прежней строки живой канал, которого у встречи нет, — строка остаётся",
         (события(conn), stats.ties_folded),
         ([("Davis Cup", broadcast.SESSION, "14:59", 7), ("Great Britain", "Spain", "12:58", 6)], 0))
conn.close()

print("5. Повтор сыгранного матча прежнюю игру не бережёт (`store.withheld_rows`)")
СНЯТО = [{"домен": "www.novasports.gr", "start_kyiv": "2026-11-27T20:45", "фильтр": parse_live.СНЯТО_СТАРЫЙ_ПОВТОР},
         {"домен": "poverkhnost.tv", "start_kyiv": "2026-11-28T09:45", "фильтр": parse_live.СНЯТО_СЫГРАН},
         {"домен": "movistarplus.es", "start_kyiv": "2026-11-27T19:00", "фильтр": parse_live.СНЯТО_НЕТ_В_ЭТАЛОНЕ_БТ},
         {"домен": "raiplay.it", "start_kyiv": "2026-11-27T19:05", "фильтр": parse_live.СНЯТО_НЕ_БЛИЖАЙШИЙ},
         {"домен": "old.test", "start_kyiv": "2026-11-27T10:00"}]
проверка("строки-повторы в защиту не идут; снятые другими фильтрами, без имени фильтра и нерешённые — идут, как раньше",
         store.withheld_rows({"снято": СНЯТО, "на_разбор": [{"домен": "nova.bg", "start_kyiv": "2026-11-27T18:00"}],
                              "без_эталона": [{"домен": "cyta.test", "start_kyiv": "2026-11-27T21:00"}]}),
         {("movistarplus.es", "2026-11-27 19:00"), ("raiplay.it", "2026-11-27 19:05"), ("old.test", "2026-11-27 10:00"),
          ("nova.bg", "2026-11-27 18:00"), ("cyta.test", "2026-11-27 21:00")})
фильтры = {имя: значение for имя, значение in vars(parse_live).items()
           if имя.startswith("СНЯТО_") and isinstance(значение, str)}
проверка("детектор: с «повтор» начинаются ровно два фильтра — повтор по эталону и повтор по памяти сборов",
         sorted(имя for имя, значение in фильтры.items() if значение.startswith(store.ПОВТОР)),
         ["СНЯТО_СТАРЫЙ_ПОВТОР", "СНЯТО_СЫГРАН"])

# заливка: игра заведена до правила, теперь её строка снята как повтор — отметка гаснет; снята другим фильтром — живёт
СВОЙ, ЧУЖОЙ, ДЕНЬ_СБОРА = "sporttv.pt", "nova.bg", "2026-10-06"
АДРЕС = {СВОЙ: f"https://sporttv.pt/guia?date={ДЕНЬ_СБОРА}", ЧУЖОЙ: f"https://nova.bg/tv?date={ДЕНЬ_СБОРА}"}


def футбол(home, away, hhmm, *строки):
    return {"sport": "F", "league": "", "home": home, "away": away, "start_kyiv": f"{ДЕНЬ_СБОРА}T{hhmm}", "start_utc": "",
            "entries": [{"source": домен, "channel": канал, "url": АДРЕС[домен], "raw_title": ""} for домен, канал in строки]}


def после_сбора(фильтр: str) -> int:
    """Счётчик пропусков отметки игры-повтора после сбора, в котором её строка снята фильтром `фильтр`."""
    conn = новая_база()
    ночь = datetime(2026, 10, 6, 1, 0)
    первый = [футбол("Valencia", "Virtus Bologna", "20:45", (СВОЙ, "SPORT.TV1")),
              футбол("Liverpool", "Everton", "20:00", (СВОЙ, "SPORT.TV2"), (ЧУЖОЙ, "nova sport"))]
    store.save_games(conn, первый, now=ночь)
    отчёт = [{"domain": домен, "channel": "", "day": ДЕНЬ_СБОРА, "итог": "расписание есть", "url": АДРЕС[домен]}
             for домен in (СВОЙ, ЧУЖОЙ)]
    итог = {"снято": [{"домен": СВОЙ, "канал": "SPORT.TV1", "start_kyiv": f"{ДЕНЬ_СБОРА}T20:45", "фильтр": фильтр}]}
    store.save_games(conn, первый[1:], now=ночь, coverage=miss.покрытие_из_отчёта(отчёт),
                     collected=f"{ДЕНЬ_СБОРА} 01:00", withheld=store.withheld_rows(итог))
    счёт = conn.execute("SELECT ec.miss_count FROM event_channels ec JOIN events e ON e.id = ec.event_id "
                        "WHERE e.team_home_auto = 'Valencia'").fetchone()[0]
    conn.close()
    return счёт


проверка("строка снята как повтор по памяти сборов или по эталону — отметка прежней игры гаснет",
         [после_сбора(parse_live.СНЯТО_СТАРЫЙ_ПОВТОР), после_сбора(parse_live.СНЯТО_СЫГРАН)], [store.MISS_LIMIT] * 2)
проверка("строка удержана другим фильтром (эфир не подтверждён) — отметка живёт, как раньше",
         после_сбора(parse_live.СНЯТО_НЕТ_В_ЭТАЛОНЕ_БТ), 0)

print("6. Сравнение сборов понимает К5 (`proverka.tie_channel`)")


def запись(home, away, когда_, строки, **метки):
    return {"sport": "T", "league": "", "home": home, "away": away, "start_kyiv": когда_, "guess": 0, **метки,
            "entries": [{"source": сайт, "channel": канал, "start_kyiv": время, "raw_title": "", "url": ""}
                        for сайт, канал, время in строки]}


У_МАТЧА = [("oneplay.cz", "ČT2", "2026-12-04T16:30"), ("sporttv.pt", "SPORT.TV6", "2026-12-04T16:58"),
           ("nova.bg", "nova sport", "2026-12-04T17:00")]
ПОЗЖЕ = [("sporttv.pt", "SPORT.TV6", "2026-12-04T20:30"), ("oneplay.cz", "ČT2", "2026-12-04T20:30"),
         ("nova.bg", "nova sport", "2026-12-04T21:00")]
прочая = запись("ATP Lyon", "tournament", "2026-12-04T12:00", [("teleman.pl", "Polsat Sport 2", "2026-12-04T12:00")])
было = {"games": [запись("Italy", "Czech Republic", "2026-12-04T16:30", У_МАТЧА),
                  запись("Davis Cup", "tournament", "2026-12-04T20:30", ПОЗЖЕ), прочая]}
стало = {"games": [запись("Italy", "Czech Republic", "2026-12-04T16:30", У_МАТЧА, **{broadcast.TIE: "Davis Cup"}), прочая]}
проверка("вторая строка «Davis Cup» (через четыре часа после начала встречи) пропала, её каналы стоят при встрече — потерь нет",
         proverka.compare(было, стало), [])
проверка("канал поздней строки найден при встрече этого турнира; при игре без метки встречи — нет",
         [(proverka.tie_channel("SPORT.TV6", "sporttv.pt", было["games"][1], стало["games"]) or {}).get("home"),
          proverka.tie_channel("SPORT.TV6", "sporttv.pt", было["games"][1], было["games"])], ["Italy", None])
без_канала = {"games": [запись("Italy", "Czech Republic", "2026-12-04T16:30", У_МАТЧА[:2], **{broadcast.TIE: "Davis Cup"}), прочая]}
проверка("канала поздней строки при встрече нет — это потеря, как раньше",
         bool(proverka.compare(было, без_канала)), True)
частично = {"games": [запись("Italy", "Czech Republic", "2026-12-04T16:30", У_МАТЧА, **{broadcast.TIE: "Davis Cup"}),
                      запись("Davis Cup", "tournament", "2026-12-04T20:30", [("teleman.pl", "Polsat Sport 3", "2026-12-04T20:30")]),
                      прочая]}
было_шире = {"games": [было["games"][0],
                       запись("Davis Cup", "tournament", "2026-12-04T20:30",
                              ПОЗЖЕ + [("teleman.pl", "Polsat Sport 3", "2026-12-04T20:30")]), прочая]}
проверка("строка турнира осталась с одним каналом, остальные перешли к встрече — потерь нет",
         proverka.compare(было_шире, частично), [])

print("7. Справочник стран: Чехия на языках сайтов")
проверка("«Tchéquie» (фр.), «Cechia» (ит.), «Chequia» (исп.), «Chéquia» и «Tchéquia» (порт.), «Çekya» (тур.) — Чехия",
         {names.country_of(x) for x in ("Tchéquie", "Cechia", "Chequia", "Chéquia", "Tchéquia", "Çekya")},
         {names.country_of("Czech Republic")})
проверка("страна узнана — строка tvpassport.com «Italie — Tchéquie» сходится с матчем уже в склейке",
         bool(names.country_of("Czech Republic")) and len(merge.merge([
             merge.Entry(source="a", channel="A", home="Italy", away="Czech Republic", start=час("2026-11-27T17:00"), sport="T"),
             merge.Entry(source="b", channel="B", home="Italie", away="Tchéquie", start=час("2026-11-27T17:00"), sport="T")])),
         1)

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

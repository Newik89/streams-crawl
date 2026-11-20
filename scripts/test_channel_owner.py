# -*- coding: utf-8 -*-
"""Проверки правила «свой сайт канала важнее агрегатора» — по одной на правило.

Запуск: venv\\Scripts\\python.exe scripts/test_channel_owner.py
К сети не обращается, база — временная в памяти.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="owner-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test0.db")

from app import channel_owner, db, store  # noqa: E402

#: своя база на каждый вызов `база()` — миграции накатывает `db.connect`
_счёт = [0]

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


#: часы заливки — сегодня в полдень, а не настоящие: игры теста стоят на
#: 20:00, и после 20:00 заливка (`save_games`) законно не брала «уже
#: прошедшую» игру — тест краснел сам по себе каждый вечер (11.10.2026)
ЧАСЫ = datetime.combine(date.today(), datetime.min.time()).replace(hour=12)


def день(n: int) -> str:
    """Дата заливки от сегодняшнего дня: `save_games(now=None)` смотрит на
    настоящие часы, и зашитые «2026-10-08» назавтра ушли в прошлое — 09.10
    тест покраснел сам по себе. 0 — сегодня, 3 — через три дня."""
    return (date.today() + timedelta(days=n)).isoformat()


def база() -> sqlite3.Connection:
    _счёт[0] += 1
    os.environ["STREAMS_DB"] = str(TMP / f"test{_счёт[0]}.db")
    conn = db.connect()
    db.init_db(conn)
    conn.execute(
        "INSERT INTO sources (id, domain, name, base_url, country, enabled, "
        "selector_config) VALUES (1, 'sportklub.hr', 'Sport Klub', "
        "'https://sportklub.hr/', 'HR', 1, ?)",
        (json.dumps({channel_owner.ФЛАГ: True}),))
    conn.execute(
        "INSERT INTO sources (id, domain, name, base_url, country, enabled) "
        "VALUES (2, 'mojtv.hr', 'MojTV', 'https://mojtv.hr/', 'HR', 1)")
    conn.execute(
        "INSERT INTO channels (id, canonical_name, slug, country) "
        "VALUES (51, 'Sport Klub 1', 'sport-klub-1-hr', 'HR')")
    conn.execute(
        "INSERT INTO channels (id, canonical_name, slug, country) "
        "VALUES (52, 'MAX Sport 1', 'max-sport-1-hr', 'HR')")
    conn.commit()
    return conn


def прошлый_сбор(conn, день: str, когда: str) -> None:
    """Как будто официальный сайт уже приносил этот день: алиас канала от
    него и отметка на игре с меткой «видели `когда`»."""
    conn.execute("INSERT OR IGNORE INTO channel_aliases (channel_id, alias, "
                 "source_id) VALUES (51, 'Sport Klub 1', 1)")
    cur = conn.execute(
        "INSERT INTO events (sport, league_auto, team_home_auto, "
        "team_away_auto, start_utc, start_kyiv, last_seen) "
        "VALUES ('F', 'Liga', 'C', 'D', ?, ?, ?)",
        (f"{день} 17:00", f"{день} 20:00", когда))
    conn.execute("INSERT INTO event_channels (event_id, channel_id, "
                 "source_id, source_url, raw_title, last_seen, miss_count) "
                 "VALUES (?, 51, 1, '', '', ?, 0)", (cur.lastrowid, когда))
    conn.commit()


def игра(день: str, строки: list[tuple[str, str]]) -> dict:
    return {"sport": "F", "league": "Liga", "home": "A", "away": "B",
            "start_kyiv": f"{день}T20:00", "start_utc": f"{день}T17:00",
            "entries": [{"source": сайт, "channel": канал, "url": "",
                         "raw_title": f"{канал}: A - B"}
                        for сайт, канал in строки]}


# ── правило 5 (книга 169): тот же показ, что у своего сайта канала ───────────

def свой_показ(conn, время: str, дом: str, гости: str, канал: int = 51,
               вид: str = "F") -> int:
    """Игра сегодня в `время`, которую свой сайт (sportklub.hr) показывает на
    канале `канал`; отметка свежая — день в глубине своего сайта."""
    conn.execute("INSERT OR IGNORE INTO channels (id, canonical_name, slug, country) "
                 "VALUES (53, 'Sport Klub 2', 'sport-klub-2-hr', 'HR')")
    for номер, имя in ((51, "Sport Klub 1"), (53, "Sport Klub 2")):
        conn.execute("INSERT OR IGNORE INTO channel_aliases (channel_id, alias, "
                     "source_id) VALUES (?, ?, 1)", (номер, имя))
    когда = ЧАСЫ.strftime("%Y-%m-%d %H:%M")
    cur = conn.execute(
        "INSERT INTO events (sport, league_auto, team_home_auto, "
        "team_away_auto, start_utc, start_kyiv, last_seen) "
        "VALUES (?, 'Turska liga', ?, ?, ?, ?, ?)",
        (вид, дом, гости, f"{день(0)} 17:00", f"{день(0)} {время}", когда))
    conn.execute("INSERT INTO event_channels (event_id, channel_id, "
                 "source_id, source_url, raw_title, last_seen, miss_count) "
                 "VALUES (?, ?, 1, '', 'Trabzon - Eyup', ?, 0)",
                 (cur.lastrowid, канал, когда))
    conn.commit()
    return cur.lastrowid


def агрегатор(время: str = "20:00", каналы=("Sport Klub 1",), вид: str = "F") -> dict:
    """Та же игра у mojtv.hr под другим написанием команд."""
    return {"sport": вид, "league": "", "home": "Trabzon", "away": "Eyup",
            "start_kyiv": f"{день(0)}T{время}", "start_utc": f"{день(0)}T17:00",
            "entries": [{"source": "mojtv.hr", "channel": канал, "url": "",
                         "raw_title": "Turska liga: Trabzon - Eyup"}
                        for канал in каналы]}


def игры_дня(conn) -> list:
    """Игры сегодня с живыми каналами: (время, дом, гости, [сайт/канал])."""
    out = []
    for e in conn.execute("SELECT id, start_kyiv, team_home_auto, team_away_auto "
                          "FROM events WHERE start_kyiv LIKE ? ORDER BY start_kyiv, id",
                          (день(0) + "%",)).fetchall():
        каналы = sorted(f"{r['domain']}/{r['canonical_name']}" for r in conn.execute(
            "SELECT s.domain, c.canonical_name FROM event_channels ec "
            "JOIN sources s ON s.id = ec.source_id JOIN channels c "
            "ON c.id = ec.channel_id WHERE ec.event_id = ? AND ec.miss_count = 0",
            (e["id"],)))
        out.append((e["start_kyiv"][11:16], e["team_home_auto"], e["team_away_auto"], каналы))
    return out


СВОЯ = ("20:00", "TRABZONSPOR", "EYUPSPOR", ["sportklub.hr/Sport Klub 1"])
ДВОЙНИК = ("20:00", "Trabzon", "Eyup", ["mojtv.hr/Sport Klub 1"])


def правило_пять() -> None:
    print("Правило 5 (книга 169): тот же показ, что у своего сайта канала")

    # тот же канал, та же минута, имена не сошлись — вторую игру не заводим
    conn = база()
    свой_показ(conn, "20:00", "TRABZONSPOR", "EYUPSPOR")
    stats = store.save_games(conn, [агрегатор()], now=ЧАСЫ)
    проверка("тот же канал и минута — второй игры нет", игры_дня(conn), [СВОЯ])
    проверка("счётчики: не заведена одна, строка агрегатора не взята",
             (stats.new, stats.same_show, stats.not_own), (0, 1, 1))

    # время у агрегатора на 10 минут позже — тот же показ; время и имена игры
    # остаются от своего сайта
    conn = база()
    свой_показ(conn, "20:00", "TRABZONSPOR", "EYUPSPOR")
    store.save_games(conn, [агрегатор("20:10")], now=ЧАСЫ)
    проверка("десять минут разницы — тот же показ, время и имена — своего сайта",
             игры_дня(conn), [СВОЯ])

    # дальше четверти часа — другая передача: игру заводим, как раньше
    conn = база()
    свой_показ(conn, "20:00", "TRABZONSPOR", "EYUPSPOR")
    stats = store.save_games(conn, [агрегатор("20:20")], now=ЧАСЫ)
    проверка("двадцать минут разницы — игра заводится, как раньше",
             (игры_дня(conn), stats.same_show),
             ([СВОЯ, ("20:20", "Trabzon", "Eyup", ["mojtv.hr/Sport Klub 1"])], 0))

    # свой сайт показывает игру на ДРУГОМ своём канале — не тот же показ
    conn = база()
    свой_показ(conn, "20:00", "TRABZONSPOR", "EYUPSPOR", канал=53)
    stats = store.save_games(conn, [агрегатор()], now=ЧАСЫ)
    проверка("другой канал своего сайта — игра заводится",
             (len(игры_дня(conn)), stats.same_show), (2, 0))

    # вид спорта спорит — не тот же показ
    conn = база()
    свой_показ(conn, "20:00", "TRABZONSPOR", "EYUPSPOR", вид="B")
    stats = store.save_games(conn, [агрегатор()], now=ЧАСЫ)
    проверка("вид спорта другой — игра заводится",
             (len(игры_дня(conn)), stats.same_show), (2, 0))

    # у своего сайта на канале две игры рядом — не гадаем
    conn = база()
    свой_показ(conn, "19:50", "TRABZONSPOR", "EYUPSPOR")
    свой_показ(conn, "20:05", "Konyaspor", "Besiktas")
    stats = store.save_games(conn, [агрегатор()], now=ЧАСЫ)
    проверка("пар две — не гадаем, игра заводится",
             (len(игры_дня(conn)), stats.same_show), (3, 0))

    # у игры агрегатора есть и канал без своего сайта — у неё свой канал
    conn = база()
    свой_показ(conn, "20:00", "TRABZONSPOR", "EYUPSPOR")
    stats = store.save_games(conn, [агрегатор(каналы=("Sport Klub 1", "MAX Sport 1"))],
                             now=ЧАСЫ)
    проверка("есть канал без своего сайта — игра заводится с ним",
             (игры_дня(conn), stats.same_show),
             ([СВОЯ, ("20:00", "Trabzon", "Eyup", ["mojtv.hr/MAX Sport 1"])], 0))

    # своего показа рядом нет — единственную строку бережём, как раньше
    conn = база()
    свой_показ(conn, "15:00", "Galatasaray", "Samsun")
    stats = store.save_games(conn, [агрегатор()], now=ЧАСЫ)
    проверка("свой сайт в эту минуту ничего не показывает — строку бережём",
             (игры_дня(conn)[-1], stats.same_show), (ДВОЙНИК, 0))

    # прежний двойник (завёлся до правила): следующая заливка его убирает
    conn = база()
    store.save_games(conn, [агрегатор()], now=ЧАСЫ)
    свой_показ(conn, "20:00", "TRABZONSPOR", "EYUPSPOR")
    проверка("до правила: двойник стоит рядом", игры_дня(conn), [ДВОЙНИК, СВОЯ])
    stats = store.save_games(conn, [агрегатор()], now=ЧАСЫ)
    проверка("прежний двойник убран", игры_дня(conn), [СВОЯ])
    проверка("счётчики: показ один, двойник убран, отметка снята",
             (stats.same_show, stats.same_show_folded, stats.not_own_dropped), (1, 1, 1))

    # у «двойника» есть живой канал другого сайта — это отдельная игра, не трогаем
    conn = база()
    store.save_games(conn, [агрегатор(каналы=("Sport Klub 1", "MAX Sport 1"))], now=ЧАСЫ)
    свой_показ(conn, "20:00", "TRABZONSPOR", "EYUPSPOR")
    stats = store.save_games(conn, [агрегатор(каналы=("Sport Klub 1", "MAX Sport 1"))],
                             now=ЧАСЫ)
    проверка("игра с живым чужим каналом остаётся",
             (игры_дня(conn), stats.same_show_folded),
             ([("20:00", "Trabzon", "Eyup", ["mojtv.hr/MAX Sport 1"]), СВОЯ], 0))

    # дозабор только дописывает: новую игру не заводит, прежний двойник не трогает
    conn = база()
    свой_показ(conn, "20:00", "TRABZONSPOR", "EYUPSPOR")
    stats = store.save_games(conn, [агрегатор()], now=ЧАСЫ, add_only=True)
    проверка("дозабор: второй игры нет", (игры_дня(conn), stats.same_show), ([СВОЯ], 1))
    conn = база()
    store.save_games(conn, [агрегатор()], now=ЧАСЫ)
    свой_показ(conn, "20:00", "TRABZONSPOR", "EYUPSPOR")
    stats = store.save_games(conn, [агрегатор()], now=ЧАСЫ, add_only=True)
    проверка("дозабор: прежний двойник не трогает",
             (игры_дня(conn), stats.same_show), ([ДВОЙНИК, СВОЯ], 0))

    # без официальных сайтов правило молчит
    conn = база()
    свой_показ(conn, "20:00", "TRABZONSPOR", "EYUPSPOR")
    conn.execute("UPDATE sources SET selector_config = NULL WHERE id = 1")
    conn.commit()
    stats = store.save_games(conn, [агрегатор()], now=ЧАСЫ)
    проверка("сайт не помечен официальным — правило молчит",
             (len(игры_дня(conn)), stats.same_show), (2, 0))

    живые_строки()


#: живые строки 20.11.2026: что sportklub.hr вёл в базе сервера и что принёс
#: файл серверного сбора mojtv.hr (замер перед правкой: 9 игр файла заливка
#: по именам не нашла). Сутки: 1 — 20.11, 2 — 21.11, 3 — 22.11
СВОЙ_САЙТ = [
    (1, "15:00", "Sport Klub 2", "T", "Alcaraz", "Cobolli"),
    (2, "15:00", "Sport Klub 4", "F", "GALATASARAY", "SAMSUNSPOR"),
    (2, "18:00", "Sport Klub 3", "F", "KOCAELISPOR", "FENERBAHÇE"),
    (2, "22:30", "Sport Klub 3", "F", "VITÓRIA SC", "SC BRAGA"),
    (3, "12:00", "Sport Klub 1", "B", "Cayirova", "Erokspor"),
    (3, "14:30", "Sport Klub 5", "F", "FC Kaiserslautern", "Dynamo Drezno"),
    (3, "15:00", "Sport Klub 4", "F", "Konyaspor", "Beşiktaş"),
    (3, "18:00", "Sport Klub 4", "F", "TRABZONSPOR", "EYUPSPOR"),
]
MOJTV = [
    (1, "02:00", "Sport Klub 1", "B", "San Antonio", "LA Clippers"),          # своего показа нет
    (1, "12:30", "Sport Klub 2", "T", "Harrison/Skupski", "Granollers/Zeballos"),  # свой — через 150 мин
    (2, "15:00", "Sport Klub 4", "F", "Galatasaray", "Samsun"),
    (2, "18:00", "Sport Klub 3", "F", "Kocaeli", "Fenerbahce"),
    (2, "22:30", "Sport Klub 3", "F", "Guimaraes", "Braga"),
    (3, "12:00", "Sport Klub 1", "B", "Cayirova", "Erok"),
    (3, "14:30", "Sport Klub 5", "F", "Kaiserslautern", "Dynamo Dresden"),
    (3, "15:00", "Sport Klub 4", "F", "Konya", "Besiktas"),
    (3, "18:00", "Sport Klub 4", "F", "Trabzon", "Eyup"),
]


def живые_строки() -> None:
    print("Правило 5 на живых строках 20.11.2026 (sportklub.hr и mojtv.hr)")
    conn = база()
    когда = ЧАСЫ.strftime("%Y-%m-%d %H:%M")
    номера = {"Sport Klub 1": 51}
    for i, имя in enumerate(("Sport Klub 2", "Sport Klub 3", "Sport Klub 4", "Sport Klub 5")):
        номера[имя] = 60 + i
        conn.execute("INSERT INTO channels (id, canonical_name, slug, country) "
                     "VALUES (?, ?, ?, 'HR')", (60 + i, имя, f"sk-{i}-hr"))
    for имя, номер in номера.items():
        conn.execute("INSERT INTO channel_aliases (channel_id, alias, source_id) "
                     "VALUES (?, ?, 1)", (номер, имя))
    for сутки, время, канал, вид, дом, гости in СВОЙ_САЙТ:
        cur = conn.execute(
            "INSERT INTO events (sport, league_auto, team_home_auto, team_away_auto, "
            "start_utc, start_kyiv, last_seen) VALUES (?, '', ?, ?, ?, ?, ?)",
            (вид, дом, гости, f"{день(сутки)} {время}", f"{день(сутки)} {время}", когда))
        conn.execute("INSERT INTO event_channels (event_id, channel_id, source_id, "
                     "source_url, raw_title, last_seen, miss_count) "
                     "VALUES (?, ?, 1, '', '', ?, 0)", (cur.lastrowid, номера[канал], когда))
    conn.commit()
    файл = [{"sport": вид, "league": "", "home": дом, "away": гости,
             "start_kyiv": f"{день(сутки)}T{время}", "start_utc": f"{день(сутки)}T{время}",
             "entries": [{"source": "mojtv.hr", "channel": канал, "url": "",
                          "raw_title": f"{дом} - {гости}"}]}
            for сутки, время, канал, вид, дом, гости in MOJTV]
    store.save_games(conn, файл, now=ЧАСЫ)
    от_агрегатора = sorted(
        (r["team_home_auto"], r["team_away_auto"]) for r in conn.execute(
            "SELECT DISTINCT e.team_home_auto, e.team_away_auto FROM events e "
            "JOIN event_channels ec ON ec.event_id = e.id WHERE ec.source_id = 2"))
    проверка("семь игр, которые свой сайт ведёт на том же канале в ту же минуту, "
             "вторыми не заведены; две без своего показа рядом — заведены",
             от_агрегатора, [("Harrison/Skupski", "Granollers/Zeballos"),
                             ("San Antonio", "LA Clippers")])
    проверка("игр в базе: восемь своего сайта и две от агрегатора",
             conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 10)
    проверка("имена своего сайта не тронуты",
             conn.execute("SELECT team_home_auto || ' — ' || team_away_auto FROM events e "
                          "JOIN event_channels ec ON ec.event_id = e.id WHERE ec.channel_id = ? "
                          "AND e.start_kyiv = ?", (номера["Sport Klub 4"], f"{день(3)} 18:00")
                          ).fetchone()[0], "TRABZONSPOR — EYUPSPOR")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("Правило «свой сайт канала важнее агрегатора»")

    conn = база()
    проверка("официальным помечен один источник",
             sorted(channel_owner.официальные(conn).values()), ["sportklub.hr"])

    # глубина своего сайта в этом сборе: 08 и 09 октября
    х = channel_owner.Хозяева(conn)
    х.учесть(1, 51, "2026-10-08")
    х.учесть(1, 51, "2026-10-09")
    проверка("правило 1: строка своего сайта — берём", х.почему(1, 51, "2026-10-09"), 1)
    проверка("правило 2: у канала нет своего сайта — берём",
             х.почему(2, 52, "2026-10-08"), 2)
    проверка("правило 3: день в глубине своего сайта — не берём",
             х.почему(2, 51, "2026-10-09"), 3)
    проверка("правило 3: и более близкий день тоже не берём",
             х.почему(2, 51, "2026-10-07"), 3)
    проверка("правило 4: день дальше глубины — берём",
             х.почему(2, 51, "2026-10-10"), 4)
    проверка("пропустить считает строки", (х.пропустить(2, 51, "2026-10-09", "mojtv.hr"),
                                           х.пропустить(2, 51, "2026-10-10", "mojtv.hr"),
                                           х.пропущено),
             (True, False, {"mojtv.hr": 1}))
    проверка("в отчёте видно сайт", "mojtv.hr: 1" in х.отчёт(), True)

    # свой сайт в сборе молчит целиком — агрегатор берём весь
    пусто = channel_owner.Хозяева(conn)
    проверка("свой сайт не дал ничего — агрегатор берём",
             пусто.почему(2, 51, "2026-10-09"), 2)
    проверка("без официальных источников отчёт пуст", пусто.отчёт(), "")

    # глубина по БАЗЕ: сбор без своего сайта вовсе (так сервер качает mojtv)
    сейчас = datetime(2026, 10, 7, 9, 0)
    conn3 = база()
    прошлый_сбор(conn3, "2026-10-09", "2026-10-07 08:15")
    из_базы = channel_owner.Хозяева(conn3, сейчас)
    проверка("база: канал признан своим у официального сайта",
             из_базы.хозяин.get(51), {1})
    проверка("база: глубина взята из отметок",
             из_базы.глубина.get(1), "2026-10-09")
    проверка("база: день в глубине — строку агрегатора не берём",
             из_базы.почему(2, 51, "2026-10-08"), 3)
    проверка("база: дальний день — берём", из_базы.почему(2, 51, "2026-10-10"), 4)

    conn4 = база()
    прошлый_сбор(conn4, "2026-10-09", "2026-10-05 08:15")      # старше 30 ч
    старое = channel_owner.Хозяева(conn4, сейчас)
    проверка("база: устаревшую отметку за глубину не считаем",
             старое.глубина.get(1), None)
    проверка("база: тогда строку агрегатора берём",
             старое.почему(2, 51, "2026-10-08"), 4)

    # сквозная заливка: «сегодня» (день(0)) есть у своего сайта, +3 дня — только у mojtv
    conn2 = база()
    stats = store.save_games(conn2, [
        игра(день(0), [("sportklub.hr", "Sport Klub 1"),
                            ("mojtv.hr", "Sport Klub 1"),
                            ("mojtv.hr", "MAX Sport 1")]),
        игра(день(3), [("mojtv.hr", "Sport Klub 1")]),
    ], now=ЧАСЫ)
    отметки = {(r["domain"], r["canonical_name"], r["start_kyiv"][:10])
               for r in conn2.execute(
                   "SELECT s.domain, c.canonical_name, e.start_kyiv "
                   "FROM event_channels ec JOIN sources s ON s.id = ec.source_id "
                   "JOIN channels c ON c.id = ec.channel_id "
                   "JOIN events e ON e.id = ec.event_id")}
    проверка("заливка: свой сайт записан",
             ("sportklub.hr", "Sport Klub 1", день(0)) in отметки, True)
    проверка("заливка: агрегатор по этому каналу и дню НЕ записан",
             ("mojtv.hr", "Sport Klub 1", день(0)) in отметки, False)
    проверка("заливка: чужой канал агрегатора записан",
             ("mojtv.hr", "MAX Sport 1", день(0)) in отметки, True)
    проверка("заливка: дальний день агрегатора записан",
             ("mojtv.hr", "Sport Klub 1", день(3)) in отметки, True)
    проверка("заливка: счётчик непринятых строк", stats.not_own, 1)

    # прежняя отметка агрегатора снимается: иначе висела бы вечно — гашение
    # её не возьмёт (у сайта «пропала» разом вся линейка, правило 6 miss.py)
    # у игры есть и чужой канал агрегатора — значит пустой она не останется
    conn5 = база()
    строки5 = [("mojtv.hr", "Sport Klub 1"), ("mojtv.hr", "MAX Sport 1")]
    без_правила = store.save_games(conn5, [игра(день(0), строки5)],
                                   now=ЧАСЫ)
    conn5.execute("UPDATE sources SET selector_config = ? WHERE id = 1",
                  (json.dumps({channel_owner.ФЛАГ: True}),))
    conn5.commit()
    прошлый_сбор(conn5, день(1), datetime.now().strftime("%Y-%m-%d %H:%M"))
    с_правилом = store.save_games(conn5, [игра(день(0), строки5)],
                                  now=ЧАСЫ)
    осталось = {r["canonical_name"] for r in conn5.execute(
        "SELECT c.canonical_name FROM event_channels ec "
        "JOIN channels c ON c.id = ec.channel_id "
        "JOIN sources s ON s.id = ec.source_id JOIN events e "
        "ON e.id = ec.event_id WHERE s.domain = 'mojtv.hr' "
        f"AND e.start_kyiv LIKE '{день(0)}%'")}
    проверка("прежняя отметка агрегатора снята",
             (без_правила.not_own, с_правилом.not_own_dropped, осталось),
             (0, 1, {"MAX Sport 1"}))
    проверка("в отчёте видно, сколько снято",
             "снято прежних отметок: 1" in с_правилом.not_own_note, True)

    # у игры только строка агрегатора и других каналов нет — берём её:
    # пустая запись на витрине хуже канала с агрегатора
    conn6 = база()
    прошлый_сбор(conn6, день(1), datetime.now().strftime("%Y-%m-%d %H:%M"))
    один = store.save_games(conn6, [
        игра(день(0), [("mojtv.hr", "Sport Klub 1")])], now=ЧАСЫ)
    есть = conn6.execute(
        "SELECT COUNT(*) FROM event_channels ec JOIN sources s "
        "ON s.id = ec.source_id JOIN events e ON e.id = ec.event_id "
        f"WHERE s.domain = 'mojtv.hr' AND e.start_kyiv LIKE '{день(0)}%'"
    ).fetchone()[0]
    проверка("единственную строку игры правило не отбирает",
             (один.not_own, есть), (0, 1))

    # а когда у той же игры есть и свой канал — строку агрегатора не берём
    conn7 = база()
    прошлый_сбор(conn7, день(1), datetime.now().strftime("%Y-%m-%d %H:%M"))
    пара = store.save_games(conn7, [
        игра(день(0), [("sportklub.hr", "Sport Klub 1"),
                            ("mojtv.hr", "Sport Klub 1")])], now=ЧАСЫ)
    проверка("рядом со своим каналом строка агрегатора не берётся",
             пара.not_own, 1)

    # хвосты: отметки агрегатора, которых в файле уже нет, за дни в глубине
    # хозяина снимаются; за дни дальше — остаются; единственный канал игры —
    # остаётся
    conn8 = база()
    # хвосты рождаются ДО того, как у канала появился хозяин: сначала
    # заливка без отметки official, потом она ставится
    conn8.execute("UPDATE sources SET selector_config = NULL WHERE id = 1")
    conn8.commit()
    store.save_games(conn8, [
        игра(день(0), [("mojtv.hr", "Sport Klub 1"),
                            ("mojtv.hr", "MAX Sport 1")]),   # хвост с соседом
        игра(день(4), [("mojtv.hr", "Sport Klub 1"),
                            ("mojtv.hr", "MAX Sport 1")]),   # дальше глубины
    ], now=ЧАСЫ)
    conn8.execute("UPDATE sources SET selector_config = ? WHERE id = 1",
                  (json.dumps({channel_owner.ФЛАГ: True}),))
    conn8.commit()
    прошлый_сбор(conn8, день(1), datetime.now().strftime("%Y-%m-%d %H:%M"))
    хвосты = store.save_games(conn8, [
        игра(день(2), [("mojtv.hr", "Sport Klub 1")])], now=ЧАСЫ)  # одиночка
    остались = sorted((r["start_kyiv"][:10], r["canonical_name"]) for r in conn8.execute(
        "SELECT e.start_kyiv, c.canonical_name FROM event_channels ec "
        "JOIN channels c ON c.id = ec.channel_id JOIN sources s "
        "ON s.id = ec.source_id JOIN events e ON e.id = ec.event_id "
        "WHERE s.domain = 'mojtv.hr' AND ec.miss_count = 0"))
    проверка("хвост в глубине снят, дальний и одиночка остались",
             остались, [(день(0), "MAX Sport 1"),
                        (день(2), "Sport Klub 1"),
                        (день(4), "MAX Sport 1"),
                        (день(4), "Sport Klub 1")])
    проверка("снятый хвост посчитан", хвосты.not_own_dropped, 1)
    проверка("заливка: строка для журнала есть",
             "mojtv.hr: 1" in stats.not_own_note, True)

    правило_пять()

    print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, "
          f"красных: {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    raise SystemExit(main())

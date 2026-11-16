# -*- coding: utf-8 -*-
r"""Книги 163–165 (16.11.2026, слово владельца: «почему отложено, а не сделано?»).

  163. слово повтора, обзора, жеребьёвки или студии в ЗАГОЛОВКЕ трансляции
       турнира — не эфир (`broadcast.not_live_title`, раздел
       `tournament_not_live` в `data/markers.json`; `pipeline.tournament_whole`,
       Т1): у сайта без пометки эфира показ в минуту матча шёл бы трансляцией;
  164. к стороне пары прилипла известная лига («Häcken - Manchester C UEFA
       Women's Champions League», dagenstv.com) — `pipeline.league_off_sides`,
       Л1–Л5;
  165. командная теннисная встреча, которую эталон ставит на соседний день
       (sport5.co.il: Japan — Argentina 21.11, у эталона 22.11): лига и пометка
       W — из эталона (`parse_live.next_tie_games`, правило 4), игра в базе
       получает имя с пометкой (`names.only_marks_added`, `store.save_games`).
В сеть не ходит, база временная. Запуск: python scripts/test_ostatok_16_11.py
"""
from __future__ import annotations

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
TMP = Path(tempfile.mkdtemp(prefix="ostatok-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import broadcast, db, live, names, pipeline, site_lang, sport, store  # noqa: E402
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


M, ВИДЫ = live.load(), sport.load()
ТУРИН = "ATP - SINGLES: Finals - Turin (World), hard (indoor)"
ЭТАЛОН = [{"sport": "T", "home": "Alcaraz C.", "away": "Tiafoe F.", "league": ТУРИН, "fs_id": "t1",
           "start_kyiv": "2026-11-16T12:30"}]
судья = Reference(ЭТАЛОН)

# ── книга 163 ────────────────────────────────────────────────────────────────
print("163. Заголовок трансляции турнира — не эфир (`broadcast.not_live_title`)")


def турнир(title: str, marker: str = "", guess_site: bool = True, domain: str = "movistarplus.es"):
    program = Program(channel_raw="M+ Deportes 2", title=title, start=когда("2026-11-16T12:30"), live_raw=marker)
    row = pipeline.classify(program, M, ВИДЫ, reference=судья, langs=site_lang.of(domain), guess_site=guess_site)
    return row.ok


проверка("сайт без пометки эфира: трансляция турнира в минуту матча проходит, как раньше",
         [турнир("Nitto ATP Finals 2026 (T2026): TBC"), турнир("Tenis ATP Torino 2026", domain="ipko.tv")], [True, True])
проверка("повтор, обзор дня, жеребьёвка и студия в заголовке — не эфир, хоть и начались в минуту матча",
         [турнир(t) for t in ("Nitto ATP Finals 2026: Redifusión", "Sorteo Nitto ATP Finals 2026",
                              "Lo mejor del día. Nitto ATP Finals 2026", "La pista del Tenis. Nitto ATP Finals (T2026): TBC",
                              "Tennis: ATP Finals Torino - Sintesi", "ATP Finals 2026: Auslosung",
                              "ATP Finals Turin: Samenvatting", "Tenis ATP Finals: Tekrar", "Теннис. ATP. Итоговый турнир. Обзор")],
         [False] * 9)
проверка("то же — у сайта, который пометил строку эфиром сам (слово записи сильнее значка)",
         [турнир("Nitto ATP Finals 2026: Redifusión", marker="directo", guess_site=False),
          турнир("Nitto ATP Finals 2026", marker="directo", guess_site=False)], [False, True])
проверка("слово ищется на языках сайтов: по одному на язык",
         [bool(broadcast.not_live_title(t)) for t in (
             "ATP Finals: reposição", "ATP Finals - reluare", "ATP Finals powtórka", "ATP Finals (opakování)",
             "ATP Finals ismétlés", "ATP Finals: Επανάληψη", "ATP Finals: שידור חוזר", "ATP Finals përsëritje",
             "ATP Finals: uusinta", "ATP Finals: tirage au sort", "ATP Finals: losowanie", "ATP Finals: κλήρωση",
             "ATP Finals: жеребьёвка", "ATP Finals: höjdpunkter", "ATP Finals: sestřih", "ATP Finals: összefoglaló")],
         [True] * 16)
проверка("двусмысленные слова не трогаем: сетка «Main Draw», формат «best of three», обычные названия",
         [broadcast.not_live_title(t) for t in ("ATP 500 Tokyo: Main Draw", "ATP Finals: best of three", "Nitto ATP Finals",
                                                "ATP FINALS 2026 - MEIA-FINAL", "Tenis: Turniej ATP Finals w Turynie")],
         [""] * 5)

# ── книга 164 ────────────────────────────────────────────────────────────────
print("164. К стороне пары прилипла лига (`pipeline.league_off_sides`)")
ЛИГИ = {"uefa women's champions league": "F", "nba herrar": "B", "salzburg": "F", "costa rica": "F",
        "champions league": "F", "serie a": "F"}
срез = pipeline.league_off_sides
проверка("Л1–Л2: лига из словаря на внешнем краю — в конце гостей и в начале хозяев",
         [срез("Häcken", "Manchester C UEFA Women's Champions League", ЛИГИ),
          срез("NBA herrar Philadelphia 76ers", "Milwaukee Bucks", ЛИГИ)],
         [("Häcken", "Manchester C"), ("Philadelphia 76ers", "Milwaukee Bucks")])
проверка("Л2: лига самой строки, которой нет в словаре, — тоже лига; типографский апостроф — тот же",
         [срез("Liga Kobiet Wisła", "Legia", {}, own_league="Liga Kobiet"),
          срез("Häcken", "Manchester C UEFA Women’s Champions League", ЛИГИ)],
         [("Wisła", "Legia"), ("Häcken", "Manchester C")])
проверка("Л2: одно слово не режем — лига-город и клуб зовутся одинаково",
         срез("Rapid Wien", "Red Bull Salzburg", ЛИГИ), ("Rapid Wien", "Red Bull Salzburg"))
проверка("Л3: страна на краю — не лига", срез("Saprissa", "Deportivo Costa Rica", ЛИГИ), ("Saprissa", "Deportivo Costa Rica"))
проверка("Л1: лига внутри пары (в конце хозяев, в начале гостей) — не трогаем",
         срез("Arsenal Champions League", "Champions League Bayern", ЛИГИ), ("Arsenal Champions League", "Champions League Bayern"))
проверка("Л4: от стороны должно остаться имя — сторона, целиком равная лиге, не режется",
         срез("Serie A", "Champions League", ЛИГИ), ("Serie A", "Champions League"))
проверка("Л5: из двух подходящих цепочек — самая длинная («UEFA Women's Champions League», а не «Champions League»)",
         срез("Häcken", "Manchester C UEFA Women's Champions League", ЛИГИ)[1], "Manchester C")
p = Program(channel_raw="TV12", title="Häcken - Manchester C UEFA Women's Champions League",
            match_raw="Häcken - Manchester C UEFA Women's Champions League",
            league_raw="Häcken - Manchester C UEFA Women's Champions League", start=когда("2026-11-18T18:40"), live_raw="direkt")
row = pipeline.classify(p, M, ВИДЫ, league_sports=ЛИГИ, reference=судья, langs=site_lang.of("dagenstv.com"))
проверка("строка dagenstv.com целиком: пара чистая, лига — «UEFA Women's Champions League», женская метка на месте",
         (row.ok, row.home, row.away, row.league), (True, "Häcken W", "Manchester C W", "UEFA Women's Champions League"))

# ── книга 165 ────────────────────────────────────────────────────────────────
print("165. Командная встреча, которую эталон ставит на соседний день")
БДК = "TEAMS - WOMEN: Billie Jean King Cup - World Group (World) - Relegation - Play Offs"
ВСТРЕЧИ = [{"sport": "T", "home": "Japan W", "away": "Argentina W", "league": БДК, "fs_id": "jp-ar",
            "start_kyiv": "2026-11-22T05:00"},
           {"sport": "T", "home": "Czechia", "away": "Canada", "league": "TEAMS - MEN: Davis Cup - World Group",
            "fs_id": "cz-ca", "start_kyiv": "2026-11-24T17:00"}]


def показ(start: str, home: str, away: str, домен: str = "sport5.co.il"):
    program = site_says(Program(channel_raw="ספורט 5", title=f"{home} - {away}", start=когда(start), live_raw="ישיר"), True)
    return домен, pipeline.Row(program=program, ok=True, live_marker="ישיר", home=home, away=away, sport="T",
                               league="גביע בילי ג'ין", start_kyiv=когда(start), start_utc=когда(start))


найдено = [показ("2026-11-21T04:00", "יפן", "ארגנטינה"), показ("2026-11-24T17:00", "Czechy", "Kanada", "teleman.pl")]
parse_live.next_tie_games(найдено, ВСТРЕЧИ)
проверка("правило 4: встреча узнана со сдвигом на сутки — пара остаётся, лига и W берутся из эталона",
         (найдено[0][1].home, найдено[0][1].away, найдено[0][1].league), ("יפן W", "ארגנטינה W", БДК))
проверка("у мужской встречи пометок нет — имена как были, лига эталона",
         (найдено[1][1].home, найдено[1][1].away, найдено[1][1].league),
         ("Czechy", "Kanada", "TEAMS - MEN: Davis Cup - World Group"))
проверка("новое имя — старое плюс пометка пола или возраста",
         [names.only_marks_added("Thailand", "Thailand W"), names.only_marks_added("Serbia", "Serbia U19"),
          names.only_marks_added("יפן", "יפן W"), names.only_marks_added("Thailand", "Thailand"),
          names.only_marks_added("Thailand W", "Thailand"), names.only_marks_added("Austria", "Australia W"),
          names.only_marks_added("", "Thailand W")],
         [True, True, True, False, False, False, False])

ДЕНЬ = (date.today() + timedelta(days=1)).isoformat()
ЧАСЫ = datetime.combine(date.today(), datetime.min.time()).replace(hour=12)
db.init_db()
conn = db.connect()
conn.execute("INSERT INTO sources (id, domain, name, base_url, country, enabled) VALUES (1, 'srf.ch', 'SRF', 'https://srf.ch/', 'XX', 1)")
conn.commit()


def игра(home, away):
    return {"sport": "T", "league": БДК, "home": home, "away": away, "start_kyiv": f"{ДЕНЬ}T07:00",
            "start_utc": f"{ДЕНЬ}T05:00",
            "entries": [{"source": "srf.ch", "channel": "SRF zwei", "url": "", "raw_title": "Thailand – Schweiz"}]}


store.save_games(conn, [игра("Thailand", "Schweiz")], now=ЧАСЫ)
store.save_games(conn, [игра("Thailand W", "Schweiz W")], now=ЧАСЫ, punish=False)
проверка("база: та же игра получает имена с пометкой, второй строки не появляется",
         [tuple(r) for r in conn.execute("SELECT team_home_auto, team_away_auto FROM events")], [("Thailand W", "Schweiz W")])
store.save_games(conn, [игра("Thailand", "Schweiz")], now=ЧАСЫ, punish=False)
проверка("обратно пометка не снимается: W у женских команд не теряем",
         [tuple(r) for r in conn.execute("SELECT team_home_auto, team_away_auto FROM events")], [("Thailand W", "Schweiz W")])
conn.close()

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

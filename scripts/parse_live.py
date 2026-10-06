# -*- coding: utf-8 -*-
r"""Разобрать страницы, скачанные живым обходом, и показать матчи.

Работает по тому, что оставил `crawl_fetch.py`: папка со страницами и
`report.json` рядом. К сайтам не обращается — только читает файлы, поэтому
запускать можно сколько угодно и где угодно.

Смысл в том, чтобы обход возвращал не «62 файла», а прямой ответ: столько-то
матчей, вот они, вот на каких каналах. Тогда по одному артефакту с GitHub
видно, годится площадка или нет.

Запуск:
    python scripts/parse_live.py
    python scripts/parse_live.py --dir recon/raw_live --md recon/raw_live/matches.md
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import (broadcast, canon, daytime, db, dictionary,  # noqa: E402
                 leagues, live, merge, names, pipeline, sport, store)
from app.parsers import get as parser_for                   # noqa: E402
from app.parsers import flashscore_mobi                     # noqa: E402
from app.parsers.flashscore_mobi import LOCALES as FS_LOCALES  # noqa: E402
from app.reference import Reference                         # noqa: E402

DEFAULT_DIR = ROOT / "recon" / "raw_live"
PLAN = ROOT / "data" / "crawl_plan.json"
#: итог прошлого удачного полного обхода — по нему судим, не просел ли этот
PREVIOUS = ROOT / "results" / "games.json"
#: игр меньше — прогон провальный (аудит 07.09, A4): под `--strict` код 2,
#: результат не коммитится. Порог — не меньше MIN_GAMES и не меньше половины
#: прошлого прогона С ТЕМ ЖЕ ОКНОМ: утро на 6 суток и вечер на 2 суток
#: сравниваются каждый со своим
MIN_GAMES = 100
DROP_SHARE = 0.5

#: сайты без честного флага эфира: их парсеры считают эфиром первый показ
#: пары, но каждый день выгрузки парсится отдельно и соседних дней не видит.
#: Поздний показ той же пары из другого дня снимаем здесь.
REPEAT_GUESS_DOMAINS = {"trtspor.com.tr", "allente.no", "programetv.ro",
                        "oneplaysport.cz", "ert.gr", "rtrs.tv", "ipko.tv",
                        "trt.net.tr", "mediaklikk.hu", "sports.kz",
                        "movistarplus.es", "tv.orf.at",
                        "programme-tv.net", "rtl.de", "bbc.co.uk",
                        "beinsports.com.tr", "raspored.hrt.hr", "tv8.com.tr",
                        "tv.sport1.de", "raiplay.it", "trtavaz.com.tr", "tvpassport.com",
                        # novasports.gr выведен 22.09: (Ζ)/LIVE — честные
                        # пометки эфира и на будущих днях (ручка admin-ajax)
                        "jupiter.err.ee", "tvguidetonight.com.au",
                        # tv2.no: флаг `live` у сайта про «идёт сейчас»,
                        # а не про прямой эфир; atv признака не ставит
                        # вовсе
                        "tv2.no", "atv.com.tr",
                        # vsetv: признака эфира у сайта нет вовсе;
                        # у kolla.tv флаги live и repeat всегда пустые
                        "vsetv.com", "kolla.tv", "dagenstv.com",
                        # РТС признака эфира не ставит вовсе; у ΣΚΑΪ
                        # пометка LIVE — про эфир канала, а не про матч
                        "rts.rs", "skai.gr",
                        # Kanal 1 пишет «Vysielame» всем строкам подряд.
                        # port.hu выведен 06.10: флаги is_live_mp/is_repeat
                        # честные, строки без флагов разбор помечает
                        # live_guess (ветка hu-live — сливать её раньше)
                        "kanal1sport.sk", "webtv.sk",
                        # литовский телегид tv3.lt эфир не помечает
                        "tv3.lt"}


def previous_counts(path: Path = PREVIOUS) -> dict[str, int]:
    """Сколько игр давали прошлые прогоны, по окнам: `{"2": 507, "6": 1300}`.
    Память едет в самом games.json (поле `по_окнам`) — отдельного файла нет."""
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    counts = {str(k): int(v) for k, v in (prev.get("по_окнам") or {}).items()
              if str(v).isdigit()}
    if prev.get("окно") and prev.get("игр"):
        counts[str(prev["окно"])] = int(prev["игр"])
    return counts


def too_few(count: int, days: int, previous: dict[str, int]) -> str:
    """Почему прогон провальный по числу игр; пустая строка — норма."""
    floor, tail = MIN_GAMES, ""
    last = previous.get(str(days), 0)
    if last:
        floor = max(floor, int(last * DROP_SHARE))
        tail = f" (прошлый прогон с окном {days} сут. дал {last})"
    if count < floor:
        return f"::error::игр всего {count} — меньше порога {floor}{tail}"
    return ""


def plan_days(plan_path: Path) -> int:
    if not plan_path.exists():
        return 2
    return json.loads(plan_path.read_text(encoding="utf-8")).get("days", 2)


def source_settings(plan_path: Path) -> dict[str, dict]:
    """Пояс и список нужных каналов по каждому сайту — из плана обхода."""
    if not plan_path.exists():
        return {}
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    return {s["domain"]: {"tz": s.get("timezone"),
                          "include": set(s.get("include") or []),
                          # разбор, одолженный у другого сайта (23.09)
                          "parser": s.get("parser") or ""}
            for s in plan.get("sources", [])}


#: Насколько поздний показ ещё считаем повтором той же игры. Больше суток с
#: запасом — но заметно меньше, чем перерыв между первым и ответным матчем.
LATE_REPEAT = timedelta(hours=30)


#: насколько раньше строки должен был пройти матч, чтобы считать показ
#: повтором. Меньше — это тот же матч в своём окне (студия, разброс сеток)
REPEAT_AFTER = timedelta(hours=4)
#: как далеко в прошлое смотрим: канал крутит запись день-два, дальше уже
#: не повтор, а новый матч тех же команд
REPEAT_DEPTH = timedelta(hours=60)
#: матч эталона в пределах ±3 ч от строки — строка показывает его вживую
#: (тот же допуск, что у сверки угаданного эфира с эталоном)
LIVE_NEAR = timedelta(hours=3)


def add_reference(programs: list, reference: list,
                  reference_full: list | None) -> None:
    """Строки справочника → эталон. `reference` — кортежи (дом, гости,
    киевское время) для сверки футбольного live; `reference_full` — полные
    записи flashscore (с fs_id) для games.json (None — не нужен)."""
    from zoneinfo import ZoneInfo as _Z
    for prg in programs:
        pair = (prg.match_raw or "").strip()
        if " - " not in pair or prg.start is None:
            continue
        home, _, away = pair.partition(" - ")
        begin = prg.start.astimezone(_Z("Europe/Kyiv"))
        # live-подтверждение остаётся футбольным: правила про повторы
        # топ-лиг и порог rich считают только футбол
        if prg.sport_raw in ("Soccer", ""):
            reference.append((home.strip(), away.strip(), begin))
        # полный эталон уезжает в games.json: по нему импорт закрепляет
        # канонические английские имена (app/canon.py); с 6б в нём и
        # баскетбол с теннисом
        if reference_full is not None:
            reference_full.append({
                "sport": {"Basketball": "B",
                          "Tennis": "T"}.get(prg.sport_raw, "F"),
                "home": home.strip(), "away": away.strip(),
                "league": (prg.league_raw or "").strip(),
                "fs_id": (prg.extra or {}).get("fs_id", ""),
                "start_kyiv": begin.strftime("%Y-%m-%dT%H:%M"),
            })


def local_reference(reference_full: list) -> dict:
    """Местные написания пар эталона (поле `names`: `{"hu": [дом, гости]}`)
    для сверки угаданного эфира, по дням: `{дата: [(дом, гости, время,
    письменность, вид спорта)]}`. Написание, совпавшее с английским или с
    уже взятой локалью, не повторяем: проверка идёт на каждую строку."""
    from app.canon import _SCRIPT_OF_LANG
    по_дням: dict = {}
    for rec in reference_full:
        try:
            when = datetime.strptime(rec["start_kyiv"], "%Y-%m-%dT%H:%M") \
                .replace(tzinfo=daytime.KYIV)
        except (KeyError, ValueError):
            continue
        seen = {(rec.get("home") or "", rec.get("away") or "")}
        for lang, pair in (rec.get("names") or {}).items():
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2
                    and pair[0] and pair[1]):
                continue
            home, away = str(pair[0]), str(pair[1])
            if (home, away) in seen:
                continue
            seen.add((home, away))
            по_дням.setdefault(when.date(), []).append(
                (home, away, when, _SCRIPT_OF_LANG.get(lang, "lat"),
                 rec.get("sport") or "F"))
    return по_дням


def in_local_reference(home: str, away: str, start, sport: str,
                       по_дням: dict) -> bool:
    """Пара строки есть среди местных написаний эталона: та же письменность
    (греческое — с греческим, латиница — с латиницей), тот же вид спорта,
    в пределах ±`LIVE_NEAR`, обе команды, в любом порядке."""
    from app.canon import _script
    script = _script(f"{home} {away}")
    день = start.date()
    for д in (день - timedelta(days=1), день, день + timedelta(days=1)):
        for h, a, t, sc, sp in по_дням.get(д, []):
            if sc != script or sp != sport or abs(start - t) > LIVE_NEAR:
                continue
            if (names.same_team(home, h) and names.same_team(away, a)) \
                    or (names.same_team(home, a) and names.same_team(away, h)):
                return True
    return False


def reference_index(reference: list) -> dict:
    """Эталон, разложенный по дням: перебирать 5 тысяч записей на каждую
    строку слишком долго."""
    по_дням: dict = {}
    for r in reference or []:
        try:
            when = datetime.fromisoformat(r.get("start_kyiv") or "")
        except ValueError:
            continue
        по_дням.setdefault(when.date(), []).append((r, when))
    return по_дням


def played_before(home: str, away: str, league: str, start,
                  индекс: dict) -> dict | None:
    """Запись эталона, повтором которой является показ, или None.

    Правила по порядку:

    1. Соперник ещё не назван («Francia — TBC») — судить не по чему: по
       одной стороне легко принять показ за повтор прошлого матча команды.
    2. Та же пара есть в эталоне в пределах ±`LIVE_NEAR` от строки — строка
       показывает этот матч вживую, это не повтор, даже если та же пара
       встречалась и раньше (сбор #205: эталон держал Instituto — Boca
       Juniors и 09.10, и 10.10, и живой эфир 10.10 снимался «записью»).
    3. Та же пара в эталоне раньше строки на `REPEAT_AFTER`…`REPEAT_DEPTH`
       (4–60 ч) — матч уже сыгран, показ — повтор. Меньше четырёх часов —
       тот же матч в своём окне (студия, разброс сеток), больше шестидесяти
       — уже новая встреча тех же команд.
    """
    if not индекс or not start:
        return None
    if names.is_placeholder(home) or names.is_placeholder(away):
        return None                                          # правило 1
    # эталон лежит в наивном киевском времени, а время строки — со смещением;
    # сравнивать их напрямую нельзя (обход 11.09 упал именно на этом)
    start = start.replace(tzinfo=None)
    день = start.date()

    def same_pair(r) -> bool:
        пара = {"home": home, "away": away, "league": league,
                "sport": r.get("sport", "F")}
        return canon._pair_score(пара, r) >= names.SIMILAR_ENOUGH

    for д in (день - timedelta(days=1), день, день + timedelta(days=1)):
        for r, when in индекс.get(д, []):
            if abs(start - when) <= LIVE_NEAR and same_pair(r):
                return None                                  # правило 2
    for д in (день, день - timedelta(days=1), день - timedelta(days=2)):
        for r, when in индекс.get(д, []):
            if REPEAT_AFTER < start - when <= REPEAT_DEPTH and same_pair(r):
                return r                                     # правило 3
    return None


def already_played(home: str, away: str, start, индекс: dict) -> bool:
    """Этот матч уже сыгран — значит показ является повтором
    (правила — `played_before`)."""
    return played_before(home, away, "", start, индекс) is not None


def drop_reference_repeats(games: list, reference: list) -> tuple[list, list]:
    """Снять показы матчей, которые УЖЕ сыграны.

    Канал крутит запись: `Fenerbahçe - AS Řím` стоит в сетке 11.09 в 10:00,
    а сам матч по flashscore был 10.09 в 19:45. Это не расписание, а повтор
    — на витрину он не идёт (разбор владельца 10.09: из 485 нерешённых строк
    67 оказались именно такими, в основном oneplaysport.cz и beIN).

    Матч эталона ПОЗЖЕ строки не трогаем: это либо анонс будущей игры, либо
    расхождение дат у сайта — другой случай, отдельный разбор. Правила —
    `played_before`. Возвращает (оставленные игры, [(снятая игра, запись
    эталона)]) — снятое уходит в журнал поимённо.
    """
    if not reference:
        return games, []
    # индекс по дню: перебирать 5 тысяч записей на каждую игру слишком долго
    по_дням = reference_index(reference)
    оставили, снятые = [], []
    for g in games:
        матч = played_before(g.home, g.away, g.first.league or "", g.start,
                             по_дням)
        if матч is None:
            оставили.append(g)
        else:
            снятые.append((g, матч))
    return оставили, снятые


def drop_late_repeats(games: list) -> tuple[list, list]:
    """Убрать поздние повторы, которые видно только по соседнему сайту.

    Сайт без честного флага эфира помечает эфиром свой самый ранний показ
    пары. Но матч мог пройти ещё раньше — и это видно по другому источнику:
    01.09 `Barcelona - Rayo Vallecano` попал в ленту четыре раза (00:30,
    05:00, 09:45, 13:00), хотя игра была накануне вечером.

    Поэтому уже после склейки смотрим: если та же пара с тем же видом спорта
    была раньше (в пределах 30 часов, чтобы не снести ответный матч через
    неделю), а поздняя запись целиком собрана из «угаданных» источников —
    это повтор, в ленту он не идёт.

    Возвращает (оставленные, [(снятая игра, та же пара раньше)]).
    """
    kept: list = []
    removed: list = []
    for game in sorted(games, key=lambda g: g.start):
        guessed_only = all(guessed(e.source, e.payload) for e in game.entries)
        # две сессии одного турнира в день — не повтор: у сведённой
        # трансляции («ATP Beijing») имя одно на весь турнир (04.10)
        if game.first.away == broadcast.SESSION:
            kept.append(game)
            continue
        earlier = next((e for e in kept if _looks_repeat(e, game)), None) \
            if guessed_only else None
        if earlier is not None:
            removed.append((game, earlier))
            continue
        kept.append(game)
    return kept, removed


def unique_rows(found: list) -> tuple[list, int]:
    """Строки без копий: одна передача сайта — (домен, канал, начало,
    заголовок) — одна строка, сколько бы его страниц её ни показали.

    Копии бывают законные: страницы дней перекрываются (dr.dk: передача
    01:50 есть и на странице 09.10, и на 10.10), а адрес `/schedule` у
    diemaxtra — копия Diema Sport (самопроверка #205, 06.10). Без этого у
    игры было два одинаковых канала. Возвращает (строки, сколько убрано)."""
    seen: set = set()
    out: list = []
    for domain, r in found:
        key = ((domain or "").removeprefix("www."), r.program.channel_raw,
               r.start_kyiv, r.program.title)
        if key in seen:
            continue
        seen.add(key)
        out.append((domain, r))
    return out, len(found) - len(out)


#: имена фильтров повторов в журнале снятого (ключ «снято» в games.json)
СНЯТО_ОЧЕРЕДЬ = "очередь: матч уже сыгран"
СНЯТО_ПОЗДНИЙ_ПОКАЗ = "поздний показ у сайта без флага"
СНЯТО_НЕТ_В_ЭТАЛОНЕ = "угаданный эфир без эталона"
СНЯТО_НЕТ_В_ЭТАЛОНЕ_БТ = "угаданный эфир без эталона (баскет/теннис)"
СНЯТО_ГРЯЗНЫЕ_МИНУТЫ = "угаданный эфир не на ровной минуте"
СНЯТО_СЫГРАН = "повтор по flashscore: матч уже сыгран"
СНЯТО_ПОЗДНИЙ_ПОВТОР = "поздний повтор: пара была раньше у другого сайта"


def removed_row(фильтр: str, domain: str, r, почему: str) -> dict:
    """Строка, снятая фильтром повторов, — поимённо для журнала разбора
    (принцип владельца «ничто не теряется молча»). `r` — строка отсева
    (`.program`, `.start_kyiv`)."""
    program = getattr(r, "program", None)
    when = getattr(r, "start_kyiv", None)
    return {"фильтр": фильтр, "домен": domain,
            "канал": getattr(program, "channel_raw", "") or "",
            "заголовок": (getattr(program, "title", "") or "")[:200],
            "start_kyiv": when.strftime("%Y-%m-%dT%H:%M") if when else "",
            "почему": почему}


def sift(rows: list, keep, снято: list, фильтр: str, почему: str) -> list:
    """Оставить строки `(сайт, строка)`, для которых `keep(сайт, строка)`
    истинно; остальные записать в `снято` поимённо."""
    kept = []
    for domain, r in rows:
        if keep(domain, r):
            kept.append((domain, r))
        else:
            снято.append(removed_row(фильтр, domain, r, почему))
    return kept


def _ref_text(r: dict) -> str:
    """Запись эталона одной строкой: «Instituto - Boca Juniors 09.10 01:30
    (fs_id Cv4icMr4)»."""
    try:
        when = datetime.fromisoformat(r.get("start_kyiv") or "").strftime("%d.%m %H:%M")
    except ValueError:
        when = r.get("start_kyiv") or "?"
    return (f"{r.get('home', '')} - {r.get('away', '')} {when} "
            f"(fs_id {r.get('fs_id') or '—'})")


def _bare_domain(domain: str) -> str:
    return (domain or "").removeprefix("www.")


def guessed(domain: str, result) -> bool:
    """Эфир у строки угадан, а не помечен сайтом: у всего сайта честного
    флага нет (`REPEAT_GUESS_DOMAINS`) или разбор пометил угаданной именно
    эту строку (`extra["live_guess"]`) — у digisport.ro флаг есть, но не у
    всех строк (06.10). Угаданный эфир сверяется с эталоном и чистится от
    повторов; помеченный честно — нет.

    Порядок правил (06.10, аудит меток эфира, ветка live-flags):
    1. Сайт сам пометил строку эфиром или повтором (`extra["site_flag"]`,
       ставит `parsers.site_says`) — не угадана, даже если весь сайт в
       `REPEAT_GUESS_DOMAINS`: часть строк сайта честная, часть нет.
    2. Разбор пометил строку угаданной (`extra["live_guess"]`) — угадана.
    3. Сайт целиком в `REPEAT_GUESS_DOMAINS` — угадана."""
    program = getattr(result, "program", None)
    extra = getattr(program, "extra", None) or {}
    if extra.get("site_flag"):
        return False
    return bool(extra.get("live_guess")) \
        or _bare_domain(domain) in REPEAT_GUESS_DOMAINS


def _looks_repeat(earlier, later) -> bool:
    """Та же игра, показанная позже: пара совпала, а разрыв больше окна
    склейки, но меньше 30 часов."""
    gap = later.start - earlier.start
    if not (timedelta(minutes=merge.WINDOW_MINUTES) < gap <= LATE_REPEAT):
        return False
    a, b = earlier.first, later.first
    if a.sport and b.sport and a.sport != b.sport:
        return False
    direct = min(names.similarity(a.home, b.home),
                 names.similarity(a.away, b.away))
    swapped = min(names.similarity(a.home, b.away),
                  names.similarity(a.away, b.home))
    return max(direct, swapped) >= names.SIMILAR_ENOUGH


def ref_sport_of(r, reference_full: list, floor: int | None = None) -> str:
    """Вид спорта по эталону flashscore для строки: пара сошлась (с местными
    написаниями, ≥ `floor`, по умолчанию SIMILAR_ENOUGH) в ±3 ч. Пусто —
    эталон пару не знает."""
    floor = names.SIMILAR_ENOUGH if floor is None else floor
    ours = r.start_kyiv.replace(tzinfo=None)
    for ref in reference_full:
        if not ref.get("start_kyiv"):
            continue
        try:
            ref_start = datetime.fromisoformat(ref["start_kyiv"])
        except ValueError:
            continue
        if abs((ours - ref_start).total_seconds()) > 3 * 3600:
            continue
        if canon._pair_score({"home": r.home, "away": r.away}, ref) >= floor:
            return ref.get("sport", "F")
    return ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--plan", default=str(PLAN))
    ap.add_argument("--md", default="", help="куда записать отчёт для человека")
    ap.add_argument("--days", type=int, default=0,
                    help="окно в сутках; 0 — взять из плана обхода")
    ap.add_argument("--date", default="",
                    help="скан одной даты ГГГГ-ММ-ДД: в отчёт идут только "
                         "игры этого дня (календарь владельца, 05.09)")
    ap.add_argument("--all", action="store_true",
                    help="показать всё, что отдали сайты, а не только окно")
    ap.add_argument("--strict", action="store_true",
                    help="код 2, если игр подозрительно мало — для полного "
                         "обхода без фильтров (MIN_GAMES, DROP_SHARE)")
    args = ap.parse_args()

    folder = Path(args.dir)
    report = folder / "report.json"
    if not report.exists():
        print(f"нет {report} — сначала обход (scripts/crawl_fetch.py)")
        return 1

    settings = source_settings(Path(args.plan))
    markers, sports = live.load(), sport.load()

    # Подтверждённые владельцем имена — если база под рукой. В GitHub Actions
    # её нет (`data/*.db` не уезжает в git), и это не беда: там работает
    # словарь слов `data/aliases.json`, он в репозитории есть.
    league_canon: dict[str, str] = {}
    try:
        conn = db.connect()
        try:
            names.set_overrides(dictionary.team_overrides(conn))
            league_canon = dictionary.league_overrides(conn)
        finally:
            conn.close()
    except sqlite3.Error as e:
        print(f"словарь имён из базы не подключён ({e}) — работаем по aliases.json")
    rows = json.loads(report.read_text(encoding="utf-8"))["строки"]

    found: list = []
    maybe: list = []          # пара есть, вида спорта нет — решает склейка
    other_rows: list = []     # другой вид спорта — во вкладку «Other Sport» (03.10)
    # слово чужого вида спорта, оказавшееся именем команды («Le Mans» —
    # клуб, а не гонка; `app/sport.py`, 06.10): слово → сколько строк
    team_words: dict[str, int] = {}
    pages: list = []          # (сайт, передачи со страницы) — до отсева
    problems: list[str] = []
    parsed_counts: dict[str, int] = {}   # сырых строк от парсера по сайтам:
    # «расписание есть, а строк 0» — признак сломанной разметки (этап 6д)
    reference: list = []      # эталон живых матчей (справочники, для сверки live)
    reference_full: list = []  # тот же flashscore, но с именами и fs_id — в games.json
    locale_names: dict[str, dict] = {}    # fs_id → {язык: [home, away]} (6е, A2)
    locale_leagues: dict[str, dict] = {}  # fs_id → {язык: лига как её пишут там}
    fs_programs: list = []    # строки всех страниц flashscore.mobi — до settle
    снято: list[dict] = []    # строки, снятые фильтрами повторов, поимённо
    for row in rows:
        name = row.get("файл")
        if not name or not (folder / name).exists():
            # дальний день, которого у сайта просто нет, — не проблема
            # разбора, в «Не разобрано» ему не место (владелец 23.09)
            if row.get("итог") != store.SHORT_DEPTH_VERDICT:
                problems.append(f"{row['domain']} {row.get('channel') or 'сетка'}: "
                                f"{row['итог']} — {row['почему']}")
            continue
        setting = settings.get(row["domain"], {})
        # своего разбора нет — берём подобранный из готовых (`autoparse.py`)
        parse = parser_for(row["domain"], setting.get("parser") or "")
        if parse is None:
            problems.append(f"{row['domain']}: своего парсера нет")
            continue
        extra = {}
        if setting.get("include"):
            extra["channels"] = setting["include"]
        day = _date.fromisoformat(row["day"]) if row.get("day") else None
        try:
            programs = parse(
                (folder / name).read_text(encoding="utf-8", errors="replace"),
                day=day, tz=setting.get("tz"), url=row["url"], **extra)
        except TypeError:                 # парсер без фильтра каналов
            programs = parse((folder / name).read_text(encoding="utf-8", errors="replace"),
                             day=day, tz=setting.get("tz"), url=row["url"])
        except Exception as e:            # noqa: BLE001
            # Один сломавшийся парсер не должен уносить весь отчёт: сайт
            # меняет разметку, и тогда падает разбор именно его страницы.
            # Пишем причину в «Не разобрано» и идём дальше (01.09, когда
            # источников стало полсотни).
            problems.append(f"{row['domain']}: парсер упал — "
                            f"{type(e).__name__}: {e}")
            continue
        bare = _bare_domain(row["domain"])
        parsed_counts[bare] = parsed_counts.get(bare, 0) + len(programs)
        if row["domain"] in FS_LOCALES:
            # языковая версия эталона (6е, A2): на витрину не идёт и live не
            # подтверждает — отдаёт только имена по fs_id, ниже они лягут в
            # записи английского эталона полем `names`
            for prg in programs:
                fs_id = (prg.extra or {}).get("fs_id") or ""
                pair = (prg.match_raw or "").strip()
                if not fs_id or " - " not in pair:
                    continue
                home, _, away = pair.partition(" - ")
                lang = (prg.extra or {}).get("lang") or FS_LOCALES[row["domain"]]
                locale_names.setdefault(fs_id, {})[lang] = [home.strip(), away.strip()]
                if (prg.league_raw or "").strip():
                    locale_leagues.setdefault(fs_id, {})[lang] = prg.league_raw.strip()
            continue
        if _bare_domain(row["domain"]) in ("sporteventz.com",
                                           "flashscore.mobi"):
            # справочники (решения владельца 02–02.09): их строки на
            # витрину не идут, а служат ЭТАЛОНОМ живых матчей — угаданный
            # футбольный live без пары здесь считается записью.
            # flashscore.mobi — главный: весь мировой футбол дня (~370
            # матчей), канонические английские написания. Через отсев их
            # не гоняем: у строки календаря нет маркера эфира, и pipeline
            # срезал её раньше, чем отдавал пару (поймано 02.09 —
            # эталон приходил пустым).
            # flashscore.mobi копим до конца цикла: матч у полуночи стоит на
            # страницах двух дней, и одно время ему выбирается по всем
            # страницам сразу (`flashscore_mobi.settle`, сбор #205)
            if _bare_domain(row["domain"]) == "flashscore.mobi":
                fs_programs += programs
            else:
                add_reference(programs, reference, None)
            continue
        # Страницы сайтов разбираются ПОСЛЕ цикла: эталон flashscore едет в
        # том же обходе, и вид спорта строки решается уже с ним на руках
        # (`sport.Sports.decide`, правило 2; владелец 06.10)
        pages.append((row["domain"], programs))

    # Эталон flashscore: один матч — одна запись и одно время (сбор #205:
    # 103 матча стояли дважды с разницей в сутки, и живой эфир Instituto —
    # Boca Juniors 10.10 снимался «повтором» несуществующего матча 09.10)
    if fs_programs:
        прочтения: dict[str, set] = {}
        for prg in fs_programs:
            прочтения.setdefault((prg.extra or {}).get("fs_id") or "",
                                 set()).add(prg.start)
        разошлись = sum(1 for k, v in прочтения.items() if k and len(v) > 1)
        settled = flashscore_mobi.settle(fs_programs)
        add_reference(settled, reference, reference_full)
        print(f"эталон flashscore: строк со страниц {len(fs_programs)}, "
              f"матчей {len(settled)}; у {разошлись} страницы разошлись "
              f"во времени — оставлено одно (flashscore_mobi.settle)")

    # Имена локалей — к записям эталона по fs_id (6е, A2). Без английской
    # записи местное имя не к чему привязать, такие (3–4 в день) пропадают.
    if locale_names:
        attached = 0
        for ref in reference_full:
            extra_names = locale_names.get(ref.get("fs_id") or "")
            if extra_names:
                ref["names"] = extra_names
                ref["leagues"] = locale_leagues.get(ref["fs_id"], {})
                attached += 1
        print(f"локали эталона: имена у {len(locale_names)} матчей, "
              f"приложены к {attached} записям эталона")

    # Отсев и вид спорта каждой строки. Эталон главнее всего, что написано
    # на странице и что знают словари (владелец 02.10, #4335/#4336/#4328:
    # подсказка пары и лига из словаря умеют врать; владелец 06.10, #4710:
    # слово «Le Mans» отправляло футбол в автоспорт). Правила — по номерам в
    # `sport.Sports.decide`; здесь строки только раскладываются по судьбам
    judge = Reference(reference_full)
    league_sports, pair_sports = leagues.sports_map(), leagues.pair_sports()
    by_rule: dict[int, int] = {}       # номер правила → сколько строк
    for domain, programs in pages:
        for r in pipeline.run(programs, markers, sports, league_sports,
                              pair_sports, judge):
            if r.sport_rule:
                by_rule[r.sport_rule] = by_rule.get(r.sport_rule, 0) + 1
            if r.team_word:
                слово = r.team_word.lower()
                team_words[слово] = team_words.get(слово, 0) + 1
            if r.ok:
                found.append((domain, r))
            elif r.needs_review and r.reason == "вид спорта не определён" \
                    and r.home and r.away and r.start_kyiv:
                # Сайт назвал пару, но не сказал, что за игра: `ert.gr` пишет
                # `Κρουζέιρο – Φλαμένγκο` без слова «футбол». Такую строку не
                # выбрасываем — отдаём склейке кандидатом: если та же пара в
                # то же время нашлась на другом сайте с известным видом
                # спорта, вид берётся оттуда (решение владельца 01.09).
                maybe.append((domain, r))
            elif r.reason.startswith("другой вид спорта") and r.start_kyiv:
                # не футбол/баскет/теннис — не выбрасываем, а отдаём
                # отдельным списком во вкладку «Other Sport» (владелец 03.10)
                other_rows.append((domain, r))
    if by_rule:
        print("вид спорта по правилам (номера — `sport.Sports.decide`): "
              + ", ".join(f"№{n} — {by_rule[n]}" for n in sorted(by_rule)))
    if team_words:
        print("слово чужого вида спорта оказалось именем команды — строка "
              f"не ушла в «Other Sport»: {sum(team_words.values())} — "
              + ", ".join(f"{w} ×{n}" for w, n in sorted(team_words.items())))

    # Кандидаты без вида спорта: оставляем тех, кто сошёлся с настоящей игрой.
    # Сравнивает `app/merge.py` — там и допуск по времени (±150 минут, сетка
    # ставит блок раньше матча), и пословное сравнение имён. Часовые пояса
    # разных сайтов уже сведены к киевскому времени в `app/daytime.py`, так
    # что сравнение честное.
    if maybe:
        known = [merge.Entry(source=d, channel=r.program.channel_raw,
                             home=r.home, away=r.away, start=r.start_kyiv,
                             sport=r.sport, payload=r) for d, r in found]
        taken = 0
        for domain, r in maybe:
            probe = merge.Entry(source=domain, channel=r.program.channel_raw,
                                home=r.home, away=r.away, start=r.start_kyiv,
                                sport="", payload=r)
            for other in known:
                if other.sport and merge._same_game(probe, other,
                                                    names.SIMILAR_ENOUGH):
                    # донор и сам может ошибаться: movistar держал «India —
                    # Uruguay» баскетболом (строку потом сняли как повтор без
                    # эталона), а flashscore знает товарищеский матч сборных —
                    # ивритская строка sport5 уезжала в баскет (регресс
                    # 02.10). Эталон знает пару — его слово главнее донора
                    ref_sport = ref_sport_of(r, reference_full)
                    if ref_sport and ref_sport != other.sport:
                        r.sport = ref_sport
                        r.sport_word = ("по эталону flashscore "
                                        f"(донор {other.source} спорил)")
                    else:
                        r.sport = other.sport
                        r.sport_word = f"по совпадению с {other.source}"
                    r.ok, r.needs_review = True, False
                    found.append((domain, r))
                    taken += 1
                    break
        if taken:
            print(f"вид спорта восстановлен по совпадению: {taken} строк(и)")
        # вторая попытка — по эталону flashscore: у cyta строка «Asteras
        # AKTOR - Iraklis» приходит совсем голой (ни лиги, ни слова спорта),
        # и на других сайтах пары может не быть. Эталон знает весь футбол,
        # баскет и теннис дня — берём вид спорта из него (поймано владельцем
        # 03.09 по греческой Суперлиге на Novasports Prime)
        from_ref = 0
        for domain, r in maybe:
            if r.ok:
                continue
            for ref in reference_full:
                if not ref.get("start_kyiv"):
                    continue
                try:
                    ref_start = datetime.fromisoformat(ref["start_kyiv"])
                except ValueError:
                    continue
                # эталон в наивном киевском времени, строка — со смещением
                ours = r.start_kyiv.replace(tzinfo=None)
                if abs((ours - ref_start).total_seconds()) > 3 * 3600:
                    continue
                # и с местными написаниями эталона (6е, A2): «Брюж» дотягивается
                # до болгарского «Клуб Брюж», а до английского
                # «Club Brugge» — нет (#669, #676, MAX Sport)
                if canon._pair_score({"home": r.home, "away": r.away},
                                     ref) >= names.SIMILAR_ENOUGH:
                    r.sport = ref.get("sport", "F")
                    r.sport_word = "по эталону flashscore"
                    r.ok, r.needs_review = True, False
                    found.append((domain, r))
                    from_ref += 1
                    break
        if from_ref:
            print(f"вид спорта восстановлен по эталону: {from_ref} строк(и)")

        # Ещё одна попытка — по КОМАНДАМ эталона, без оглядки на время.
        # Клуб играет в одном виде спорта: раз «Kasımpaşa» и «Amedspor»
        # известны эталону как футбольные, то и строка beIN про них —
        # футбол, даже если сам матч идёт в записи. Владелец 10.09: «есть
        # названия, которые ты по логике уже должен знать». Берём только
        # однозначные имена: «Barcelona» — и футбол, и баскетбол, такие
        # пропускаем
        # ключ — чтение имени ВМЕСТЕ с полом и возрастом: «Mechelen W» —
        # другая команда, чем «Mechelen», и спорт у них может быть разный
        # (мужской Mechelen — футбол, женский — баскетбол; так женский
        # баскет cyta записывался футболом, #3535, владелец 28.09)
        def _ключ_вида(имя: str) -> tuple:
            return ((names.readings(имя) or ("",))[0], names.category(имя))

        по_командам: dict[tuple, set] = {}
        for ref in reference_full:
            вид = ref.get("sport") or "F"
            for сторона in ("home", "away"):
                имя = (ref.get(сторона) or "").strip()
                if имя:
                    ключ = _ключ_вида(имя)
                    if ключ[0]:
                        по_командам.setdefault(ключ, set()).add(вид)
        # плюс команды НАШЕЙ базы: эталон покрывает только дни обхода, а в
        # базе накоплено больше (владелец 10.09 — «сопоставь с расписанием»)
        for имя, вид in leagues.team_sports().items():
            ключ = _ключ_вида(имя)
            if ключ[0]:
                по_командам.setdefault(ключ, set()).add(вид)
        # Ключ считается по очищенному имени, и разные клубы могут сойтись в
        # один: «Paris FC» (футбол) и «Paris Basketball» дают «PARIS». Такой
        # ключ выбрасываем — по нему вид спорта не определить
        однозначные = {k: next(iter(v)) for k, v in по_командам.items()
                       if len(v) == 1}
        from_team = 0
        for domain, r in maybe:
            if r.ok:
                continue
            буквы = set()
            for имя in (r.home, r.away):
                буквы.add(однозначные.get(_ключ_вида(имя or "")))
            # обе стороны должны быть известны и сойтись: у сборных за одним
            # именем стоит и футбол, и баскетбол, и по одной стороне решать
            # нельзя («Fidži - Kanada» — это могло быть что угодно)
            if len(буквы) != 1 or None in буквы:
                continue
            r.sport = буквы.pop()
            r.sport_word = "по командам эталона"
            r.ok, r.needs_review = True, False
            found.append((domain, r))
            from_team += 1
        if from_team:
            print(f"вид спорта восстановлен по командам эталона: "
                  f"{from_team} строк(и)")
        # третья попытка — иврит (6е, задание 03.09): израильскую строку
        # буквы к эталону не подведут (локали he у flashscore нет), ведут
        # лига и время — мост общий с canon.align. Без лиги
        # игру выдают сами клубы (Хапоэль, Маккаби, Бейтар…)
        from_il = 0
        for domain, r in maybe:
            if r.ok:
                continue
            probe = {"home": r.home, "away": r.away,
                     "league": r.league or r.program.league_raw or ""}
            if canon._script(f"{r.home} {r.away}") != "he" \
                    or not canon.looks_israeli(probe):
                continue
            ours = r.start_kyiv.replace(tzinfo=None)
            il = []
            for ref in reference_full:
                try:
                    ref_start = datetime.fromisoformat(
                        ref.get("start_kyiv") or "")
                except ValueError:
                    continue
                israeli = (ref.get("league") or "").upper() \
                    .startswith("ISRAEL")
                if israeli and abs((ours - ref_start).total_seconds()) \
                        <= 3 * 3600:
                    il.append(ref)
            pick, verdict = canon.il_pick(probe, il)
            if pick is not None:
                r.sport = pick.get("sport", "F")
                r.sport_word = "израильский матч эталона"
                r.ok, r.needs_review = True, False
                found.append((domain, r))
                from_il += 1
        if from_il:
            print(f"вид спорта восстановлен по израильскому эталону: "
                  f"{from_il} строк(и)")

    # Правило владельца 04.09: строку с парой и временем, которую не поняли
    # ни склейка, ни эталон, ни израильский мост, — НЕ убивать молча, а
    # отдать человеку (очередь «Вид спорта» в модерации; кейс Эйлат —
    # Герцлия: 5 израильских кандидатов в ±3 ч, буквы не решили).
    # Но только с похожих на спорт строк: без этого сита в очередь ехали
    # 1543 строки — передачи BBC, скачки, биржевые сводки
    sporty_channel = re.compile(r"sport|спорт|ספורט|deportes|esporte", re.I)
    unsolved = [
        (domain, r) for domain, r in maybe
        if not r.ok and (
            sporty_channel.search(r.program.channel_raw or "")
            or canon.looks_israeli(
                {"home": r.home, "away": r.away,
                 "league": r.league or r.program.league_raw or ""}))]
    # Повтор в очередь не кладём: канал крутит запись вчерашнего матча, и
    # спрашивать про него вид спорта незачем (10.09: из 485 нерешённых
    # строк 67 были именно такими, в основном beIN и oneplaysport)
    # `reference` — кортежи (дом, гости, время) для сверки live, а
    # индексу нужны записи целиком: `reference_full` (обход 11.09
    # упал на этой путанице)
    индекс_эталона = reference_index(reference_full)
    было = len(unsolved)
    в_очередь = []
    for domain, r in unsolved:
        матч = played_before(r.home, r.away, "", r.start_kyiv, индекс_эталона)
        if матч is None:
            в_очередь.append((domain, r))
        else:
            снято.append(removed_row(СНЯТО_ОЧЕРЕДЬ, domain, r,
                                     f"эталон: {_ref_text(матч)}"))
    unsolved = в_очередь
    if было - len(unsolved):
        print(f"из очереди убрано повторов: {было - len(unsolved)} "
              f"(матч уже сыгран)")
    if unsolved:
        print(f"не разобрано — уйдёт в модерацию: {len(unsolved)} строк(и)")

    # Межфайловые повторы у источников без честного флага (см. константу):
    # та же пара (в любом порядке команд) позже первого показа — запись.
    def _bare(domain: str) -> str:
        return domain.removeprefix("www.")

    def _guess_key(domain: str, r) -> tuple:
        return (_bare(domain), tuple(sorted((r.home.lower(), r.away.lower()))))

    firsts: dict[tuple, object] = {}
    for domain, r in found:
        if guessed(domain, r):
            key = _guess_key(domain, r)
            if key not in firsts or r.start_kyiv < firsts[key]:
                firsts[key] = r.start_kyiv

    def _late_show(domain: str, r) -> bool:
        if not guessed(domain, r):
            return False
        first = firsts[_guess_key(domain, r)]
        if r.start_kyiv <= first:
            return False
        снято.append(removed_row(
            СНЯТО_ПОЗДНИЙ_ПОКАЗ, domain, r,
            f"та же пара у этого сайта раньше: {first.strftime('%d.%m %H:%M')}"))
        return True

    found = [(domain, r) for domain, r in found if not _late_show(domain, r)]

    # Топовая лига от «угадаек» без подтверждения эталоном — запись.
    # Повторы АПЛ/ЛаЛиги/ЛЧ крутят днём все европейские пакеты (Spurs -
    # Newcastle в 14:30 у tv2.no, Dinamo Zagreb - Viking в 12:55 у TRT и
    # movistar — поймано владельцем 02.09). Настоящий матч топ-турнира
    # всегда есть в справочнике sporteventz; нишевые лиги (кубок Греции на
    # ERT) правило не трогает — их повторы днём не гоняют, а в справочнике
    # их может не быть.
    # местные написания эталона той же письменности (как `canon._sides`):
    # угадайку ERT «Β. Ιρλανδία – Ελλάδα» английские имена не узнавали, и
    # честный live U21 снимался как «повтор без эталона» (01.10). Греческое
    # сравниваем с греческим flashscore, иврит/кириллицу — со своими.
    # Латиницу тоже (07.10, сбор #205): «Ferencvárosi TC - DVSC» у port.hu
    # английское «Ferencvaros - Debrecen» не узнавало, а венгерское
    # «Debreceni VSC» узнаёт. Футбол и баскет/теннис — каждый со своими
    reference_local = local_reference(reference_full)

    def _in_reference_local(r, sport: str) -> bool:
        return in_local_reference(r.home, r.away, r.start_kyiv, sport,
                                  reference_local)

    def _in_reference(r) -> bool:
        # пословно, а не побуквенно: «Millwall FC - Newcastle United» у
        # oneplaysport — тот же матч, что «Millwall - Newcastle» эталона,
        # а точное сравнение убивало живую строку как запись (#728, 03.09)
        if _in_reference_local(r, "F"):
            return True
        for h, a, t in reference:
            if abs((r.start_kyiv - t).total_seconds()) > 3 * 3600:
                continue
            if (names.same_team(r.home, h) and names.same_team(r.away, a))                     or (names.same_team(r.home, a)
                        and names.same_team(r.away, h)):
                return True
        return False

    top_league = re.compile(
        r"(?i)premier ?league|la ?liga|serie ?a\b|bundesliga|ligue ?1"
        r"|champions|şampiyonlar|liga de campeones|лига чемпионов|европ"
        r"|europa|conference|чемпионат (испании|англии|италии|германии)"
        r"|d[üu]nya kupas|world cup|кубок мира|coppa italia|copa del rey"
        r"|dfb.pokal|fa cup|кубок (италии|испании|германии|англии)")
    before = len(found)
    # Только футбол: эталоны футбольные, баскет и теннис им не проверить.
    # Пока эталон был бедным (sporteventz, ~20 матчей) правило касалось
    # лишь топ-лиг; с flashscore.mobi (весь мировой футбол дня, ~370)
    # сверяется КАЖДЫЙ угаданный футбольный live — утренние повторы
    # Eliteserien и 1. Lig уходят так же, как АПЛ. Богат ли эталон,
    # проверяем по размеру: сломается mobi — вернёмся к мягкому правилу.
    rich = len(reference) >= 100
    found = sift(found, lambda domain, r: (
        not guessed(domain, r)
        or r.sport != "F"
        or not (rich or top_league.search(f"{r.league} {r.program.league_raw}"))
        or _in_reference(r)),
        снято, СНЯТО_НЕТ_В_ЭТАЛОНЕ,
        "эфир угадан, а пары нет в эталоне в ±3 ч — запись")
    if before - len(found):
        kind = "все лиги, эталон полный" if rich else "топ-лиги"
        print(f"повторы без эталона ({kind}): убрано {before - len(found)}")

    # 22.09 (#3368/#3369/#3370): та же страховка для БАСКЕТА и ТЕННИСА —
    # Кубок Дэвиса и «Уимблдон» с Джоковичем шли записями: сверка выше
    # касалась только футбола, а у novasports/beIN будущий эфир не помечен
    # ((Ζ)/LIVE сайт вешает только на идущее сейчас). Эталон B/T лежит в
    # reference_full (flashscore.mobi, с 6б); беден эталон спорта — правило
    # для этого спорта молчит, как футбольное до rich.
    from datetime import datetime as _dt_kls
    from zoneinfo import ZoneInfo as _Kyiv
    reference_bt = []
    for rec in reference_full:
        if rec.get("sport") in ("B", "T"):
            try:
                t = _dt_kls.strptime(rec["start_kyiv"], "%Y-%m-%dT%H:%M") \
                    .replace(tzinfo=_Kyiv("Europe/Kyiv"))
            except (KeyError, ValueError):
                continue
            reference_bt.append((rec["home"], rec["away"], t, rec["sport"]))
    rich_bt = {s: sum(1 for *_x, sp in reference_bt if sp == s) >= 40
               for s in ("B", "T")}

    def _in_reference_bt(r) -> bool:
        # местные написания эталона — как у футбола (07.10)
        if _in_reference_local(r, r.sport):
            return True
        for h, a, t, sp in reference_bt:
            if sp != r.sport:
                continue
            if abs((r.start_kyiv - t).total_seconds()) > 3 * 3600:
                continue
            if (names.same_team(r.home, h) and names.same_team(r.away, a)) \
                    or (names.same_team(r.home, a)
                        and names.same_team(r.away, h)):
                return True
        return False

    before = len(found)
    found = sift(found, lambda domain, r: (
        not guessed(domain, r)
        or r.sport not in ("B", "T")
        or not rich_bt.get(r.sport)
        or _in_reference_bt(r)),
        снято, СНЯТО_НЕТ_В_ЭТАЛОНЕ_БТ,
        "эфир угадан, а пары нет в эталоне в ±3 ч — запись")
    if before - len(found):
        print("повторы без эталона (баскет/теннис): "
              f"убрано {before - len(found)}")

    # «Грязные» минуты у угаданного эфира — признак записи: прямые
    # трансляции начинаются на :00/:05/…/:55, а повтор в сетке стартует
    # где закончился прошлый блок (`Man Utd - Ipswich` в 00:17 и
    # `Crystal Palace - Man City` в 03:47 у movistarplus — поймано
    # владельцем на витрине 02.09). Честно помеченных сайтов не касается.
    found = sift(found, lambda domain, r: (
        not guessed(domain, r) or r.start_kyiv.minute % 5 == 0),
        снято, СНЯТО_ГРЯЗНЫЕ_МИНУТЫ,
        "эфир угадан, а начало не на :00/:05/…/:55 — запись")

    # Сетки отдают сразу две недели вперёд. Обрезаем по правилу владельца
    # «сегодня и не больше 6 дней вперёд» (01.09), а НЕ по окну скачивания:
    # недельная сетка уже привезла дальние дни одним запросом, выбрасывать
    # их — терять понедельник бесплатно (поймано владельцем 03.09 по
    # sporttv.pt). Окно `days` управляет только числом СКАЧИВАЕМЫХ страниц.
    # С `--all` видно всё, что пришло.
    def in_window(day: _date) -> bool:
        if args.date:
            return day == _date.fromisoformat(args.date)
        if args.all:
            return True
        # окно витрины — киевские сутки: игры идут с киевским временем, а
        # часы GitHub (UTC) в 22:30 ещё во вчерашнем дне Киева
        first = daytime.today("Europe/Kyiv")
        return first <= day <= first + timedelta(days=6)

    found = [x for x in found if in_window(x[1].start_kyiv.date())]

    found.sort(key=lambda x: x[1].start_kyiv)
    found, копий = unique_rows(found)
    if копий:
        print(f"одна передача с нескольких страниц сайта — копий убрано: {копий}")

    # Другой вид спорта — тем же окном дней, без склейки: одна строка на
    # (сайт, канал, заголовок, время). Это отдельный список для вкладки
    # «Other Sport» админки, с футболом/баскетом/теннисом не смешивается
    # (владелец 03.10); вид спорта словами — из раздела «другие» markers.json
    other_rows = [x for x in other_rows if in_window(x[1].start_kyiv.date())]
    seen_other: set = set()
    other_out: list[dict] = []
    for domain, r in sorted(other_rows, key=lambda x: x[1].start_kyiv):
        key = (domain, r.program.channel_raw or "", (r.program.title or "")[:200],
               r.start_kyiv)
        if key in seen_other:
            continue
        seen_other.add(key)
        other_out.append({
            "домен": domain,
            "канал": r.program.channel_raw or "",
            "заголовок": (r.program.title or "")[:200],
            "лига": (r.program.league_raw or "")[:120],
            # страница, где строка найдена, — для ссылки «открыть расписание
            # канала» на вкладке Other Sport (владелец 04.10)
            "url": r.program.source_url or "",
            "вид": r.sport_group or "другое",
            "слово": r.reason.split(":", 1)[-1].strip()[:60],
            "start_kyiv": r.start_kyiv.strftime("%Y-%m-%dT%H:%M"),
            "start_utc": (r.start_utc.strftime("%Y-%m-%dT%H:%M")
                          if r.start_utc else ""),
        })
    if other_out:
        kinds = len({x["вид"] for x in other_out})
        print(f"другой вид спорта: {len(other_out)} строк(и), видов {kinds} — "
              f"во вкладку «Other Sport»")

    # Трансляция турнира без пары игроков: каждый сайт зовёт её по-своему
    # («China Open - Beijing», «ATP 500 - BEIJING», «BEIJING 2026 - QUARTOS DE
    # FINAL»), и склейка по буквам их не сводит. Узнаём тур и город по
    # словарю и эталону — строка получает общее имя «ATP Beijing», и сайты
    # ложатся одной строкой со всеми каналами (владелец 04.10,
    # `app/broadcast.py`). Не узнали — остаётся как написал сайт
    known_tournaments = broadcast.tournaments(reference_full)
    сведено, не_узнаны = 0, set()
    for domain, r in found:
        if r.sport != "T" or not broadcast.is_title("T", r.home, r.away):
            continue
        заголовок = " ".join(x for x in (r.program.title, r.program.league_raw,
                                         r.program.sport_raw) if x)
        имя = broadcast.tournament(заголовок, known_tournaments)
        if имя:
            r.home, r.away = имя, broadcast.SESSION
            сведено += 1
        else:
            не_узнаны.add((domain, (r.program.title or "")[:70]))
    if сведено or не_узнаны:
        print(f"трансляции турниров без пары: сведено по туру и городу {сведено}; "
              f"город не узнан у {len(не_узнаны)} заголовков"
              + ("".join(f"\n   • {d}: {t}" for d, t in sorted(не_узнаны)[:12])
                 if не_узнаны else ""))

    # Одна игра, найденная на трёх сайтах, — одна строка с тремя каналами
    # (ТЗ разд. 9). Разбор по сайтам ниже сохраняем: по нему видно, откуда
    # что пришло, и проверяется сама склейка.
    # Лигу показываем канонически (`ENGLAND: Premier League`), а не так, как
    # её назвал сайт. Канона ещё нет — оставляем сырое имя: оно попадёт в
    # очередь названий и станет каноном после подтверждения.
    games = merge.merge([
        merge.Entry(source=domain, channel=r.program.channel_raw,
                    home=r.home, away=r.away, start=r.start_kyiv,
                    sport=r.sport,
                    league=league_canon.get(r.league, r.league), payload=r)
        for domain, r in found])

    games, повторы = drop_reference_repeats(games, reference_full)
    for g, матч in повторы:
        for e in g.entries:
            снято.append(removed_row(СНЯТО_СЫГРАН, e.source, e.payload,
                                     f"эталон: {_ref_text(матч)}"))
    if повторы:
        print(f"повторы сняты по flashscore: {len(повторы)} (матч уже сыгран, "
              f"канал крутит запись)"
              + "".join(f"\n   • {g.start.strftime('%d.%m %H:%M')} {g.home} — "
                        f"{g.away} [{', '.join(g.channels)}] ← {_ref_text(матч)}"
                        for g, матч in повторы))

    games, late = drop_late_repeats(games)
    for g, earlier in late:
        for e in g.entries:
            снято.append(removed_row(
                СНЯТО_ПОЗДНИЙ_ПОВТОР, e.source, e.payload,
                f"та же пара раньше: {earlier.start.strftime('%d.%m %H:%M')} "
                f"[{', '.join(earlier.channels)}]"))
    if late:
        print(f"поздние повторы сняты: {len(late)} (та же пара уже была раньше "
              f"у другого сайта)"
              + "".join(f"\n   • {g.start.strftime('%d.%m %H:%M')} {g.home} — "
                        f"{g.away} [{', '.join(g.channels)}] ← "
                        f"{earlier.start.strftime('%d.%m %H:%M')}"
                        for g, earlier in late))

    # Журнал снятого (владелец: «ничто не теряется молча»): каждая строка,
    # снятая фильтром повторов, — поимённо, тем же окном дней, что витрина
    снято = [x for x in снято if not x["start_kyiv"]
             or in_window(_date.fromisoformat(x["start_kyiv"][:10]))]
    if снято:
        по_фильтрам: dict[str, int] = {}
        for x in снято:
            по_фильтрам[x["фильтр"]] = по_фильтрам.get(x["фильтр"], 0) + 1
        print(f"снято фильтрами повторов (в окне витрины): {len(снято)} — "
              + "; ".join(f"{k}: {v}" for k, v in по_фильтрам.items())
              + " (поимённо — matches.md и games.json «снято»)")

    lines = ["# Матчи с живого обхода", "",
             f"Игр: **{len(games)}** (строк с сайтов: {len(found)}). "
             f"Время киевское.", "",
             "| Когда | Матч | Лига | Каналы |", "|---|---|---|---|"]
    print(f"строк с сайтов: {len(found)}, игр после склейки: {len(games)}\n")
    for g in games:
        when = g.start.strftime("%d.%m %H:%M")
        mark = " ×" + str(len(g.entries)) if len(g.entries) > 1 else ""
        print(f"  {when}  {g.home[:22].ljust(22)} — {g.away[:22].ljust(22)}"
              f" {g.league[:26].ljust(26)}{mark}")
        lines.append(f"| {when} | {g.home} — {g.away} | {g.league} | "
                     f"{', '.join(g.channels)} |")

    lines += ["", "## Строки по сайтам", "",
              "| Когда | Сайт | Канал | Матч | Лига |", "|---|---|---|---|---|"]
    for domain, r in found:
        lines.append(f"| {r.when} | {domain} | {r.program.channel_raw} | "
                     f"{r.home} — {r.away} | {r.league} |")
    if снято:
        lines += ["", "## Снято фильтрами повторов", "",
                  "| Когда | Сайт | Канал | Заголовок | Фильтр | Почему |",
                  "|---|---|---|---|---|---|"]
        for x in sorted(снято, key=lambda x: (x["start_kyiv"], x["домен"])):
            lines.append(f"| {x['start_kyiv'].replace('T', ' ')} | {x['домен']} | "
                         f"{x['канал']} | {x['заголовок'][:80]} | {x['фильтр']} | "
                         f"{x['почему']} |")
    if problems:
        print("\nне разобрано:")
        lines += ["", "## Не разобрано", ""]
        for text in problems:
            print("  •", text)
            lines.append(f"- {text}")

    out = Path(args.md) if args.md else folder / "matches.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Машиночитаемый двойник отчёта: его забирает `scripts/games_import.py`
    # и кладёт игры в базу для сайта (этап 4). Человеку — matches.md, коду — это.
    window = args.days or plan_days(Path(args.plan))
    previous = previous_counts()
    verdict = (too_few(len(games), window, previous)
               if args.strict and not args.date else "")
    # «собрано» — ВСЕГДА в UTC: заливка (`store.log_run`) и возраст файла
    # (`crawl_fetch.age_hours`) считают метку UTC-часами. На GitHub так и
    # было само собой, а сервер (mojtv, киевский пояс) писал местное время —
    # и его сборы показывались на 3 часа позже, ломая порядок «Last 3 runs»
    # (жалоба владельца 26.09)
    payload = {"собрано": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
               "игр": len(games),
               # окно этого прогона и память «сколько игр давало каждое
               # окно» — для порога провала следующего (A4)
               "окно": 0 if args.date else window,
               "по_окнам": (previous if args.date
                            else {**previous, str(window): len(games)}),
               "оценка": verdict,
               "эталон": reference_full,
               "разобрано": parsed_counts,
               # другой вид спорта — отдельным списком во вкладку «Other
               # Sport» админки (владелец 03.10)
               "другие_виды": other_out,
               # нерешённые строки — человеку в модерацию (правило 04.09)
               "на_разбор": [{
                   "домен": domain,
                   "канал": r.program.channel_raw or "",
                   "home": r.home, "away": r.away,
                   "league": r.league or r.program.league_raw or "",
                   "start_kyiv": (r.start_kyiv.strftime("%Y-%m-%dT%H:%M")
                                  if r.start_kyiv else ""),
                   "raw_title": (r.program.title or "")[:200],
               } for domain, r in unsolved],
               # строки, снятые фильтрами повторов, поимённо (сайт, канал,
               # заголовок, время, фильтр, почему) — заливка ключ не читает
               "снято": снято,
               "games": [{
                   # игра целиком из «угаданных» источников: при заливке её
                   # сверяют с УЖЕ лежащими в базе событиями той же пары —
                   # прошлый прогон мог видеть настоящий эфир (этап 6б)
                   "guess": int(all(guessed(e.source, e.payload)
                                    for e in g.entries)),
                   "sport": g.sport,
                   "league": g.league,
                   "home": g.home,
                   "away": g.away,
                   "start_kyiv": g.start.strftime("%Y-%m-%dT%H:%M"),
                   "start_utc": (g.first.payload.start_utc.strftime("%Y-%m-%dT%H:%M")
                                 if getattr(g.first.payload, "start_utc", None)
                                 else ""),
                   "entries": [{
                       "source": e.source,
                       "channel": e.channel,
                       "url": getattr(getattr(e.payload, "program", None),
                                      "source_url", "") or "",
                       "raw_title": getattr(getattr(e.payload, "program", None),
                                            "title", "") or "",
                   } for e in g.entries],
               } for g in games]}
    games_out = out.parent / "games.json"
    games_out.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    print(f"\nотчёт: {out}\nигры для базы: {games_out}")
    if verdict:
        print(verdict)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

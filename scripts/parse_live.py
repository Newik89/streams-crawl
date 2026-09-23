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
from datetime import date as _date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import (canon, db, dictionary, leagues, live, merge, names,  # noqa: E402
                 pipeline, sport)
from app.parsers import get as parser_for                   # noqa: E402
from app.parsers.flashscore_mobi import LOCALES as FS_LOCALES  # noqa: E402

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
                        # Kanal 1 пишет «Vysielame» всем строкам подряд;
                        # у port.hu признака эфира нет вовсе
                        "kanal1sport.sk", "port.hu", "webtv.sk",
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


def already_played(home: str, away: str, start, индекс: dict) -> bool:
    """Этот матч уже сыгран — значит показ является повтором.

    Ищем ту же пару в эталоне flashscore за прошедшие 4–60 часов. Меньше
    четырёх — это тот же матч в своём окне (студия, разброс сеток), больше
    шестидесяти — уже новая встреча тех же команд.
    """
    if not индекс or not start:
        return False
    # эталон лежит в наивном киевском времени, а время строки — со смещением;
    # сравнивать их напрямую нельзя (обход 11.09 упал именно на этом)
    start = start.replace(tzinfo=None)
    if names.is_placeholder(home) or names.is_placeholder(away):
        return False        # соперник ещё не назван — судить не по чему
    день = start.date()
    for д in (день, день - timedelta(days=1), день - timedelta(days=2)):
        for r, when in индекс.get(д, []):
            разрыв = start - when
            if not (REPEAT_AFTER < разрыв <= REPEAT_DEPTH):
                continue
            пара = {"home": home, "away": away, "league": "",
                    "sport": r.get("sport", "F")}
            if canon._pair_score(пара, r) >= names.SIMILAR_ENOUGH:
                return True
    return False


def drop_reference_repeats(games: list, reference: list) -> tuple[list, int]:
    """Снять показы матчей, которые УЖЕ сыграны.

    Канал крутит запись: `Fenerbahçe - AS Řím` стоит в сетке 11.09 в 10:00,
    а сам матч по flashscore был 10.09 в 19:45. Это не расписание, а повтор
    — на витрину он не идёт (разбор владельца 10.09: из 485 нерешённых строк
    67 оказались именно такими, в основном oneplaysport.cz и beIN).

    Матч эталона ПОЗЖЕ строки не трогаем: это либо анонс будущей игры, либо
    расхождение дат у сайта — другой случай, отдельный разбор.
    """
    if not reference:
        return games, 0
    # индекс по дню: перебирать 5 тысяч записей на каждую игру слишком долго
    по_дням: dict = {}
    for r in reference:
        try:
            when = datetime.fromisoformat(r.get("start_kyiv") or "")
        except ValueError:
            continue
        по_дням.setdefault(when.date(), []).append((r, when))
    оставили, снято = [], 0
    for g in games:
        начало = g.start.replace(tzinfo=None)     # эталон — в наивном времени
        # соперник ещё не назван («Francia — TBC»): такую строку по одной
        # стороне легко принять за повтор прошлого матча этой команды
        if names.is_placeholder(g.home) or names.is_placeholder(g.away):
            оставили.append(g)
            continue
        повтор = False
        день = начало.date()
        сутки = [день, день - timedelta(days=1), день - timedelta(days=2)]
        for д in сутки:
            for r, when in по_дням.get(д, []):
                разрыв = начало - when
                if not (REPEAT_AFTER < разрыв <= REPEAT_DEPTH):
                    continue
                пара = {"home": g.home, "away": g.away,
                        "league": g.first.league or "",
                        "sport": r.get("sport", "F")}
                if canon._pair_score(пара, r) >= names.SIMILAR_ENOUGH:
                    повтор = True
                    break
            if повтор:
                break
        if повтор:
            снято += 1
        else:
            оставили.append(g)
    return оставили, снято


def drop_late_repeats(games: list) -> tuple[list, int]:
    """Убрать поздние повторы, которые видно только по соседнему сайту.

    Сайт без честного флага эфира помечает эфиром свой самый ранний показ
    пары. Но матч мог пройти ещё раньше — и это видно по другому источнику:
    01.09 `Barcelona - Rayo Vallecano` попал в ленту четыре раза (00:30,
    05:00, 09:45, 13:00), хотя игра была накануне вечером.

    Поэтому уже после склейки смотрим: если та же пара с тем же видом спорта
    была раньше (в пределах 30 часов, чтобы не снести ответный матч через
    неделю), а поздняя запись целиком собрана из «угаданных» источников —
    это повтор, в ленту он не идёт.
    """
    kept: list = []
    removed = 0
    for game in sorted(games, key=lambda g: g.start):
        guessed_only = all(
            _bare_domain(e.source) in REPEAT_GUESS_DOMAINS for e in game.entries)
        if guessed_only and any(
                _looks_repeat(earlier, game) for earlier in kept):
            removed += 1
            continue
        kept.append(game)
    return kept, removed


def _bare_domain(domain: str) -> str:
    return (domain or "").removeprefix("www.")


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
    problems: list[str] = []
    parsed_counts: dict[str, int] = {}   # сырых строк от парсера по сайтам:
    # «расписание есть, а строк 0» — признак сломанной разметки (этап 6д)
    reference: list = []      # эталон живых матчей (справочники, для сверки live)
    reference_full: list = []  # тот же flashscore, но с именами и fs_id — в games.json
    locale_names: dict[str, dict] = {}    # fs_id → {язык: [home, away]} (6е, A2)
    locale_leagues: dict[str, dict] = {}  # fs_id → {язык: лига как её пишут там}
    for row in rows:
        name = row.get("файл")
        if not name or not (folder / name).exists():
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
            from zoneinfo import ZoneInfo as _Z
            for prg in programs:
                pair = (prg.match_raw or "").strip()
                if " - " in pair and prg.start is not None:
                    home, _, away = pair.partition(" - ")
                    begin = prg.start.astimezone(_Z("Europe/Kyiv"))
                    # live-подтверждение остаётся футбольным: правила про
                    # повторы топ-лиг и порог rich считают только футбол
                    if prg.sport_raw in ("Soccer", ""):
                        reference.append((home.strip(), away.strip(),
                                          begin))
                    # полный эталон уезжает в games.json: по нему импорт
                    # закрепляет канонические английские имена (app/canon.py);
                    # с 6б в нём и баскетбол с теннисом
                    if _bare_domain(row["domain"]) == "flashscore.mobi":
                        reference_full.append({
                            "sport": {"Basketball": "B",
                                      "Tennis": "T"}.get(prg.sport_raw, "F"),
                            "home": home.strip(), "away": away.strip(),
                            "league": (prg.league_raw or "").strip(),
                            "fs_id": (prg.extra or {}).get("fs_id", ""),
                            "start_kyiv": begin.strftime("%Y-%m-%dT%H:%M"),
                        })
            continue
        for r in pipeline.run(programs, markers, sports):
            if r.ok:
                found.append((row["domain"], r))
            elif r.needs_review and r.reason == "вид спорта не определён"                     and r.home and r.away and r.start_kyiv:
                # Сайт назвал пару, но не сказал, что за игра: `ert.gr` пишет
                # `Κρουζέιρο – Φλαμένγκο` без слова «футбол». Такую строку не
                # выбрасываем — отдаём склейке кандидатом: если та же пара в
                # то же время нашлась на другом сайте с известным видом
                # спорта, вид берётся оттуда (решение владельца 01.09).
                maybe.append((row["domain"], r))

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
        по_командам: dict[str, set] = {}
        for ref in reference_full:
            вид = ref.get("sport") or "F"
            for сторона in ("home", "away"):
                имя = (ref.get(сторона) or "").strip()
                if имя:
                    ключ = (names.readings(имя) or ("",))[0]
                    if ключ:
                        по_командам.setdefault(ключ, set()).add(вид)
        # плюс команды НАШЕЙ базы: эталон покрывает только дни обхода, а в
        # базе накоплено больше (владелец 10.09 — «сопоставь с расписанием»)
        for имя, вид in leagues.team_sports().items():
            ключ = (names.readings(имя) or ("",))[0]
            if ключ:
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
                ключ = (names.readings(имя or "") or ("",))[0]
                буквы.add(однозначные.get(ключ))
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
    unsolved = [(domain, r) for domain, r in unsolved
                if not already_played(r.home, r.away, r.start_kyiv,
                                      индекс_эталона)]
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
        if _bare(domain) in REPEAT_GUESS_DOMAINS:
            key = _guess_key(domain, r)
            if key not in firsts or r.start_kyiv < firsts[key]:
                firsts[key] = r.start_kyiv
    found = [(domain, r) for domain, r in found
             if _bare(domain) not in REPEAT_GUESS_DOMAINS
             or r.start_kyiv <= firsts[_guess_key(domain, r)]]

    # Топовая лига от «угадаек» без подтверждения эталоном — запись.
    # Повторы АПЛ/ЛаЛиги/ЛЧ крутят днём все европейские пакеты (Spurs -
    # Newcastle в 14:30 у tv2.no, Dinamo Zagreb - Viking в 12:55 у TRT и
    # movistar — поймано владельцем 02.09). Настоящий матч топ-турнира
    # всегда есть в справочнике sporteventz; нишевые лиги (кубок Греции на
    # ERT) правило не трогает — их повторы днём не гоняют, а в справочнике
    # их может не быть.
    def _in_reference(r) -> bool:
        # пословно, а не побуквенно: «Millwall FC - Newcastle United» у
        # oneplaysport — тот же матч, что «Millwall - Newcastle» эталона,
        # а точное сравнение убивало живую строку как запись (#728, 03.09)
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
    found = [(domain, r) for domain, r in found
             if _bare_domain(domain) not in REPEAT_GUESS_DOMAINS
             or r.sport != "F"
             or not (rich
                     or top_league.search(f"{r.league} {r.program.league_raw}"))
             or _in_reference(r)]
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
    found = [(domain, r) for domain, r in found
             if _bare_domain(domain) not in REPEAT_GUESS_DOMAINS
             or r.sport not in ("B", "T")
             or not rich_bt.get(r.sport)
             or _in_reference_bt(r)]
    if before - len(found):
        print("повторы без эталона (баскет/теннис): "
              f"убрано {before - len(found)}")

    # «Грязные» минуты у угаданного эфира — признак записи: прямые
    # трансляции начинаются на :00/:05/…/:55, а повтор в сетке стартует
    # где закончился прошлый блок (`Man Utd - Ipswich` в 00:17 и
    # `Crystal Palace - Man City` в 03:47 у movistarplus — поймано
    # владельцем на витрине 02.09). Честно помеченных сайтов не касается.
    found = [(domain, r) for domain, r in found
             if _bare(domain) not in REPEAT_GUESS_DOMAINS
             or r.start_kyiv.minute % 5 == 0]

    # Сетки отдают сразу две недели вперёд. Обрезаем по правилу владельца
    # «сегодня и не больше 6 дней вперёд» (01.09), а НЕ по окну скачивания:
    # недельная сетка уже привезла дальние дни одним запросом, выбрасывать
    # их — терять понедельник бесплатно (поймано владельцем 03.09 по
    # sporttv.pt). Окно `days` управляет только числом СКАЧИВАЕМЫХ страниц.
    # С `--all` видно всё, что пришло.
    if args.date:
        chosen = _date.fromisoformat(args.date)
        found = [x for x in found if x[1].start_kyiv.date() == chosen]
    elif not args.all:
        first = _date.today()
        last = first + timedelta(days=6)
        found = [x for x in found if first <= x[1].start_kyiv.date() <= last]

    found.sort(key=lambda x: x[1].start_kyiv)

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
    if повторы:
        print(f"повторы сняты по flashscore: {повторы} (матч уже сыгран, "
              f"канал крутит запись)")

    games, late = drop_late_repeats(games)
    if late:
        print(f"поздние повторы сняты: {late} (та же пара уже была раньше "
              f"у другого сайта)")

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
    payload = {"собрано": datetime.now().strftime("%Y-%m-%d %H:%M"),
               "игр": len(games),
               # окно этого прогона и память «сколько игр давало каждое
               # окно» — для порога провала следующего (A4)
               "окно": 0 if args.date else window,
               "по_окнам": (previous if args.date
                            else {**previous, str(window): len(games)}),
               "оценка": verdict,
               "эталон": reference_full,
               "разобрано": parsed_counts,
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
               "games": [{
                   # игра целиком из «угаданных» источников: при заливке её
                   # сверяют с УЖЕ лежащими в базе событиями той же пары —
                   # прошлый прогон мог видеть настоящий эфир (этап 6б)
                   "guess": int(all(_bare_domain(e.source)
                                    in REPEAT_GUESS_DOMAINS
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

# -*- coding: utf-8 -*-
r"""Книга случаев: каждая жалоба владельца и каждая введённая возможность —
постоянная проверка перед выкладкой (владелец 13.10.2026: «чтобы не
повторялись ошибки и не ходить кругами»; «не только жалоб, а и предложений
ввести новое — чтоб новое не ломало старое»).

Случай — файл `kniga/cases/NNN-имя.json`. Что в нём и как добавить новый —
`kniga/README.md`. Виды проверки (поле «проверка»):

1. «разбор» — страницы сайта, сохранённые срезом сбора (`kniga/slices/`),
   разбираются ТЕМ ЖЕ `parse_live.py`, что на GitHub, с часами,
   остановленными на моменте сбора (часть разборщиков считает дни от
   «сегодня»). Ждём в поле «ждём» список:
   - {"игра": "Дом - Гости", "время": "ГГГГ-ММ-ДД ЧЧ:ММ", "канал": …,
     "сайт": …} — игра есть (пара — тем же сравнением, что у разбора,
     `canon._pair_score` ≥ 85, пол и возраст обязаны совпасть), начало
     ±10 мин, у неё есть канал с этого сайта;
   - {"снято": "Дом - Гости", "сайт": …, "время": …} — строка сайта снята
     фильтром (раздел «снято» в games.json), на витрину не попала;
   - {"нет": "Дом - Гости", "время": …, "сайт": …} — такой игры (±3 ч) на
     витрине нет; с «сайт» — нет у игры канала этого сайта.
2. «ссылка» — кнопка ↗: `app/channel_page.link` с настоящими шаблонами
   `data/channel_pages.json` и часами случая даёт ровно ожидаемый адрес.
3. «тест» — случай охраняет готовый тест `scripts/test_*.py` (данные в нём
   самом): зелёный, если тест вышел с кодом 0.

Итог — одна строка («книга: 12 случаев, все зелёные»); красный случай
печатается с причиной и ближайшими кандидатами. Код выхода 1 — есть красные.

В сеть не ходит. Запуск:
    python scripts/kniga.py                  # вся книга
    python scripts/kniga.py --case 4         # один случай
    python scripts/kniga.py --list           # оглавление для владельца
    python scripts/kniga.py --cut <папка артефакта> --name <срез> \
        --domains teleman.pl,raiplay.it --days 2026-10-13,2026-10-14 \
        --clock "2026-10-13 13:46" --what "сбор #249"   # нарезать срез
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "kniga"
CASES = BOOK / "cases"
SLICES = BOOK / "slices"
sys.path.insert(0, str(ROOT))

#: допуск начала игры против ожидаемого (сетка ставит блок чуть раньше)
ДОПУСК_МИН = 10
#: «нет такой игры»: ищем в этом окне вокруг ожидаемого времени
ОКНО_НЕТ_Ч = 3
#: пара та же — как у разбора (`parse_live`, склейка с эталоном)
ПОРОГ_ПАРЫ = 85
#: справочники эталона: их страницы идут в срез за выбранные дни всегда
ЭТАЛОН = ("flashscore", "eredmenyek.com", "rezultati.com")
#: тест дольше — завис (самый долгий, test_watch, идёт ~40 с)
ТЕСТ_ТАЙМАУТ_С = 600

ВИДЫ = ("разбор", "ссылка", "тест")

#: часы для тестов и для разбора срезов. Тесты писаны под киевские часы
#: (сервер и компьютер владельца), а на GitHub часы UTC — test_friend там
#: ронял 3 проверки (проверка ветки 13.10). Разбор — как на GitHub, где сбор
#: и разбирался: UTC. Windows имя «Europe/Kyiv» в TZ не понимает (часы
#: сбиваются), а его машина и так киевская — там TZ для тестов не ставим,
#: для разбора — «UTC0» (формат, понятный и Windows, и Linux)
TEST_CLOCK = {} if os.name == "nt" else {"TZ": "Europe/Kyiv"}
PARSE_CLOCK = {"TZ": "UTC0"}


def bare(domain: str) -> str:
    return (domain or "").lower().removeprefix("www.").removeprefix("m.")


def kyiv(text: str) -> datetime:
    """«2026-10-13 18:55» или «2026-10-13T18:55» → наивное киевское время."""
    return datetime.fromisoformat(text.strip().replace(" ", "T")[:16])


# --- случаи ---------------------------------------------------------------

def load_cases() -> list[dict]:
    """Все случаи по номерам. Ошибка в файле случая — красный случай, а не
    падение всей книги: сломанная запись тоже должна быть видна."""
    cases = []
    for path in sorted(CASES.glob("*.json")):
        try:
            case = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError as e:
            case = {"номер": path.stem, "суть": path.name,
                    "ошибка_файла": f"битый JSON: {e}"}
        case["_файл"] = path.name
        cases.append(case)
    return cases


def case_problems(case: dict, slices: set[str]) -> list[str]:
    """Что не так с записью случая (до всякой проверки)."""
    if case.get("ошибка_файла"):
        return [case["ошибка_файла"]]
    out = [f"нет поля «{k}»" for k in ("номер", "дата", "вид", "суть", "проверка")
           if not case.get(k)]
    вид = case.get("проверка")
    if вид and вид not in ВИДЫ:
        out.append(f"проверка «{вид}» — неизвестная (знаю: {', '.join(ВИДЫ)})")
    if вид == "тест" and case.get("ждём"):
        # «ждём» у теста ничего не проверяет, но оправдывал бы потери на
        # сборе (`proverka.explained`) — так нельзя
        out.append("у случая-теста не бывает «ждём»")
    if вид == "разбор":
        if case.get("срез") not in slices:
            out.append(f"среза «{case.get('срез')}» нет в kniga/slices/")
        if not case.get("ждём"):
            out.append("пустое «ждём» — нечего проверять")
        сайты = set()
        if case.get("срез") in slices:
            meta = slice_meta(case["срез"])
            if not meta:
                out.append(f"у среза {case['срез']} нет описания {case['срез']}.json")
            сайты = {bare(s) for s in meta.get("сайты") or []}
        for exp in case.get("ждём") or []:
            if not ("нет" in exp or "снято" in exp):
                continue
            # «нет»/«снято» без времени и сайта или про сайт, которого в
            # срезе нет, зелены при любом коде — и оправдывали бы потери
            if not exp.get("время") or not exp.get("сайт"):
                out.append(f"у «нет»/«снято» обязательны «время» и «сайт»: {exp}")
            elif сайты and bare(exp["сайт"]) not in сайты:
                out.append(f"сайта {exp['сайт']} нет в срезе {case['срез']}: {exp}")
    if вид == "ссылка" and not case.get("ждём"):
        out.append("пустое «ждём» — нечего проверять")
    if вид == "тест":
        for name in case.get("тесты") or []:
            if not (ROOT / "scripts" / name).exists():
                out.append(f"теста {name} нет в scripts/")
        if not case.get("тесты"):
            out.append("нет поля «тесты»")
    return out


# --- срезы: нарезка и разбор ----------------------------------------------

def slice_meta(name: str) -> dict:
    """Описание среза (`<срез>.json`); нет файла — пусто."""
    path = SLICES / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def cut(folder: Path, name: str, domains: list[str], days: list[str],
        clock: str, what: str) -> Path:
    """Срез из папки артефакта (`github_run.py fetch --run N`): строки отчёта
    выбранных сайтов + эталон flashscore всех языков, только за выбранные
    дни (строки без дня — целиком), страницы — в zip рядом с описанием."""
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    want = {bare(d) for d in domains}
    # страница «сегодня» у многих сайтов держит и дни вперёд (digisport.ro —
    # всю неделю одной страницей) и помечена днём сбора: у выбранных сайтов
    # её берём всегда, иначе срез на 25.10 вышел без digisport (#7400, 21.10)
    сбор = (clock or "")[:10]
    keep = []
    for row in report["строки"]:
        b = bare(row["domain"])
        if b not in want and not any(e in b for e in ЭТАЛОН):
            continue
        if days and row.get("day") and row["day"] not in days \
                and not (b in want and row["day"] == сбор):
            continue
        keep.append(row)
    SLICES.mkdir(parents=True, exist_ok=True)
    out = SLICES / f"{name}.zip"
    small = dict(report, строки=keep)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("report.json", json.dumps(small, ensure_ascii=False, indent=1))
        for row in keep:
            if row.get("файл") and (folder / row["файл"]).exists():
                z.write(folder / row["файл"], row["файл"])
    window = 6
    try:
        window = int(json.loads((folder / "games.json").read_text(
            encoding="utf-8")).get("окно") or 6)
    except (OSError, ValueError):
        pass
    meta = {"срез": name, "откуда": what, "часы_utc": clock, "окно": window,
            "сайты": sorted(want), "дни": days, "строк": len(keep)}
    (SLICES / f"{name}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"срез {name}: строк {len(keep)}, архив {out.stat().st_size // 1024} КБ")
    return out


def frozen_parse(folder: str, clock_utc: str, window: int, out: str) -> int:
    """Разбор среза ТЕМ ЖЕ `parse_live.main`, с часами на моменте сбора.
    Зовётся в отдельном процессе (`--_parse`): у разбора свои глобальные
    словари, и случаи не должны видеть друг друга."""
    import time_machine
    os.environ["STREAMS_DB"] = str(Path(out) / "none.db")   # без локальной базы
    sys.path.insert(0, str(ROOT / "scripts"))
    import parse_live
    moment = datetime.fromisoformat(clock_utc.replace(" ", "T")).replace(
        tzinfo=timezone.utc)
    sys.argv = ["parse_live.py", "--dir", folder, "--days", str(window),
                "--md", str(Path(out) / "matches.md")]
    with time_machine.travel(moment, tick=False):
        return parse_live.main()


def parse_slice(name: str, workdir: Path) -> tuple[dict | None, str]:
    """Распаковать срез и разобрать. → (games.json, журнал разбора)."""
    meta = slice_meta(name)
    pages = workdir / name / "pages"
    out = workdir / name / "out"
    pages.mkdir(parents=True)
    out.mkdir(parents=True)
    with zipfile.ZipFile(SLICES / f"{name}.zip") as z:
        z.extractall(pages)
    # часы — как у разбора на GitHub (UTC), где сбор и разбирался
    env = dict(os.environ, PYTHONIOENCODING="utf-8", STREAMS_DB=str(out / "none.db"),
               **PARSE_CLOCK)
    run = subprocess.run(
        [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--_parse",
         str(pages), "--clock", meta["часы_utc"], "--window", str(meta["окно"]),
         "--out", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(ROOT), timeout=ТЕСТ_ТАЙМАУТ_С)
    log = run.stdout + run.stderr
    games = out / "games.json"
    if run.returncode not in (0, 2) or not games.exists():
        return None, log
    return json.loads(games.read_text(encoding="utf-8")), log


# --- ожидания «разбора» ---------------------------------------------------

def _pair(text: str) -> tuple[str, str]:
    home, _, away = text.partition(" - ")
    return home.strip(), away.strip()


def pair_score(game: dict, text: str) -> int:
    from app import canon
    home, away = _pair(text)
    return canon._pair_score(game, {"home": home, "away": away})


def _has_channel(game: dict, канал: str, сайт: str) -> bool:
    for e in game.get("entries") or []:
        if сайт and bare(e.get("source") or "") != bare(сайт):
            continue
        if канал and (e.get("channel") or "").casefold() != канал.casefold():
            continue
        return True
    return False


def _show(game: dict) -> str:
    chans = ", ".join(f"{e.get('channel')}/{bare(e.get('source') or '')}"
                      for e in (game.get("entries") or [])[:6])
    return (f"{game['start_kyiv'].replace('T', ' ')} {game['home']} — "
            f"{game['away']} [{chans}]")


def check_expect(games: dict, exp: dict) -> str:
    """Пусто — ожидание выполнено; иначе — почему нет."""
    all_games = games.get("games") or []
    if "игра" in exp:
        when = kyiv(exp["время"]) if exp.get("время") else None
        same = [g for g in all_games if pair_score(g, exp["игра"]) >= ПОРОГ_ПАРЫ]
        if when:
            same = [g for g in same
                    if abs(kyiv(g["start_kyiv"]) - when) <= timedelta(minutes=ДОПУСК_МИН)]
        if not same:
            near = sorted(all_games, key=lambda g: -pair_score(g, exp["игра"]))[:3]
            return (f"нет игры «{exp['игра']}» {exp.get('время', '')}; "
                    f"ближе всех: " + "; ".join(_show(g) for g in near))
        if exp.get("канал") or exp.get("сайт"):
            if not any(_has_channel(g, exp.get("канал", ""), exp.get("сайт", ""))
                       for g in same):
                return (f"игра есть, но без «{exp.get('канал', '')}» от "
                        f"{exp.get('сайт', 'любого сайта')}: " + _show(same[0]))
        return ""
    if "снято" in exp:
        home, away = _pair(exp["снято"])
        for x in games.get("снято") or []:
            if exp.get("сайт") and bare(x.get("домен") or "") != bare(exp["сайт"]):
                continue
            if exp.get("время") and kyiv(x["start_kyiv"]) != kyiv(exp["время"]):
                continue
            title = (x.get("заголовок") or "").casefold()
            if home.casefold() in title and away.casefold() in title:
                return ""
        return (f"строка «{exp['снято']}» {exp.get('время', '')} от "
                f"{exp.get('сайт', '?')} не снята фильтром")
    if "нет" in exp:
        when = kyiv(exp["время"])
        for g in all_games:
            if abs(kyiv(g["start_kyiv"]) - when) > timedelta(hours=ОКНО_НЕТ_Ч):
                continue
            if pair_score(g, exp["нет"]) < ПОРОГ_ПАРЫ:
                continue
            if exp.get("сайт") and not _has_channel(g, "", exp["сайт"]):
                continue
            return f"на витрине есть то, чего быть не должно: {_show(g)}"
        return ""
    return f"не понимаю ожидание {exp}"


# --- ссылка ↗ -------------------------------------------------------------

def check_link(exp: dict) -> str:
    import time_machine
    from app import channel_page
    moment = datetime.fromisoformat(exp["часы_utc"].replace(" ", "T")).replace(
        tzinfo=timezone.utc)
    with time_machine.travel(moment, tick=False):
        got = channel_page.link(exp.get("адрес_отметки"), domain=exp["сайт"],
                                base_url=exp.get("адрес_источника", ""),
                                start_kyiv=exp["время"], tz=exp.get("пояс"),
                                channel=exp["канал"])
    if got != exp["ссылка"]:
        return f"↗ {exp['канал']} ({exp['сайт']}, {exp['время']}): «{got}» вместо «{exp['ссылка']}»"
    return ""


# --- тесты ----------------------------------------------------------------

#: исход теста: зелёный — код 0; жёлтый — упали ТОЛЬКО замеры скорости
#: (в имени проверки «скорость:»: время зависит от машины, на ноутбуке и на
#: GitHub разное) — пишется в итог, но выкладку не держит; красный — прочее
ЗЕЛЁНЫЙ, ЖЁЛТЫЙ, КРАСНЫЙ = "зелёный", "жёлтый", "красный"
СКОРОСТЬ = "скорость:"
_tests: dict[str, tuple[str, str]] = {}


def red_lines(log: str) -> list[str]:
    """Строки упавших проверок в выводе теста (у тестов два вида пометки)."""
    return [ln.strip() for ln in log.splitlines()
            if ln.strip().startswith(("✗", "✖", "красная:", "Traceback"))]


def verdict(returncode: int, log: str) -> str:
    if returncode == 0:
        return ЗЕЛЁНЫЙ
    bad = red_lines(log)
    if bad and all(СКОРОСТЬ in ln for ln in bad):
        return ЖЁЛТЫЙ
    return КРАСНЫЙ


def run_test(name: str) -> tuple[str, str]:
    """Один тест в своём процессе, без локальной базы. → (исход, вывод).
    Кэш — на прогон: тест, на который ссылаются несколько случаев, идёт раз."""
    if name in _tests:
        return _tests[name]
    tmp = tempfile.mkdtemp(prefix="kniga-test-")
    # журнал посещений — во временную папку, а не в data/ репозитория
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               STREAMS_DB=str(Path(tmp) / "none.db"), STREAMS_VISITS_DIR=tmp)
    env.update(TEST_CLOCK)
    try:
        run = subprocess.run([sys.executable, "-X", "utf8", f"scripts/{name}"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", env=env, cwd=str(ROOT),
                             timeout=ТЕСТ_ТАЙМАУТ_С)
        log = run.stdout + run.stderr
        result = (verdict(run.returncode, log), log)
    except subprocess.TimeoutExpired:
        result = (КРАСНЫЙ, f"завис дольше {ТЕСТ_ТАЙМАУТ_С} с")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _tests[name] = result
    return result


def failed_lines(log: str) -> str:
    """Причина для итога: упавшие проверки, иначе последняя строка вывода."""
    bad = red_lines(log)
    if bad:
        return "; ".join(bad[:4])
    tail = log.strip().splitlines()
    return tail[-1] if tail else "нет вывода"


# --- прогон ---------------------------------------------------------------

def title(case: dict) -> str:
    return f"{int(case['номер']):03d} {case.get('дата', '')} {case.get('вид', '')}: {case.get('суть', '')}" \
        if str(case.get("номер", "")).isdigit() else f"{case.get('номер')} {case.get('суть', '')}"


def run_book(only: int | None = None) -> tuple[int, list[str], list[str]]:
    """→ (число случаев, красные, жёлтые). Печатает строку на случай."""
    cases = load_cases()
    if only is not None:
        cases = [c for c in cases if str(c.get("номер")) == str(only)]
    slices = {p.stem for p in SLICES.glob("*.zip")}
    numbers = [str(c.get("номер")) for c in cases]
    red: list[str] = []
    yellow: list[str] = []
    if len(set(numbers)) != len(numbers):
        red.append("в книге повторяются номера случаев: " + ", ".join(
            sorted({n for n in numbers if numbers.count(n) > 1})))
        print("❌ " + red[-1])
    parsed: dict[str, tuple[dict | None, str]] = {}
    workdir = Path(tempfile.mkdtemp(prefix="kniga-"))
    try:
        for case in cases:
            why = case_problems(case, slices)
            warn: list[str] = []
            if not why and case["проверка"] == "разбор":
                name = case["срез"]
                if name not in parsed:
                    parsed[name] = parse_slice(name, workdir)
                games, log = parsed[name]
                if games is None:
                    why = ["разбор среза упал: " + log.strip()[-400:]]
                else:
                    why = [w for w in (check_expect(games, e) for e in case["ждём"]) if w]
            elif not why and case["проверка"] == "ссылка":
                why = [w for w in (check_link(e) for e in case["ждём"]) if w]
            elif not why and case["проверка"] == "тест":
                for name in case["тесты"]:
                    status, log = run_test(name)
                    if status == КРАСНЫЙ:
                        why.append(f"{name}: {failed_lines(log)}")
                    elif status == ЖЁЛТЫЙ:
                        warn.append(f"{name}: {failed_lines(log)}")
            mark = "❌" if why else ("🟡" if warn else "✅")
            print(f"{mark} {title(case)}")
            for w in why + warn:
                print(f"     ✗ {w}")
            if why:
                red.append(title(case))
            elif warn:
                yellow.append(title(case))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return len(cases), red, yellow


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", type=int, help="только этот номер")
    ap.add_argument("--list", action="store_true", help="оглавление книги")
    ap.add_argument("--cut", help="папка артефакта, из которой нарезать срез")
    ap.add_argument("--name", help="имя среза (латиницей: sbor-249-teleman)")
    ap.add_argument("--domains", default="", help="сайты среза через запятую")
    ap.add_argument("--days", default="", help="дни среза через запятую (ГГГГ-ММ-ДД)")
    ap.add_argument("--clock", help="момент сбора по UTC «ГГГГ-ММ-ДД ЧЧ:ММ»")
    ap.add_argument("--what", default="", help="откуда срез: «сбор #249, 13.10»")
    ap.add_argument("--_parse", help=argparse.SUPPRESS)
    ap.add_argument("--window", type=int, default=6, help=argparse.SUPPRESS)
    ap.add_argument("--out", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args._parse:
        return frozen_parse(args._parse, args.clock, args.window, args.out)
    if args.cut:
        if not (args.name and args.domains and args.clock):
            print("для --cut нужны --name, --domains и --clock")
            return 1
        cut(Path(args.cut), args.name, args.domains.split(","),
            [d for d in args.days.split(",") if d], args.clock, args.what)
        return 0
    if args.list:
        for case in load_cases():
            print(f"{title(case)}  [{case.get('проверка', '?')}]")
        return 0
    total, red, yellow = run_book(args.case)
    print("\n" + summary(total, red, yellow))
    return 1 if red or not total else 0


def summary(total: int, red: list[str], yellow: list[str]) -> str:
    """Одна строка итога — она и идёт владельцу."""
    if not total:
        return "книга: 0 случаев — нечего проверять (номер не тот? папка пуста?)"
    if red:
        return f"книга: {total} случаев, КРАСНЫХ {len(red)} — выкладывать нельзя"
    if yellow:
        return (f"книга: {total} случаев, зелёные; жёлтых {len(yellow)} — "
                "сорвался только замер скорости")
    return f"книга: {total} случаев, все зелёные"


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
r"""Проверка перед выкладкой — одной командой (книга случаев, владелец
13.10.2026: «чтоб новое не ломало старое»). Красный итог — в main не
выкладывать. Правила по порядку:

1. Все тесты `scripts/test_*.py` — каждый в своём процессе, без локальной
   базы. Упал только замер скорости («скорость:» в имени) — жёлтый: пишется,
   но не держит (время зависит от машины).
2. Каждый тест записан хотя бы в один случай книги (`kniga/cases`): новая
   возможность без случая в книге — красный («добавь случай»).
3. Книга случаев (`scripts/kniga.py`) — все случаи зелёные.
4. С `--sravnit <папка сбора>` — последний сбор разбирается старым кодом
   (`--base`; на GitHub — общий предок ветки и main) и новым, с часами на
   моменте сбора. Новое и изменённое — печатается. Та же игра узнаётся по
   паре или по каналам (переименование), переезд во времени (до 3 ч) —
   только если ближе к эталону, двойня, склеенная в прежнюю игру, — не
   потеря. ПОТЕРЯ (у игры пропал канал; пропала игра = пропали все её
   каналы) — красный, если каждый пропавший канал не объясняет случай книги
   на сохранённых страницах с «нет» или «снято» (та же пара ±3 ч, тот же
   сайт): задуманное снятие сперва пишется в книгу.

В сеть не ходит (сбор берётся готовым: `github_run.py fetch --run N`).
    python scripts/proverka.py                     # тесты + книга, ~3 мин
    python scripts/proverka.py --sravnit recon/raw_live --base origin/main
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import kniga  # noqa: E402
from app import broadcast, live  # noqa: E402

#: разбор полного сбора идёт 6–9 минут; дольше — завис
РАЗБОР_ТАЙМАУТ_С = 40 * 60

# разбор чужим (старым) деревом: его parse_live зовём как есть, часы стоят
_PARSE_AT = r"""
import os, runpy, sys, time_machine
from datetime import datetime, timezone
tree, folder, clock, window, out = sys.argv[1:6]
sys.path[:0] = [tree, os.path.join(tree, "scripts")]
os.chdir(tree)
moment = datetime.fromisoformat(clock.replace(" ", "T")).replace(tzinfo=timezone.utc)
sys.argv = ["parse_live.py", "--dir", folder, "--days", window,
            "--md", os.path.join(out, "matches.md")]
with time_machine.travel(moment, tick=False):
    try:
        runpy.run_path(os.path.join(tree, "scripts", "parse_live.py"), run_name="__main__")
    except SystemExit as e:
        sys.exit(e.code)
"""


# --- 1–2. тесты -----------------------------------------------------------

def all_tests() -> list[str]:
    return sorted(p.name for p in (ROOT / "scripts").glob("test_*.py"))


def run_tests() -> tuple[list[str], list[str]]:
    """→ (красные, жёлтые). По очереди, не разом: параллельный прогон грузит
    машину, и замеры скорости ложно желтеют."""
    red, yellow = [], []
    for name in all_tests():
        status, log = kniga.run_test(name)
        mark = {kniga.ЗЕЛЁНЫЙ: "✅", kniga.ЖЁЛТЫЙ: "🟡"}.get(status, "❌")
        print(f"{mark} {name}")
        if status != kniga.ЗЕЛЁНЫЙ:
            print(f"     ✗ {kniga.failed_lines(log)}")
        if status == kniga.КРАСНЫЙ:
            red.append(name)
        elif status == kniga.ЖЁЛТЫЙ:
            yellow.append(name)
    return red, yellow


def tests_without_case() -> list[str]:
    """Правило 2: тест, на который не ссылается ни один случай книги."""
    used = set()
    for case in kniga.load_cases():
        used.update(case.get("тесты") or [])
    return [t for t in all_tests() if t not in used]


# --- 4. старый и новый код на последнем сборе ------------------------------

def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout.strip()


def parse_with(tree: Path, folder: Path, clock: str, window: int, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    # часы — как у разбора на GitHub (UTC), где этот сбор и разбирался
    env = dict(os.environ, PYTHONIOENCODING="utf-8", STREAMS_DB=str(out / "none.db"),
               **kniga.PARSE_CLOCK)
    run = subprocess.run([sys.executable, "-X", "utf8", "-c", _PARSE_AT, str(tree),
                          str(folder), clock, str(window), str(out)],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env, timeout=РАЗБОР_ТАЙМАУТ_С)
    (out / "log.txt").write_text(run.stdout + run.stderr, encoding="utf-8")
    games = out / "games.json"
    if not games.exists():
        raise RuntimeError(f"разбор кодом {tree} упал: "
                           + (run.stdout + run.stderr).strip()[-600:])
    return json.loads(games.read_text(encoding="utf-8"))


def _key(g: dict) -> tuple:
    return (g["start_kyiv"], g["home"], g["away"])


def _chans(g: dict) -> set:
    return {(e.get("channel") or "", kniga.bare(e.get("source") or ""))
            for e in g.get("entries") or []}


def _rows(g: dict) -> set:
    """Строки сайтов игры: (канал, сайт, время строки)."""
    return {(e.get("channel") or "", kniga.bare(e.get("source") or ""), e.get("start_kyiv") or "")
            for e in g.get("entries") or []}


def row_host(row: tuple, games) -> dict | None:
    """Книга 178: игра нового разбора, при которой стоит ТА ЖЕ строка сайта —
    тот же канал того же сайта с тем же временем строки. Правило К4
    (`broadcast.team_tie`) переводит строку турнира без пары к матчу эталона
    («Davis Cup — tournament» 16:58 → «Italy — Czech Republic»), а вторая за
    вечер строка канала входит в строку турнира и дальше `СДВИГ_Ч`
    (oneplay.cz ČT2 20:30 → «Davis Cup — tournament» 17:00). Строка на
    витрине, при другой игре, — это не пропажа. Спрашивается только для
    тенниса: там строка турнира без пары и матч — один и тот же показ."""
    return next((g for g in games if row in _rows(g)), None)


def rows_moved(gone: dict, games) -> list[dict]:
    """Книга 178: игры нового разбора, куда перешли ВСЕ строки пропавшей
    теннисной игры (`row_host`); хоть одна строка не нашлась — пусто."""
    if gone.get("sport") != "T" or not _rows(gone):
        return []
    hosts = [row_host(row, games) for row in sorted(_rows(gone))]
    return hosts if all(h is not None for h in hosts) else []


def tie_channel(ch: str, site: str, was: dict, games) -> dict | None:
    """Книга 181: встреча командного турнира нового разбора, при которой
    стоит канал `ch` сайта `site` строки этого турнира без пары `was`.
    Поздние строки встречи (вторая игра, пара: «FINAL 8 - MEIA-FINAL» 18:59
    и 20:59 при встрече 17:00) разбор сажает к матчу (`broadcast.team_tie`,
    К5), а вторую строку того же канала у матча снимает
    `one_row_per_channel` — канал на витрине остался, при матче. Правила:
    `was` — теннис, строка турнира (`broadcast.SESSION`); игра нового
    разбора несёт метку встречи ЭТОГО турнира (`broadcast.TIE`), канал сайта
    у неё есть, и `was` начинается в её часы (`broadcast.tie_show`)."""
    if was.get("sport") != "T" or was.get("away") != broadcast.SESSION:
        return None
    try:
        start = datetime.fromisoformat(was.get("start_kyiv") or "")
    except ValueError:
        return None
    for g in games:
        if g.get(broadcast.TIE) != was.get("home") or (ch, site) not in _chans(g):
            continue
        try:
            kickoff = datetime.fromisoformat(g.get("start_kyiv") or "")
        except ValueError:
            continue
        if broadcast.tie_show(kickoff, start):
            return g
    return None


_MARKERS: list = []


def studio_start(game: dict) -> bool:
    """Книга 182: начало игры нового разбора — это время её строки-студии
    (в заголовке строки слово студии, `live.studio_cut`). Студию, внутри
    которой идёт матч, разбор берёт показом матча (`pipeline.studio_inside`);
    она начинается раньше матча, и игра, к которой она пришла, встаёт на её
    время («Crna Gora U17 — Čile U17» 16:50 → «Montenegro U17 — Chile U17»
    16:30: первой стала строка alkass.net «Mondial Studio 2 / Montenegro ×
    Chile»). Игра при этом не переезжала."""
    if not _MARKERS:
        _MARKERS.append(live.load())
    return any(e.get("start_kyiv") == game.get("start_kyiv")
               and live.studio_cut(_MARKERS[0], e.get("raw_title") or "")
               for e in game.get("entries") or [])


def _most_channels(old: set, new: set) -> bool:
    """Большинство каналов старой игры при новой — не меньше двух и не
    меньше половины. Имя игры сменилось, а один канал ушёл — это
    переименование с потерей канала, не пропажа всей игры (книга 094: студия
    programme-tv больше не пара, 7 из 8 каналов на месте). Потерю канала
    сверка покажет отдельно и спросит с книги."""
    common = old & new
    return len(common) >= 2 and 2 * len(common) >= len(old)


def explained(game: dict, site: str) -> str:
    """Номер случая книги, который объясняет потерю канала сайта `site` у
    этой игры: «нет»/«снято» с той же парой ±3 ч и тем же сайтом. Берутся
    только случаи на сохранённых страницах («разбор»): их «нет»/«снято»
    книга сама проверяет, и они не зелены при любом коде."""
    when = kniga.kyiv(game["start_kyiv"])
    for case in kniga.load_cases():
        if case.get("проверка") != "разбор":
            continue
        for exp in case.get("ждём") or []:
            text = exp.get("нет") or exp.get("снято")
            if not text or not exp.get("время") or not exp.get("сайт"):
                continue
            if kniga.bare(exp["сайт"]) != site:
                continue
            if abs(kniga.kyiv(exp["время"]) - when) > timedelta(hours=kniga.ОКНО_НЕТ_Ч):
                continue
            if kniga.pair_score(game, text) >= kniga.ПОРОГ_ПАРЫ:
                return str(case.get("номер"))
    return ""


#: та же пара сдвинулась во времени не дальше этого — переезд, а не потеря,
#: если новое время ближе к эталону (сбор #249: Al Ittihad — Al Shabab
#: 19:55 → 20:55 при эталоне 21:00); дальше от эталона — ошибка пояса
СДВИГ_Ч = 3


def _same_pair(one: dict, two: dict) -> bool:
    from app import canon, reference
    pair = {"home": two["home"], "away": two["away"]}
    if canon._pair_score(one, pair) >= kniga.ПОРОГ_ПАРЫ:
        return True
    # метки из эталона (правило 5 `Reference.confirm`, 24.10): новый код
    # дописывает «W»/«U19» командам, у которых их не было, — старая «Golden
    # State Valkyries — Atlanta Dream» и новая «… W — … W» одна игра. Стена
    # `_pair_score` (моя метка ≠ его → 0) тут не судья: сравниваем без
    # меток, когда у одной игры их нет вовсе, а у другой одна и та же у
    # обеих команд. Мужская при женской с метками у обеих — по-прежнему
    # разные игры, если метки есть у обеих сторон
    mine = {"home": one["home"], "away": one["away"]}
    if not reference._entry_marks(mine) and reference._entry_marks(pair) \
            and not any(reference._marks_of(mine[k]) for k in ("home", "away")):
        bare = {k: reference._strip_marks(pair[k]) for k in ("home", "away")}
        return canon._pair_score(mine, bare) >= kniga.ПОРОГ_ПАРЫ
    if not reference._entry_marks(pair) and reference._entry_marks(mine) \
            and not any(reference._marks_of(pair[k]) for k in ("home", "away")):
        bare = {k: reference._strip_marks(mine[k]) for k in ("home", "away")}
        return canon._pair_score(bare, pair) >= kniga.ПОРОГ_ПАРЫ
    return False


def ref_time(game: dict, refs: list[dict]):
    """Начало того же матча по эталону (±3 ч) или None."""
    when = kniga.kyiv(game["start_kyiv"])
    near = [kniga.kyiv(r["start_kyiv"]) for r in refs
            if r.get("start_kyiv") and r.get("home") and r.get("away")
            and abs(kniga.kyiv(r["start_kyiv"]) - when) <= timedelta(hours=СДВИГ_Ч)
            and _same_pair(game, r)]
    return min(near, key=lambda t: abs(t - when)) if near else None


def _moved_apart(ch: str, site: str, was: dict, fresh: list[dict]) -> dict | None:
    """Новая игра (которой не было в старом разборе), куда ушёл канал `ch`
    сайта `site` старой игры `was`: та же отметка (канал, сайт) не дальше
    СДВИГ_Ч от старого начала. Пара не сравнивается: имя у новой игры может
    быть на другом языке («גולדן סטייט — אטלנטה» у sport5)."""
    when = kniga.kyiv(was["start_kyiv"])
    near = [g for g in fresh if (ch, site) in _chans(g)
            and abs(kniga.kyiv(g["start_kyiv"]) - when) <= timedelta(hours=СДВИГ_Ч)]
    return min(near, key=lambda g: abs(kniga.kyiv(g["start_kyiv"]) - when)) if near else None


def twin(gone: dict, fresh: list[dict], refs: list[dict]) -> tuple[dict | None, str]:
    """Та же игра среди НОВЫХ записей нового разбора:
    «имя» — пара та же (словарь перевёл, сверка поправила) или все каналы
    старой игры при ней (большинство — `_most_channels`), начало ±10 мин;
    «время» — пара та же, начало сдвинулось не дальше СДВИГ_Ч И стало ближе
    к эталону. Уехала дальше от эталона или эталона нет — не переезд;
    «строка» (книга 158) — ВСЕ каналы старой игры при новой, а новое начало
    — это время строки, которая у старой игры уже была (тот же канал того
    же сайта, сдвиг не дальше СДВИГ_Ч): игра не переезжала — у неё ушла
    ранняя строка (студия перед матчем, novasports.gr «Pre Game Show»
    19:30 у игры Арис — Ле-Ман; оставшаяся строка 19:55 стоит, где стояла).
    Ошибку пояса так не спутать: при ней строки сайта меняют время;
    «студия» (книга 182) — ВСЕ каналы старой игры при новой, а новое начало
    — время пришедшей к игре строки-студии, внутри которой идёт матч
    (`studio_start`): игра не переезжала, у неё появилась ранняя строка."""
    when = kniga.kyiv(gone["start_kyiv"])
    # та же пара — или те же каналы: имя игры могло взяться у нового сайта
    # («Olympique de Marsella» у movistarplus вместо «Olympique Marseille»,
    # сбор #249), а все отметки старой игры на месте
    chans = _chans(gone)
    near = sorted((g for g in fresh if _same_pair(gone, g)
                   or (chans and chans <= _chans(g))
                   or _most_channels(chans, _chans(g))),
                  key=lambda g: abs(kniga.kyiv(g["start_kyiv"]) - when))
    kick = ref_time(gone, refs)
    for g in near:
        new_when = kniga.kyiv(g["start_kyiv"])
        shift = abs(new_when - when)
        if shift <= timedelta(minutes=kniga.ДОПУСК_МИН):
            return g, "имя"
        if (shift <= timedelta(hours=СДВИГ_Ч) and kick is not None
                and abs(new_when - kick) < abs(when - kick)):
            return g, "время"
        if shift <= timedelta(hours=СДВИГ_Ч) and chans and chans <= _chans(g) and any(
                e.get("start_kyiv") and kniga.kyiv(e["start_kyiv"]) == new_when
                and (e.get("channel") or "", kniga.bare(e.get("source") or "")) in _chans(g)
                for e in gone.get("entries") or []):
            return g, "строка"
        # «студия» (книга 182) — ВСЕ каналы старой игры при новой, а новое
        # начало — время строки-студии, которая к игре пришла (`studio_start`)
        if shift <= timedelta(hours=СДВИГ_Ч) and chans and chans <= _chans(g) \
                and studio_start(g):
            return g, "студия"
    return None, ""


def absorbed(gone: dict, kept: list[dict]) -> dict | None:
    """Двойня, склеенная в игру, которая была и в старом разборе: та же пара
    ±3 ч (случай 036: дубль Lokomotiv — Krasnodar) — или все каналы
    пропавшей при ней, как у `twin` (20.10: «Айнтрахт Брауншвайг — Хановер»
    nova.bg/novasports.gr вклеилась в «Eintracht Braunschweig — Hannover 96»,
    а кириллица с латиницей буквами 85 не набирает). Её каналы сверяются с
    каналами пропавшей — недостающий канал всё равно потеря."""
    when = kniga.kyiv(gone["start_kyiv"])
    chans = _chans(gone)
    hosts = [g for g in kept if (_same_pair(gone, g) or (chans and chans <= _chans(g)))
             and abs(kniga.kyiv(g["start_kyiv"]) - when) <= timedelta(hours=СДВИГ_Ч)]
    return min(hosts, key=lambda g: abs(kniga.kyiv(g["start_kyiv"]) - when)) if hosts else None


def merged_session(gone: dict, fresh: list[dict]) -> dict | None:
    """Книга 138: показ теннисного турнира без игроков вошёл в НОВУЮ
    сведённую строку турнира («ATP FINALS 2026 — MEIA-FINAL» 15:30 у
    sporttv.pt → «ATP Finals Turin — tournament» 13:00, где этот канал
    стоит рядом с каналами других сайтов). Это не пропажа: строка сессии
    начинается с первого показа. Правила: пропавшая — теннис; новая —
    сведённая трансляция (вторая сторона `broadcast.SESSION`); ВСЕ каналы
    пропавшей стоят при новой; начала не дальше `СДВИГ_Ч` часов."""
    from app import broadcast
    chans = _chans(gone)
    if gone.get("sport") != "T" or not chans:
        return None
    when = kniga.kyiv(gone["start_kyiv"])
    hosts = [g for g in fresh
             if g.get("away") == broadcast.SESSION and chans <= _chans(g)
             and abs(kniga.kyiv(g["start_kyiv"]) - when) <= timedelta(hours=СДВИГ_Ч)]
    return min(hosts, key=lambda g: abs(kniga.kyiv(g["start_kyiv"]) - when)) if hosts else None


def compare(old: dict, new: dict) -> list[str]:
    """Печатает разницу, → потери без объяснения в книге."""
    a = {_key(g): g for g in old.get("games") or []}
    b = {_key(g): g for g in new.get("games") or []}
    refs = new.get("эталон") or []
    print(f"игр: старым кодом {len(a)}, новым {len(b)}")
    losses = []
    pairs = [(a[k], b[k]) for k in sorted(set(a) & set(b))]
    kept = [b[k] for k in sorted(set(a) & set(b))]
    fresh = [b[k] for k in sorted(set(b) - set(a))]
    taken: list[dict] = []     # новые игры, которые уже заняла старая («имя», «время»)
    left: list = []
    for k in sorted(set(a) - set(b)):
        same, how = twin(a[k], fresh, refs)
        if same:
            fresh.remove(same)
            taken.append(same)
            to = (f"{same['home']} — {same['away']}" if how == "имя"
                  else same["start_kyiv"].replace("T", " "))
            print(f"  ~ {how}: {kniga._show(a[k])} → {to}")
            pairs.append((a[k], same))
            continue
        left.append(k)
    for k in left:
        # склеена — в игру, что была и в старом разборе, или в НОВУЮ, которую
        # уже заняла другая старая игра: две старые строки сошлись в одну и
        # та сменила имя («Czarnogóra — Latvija» и «Muntenegru — Letonia» →
        # «Czarnogóra — Letonia», книга 104: без этого вторая считалась
        # пропавшей, хотя её канал стоит при общей игре)
        host = (absorbed(a[k], kept) or absorbed(a[k], taken)
                or merged_session(a[k], fresh))       # книга 138
        if host:
            print(f"  ~ склеена: {kniga._show(a[k])} → {kniga._show(host)}")
            pairs.append((a[k], host))
            continue
        # книга 178: все строки теннисной игры стоят при других играх нового
        # разбора (строка турнира перешла к матчу эталона) — не пропажа
        moved = rows_moved(a[k], list(b.values()))
        if moved:
            print(f"  ~ строки перешли: {kniga._show(a[k])} → {kniga._show(moved[0])}")
            continue
        # книга 181: все каналы пропавшей строки командного турнира стоят
        # при его встрече (поздние строки встречи сели к матчу) — не пропажа
        при_встрече = [tie_channel(ch, site, a[k], list(b.values()))
                       for ch, site in sorted(_chans(a[k]))]
        if при_встрече and all(g is not None for g in при_встрече):
            print(f"  ~ каналы при встрече: {kniga._show(a[k])} → {kniga._show(при_встрече[0])}")
            continue
        # пропала: потеря КАЖДОГО её канала, и каждый сайт объясняется сам —
        # случай про один сайт не оправдывает остальные
        bad = [(ch, site) for ch, site in sorted(_chans(a[k])) if not explained(a[k], site)]
        if bad:
            print(f"  ✗ ПРОПАЛА: {kniga._show(a[k])} — без случая в книге: "
                  + ", ".join(f"{ch}/{site}" for ch, site in bad))
            losses.append(f"пропала игра {kniga._show(a[k])}")
        else:
            cases = sorted({explained(a[k], site) for _, site in _chans(a[k])})
            print(f"  − пропала (так и надо, случай {', '.join(cases)}): {kniga._show(a[k])}")
    for g in fresh:
        print(f"  + новая игра: {kniga._show(g)}")
    for was, now in pairs:
        lost, got = _chans(was) - _chans(now), _chans(now) - _chans(was)
        for ch, site in sorted(got):
            print(f"  + канал {ch}/{site}: {kniga._show(now)}")
        for ch, site in sorted(lost):
            # случай книги написан верными именами, а у старого кода имя
            # могло быть мусорным (094) — спрашиваем книгу и по новым
            why = explained(was, site) or explained(now, site)
            apart = _moved_apart(ch, site, was, fresh)
            # книга 178: та же строка сайта стоит при другой игре нового
            # разбора (строка турнира перешла к матчу эталона) — теннис
            host = None
            if was.get("sport") == "T":
                host = next((h for h in (row_host(row, [g for g in b.values() if g is not now])
                                         for row in sorted(_rows(was)) if row[:2] == (ch, site))
                             if h is not None), None)
            # книга 181: канал строки командного турнира стоит при его встрече
            host = host or tie_channel(ch, site, was, [g for g in b.values() if g is not now])
            if why:
                print(f"  − канал {ch}/{site} снят (случай {why}): {kniga._show(was)}")
            elif apart is not None:
                # канал не потерян — он на витрине отдельной новой игрой (24.10:
                # игра встала на время эталона 01:55, а показ sport5 03:00 вышел
                # за окно склейки и отделился); дубль — не потеря, новая игра
                # уже напечатана выше со знаком «+»
                print(f"  ~ канал {ch}/{site} отделился в новую игру: {kniga._show(apart)}")
            elif host is not None:
                print(f"  ~ канал {ch}/{site} перешёл к игре: {kniga._show(host)}")
            else:
                print(f"  ✗ ПРОПАЛ КАНАЛ {ch}/{site}: {kniga._show(was)}")
                losses.append(f"пропал канал {ch}/{site} у {kniga._show(was)}")
    sa = {(o["домен"], o["заголовок"], o["start_kyiv"]) for o in old.get("снято") or []}
    sb = {(o["домен"], o["заголовок"], o["start_kyiv"]) for o in new.get("снято") or []}
    for x in sorted(sb - sa):
        print(f"  снято теперь (раньше нет): {x[2]} {x[0]} «{x[1][:70]}»")
    for x in sorted(sa - sb):
        print(f"  больше не снимается: {x[2]} {x[0]} «{x[1][:70]}»")
    return losses


#: книга 128: сайт давал не меньше стольких сырых строк…
RAW_BASE = 5
#: …а новым кодом дал меньше этой доли — потеря разборщика
RAW_SHARE = 0.5


def raw_losses(old: dict, new: dict) -> list[str]:
    """Книга 128 — сторож ВСЕХ разборщиков на настоящих страницах сбора
    (тест для разборщиков, у которых своего теста нет): счёт сырых строк по
    сайтам («разобрано» в games.json) старым кодом и новым.
    Правило 1: сайт давал старым кодом не меньше `RAW_BASE` строк, а новым —
    меньше `RAW_SHARE` от прежнего (или ноль) — потеря: правка сломала
    разборщик сайта.
    Правило 2: сайта не было в старом разборе или строк было мало — не судим.
    → строки потерь (как у `compare`)."""
    was = old.get("разобрано") if isinstance(old.get("разобрано"), dict) else {}
    now = new.get("разобрано") if isinstance(new.get("разобрано"), dict) else {}
    out = []
    for site in sorted(was):
        before, after = int(was.get(site) or 0), int(now.get(site) or 0)
        if before >= RAW_BASE and after < before * RAW_SHARE:
            out.append(f"разборщик {site}: строк со страниц было {before}, стало {after}")
    if out:
        print("разборщики сайтов дали заметно меньше строк, чем старым кодом:")
        for line in out:
            print("   " + line)
    return out


def compare_run(folder: Path, base: str, keep: Path | None = None) -> list[str]:
    """Правило 4. → потери без объяснения. `keep` — сохранить оба разбора
    (`old.json`, `new.json`), чтобы сравнить ещё раз без 10 минут разбора:
    `--compare <keep>/old.json <keep>/new.json`."""
    # полный путь: старый код разбирается из своей папки (первый прогон на
    # GitHub упал на относительном «sbor» — старый разбор его не нашёл)
    folder = Path(folder).resolve()
    games = json.loads((folder / "games.json").read_text(encoding="utf-8"))
    clock, window = games["собрано"], int(games.get("окно") or 6)
    sha = _git("rev-parse", "--short", base)
    print(f"\nсбор {folder.name}: часы {clock} UTC, окно {window}; старый код {base} ({sha})")
    tmp = Path(tempfile.mkdtemp(prefix="proverka-"))
    old_tree = tmp / "old"
    _git("worktree", "add", "--detach", str(old_tree), sha)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fo = pool.submit(parse_with, old_tree, folder, clock, window, tmp / "out-old")
            fn = pool.submit(parse_with, ROOT, folder, clock, window, tmp / "out-new")
            old, new = fo.result(), fn.result()
        if keep:
            keep.mkdir(parents=True, exist_ok=True)
            shutil.copy(tmp / "out-old" / "games.json", keep / "old.json")
            shutil.copy(tmp / "out-new" / "games.json", keep / "new.json")
        return compare(old, new) + raw_losses(old, new)
    finally:
        _git("worktree", "remove", "--force", str(old_tree))
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sravnit", help="папка скачанного сбора (report.json, games.json, страницы)")
    ap.add_argument("--base", default="origin/main", help="старый код для сравнения")
    ap.add_argument("--keep", help="сохранить оба разбора сбора в эту папку")
    ap.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"),
                    help="только сравнить два сохранённых разбора (games.json)")
    args = ap.parse_args()

    if args.compare:
        old, new = (json.loads(Path(p).read_text(encoding="utf-8")) for p in args.compare)
        losses = compare(old, new) + raw_losses(old, new)
        print(f"\nпотерь без случая в книге: {len(losses)}")
        return 1 if losses else 0

    print("— тесты —")
    red_tests, yellow_tests = run_tests()
    orphans = tests_without_case()
    print("\n— книга случаев —")
    total, red_cases, yellow_cases = kniga.run_book()
    losses = (compare_run(Path(args.sravnit), args.base,
                          Path(args.keep) if args.keep else None)
              if args.sravnit else [])

    red = []
    if red_tests:
        red.append(f"тесты красные: {', '.join(red_tests)}")
    if orphans:
        red.append(f"тест без случая в книге: {', '.join(orphans)} — добавь случай (kniga/README.md)")
    if red_cases:
        red.append(f"книга: красных {len(red_cases)}")
    if losses:
        red.append(f"на последнем сборе потери без случая в книге: {len(losses)}")
    print()
    for line in red:
        print("✗ " + line)
    yellow = yellow_tests + [y for y in yellow_cases]
    tail = (f"; жёлтые (только скорость): {', '.join(sorted(set(yellow_tests)))}"
            if yellow_tests else "")
    if red:
        print(f"ИТОГ: КРАСНЫЙ — выкладывать нельзя{tail}")
        return 1
    compared = "; старый и новый код на сборе — без потерь" if args.sravnit else ""
    print(f"ИТОГ: зелёный — тестов {len(all_tests())}, {kniga.summary(total, [], yellow_cases)}"
          f"{compared}{tail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

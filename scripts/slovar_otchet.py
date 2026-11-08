# -*- coding: utf-8 -*-
r"""Отчёт по словарю команд — ТОЛЬКО ЧТЕНИЕ (карточка словаря 09.11.2026, шаг 1).

Зачем: решение владельца 08.11 — ничего не удалять, ошибки словаря — в книгу
ошибок, дубли клубов — слить, двусмысленные имена — по языку сайта; 09.11 —
«разобрать максимально всё, чтобы владельца не спрашивать о том, что и так
понятно». Отчёт раскладывает написания по классам и решает каждую пару
«тот же клуб?» уликами из базы. База открывается только для чтения.

    venv/bin/python scripts/slovar_otchet.py            # на экран
    venv/bin/python scripts/slovar_otchet.py --out otchet.md --limit 50

Классы написаний (`team_aliases`, ключ alias+lang) — как в карточке:
  Д  двусмысленное: одно написание ведёт к нескольким РАЗНЫМ клубам;
  П  пара матча записана как имя («A - B», «A – B», «A vs B», «A v B»,
     пробелы по обе стороны — иначе это одна команда `Fleury-Merogis`);
  Л  лига впереди имени («Nogomet: Cibalia») — рабочее написание, оставить;
  К  написание = каноническое имя ДРУГОЙ команды, клубы разные
     (сходство < SAME_CLUB) — коллизия, ведёт матч не туда;
  С  то же, но сходство ≥ SAME_CLUB — одна команда записана дважды? Решает
     правило С6 (ниже), сходство само по себе ничего не решает;
  Дк дубли канонов буква в букву (без регистра) — слияние.

Правило С6 для пары (X, Y), где написание X равно канону Y, по порядку:
  1. виды спорта расходятся (события, `team_sports` из data/dictionaries.json,
     слова-маркеры баскетбола в имени) → «тёзки по виду», не сливать;
  2. стояли в одном событии друг против друга → «разные: играли между собой»;
  3. голое имя Y (его канон лежит написанием у X) тянут ≥ 2 разных X
     (`AEK`, `CSKA`, `Roma`, `Nápoles`) → Д, двусмысленное имя, не сливать;
  4. «эталонная» команда — у которой есть переводы с языком (их пишет
     только сверка с flashscore); имя без них родилось из строки сайта.
     Обе эталонные и страны РАЗНЫЕ → «разные: два клуба эталона»
     (`Al-Faisaly` Саудовская Аравия / `Al Faisaly` Иордания);
  5. имена равны после нормализации (регистр, диакритика, `Łódź`, дефис↔
     пробел, точки), или слова короткого целиком входят в длинное (`Milan` ⊂
     `AC Milan`), или сокращение/инициалы (`Atl.` → Atletico, `PSG`), или
     хвост ` WO` у теннисистов → «сливать точно»; но если обе эталонные и
     страна не подтверждает — только «возможный дубль»;
  6. улики (любая достаточна): один матч эталона `fs:` под двумя именами
     (events.flags одинаковы, та же сторона); общее написание С ЯЗЫКОМ у
     обеих; Y эталону неизвестна и совпавшее написание у X — с языком
     (перевод: `Columbia` ro → Colombia; а `Granada` с переводами — нет);
     Y эталону неизвестна, у неё ≤ 2 написаний и вид не спорит (`Al Taawoun`
     → Al Taawon, `Génova` → Genoa); костяк согласных совпал И одна лига
     (events.league_id); везде страны не должны расходиться →
     «сливать по уликам»;
  7. иначе → «возможный дубль»: оставить двумя командами, в книгу; при
     следующем прогоне улики появятся — сольётся само.

Выживший при слиянии — у кого имя эталона flashscore: больше написаний
С ЯЗЫКОМ (их пишет сверка с эталоном, `canon.py`), при равенстве — больше
событий, затем больше написаний всего, затем короче имя.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "app").exists():              # скрипт запустили вне репо
    ROOT = Path.cwd()
for p in (str(ROOT), os.getcwd()):
    if p not in sys.path:
        sys.path.insert(0, p)

from app import db, names                                   # noqa: E402
from app.dictionary import SAME_CLUB                        # noqa: E402

PAIR_RE = re.compile(r"\S\s+(?:-|–|—|vs\.?|v)\s+\S", re.IGNORECASE)
LEAGUE_RE = re.compile(r"\S:\s+\S")
#: слова в имени, по которым команда — баскетбольная, даже если событий нет
BASKET_WORDS = {"basket", "basketball", "bc", "kk", "bk", "giants", "basquet"}
WO_TAIL = " WO"


def open_ro() -> sqlite3.Connection:
    """База только для чтения: отчёт не имеет права ничего менять."""
    conn = sqlite3.connect(f"file:{db.db_path()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def is_pair(text: str) -> bool:
    return bool(PAIR_RE.search(text or ""))


def is_league_first(text: str) -> bool:
    return bool(LEAGUE_RE.search(text or ""))


#: буквы, которые NFKD не раскладывает: `Łódź` → `lodz`, `Brøndby` → `brondby`
_PLAIN = str.maketrans({"ł": "l", "ø": "o", "đ": "d", "ß": "ss", "æ": "ae", "œ": "oe",
                        "ı": "i", "þ": "th", "ð": "d"})


def norm(name: str) -> str:
    """`Académica` → `academica`, `Al-Sadd` → `al sadd`, `St.mirren` → `st mirren`."""
    folded = unicodedata.normalize("NFKD", name or "")
    plain = "".join(c for c in folded if not unicodedata.combining(c))
    plain = re.sub(r"\([^)]*\)", " ", plain)            # `Fluminense (Bra)`
    plain = plain.casefold().translate(_PLAIN)
    plain = plain.replace("-", " ").replace("/", " ").replace(".", ". ")
    plain = plain.replace(". ", " ")
    return " ".join(plain.split())


def words_inside(short: str, long: str) -> bool:
    a, b = set(norm(short).split()), set(norm(long).split())
    return bool(a) and a <= b


def abbreviated(short: str, long: str) -> bool:
    """Сокращение эталона: каждое слово короткого имени — либо слово длинного,
    либо его начало (`Atl.` → Atletico, `Ath` → Athletic, `Brom` → Bromwich,
    `Chemnitz` → Chemnitzer; начало не короче 3 букв, иначе `Spain` и
    `San Marino` сошлись бы на одной букве). Слова длинного имени могут
    оставаться лишними (`Stade Brestois 29` ⊃ `Brest`). Или короткое — инициалы
    длинного (`PSG` = Paris Saint Germain)."""
    a, b = norm(short).split(), norm(long).split()
    if not a or not b or len(a) > len(b):
        return False
    if len(a) == 1 and 2 <= len(a[0]) <= 4 and len(b) >= 2 \
            and a[0] == "".join(w[0] for w in b if w and not w.isdigit()):
        return True
    rest = list(b)
    for w in a:
        hit = next((x for x in rest if x == w or (len(w) >= 3 and x.startswith(w))), None)
        if hit is None:
            return False
        rest.remove(hit)
    return True


def abbreviated_either(x: str, y: str) -> bool:
    return abbreviated(x, y) or abbreviated(y, x)


#: слова, которыми одно и то же имя клуба отличается от своего короткого вида
CLUB_TOKENS = {"fc", "sc", "cf", "cd", "ud", "cp", "club", "utd", "united", "sad", "os",
               "as", "ac", "fk", "nk", "sk", "hk", "gks", "afc", "cfc", "de", "the", "sv",
               "fsv", "ssv", "tsv", "vfb", "vfl", "bsc", "1", "sport", "sporting", "athletic"}
PLAYER_RE = re.compile(r"\b[A-ZА-ЯЁ]\.$")      # `Osaka N.`, `Preston T.` — теннисист


def only_club_tokens_differ(short: str, long: str) -> bool:
    """`Rangers` / `Rangers FC`, `Sporting` / `Sporting CP` — тот же клуб;
    `Lugano` / `Lugano Tigers`, `Qatar` / `Qatar SC` сюда не попадают (Tigers —
    не клубное слово; сборную ловит `national`)."""
    a, b = set(norm(short).split()), set(norm(long).split())
    return bool(a) and a < b and (b - a) <= CLUB_TOKENS


def is_player(name: str) -> bool:
    return bool(PLAYER_RE.search(name or "")) or "/" in (name or "")


def skeleton(name: str) -> str:
    return names._skeleton(norm(name).upper())


def team_sport_memory() -> dict[str, str]:
    try:
        data = json.loads((ROOT / "data" / "dictionaries.json").read_text(encoding="utf-8"))
        return {k: v for k, v in (data.get("team_sports") or {}).items() if isinstance(v, str)}
    except (OSError, ValueError):
        return {}


def collect(conn: sqlite3.Connection) -> dict:
    teams = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, canonical_name, country FROM teams")}
    by_canon_ci: dict[str, list[int]] = defaultdict(list)
    for tid, t in teams.items():
        by_canon_ci[t["canonical_name"].casefold()].append(tid)

    events: dict[int, int] = defaultdict(int)
    sports: dict[int, set] = defaultdict(set)
    leagues: dict[int, set] = defaultdict(set)
    met: set[tuple[int, int]] = set()
    fs_side: dict[tuple[str, str], set[int]] = defaultdict(set)
    for r in conn.execute("SELECT team_home_id AS a, team_away_id AS b, sport, "
                          "league_id, flags FROM events"):
        for side, tid in (("h", r["a"]), ("a", r["b"])):
            if not tid:
                continue
            events[tid] += 1
            sports[tid].add(r["sport"])
            if r["league_id"]:
                leagues[tid].add(r["league_id"])
            if r["flags"] and str(r["flags"]).startswith("fs:"):
                fs_side[(r["flags"], side)].add(tid)
        if r["a"] and r["b"]:
            met.add((min(r["a"], r["b"]), max(r["a"], r["b"])))
    memory = team_sport_memory()
    #: имя команды = страна какой-то лиги эталона → это сборная
    countries = {norm(r[0]) for r in conn.execute(
        "SELECT DISTINCT country FROM leagues WHERE country IS NOT NULL AND country <> ''")}
    for r in conn.execute("SELECT canonical_name FROM leagues WHERE canonical_name LIKE '%: %'"):
        countries.add(norm(r[0].split(":", 1)[0]))      # `QATAR: Stars League` → qatar

    def national(tid: int) -> bool:
        return norm(teams[tid]["canonical_name"]) in countries

    def sport_of(tid: int) -> set:
        found = set(sports.get(tid, set()))
        name = teams[tid]["canonical_name"]
        if name in memory:
            found.add(memory[name])
        if set(norm(name).split()) & BASKET_WORDS:
            found.add("B")
        return found

    aliases = [dict(r) for r in conn.execute(
        "SELECT alias, lang, team_id FROM team_aliases ORDER BY id")]
    alias_total: dict[int, int] = defaultdict(int)
    alias_lang: dict[int, int] = defaultdict(int)
    owners: dict[str, set[int]] = defaultdict(set)
    owners_nolang: dict[str, set[int]] = defaultdict(set)
    lang_alias_owners: dict[tuple[str, str], set[int]] = defaultdict(set)
    for a in aliases:
        alias_total[a["team_id"]] += 1
        owners[a["alias"]].add(a["team_id"])
        if a["lang"]:
            alias_lang[a["team_id"]] += 1
            lang_alias_owners[(a["alias"], a["lang"])].add(a["team_id"])
        else:
            owners_nolang[a["alias"]].add(a["team_id"])

    def clubs(ids: set[int]) -> int:
        canons = [teams[i]["canonical_name"] for i in ids if i in teams]
        groups: list[list[str]] = []
        for name in canons:
            for g in groups:
                if any(names.similarity(name, o) >= SAME_CLUB for o in g):
                    g.append(name)
                    break
            else:
                groups.append([name])
        return len(groups)

    out: dict = {"команд": len(teams), "написаний": len(aliases),
                 "команд_в_событиях": len(events)}
    out["Д"] = sorted(((al, sorted(teams[i]["canonical_name"] for i in ids if i in teams))
                       for al, ids in owners.items()
                       if len(ids) > 1 and clubs(ids) > 1), key=lambda x: -len(x[1]))
    out["Д_без_языка"] = sum(1 for al, ids in owners_nolang.items()
                             if len(ids) > 1 and clubs(ids) > 1)
    out["П"] = [(a["alias"], a["lang"], teams[a["team_id"]]["canonical_name"])
                for a in aliases if a["team_id"] in teams and is_pair(a["alias"])]
    out["П_каноны"] = [(tid, t["canonical_name"], events.get(tid, 0))
                       for tid, t in teams.items() if is_pair(t["canonical_name"])]
    out["Л"] = sum(1 for a in aliases
                   if is_league_first(a["alias"]) and not is_pair(a["alias"]))

    def score(tid: int) -> tuple:
        return (alias_lang[tid], events.get(tid, 0), alias_total[tid],
                -len(teams[tid]["canonical_name"]))

    # пары (X, Y): написание X равно канону Y
    seen: dict[tuple[int, int], set[str]] = {}   # пара → языки совпавших написаний
    kol: list[tuple] = []
    same: list[tuple[int, int, int]] = []
    for a in aliases:
        tid = a["team_id"]
        if tid not in teams:
            continue
        for other in by_canon_ci.get(a["alias"].casefold(), []):
            if other == tid:
                continue
            key = (min(tid, other), max(tid, other))
            if key in seen:
                if a["lang"]:
                    seen[key].add(a["lang"])
                continue
            seen[key] = {a["lang"]} if a["lang"] else set()
            me, him = teams[tid]["canonical_name"], teams[other]["canonical_name"]
            if is_pair(me) or is_pair(him):          # ложные каноны-пары — класс П
                continue
            sim = names.similarity(me, him)
            if sim >= SAME_CLUB:
                same.append((tid, other, sim))
            else:
                kol.append((a["alias"], a["lang"], me, him, sim))
    out["К"] = sorted(kol, key=lambda x: (x[0], x[1] or ""))

    # п. 3 правила: сколько РАЗНЫХ команд тянут «голое имя» Y (его канон лежит
    # написанием у X) — по ВСЕМ записям, в обе стороны, без склейки пар
    partners: dict[int, set[int]] = defaultdict(set)
    for a in aliases:
        for other in by_canon_ci.get(a["alias"].casefold(), []):
            if other != a["team_id"] and a["team_id"] in teams and other in teams:
                partners[other].add(a["team_id"])

    def ref(tid: int) -> bool:
        """Команду под этим именем знает эталон: есть переводы с языком (их
        пишет только сверка с flashscore). Иначе имя родилось из строки сайта."""
        return alias_lang[tid] > 0

    def shared_lang_alias(x: int, y: int) -> bool:
        return any(x in ids and y in ids for ids in lang_alias_owners.values())

    def same_fs_match(x: int, y: int) -> bool:
        return any(x in ids and y in ids for ids in fs_side.values())

    def decide(x: int, y: int) -> tuple[str, str]:
        nx, ny = teams[x]["canonical_name"], teams[y]["canonical_name"]
        sx, sy = sport_of(x), sport_of(y)
        if sx and sy and not (sx & sy):
            return "тёзки по виду", f"виды {''.join(sorted(sx))}/{''.join(sorted(sy))}"
        if (min(x, y), max(x, y)) in met:
            return "разные: играли между собой", "стояли в одном событии"
        for bare in (y, x):
            if len(partners[bare]) >= 2:
                return "Д: голое имя", (f"«{teams[bare]['canonical_name']}» тянут "
                                       f"{len(partners[bare])} команд")
        cx, cy = teams[x]["country"], teams[y]["country"]
        countries_ok = not cx or not cy or cx == cy
        same_norm = norm(nx) == norm(ny)
        if not same_norm:
            if national(x) != national(y):
                return "разные: сборная и клуб", f"«{nx if national(x) else ny}» — сборная"
            if is_player(nx) != is_player(ny):
                return "разные: игрок и клуб", "инициал или пара игроков только у одного"
        if ref(x) and ref(y) and cx and cy and cx != cy:
            return "разные: два клуба эталона", f"страны {cx}/{cy}, оба с переводами эталона"
        tails = (nx.endswith(WO_TAIL) or ny.endswith(WO_TAIL)
                 or "RETIRED" in nx or "RETIRED" in ny)
        if same_norm or tails:
            return "сливать точно", "имена совпали после нормализации / хвост WO, RETIRED"
        if only_club_tokens_differ(nx, ny) or only_club_tokens_differ(ny, nx):
            return "сливать точно", "разница только в клубных словах (FC, SC, Utd…)"
        wx, wy = norm(nx).split(), norm(ny).split()
        initials = (len(wx) == 1 and len(wy) >= 2 and wx[0] == "".join(w[0] for w in wy)) or \
                   (len(wy) == 1 and len(wx) >= 2 and wy[0] == "".join(w[0] for w in wx))
        if abbreviated_either(nx, ny) and (len(wx) == len(wy) or initials):
            # слово в слово (`Atl. Madrid`/`Atletico Madrid`) или инициалы (`PSG`);
            # `Roma` ⊂ `BC Roma`, `Kuwait` ⊂ `Al Kuwait` — нет, это вхождение (ниже, по уликам)
            return "сливать точно", "сокращение эталона (Atl., Din., Ath, инициалы)"
        if same_fs_match(x, y):
            return "сливать по уликам", "один матч flashscore под двумя именами"
        if shared_lang_alias(x, y):
            return "сливать по уликам", "общее написание с языком"
        contained = words_inside(nx, ny) or words_inside(ny, nx) or abbreviated_either(nx, ny)
        if contained and sx and sy and (sx & sy) and (leagues[x] & leagues[y]):
            return "сливать по уликам", "короткое имя внутри длинного, один вид и одна лига"
        if langs and not ref(y) and countries_ok:
            return "сливать по уликам", f"перевод эталона ({', '.join(sorted(langs))}), «{ny}» эталону неизвестна"
        if not ref(y) and alias_total[y] <= 2 and countries_ok and (not sy or sy == sx):
            return "сливать по уликам", f"«{ny}» родилась из строки сайта и лежит написанием у «{nx}»"
        if skeleton(nx) == skeleton(ny) and (leagues[x] & leagues[y]) and countries_ok:
            return "сливать по уликам", "костяк согласных + одна лига"
        return "возможный дубль", "улик нет — оставить, в книгу"

    buckets: dict[str, list[tuple]] = defaultdict(list)
    for x, y, sim in same:
        langs = seen[(min(x, y), max(x, y))]
        verdict, why = decide(x, y)
        win, lose = (x, y) if score(x) >= score(y) else (y, x)
        buckets[verdict].append((teams[win]["canonical_name"], teams[lose]["canonical_name"],
                                 sim, why))
    out["С6"] = {k: sorted(v) for k, v in buckets.items()}
    out["Дк"] = [[teams[i]["canonical_name"] for i in ids]
                 for ids in by_canon_ci.values() if len(ids) > 1]
    return out


ORDER = ("сливать точно", "сливать по уликам", "возможный дубль", "Д: голое имя",
         "тёзки по виду", "разные: играли между собой", "разные: сборная и клуб",
         "разные: игрок и клуб", "разные: два клуба эталона")


def render(r: dict, limit: int) -> str:
    L: list[str] = []
    w = L.append
    w("# Отчёт по словарю команд (только чтение)\n")
    w("| Что | Сколько |\n|---|---|")
    w(f"| команд | {r['команд']} (в событиях {r['команд_в_событиях']}) |")
    w(f"| написаний | {r['написаний']} |")
    w(f"| Д двусмысленных написаний (разные клубы) | {len(r['Д'])}, без языка {r['Д_без_языка']} |")
    w(f"| П пара как имя | {len(r['П'])} написаний, {len(r['П_каноны'])} канонов |")
    w(f"| Л лига впереди (оставить) | {r['Л']} |")
    w(f"| К коллизии разных клубов | {len(r['К'])} |")
    for k in ORDER:
        w(f"| С6 {k} | {len(r['С6'].get(k, []))} |")
    w(f"| Дк дубли канонов | {len(r['Дк'])} |\n")
    for k in ORDER:
        rows = r["С6"].get(k, [])
        w(f"## С6 — {k} ({len(rows)}), первые {limit}\n")
        w("| Выживший | Проигравший | Сходство | Почему |\n|---|---|---|---|")
        for win, lose, sim, why in rows[:limit]:
            w(f"| {win} | {lose} | {sim} | {why} |")
        w("")
    w(f"## К — коллизии: написание ведёт на чужой клуб, первые {limit}\n")
    w("| Написание | Язык | Ведёт на | А это имя команды | Сходство |\n|---|---|---|---|---|")
    for al, lang, me, him, sim in r["К"][:limit]:
        w(f"| {al} | {lang or '—'} | {me} | {him} | {sim} |")
    w("\n## П — ложные каноны-пары (событий на каждом)\n")
    for tid, name, ev in r["П_каноны"]:
        w(f"- {name} (id {tid}, событий {ev})")
    w(f"\n## Д — двусмысленные, первые {limit}\n")
    for al, canons in r["Д"][:limit]:
        w(f"- {al} → {', '.join(canons)}")
    w("\n## Дк — дубли канонов\n")
    for group in r["Дк"]:
        w(f"- {' / '.join(group)}")
    return "\n".join(L) + "\n"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="", help="записать отчёт в файл (markdown)")
    ap.add_argument("--limit", type=int, default=40, help="строк в каждом списке")
    args = ap.parse_args()
    conn = open_ro()
    try:
        text = render(collect(conn), args.limit)
    finally:
        conn.close()
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"отчёт записан: {args.out} ({text.count(chr(10))} строк)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
r"""Чистка словаря имён — пакет C аудита (14.09.2026).

Разделы (по умолчанию все; выборочно — `--only копии,пол`):

  копии    точные повторы строк алиасов команд и лиг. У `lang=NULL` защита
           UNIQUE(alias, lang) в SQLite не срабатывает, и каждый прогон
           дописывал ту же строку ещё раз — к 14.09 174 тыс. копий на 48 тыс.
           строк. Остаётся последняя запись: порядок «кто новее» не меняется;
  пол      голое имя висит и на взрослой команде, и на юношеской/женской той
           же вывески («ASTON VILLA» → и Aston Villa U19). С чужой категории
           снимается (ГРАБЛИ №10). Своей категории у имени нет — не трогаем:
           лишний W лучше потерянного;
  матчи    в написании весь матч или заголовок сетки: «EVERTON X WOLVERHAMPTON»
           → Everton, «ארצו, מחזור 3», «3a giornata: Catania - Cosenza»;
  чужие    написание буквами явно за один клуб, а висит ещё и на непохожем:
           «מכבי חיפה» → и Maccabi Rishon, «Besiktas» → и Bnei Yehuda. С
           непохожего снимается — кроме эталонной команды, которую обошёл
           старый двойник с транслитом вместо имени («Тулуза» → Tuluza).
           Спорные между похожими («Dinamo» трёх клубов) не удаляются — их не
           отдаёт сам словарь (`dictionary.team_alias_map`);
  лиги     точечные правки, список `LEAGUE_FIXES`;
  команды  точечные правки, список `TEAM_FIXES`: снять с чужой, переложить
           на свою.

`--merge 178:444` — слить команду-двойника в главную (Wolverhampton → Wolves):
написания и игры переезжают, двойник удаляется.

По умолчанию только показывает. `--apply` пишет, `--vacuum` после записи
ужимает файл базы. Построчно — `--report файл`.

На сервере (сначала снимок scripts/db_backup.py):
    venv/bin/python scripts/dict_clean.py --merge 178:444 --report /root/dict_clean.txt
    venv/bin/python scripts/dict_clean.py --merge 178:444 --apply --vacuum
Копия базы локально — переменная STREAMS_DB. К сети не обращается.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import canon, db, dictionary, names  # noqa: E402

SECTIONS = ("копии", "пол", "матчи", "чужие", "лиги", "команды")

#: написание лиги → канон, с которого его снять
LEAGUE_FIXES = (
    # maariv так пишет футбольную Лигу Израиля, а висело и на баскетбольном
    # Кубке — футбол уезжал в баскетбол (#2431, #2510)
    ("ליגת ווינר", "ISRAEL: League Cup"),
    # вторая Лига чемпионов Азии пишется с «2»
    ("ליגת האלופות אסיה", "ASIA: AFC Champions League 2"),
    # «LIGA EUROPE» у Arena Sport — Лига Европы, а не Лига Леумит
    ("LIGA EUROPE", "ISRAEL: Leumit League"),
    # женская лига, а в написании пола нет
    ("Liga angielska", "ENGLAND: WSL"),
    ("efbet Лига", "BULGARIA: Vtora liga"),
)
#: написание команды → с какой снять → на какую переложить (или None). След
#: моста «та же лига + то же время» через «LIGA EUROPE» = Лига Леумит:
#: «Besiktas - Olympique M.» (Arena Sport) легла на Bnei Yehuda — M. Herzliya,
#: и канал Лиги Европы висел на израильской игре. «Olympique M.» у Arena
#: Sport — это Марсель («Olympique M. - PSG», 20.09)
TEAM_FIXES = (
    ("Olympique M", "M. Herzliya", "Marseille"),
)
#: буквы явно за один клуб (CLEAR) — и явно не за другой (ниже FOREIGN)
CLEAR, FOREIGN = 85, 60


def _kind(text: str) -> tuple[str, bool]:
    return names.category(text), "3x3" in text.lower()


def _owners(conn) -> dict[str, list]:
    """Написание → различные (команда, язык) там, где команд две и больше."""
    out: dict[str, list] = {}
    for r in conn.execute(
            "SELECT DISTINCT a.alias, a.lang, a.team_id, "
            "       t.canonical_name AS canon "
            "FROM team_aliases a JOIN teams t ON t.id = a.team_id "
            "WHERE a.alias IN (SELECT alias FROM team_aliases GROUP BY alias "
            "                  HAVING count(DISTINCT team_id) > 1)"):
        out.setdefault(r["alias"], []).append(r)
    return out


def _drop(conn, keys: set, apply: bool) -> int:
    if apply and keys:
        conn.executemany("DELETE FROM team_aliases WHERE team_id = ? "
                         "AND alias = ? AND lang IS ?", sorted(keys, key=str))
    return len(keys)


def copies(conn, apply: bool, log) -> str:
    parts = []
    for table, key in (("team_aliases", "team_id"),
                       ("league_aliases", "league_id")):
        total = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        keep = conn.execute(f"SELECT count(*) FROM (SELECT 1 FROM {table} "
                            f"GROUP BY {key}, alias, lang)").fetchone()[0]
        if apply and total > keep:
            conn.execute(f"DELETE FROM {table} WHERE id NOT IN (SELECT max(id) "
                         f"FROM {table} GROUP BY {key}, alias, lang)")
        parts.append(f"{table} {total} → {keep}")
    return ", ".join(parts)


def gender(conn, apply: bool, log) -> str:
    keys = set()
    for alias, rows in _owners(conn).items():
        mine = _kind(alias)
        if not any(_kind(r["canon"]) == mine for r in rows):
            continue
        for r in rows:
            if _kind(r["canon"]) != mine:
                keys.add((r["team_id"], alias, r["lang"]))
                log(f"пол    {alias!r} — снято с «{r['canon']}»")
    return f"снято {_drop(conn, keys, apply)}"


def matches(conn, apply: bool, log) -> str:
    keys = set()
    for r in conn.execute(
            "SELECT DISTINCT a.alias, a.lang, a.team_id, "
            "       t.canonical_name AS canon "
            "FROM team_aliases a JOIN teams t ON t.id = a.team_id"):
        alias = r["alias"]
        bare = canon.bare_title(alias)
        # лигу и тур в имени оставил заголовок сетки: у иврита (sport5) —
        # всегда, у латиницы — когда внутри осталась ещё и пара
        titled = bare != alias.strip() and (
            canon._script(alias) == "he"
            or any(sep in bare for sep in canon._SEPS))
        if titled or not canon._one_team(alias, r["canon"]):
            keys.add((r["team_id"], alias, r["lang"]))
            log(f"матчи  {alias!r} — снято с «{r['canon']}»")
    return f"снято {_drop(conn, keys, apply)}"


def _official(conn) -> set[int]:
    """Команды с именем эталона flashscore: имя есть в свежем эталоне обхода
    (`results/…/games.json`) или у команды есть написания локалей (lang)."""
    seen: set[str] = set()
    for path in (ROOT / "results" / "games.json",
                 ROOT / "results" / "day" / "games.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in data.get("эталон", []):
            seen.update(x.strip() for x in (r.get("home"), r.get("away")) if x)
    ids = {r[0] for r in conn.execute(
        "SELECT DISTINCT team_id FROM team_aliases WHERE lang IS NOT NULL")}
    ids |= {r[0] for r in conn.execute("SELECT id, canonical_name FROM teams")
            if r[1] in seen}
    return ids


def foreign(conn, apply: bool, log) -> str:
    # буквы без словаря: иначе мусорное написание «похоже» на того, к кому
    # оно уже прилипло
    names.set_overrides({})
    official = _official(conn)
    keys = set()
    for alias, rows in _owners(conn).items():
        mine = _kind(alias)
        own = [r for r in rows if _kind(r["canon"]) == mine]
        score = {r["team_id"]: names.similarity(alias, r["canon"]) for r in own}
        if len(score) < 2 or max(score.values()) < CLEAR:
            continue
        top = max(score.values())
        leaders = [r for r in own if score[r["team_id"]] >= CLEAR]
        for r in own:
            # написания локалей flashscore (lang) — точные, по fs_id; их не трогаем
            if r["lang"] is not None or score[r["team_id"]] >= FOREIGN:
                continue
            # эталонную команду не обделяем в пользу старого двойника, у
            # которого вместо имени транслит: «Тулуза» — это Toulouse, а не
            # Tuluza; «Локомотив София» — Lok. Sofia, а не Lokomotiv Sofia
            if r["team_id"] in official and not any(
                    x["team_id"] in official or x["canon"] == alias
                    for x in leaders):
                log(f"оставлено {alias!r} на «{r['canon']}»: за буквами "
                    f"только двойник {sorted({x['canon'] for x in leaders})}")
                continue
            keys.add((r["team_id"], alias, r["lang"]))
            log(f"чужие  {alias!r} — снято с «{r['canon']}» "
                f"(буквы {score[r['team_id']]} при {top})")
    return f"снято {_drop(conn, keys, apply)}"


def leagues(conn, apply: bool, log) -> str:
    fixed = 0
    for alias, league in LEAGUE_FIXES:
        ids = [r[0] for r in conn.execute(
            "SELECT a.id FROM league_aliases a "
            "JOIN leagues l ON l.id = a.league_id "
            "WHERE a.alias = ? AND l.canonical_name = ?", (alias, league))]
        if not ids:
            continue
        fixed += 1
        log(f"лиги   {alias!r} — снято с «{league}»")
        if apply:
            conn.executemany("DELETE FROM league_aliases WHERE id = ?",
                             [(i,) for i in ids])
    return f"снято написаний {fixed}"


def teams(conn, apply: bool, log) -> str:
    fixed = 0
    for alias, wrong, right in TEAM_FIXES:
        ids = [r[0] for r in conn.execute(
            "SELECT a.id FROM team_aliases a JOIN teams t ON t.id = a.team_id "
            "WHERE a.alias = ? AND t.canonical_name = ?", (alias, wrong))]
        if not ids:
            continue
        fixed += 1
        log(f"команды {alias!r} — снято с «{wrong}»"
            + (f", переложено на «{right}»" if right else ""))
        if apply:
            conn.executemany("DELETE FROM team_aliases WHERE id = ?",
                             [(i,) for i in ids])
            if right and conn.execute("SELECT 1 FROM teams WHERE "
                                      "canonical_name = ?", (right,)).fetchone():
                dictionary.remember_team(conn, alias, right)
    return f"поправлено написаний {fixed}"


def merge(conn, dup: int, main: int, apply: bool, log) -> str:
    d = conn.execute("SELECT id, canonical_name FROM teams WHERE id = ?",
                     (dup,)).fetchone()
    m = conn.execute("SELECT id, canonical_name FROM teams WHERE id = ?",
                     (main,)).fetchone()
    if not d or not m or dup == main:
        return f"пропуск {dup}:{main} — нет такой команды"
    spellings = [(r["alias"], r["lang"]) for r in conn.execute(
        "SELECT DISTINCT alias, lang FROM team_aliases WHERE team_id = ?",
        (dup,))]
    games = conn.execute("SELECT count(*) FROM events WHERE team_home_id = ? "
                         "OR team_away_id = ?", (dup, dup)).fetchone()[0]
    text = (f"«{d['canonical_name']}» #{dup} → «{m['canonical_name']}» "
            f"#{main}: написаний {len(spellings)}, игр {games}")
    log(f"слить  {text}")
    if apply:
        # сперва снять у двойника: UNIQUE(alias, lang) не пустит то же
        # написание с языком второй раз
        conn.execute("DELETE FROM team_aliases WHERE team_id = ?", (dup,))
        for alias, lang in spellings + [(d["canonical_name"], None)]:
            if not conn.execute(
                    "SELECT 1 FROM team_aliases WHERE team_id = ? "
                    "AND alias = ? AND lang IS ?", (main, alias, lang)).fetchone():
                conn.execute("INSERT OR IGNORE INTO team_aliases "
                             "(team_id, alias, lang) VALUES (?, ?, ?)",
                             (main, alias, lang))
        conn.execute("UPDATE events SET team_home_id = ? WHERE team_home_id = ?",
                     (main, dup))
        conn.execute("UPDATE events SET team_away_id = ? WHERE team_away_id = ?",
                     (main, dup))
        conn.execute("DELETE FROM teams WHERE id = ?", (dup,))
    return text


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="",
                    help="разделы через запятую: " + ", ".join(SECTIONS))
    ap.add_argument("--merge", action="append", default=[],
                    metavar="ДВОЙНИК:ГЛАВНАЯ",
                    help="слить команду-двойника в главную (id через двоеточие)")
    ap.add_argument("--apply", action="store_true", help="записать")
    ap.add_argument("--vacuum", action="store_true",
                    help="после записи ужать файл базы")
    ap.add_argument("--report", default="", help="куда записать построчно")
    args = ap.parse_args()

    only = [s.strip() for s in args.only.split(",") if s.strip()] \
        or list(SECTIONS)
    unknown = sorted(set(only) - set(SECTIONS))
    if unknown:
        print(f"нет таких разделов: {', '.join(unknown)}")
        return 1
    steps = {"копии": copies, "пол": gender, "матчи": matches,
             "чужие": foreign, "лиги": leagues, "команды": teams}
    lines: list[str] = []
    conn = db.connect()
    try:
        print(f"база: {db.db_path()} — "
              f"{'ЗАПИСЬ' if args.apply else 'только показ'}")
        for name in SECTIONS:
            if name in only:
                print(f"{name:7} {steps[name](conn, args.apply, lines.append)}")
        for pair in args.merge:
            dup, _, main_id = pair.partition(":")
            print(f"слить   {merge(conn, int(dup), int(main_id), args.apply, lines.append)}")
        if args.apply:
            conn.commit()
            if args.vacuum:
                conn.execute("VACUUM")
                print("VACUUM: файл базы ужат")
    finally:
        conn.close()
    if args.report:
        Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"построчно: {args.report} ({len(lines)} строк)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

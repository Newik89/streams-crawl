# -*- coding: utf-8 -*-
r"""Словари между базой и файлом `data/dictionaries.json`.

Зачем: подтверждённые названия живут в базе, а база в git не едет
(`data/*.db` в `.gitignore`) — на сервере она своя и пустая. Без выгрузки
работа по наполнению словарей осталась бы на одном компьютере.

    venv\Scripts\python.exe scripts/dict_sync.py --export
        база → `data/dictionaries.json` (файл едет в git)

    venv\Scripts\python.exe scripts/dict_sync.py --import
        файл → база; существующее не трогает, добавляет недостающее

Выгружать после каждого наполнения словаря — иначе правки не доедут до
сервера. Загрузка безопасна: повторный запуск ничего не портит и не плодит
двойников.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary                              # noqa: E402

TARGET = ROOT / "data" / "dictionaries.json"


def previous_team_sports(path: Path) -> dict[str, str]:
    """Подсказки видов спорта из ПРЕЖНЕГО файла словарей — память между
    выгрузками. Файла нет или он битый — пусто."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    prev = data.get("team_sports") if isinstance(data, dict) else None
    return {k: v for k, v in (prev or {}).items() if isinstance(v, str) and v}


def merge_team_sports(prev: dict[str, str], виды: dict[str, set]) -> dict[str, str]:
    """Вид спорта по командам: что видно в событиях базы СЕЙЧАС (`виды`:
    имя → виды) поверх памяти прежнего файла (`prev`). Подсказка не забывается
    с текучкой событий: матч прошёл и команда ушла из базы — вид её не
    сменился (книга 097, 08.11.2026: автокоммит словаря выбросил 107 команд,
    и проверка main покраснела «ПРОПАЛА FCSB — Corvinul» на primaplay.ro —
    сайте без вида спорта). Команда с двумя видами в базе («Barcelona» —
    футбол и баскетбол) выбрасывается и из памяти; пустой вид — не подсказка."""
    doubtful = {k for k, v in виды.items() if len(v) > 1}
    merged = {k: v for k, v in prev.items() if k not in doubtful}
    for k, v in виды.items():
        if len(v) == 1 and next(iter(v)):
            merged[k] = next(iter(v))
    return dict(sorted(merged.items()))


def export(conn, path: Path) -> dict[str, int]:
    """Выгружает команды, лиги и каналы вместе с их написаниями."""
    data: dict = {
        "_": "Подтверждённые названия. Выгружено scripts/dict_sync.py --export. "
             "Правится через админку («Названия»), не руками.",
        "teams": [], "leagues": [], "channels": [],
        # вид спорта, названный владельцем для пары команд: у части сайтов
        # спорта не написано вовсе, и без подсказки строка каждый раз
        # уходила бы в очередь заново (10.09)
        "sport_hints": {},
    }
    # с 15.09 у подсказки есть день матча: {"sport": "F", "day": "…"}.
    # День NULL — бессрочная запись, обход понимает оба формата
    for запрос in ("SELECT pair, sport, match_day FROM sport_hints ORDER BY pair",
                   # база ещё без колонки (миграцию делает init_db) — не терять
                   # подсказки молча, как случилось на пробе 15.09
                   "SELECT pair, sport, NULL AS match_day FROM sport_hints "
                   "ORDER BY pair"):
        try:
            data["sport_hints"] = {
                r["pair"]: {"sport": r["sport"], "day": r["match_day"]}
                for r in conn.execute(запрос)}
            break
        except Exception:                   # совсем старая база без таблицы
            continue
    # Вид спорта по командам НАШЕЙ базы: клуб играет в одном виде, и раз
    # «Arsenal» и «Manchester City» у нас футбольные, то и строка чешского
    # сайта про них — футбол (владелец 10.09: «сопоставь с нашим
    # расписанием»). Команды, за которыми числится больше одного вида
    # («Barcelona» — футбол и баскетбол), не берём
    виды: dict[str, set] = {}
    for row in conn.execute(
            "SELECT t.canonical_name AS имя, e.sport AS вид "
            "FROM events e JOIN teams t "
            "  ON t.id IN (e.team_home_id, e.team_away_id) "
            "GROUP BY t.canonical_name, e.sport"):
        виды.setdefault(row["имя"], set()).add(row["вид"])
    data["team_sports"] = merge_team_sports(previous_team_sports(path), виды)
    # С8 (карточка словаря 09.11): команда, слитая в другую (`merged_into`),
    # в выгрузку не идёт — её написания уже у выжившей; база старше миграции
    # (без колонки) выгружается по-старому
    try:
        rows = conn.execute(
            "SELECT t.canonical_name, t.country, "
            "       group_concat(a.alias, '|') AS aliases "
            "FROM teams t LEFT JOIN team_aliases a ON a.team_id = t.id "
            "WHERE t.merged_into IS NULL "
            "GROUP BY t.id ORDER BY t.canonical_name").fetchall()
    except Exception:
        rows = conn.execute(
            "SELECT t.canonical_name, t.country, "
            "       group_concat(a.alias, '|') AS aliases "
            "FROM teams t LEFT JOIN team_aliases a ON a.team_id = t.id "
            "GROUP BY t.id ORDER BY t.canonical_name").fetchall()
    for row in rows:
        data["teams"].append({
            "name": row["canonical_name"], "country": row["country"],
            "aliases": sorted((row["aliases"] or "").split("|")) if row["aliases"] else [],
        })
    for row in conn.execute(
            "SELECT l.canonical_name, l.slug, l.sport, l.country, "
            "       group_concat(a.alias, '|') AS aliases "
            "FROM leagues l LEFT JOIN league_aliases a ON a.league_id = l.id "
            "GROUP BY l.id ORDER BY l.canonical_name"):
        data["leagues"].append({
            "name": row["canonical_name"], "slug": row["slug"],
            "sport": row["sport"], "country": row["country"],
            "aliases": sorted((row["aliases"] or "").split("|")) if row["aliases"] else [],
        })
    # У канала написание привязано к сайту: `Nova Sport 1` на греческом и на
    # чешском телегиде — разные каналы. Поэтому храним домен, а не id: id на
    # другой машине будет другим.
    for row in conn.execute(
            "SELECT c.canonical_name, c.country, c.language, a.alias, s.domain "
            "FROM channels c LEFT JOIN channel_aliases a ON a.channel_id = c.id "
            "LEFT JOIN sources s ON s.id = a.source_id "
            "ORDER BY c.country, c.canonical_name"):
        data["channels"].append({
            "name": row["canonical_name"], "country": row["country"],
            "language": row["language"], "alias": row["alias"],
            "source": row["domain"],
        })

    # Книга ошибок словаря (карточка 09.11, С8): едет вместе со словарями,
    # чтобы обход на GitHub знал карантин. Команда — именем, не id: id на
    # другой машине другой. Базы старше миграции таблицы не имеют
    data["dictionary_errors"] = []
    try:
        for r in conn.execute(
                "SELECT e.alias, e.lang, e.class, t.canonical_name AS team, "
                "e.source_domain, e.led_to, e.truth, e.note, e.answered_by "
                "FROM dictionary_errors e LEFT JOIN teams t ON t.id = e.team_id "
                "ORDER BY e.class, e.alias, e.lang"):
            data["dictionary_errors"].append({k: r[k] for k in r.keys()})
    except Exception:
        pass
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return {"команд": len(data["teams"]), "лиг": len(data["leagues"]),
            "каналов": len(data["channels"]),
            "ошибок в книге": len(data["dictionary_errors"])}


def load(conn, path: Path) -> dict[str, int]:
    if not path.exists():
        raise FileNotFoundError(f"нет файла {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    domains = {r["domain"]: r["id"] for r in
               conn.execute("SELECT id, domain FROM sources")}
    added = {"команд": 0, "лиг": 0, "каналов": 0, "ошибок в книге": 0}

    # книга ошибок — первой: карантин должен действовать до того, как
    # написания команд лягут в словарь (С3, С8); повтор ничего не плодит (С9)
    for item in data.get("dictionary_errors", []):
        team = conn.execute("SELECT id FROM teams WHERE canonical_name = ?",
                            (item.get("team") or "",)).fetchone()
        dictionary.note_error(conn, item["alias"], item["class"], lang=item.get("lang"),
                              team_id=team["id"] if team else None,
                              source_domain=item.get("source_domain"),
                              led_to=item.get("led_to"), truth=item.get("truth"),
                              note=item.get("note"),
                              answered_by=item.get("answered_by") or "программа")
        added["ошибок в книге"] += 1
    conn.commit()

    for item in data.get("teams", []):
        for alias in item.get("aliases") or [item["name"]]:
            dictionary.remember_team(conn, alias, item["name"], item.get("country"))
        added["команд"] += 1
    for item in data.get("leagues", []):
        for alias in item.get("aliases") or [item["name"]]:
            dictionary.remember_league(conn, alias, item["name"],
                                       item.get("sport"), item.get("country"))
        added["лиг"] += 1
    lost_sources: set[str] = set()
    for item in data.get("channels", []):
        if not item.get("country"):
            print(f"  пропущен канал без страны: {item['name']}")
            continue
        source = item.get("source") or ""
        if source and source not in domains:
            lost_sources.add(source)
        dictionary.remember_channel(conn, item.get("alias") or item["name"],
                                    item["name"], item["country"],
                                    domains.get(source), item.get("language"))
        added["каналов"] += 1

    # Связь «написание канала → сайт» различает одноимённые каналы разных
    # стран. Потерять её молча нельзя: `Nova Sport 1` греческий и чешский
    # сольются в один.
    if lost_sources:
        print("  ВНИМАНИЕ: этих сайтов в базе нет, связь канала с сайтом не "
              "записана: " + ", ".join(sorted(lost_sources)))
        print("  Сначала заведите источники (scripts/import_sources.py), "
              "потом повторите загрузку.")
    return added


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true", help="база → файл")
    ap.add_argument("--import", dest="do_import", action="store_true",
                    help="файл → база")
    ap.add_argument("--file", default=str(TARGET))
    args = ap.parse_args()

    if args.export == args.do_import:
        print("нужно ровно одно: --export или --import")
        return 1

    path = Path(args.file)
    conn = db.connect()
    try:
        counts = export(conn, path) if args.export else load(conn, path)
    finally:
        conn.close()
    where = "выгружено" if args.export else "загружено"
    print(f"{where}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    print(f"файл: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

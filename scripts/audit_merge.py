# -*- coding: utf-8 -*-
r"""Самопроверка №13 на сервере ПОСЛЕ склейки, с памятью прошлых сборов.

Правило (б) починки самопроверки №13 (20.10): «самопроверка на сервере
ПОСЛЕ склейки, с памятью: красное только новое, счёт матчами, в строке —
шаг потери». Список «показал, а канала у игры нет» GitHub составляет ДО
склейки на сервере, и каждый сбор показывал владельцу одни и те же ~130
матчей; сам он считал не матчи, а строки по сайтам.

Запуск — на сервере, в `deploy/streams-update.sh` сразу после
`canon_backfill.py` (метки `fs:` у игр уже стоят):

    venv/bin/python scripts/audit_merge.py                  # results/audit.json
    venv/bin/python scripts/audit_merge.py --file <audit.json> --dry-run

Правила:
  1. СТРОКА ПРОГОНА. Из `audit.json` берётся ключ «показано_нет» (его пишет
     `audit_run.check_seen_not_shown`). Строка `runs` — та, у которой
     `finished_at == store.kyiv_from_utc(audit["собрано"])` (так её пишет
     `store.log_run`), последняя по id, и в её логе есть «самопроверка».
     Не нашлась (или ключа «показано_нет» нет) — строка в stdout, код 0,
     база не тронута.
  2. СВЕРКА С ВИТРИНОЙ. Игра матча: события с `events.flags = 'fs:<fs_id>'`;
     без fs_id (или если метки ни у кого нет) — по паре: имена
     `team_home_auto`/`team_away_auto` = «эталон» через `names.same_team`
     в любом порядке и начало в ±3 ч (`PAIR_WINDOW`) от «начало». Матч
     «склейка добрала», если у такой игры есть ВИДИМАЯ отметка
     (`miss_count < store.MISS_LIMIT`) этого сайта (`sources.domain` без
     `www.`) или того же канала с любого сайта (имя канала — как
     `audit_run._channel_key`: его `canonical_name`, псевдонимы
     `channel_aliases` и сырые имена `source_channels`). Иначе матч потерян.
  3. ПАМЯТЬ. Настройка `audit13_seen` — JSON `{ключ: "ГГГГ-ММ-ДД ЧЧ:ММ"}`,
     дата — первый сбор (киевское время, как `runs.finished_at`), на
     котором матч был потерян. Ключ — `fs_id|сайт`, без fs_id —
     `эталон|начало|сайт`. Потерянного в памяти нет — НОВЫЙ (красный), есть
     с более ранней датой — СТАРЫЙ (с датой первого сбора). Новые
     дописываются; записи старше `KEEP_DAYS` суток от «собрано», которых
     в этом сборе нет, вычищаются.
  4. СЧЁТ МАТЧАМИ. Раздел 13 в `runs.log["самопроверка"]` переписывается:
     название с числами «матчей N, новых M, старых K, склейка добрала L»
     (матч — пара «матч эталона × сайт», как в «показано_нет»), строки —
     по сайту: новых/старых, шаги потери (`audit_run.step_kind`) с числом,
     до `audit_run.EXAMPLES` примеров новых и старых. Новых и старых 0 —
     раздела нет. «подозрений» = прежнее − строки прежнего раздела 13 +
     строки нового. Ключ «новых_13» = M — шаблон «Прогонов» покажет его.
  5. ПОВТОР НЕ УДВАИВАЕТ. Дата в памяти, равная текущему «собрано», —
     матч всё ещё новый (старым он станет на СЛЕДУЮЩЕМ сборе); раздел
     пересчитывается из `audit.json`, а не дописывается.
  6. ОШИБКА — КОД 1. Нет файла, битый JSON, сбой базы — понятная строка в
     stdout и код 1; лог прогона и память пишутся одной транзакцией.
  7. --dry-run — только напечатать итог: ни лог прогона, ни память не
     пишутся.

Итог владельцу одной строкой:
`самопроверка после склейки: матчей 135, новых 12, старых 110, склейка добрала 13`.
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app import db, names, store  # noqa: E402
from audit_run import EXAMPLES, _channel_key, step_kind  # noqa: E402

#: настройка с памятью потерянных матчей (правило 3)
MEMORY_KEY = "audit13_seen"
#: сколько суток помнить матч (правило 3)
KEEP_DAYS = 10
#: окно поиска игры по паре без fs_id (правило 2)
PAIR_WINDOW = timedelta(hours=3)
#: начало названия раздела 13 — по нему раздел находится в логе прогона
SECTION_PREFIX = "13."
SECTION_TITLE = ("13. Сайт показал матч эталона в эфир, а канала у игры на "
                 "витрине нет — после склейки")
#: формат меток времени базы и памяти
STAMP = "%Y-%m-%d %H:%M"


def bare(domain: str) -> str:
    """Домен без `www.` и регистра — как `audit_run.bare`."""
    domain = (domain or "").strip().lower()
    return domain[4:] if domain.startswith("www.") else domain


def memory_key(m: dict) -> str:
    """Правило 3: `fs_id|сайт`, без fs_id — `эталон|начало|сайт`."""
    if m.get("fs_id"):
        return f"{m['fs_id']}|{m.get('сайт', '')}"
    return f"{m.get('эталон', '')}|{m.get('начало', '')}|{m.get('сайт', '')}"


def _pair(text: str) -> tuple[str, str]:
    """«Stuttgart — Atl. Madrid» → («Stuttgart», «Atl. Madrid»)."""
    for sep in (" — ", " - ", " – "):
        if sep in (text or ""):
            home, away = text.split(sep, 1)
            return home.strip(), away.strip()
    return (text or "").strip(), ""


def find_events(conn: sqlite3.Connection, m: dict) -> list[int]:
    """Правило 2: игры базы этого матча — по метке fs:, иначе по паре ±3 ч."""
    if m.get("fs_id"):
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM events WHERE flags = ?", (f"fs:{m['fs_id']}",))]
        if ids:
            return ids
    home, away = _pair(m.get("эталон", ""))
    try:
        start = datetime.fromisoformat(store.db_time(m.get("начало", "")))
    except ValueError:
        return []
    if not home or not away:
        return []
    lo = (start - PAIR_WINDOW).strftime(STAMP)
    hi = (start + PAIR_WINDOW).strftime(STAMP)
    out = []
    for r in conn.execute(
            "SELECT id, team_home_auto, team_away_auto FROM events "
            "WHERE replace(start_kyiv, 'T', ' ') BETWEEN ? AND ?", (lo, hi)):
        h, a = r["team_home_auto"] or "", r["team_away_auto"] or ""
        if ((names.same_team(h, home) and names.same_team(a, away))
                or (names.same_team(h, away) and names.same_team(a, home))):
            out.append(r["id"])
    return out


def visible_marks(conn: sqlite3.Connection, event_ids: list[int]) -> list[tuple[str, set]]:
    """Видимые отметки игр: (домен без www, ключи имён канала)."""
    if not event_ids:
        return []
    marks = []
    q = ",".join("?" * len(event_ids))
    for r in conn.execute(
            f"SELECT ec.channel_id, ec.source_id, s.domain, c.canonical_name "
            f"FROM event_channels ec JOIN sources s ON s.id = ec.source_id "
            f"JOIN channels c ON c.id = ec.channel_id "
            f"WHERE ec.event_id IN ({q}) AND ec.miss_count < ?",
            (*event_ids, store.MISS_LIMIT)).fetchall():
        keys = {_channel_key(r["canonical_name"])}
        keys |= {_channel_key(x["alias"]) for x in conn.execute(
            "SELECT alias FROM channel_aliases WHERE channel_id = ?", (r["channel_id"],))}
        keys |= {_channel_key(x["raw_name"]) for x in conn.execute(
            "SELECT raw_name FROM source_channels WHERE channel_id = ?", (r["channel_id"],))}
        keys.discard("")
        marks.append((bare(r["domain"]), keys))
    return marks


def recovered(conn: sqlite3.Connection, m: dict) -> bool:
    """Правило 2: склейка добрала — отметка этого сайта или того же канала."""
    site, key = bare(m.get("сайт", "")), _channel_key(m.get("канал", ""))
    for domain, keys in visible_marks(conn, find_events(conn, m)):
        if domain == site or (key and key in keys):
            return True
    return False


def _short(when: str) -> str:
    """«2026-10-20T22:00» → «20.10 22:00»."""
    try:
        return datetime.fromisoformat(store.db_time(when)).strftime("%d.%m %H:%M")
    except ValueError:
        return when or "?"


def example(m: dict, first: str = "") -> str:
    """Пример строки: показ, канал, подпись, эталон, шаг (и дата первого сбора)."""
    since = f", с {_short(first)}" if first else ""
    return (f"{_short(m.get('показ', ''))} {m.get('канал', '')} "
            f"«{(m.get('подпись') or '')[:60]}» = {m.get('эталон', '')} "
            f"({step_kind(m.get('шаг') or '?')}{since})")


def site_lines(new: list[dict], old: list[tuple[dict, str]]) -> list[str]:
    """Правило 4: строка на сайт — новых/старых, шаги, примеры."""
    by_site: dict[str, dict] = collections.defaultdict(lambda: {"new": [], "old": []})
    for m in new:
        by_site[m.get("сайт", "")]["new"].append(m)
    for m, first in old:
        by_site[m.get("сайт", "")]["old"].append((m, first))
    out = []
    for site in sorted(by_site):
        n, o = by_site[site]["new"], by_site[site]["old"]
        kinds = collections.Counter(step_kind(m.get("шаг") or "?")
                                    for m in n + [x for x, _ in o])
        line = (f"{site}: новых {len(n)}, старых {len(o)} — шаги: "
                + ", ".join(f"{k} ×{c}" for k, c in kinds.most_common()))
        if n:
            line += " — примеры новых: " + "; ".join(example(m) for m in n[:EXAMPLES])
        if o:
            line += "; старые: " + "; ".join(example(m, f) for m, f in o[:EXAMPLES])
        out.append(line)
    return out


def merge(conn: sqlite3.Connection, audit: dict, dry_run: bool) -> tuple[int, str]:
    """Правила 1–5. Возвращает (код выхода, строку итога)."""
    lost = audit.get("показано_нет")
    if not isinstance(lost, list):
        return 0, "самопроверка после склейки: в audit.json нет «показано_нет» — нечего сверять"
    when = store.kyiv_from_utc(str(audit.get("собрано") or ""))
    row = conn.execute("SELECT id, log FROM runs WHERE finished_at = ? "
                       "ORDER BY id DESC LIMIT 1", (when,)).fetchone() if when else None
    if row is None:
        return 0, (f"самопроверка после склейки: строки «Прогоны» для сбора "
                   f"«{audit.get('собрано')}» нет — ничего не меняю")
    log = json.loads(row["log"] or "{}") or {}
    check = log.get("самопроверка") if isinstance(log, dict) else None
    if not isinstance(check, dict):
        return 0, (f"самопроверка после склейки: у прогона #{row['id']} нет "
                   f"самопроверки — ничего не меняю")

    # правило 2: сверка с витриной после склейки
    got, missing = [], []
    for m in lost:
        if isinstance(m, dict):
            (got if recovered(conn, m) else missing).append(m)

    # правила 3 и 5: память первых сборов
    memory = json.loads(db.get_setting(conn, MEMORY_KEY, "{}") or "{}")
    if not isinstance(memory, dict):
        memory = {}
    new, old = [], []
    for m in missing:
        k = memory_key(m)
        first = memory.get(k)
        if first and first < when:
            old.append((m, first))
        else:
            new.append(m)
            memory[k] = when
    now_keys = {memory_key(m) for m in missing}
    edge = (datetime.strptime(when, STAMP) - timedelta(days=KEEP_DAYS)).strftime(STAMP)
    memory = {k: v for k, v in memory.items() if k in now_keys or str(v) >= edge}

    # правило 4: раздел 13 матчами
    разделы = [r for r in (check.get("разделы") or []) if isinstance(r, dict)]
    place = next((i for i, r in enumerate(разделы)
                  if str(r.get("название") or "").startswith(SECTION_PREFIX)), None)
    before = len(разделы[place].get("строки") or []) if place is not None else 0
    lines = site_lines(new, old)
    if place is not None:
        разделы.pop(place)
    if lines:
        title = (f"{SECTION_TITLE}: матчей {len(missing) + len(got)}, новых {len(new)}, "
                 f"старых {len(old)}, склейка добрала {len(got)}")
        if place is None:   # раздела не было — перед «Разбор упал», иначе в конец
            place = next((i for i, r in enumerate(разделы)
                          if r.get("название") == "Разбор упал"), len(разделы))
        разделы.insert(place, {"название": title, "строки": lines})
    check["разделы"] = разделы
    check["подозрений"] = max(0, int(check.get("подозрений") or 0) - before + len(lines))
    check["новых_13"] = len(new)
    log["самопроверка"] = check

    summary = (f"самопроверка после склейки: матчей {len(missing) + len(got)}, новых {len(new)}, "
               f"старых {len(old)}, склейка добрала {len(got)}")
    if dry_run:
        return 0, summary + " (--dry-run: ничего не записано)"
    # правило 6: лог прогона и память — одной транзакцией (set_setting
    # делает commit обоих)
    conn.execute("UPDATE runs SET log = ? WHERE id = ?",
                 (json.dumps(log, ensure_ascii=False), row["id"]))
    db.set_setting(conn, MEMORY_KEY, json.dumps(memory, ensure_ascii=False, sort_keys=True))
    return 0, summary


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", default=str(ROOT / "results" / "audit.json"),
                    help="audit.json сбора (по умолчанию results/audit.json)")
    ap.add_argument("--dry-run", action="store_true",
                    help="только показать итог, базу не трогать")
    args = ap.parse_args(argv)
    try:
        audit = json.loads(Path(args.file).read_text(encoding="utf-8"))
        if not isinstance(audit, dict):
            raise ValueError("в файле не словарь")
    except (OSError, ValueError) as e:
        print(f"самопроверка после склейки: не прочитать {args.file}: {e}")
        return 1
    conn = None
    try:
        conn = db.connect(db.BUSY_TIMEOUT_SCRIPT)
        code, summary = merge(conn, audit, args.dry_run)
    except (sqlite3.Error, ValueError, TypeError) as e:
        if conn is not None:
            conn.rollback()
        print(f"самопроверка после склейки: ошибка базы, ничего не записано: {e}")
        return 1
    finally:
        if conn is not None:
            conn.close()
    print(summary)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

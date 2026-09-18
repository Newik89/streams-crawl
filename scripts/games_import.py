# -*- coding: utf-8 -*-
"""Влить игры обхода в базу сайта.

Обход (GitHub Actions) кладёт `results/games.json` в репозиторий; после
`git pull` этот скрипт переносит игры в базу и убирает те, чьё время вышло.
К сайтам не обращается — только файл и база, запускать можно сколько угодно.

Запуск:
    python scripts/games_import.py               # results/games.json
    python scripts/games_import.py --file recon/raw_live/games.json
    python scripts/games_import.py --purge-only  # только срок жизни
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import canon, db, dictionary, health, names, store  # noqa: E402

DEFAULT = ROOT / "results" / "games.json"


def crawl_facts(report_path: Path) -> tuple[set[str] | None, str]:
    """Из отчёта обхода: какие домены отработали и по какой день качали.

    Нужно заливке, чтобы короткий прогон не гасил каналы дальних дней и
    чтобы лежащий сайт не уносил свои каналы с витрины (аудит 07.09, A7).
    Отчёта нет — возвращаем `(None, "")`, и заливка ведёт себя по-старому."""
    import json as _json
    try:
        report = _json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, ""
    rows = report.get("строки") or []
    if not rows:
        return None, ""
    broken = ("не открылась", "заглушка защиты")
    worked = {r["domain"] for r in rows if r.get("итог") not in broken}
    # последний день, который прогон вообще скачивал: у сеток день не
    # проставлен — их страницы приносят сразу всё окно, поэтому пустые
    # значения не учитываем, а если дней нет вовсе, порог не ставим
    days = sorted(d for d in (r.get("day") or "" for r in rows) if d)
    return worked, (days[-1] if days else "")


def _json_stamp(path) -> str:
    """Метка прогона из games.json («собрано») — по ней отличаем свежий
    файл от повторной заливки того же."""
    import json as _json
    try:
        return str(_json.loads(path.read_text(encoding="utf-8"))
                   .get("собрано") or "")
    except (OSError, ValueError):
        return ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DEFAULT))
    ap.add_argument("--reimport", action="store_true",
                    help="перелить УЖЕ влитый файл ещё раз — после починки "
                         "разбора или склейки, не дожидаясь нового обхода. "
                         "Каналы при этом не гасятся (файл старый), но "
                         "записи, снятые руками после той заливки, могут "
                         "вернуться — запускать осознанно")
    ap.add_argument("--purge-only", action="store_true",
                    help="не вливать, только убрать отжившие игры")
    ap.add_argument("--who", default="",
                    help="чей сбор — подпись на витрине («сервер mojtv.hr»)")
    args = ap.parse_args()

    conn = db.connect()
    try:
        db.init_db(conn)
        gone = store.purge_expired(conn)
        print(f"отжило и убрано: {gone}")
        if args.purge_only:
            return 0

        path = Path(args.file)
        if not path.exists():
            print(f"нет {path} — сначала обход или git pull")
            return 1
        # подтверждённые владельцем имена — сильнее словаря слов
        names.set_overrides(dictionary.team_overrides(conn))
        games = store.load_games_json(path)

        # канон имён по эталону flashscore (задание владельца 02.09):
        # уверенные совпадения — в библиотеку, сомнительные — в очередь.
        # Свежие алиасы тут же применяются к этой же заливке.
        import json as _json
        reference = _json.loads(path.read_text(encoding="utf-8")) \
            .get("эталон", [])
        aligned = {"sure": [], "ask": [], "missed": []}
        if reference:
            # A2 (6е): местные написания эталона → английские по fs_id;
            # свежие алиасы тут же видит сверка ниже
            learned_teams, learned_leagues = canon.learn_by_id(conn, reference)
            if learned_teams or learned_leagues:
                names.set_overrides(dictionary.team_overrides(conn))
            print(f"по fs_id локалей выучено: команд {learned_teams}, "
                  f"лиг {learned_leagues}")
            aligned = canon.align(games, reference,
                                  dictionary.league_overrides(conn))
            fixed, queued = canon.apply(conn, aligned)
            names.set_overrides(dictionary.team_overrides(conn))
            retimed = canon.retime(aligned)
            print(f"канон по flashscore: имён закреплено {fixed}, "
                  f"в очередь на подтверждение {queued}, "
                  f"время подтянуто к эталону у {retimed}, "
                  f"не найдено в эталоне {len(aligned['missed'])}")

        # тот же файл, что и в прошлый раз, — заливку пропускаем целиком:
        # повторная заливка воскрешала снятые руками записи (#1207, 05.09).
        # Метка своя на каждый путь: полный прогон и скан даты — разные файлы
        stamp = _json_stamp(path)
        stamp_key = f"last_import_stamp:{path.parent.name}"
        if stamp and stamp == db.get_setting(conn, stamp_key):
            if not args.reimport:
                print(f"файл не менялся с прошлой заливки ({stamp}) — пропуск")
                return 0
            print(f"переналивка того же файла ({stamp}) — без гашения каналов")
        worked, punish_until = crawl_facts(path.parent / "report.json")
        if worked is not None:
            print(f"отработали сайтов: {len(worked)}; каналы игр после "
                  f"{punish_until or '—'} этот прогон не гасит")
        stats = store.save_games(conn, games, punish=not args.reimport,
                                 worked=worked, punish_until=punish_until)
        db.set_setting(conn, stamp_key, stamp)
        # отчёт для карточки на дашборде: владелец видит, что скан доехал.
        # Время — СЕРВЕРНЫМИ часами (метка «собрано» на GitHub идёт в UTC
        # и сравнение с заказом врало на 3 часа), плюс дата скана
        if path.parent.name == "day":
            from datetime import datetime as _dt
            days = sorted({(g.get("start_kyiv") or "")[:10]
                           for g in games if g.get("start_kyiv")})
            db.set_setting(conn, "day_scan_result",
                           f"{days[0] if days else ''}|"
                           f"{_dt.now().strftime('%Y-%m-%d %H:%M')}|"
                           f"{len(games)}")
        if aligned["sure"]:
            canon.stamp(conn, aligned)

        # Нерешённые строки обхода — человеку в очередь «Вид спорта»
        # (правило владельца 04.09: непонятное не убивать, а на разбор)
        import json as _json
        unsolved = _json.loads(path.read_text(encoding="utf-8")) \
            .get("на_разбор", [])
        queued_review = 0
        for row in unsolved:
            # без времени: одна пара спрашивается один раз, а не на каждый
            # повтор в сетке (время и сырой заголовок — в подсказке)
            label = " | ".join(x for x in (
                f"{row.get('home', '')} - {row.get('away', '')}",
                row.get("league") or "",
                f"{row.get('канал', '')} ({row.get('домен', '')})") if x)
            hint = " | ".join(x for x in (
                (row.get("start_kyiv") or "").replace("T", " "),
                row.get("raw_title") or "") if x)
            if dictionary.enqueue(conn, "sport", label, suggestion=hint):
                queued_review += 1
        if unsolved:
            print(f"нерешённых строк: {len(unsolved)}, "
                  f"в модерацию добавлено: {queued_review}")
        from datetime import datetime
        db.set_setting(conn, "last_import", datetime.now().strftime("%Y-%m-%d %H:%M"))
        # заливка дошла до конца — прежняя жалоба на дашборде снимается (A5)
        health.mark("import", True)
        # метка самого обхода («собрано», часы GitHub — UTC): по ней панель
        # «Здоровье» показывает, когда сбор реально прошёл, и понимает,
        # доехал ли заказанный кнопкой обход (просьба владельца 09.09)
        if stamp:
            db.set_setting(conn, "last_crawl", stamp)
        store.log_run(conn, path.parent / "report.json", stats,
                      crawled=stamp, who=args.who)
        print(f"в файле игр: {len(games)}; новых: {stats.new}, "
              f"обновлено: {stats.updated}, отметок каналов: {stats.channels}, "
              f"повторов не пущено: {stats.repeats}, "
              f"прилипло к flashscore вопреки времени сайта: {stats.time_off}")
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        print(f"игр в базе теперь: {total}")
        return 0
    finally:
        conn.close()


def guarded() -> int:
    """Падение заливки — не только строчка в логе, но и жалоба на дашборде.

    До аудита (A5) упавший `games_import` виден был лишь в
    `/var/log/streams-update.log`: сайт как ни в чём не бывало показывал
    вчерашние игры. Теперь причина ложится в `last_import_error`, а карточка
    «Здоровье сбора» краснеет.
    """
    try:
        return main()
    except Exception as beda:                  # noqa: BLE001 — см. докстринг
        try:
            health.mark("import", False, f"{type(beda).__name__}: {beda}")
        except Exception:                      # noqa: BLE001
            pass                               # база недоступна — только лог
        raise


if __name__ == "__main__":
    raise SystemExit(guarded())

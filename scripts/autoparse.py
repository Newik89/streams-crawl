# -*- coding: utf-8 -*-
r"""Подобрать разбор новому сайту из УЖЕ готовых — без нового парсера.

Просьба владельца 22–23.09.2026: «когда я добавляю новый источник, система
сама должна определить, каким образом собирать информацию; не подберёт —
тогда разберу сайт отдельно».

Как работает: страница сайта прогоняется через все готовые разборы (их
больше сотни), каждый оценивается на «похоже ли на телесетку» — сколько
строк, у скольких есть время и название, попадаются ли пары команд. Лучший
показывается владельцу вместе с примерами строк; с `--apply` он
записывается источнику как «одолженный» (`selector_config.parser`), и обход
начинает ходить на этот сайт без единой строки нового кода.

Запуск (сеть — только с сервера, правило проекта):
    ssh root@157.245.77.140 "cd streams-schedule && \
        venv/bin/python scripts/autoparse.py start.sportdigital.de"
    …тот же вызов с --apply — записать выбор источнику

Локально можно разбирать сохранённую копию, в сеть не выходя:
    venv\Scripts\python.exe scripts/autoparse.py домен --file страница.html
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, fetch, parsers, urls  # noqa: E402

#: ниже этого балла считаем, что не подобралось: сайт уходит владельцу на
#: ручной разбор, как он и просил
GOOD_ENOUGH = 45
#: сколько кандидатов показывать
SHOW_TOP = 5


def _on_server() -> bool:
    return Path("/etc/streams-schedule.env").exists()


def _page_url(row) -> str:
    """Адрес первой страницы источника с подставленной сегодняшней датой."""
    pattern = row["url_pattern"] or row["base_url"] or ""
    config = json.loads(row["selector_config"] or "{}") or {}
    return urls.resolve(pattern, row["base_url"] or "", day=date.today(),
                        **(config.get("url_marks") or {}))


def _download(url: str, browser: bool) -> str:
    """Одна страница — тем же загрузчиком, что и обход."""
    fetcher = fetch.Fetcher(offline=False, use_cache=False,
                            browser_fallback=True, browser_only=browser)
    page = fetcher.get(url)
    if not page.ok:
        raise RuntimeError(f"страница не открылась: {page.verdict} {page.why}")
    return page.html


def _examples(programs: list, limit: int = 3) -> list[str]:
    out = []
    for p in programs[:limit]:
        when = p.start.strftime("%d.%m %H:%M") if p.start else (p.raw_time or "—")
        out.append(f"{when} | {(p.channel_raw or '—')[:22]} | "
                   f"{(p.title or '')[:60]}")
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("domain", help="домен источника, как в базе")
    ap.add_argument("--file", help="разобрать сохранённую копию, не ходя в сеть")
    ap.add_argument("--browser", action="store_true",
                    help="сразу браузером: сетку рисует скрипт")
    ap.add_argument("--apply", action="store_true",
                    help="записать найденный разбор источнику")
    args = ap.parse_args()

    conn = db.connect()
    row = conn.execute("SELECT id, domain, base_url, url_pattern, timezone, "
                       "selector_config FROM sources WHERE domain = ?",
                       (args.domain,)).fetchone()
    if row is None:
        print(f"источника {args.domain} нет в базе")
        return 1

    own = parsers.get(args.domain)
    if own is not None:
        print(f"у {args.domain} УЖЕ есть свой разбор "
              f"({own.__module__.rsplit('.', 1)[-1]}) — подбирать нечего")
        return 0

    if args.file:
        html = Path(args.file).read_text(encoding="utf-8", errors="replace")
        url = _page_url(row)
        print(f"разбираю сохранённую копию: {args.file}")
    else:
        if not _on_server():
            print("в сеть ходим только с сервера (правило проекта). "
                  "Локально — с --file по сохранённой копии.")
            return 2
        url = _page_url(row)
        print(f"качаю {url}")
        try:
            html = _download(url, args.browser)
        except RuntimeError as e:
            print(f"  {e}")
            print("  сетку рисует скрипт? повторите с --browser")
            return 1
    print(f"  страница {len(html)} знаков\n")

    found = parsers.try_all(html, day=date.today(),
                            tz=row["timezone"] or None, url=url)
    if not found:
        print("НЕ ПОДОБРАЛОСЬ: ни один готовый разбор не дал строк — "
              "сайт на ручной разбор")
        conn.close()
        return 3

    print(f"{'донор':26} {'балл':>5} {'строк':>6} {'со временем':>12} "
          f"{'пар':>4}")
    for donor, fit, _ in found[:SHOW_TOP]:
        print(f"{donor:26} {fit['score']:>5} {fit['rows']:>6} "
              f"{fit['timed']:>12} {fit['pairs']:>4}")

    best_donor, best_fit, best_programs = found[0]
    print(f"\nлучший — {best_donor} (балл {best_fit['score']}), примеры строк:")
    for line in _examples(best_programs):
        print("   ", line)

    if best_fit["score"] < GOOD_ENOUGH:
        print(f"\nНЕ ПОДОБРАЛОСЬ уверенно (балл ниже {GOOD_ENOUGH}) — "
              "сайт на ручной разбор")
        conn.close()
        return 3

    if not args.apply:
        print("\nэто показ. Записать источнику: повторить с --apply")
        conn.close()
        return 0

    config = json.loads(row["selector_config"] or "{}") or {}
    config["parser"] = best_donor
    conn.execute("UPDATE sources SET selector_config = ?, parse_level = ? "
                 "WHERE id = ?",
                 (json.dumps(config, ensure_ascii=False), "A", row["id"]))
    conn.commit()
    conn.close()
    print(f"\nзаписано: {args.domain} разбирается как {best_donor}. "
          "Дальше — пересобрать план (scripts/crawl_plan.py --json "
          "data/crawl_plan.json) и доставить его (scripts/push_plan.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

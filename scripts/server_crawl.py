# -*- coding: utf-8 -*-
r"""Обход сайтов, которые качает САМ СЕРВЕР, а не GitHub.

Часть сайтов закрыта для сети GitHub Actions: `mojtv.hr` с 09.09 отвечает
раннеру «Sorry, you have been blocked» (Cloudflare забанил адрес), до
`rtrs.tv` раннер вовсе не достучался. С нашего DigitalOcean оба открываются.
Решение владельца 10.09: такие сайты качает сервер, раз в сутки.

Домены берутся из базы — у источника в `selector_config` стоит
`by_server: true` (ставится `scripts/source_mode.py --by-server`, кнопкой
«Качать сервером» или сам — `app/site_move.py`). Глубина —
`site_move.server_depth` (П3): его `max_days`; переведённый автоматически —
окно планового сбора (6 дн.); переведённый владельцем без потолка — 2 дня.

    venv/bin/python scripts/server_crawl.py             # если пора
    venv/bin/python scripts/server_crawl.py --force     # не глядя на срок
    venv/bin/python scripts/server_crawl.py --only mojtv.hr
    venv/bin/python scripts/server_crawl.py --once tv.site.cz   # проверка 1 адресом

Утренний запуск (cron 06:40, без `--only`) перед обычным ходом делает шаг 11
схемы сбоев (`app/site_move.py`): возвращает на GitHub сайты, чья недельная
проба с GitHub открылась (П4), и проверяет ОДНИМ адресом сайты, которые
GitHub не скачал 3 сбора подряд (П2): открылся серверу — сайт переводится
на сервер и тут же качается обычным ходом. Пока идут эти проверки, замок
заливки (`/run/streams-update.lock`) держит этот скрипт — заливка ждёт.
`--once <домен>` — та же проверка одного сайта руками (те же пределы).

Чаще раза в сутки к сайту не ходим, даже если запустить много раз подряд:
владелец 10.09 — «даже кнопкой не больше одного раза в сутки». Память —
`results/server_crawl.json`. Полный сбор всех сайтов с сервера — НИКОГДА
(слово владельца 06.10): здесь только сайты `by_server` и проверки 1 адресом.

Запускать ТОЛЬКО на сервере: скрипт выходит в сеть.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, plan_push, site_move  # noqa: E402
from app.crawl_hook import SITE_GAP_HOURS  # noqa: E402

ПАМЯТЬ = ROOT / "results" / "server_crawl.json"
РАБОЧАЯ = Path("/var/tmp/streams-server-crawl")
#: сколько часов ждём между заходами к одному сайту — порог общий с кнопкой
#: «Обойти сайт» (app/crawl_hook.py), менять там
ЖДЁМ_ЧАСОВ = SITE_GAP_HOURS
PY = str(Path(sys.executable))


def память() -> dict:
    try:
        return json.loads(ПАМЯТЬ.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def запомнить(домен: str, итог: str) -> None:
    было = память()
    было[домен] = {"когда": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "итог": итог}
    ПАМЯТЬ.parent.mkdir(parents=True, exist_ok=True)
    ПАМЯТЬ.write_text(json.dumps(было, ensure_ascii=False, indent=2),
                      encoding="utf-8")


def пора(домен: str, память_: dict, force: bool) -> bool:
    if force:
        return True
    было = (память_.get(домен) or {}).get("когда") or ""
    try:
        прошлый = datetime.strptime(было, "%Y-%m-%d %H:%M")
    except ValueError:
        return True
    return datetime.now() - прошлый >= timedelta(hours=ЖДЁМ_ЧАСОВ)


def сайты(only: str = "", days: int = 0) -> list[tuple[str, int]]:
    """Домены «качает сервер» и их глубина в днях (`site_move.server_depth`,
    П3; `days` — окно из `--days`)."""
    conn = db.connect()
    try:
        out = []
        for r in conn.execute("SELECT domain, selector_config FROM sources "
                              "WHERE enabled = 1 AND role = 'schedule'"):
            config = json.loads(r["selector_config"] or "{}") or {}
            if not config.get("by_server"):
                continue
            if only and r["domain"] != only:
                continue
            out.append((r["domain"], site_move.server_depth(config, days)))
        return out
    finally:
        conn.close()


@contextmanager
def замок_заливки(путь: str = site_move.UPDATE_LOCK):
    """П2 (`app/site_move.py`): проверки и переводы — не одновременно с
    заливкой. Берём общий замок `streams-update.sh` и забора по стуку
    (`flock -w 900 /run/streams-update.lock`) БЕЗ ожидания: взяли — пока
    держим, заливка ждёт (до 15 мин, проверки короче); занят — отдаём,
    почему нельзя. Отдаёт пусто, когда замок наш. Не Linux (локальная
    обкатка) — замка нет, пусто."""
    try:
        import fcntl
    except ImportError:
        fcntl = None
    файл, почему = None, ""
    if fcntl is not None:
        try:
            файл = open(путь, "a")
        except OSError as e:
            почему = f"замок заливки не открылся ({type(e).__name__})"
        else:
            try:
                fcntl.flock(файл, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                файл.close()
                файл, почему = None, ("идёт заливка (замок streams-update.sh "
                                      "занят — заливкой или другой проверкой)")
    try:
        yield почему
    finally:
        if файл is not None:
            fcntl.flock(файл, fcntl.LOCK_UN)
            файл.close()


def план_по_доменам() -> dict:
    """Источники плана обхода (`data/crawl_plan.json`) по домену — из них
    `crawl_fetch.один_адрес` строит адрес проверки."""
    try:
        план = json.loads(plan_push.PLAN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {s["domain"]: s for s in план.get("sources") or [] if s.get("domain")}


_качалка = None


def проверить_адрес(source: dict) -> dict:
    """П2/П6: ОДИН адрес сайта с сервера — обычным запросом, отказали —
    браузером (как в обходе). Страница не сохраняется."""
    global _качалка
    import crawl_fetch
    from app import fetch
    if _качалка is None:
        _качалка = fetch.Fetcher(offline=False, use_cache=False,
                                 browser_fallback=True)
    return crawl_fetch.проба_одним_адресом(source, _качалка)


def утренний_ход(conn, now=None, fetch_one=None, set_mode=None,
                 plan=None, lock=None, free=None) -> list[str]:
    """Шаг 11 схемы сбоев перед обычным ходом (`app/site_move.py`): П4 —
    вернуть на GitHub сайты с открывшейся пробой; П2 — проверить кандидатов
    одним адресом и перевести. Подмены (`fetch_one`, `set_mode`, `plan`,
    `lock`, `free`) — для проверок. Возвращает строки журнала."""
    now = now or datetime.now(site_move.KYIV)
    fetch_one = fetch_one or проверить_адрес
    set_mode = set_mode or plan_push.set_mode
    lock = lock or замок_заливки
    said = []
    with lock() as занято:
        said += site_move.return_turn(conn, now, set_mode, busy=занято)
        said += site_move.server_turn(conn, now, fetch_one,
                                      plan if plan is not None else план_по_доменам(),
                                      set_mode, busy=занято,
                                      free=free or site_move.free_mb)
    return said


def разовая_проверка(conn, домен: str, now=None, fetch_one=None,
                     set_mode=None, plan=None, lock=None, free=None) -> list[str]:
    """`--once <домен>`: проверка одного сайта одним адресом с сервера (П2,
    те же пределы); переводит, только если сайт — кандидат."""
    now = now or datetime.now(site_move.KYIV)
    lock = lock or замок_заливки
    with lock() as занято:
        return site_move.server_turn(
            conn, now, fetch_one or проверить_адрес,
            plan if plan is not None else план_по_доменам(),
            set_mode or plan_push.set_mode, busy=занято, only=домен, limit=1,
            free=free or site_move.free_mb)


#: свободная память, МБ (MemAvailable) — перед каждым сайтом обычного хода;
#: проверки подменяют
свободно_мб = site_move.free_mb


def отложил(домен: str, свободно: int) -> None:
    """Мало памяти перед сайтом: строка в журнал и в «Прогоны», без
    падения — остальные сайты пробуем дальше (память могла освободиться)."""
    строка = (f"мало памяти (свободно {свободно} МБ, нужно не меньше "
              f"{site_move.MIN_FREE_MB}), сайт {домен} откладываю")
    print(f"{домен}: {строка}")
    try:
        conn = db.connect(db.BUSY_TIMEOUT_SCRIPT)
        try:
            site_move.note(conn, строка)
        finally:
            conn.close()
    except Exception as беда:                    # noqa: BLE001 — только строка
        print(f"   строку в «Прогоны» не записал: {type(беда).__name__}")


def шаг(команда: list[str], тег: str) -> bool:
    print(f"   {тег}…", flush=True)
    готово = subprocess.run(команда, cwd=str(ROOT), capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    хвост = (готово.stdout or "").strip().splitlines()[-3:]
    for строка in хвост:
        print(f"      {строка}")
    if готово.returncode != 0:
        print(f"      не вышло, код {готово.returncode}")
        сбой = (готово.stderr or "").strip().splitlines()[-3:]
        for строка in сбой:
            print(f"      {строка}")
    return готово.returncode == 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", default="", help="только этот домен")
    ap.add_argument("--force", action="store_true",
                    help="не смотреть, прошли ли сутки")
    ap.add_argument("--days", type=int, default=0, help="окно, суток")
    ap.add_argument("--once", default="", metavar="ДОМЕН",
                    help="проверить ОДНИМ адресом сайт, который GitHub не "
                         "скачал 3 сбора подряд; открылся — перевести на "
                         "сервер (app/site_move.py, П2)")
    args = ap.parse_args()

    if args.once:
        conn = db.connect(db.BUSY_TIMEOUT_SCRIPT)
        try:
            for строка in разовая_проверка(conn, args.once):
                print(строка)
        finally:
            conn.close()
        return 0
    if not args.only:
        # утро: шаг 11 схемы сбоев — вернуть / проверить / перевести. Его
        # ошибка не мешает обычному ходу по сайтам «качает сервер»
        conn = db.connect(db.BUSY_TIMEOUT_SCRIPT)
        try:
            for строка in утренний_ход(conn):
                print(f"перевод сайтов: {строка}")
        except Exception as беда:                # noqa: BLE001 — см. выше
            print(f"перевод сайтов: ошибка {type(беда).__name__}: {беда}")
        finally:
            conn.close()

    список = сайты(args.only, args.days)
    if not список:
        print("сайтов с пометкой «качает сервер» нет")
        return 0
    помню = память()
    for домен, дней in список:
        if not пора(домен, помню, args.force):
            было = (помню.get(домен) or {}).get("когда")
            print(f"{домен}: ходили {было} — ждём {ЖДЁМ_ЧАСОВ} ч, пропуск")
            continue
        # сервер на 1 ГБ (схема сбоев, шаг 11): перед КАЖДЫМ сайтом —
        # свободно ли MemAvailable ≥ site_move.MIN_FREE_MB; мало — сайт
        # откладываем (в память не пишем: следующий запуск возьмёт его)
        свободно = свободно_мб()
        if site_move.memory_short(свободно):
            отложил(домен, свободно)
            continue
        куда = РАБОЧАЯ / домен
        print(f"{домен}: обход на {дней} дн. → {куда}")
        ок = шаг([PY, "scripts/crawl_fetch.py", "--full", "--only", домен,
                  "--days", str(дней), "--out", str(куда)], "качаю")
        if ок:
            ок = шаг([PY, "scripts/parse_live.py", "--dir", str(куда),
                      "--days", str(дней), "--md", str(куда / "matches.md")],
                     "разбираю")
        if ок:
            ок = шаг([PY, "scripts/games_import.py", "--file",
                      str(куда / "games.json"), "--who", f"сервер {домен}"],
                     "вливаю в базу")
        запомнить(домен, "ок" if ок else "сбой")
        if args.only and ок:
            # кнопка «Обойти сайт» (20.09): строка «✅ ВЫПОЛНЕН» в админке;
            # плановый суточный прогон (без --only) статус не трогает
            conn = db.connect()
            try:
                db.set_setting(conn, "site_crawl_result",
                               f"{домен}|{datetime.now():%Y-%m-%d %H:%M}|—")
            finally:
                conn.close()
        print(f"{домен}: {'готово' if ок else 'НЕ ВЫШЛО'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

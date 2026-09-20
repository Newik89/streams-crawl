# -*- coding: utf-8 -*-
r"""Обход сайтов, которые качает САМ СЕРВЕР, а не GitHub.

Часть сайтов закрыта для сети GitHub Actions: `mojtv.hr` с 09.09 отвечает
раннеру «Sorry, you have been blocked» (Cloudflare забанил адрес), до
`rtrs.tv` раннер вовсе не достучался. С нашего DigitalOcean оба открываются.
Решение владельца 10.09: такие сайты качает сервер, раз в сутки.

Домены берутся из базы — у источника в `selector_config` стоит
`by_server: true` (ставится `scripts/source_mode.py --by-server`). Глубина —
его же `max_days`, по умолчанию окно из плана.

    venv/bin/python scripts/server_crawl.py             # если пора
    venv/bin/python scripts/server_crawl.py --force     # не глядя на срок
    venv/bin/python scripts/server_crawl.py --only mojtv.hr

Чаще раза в сутки к сайту не ходим, даже если запустить много раз подряд:
владелец 10.09 — «даже кнопкой не больше одного раза в сутки». Память —
`results/server_crawl.json`.

Запускать ТОЛЬКО на сервере: скрипт выходит в сеть.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
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


def сайты(only: str = "") -> list[tuple[str, int]]:
    """Домены «качает сервер» и их глубина в днях."""
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
            out.append((r["domain"], int(config.get("max_days") or 0)))
        return out
    finally:
        conn.close()


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
    args = ap.parse_args()

    список = сайты(args.only)
    if not список:
        print("сайтов с пометкой «качает сервер» нет")
        return 0
    помню = память()
    for домен, свой_потолок in список:
        if not пора(домен, помню, args.force):
            было = (помню.get(домен) or {}).get("когда")
            print(f"{домен}: ходили {было} — ждём {ЖДЁМ_ЧАСОВ} ч, пропуск")
            continue
        дней = args.days or свой_потолок or 2
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

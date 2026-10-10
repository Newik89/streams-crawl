# -*- coding: utf-8 -*-
r"""Причина провала обхода — одним словом для стука серверу.

Схема сбоев (`deploy/СБОИ-СХЕМА.md`, шаг 3): сторож на сервере раньше видел
только «сбор не успешен» и на любой срыв заказывал ещё один ПОЛНЫЙ сбор
(~1500 запросов) — даже когда сайты закрыли доступ или упал наш же разбор.
Теперь шаг «Стук серверу — закончили» (`crawl.yml`) зовёт этот скрипт, а
код причины едет в стуке (`X-Reason`, подписан вместе с остальным) и ложится
в память сервера (`crawl_hook.remember_failure`); сторож решает по нему
(`watch.RECOVERY`, ключ «<чей>-failed-<причина>»).

Коды (раздел Д схемы) и как их узнаём — по порядку:
  timeout    — job отменён GitHub по лимиту времени (`job.status` = cancelled)
  env        — упала самопроверка окружения или проверка читалок (до обхода)
  pages      — переразбор (шаг 4): страниц прежнего сбора нет (артефакт истёк,
               прогон не найден или не полный обход) — до разбора
  plan       — обход не сделал ни одного запроса (план пуст)
  fetch-ban  — обход упал, и среди неоткрывшихся страниц половина и больше —
               защита: «заглушка защиты», HTTP 403/429
  fetch-down — … половина и больше — сайт лёг: HTTP 5xx (в т. ч. 520–524)
  fetch-net  — … остальное: нет ответа, DNS, таймаут
  few        — разбор дошёл до конца (games.json есть), но игр меньше порога
               (`parse_live --strict`)
  parse      — разбор упал, games.json не написан (ошибка кода)
  push       — результат не запушился
  unknown    — ни один шаг не красный, а job не success (не должно быть)

Запуск (на GitHub, из crawl.yml):
    STEP_ENV=… STEP_READERS=… STEP_FETCH=… STEP_PARSE=… STEP_PUSH=… JOB_STATUS=… \
      python scripts/fail_reason.py            # печатает код
    (переразбор: ещё STEP_PRIOR=… STEP_PAGES=…, а STEP_PUSH — итог шага push_partial)
    python scripts/fail_reason.py --report recon/raw_live/report.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "recon" / "raw_live"

#: доля неоткрывшихся страниц одного класса, с которой класс — причина
ШАРЕ = 0.5
_5XX = re.compile(r"\b5\d\d\b")
_BAN = re.compile(r"\b(403|429)\b")


def classify_rows(rows: list[dict]) -> str:
    """fetch-ban / fetch-down / fetch-net / plan — по строкам report.json."""
    if not rows:
        return "plan"
    broken = [r for r in rows if r.get("итог") in ("не открылась", "заглушка защиты")]
    if not broken:
        return "fetch-net"
    ban = down = 0
    for r in broken:
        why = str(r.get("почему") or "")
        if r.get("итог") == "заглушка защиты" or _BAN.search(why):
            ban += 1
        elif _5XX.search(why):
            down += 1
    if ban >= len(broken) * ШАРЕ:
        return "fetch-ban"
    if down >= len(broken) * ШАРЕ:
        return "fetch-down"
    return "fetch-net"


def reason(outcomes: dict, job_status: str, raw: Path = RAW) -> str:
    """Код причины по итогам шагов (`steps.<id>.outcome`: success / failure /
    cancelled / skipped) и статусу job."""
    if job_status == "cancelled":
        return "timeout"
    red = {k for k, v in outcomes.items() if v in ("failure", "cancelled")}
    if "env" in red or "readers" in red:
        return "env"
    if "prior" in red or "pages" in red:
        return "pages"
    if "fetch" in red:
        try:
            rows = json.loads((raw / "report.json").read_text(encoding="utf-8")).get("строки") or []
        except (OSError, ValueError):
            rows = []
        return classify_rows(rows)
    if "parse" in red:
        try:
            games = json.loads((raw / "games.json").read_text(encoding="utf-8"))
            return "few" if "игр" in games else "parse"
        except (OSError, ValueError):
            return "parse"
    if "push" in red:
        return "push"
    return "unknown"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--report", default="", help="папка с report.json/games.json")
    args = ap.parse_args()
    outcomes = {k: os.environ.get(f"STEP_{k.upper()}", "") for k in
                ("env", "readers", "prior", "pages", "fetch", "parse", "push")}
    raw = Path(args.report).parent if args.report else RAW
    print(reason(outcomes, os.environ.get("JOB_STATUS", ""), raw))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

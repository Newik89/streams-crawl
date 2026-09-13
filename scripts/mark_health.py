# -*- coding: utf-8 -*-
"""Отметить в базе, как прошёл забор на сервере (аудит 07.09, A5).

Сервер о себе ничего не рассказывал: `git pull` мог не пройти (грабля про
`unstaged changes`), заливка — упасть с ошибкой, а дашборд всё это время
рисовал вчерашние цифры как ни в чём не бывало. Теперь `streams-update.sh`
зовёт этот скрипт вокруг двух своих шагов:

    venv/bin/python scripts/mark_health.py pull ok
    venv/bin/python scripts/mark_health.py pull fail "git pull, код 1"
    venv/bin/python scripts/mark_health.py import ok
    venv/bin/python scripts/mark_health.py import fail "games_import, код 1"

Сама отметка живёт в `app/health.py: mark` — оттуда её зовёт и упавшая
заливка. Пишет две настройки:
    last_pull          «ГГГГ-ММ-ДД ЧЧ:ММ|ok» или «…|fail|почему»
    last_import_error  «ГГГГ-ММ-ДД ЧЧ:ММ|почему», при удаче — пусто

Своей бедой цепочку забора не рвёт: что бы ни случилось, код выхода 0 —
иначе неудачная отметка уронила бы сам забор, который она описывает.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("step", choices=["pull", "import"])
    ap.add_argument("result", choices=["ok", "fail"])
    ap.add_argument("why", nargs="?", default="", help="почему не вышло")
    args = ap.parse_args()
    try:
        from app import health
        value = health.mark(args.step, args.result == "ok", args.why)
    except Exception as beda:                      # noqa: BLE001 — см. докстринг
        print(f"отметку не записали: {beda}")
        return 0
    print(f"{args.step}: {value or 'ошибок нет'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

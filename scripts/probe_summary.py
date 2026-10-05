# -*- coding: utf-8 -*-
"""Итог пробы адреса одним словом — для стука серверу (кнопка «Проверить
с GitHub», владелец 20.09). Читает отчёт пробы и печатает короткую сводку,
которая едет в X-What (лимит 60 знаков): «ok-324-metok», «fail-HTTP_520»,
«blocked-cloudflare», «no-answer»."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPORT = Path(__file__).resolve().parent.parent / "recon" / "raw_live" / "report.json"


def main() -> int:
    try:
        rows = json.loads(REPORT.read_text(encoding="utf-8")).get("строки") or []
    except (OSError, ValueError):
        rows = []
    if not rows:
        print("no-answer")
        return 0
    row = rows[0]
    verdict = row.get("итог") or "?"
    why = re.sub(r"[^A-Za-z0-9 ]", "", (row.get("почему") or ""))[:20].strip()
    if verdict == "расписание есть":
        out = f"ok-{row.get('меток времени')}-metok"
    elif verdict == "не открылась":
        out = f"fail-{why or 'net'}"
    elif verdict == "заглушка защиты":
        out = f"blocked-{why or 'protection'}"
    elif verdict == "пусто":
        out = "empty"
    else:
        out = "other"
    # Итог едет в заголовок стука X-What и входит в его подпись: русское слово
    # («пусто») ломало проверку подписи, сервер отвечал 403 и не снимал отметку
    # «сбор идёт» — 05.10 из-за этого не ушла плановая заявка 16:15. Поэтому
    # наружу — только латиница и цифры
    out = re.sub(r"[^A-Za-z0-9_.-]", "", re.sub(r"\s+", "_", out)) or "other"
    print(out[:40])
    return 0


if __name__ == "__main__":
    sys.exit(main())

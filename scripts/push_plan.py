# -*- coding: utf-8 -*-
r"""Отправить пересобранный план обхода в git — с сервера, ключом rw.

План (`data/crawl_plan.json`) пересобирает сервер (`scripts/crawl_plan.py
--json data/crawl_plan.json`), но обход на GitHub берёт его из репозитория,
поэтому после пересборки план нужно туда доставить. Кнопки «GitHub ↔ сервер»
делают это сами (`app/plan_push._push_plan`) — здесь тот же путь для
пересборки целиком: add → commit → pull --rebase → push, при провале дерево
возвращается к чистому.

Перед запуском обязательно сверить домены старого и нового плана (грабля
о пересборке: план собирали с отставшей копии настроек и теряли страницы).

    ssh root@157.245.77.140 "cd streams-schedule && \
        venv/bin/python scripts/push_plan.py 'RTP2 добавлен в план'"
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import plan_push  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    words = " ".join(sys.argv[1:]).strip() or "План обхода пересобран"
    print(plan_push._push_plan(f"План обхода: {words}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

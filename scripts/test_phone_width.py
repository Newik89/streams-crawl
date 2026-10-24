# -*- coding: utf-8 -*-
r"""Витрина на телефоне не шире экрана (владелец 24.10.2026: «почини ширину
таблицы на телефоне»).

До 24.10 на экране 375 px таблица была 600 px: плашки каналов не переносили
текст, и самая длинная («NO| TV 2 Direkte Tekst hørselshem.», ≈250 px) не
давала столбцу каналов сжаться. Сжать пять столбцов тоже не вышло — рвались
посреди слова то имена команд, то каналы.

Правила (обе вкладки: Matches — `schedule.html`, Other Sport —
`schedule_other.html`, блок `@media (max-width:640px)`):
 1. Строка игры в два этажа: сетка «№ | время | значок | матч», ячейка
    каналов (последняя в строке) — второй строкой на всю ширину.
 2. Текст переносится внутри плашки канала и в названии матча.
 3. Заголовок последнего столбца («Channels») на телефоне спрятан.
 4. «live» — под временем.
 5. Шире 640 px — как было: плашка канала текст не переносит.
Сквозная проверка ширины в браузере (320–1600 px) — HANDOFF 24.10; здесь —
сторож, чтобы правила не пропали при правке шаблонов.

Запуск: python scripts/test_phone_width.py — в сеть не ходит.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8")

passed, failed = 0, []


def check(name: str, cond: bool) -> None:
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name)


def phone_block(css: str) -> str:
    """Тело блока @media (max-width:640px) { … } — по скобкам."""
    start = css.find("@media (max-width:640px)")
    if start < 0:
        return ""
    i = css.index("{", start) + 1
    depth = 1
    j = i
    while depth and j < len(css):
        depth += {"{": 1, "}": -1}.get(css[j], 0)
        j += 1
    return css[i:j - 1]


def rule(block: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", block)
    return m.group(1) if m else ""


def main() -> int:
    for name in ("schedule.html", "schedule_other.html"):
        print(name)
        html = (ROOT / "app" / "templates" / name).read_text(encoding="utf-8")
        css = html[html.index("<style>"):html.index("</style>")]
        block = phone_block(css)
        check("есть блок для телефона", bool(block))
        check("строка — сетка «№ | время | значок | матч»",
              "display:grid" in rule(block, "table tr")
              and "grid-template-columns" in rule(block, "table tr"))
        check("таблица и тело — блоки (иначе сетка строки не работает)",
              "display:block" in rule(block, "table, table > tbody"))
        check("каналы — вторым этажом на всю ширину",
              "grid-column:1 / -1" in rule(block, "tr.game > td:last-child"))
        check("плашка канала переносит текст",
              "white-space:normal" in rule(block, ".chan")
              and "overflow-wrap:anywhere" in rule(block, ".chan"))
        check("название матча переносится", "overflow-wrap:anywhere" in rule(block, "td.match"))
        check("заголовок «Channels» спрятан", "display:none" in rule(block, "th:last-child"))
        check("«live» под временем", "display:block" in rule(block, "td.time .live"))
        outside = css.replace(block, "")
        check("на компьютере плашка текст не переносит",
              re.search(r"\.chan \{[^}]*white-space:nowrap", outside) is not None)
        check("последняя ячейка строки — каналы",
              re.search(r'<td>\{%\s*for c in g\.(channels|links)', html) is not None
              and html.index("</td>\n      </tr>") > 0)

    print(f"\nПроверок: {passed + len(failed)}, провалов: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

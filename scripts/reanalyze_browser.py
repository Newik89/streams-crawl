# -*- coding: utf-8 -*-
"""Пересчёт вердиктов по УЖЕ сохранённым страницам из recon/raw_browser.

Зачем: первая версия проверки считала временем и числа с точкой, поэтому
принимала за расписание координаты в картинках (на 2plus2.ua так набралось
850 «меток времени»). Часть сайтов из-за этого получила статус «рабочий»
незаслуженно. Здесь считаем заново, строгой меркой — только `ЧЧ:ММ`.

К сайтам не обращаемся: работаем с тем, что уже скачано.

Запуск:
    venv\\Scripts\\python.exe scripts/reanalyze_browser.py
"""

from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, protection, timemarks  # noqa: E402

RAW = Path(__file__).resolve().parent.parent / "recon" / "raw_browser"

MIN_HITS = 5          # меньше — считаем, что расписания на странице нет

# Старые копии обрезаны на 600 000 знаков (см. app/timemarks.py, случай 5).
# По такой копии вердикт ненадёжен: настоящее расписание могло не поместиться.
CUT_AT = 600_000


def read_page(f: Path) -> str:
    """Копия страницы: обычная или сжатая `.html.gz`."""
    if f.suffix == ".gz":
        with gzip.open(f, "rt", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return f.read_text(encoding="utf-8", errors="replace")

JSON_MARKERS = ("application/ld+json", "__NEXT_DATA__", "__NUXT_DATA__",
                "__NUXT__", "__INITIAL_STATE__")

# Поиск времени и опознание защиты живут в app/timemarks.py и app/protection.py:
# логика общая с probe_browser.py, и раньше эти две копии успели разъехаться.
clean = timemarks.clean


def main() -> int:
    # Консоль Windows по умолчанию cp1251: русский текст выводится крякозябрами,
    # а стрелка «→» вообще роняет скрипт на середине прогона.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:      # на всякий случай, если stdout подменён
        pass

    conn = db.connect()
    files = sorted(list(RAW.glob("*.html")) + list(RAW.glob("*.html.gz")))
    print(f"сохранённых страниц: {len(files)}\n")

    up = down = same = 0
    for f in files:
        domain = f.name[:-8] if f.name.endswith(".html.gz") else f.name[:-5]
        row = conn.execute("SELECT id, access, parse_level FROM sources "
                           "WHERE domain = ?", (domain,)).fetchone()
        if not row:
            continue

        html = read_page(f)
        # обрезанная копия — ровно 600 000 знаков; целая страница длиннее
        # или короче, но никогда не равна отметке обрезки
        cut = len(html) == CUT_AT
        text = clean(html)
        hits = timemarks.count(text)
        blocked = protection.is_blocked(text, html)
        has_json = any(m in html for m in JSON_MARKERS)

        if blocked and hits < MIN_HITS:
            # защита у сайта может стоять и при читаемом расписании — тогда это
            # не «не пускают», а просто повод ходить браузером и с паузами
            access, status, level = "unknown", "closed", "D"
            name = protection.guess_name(html)
            note = f"браузер тоже не пустили: защита{' (' + name + ')' if name else ''}"
        elif hits >= MIN_HITS:
            access, status = "open", "ok"
            level = "A" if has_json else "B"
            note = f"в браузере видно расписание: {hits} меток времени"
            if has_json:
                note += ", есть готовый JSON"
            how = timemarks.describe(text)
            if how:
                note += f", {how}"
        else:
            access, status, level = "unknown", "new", "D"
            note = (f"расписание на странице не найдено ({hits} меток времени) — "
                    f"нужен точный адрес программы или клик по дню")

        if cut:
            note += "; копия страницы обрезана — нужен повторный заход"

        was = row["access"]
        conn.execute("UPDATE sources SET access=?, status=?, parse_level=?, "
                     "notes=? WHERE id=?", (access, status, level, note, row["id"]))
        if was != access:
            arrow = "→ рабочий" if access == "open" else "→ снят с рабочих"
            print(f"{domain:24} {was:12} {arrow:18} ({hits} меток)")
            up += access == "open"
            down += access != "open"
        else:
            same += 1

    conn.commit()
    print(f"\nстало рабочими: {up}, снято: {down}, без изменений: {same}")
    for line in conn.execute("SELECT access, COUNT(*) c FROM sources "
                             "GROUP BY access ORDER BY c DESC"):
        print(f"  {line['access']:14} {line['c']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

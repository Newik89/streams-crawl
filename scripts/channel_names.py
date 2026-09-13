# -*- coding: utf-8 -*-
r"""Канонические имена каналов — правки владельца (6е, B4/B10 и по ходу).

Меняется только `channels.canonical_name` — то, что видно на витрине.
Алиасы (как сайты пишут канал) остаются и продолжают попадать в тот же
канал; слаг не трогаем. Повторный запуск ничего не меняет.

Правила накапливаются в RULES: (страна, регулярка, замена). Канал
опознаётся парой (имя, страна) — правило без страны не пишем.

Гонять на ОБЕИХ базах:
    venv\Scripts\python.exe scripts/channel_names.py
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/channel_names.py"
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

RULES = [
    # владелец 03.09: «Cytavision Sports4 HD» → «Cytavision Sports 4»
    ("CY", re.compile(r"^Cytavision Sports(\d+) HD$"), r"Cytavision Sports \1"),
    # B4: вся линейка sporttv.pt — точку на пробел
    ("PT", re.compile(r"^SPORT\.TV(\d+)$"), r"SPORT TV \1"),
    ("PT", re.compile(r"^SPORT\.TV \+$"), "SPORT TV +"),
    # владелец 04.09: страну у ВСЕХ каналов рисует витрина префиксом
    # «BG| …» — свой префикс из имени MAX Sport убираем (был с 03.09),
    # иначе задвоится
    ("BG", re.compile(r"^bg\| MAX Sport (\d+)$"), r"MAX Sport \1"),
    # B10: канонические имена sport5.co.il — латиницей, вся линейка.
    # Правила без групп: подстановка \1 однажды превратилась в мусорный
    # байт (см. журнал 03.09), поэтому каждое имя — явной парой
    ("IL", re.compile(r"^ספורט 5 Live$"), "Sport 5 Live"),
    ("IL", re.compile(r"^ספורט 5 Stars$"), "Sport 5 Stars"),
    ("IL", re.compile(r"^ספורט 5 Gold$"), "Sport 5 Gold"),
    ("IL", re.compile(r"^ספורט 5\+$"), "Sport 5 Plus"),
    ("IL", re.compile(r"^ספורט 5$"), "Sport 5"),
    # обломок бага 03.09: в шаблоне лежал мусорный байт вместо ``,
    # сработать он не мог ни разу — снят 10.09, ивритское написание
    # уже покрыто строкой выше
    # владелец 04.09: голландская линейка ESPN — «ESPN» без номера значит
    # первый канал; на источнике второй пишут «ESPN 2», так и на витрине
    ("INT", re.compile(r"^ESPN Netherlands$"), "ESPN 1"),
    ("INT", re.compile(r"^ESPN (\d) Netherlands$"), r"ESPN \1"),
    # владелец 05.09: OneSoccer -> One Soccer
    ("CA", re.compile(r"^OneSoccer$"), "One Soccer"),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = db.connect()
    changed = skipped = 0
    try:
        for row in conn.execute(
                "SELECT id, canonical_name, country FROM channels").fetchall():
            name = row["canonical_name"] or ""
            for country, pattern, repl in RULES:
                if row["country"] != country:
                    continue
                new = pattern.sub(repl, name)
                if new == name:
                    continue
                # тёзка в той же стране = два канала с одним именем: правило
                # приводило к общему виду сразу оба написания («Cytavision
                # Sports1 HD» и «Cytavision Sports 1 HD»), и на витрине
                # появлялась пара одинаковых строк (найдено 09.09 по 21
                # пустышке). Такой случай не переименовываем — его должен
                # разобрать человек: слить или назвать иначе
                twin = conn.execute(
                    "SELECT id FROM channels WHERE canonical_name=? AND "
                    "IFNULL(country,'')=IFNULL(?,'') AND id<>?",
                    (new, row["country"], row["id"])).fetchone()
                if twin:
                    print(f"  {row['country']}: {name} → {new} — ПРОПУСК, "
                          f"имя уже занято каналом #{twin['id']}")
                    skipped += 1
                    break
                conn.execute("UPDATE channels SET canonical_name=? "
                             "WHERE id=?", (new, row["id"]))
                print(f"  {row['country']}: {name} → {new}")
                changed += 1
                break
        conn.commit()
        print(f"переименовано: {changed}"
              + (f", пропущено из-за тёзки: {skipped}" if skipped else "")
              + f" (база {db.db_path()})")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

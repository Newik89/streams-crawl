# -*- coding: utf-8 -*-
r"""Канонические имена каналов — правки владельца (6е, B4/B10 и по ходу).

Меняется только `channels.canonical_name` — то, что видно на витрине.
Алиасы (как сайты пишут канал) остаются и продолжают попадать в тот же
канал; слаг не трогаем. Повторный запуск ничего не меняет.

Правила живут в `app/channel_rules.py` (применяются и при рождении
канала); здесь — только прогон по уже заведённым. С 19.09 сервер гоняет
этот скрипт после каждой заливки (`/root/streams-update.sh`), поэтому
правило, добавленное позже канала, доезжает без ручного запуска.

Гонять на ОБЕИХ базах:
    venv\Scripts\python.exe scripts/channel_names.py
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/channel_names.py"
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.channel_rules import RULES  # noqa: E402


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

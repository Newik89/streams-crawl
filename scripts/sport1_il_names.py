# -*- coding: utf-8 -*-
r"""Израильские каналы Sport 1: имя по вывеске сайта, а не по файлу логотипа.

Кейс 09.09 (владелец, номера #1520, #1526, #1537, #1557): на витрине каналы
звались «Sport 1 (4)», «Sport 1 (5)» — цифра в скобках взята из адреса
картинки `sport1-4-channel-logo.svg`. Владелец шёл на сайт, открывал вкладку
«Спорт 1» и матча там не находил: у сайта пять каналов, и номер логотипа с
номером канала не совпадает.

Настоящие имена стоят в заголовках страницы `/broadcast-schedule/`
(`<h2 data-channel-id>`), сверено пробой #254 и составом матчей 13.09:

    логотип sport1-1 → Sport 1   (Ковентри — Брайтон 15:50, Ман Юн — Ман Сити)
    логотип sport1-3 → Sport 2   (Шеффилд — Вулверхэмптон 13:55)
    логотип sport1-4 → Sport 3
    логотип sport1-5 → Sport 4
    логотип sport1-6 → Sport 6   (пятого канала у сайта нет)

Меняем только показываемое имя (`channels.canonical_name`). Алиас источника
(`Sport1 4` → тот же канал) не трогаем: он ключ, по нему обход узнаёт канал,
и переписывать его незачем. `slug` тоже оставляем — он уникален и наружу не
показывается, а «sport-1» в базе уже занят украинским каналом.

Идемпотентен. Показ без `--apply`; гонять на ОБЕИХ базах:
    venv\Scripts\python.exe scripts/sport1_il_names.py --apply
    ssh -i ~/.ssh/streams_schedule root@157.245.77.140 \
        "cd /root/streams-schedule && venv/bin/python scripts/sport1_il_names.py --apply"
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

#: алиас источника (он же номер логотипа) → как канал называется на сайте
NAMES = {"Sport1 1": "Sport 1", "Sport1 3": "Sport 2", "Sport1 4": "Sport 3",
         "Sport1 5": "Sport 4", "Sport1 6": "Sport 6"}
SOURCE = "sport1.maariv.co.il"


def rename(conn: sqlite3.Connection, apply: bool) -> int:
    source = conn.execute("SELECT id FROM sources WHERE domain=?",
                          (SOURCE,)).fetchone()
    if source is None:
        print(f"источника {SOURCE} нет — пропуск")
        return 1
    changed = 0
    for alias, name in NAMES.items():
        row = conn.execute(
            "SELECT ch.id, ch.canonical_name, ch.country FROM channel_aliases ca "
            "JOIN channels ch ON ch.id = ca.channel_id "
            "WHERE ca.alias = ? AND ca.source_id = ?",
            (alias, source["id"])).fetchone()
        if row is None:
            print(f"  {alias}: канала с таким алиасом нет — пропуск")
            continue
        if row["canonical_name"] == name:
            print(f"  {alias}: уже «{name}»")
            continue
        # тёзка той же страны — знак, что канал уже заведён дважды: сливать
        # каналы эта команда не умеет, пусть решает человек
        twin = conn.execute(
            "SELECT id FROM channels WHERE canonical_name = ? AND "
            "IFNULL(country,'') = IFNULL(?,'') AND id <> ?",
            (name, row["country"], row["id"])).fetchone()
        if twin:
            print(f"  {alias}: «{name}» ({row['country']}) уже занят каналом "
                  f"#{twin['id']} — пропуск, нужен разбор вручную")
            continue
        print(f"  {alias}: «{row['canonical_name']}» → «{name}»"
              + ("" if apply else "  (показ)"))
        if apply:
            conn.execute("UPDATE channels SET canonical_name = ? WHERE id = ?",
                         (name, row["id"]))
        changed += 1
    if apply:
        conn.commit()
    print(f"\n{'переименовано' if apply else 'будет переименовано'}: {changed}"
          + ("" if apply else "; чтобы сделать — добавьте --apply"))
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="без него — только показ")
    ap.add_argument("--db", default="", help="другая база (проверка на копии)")
    args = ap.parse_args()
    if args.db:
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
    else:
        conn = db.connect()
    try:
        return rename(conn, args.apply)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

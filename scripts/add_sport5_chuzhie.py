# -*- coding: utf-8 -*-
r"""Пять каналов sport5.co.il, подписанных текстом без логотипа, — книга 170,
слово владельца 20.11.2026: «да, бери эти пять каналов».

Сайт sport5.co.il кроме своих каналов показывает пять чужих: «ספורט 1»,
«ספורט 2», «ספורט 3», «ספורט 4» и «ערוץ One». Их шапки — текст без логотипа,
и до книги 170 разборщик их не читал. Теперь читает; без этого скрипта база
завела бы пять новых каналов с именами на иврите.

Правила по порядку:

 А. «ספורט 1–4» — ТЕ ЖЕ каналы Израиля, что уже идут со своего сайта
    sport1.maariv.co.il (`ПАРЫ`: имя у sport5.co.il → имя канала на своём
    сайте, написание «Sport N» в базе). Сверено 20.11.2026 по матчам (сбор
    #522 против базы сервера): «ספורט 1» — 4 матча из 4 на «Sport 1»,
    «ספורט 4» — 2 из 2 на «Sport 4», «ספורט 2» — Milan — Frosinone на
    «Sport 2»; «ספורט 3» — по имени (единственный его матч в сборе свой сайт
    ведёт на «Sport 6»). Канал ищется по написанию; имя канала на витрине НЕ
    меняется — их назвал владелец («yes Sport 1» …). Нет канала — заводится
    в IL с именем «Sport N».
 Б. «ערוץ One» — такого канала в базе нет: заводится в IL с именем «ONE»
    (владелец переименует в админке, если нужно).
 В. Написание, уже привязанное к каналу у этого сайта, не трогаем.
 Г. Идемпотентно; без `--apply` — только показ, база не меняется.

Гонять в ОБЕИХ базах (сначала без `--apply`), ДО первой заливки сбора,
разобранного кодом книги 170:
    venv\Scripts\python.exe scripts/add_sport5_chuzhie.py --apply
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_sport5_chuzhie.py --apply"
К сайтам не обращается. Тест: `scripts/test_add_sport5_chuzhie.py`.

Откат: удалить пять написаний этого сайта (`channel_aliases`, источник
sport5.co.il) и канал «ONE» — либо вернуть базу из копии до запуска.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402

SPORT5 = "sport5.co.il"
COUNTRY = "IL"
#: правило А: (имя канала у sport5.co.il, имя того же канала на своём сайте)
ПАРЫ = [("ספורט 1", "Sport 1"), ("ספורט 2", "Sport 2"), ("ספורט 3", "Sport 3"), ("ספורט 4", "Sport 4")]
#: правило Б: (имя канала у sport5.co.il, имя нового канала на витрине)
НОВЫЙ = ("ערוץ One", "ONE")


def _key(text: str) -> str:
    return "".join(c for c in (text or "").casefold() if c.isalnum())


def find_channel(conn, name: str, country: str) -> int | None:
    """Канал страны по имени или написанию (без регистра и пробелов)."""
    want = _key(name)
    for r in conn.execute("SELECT id, canonical_name FROM channels WHERE country = ?", (country,)):
        if _key(r["canonical_name"]) == want:
            return r["id"]
    for r in conn.execute("SELECT a.channel_id, a.alias FROM channel_aliases a "
                          "JOIN channels c ON c.id = a.channel_id WHERE c.country = ?", (country,)):
        if _key(r["alias"]) == want:
            return r["channel_id"]
    return None


def _canonical(conn, channel_id: int) -> str:
    return conn.execute("SELECT canonical_name FROM channels WHERE id = ?", (channel_id,)).fetchone()["canonical_name"]


def apply(conn, *, write: bool) -> list[str]:
    """Правила А–Г. Возвращает строки отчёта; write=False — только показ."""
    source = conn.execute("SELECT id FROM sources WHERE domain IN (?, ?)", (SPORT5, "www." + SPORT5)).fetchone()
    if source is None:
        return [f"источника {SPORT5} в базе нет — ничего не сделано"]
    out: list[str] = []
    for raw, name in [*ПАРЫ, НОВЫЙ]:
        bound = conn.execute("SELECT channel_id FROM channel_aliases WHERE alias = ? AND source_id = ?",
                             (raw, source["id"])).fetchone()
        if bound:                                                   # правило В
            out.append(f"{raw}: уже привязано к каналу «{_canonical(conn, bound['channel_id'])}» "
                       f"(id {bound['channel_id']}) — без изменений")
            continue
        channel_id = find_channel(conn, name, COUNTRY)
        if channel_id:                                              # правило А
            canonical = _canonical(conn, channel_id)
            what = f"тот же канал, что «{canonical}» (id {channel_id}); имя на витрине не меняется"
        else:                                                       # правила А (нет канала) и Б
            canonical = name
            what = f"канала «{name}» в стране {COUNTRY} нет — {'заведён' if write else 'заведу'} новый"
        if write:
            channel_id = dictionary.remember_channel(conn, raw, canonical, COUNTRY, source_id=source["id"])
            what += f"; написание привязано (id {channel_id})"
        out.append(f"{raw}: {what}")
    if write:
        conn.commit()
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="пять каналов sport5.co.il без логотипа: привязать к каналам базы")
    ap.add_argument("--apply", action="store_true", help="записать (без него — показ)")
    args = ap.parse_args()
    conn = db.connect()
    try:
        print(f"база: {db.db_path()}" + ("" if args.apply else "  (только показ)"))
        for line in apply(conn, write=args.apply):
            print("  " + line)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

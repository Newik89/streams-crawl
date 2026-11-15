# -*- coding: utf-8 -*-
r"""Занести в книгу знаний слова, которые сайт ставит перед хозяевами или
после гостей (книга 137).

Слово владельца 15.11.2026: «да, заноси в книгу знаний». Сами такие слова в
книгу попадают, когда срез подтверждает эталон (`dictionary.note_trims`,
книга 136). Но есть слова, которые эталону срезать не приходится: пара с
ними сходится и так («Raiffeisen Liga e Pare Prishtina e Re — Liria» —
сравнение имён терпит лишнее в начале названия клуба). Тогда в книгу они
сами не попадут, а у матча, которого эталон не знает (младшая лига), так и
останутся в имени команды. Такие слова заносятся отсюда — данными, а не
кодом в разборщике одного сайта: из книги их читает общий разбор
(`pipeline.known_trims`), и они годятся всем сайтам того же языка.

Правила:
  С1. `WORDS` — список (класс, слова, сайт, откуда знаем). Класс — где слова
      стоят: `live.KNOWN_HOME` (перед хозяевами) или `live.KNOWN_AWAY`
      (после гостей). Язык записи — языки сайта, как у `note_trims` (З3).
  С2. Запись — `dictionary.note_error`: одна строка на (слова, язык,
      класс); повторный запуск ничего не плодит. Кто записал —
      «владелец 15.11» (слова занесены по его слову, не программой).
  С3. Без `--apply` — только показ: что уже в книге, что будет записано.
  С4. К сайтам не обращается. На GitHub слова уедут с ближайшей выгрузкой
      словаря (`scripts/dict_push.py`, дважды в день).

    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/kniga_slova.py --apply"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary, live, site_lang  # noqa: E402

WHO = "владелец 15.11"
#: С1: (класс, слова, сайт, откуда знаем)
WORDS = [
    # ipko.tv, косовские Sport 1–6: «Futboll: <турнир> <хозяева> - <гости>»,
    # заголовки сбора 15.11 и книги 094
    (live.KNOWN_HOME, "Liga e Kombeve", "ipko.tv", "Лига наций; сбор 15.11"),
    (live.KNOWN_HOME, "Liga e Kampioneve", "ipko.tv", "Лига чемпионов; сбор 15.11"),
    (live.KNOWN_HOME, "Raiffeisen Liga e Pare", "ipko.tv", "первая лига Косова со спонсором; сбор 15.11"),
    (live.KNOWN_HOME, "Liga e Pare", "ipko.tv", "первая лига Косова; сбор 15.11"),
    (live.KNOWN_HOME, "ALBI Mall Superliga", "ipko.tv", "суперлига Косова со спонсором; сбор 15.11"),
    (live.KNOWN_HOME, "Procredit Superliga", "ipko.tv", "суперлига Косова, прежний спонсор; #9470, книга 094"),
    (live.KNOWN_HOME, "Superliga", "ipko.tv", "суперлига Косова; книга 094"),
    (live.KNOWN_HOME, "La Liga", "ipko.tv", "сбор 15.11"),
    (live.KNOWN_HOME, "Europa League", "ipko.tv", "сбор 15.11"),
    (live.KNOWN_HOME, "Conference League", "ipko.tv", "сбор 15.11"),
    (live.KNOWN_HOME, "NBA", "ipko.tv", "сбор 15.11"),
]


def lang_of(site: str) -> str:
    """С1: язык записи — языки сайта без английского (как `note_trims`, З3)."""
    langs = site_lang.of(site) or frozenset()
    return " ".join(sorted(langs - {"en"})) or "en"


def apply(conn, *, write: bool, words=None) -> list[str]:
    """Правила С1–С3. Возвращает строки отчёта; write=False — только показ."""
    out = []
    for cls, phrase, site, why in (WORDS if words is None else words):
        lang = lang_of(site)
        have = conn.execute(
            "SELECT 1 FROM dictionary_errors WHERE alias = ? AND lang IS ? AND class = ?",
            (phrase, lang, cls)).fetchone()
        if have:
            out.append(f"«{phrase}» ({cls}, {lang}) — уже в книге")
            continue
        if write:
            dictionary.note_error(conn, phrase, cls, lang=lang, source_domain=site,
                                  note=why, answered_by=WHO)
            out.append(f"«{phrase}» ({cls}, {lang}) — записано")
        else:
            out.append(f"«{phrase}» ({cls}, {lang}) — будет записано")
    if write:
        conn.commit()
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="слова перед хозяевами и после гостей — в книгу знаний")
    ap.add_argument("--apply", action="store_true", help="записать (без него — показ)")
    args = ap.parse_args()
    conn = db.connect()
    try:
        print(f"база: {db.db_path()}" + ("" if args.apply else "  (только показ)"))
        for line in apply(conn, write=args.apply):
            print("  " + line)
        total = conn.execute(
            "SELECT COUNT(*) FROM dictionary_errors WHERE class IN (?, ?)",
            (live.KNOWN_HOME, live.KNOWN_AWAY)).fetchone()[0]
        print(f"слов о лишнем у пары в книге знаний: {total}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

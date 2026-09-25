# -*- coding: utf-8 -*-
r"""Польза языков эталона: что дал каждый язык словарю (только чтение).

Показывает по базе:
  * написания команд и лиг по языкам (`team_aliases.lang` /
    `league_aliases.lang`); у языков, подключённых 25.09.2026
    (sk/de/pt/it/fr/es/nl/sv/da), отдельно счёт «впервые» — написания,
    текста которых не было у прежних языков (честная польза: совпадение
    с уже известным написанием покрытия не добавляет);
  * сколько игр в базе с меткой эталона `fs:` и сколько без, и какие
    сайты дают игры без метки (одна игра числится у каждого своего сайта);
  * карточки языковых версий эталона — все ли живы (status/last_success).

Ничего не меняет и в сеть не ходит. Запуск:
    venv\Scripts\python.exe scripts/lang_report.py
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/lang_report.py"
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db                                   # noqa: E402
from app.parsers.flashscore_mobi import LOCALES      # noqa: E402

#: языки, подключённые 25.09.2026 («языки источников знаем —
#: пусть словарь заполняется сам»)
NEW_LANGS = ("sk", "de", "pt", "it", "fr", "es", "nl", "sv", "da")


def _counts(conn, table: str) -> list:
    return conn.execute(
        f"SELECT lang, COUNT(*) AS n FROM {table} "
        f"GROUP BY lang ORDER BY n DESC").fetchall()


def _fresh(conn, table: str, lang: str) -> int:
    """Сколько написаний языка встречаются в словаре впервые: того же
    текста нет ни у одного из прежних языков (включая безъязыковые)."""
    marks = ",".join("?" * len(NEW_LANGS))
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} a WHERE a.lang = ? AND NOT EXISTS ("
        f"  SELECT 1 FROM {table} b WHERE b.alias = a.alias "
        f"  AND (b.lang IS NULL OR b.lang NOT IN ({marks})))",
        (lang, *NEW_LANGS)).fetchone()[0]


def _section(conn, table: str, title: str) -> None:
    rows = _counts(conn, table)
    total = sum(r["n"] for r in rows)
    print(f"\n{title}: всего {total}")
    for r in rows:
        lang = r["lang"] or "(без языка)"
        line = f"  {lang:12} {r['n']:6}"
        if r["lang"] in NEW_LANGS:
            line += f"   впервые {_fresh(conn, table, r['lang']):5}   ← новый 25.09"
        print(line)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = db.connect()
    try:
        print("=== Написания по языкам ===")
        _section(conn, "team_aliases", "команды")
        _section(conn, "league_aliases", "лиги")

        total, with_fs = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN flags LIKE 'fs:%' THEN 1 ELSE 0 "
            "END) FROM events").fetchone()
        with_fs = with_fs or 0
        without = total - with_fs
        pct = (100.0 * without / total) if total else 0.0
        print("\n=== Метка эталона у игр в базе ===")
        print(f"игр {total}, с меткой fs: {with_fs}, "
              f"без метки {without} ({pct:.1f}%)")
        print("без метки, по сайтам (топ-15):")
        for r in conn.execute(
                "SELECT s.domain, COUNT(DISTINCT e.id) AS games "
                "FROM events e "
                "JOIN event_channels ec ON ec.event_id = e.id "
                "JOIN sources s ON s.id = ec.source_id "
                "WHERE e.flags IS NULL OR e.flags NOT LIKE 'fs:%' "
                "GROUP BY s.domain ORDER BY games DESC LIMIT 15"):
            print(f"  {r['domain']:24} {r['games']:4}")

        print("\n=== Карточки языковых версий эталона ===")
        marks = ",".join("?" * len(LOCALES))
        for r in conn.execute(
                f"SELECT domain, enabled, status, last_success FROM sources "
                f"WHERE domain IN ({marks}) ORDER BY domain", list(LOCALES)):
            mark = " ← новый" if LOCALES.get(r["domain"]) in NEW_LANGS else ""
            state = "вкл " if r["enabled"] else "ВЫКЛ"
            print(f"  {r['domain']:22} {state} {r['status']:8} "
                  f"last_success={r['last_success'] or '—'}{mark}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

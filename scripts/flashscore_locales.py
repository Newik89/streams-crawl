# -*- coding: utf-8 -*-
r"""Завести языковые версии эталона flashscore в базе (этап 6е, A2).

Одна карточка на язык, один адрес `?d={DAYNUM}`, глубина — в
`selector_config.days_ahead`: греческая, венгерская и болгарская — 7 дней
(именно с их сайтов шли игры без английских имён), остальные — по странице
в день. Повторный запуск ничего не дублирует и глубину, выставленную
владельцем, не трогает. К сайтам не обращается.

Гонять на обеих базах (локальной и серверной), как `source_config.py`:
    venv\Scripts\python.exe scripts/flashscore_locales.py
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/flashscore_locales.py"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.parsers.flashscore_mobi import LOCALES  # noqa: E402

#: страна карточки и глубина по языку
COUNTRY = {"el": "GR", "bg": "BG", "hu": "HU", "ro": "RO", "tr": "TR",
           "pl": "PL", "ru": "RU", "uk": "UA", "cs": "CZ", "hr": "HR"}
DEEP = {"el", "hu", "bg", "hr"}    # 7 дней; остальные — 1
#: у этих языков берём и баскетбол: греческие (cosmote, novasports),
#: турецкие, русские и сербохорватские сетки держат много баскета, и его
#: имена оставались без канона (сервер 03.09: Αναντολού Εφές, Ερυθρός
#: Αστέρας). Раздел у каждой локали зовётся по-своему — обкатка №212:
#: /basketball/ у tr и hr отдал 404
BASKET = {"el": "basketball", "tr": "basketbol", "ru": "basketball",
          "hr": "kosarka"}

NOTE = ("языковая версия эталона flashscore (6е, A2): те же fs_id, имена "
        "по-местному; на витрину не идёт — parse_live прикладывает имена к "
        "эталону, games_import учит словарь по fs_id (canon.learn_by_id). "
        "Время местное, не используется. Глубина — days_ahead в карточке")


def _channels(conn, source_id: int, domain: str, lang: str) -> None:
    """Разделы-страницы локали. Футбол — у всех; баскетбол — языкам из
    BASKET. Повторный запуск ничего не дублирует."""
    sections = [("football", f"https://{domain}/?d={{DAYNUM}}")]
    if lang in BASKET:
        sections.append(("basketball",
                         f"https://{domain}/{BASKET[lang]}/?d={{DAYNUM}}"))
    for raw_name, page_url in sections:
        row = conn.execute(
            "SELECT id, page_url FROM source_channels "
            "WHERE source_id=? AND raw_name=?",
            (source_id, raw_name)).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO source_channels (source_id, raw_name, page_url, "
                "include) VALUES (?,?,?,1)", (source_id, raw_name, page_url))
        elif row["page_url"] != page_url:
            conn.execute("UPDATE source_channels SET page_url=? WHERE id=?",
                         (page_url, row["id"]))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = db.connect()
    added = kept = 0
    try:
        for domain, lang in LOCALES.items():
            row = conn.execute("SELECT id, selector_config FROM sources "
                               "WHERE domain=?", (domain,)).fetchone()
            depth = 7 if lang in DEEP else 1
            if row:
                config = json.loads(row["selector_config"] or "{}") or {}
                if "days_ahead" not in config:
                    config["days_ahead"] = depth
                    conn.execute("UPDATE sources SET selector_config=? WHERE id=?",
                                 (json.dumps(config, ensure_ascii=False), row["id"]))
                _channels(conn, row["id"], domain, lang)
                kept += 1
                continue
            cur = conn.execute(
                "INSERT INTO sources (domain, name, base_url, country, timezone, "
                "role, access, url_pattern, needs_js, selector_config, priority, "
                "enabled, status, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (domain, f"Flashscore {lang} (локаль эталона)",
                 f"https://{domain}/", COUNTRY.get(lang, "INT"), "UTC",
                 "schedule", "open", f"https://{domain}/?d={{DAYNUM}}", 0,
                 json.dumps({"days_ahead": depth, "lang": lang}), 100, 1, "ok",
                 NOTE))
            _channels(conn, cur.lastrowid, domain, lang)
            added += 1
        conn.commit()
        print(f"локали эталона: добавлено {added}, уже были {kept}")
        for r in conn.execute("SELECT domain, url_pattern, selector_config FROM sources "
                              "WHERE domain IN (%s) ORDER BY domain"
                              % ",".join("?" * len(LOCALES)), list(LOCALES)):
            print(f"  {r['domain']:22} {r['url_pattern']:40} {r['selector_config']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

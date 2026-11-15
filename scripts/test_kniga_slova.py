# -*- coding: utf-8 -*-
r"""Книга 137 (15.11.2026): слова, которые сайт ставит перед хозяевами,
занесены в книгу знаний данными (`scripts/kniga_slova.py`, слово владельца
«да, заноси в книгу знаний») — и общий разбор режет по ним.

Проверяет правила С1–С3 скрипта и весь путь: книга в базе → файл словаря →
`pipeline.known_trims` → `pipeline.trim_over_pair` для строки, которую эталон
не знает. В сеть не ходит, база временная.

Запуск: python scripts/test_kniga_slova.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="kniga-slova-test-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import db, live, pipeline, site_lang  # noqa: E402
from app.parsers import Program  # noqa: E402
import kniga_slova  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def в_книге(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM dictionary_errors").fetchone()[0]


db.init_db()
conn = db.connect()

print("С3. Показ без --apply")
строки = kniga_slova.apply(conn, write=False)
проверка("показ ничего не пишет и называет каждое слово списка",
         (в_книге(conn), len(строки), all("будет записано" in с for с in строки)),
         (0, len(kniga_slova.WORDS), True))

print("С1–С2. Запись")
kniga_slova.apply(conn, write=True)
записи = {r["alias"]: (r["class"], r["lang"], r["source_domain"], r["answered_by"]) for r in conn.execute(
    "SELECT * FROM dictionary_errors")}
проверка("каждое слово — своя строка книги: класс, язык сайта, сайт, кто записал",
         (len(записи), записи.get("Raiffeisen Liga e Pare"), записи.get("NBA")),
         (len(kniga_slova.WORDS), (live.KNOWN_HOME, "sq", "ipko.tv", kniga_slova.WHO),
          (live.KNOWN_HOME, "sq", "ipko.tv", kniga_slova.WHO)))
проверка("язык записи — языки сайта без английского, как у срезов по эталону",
         (kniga_slova.lang_of("ipko.tv"), kniga_slova.lang_of("webtv.sk"),
          " ".join(sorted(site_lang.of("webtv.sk") - {"en"}))), ("sq", "cs sk", "cs sk"))
до = в_книге(conn)
строки = kniga_slova.apply(conn, write=True)
проверка("повторный запуск ничего не плодит и говорит «уже в книге»",
         (в_книге(conn), all("уже в книге" in с for с in строки)), (до, True))
проверка("классы слов списка — только классы книги про лишнее у пары",
         {cls for cls, _p, _s, _w in kniga_slova.WORDS} <= {live.KNOWN_HOME, live.KNOWN_AWAY})

print("Весь путь: книга → файл словаря → общий разбор")
файл = TMP / "dictionaries.json"
файл.write_text(json.dumps({"dictionary_errors": [
    {"alias": r["alias"], "lang": r["lang"], "class": r["class"], "answered_by": r["answered_by"]}
    for r in conn.execute("SELECT alias, lang, class, answered_by FROM dictionary_errors")]}, ensure_ascii=False),
    encoding="utf-8")
известное = pipeline.known_trims(файл)


def строка(сайт: str, пара: str):
    home, _, away = пара.partition(" - ")
    p = Program(channel_raw="Sport 1", title=f"Futboll: {пара}",
                start=datetime(2026, 11, 22, 14, 0, tzinfo=KYIV), raw_time="", match_raw=пара,
                live_raw="live", league_raw="", sport_raw="", source_url="", extra={})
    got = pipeline.trim_over_pair(p, live.Verdict(True, "", live_marker="live", home=home, away=away),
                                  None, None, langs=site_lang.of(сайт), known=известное)
    return None if got is None else (got.home, got.away, p.extra[pipeline.TRIMMED]["срезано"])


проверка("ipko.tv, матча эталон не знает: «Raiffeisen Liga e Pare Drita B - Vushtrria» → «Drita B - Vushtrria»",
         строка("ipko.tv", "Raiffeisen Liga e Pare Drita B - Vushtrria"),
         ("Drita B", "Vushtrria", "Raiffeisen Liga e Pare"))
проверка("срезается самая длинная известная цепочка: «Liga e Pare …» без спонсора и «ALBI Mall Superliga …»",
         [строка("ipko.tv", "Liga e Pare Drita B - Vushtrria"),
          строка("ipko.tv", "albi mall superliga Drita - Ballkani")],
         [("Drita B", "Vushtrria", "Liga e Pare"), ("Drita", "Ballkani", "albi mall superliga")])
проверка("другой сайт на албанском получает тот же опыт; сайт на другом языке — нет",
         (строка("tring.al", "Liga e Kampioneve Bodo Glimt - Lille"), строка("webtv.sk", "Liga e Kampioneve Bodo Glimt - Lille")),
         (("Bodo Glimt", "Lille", "Liga e Kampioneve"), None))
проверка("пара без известных слов и имя из одного известного слова не трогаются",
         [строка("ipko.tv", "Prishtina - Drita"), строка("ipko.tv", "Superliga - Drita")], [None, None])
conn.close()

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

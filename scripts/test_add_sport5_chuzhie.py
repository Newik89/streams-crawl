# -*- coding: utf-8 -*-
r"""Пять каналов sport5.co.il без логотипа (`scripts/add_sport5_chuzhie.py`,
книга 170, слово владельца 20.11.2026: «да, бери эти пять каналов»).

Проверяет правила скрипта и весь путь: строка сайта «ספורט 1» → отметка в
канал, который владелец назвал «yes Sport 1» (а не новый канал на иврите).

Запуск: python scripts/test_add_sport5_chuzhie.py — в сеть не ходит, база временная.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="add-sport5-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")
os.environ.pop("STREAMS_LOCAL", None)

from app import db, store  # noqa: E402
from app.parsers import sport5_co_il  # noqa: E402

spec = importlib.util.spec_from_file_location("add_sport5_chuzhie", ROOT / "scripts" / "add_sport5_chuzhie.py")
add = importlib.util.module_from_spec(spec)
spec.loader.exec_module(add)

passed, failed = 0, []


def check(name: str, cond: bool, extra="") -> None:
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def counts(conn) -> tuple[int, int]:
    return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("channels", "channel_aliases"))


def name_of(conn, channel_id) -> str:
    return conn.execute("SELECT canonical_name FROM channels WHERE id = ?", (channel_id,)).fetchone()["canonical_name"]


def main() -> int:
    conn = db.connect()
    db.init_db(conn)
    print("нет источника — ничего не делаем")
    check("скрипт сообщает и базу не трогает",
          add.apply(conn, write=True) == ["источника sport5.co.il в базе нет — ничего не сделано"] and counts(conn) == (0, 0))

    for domain in ("sport5.co.il", "sport1.maariv.co.il"):
        conn.execute("INSERT INTO sources (domain, name, base_url, country, timezone, enabled, role, access, status) "
                     "VALUES (?, ?, ?, 'IL', 'Asia/Jerusalem', 1, 'schedule', 'open', 'ok')",
                     (domain, domain, f"https://{domain}/"))
    sport5 = conn.execute("SELECT * FROM sources WHERE domain = 'sport5.co.il'").fetchone()
    maariv = conn.execute("SELECT * FROM sources WHERE domain = 'sport1.maariv.co.il'").fetchone()
    # как в базе сервера 20.11: каналы своего сайта названы владельцем, написание «Sport N» — без источника;
    # «Sport 3» нарочно не заведён — проверим ветку «канала нет»
    ids = {}
    for canonical, alias, logo in (("yes Sport 1", "Sport 1", "Sport1 1"), ("yes sport 2", "Sport 2", "Sport1 3"),
                                   ("ISR| YES SPORT 4 FHD", "Sport 4", "Sport1 5")):
        ids[alias] = conn.execute("INSERT INTO channels (canonical_name, slug, country) VALUES (?, ?, 'IL')",
                                  (canonical, alias.lower().replace(" ", "-") + "-il")).lastrowid
        conn.execute("INSERT INTO channel_aliases (channel_id, alias, source_id) VALUES (?, ?, NULL)", (ids[alias], alias))
        conn.execute("INSERT INTO channel_aliases (channel_id, alias, source_id) VALUES (?, ?, ?)",
                     (ids[alias], logo, maariv["id"]))
    # тёзка в другой стране — трогать нельзя
    conn.execute("INSERT INTO channels (canonical_name, slug, country) VALUES ('Sport 1', 'sport-1', 'UA')")
    conn.commit()
    before = counts(conn)

    print("показ (без --apply)")
    lines = add.apply(conn, write=False)
    check("правило Г: показ базу не меняет", counts(conn) == before, str(counts(conn)))
    check("показ называет все пять каналов", len(lines) == 5 and all(raw in "\n".join(lines) for raw, _ in [*add.ПАРЫ, add.НОВЫЙ]))

    print("запись (--apply)")
    add.apply(conn, write=True)

    def bound(raw):
        row = conn.execute("SELECT channel_id FROM channel_aliases WHERE alias = ? AND source_id = ?",
                           (raw, sport5["id"])).fetchone()
        return row["channel_id"] if row else None

    check("правило А: «ספורט 1», «ספורט 2», «ספורט 4» привязаны к каналам своего сайта",
          (bound("ספורט 1"), bound("ספורט 2"), bound("ספורט 4")) == (ids["Sport 1"], ids["Sport 2"], ids["Sport 4"]))
    check("правило А: имена каналов на витрине не изменились",
          [name_of(conn, ids[a]) for a in ("Sport 1", "Sport 2", "Sport 4")] == ["yes Sport 1", "yes sport 2", "ISR| YES SPORT 4 FHD"])
    check("правило А: канала «Sport 3» не было — заведён в IL с этим именем",
          name_of(conn, bound("ספורט 3")) == "Sport 3"
          and conn.execute("SELECT country FROM channels WHERE id = ?", (bound("ספורט 3"),)).fetchone()[0] == "IL")
    check("правило Б: «ערוץ One» — новый канал «ONE» в IL", name_of(conn, bound("ערוץ One")) == "ONE")
    check("тёзка «Sport 1» в другой стране не тронут",
          conn.execute("SELECT COUNT(*) FROM channel_aliases a JOIN channels c ON c.id = a.channel_id "
                       "WHERE c.country = 'UA'").fetchone()[0] == 0)
    check("каналов прибавилось два (Sport 3 и ONE), написаний — пять", counts(conn) == (before[0] + 2, before[1] + 5),
          str(counts(conn)))

    print("повторный запуск")
    after = counts(conn)
    lines = add.apply(conn, write=True)
    check("правила В и Г: второй запуск ничего не меняет", counts(conn) == after and all("без изменений" in x for x in lines))

    print("весь путь: строка сайта → канал базы")
    страница = ('<table><tr class="tr-header"><th colspan="4"><span class="channel-text">ספורט 1</span>'
                '<span class="channel_numbers"></span></th></tr>'
                '<tr><td class="date"><div>21:30</div></td><td class="text">בונדסליגה: באיירן מינכן - קלן, מחזור 10</td></tr></table>')
    programs = sport5_co_il.parse(страница, tz="Asia/Jerusalem",
                                  url="https://www.sport5.co.il/Ajax/GetBroadcastSheetData.aspx?date=20%2F11%2F2026")
    check("разборщик читает шапку без логотипа", [p.channel_raw for p in programs] == ["ספורט 1"])
    check("база узнаёт написание — канал «yes Sport 1», новый не заводится",
          store._channel_id(conn, programs[0].channel_raw, sport5) == ids["Sport 1"] and counts(conn) == after)

    conn.close()
    print(f"\nитог: {passed} зелёных, {len(failed)} красных")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

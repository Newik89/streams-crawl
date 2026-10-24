# -*- coding: utf-8 -*-
r"""Заведение RTSH Sport / RTSH 1 / RTSH 2 страницами livesoccertv
(`scripts/add_rtsh.py`, слово владельца 24.10.2026).

Проверяет правила скрипта и весь путь: страница канала livesoccertv →
имя канала из заголовка → отметка в канал страны AL (а не новый канал со
страной источника) → три страницы в плане обхода.

Запуск: python scripts/test_add_rtsh.py — в сеть не ходит, база временная.
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

TMP = Path(tempfile.mkdtemp(prefix="add-rtsh-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")
os.environ.pop("STREAMS_LOCAL", None)

from app import crawl, db, store  # noqa: E402
from app.parsers import livesoccertv_com  # noqa: E402

spec = importlib.util.spec_from_file_location("add_rtsh", ROOT / "scripts" / "add_rtsh.py")
add_rtsh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(add_rtsh)

passed, failed = 0, []


def check(name: str, cond: bool, extra="") -> None:
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def counts(conn) -> tuple[int, int, int]:
    return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("channels", "channel_aliases", "source_channels"))


#: страница канала livesoccertv с одним будущим матчем (разметка как у сайта
#: 24.10: span.ts[dv] — миллисекунды UTC, ссылка /match/, турнир /competitions/)
PAGE = """<html><head><title>RTSH Sport TV Schedule, Broadcast Rights - Live Soccer TV</title></head>
<body><table>
<tr id="1" class="matchrow" data-timer="" data-ko="2026-11-01 13:30:00" data-has-tv="0">
<td class="timecol"><span class="timecell"><span id="ko1" class="ts" dv="1793971800000"
 df="h:MMtt">1:30pm</span></span></td>
<td class="matchcol"><a href="/match/tirana-vs-egnatia/abc">Tirana vs Egnatia Rrogozhinë</a></td>
<td class="compcell_right"><a href="/competitions/albania/superliga/">Kategoria Superiore</a></td>
</tr></table></body></html>"""


def main() -> int:
    conn = db.connect()
    db.init_db(conn)
    # как у живого источника: в план идут только enabled + schedule + open + ok
    conn.execute("INSERT INTO sources (domain, name, base_url, country, timezone, enabled, "
                 "role, access, status) VALUES ('livesoccertv.com', 'Live Soccer TV', "
                 "'https://www.livesoccertv.com/', 'INT', 'UTC', 1, 'schedule', 'open', 'ok')")
    lstv = conn.execute("SELECT * FROM sources WHERE domain = 'livesoccertv.com'").fetchone()
    # прежняя страница источника — должна остаться как была
    conn.execute("INSERT INTO source_channels (source_id, raw_name, page_url, include) "
                 "VALUES (?, 'SuperSport 1 Digitalb', "
                 "'https://www.livesoccertv.com/channels/supersport-digitalb/', 1)", (lstv["id"],))
    # RTSH 1 уже есть в Албании (другое написание) — должен найтись, не дублироваться
    conn.execute("INSERT INTO channels (canonical_name, slug, country) "
                 "VALUES ('Rtsh  1', 'rtsh-1-al', 'AL')")
    old_rtsh1 = conn.execute("SELECT id FROM channels WHERE slug = 'rtsh-1-al'").fetchone()[0]
    # тёзка RTSH 2 в другой стране — брать нельзя (канал — пара имя + страна)
    conn.execute("INSERT INTO channels (canonical_name, slug, country) "
                 "VALUES ('RTSH 2', 'rtsh-2-xk', 'XK')")
    foreign = conn.execute("SELECT id FROM channels WHERE slug = 'rtsh-2-xk'").fetchone()[0]
    conn.commit()

    print("1. показ без --apply")
    before = counts(conn)
    lines = add_rtsh.apply(conn, write=False)
    check("показ ничего не пишет", counts(conn) == before, (before, counts(conn)))
    check("показ называет все три канала", len(lines) == 3 and all(
        n in "\n".join(lines) for n, _ in add_rtsh.CHANNELS))

    print("2. --apply")
    add_rtsh.apply(conn, write=True)
    rows = {r["raw_name"]: r for r in conn.execute(
        "SELECT * FROM source_channels WHERE source_id = ?", (lstv["id"],))}
    for name, slug in add_rtsh.CHANNELS:
        r = rows.get(name)
        check(f"страница {name}: адрес и include",
              r is not None and r["page_url"] == f"https://www.livesoccertv.com/channels/{slug}/"
              and r["include"] == 1, dict(r) if r else None)
        ch = conn.execute("SELECT country FROM channels WHERE id = ?",
                          (r["channel_id"] if r else -1,)).fetchone()
        check(f"канал {name} — страны AL", ch is not None and ch["country"] == "AL")
    check("RTSH 1 — прежний канал AL, не новый", rows["RTSH 1"]["channel_id"] == old_rtsh1)
    check("RTSH 2 — не тёзка из XK", rows["RTSH 2"]["channel_id"] != foreign)
    check("прежняя страница источника цела", "SuperSport 1 Digitalb" in rows)
    check("всего страниц у источника — 4", len(rows) == 4, len(rows))

    print("3. повторный --apply ничего не дублирует")
    after = counts(conn)
    add_rtsh.apply(conn, write=True)
    check("строк столько же", counts(conn) == after, (after, counts(conn)))

    print("4. путь: страница → имя → канал AL")
    progs = livesoccertv_com.parse(PAGE, tz="Europe/Kyiv",
                                   url="https://www.livesoccertv.com/channels/rtsh-sport-albania/")
    check("разбор взял матч", len(progs) == 1, len(progs))
    raw = progs[0].channel_raw if progs else ""
    check("имя канала со страницы — «RTSH Sport»", raw == "RTSH Sport", raw)
    check("матч и турнир", bool(progs) and progs[0].match_raw == "Tirana - Egnatia Rrogozhinë"
          and progs[0].league_raw == "Kategoria Superiore")
    before = counts(conn)
    got = store._channel_id(conn, raw, lstv)
    check("заливка кладёт отметку в канал AL RTSH Sport",
          got == rows["RTSH Sport"]["channel_id"], (got, rows["RTSH Sport"]["channel_id"]))
    check("нового канала заливка не завела", counts(conn)[0] == before[0])

    print("5. план обхода")
    plan = {s["domain"]: s for s in crawl.templates(conn, ["livesoccertv.com"])}
    src = plan.get("livesoccertv.com") or {}
    patterns = {c["pattern"] for c in src.get("channels", [])}
    for name, slug in add_rtsh.CHANNELS:
        check(f"в плане страница {name}",
              f"https://www.livesoccertv.com/channels/{slug}/" in patterns)
    check("в плане 4 страницы — по одной на канал", len(src.get("channels", [])) == 4,
          len(src.get("channels", [])))

    print("6. источника нет — ничего не делается")
    conn.execute("UPDATE sources SET domain = 'x.invalid' WHERE id = ?", (lstv["id"],))
    before = counts(conn)
    out = add_rtsh.apply(conn, write=True)
    check("отчёт «источника нет», база не тронута",
          "нет" in out[0] and counts(conn) == before, out)
    conn.close()

    print(f"\nПроверок: {passed + len(failed)}, провалов: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

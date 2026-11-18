# -*- coding: utf-8 -*-
r"""ON Sport с yallakora.com и STC TV страницей livesoccertv
(`scripts/add_on_sport_stc.py`, книга 167, слова владельца 19.11.2026).

Проверяет правила скрипта и весь путь: строка yallakora → канал Египта, тот
же, что у livesoccertv (имя, которое дал каналу владелец, не меняется);
страница «ON Sport 2» снята с обхода, но канал цел; STC TV — канал страны
SA со страницей livesoccertv; оба сайта в плане обхода.

Запуск: python scripts/test_on_sport_stc.py — в сеть не ходит, база временная.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="on-sport-stc-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")
os.environ.pop("STREAMS_LOCAL", None)

from app import crawl, db, store  # noqa: E402

spec = importlib.util.spec_from_file_location("add_on_sport_stc", ROOT / "scripts" / "add_on_sport_stc.py")
skript = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skript)

passed, failed = 0, []


def check(name: str, cond: bool, extra="") -> None:
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def counts(conn) -> tuple[int, ...]:
    return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("sources", "channels", "channel_aliases", "source_channels"))


def main() -> int:
    conn = db.connect()
    db.init_db(conn)
    conn.execute("INSERT INTO sources (domain, name, base_url, country, timezone, enabled, role, access, status) "
                 "VALUES ('livesoccertv.com', 'Live Soccer TV', 'https://www.livesoccertv.com/', 'INT', 'UTC', "
                 "1, 'schedule', 'open', 'ok')")
    lstv = conn.execute("SELECT * FROM sources WHERE domain = 'livesoccertv.com'").fetchone()
    # как на сервере 19.11: три канала владелец переименовал сам, написания — у livesoccertv
    for canon, alias, slug, custom in (("AR ON Sport 1", "ON Sport 1", "on-sport-egypt", 1),
                                       ("ON Sport 2", "ON Sport 2", "on-sport-2-egypt", 0),
                                       ("ar ON Sport Max", "ON Sport Max", "on-sport-max", 1),
                                       ("ar ON Sport Plus", "ON Sport Plus", "on-sport-plus", 1)):
        cid = conn.execute("INSERT INTO channels (canonical_name, slug, country, custom_name) VALUES (?, ?, 'EG', ?)",
                           (canon, slug + "-eg", custom)).lastrowid
        conn.execute("INSERT INTO channel_aliases (channel_id, alias, source_id) VALUES (?, ?, ?)",
                     (cid, alias, lstv["id"]))
        conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, page_url, include) "
                     "VALUES (?, ?, ?, ?, 1)",
                     (lstv["id"], alias, cid, f"https://www.livesoccertv.com/channels/{slug}/"))
    conn.commit()
    ids = {r["canonical_name"]: r["id"] for r in conn.execute("SELECT id, canonical_name FROM channels")}

    print("1. показ без --apply")
    before = counts(conn)
    lines = skript.apply(conn, write=False)
    check("показ ничего не пишет", counts(conn) == before, (before, counts(conn)))
    text = "\n".join(lines)
    check("показ называет источник, три канала, снятую страницу и STC TV",
          all(w in text for w in ("yallakora.com", "ON Sport Max", "ON Sport Plus", "ON Sport 2", "STC TV")), text)

    print("2. --apply")
    skript.apply(conn, write=True)
    yalla = conn.execute("SELECT * FROM sources WHERE domain = 'yallakora.com'").fetchone()
    check("источник yallakora.com: страна, пояс, адрес на день, включён",
          yalla is not None and (yalla["country"], yalla["timezone"], yalla["enabled"], yalla["status"])
          == ("EG", "Africa/Cairo", 1, "ok") and "{MM/DD/YYYY}" in yalla["url_pattern"])
    check("глубина — 2 дня", '"max_days": 2' in (yalla["selector_config"] or ""), yalla["selector_config"])
    for raw, canon in (("ON Sport", "AR ON Sport 1"), ("ON Sport Max", "ar ON Sport Max"),
                       ("ON Sport Plus", "ar ON Sport Plus")):
        got = store._channel_id(conn, raw, yalla)
        check(f"строка yallakora «{raw}» → канал владельца «{canon}»", got == ids[canon], (got, ids[canon]))
    names = {r["id"]: r["canonical_name"] for r in conn.execute("SELECT id, canonical_name FROM channels")}
    check("имена, которые дал владелец, не изменились",
          all(names[i] == n for n, i in ids.items()), names)
    check("новых каналов Египта не заведено",
          conn.execute("SELECT COUNT(*) FROM channels WHERE country = 'EG'").fetchone()[0] == 4)
    off = conn.execute("SELECT include, channel_id FROM source_channels WHERE source_id = ? AND raw_name = 'ON Sport 2'",
                       (lstv["id"],)).fetchone()
    check("страница «ON Sport 2» снята с обхода, канал цел",
          off["include"] == 0 and conn.execute("SELECT 1 FROM channels WHERE id = ?", (ids["ON Sport 2"],)).fetchone() is not None)
    stc = conn.execute("SELECT sc.page_url, sc.include, c.country, c.id FROM source_channels sc JOIN channels c "
                       "ON c.id = sc.channel_id WHERE sc.source_id = ? AND sc.raw_name = 'STC TV'", (lstv["id"],)).fetchone()
    check("STC TV: страница livesoccertv, канал страны SA",
          stc is not None and (stc["page_url"], stc["include"], stc["country"])
          == ("https://www.livesoccertv.com/channels/stc-tv/", 1, "SA"), dict(stc) if stc else None)
    check("строка livesoccertv «STC TV» → этот канал", stc is not None and store._channel_id(conn, "STC TV", lstv) == stc["id"])

    print("3. повторный --apply ничего не дублирует")
    after = counts(conn)
    skript.apply(conn, write=True)
    check("строк столько же", counts(conn) == after, (after, counts(conn)))

    print("4. план обхода")
    plan = {s["domain"]: s for s in crawl.templates(conn, ["livesoccertv.com", "yallakora.com"])}
    pages = {c["pattern"] for c in (plan.get("livesoccertv.com") or {}).get("channels", [])}
    check("в плане страница STC TV", "https://www.livesoccertv.com/channels/stc-tv/" in pages, pages)
    check("в плане нет страницы ON Sport 2", "https://www.livesoccertv.com/channels/on-sport-2-egypt/" not in pages)
    check("три прежние страницы ON Sport на месте", len([p for p in pages if "on-sport" in p]) == 3, pages)
    y = plan.get("yallakora.com") or {}
    check("yallakora.com в плане, каналы — три ON Sport",
          sorted(y.get("include") or []) == ["ON Sport", "ON Sport Max", "ON Sport Plus"], y.get("include"))
    urls = [t.url for t in crawl.plan_source(conn, yalla["id"], days=6, start=date(2026, 11, 19))]
    check("обход при окне 6 дней: два запроса — сегодня и завтра, дата М/Д/ГГГГ",
          urls == ["https://www.yallakora.com/match-center?date=11/19/2026",
                   "https://www.yallakora.com/match-center?date=11/20/2026"], urls)

    print("5. источника livesoccertv нет — yallakora заводится, страницы не трогаются")
    conn.execute("UPDATE sources SET domain = 'x.invalid' WHERE id = ?", (lstv["id"],))
    before = counts(conn)
    out = skript.apply(conn, write=True)
    check("отчёт говорит, что источника нет; база не тронута",
          any("нет" in line and "livesoccertv" in line for line in out) and counts(conn) == before, out)
    conn.close()

    print(f"\nПроверок: {passed + len(failed)}, провалов: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

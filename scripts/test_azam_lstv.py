# -*- coding: utf-8 -*-
r"""Книга 131 (15.11.2026): Azam Sports 1, 2 и 3 — страницами livesoccertv
(`scripts/add_azam_lstv.py`, слово владельца «завести Azam 1 2 3»).

Проверяет правила скрипта и весь путь: страница канала livesoccertv → имя
канала из заголовка («Azam Sports HD») → отметка в НАШ канал «Azam Sports
1 HD» страны TZ (а не новый канал со страной источника) → три страницы в
плане обхода.

Запуск: python scripts/test_azam_lstv.py — в сеть не ходит, базы временные.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="azam-lstv-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")
os.environ.pop("STREAMS_LOCAL", None)

from app import crawl, db, store  # noqa: E402
from app.parsers import livesoccertv_com  # noqa: E402
import add_azam  # noqa: E402
import add_azam_lstv  # noqa: E402

зелёных = красных = 0
BASE = "https://www.livesoccertv.com/channels/"
СТРАНИЦЫ = {"Azam Sports HD": BASE + "azam-sports-hd-tanzania/",
            "Azam Sports 2 HD": BASE + "azam-sports-2-hd/",
            "Azam Sports 3 HD": BASE + "azam-sports-3-hd/"}


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def счёт(conn) -> tuple[int, int, int]:
    return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("channels", "channel_aliases", "source_channels"))


def новая_база(имя: str):
    """Чистая база с источником livesoccertv и одной его прежней страницей."""
    os.environ["STREAMS_DB"] = str(TMP / имя)
    conn = db.connect()
    db.init_db(conn)
    conn.execute("INSERT INTO sources (domain, name, base_url, country, timezone, enabled, "
                 "role, access, status) VALUES ('livesoccertv.com', 'Live Soccer TV', "
                 "'https://www.livesoccertv.com/', 'INT', 'UTC', 1, 'schedule', 'open', 'ok')")
    lstv = conn.execute("SELECT * FROM sources WHERE domain = 'livesoccertv.com'").fetchone()
    conn.execute("INSERT INTO source_channels (source_id, raw_name, page_url, include) "
                 "VALUES (?, 'SuperSport 1 Digitalb', ?, 1)",
                 (lstv["id"], BASE + "supersport-digitalb/"))
    conn.commit()
    return conn, lstv


def канал(conn, имя: str):
    return conn.execute("SELECT id FROM channels WHERE canonical_name = ? AND country = 'TZ'",
                        (имя,)).fetchone()


def страницы(conn, source_id: int) -> dict:
    return {r["raw_name"]: r for r in conn.execute(
        "SELECT * FROM source_channels WHERE source_id = ?", (source_id,))}


#: страница канала livesoccertv с одним матчем (разметка сайта: span.ts[dv] —
#: миллисекунды UTC, ссылка /match/, турнир /competitions/); заголовок — как
#: у первого канала Azam на пробе GitHub 15.11
PAGE = """<html><head><title>Azam Sports HD TV Schedule, Broadcast Rights - Live Soccer TV</title></head>
<body><table>
<tr id="1" class="matchrow" data-timer="" data-ko="2026-11-20 12:00:00" data-has-tv="0">
<td class="timecol"><span class="timecell"><span id="ko1" class="ts" dv="1795262400000"
 df="h:MMtt">12:00pm</span></span></td>
<td class="matchcol"><a href="/match/polisi-tanzania-vs-young-africans/abc">Polisi Tanzania vs Young Africans</a></td>
<td class="compcell_right"><a href="/competitions/tanzania/premier-league/">Premier League</a></td>
</tr></table></body></html>"""

conn, lstv = новая_база("a.db")
add_azam.apply(conn)                      # как на сервере: сперва сайт Azam (каналы 1 и 3)
первый, третий = канал(conn, "Azam Sports 1 HD")["id"], канал(conn, "Azam Sports 3 HD")["id"]

print("Правило 6. Показ без --apply")
до = счёт(conn)
строки = add_azam_lstv.apply(conn, write=False)
проверка("показ ничего не пишет и называет все три канала",
         (счёт(conn) == до, len(строки), all(n in "\n".join(строки) for n, _, _ in add_azam_lstv.CHANNELS)),
         (True, 3, True))

print("Правила 2, 3, 5. --apply")
add_azam_lstv.apply(conn, write=True)
наши = страницы(conn, lstv["id"])
проверка("три страницы: имя — как на странице livesoccertv, адрес, include",
         {n: (r["page_url"], r["include"]) for n, r in наши.items() if n in СТРАНИЦЫ},
         {n: (u, 1) for n, u in СТРАНИЦЫ.items()})
проверка("«Azam Sports HD» и «Azam Sports 3 HD» сели в каналы, что завёл сайт Azam, — новых не появилось",
         (наши["Azam Sports HD"]["channel_id"], наши["Azam Sports 3 HD"]["channel_id"]), (первый, третий))
второй = канал(conn, "Azam Sports 2 HD")
проверка("Azam Sports 2 HD — новый канал страны TZ; всего каналов TZ — три",
         (второй is not None and наши["Azam Sports 2 HD"]["channel_id"] == второй["id"],
          conn.execute("SELECT COUNT(*) FROM channels WHERE country = 'TZ'").fetchone()[0]), (True, 3))
проверка("прежняя страница источника цела; всего страниц у источника — четыре",
         ("SuperSport 1 Digitalb" in наши, len(наши)), (True, 4))

print("Правило 6. Повторный --apply ничего не дублирует")
после = счёт(conn)
add_azam_lstv.apply(conn, write=True)
add_azam.apply(conn)
проверка("строк столько же (и после повторного add_azam.py)", счёт(conn), после)

print("Правило 3. Путь: страница → имя → наш канал")
передачи = livesoccertv_com.parse(PAGE, tz="Europe/Kyiv", url=СТРАНИЦЫ["Azam Sports HD"])
имя = передачи[0].channel_raw if передачи else ""
проверка("разбор взял матч; имя канала со страницы — «Azam Sports HD»",
         (len(передачи), имя, передачи[0].match_raw if передачи else ""),
         (1, "Azam Sports HD", "Polisi Tanzania - Young Africans"))
до = счёт(conn)
проверка("заливка кладёт отметку в «Azam Sports 1 HD» (TZ), нового канала не заводит",
         (store._channel_id(conn, имя, lstv), счёт(conn)[0]), (первый, до[0]))

print("План обхода")
план = {s["domain"]: s for s in crawl.templates(conn, ["livesoccertv.com", "azamtvmax.com"])}
адреса = {c["pattern"] for c in (план.get("livesoccertv.com") or {}).get("channels", [])}
проверка("в плане livesoccertv — три страницы Azam и прежняя; у сайта Azam — по-прежнему две",
         (set(СТРАНИЦЫ.values()) <= адреса, len(адреса),
          len((план.get("azamtvmax.com") or {}).get("channels", []))), (True, 4, 2))

print("Правило 4. Написание занято другим каналом")
conn.execute("INSERT INTO channels (canonical_name, slug, country) VALUES ('Чужой', 'chuzhoy-int', 'INT')")
чужой = conn.execute("SELECT id FROM channels WHERE slug = 'chuzhoy-int'").fetchone()["id"]
conn.execute("UPDATE channel_aliases SET channel_id = ? WHERE alias = 'Azam Sports 2 HD' AND source_id = ?",
             (чужой, lstv["id"]))
conn.commit()
отчёт = add_azam_lstv.apply(conn, write=True)
проверка("в отчёте строка «ЗАНЯТО», написание осталось у чужого канала, остальные каналы заведены",
         (sum("ЗАНЯТО" in с for с in отчёт), sum("страница" in с for с in отчёт),
          conn.execute("SELECT channel_id FROM channel_aliases WHERE alias = 'Azam Sports 2 HD' "
                       "AND source_id = ?", (lstv["id"],)).fetchone()["channel_id"]), (1, 2, чужой))

print("Правило 1. Источника нет — ничего не делается")
conn.execute("UPDATE sources SET domain = 'x.invalid' WHERE id = ?", (lstv["id"],))
до = счёт(conn)
отчёт = add_azam_lstv.apply(conn, write=True)
проверка("отчёт «источника нет», база не тронута", ("нет" in отчёт[0], счёт(conn) == до), (True, True))
conn.close()

print("Правило 2. Обратный порядок: сперва livesoccertv, потом сайт Azam")
conn, lstv = новая_база("b.db")
add_azam_lstv.apply(conn, write=True)
add_azam.apply(conn)
проверка("каналов TZ — три, дублей нет; страница сайта Azam села в тот же «Azam Sports 1 HD»",
         (conn.execute("SELECT COUNT(*) FROM channels WHERE country = 'TZ'").fetchone()[0],
          conn.execute("SELECT sc.channel_id FROM source_channels sc JOIN sources s ON s.id = sc.source_id "
                       "WHERE s.domain = 'azamtvmax.com' AND sc.raw_name = 'Azam Sports 1 HD'").fetchone()[0]
          == канал(conn, "Azam Sports 1 HD")["id"]), (3, True))
conn.close()

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

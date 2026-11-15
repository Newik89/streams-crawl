"""Книга 129 (15.11): источник azamtvmax.com — программа Azam Sports 1 HD и 3 HD.

Запуск: python scripts/test_azam.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="azam-test-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import crawl, db, parsers, site_lang  # noqa: E402
from app.parsers import azamtvmax_com  # noqa: E402
import add_azam  # noqa: E402
import crawl_plan  # noqa: E402

зелёных = красных = 0
AS1 = "https://web.azamtvmax.com/channel/CH-3974c2cd-9ec4-4d03-82b1-9c993973e487"
AS3 = "https://web.azamtvmax.com/channel/CH-a8f7959c-f424-4064-8b71-6c125da488ff"


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def страница(*передачи) -> str:
    """Страница канала, как её отдал браузер на GitHub (проба 15.11): каждая
    передача стоит в нескольких блоках подряд."""
    блоки = "".join(f"<div><span>{t}</span><span>{w}</span></div>" for t, w in передачи)
    return (f"<html><body><h1>Azam Sports 1 HD</h1><nav>Home</nav><div>Sports</div>{блоки}"
            f"<a>Watch Now</a><div>EPG</div><div>Schedule</div><div>Today</div><div>Sun, 15 Nov</div>"
            f"{блоки}{блоки}<footer>Contact us</footer></body></html>")


print("Разбор страницы канала")
html = страница(("NAMUNGO V POLISI TANZANIA", "Sat, 14 Nov - 10:00PM - 12:00AM"),
                ("NIGERIA V TANZANIA LIVE", "Sun, 15 Nov-4:00PM - 6:00PM"),
                ("SPORTS HQ", "Sun, 15 Nov 12:30AM - 1:00AM"))
строки = azamtvmax_com.parse(html, day=date(2026, 11, 15), tz="UTC", url=AS1)
проверка("передача из нескольких блоков страницы — один раз; три записи времени читаются",
         [(p.title, p.start.strftime("%d.%m %H:%M")) for p in строки],
         [("NAMUNGO V POLISI TANZANIA", "14.11 22:00"), ("NIGERIA V TANZANIA LIVE", "15.11 16:00"),
          ("SPORTS HQ", "15.11 00:30")])
проверка("канал — по номеру в адресе; пара через « V »; «LIVE» — слово сайта об эфире",
         [(p.channel_raw, p.match_raw, bool(p.live_raw)) for p in строки],
         [("Azam Sports 1 HD", "NAMUNGO - POLISI TANZANIA", False),
          ("Azam Sports 1 HD", "NIGERIA - TANZANIA", True), ("Azam Sports 1 HD", " ", False)])
проверка("время — в поясе источника (UTC, часы браузера на GitHub)",
         строки[0].start.isoformat(), "2026-11-14T22:00:00+00:00")
проверка("второй канал — свой номер в адресе",
         azamtvmax_com.parse(html, day=date(2026, 11, 15), url=AS3)[0].channel_raw, "Azam Sports 3 HD")
проверка("номер канала незнаком — имя берётся с первой строки страницы",
         azamtvmax_com.parse(html, day=date(2026, 11, 15),
                             url="https://web.azamtvmax.com/channel/CH-00000000-0000-0000-0000-000000000000")[0].channel_raw,
         "Azam Sports 1 HD")
проверка("канал не из списка владельца — пусто",
         azamtvmax_com.parse(html, day=date(2026, 11, 15), url=AS1, channels={"Другой"}), [])
проверка("нового дня ещё нет (страница без программы) и пустая страница — пусто",
         [azamtvmax_com.parse(x, day=date(2026, 11, 15), url=AS3) for x in
          ("<html><body><h1>Azam Sports 3 HD</h1><div>Schedule</div></body></html>", "")], [[], []])
новый_год = azamtvmax_com.parse(страница(("FINAL", "Thu, 31 Dec - 11:00PM - 1:00AM")),
                               day=date(2027, 1, 1), url=AS1)
проверка("запись за 31 декабря, прочитанная 1 января, — прошлый год",
         новый_год[0].start.strftime("%Y-%m-%d"), "2026-12-31")

print("Сайт вписан в списки программы")
проверка("разборщик найден по домену плана", parsers.get("azamtvmax.com") is azamtvmax_com.parse, True)
проверка("сетка «страница на канал, один запрос»; в списке плана; язык сайта задан",
         ("azamtvmax.com" in crawl.CHANNEL_GRID_DOMAINS, "azamtvmax.com" in crawl_plan.PILOTS,
          site_lang.of("azamtvmax.com") is not None), (True, True, True))

print("Заведение источника: правила 1–3")
db.init_db()
conn = db.connect()
сказано = add_azam.apply(conn)
src = conn.execute("SELECT * FROM sources WHERE domain = 'azamtvmax.com'").fetchone()
проверка("источник: браузер, пояс UTC, открыт, включён",
         (src["needs_js"], src["timezone"], src["access"], src["enabled"], src["status"], src["country"]),
         (1, "UTC", "open", 1, "ok", "TZ"))
страницы = {r["raw_name"]: r["page_url"] for r in conn.execute(
    "SELECT raw_name, page_url FROM source_channels WHERE source_id = ? AND include = 1", (src["id"],))}
проверка("два канала, у каждого своя страница; Azam Sports 2 HD не заведён",
         страницы, {"Azam Sports 1 HD": AS1, "Azam Sports 3 HD": AS3})
add_azam.apply(conn)
проверка("повторный запуск ничего не дублирует",
         (conn.execute("SELECT COUNT(*) FROM sources WHERE domain = 'azamtvmax.com'").fetchone()[0],
          conn.execute("SELECT COUNT(*) FROM source_channels WHERE source_id = ?", (src["id"],)).fetchone()[0],
          conn.execute("SELECT COUNT(*) FROM channels WHERE country = 'TZ'").fetchone()[0]), (1, 2, 2))
план = {s["domain"]: s for s in crawl.templates(conn, ["azamtvmax.com"])}
запись = план.get("azamtvmax.com") or {}
проверка("запись плана обхода: браузер, один запрос на канал, две страницы",
         (запись.get("browser"), запись.get("days_inline"),
          sorted(c["pattern"] for c in запись.get("channels") or [])), (True, True, sorted([AS1, AS3])))
conn.close()

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

# -*- coding: utf-8 -*-
"""Канада (слово владельца 22.10.2026): canpl.ca — правила 1–5 разбора,
tvpassport — французские разделители пары и новые станции, onesoccer.ca снят.

Страницы — урезанные по образцу проб #311–#312, собраны здесь. В сеть не
ходит, база не нужна:

    venv\\Scripts\\python.exe scripts/test_kanada.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app.parsers import canpl_ca, tvpassport_com  # noqa: E402

зелёных = красных = 0


def проверка(имя, вышло, ждём):
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✗ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def матч(status, teams, clock="", codes=()):
    time = (f'<span data-translation-key="matchtimeformat">My Time</span><span>{clock}</span>'
            if clock else '<span data-translation-key="finishedstatus">Full Time</span>')
    links = "".join(f'<a href="https://x.example/{c}" target="_blank" '
                    f'data-translation-key="{c}">{c}</a>' for c in codes)
    return (f'<div class="match" data-matchid="cpl::Football_Match::{abs(hash(teams))}" '
            f'data-match-status="{status}" data-match-teams="{teams}, venue: Stadium" '
            f'data-translation-key="venue"><div><a href="/match/x">{time}'
            f'<span>Canadian Premier League</span></a></div><div>{links}</div></div>')


def день(text):
    return f'<div class="day"><span>{text}</span></div>'


СТРАНИЦА = (день("Friday, July 24")
            + матч("FINISHED", "HFX Wanderers vs Supra du Québec", codes=("onesoccer", "cbc"))
            + день("Sunday, Oct 25")
            + матч("UPCOMING", "Pacific vs Forge", "8:00 PM", ("onesoccer",))
            + матч("UPCOMING", "HFX Wanderers vs Supra du Québec", "8:00 PM", ("onesoccer", "tvas2"))
            + матч("UPCOMING", "Cavalry vs Vancouver FC", "11:30 AM", ("onesoccer", "cbc", "tsn", "newtv"))
            + день("Saturday, Jan 2")
            + матч("UPCOMING", "Forge vs Cavalry", "7:00 PM", ("tva",)))
строки = canpl_ca.parse(СТРАНИЦА, day=date(2026, 10, 21), tz="UTC",
                        url="https://canpl.ca/schedule/")


def где(пара):
    return [(p.channel_raw, p.start.strftime("%Y-%m-%d %H:%M %Z")) for p in строки
            if p.match_raw == пара]


print("canpl.ca — календарь CPL с каналами")
проверка("правило 1: сыгранный матч (FINISHED) не берётся",
         [p for p in строки if p.start.month == 7], [])
проверка("правило 2: «Sunday, Oct 25» — 25.10 этого года",
         {p.start.date() for p in строки if p.match_raw == "Pacific - Forge"}, {date(2026, 10, 25)})
проверка("правило 2: «Saturday, Jan 2» на странице октября — следующий год",
         {p.start.date() for p in строки if p.match_raw == "Forge - Cavalry"}, {date(2027, 1, 2)})
проверка("правило 3: «8:00 PM» — 20:00 по часам браузера (UTC)",
         где("Pacific - Forge"), [("OneSoccer", "2026-10-25 20:00 UTC")])
проверка("правило 3: «11:30 AM» — утро, не вечер",
         {s for _, s in где("Cavalry - Vancouver FC")}, {"2026-10-25 11:30 UTC"})
проверка("правило 4: каждый код канала — своя строка, tvas2 → TVA Sports 2",
         [c for c, _ in где("HFX Wanderers - Supra du Québec")], ["OneSoccer", "TVA Sports 2"])
проверка("правило 4: незнакомый код не выбрасывается — имя заглавными",
         [c for c, _ in где("Cavalry - Vancouver FC")], ["OneSoccer", "CBC", "TSN", "NEWTV"])
проверка("правило 4: tva → TVA Sports", [c for c, _ in где("Forge - Cavalry")], ["TVA Sports"])
проверка("правило 5: каждая строка — эфир по слову сайта",
         {p.extra.get("site_flag") for p in строки}, {"live"})
проверка("пара — из data-match-teams без «venue»",
         sorted({p.match_raw for p in строки}),
         ["Cavalry - Vancouver FC", "Forge - Cavalry", "HFX Wanderers - Supra du Québec",
          "Pacific - Forge"])

print("tvpassport — TVA Sports и OneSoccer")
проверка("французское « contre »: HFX Wanderers FC contre Supra du Québec",
         tvpassport_com._pair("HFX Wanderers FC contre Supra du Québec"),
         "HFX Wanderers FC - Supra du Québec")
проверка("французское « c. »: Panthers de la Floride c. Blackhawks de Chicago",
         tvpassport_com._pair("Panthers de la Floride c. Blackhawks de Chicago"),
         "Panthers de la Floride - Blackhawks de Chicago")
проверка("английское « vs. » — как раньше",
         tvpassport_com._pair("Pisa vs. Catanzaro"), "Pisa - Catanzaro")
проверка("станции по адресу: TVA Sports 2, TVA Sports, OneSoccer",
         [tvpassport_com._NAMES.get(s) for s in ("tva-sports-2-hd", "tva-sports-hd", "one-soccer")],
         ["TVA Sports 2", "TVA Sports", "OneSoccer"])
ряд = ('<select id="timezone_selector"><option value="America/New_York" selected>ET</option></select>'
       '<div class="list-group-item" data-st="2026-10-25 16:00:00" '
       'data-showName="Soccer de la Première Ligue Canadienne" '
       'data-episodeTitle="HFX Wanderers FC contre Supra du Québec" data-live="1"></div>')
одна = tvpassport_com.parse(ряд, url="https://www.tvpassport.com/tv-listings/stations/"
                            "tva-sports-2-hd/13778/2026-10-25")
проверка("строка TVA Sports 2: канал, пара, 16:00 Нью-Йорка = 20:00 UTC",
         [(p.channel_raw, p.match_raw, p.start.astimezone().utcoffset() is not None,
           p.start.strftime("%H:%M")) for p in одна],
         [("TVA Sports 2", "HFX Wanderers FC - Supra du Québec", True, "16:00")])

print("onesoccer.ca снят (слово владельца 22.10)")
import crawl_plan  # noqa: E402
проверка("onesoccer.ca нет в плане, canpl.ca есть",
         ("onesoccer.ca" in crawl_plan.PILOTS, "canpl.ca" in crawl_plan.PILOTS), (False, True))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

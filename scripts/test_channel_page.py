# -*- coding: utf-8 -*-
r"""Кнопка ↗ «Открыть расписание канала» (жалоба владельца 13.10.2026:
у Sport Klub 2 #6018 она вела на API `api-web.ug-be.cdn.united.cloud` и
отвечала 401). Требование: ↗ = страница КАНАЛА на ДЕНЬ ИГРЫ на сайте.
Правила — `app/channel_page.py`, шаблоны сайтов — `data/channel_pages.json`.

Проверки по правилам модуля + сторож по живым данным: каждый машинный
адрес плана и последнего сбора (`results/report.json`, `results/games.json`)
даёт человеческую ссылку, а у каждого сайта с машинным адресом есть шаблон.

В сеть не ходит:
    python scripts/test_channel_page.py
"""

from __future__ import annotations

import json
import os
import time
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import channel_page as cp, daytime  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


print("1. машинный адрес — признаки а–г")
for адрес, домен, ждём in (
        # жалоба 13.10: `/epg?` без косой и хост `api-web.` старая проверка не ловила
        ("https://api-web.ug-be.cdn.united.cloud/v1/public/events/epg?cid=923"
         "&fromTime=1&toTime=2&communityIdentifier=sk_hr&languageId=181",
         "sportklub.hr", True),
        ("https://api.sport1.info/v3/de/tv/epg", "tv.sport1.de", True),      # в
        ("https://tvarenaprogram.com/live/v2/ba", "tvarenasport.ba", True),  # г
        ("https://mediaklikk.hu/wp-content/plugins/x/programGuideInterface.php",
         "mediaklikk.hu", True),                                             # а
        ("https://tvheute.at/part/channel-shows/partial/ard/15-10-2026",
         "tvheute.at", True),                                                # а
        ("https://www.atv.com.tr/streaming/jsondatehtml?dt=5.10.2026&isajax=true",
         "atv.com.tr", True),                                                # б
        ("https://mwapi-prod.cosmotetvott.gr/api/v3.4/epg/listings/el",
         "cosmotetv.gr", True),
        ("https://www.raiplay.it/palinsesto/app/rai-sport/15-10-2026.json",
         "raiplay.it", True),
        # человеческие страницы — не машинные
        ("https://www.teleman.pl/sport?live=1&stations=all&page=3", "teleman.pl", False),
        ("https://www.rtrs.tv/program/raspored.php?c=1", "rtrs.tv", False),
        ("https://www.poverkhnost.tv/pages/index.php?c=10&s=135", "poverkhnost.tv", False),
        ("https://epg.cyta.com.cy/tv-guide/en", "epg.cyta.com.cy", False),
        ("https://services.err.ee/x/telekava", "jupiter.err.ee", False),      # тот же err.ee
        ("https://m.flashscore.com.tr/?d=1", "m.flashscore.com.tr", False),
        # канал клуба Ajax и венгерский napi — слова, а не признаки ручки
        ("https://www.livesoccertv.com/channels/ajax-tv/", "livesoccertv.com", False),
        ("https://napi.hu/tv/musor", "napi.hu", False),
        ("https://www.novasports.gr/wp-admin/admin-ajax.php?action=x", "novasports.gr", True),
        ("https://ntvplus.tv/tv/ajax/tv?genre=sport", "ntvplus.tv", True),
        ("https://x.ru/ajax.php?day=1", "x.ru", True),
        ("https://x.ru/services/getAjaxData.aspx?d=1", "x.ru", True),
        ("https://www.sport5.co.il/Ajax/GetBroadcastSheetData.aspx?date=1", "sport5.co.il", True),
        ("https://www.bbc.co.uk/schedules/p00fzl6p/2026/10/15", "bbc.co.uk", False)):
    проверка(f"{адрес[:70]} → {'машинный' if ждём else 'для человека'}",
             cp.is_machine(адрес, домен), ждём)

print("2. домен сайта без поддоменов")
for хост, ждём in (("services.err.ee", "err.ee"), ("www.bbc.co.uk", "bbc.co.uk"),
                   ("m.flashscore.com.tr", "flashscore.com.tr"),
                   ("tvarenaprogram.com", "tvarenaprogram.com")):
    проверка(f"{хост} → {ждём}", cp.site_of(хост), ждём)

print("3. день игры — по часам сайта")
проверка("00:30 по Киеву — у Загреба ещё вчера",
         cp.site_day("2026-10-16 00:30", "Europe/Zagreb"), date(2026, 10, 15))
проверка("21:00 по Киеву — у Загреба тот же день",
         cp.site_day("2026-10-16T21:00", "Europe/Zagreb"), date(2026, 10, 16))
проверка("без пояса — день по Киеву",
         cp.site_day("2026-10-16 00:30", None), date(2026, 10, 16))
проверка("пустое время — дня нет", cp.site_day("", "Europe/Zagreb"), None)

print("4. шаблон сайта: канал из адреса, имени или словаря")
день = date(2026, 10, 15)
проверка("параметр адреса q:cid + словарь",
         cp.from_template({"page": "https://x.hr/k/{CH}/{YYYY-MM-DD}", "ch": "q:cid",
                           "map": {"923": "sk2"}},
                          "https://api.x/epg?cid=923", "", день, None),
         "https://x.hr/k/sk2/2026-10-15")
проверка("часть пути path:-2 без .json",
         cp.from_template({"page": "https://r.it/g?channel={CH}&date={DD-MM-YYYY}",
                           "ch": "path:-2"},
                          "https://r.it/palinsesto/app/rai-sport/15-10-2026.json",
                          "", день, None),
         "https://r.it/g?channel=rai-sport&date=15-10-2026")
проверка("часть пути path:-1 без .json",
         cp.from_template({"page": "https://r.ie/#/{CH}/{YYYY-MM-DD}/", "ch": "path:-1"},
                          "https://r.ie/data-feed/pa/bbc-2.json", "", день, None),
         "https://r.ie/#/bbc-2/2026-10-15/")
проверка("имя канала через словарь",
         cp.from_template({"page": "https://t.pl/stacje/{CH}?date={YYYY-MM-DD}",
                           "ch": "name", "map": {"Eleven Sports 2": "Eleven-Sports-2"}},
                          "", "Eleven Sports 2", день, None),
         "https://t.pl/stacje/Eleven-Sports-2?date=2026-10-15")
проверка("канала нет в словаре — запасной шаблон без канала",
         cp.from_template({"page": "https://t.pl/stacje/{CH}?date={YYYY-MM-DD}",
                           "ch": "name", "map": {}, "else": "https://t.pl/?date={YYYY-MM-DD}"},
                          "", "Новый канал", день, None),
         "https://t.pl/?date=2026-10-15")
проверка("канала нет и запасного нет — пусто",
         cp.from_template({"page": "https://t.pl/stacje/{CH}", "ch": "q:id"},
                          "https://api.t.pl/x", "", день, None), "")
проверка("значение словаря с :// — готовая страница канала, дата подставлена",
         cp.from_template({"page": "{CH}", "ch": "name",
                           "map": {"Nova Sport 1": "https://o.cz/program?date={YYYY-MM-DD}"},
                           "else": "https://www.o.cz/program"},
                          "", "Nova Sport 1", день, None),
         "https://o.cz/program?date=2026-10-15")
проверка("имя сравнивается без регистра, пробелов и HD",
         cp.from_template({"page": "https://d.se/kanal/{CH}", "ch": "name", "map": {"SVT1": "svt1"}},
                          "", "SVT 1 HD", день, None), "https://d.se/kanal/svt1")
проверка("приставка страны владельца перед именем не мешает",
         cp.from_template({"page": "https://t.dk/kanal/{CH}", "ch": "name",
                           "map": {"TV 2 Sport X": "tv-2-sport-x"}},
                          "", "D TV 2 Sport X", день, None), "https://t.dk/kanal/tv-2-sport-x")
проверка("ударения в имени не мешают",
         cp.from_template({"page": "https://p.hu/{CH}", "ch": "name", "map": {"Spiler1 TV": "s1"}},
                          "", "Spíler1 TV", день, None), "https://p.hu/s1")
сегодня = daytime.today("Europe/Podgorica")
rtcg = {"page": "https://rtcg.me/s.html?id={CH}&day={DAYNUM}", "ch": "q:broadcastId",
        "days": [0, 6], "else": "https://rtcg.me/s.html?id={CH}"}
проверка("день вне окна сайта (через 9 дней) — страница канала без дня",
         cp.from_template(rtcg, "https://rtcg.me/s.html?broadcastId=178&day=1", "",
                          сегодня + timedelta(days=9), "Europe/Podgorica"),
         "https://rtcg.me/s.html?id=178")
проверка("день в окне — с номером дня",
         cp.from_template(rtcg, "https://rtcg.me/s.html?broadcastId=178&day=1", "",
                          сегодня + timedelta(days=3), "Europe/Podgorica"),
         "https://rtcg.me/s.html?id=178&day=3")
проверка("номер дня {DAYNUM} — от сегодняшнего дня, а не от дня сбора",
         cp.from_template({"page": "https://rtcg.me/s.html?day={DAYNUM}"}, "", "",
                          сегодня + timedelta(days=2), "Europe/Podgorica"),
         "https://rtcg.me/s.html?day=2")

print("5. порядок правил ссылки")
шаблон = {"sportklub.hr": {"page": "https://sportklub.hr/p/{CH}?d={YYYY-MM-DD}",
                           "ch": "q:cid", "map": {"923": "sk2"}}}
api = "https://api-web.ug-be.cdn.united.cloud/v1/public/events/epg?cid=923"
проверка("1: шаблон сайта, день по часам сайта",
         cp.link(api, domain="sportklub.hr", base_url="https://sportklub.hr/tv-program/",
                 start_kyiv="2026-10-16 00:30", tz="Europe/Zagreb", channel="Sport Klub 2", rules=шаблон),
         "https://sportklub.hr/p/sk2?d=2026-10-15")
проверка("2: человеческий адрес отметки — как есть",
         cp.link("https://www.tv3.lt/programos/btv?d=2026-10-17", domain="tv3.lt",
                 base_url="https://www.tv3.lt/programos/btv", rules=шаблон),
         "https://www.tv3.lt/programos/btv?d=2026-10-17")
проверка("3: машинный без шаблона — страница сайта без ?… и #…",
         cp.link("https://www.rte.ie/data-feed/pa/rte-2.json", domain="rte.ie",
                 base_url="https://www.rte.ie/entertainment/listings/television/#/rte2/2026-01-24/",
                 rules=шаблон),
         "https://www.rte.ie/entertainment/listings/television/")
проверка("4: ничего нет — пусто", cp.link("https://api.x.sk/epg", domain="x.sk", rules=шаблон), "")
проверка("4: машинная закладка — тоже пусто",
         cp.link("https://api.x.sk/epg", domain="x.sk", base_url="https://api.x.sk/v1/list",
                 rules=шаблон), "")
проверка("3: адреса у отметки нет — страница сайта",
         cp.link("", domain="x.sk", base_url="https://x.sk/program?d=1", rules=шаблон),
         "https://x.sk/program")

print("6. поломки не роняют витрину")
проверка("кривой пояс сайта — день по Киеву, без ошибки",
         cp.link(api, domain="sportklub.hr", start_kyiv="2026-10-16 00:30",
                 tz="UTC+3", channel="Sport Klub 2", rules=шаблон),
         "https://sportklub.hr/p/sk2?d=2026-10-16")
проверка("кривой адрес — страница сайта, без ошибки",
         cp.link("http://[::1", domain="x.sk", base_url="https://x.sk/program", rules=шаблон),
         "https://x.sk/program")
import tempfile  # noqa: E402
настоящий = cp.PAGES_FILE
with tempfile.TemporaryDirectory() as папка:
    for имя, текст in (("битый JSON", '{"x.sk": {"page": '), ("пустой файл", ""),
                       ("список вместо словаря", "[1, 2]"),
                       ("BOM Блокнота", '﻿{"x.sk": {"page": "https://x.sk/ok"}}')):
        файл = Path(папка) / f"{len(имя)}.json"
        файл.write_text(текст, encoding="utf-8")
        cp.PAGES_FILE = файл
        cp._cache.update(mtime=None, checked=0.0, pages={})
        try:
            вышло = cp.link("https://api.x.sk/epg", domain="x.sk",
                            base_url="https://x.sk/program")
        except Exception as ошибка:  # noqa: BLE001
            вышло = f"упало: {ошибка!r}"
        ждём = "https://x.sk/ok" if имя == "BOM Блокнота" else "https://x.sk/program"
        проверка(f"файл шаблонов: {имя}", вышло, ждём)
    # файл не прочитался один раз (занят во время git pull) — новое
    # содержимое всё равно подхватывается при следующей проверке
    файл = Path(папка) / "ab.json"
    cp.PAGES_FILE = файл
    cp._cache.update(mtime=None, checked=0.0, pages={})
    файл.write_text('{"x.sk": {"page": "https://x.sk/A"}}', encoding="utf-8")
    первый = cp.link("", domain="x.sk")
    файл.write_text('{"x.sk": {"page": "https://x.sk/', encoding="utf-8")   # недописан
    cp._cache["checked"] = 0.0
    второй = cp.link("", domain="x.sk")
    файл.write_text('{"x.sk": {"page": "https://x.sk/B"}}', encoding="utf-8")
    os.utime(файл, (time.time() + 5, time.time() + 5))    # новое время файла
    cp._cache["checked"] = 0.0
    третий = cp.link("", domain="x.sk")
    проверка("недописанный файл: прежний шаблон, затем новый",
             (первый, второй, третий), ("https://x.sk/A", "https://x.sk/A", "https://x.sk/B"))
cp.PAGES_FILE = настоящий
cp._cache.update(mtime=None, checked=0.0, pages={})

print("7. имя канала — как на сайте; ночь телегида")
словарь = {"page": "https://t.fi/kanava/{CH}", "ch": "name",
           "map": {"MTV Katsomo": "mtv-katsomo-2", "MTV Katsomo+": "mtv-katsomo",
                   "TV3 Plus": "tv3-plus"}}
проверка("«MTV Katsomo» и «MTV Katsomo+» — разные каналы",
         cp.from_template(словарь, "", "MTV Katsomo", день, None), "https://t.fi/kanava/mtv-katsomo-2")
проверка("«TV3+» = «TV3 Plus»",
         cp.from_template(словарь, "", "TV3+", день, None), "https://t.fi/kanava/tv3-plus")
проверка("имя как на сайте раньше имени владельца («YES Sport 3» ← «Sport1 4»)",
         cp.from_template({"page": "https://s.il/?ch={CH}", "ch": "name", "map": {"Sport1 4": "4"}},
                          "", ("Sport1 4", "YES Sport 3"), день, None), "https://s.il/?ch=4")
проверка("уже закодированное значение словаря не кодируется второй раз",
         cp.from_template({"page": "https://x.fr/{CH}", "ch": "name", "map": {"Café": "caf%C3%A9"}},
                          "", "Café", день, None), "https://x.fr/caf%C3%A9")
проверка("канал в адресе кодируется",
         cp.from_template({"page": "https://x.pl/s/{CH}", "ch": "name"}, "", "Canal Sport", день, None),
         "https://x.pl/s/Canal%20Sport")
проверка("ночь телегида: 02:00 по Варшаве 16.10 — страница 15.10",
         cp.site_day("2026-10-16 03:00", "Europe/Warsaw", 6), date(2026, 10, 15))
проверка("ночь телегида: 07:00 по Варшаве — свой день",
         cp.site_day("2026-10-16 08:00", "Europe/Warsaw", 6), date(2026, 10, 16))

print("8. сторож: машинные адреса плана и последнего сбора")
шаблоны = cp.pages()
план = json.loads((ROOT / "data" / "crawl_plan.json").read_text(encoding="utf-8"))
зоны = {s["domain"]: s.get("timezone") for s in план["sources"]}
базы = {s["domain"]: s.get("base_url") or "" for s in план["sources"]}
без_шаблона, пост_не_узнан = [], []
for s in план["sources"]:
    адреса = [c["pattern"] for c in s["channels"]]
    машинный = any(cp.is_machine(a, s["domain"]) for a in адреса)
    if (s.get("post_json") or s.get("post_fields") or s.get("headers")) and not машинный:
        пост_не_узнан.append(s["domain"])
    if машинный and cp._bare(s["domain"]) not in шаблоны:
        без_шаблона.append(s["domain"])
проверка("сайт с POST/JSON/заголовками узнан машинным", пост_не_узнан, [])
проверка("у каждого сайта с машинным адресом есть шаблон в channel_pages.json",
         без_шаблона, [])

отметки = []          # (сайт, канал, адрес, время по Киеву)
игры = json.loads((ROOT / "results" / "games.json").read_text(encoding="utf-8"))
for g in игры.get("games", []):
    for e in g.get("entries", []):
        отметки.append((e.get("source") or "", e.get("channel") or "",
                        e.get("url") or "", g.get("start_kyiv") or ""))
for o in игры.get("другие_виды", []):
    отметки.append((o.get("домен") or "", o.get("канал") or "",
                    o.get("url") or "", o.get("start_kyiv") or ""))
отчёт = json.loads((ROOT / "results" / "report.json").read_text(encoding="utf-8"))
for r in отчёт.get("строки", []):
    отметки.append((r.get("domain") or "", r.get("channel") or "",
                    r.get("url") or "", (r.get("day") or "") + " 12:00"))
плохие, всего_машинных, без_канала = [], 0, set()
for сайт, канал, адрес, когда in отметки:
    правило = шаблоны.get(cp._bare(сайт), {})
    if not cp.is_machine(адрес, сайт) and not правило:
        continue
    if cp.is_machine(адрес, сайт):
        всего_машинных += 1
        ссылка = cp.link(адрес, domain=сайт, base_url=базы.get(сайт, ""),
                         start_kyiv=когда, tz=зоны.get(сайт), channel=канал)
        # ссылка на соседний сайт того же владельца законна (magentatv.gr у
        # cosmotetv.gr) — здесь проверяются только признаки а–в
        if not ссылка or cp.is_machine(ссылка):
            плохие.append(f"{сайт} / {канал}: {адрес[:60]} → {ссылка[:60]!r}")
    как = правило.get("ch", "")
    # строка отчёта сетки (одна страница на все каналы) канала не знает
    if "{CH}" in (правило.get("page") or "") and (канал or как != "name"):
        ключ = cp._channel_key(как, адрес, канал)
        if not ключ or (правило.get("map") is not None
                        and not cp._lookup(правило, ключ, как == "name")):
            без_канала.add(f"{сайт}: {канал} ({ключ})")
print(f"  машинных отметок в последнем сборе: {всего_машинных}")
проверка("каждая даёт человеческую ссылку", плохие[:10], [])
# канал есть в сборе, а словарь шаблона его не знает — ссылка ведёт на
# запасную страницу без канала: дописать канал в map
проверка("каждый канал сбора узнан словарём своего сайта", sorted(без_канала)[:15], [])
# два разных имени словаря после упрощения совпали — один канал поведёт
# на страницу другого («MTV Katsomo» и «MTV Katsomo+» до 13.10)
совпали = []
for сайт, правило in шаблоны.items():
    if правило.get("ch") == "name":
        видели: dict = {}
        for имя, значение in (правило.get("map") or {}).items():
            прежнее = видели.setdefault(cp._norm(имя), (имя, значение))
            if прежнее[1] != значение:
                совпали.append(f"{сайт}: «{прежнее[0]}» и «{имя}»")
проверка("в словарях нет разных каналов с одинаковым упрощённым именем", совпали, [])

print(f"\nзелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

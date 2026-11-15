# -*- coding: utf-8 -*-
r"""Книга 132 (15.11.2026): сайт пришёл пустым целиком — через час дозабор.

Слово владельца 15.11: «в таких случаях должен быть точечный отложенный
сбор, через час хотя бы». Случай: 15.11 в 08:15 ntvplus.tv на все шесть дней
ответил пустой страницей (34 байта), матч «Ростов — Крылья Советов» с канала
МАТЧ ПРЕМЬЕР пропал с витрины. Правило Д10 — шапка `app/redo.py`.

В сеть не ходит: страницы подменены заглушкой, часы задаются явно (от
сегодняшнего дня тест не зависит). Запуск:

    python scripts/test_redo_empty.py
"""
from __future__ import annotations

import inspect
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import fetch, redo  # noqa: E402
import crawl_fetch as cf  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
DAY = "2026-11-15"
#: сбор начат 15.11, дозабор идёт в тот же день в 11:00 по Киеву — не ночь
NOON = datetime(2026, 11, 15, 11, 0, tzinfo=KYIV)
TMP = Path(tempfile.mkdtemp(prefix="redo-empty-test-"))
STUB = '<div class="" data-size="0"></div>'          # что отдал ntvplus.tv 15.11
FULL = "<html><body><p>19:25 Ростов - Крылья Советов</p><p>22:00 Динамо - Локомотив</p></body></html>"

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def page(site: str, day: str, verdict: str, why: str = "", url: str = "", **more) -> dict:
    """Строка отчёта сбора: страница сайта `site` на день `day` (в адресе —
    дата ДД.ММ.ГГГГ, как у ntvplus.tv)."""
    d = datetime.strptime(day, "%Y-%m-%d").strftime("%d.%m.%Y")
    return {"domain": site, "channel": "", "day": day,
            "url": url or f"https://{site.removeprefix('www.')}/tv?date={d}",
            "итог": verdict, "почему": why, **more}


def empty(site: str, day: str, **more) -> dict:
    return page(site, day, redo.EMPTY, "времени на странице нет", **more)


def filled(site: str, day: str, **more) -> dict:
    return page(site, day, redo.FILLED, **more)


def down(site: str, day: str) -> dict:
    return page(site, day, "не открылась", "HTTP 503")


def days(first: int, count: int) -> list[str]:
    return [f"2026-11-{first + i:02d}" for i in range(count)]


def report_of(rows: list, before: list, **more) -> dict:
    """Отчёт полного сбора со строками `rows`; раздел «опустели» — как его
    пишет `crawl_fetch.py`: по сравнению с прошлым сбором `before`."""
    out = {"когда": DAY, "начат_киев": DAY, "режим": "полный обход, окно 6 суток",
           "прогон": "475", "строки": rows, "дозор": {}, "пояса": {},
           "оценка": {"код": 0, "строгая": True}, **more}
    section = redo.emptied_sites(rows, before)
    if section:
        out[redo.EMPTIED_KEY] = section
    return out


print("Д10 (а)+(б). Какой сайт «опустел»")
ntv_now = [empty("ntvplus.tv", d) for d in days(15, 6)]             # 15–20.11
ntv_was = [filled("ntvplus.tv", d) for d in days(14, 6)]            # 14–19.11
проверка("случай 15.11: все шесть страниц пусты, пять из них вчера были с расписанием — опустел",
         redo.emptied_sites(ntv_now, ntv_was), {"ntvplus.tv": {"пустых": 6, "было": 5}})
проверка("хоть одна страница сайта с расписанием — не опустел (у канала может не быть спорта в этот день)",
         redo.emptied_sites([empty("a.tv", "2026-11-15"), filled("a.tv", "2026-11-16")],
                            [filled("a.tv", "2026-11-15"), filled("a.tv", "2026-11-16")]), {})
проверка("те же страницы и в прошлом сборе были пусты (unian.tv на сегодня и завтра) — не опустел",
         redo.emptied_sites([empty("unian.tv", d) for d in days(14, 2)],
                            [empty("unian.tv", d) for d in days(14, 2)]
                            + [filled("unian.tv", d) for d in days(16, 4)]), {})
проверка("сайт пуст всегда (tv8.com.tr) и сайт, которого в прошлом сборе не было, — не опустели",
         redo.emptied_sites([empty("tv8.com.tr", "2026-11-15"), empty("new.tv", "2026-11-15")],
                            [empty("tv8.com.tr", "2026-11-15")]), {})
проверка("у сайта только упавшие страницы, пустых нет — это не «опустел», их берёт обычный дозабор",
         redo.emptied_sites([down("b.tv", "2026-11-15")], [filled("b.tv", "2026-11-15")]), {})
проверка("часть страниц упала, остальные пусты, расписания нет нигде — опустел",
         redo.emptied_sites([down("c.tv", "2026-11-15"), empty("c.tv", "2026-11-16")],
                            [filled("c.tv", "2026-11-15"), filled("c.tv", "2026-11-16")]),
         {"c.tv": {"пустых": 1, "было": 1}})
проверка("сайт с www и без — один сайт; в разделе имя без www",
         redo.emptied_sites([empty("www.d.tv", "2026-11-15")], [filled("d.tv", "2026-11-15")]),
         {"d.tv": {"пустых": 1, "было": 1}})
один_адрес = "https://e.tv/program.html"
проверка("POST-сайт (адрес общий на все дни): «тот же адрес» — адрес вместе с телом запроса",
         (redo.emptied_sites([empty("e.tv", "2026-11-15", url=один_адрес, post={"day": "2026-11-15"})],
                             [filled("e.tv", "2026-11-15", url=один_адрес, post={"day": "2026-11-15"})]),
          redo.emptied_sites([empty("e.tv", "2026-11-17", url=один_адрес, post={"day": "2026-11-17"})],
                             [filled("e.tv", "2026-11-15", url=один_адрес, post={"day": "2026-11-15"})])),
         ({"e.tv": {"пустых": 1, "было": 1}}, {}))
проверка("битые входы (не список, строка не словарь) не роняют",
         [redo.emptied_sites(None, None), redo.emptied_sites("x", 5),
          redo.emptied_sites([None, 7, empty("f.tv", "2026-11-15")], [None, "y"])], [{}, {}, {}])

print("Д10. Отбор дозабора (`pick`): пустые страницы опустевшего сайта — наравне с упавшими")
rows = ([filled("ok.tv", "2026-11-15")] + ntv_now
        + [empty("tv8.com.tr", "2026-11-15"), down("lay.tv", "2026-11-15")])
report = report_of(rows, ntv_was + [filled("lay.tv", "2026-11-15")])
choice = redo.pick(report, now=NOON)
проверка("взяты все шесть страниц опустевшего сайта (и новый дальний день 20.11) и упавшая; вечно пустой сайт — нет",
         (choice.index, choice.total, choice.empty), ([1, 2, 3, 4, 5, 6, 8], 7, 6))
проверка("слова сторожа называют и упавшие, и пустые",
         redo.count_words(choice),
         "не открылись 1 адр. (сайт лёг или не ответил); пришли пустыми 6 адр. сайтов, "
         "что в прошлом сборе давали расписание")
только_пустые = redo.pick(report_of(ntv_now, ntv_was), now=NOON)
проверка("упавших нет, есть пустые — слова только про пустые",
         redo.count_words(только_пустые),
         "пришли пустыми 6 адр. сайтов, что в прошлом сборе давали расписание")
без_раздела = redo.pick({"когда": DAY, "начат_киев": DAY, "строки": rows}, now=NOON)
проверка("раздела «опустели» в отчёте нет (старый отчёт) — пустые не берём, слова прежние",
         (без_раздела.index, без_раздела.empty, redo.count_words(без_раздела)),
         ([8], 0, "не открылись 1 адр. (сайт лёг или не ответил)"))
проверка("раздел битый (не словарь) — как будто его нет",
         redo.pick({"когда": DAY, "начат_киев": DAY, "строки": ntv_now,
                    redo.EMPTIED_KEY: ["ntvplus.tv"]}, now=NOON).total, 0)
дозор = report_of(ntv_now, ntv_was, дозор={"ntvplus.tv": {}})
проверка("опустевший сайт — в дозоре: не трогаем (его пробуют раз в сутки)",
         (redo.pick(дозор, now=NOON).total, redo.pick(дозор, now=NOON).skipped),
         (0, {"сайт дозора": 6}))
без_даты = [empty("g.tv", "2026-11-15", url="https://g.tv/today"), empty("g.tv", "2026-11-16")]
ночь = redo.pick(report_of(без_даты, [filled("g.tv", "2026-11-15", url="https://g.tv/today")]),
                 now=NOON + timedelta(days=1))
проверка("дозабор в другие сутки: страницу без даты в адресе не берём, с датой — берём",
         (ночь.index, ночь.skipped), ([1], {redo.NIGHT_UNDATED: 1}))
много = [empty("h.tv", "2026-11-15", url=f"https://h.tv/ch{i}?date=15.11.2026") for i in range(50)]
проверка(f"пределы те же: не больше {redo.REDO_MAX_URLS} адресов за дозабор",
         (lambda c: (len(c.rows), c.total, c.mass))(redo.pick(report_of(много, [dict(r, итог=redo.FILLED) for r in много]), now=NOON)),
         (redo.REDO_MAX_URLS, 50, False))
толпа = [empty("i.tv", "2026-11-15", url=f"https://i.tv/ch{i}?date=15.11.2026") for i in range(redo.REDO_MASS + 1)]
проверка(f"пустых и упавших вместе больше {redo.REDO_MASS} — массовый сбой, а не дозабор",
         (lambda c: (c.mass, c.rows))(redo.pick(report_of(толпа, [dict(r, итог=redo.FILLED) for r in толпа]), now=NOON)),
         (True, []))

print("Д10 + Д3. Когда: через час после конца сбора")
факты = dict(choice=только_пустые, same="", night=False, next_slot=NOON + timedelta(hours=5),
             collected="", going="", today=0, blocker="", deferred=False)
рано = redo.plan(end=NOON - timedelta(minutes=30), now=NOON, **факты)
пора = redo.plan(end=NOON - timedelta(minutes=redo.REDO_AFTER_MINUTES + 1), now=NOON, **факты)
проверка("через полчаса после сбора — ждём; через час — заказываем дозабор",
         (рано[0], пора[0], "пришли пустыми 6 адр." in пора[1], "ДОЗАБОР" in пора[1]),
         ("wait", "order", True, True))

print("Д10 + Д6. Выправилась ли перекачанная страница (`healed`, `merge`)")
пустая, упавшая = empty("ntvplus.tv", DAY), down("ntvplus.tv", DAY)
с_расписанием, снова_пустая, снова_упала = filled("ntvplus.tv", DAY), empty("ntvplus.tv", DAY), down("ntvplus.tv", DAY)
проверка("пустая: стала с расписанием — да; снова пуста — нет; не открылась — нет",
         [redo.healed(пустая, с_расписанием), redo.healed(пустая, снова_пустая),
          redo.healed(пустая, снова_упала)], [True, False, False])
проверка("упавшая — как раньше: открылась (хоть и без расписания) — да; не открылась — нет",
         [redo.healed(упавшая, с_расписанием), redo.healed(упавшая, снова_пустая),
          redo.healed(упавшая, снова_упала)], [True, True, False])
три = {"когда": DAY, "строки": [empty("j.tv", "2026-11-15"), empty("j.tv", "2026-11-16"),
                               down("k.tv", "2026-11-15")]}
слито = redo.merge(три, {0: filled("j.tv", "2026-11-15"), 1: empty("j.tv", "2026-11-16"),
                         2: empty("k.tv", "2026-11-15")}, redo.Pick(), "475")
проверка("в отчёте дозабора «выправилось» не считает страницу, что снова пуста",
         (слито[redo.SECTION]["адресов"], слито[redo.SECTION]["выправилось"]), (3, 2))

print("Д10 + Д6. GitHub качает пустые страницы заново (`crawl_fetch.redo_fetch`)")


class FakeFetcher:
    """Вместо сети: адрес → страница; что спросили — в `asked`."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.asked: list[str] = []
        self.browser_only = False

    def get_with_fallback(self, url, local=None, locale="en-GB", post=None, warmup="",
                          post_json=None, extra=None):
        self.asked.append(url)
        return fetch.Page(url, self.answers.get(url, STUB), False, "")


cf._now = lambda: NOON
OUT = TMP / "raw_live"
OUT.mkdir()
ожил = FakeFetcher({r["url"]: FULL for r in ntv_now})
код, отчёт, _ = cf.redo_fetch(report_of(ntv_now, ntv_was), OUT, ожил, "475")
раздел = отчёт[redo.SECTION]
проверка("сайт ожил: спрошены все шесть адресов, все шесть выправились",
         (код, ожил.asked, раздел["адресов"], раздел["выправилось"]),
         (0, [r["url"] for r in ntv_now], 6, 6))
проверка("страницы легли файлами под именами обхода — разбор допишет их игры к уже влитому",
         (sorted(redo.redone_files(отчёт)) == sorted(fetch.cache_name(r["url"]).name for r in ntv_now),
          (OUT / fetch.cache_name(ntv_now[5]["url"]).name).read_text(encoding="utf-8")), (True, FULL))
OUT2 = TMP / "raw_live2"
OUT2.mkdir()
всё_пуст = FakeFetcher({ntv_now[0]["url"]: FULL})           # ожила только первая страница
_, отчёт2, _ = cf.redo_fetch(report_of(ntv_now, ntv_was), OUT2, всё_пуст, "475")
раздел2 = отчёт2[redo.SECTION]
проверка(f"после {redo.REDO_SITE_FAILS} страниц подряд, что снова пусты, остальные адреса сайта не трогаем",
         (всё_пуст.asked, раздел2["выправилось"],
          [(p["url"], p["почему"]) for p in раздел2["пропущено"]]),
         ([r["url"] for r in ntv_now[:3]], 1,
          [(r["url"], redo.SITE_STILL_EMPTY) for r in ntv_now[3:]]))

print("Д10. Раздел «опустели» пишет полный обход — по отчёту прошлого полного сбора")
прошлый = TMP / "prev.json"
прошлый.write_text(json.dumps({"строки": ntv_was, "оценка": {"строгая": True}}, ensure_ascii=False),
                   encoding="utf-8")
не_полный = TMP / "site.json"
не_полный.write_text(json.dumps({"строки": ntv_was, "оценка": {"строгая": False}}, ensure_ascii=False),
                     encoding="utf-8")
битый = TMP / "bad.json"
битый.write_text("{не json", encoding="utf-8")
список = TMP / "list.json"
список.write_text("[1, 2]", encoding="utf-8")
проверка("прошлый сбор: полный — его строки; не полный, битый, не словарь, файла нет — пусто",
         [cf.прошлый_сбор(прошлый) == ntv_was, cf.прошлый_сбор(не_полный), cf.прошлый_сбор(битый),
          cf.прошлый_сбор(список), cf.прошлый_сбор(TMP / "нет.json")], [True, [], [], [], []])
главное = inspect.getsource(cf.main)
проверка("полный обход сравнивает себя с отчётом из репозитория и пишет раздел только строгому сбору",
         ("redo.emptied_sites(report, прошлый_сбор(PREVIOUS_REPORT))" in главное,
          "payload[redo.EMPTIED_KEY]" in главное,
          cf.PREVIOUS_REPORT == cf.ROOT / "results" / "report.json"), (True, True, True))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

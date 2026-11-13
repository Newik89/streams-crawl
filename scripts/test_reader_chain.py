# -*- coding: utf-8 -*-
r"""Третий заход — читалки (книга 116, слово владельца 13.11.2026).

Правила — в шапке `app/reader_chain.py` (Ч1–Ч9). Здесь на каждое — проверка.
В сеть не ходит: читалка подменена.

    python scripts/test_reader_chain.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import fetch, reader_chain as rc  # noqa: E402

passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def item(domain, n=1, итог="заглушка защиты", почему="cloudflare", **job):
    j = {"domain": domain, "channel": "", "url": f"https://{domain}/p{n}",
         "day": "2026-11-14", **job}
    return {"job": j, "row": {**j, "итог": итог, "почему": почему,
                              "байт": 0, "меток времени": 0, "чем": "requests"}}


print("Ч2–Ч4. Какие страницы пробуем читалкой")
check("заглушка защиты — пробуем", rc.eligible(**item("a.example")))
check("HTTP 403 — пробуем",
      rc.eligible(**item("a.example", итог="не открылась", почему="HTTP 403")))
check("HTTP 429 — пробуем",
      rc.eligible(**item("a.example", итог="не открылась", почему="HTTP 429")))
check("Ч2: сайт лежит (HTTP 503) — не трогаем",
      not rc.eligible(**item("a.example", итог="не открылась", почему="HTTP 503")))
check("Ч2: таймаут — не трогаем",
      not rc.eligible(**item("a.example", итог="не открылась",
                             почему="ReadTimeout: нет ответа")))
check("Ч2: страница открылась — не трогаем",
      not rc.eligible(**item("a.example", итог="расписание есть", почему="")))
check("Ч3: форма (POST) — не трогаем",
      not rc.eligible(**item("a.example", post={"day": "1"})))
check("Ч3: страница с разогревом — не трогаем",
      not rc.eligible(**item("a.example", warmup="https://a.example/")))
check("Ч4: зеркало эталона — не трогаем",
      not rc.eligible(**item("m.flashscore.pl")))
check("Ч4: основной эталон — пробуем", rc.eligible(**item("flashscore.mobi")))

print("Ч5. Массовый сбой")
норма = [{"domain": f"s{n}.example", "итог": "расписание есть"} for n in range(18)] \
    + [{"domain": "x.example", "итог": "заглушка защиты"},
       {"domain": "y.example", "итог": "не открылась"}]
check("не дались 2 сайта из 20 — не массовый", not rc.is_mass(норма))
обвал = [{"domain": f"s{n}.example", "итог": "расписание есть"} for n in range(14)] \
    + [{"domain": f"b{n}.example", "итог": "не открылась"} for n in range(6)]
check("не дались 6 сайтов из 20 — массовый", rc.is_mass(обвал))
check("сайт с одной открывшейся страницей — дался",
      not rc.is_mass(норма + [{"domain": "x.example", "итог": "расписание есть"}]))
check("в пробе из трёх сайтов долю не считаем", not rc.is_mass(обвал[14:17]))


class Страница:
    def __init__(self, ok, via=""):
        self.ok, self.via = ok, via


def читалка(пускает: dict, журнал: list):
    """Подмена сети: `пускает` — {сайт: имя читалки, которая его берёт};
    страницу отдаёт только она. Остальные читалки отвечают пустышкой."""
    def take(job, accept, only):
        журнал.append((job["url"], only))
        имя = пускает.get(job["domain"])
        if not имя or (only and only != (имя, {})):
            return Страница(False), {**job, "итог": "не открылась",
                                     "почему": "читалки не отдали страницу"}, None
        if not accept("<html>расписание</html>"):
            return Страница(False), {**job, "итог": "не открылась",
                                     "почему": "страница без расписания"}, None
        return (Страница(True, f"reader:{имя}"),
                {**job, "итог": "расписание есть", "почему": "", "байт": 5000,
                 "меток времени": 12, "чем": f"reader:{имя}"}, (имя, {}))
    return take


# разбор сайта: считаем, что строки есть (сам разбор проверяется ниже)
настоящий = rc.parser_rows
rc.parser_rows = lambda job, html, setting=None: 3

print("Ч6–Ч9. Ход по сайту")
журнал: list = []
страницы = [item("a.example", 1), item("a.example", 2), item("a.example", 3),
            item("b.example", 1),
            item("c.example", 1, итог="не открылась", почему="HTTP 503")]
итог = rc.run(страницы, [s["row"] for s in страницы],
              читалка({"a.example": "r.jina.ai"}, журнал), say=lambda *_: None)
check("Ч6: сайт, который читалка берёт, — взяты все 3 страницы",
      итог["взято"].get("a.example") == ["r.jina.ai", 3, 3], итог)
check("Ч9: строка отчёта переписана — расписание есть, через читалку",
      страницы[0]["row"]["итог"] == "расписание есть"
      and "(через читалку r.jina.ai)" in страницы[0]["row"]["почему"]
      and страницы[0]["row"]["чем"] == "reader:r.jina.ai", страницы[0]["row"])
check("Ч7: вторая и третья страницы — той же читалкой, без перебора",
      [only for url, only in журнал if "a.example" in url]
      == [None, ("r.jina.ai", {}), ("r.jina.ai", {})], журнал)
check("сайт, который не берёт ни одна читалка, — в «не взято»",
      any("b.example" in x for x in итог["не_взято"])
      and страницы[3]["row"]["итог"] == "заглушка защиты", итог)
check("Ч2: лежащий сайт читалкой не пробовали",
      not any("c.example" in url for url, _ in журнал))
check("сайтов в ходу — два (a и b)", итог["сайтов"] == 2, итог)

print("Ч6. Выдача без строк разбора не засчитывается")
rc.parser_rows = lambda job, html, setting=None: 0
журнал = []
страницы = [item("a.example", 1), item("a.example", 2)]
итог = rc.run(страницы, [s["row"] for s in страницы],
              читалка({"a.example": "r.jina.ai"}, журнал), say=lambda *_: None)
check("разбор не нашёл строк — страница не взята, строка отчёта прежняя",
      not итог["взято"] and страницы[0]["row"]["итог"] == "заглушка защиты", итог)
check("первую страницу не взял никто — вторую не пробуем",
      len(журнал) == 1, журнал)
rc.parser_rows = lambda job, html, setting=None: None
итог = rc.run([item("a.example", 1)], [], читалка({"a.example": "x"}, []),
              say=lambda *_: None)
check("у сайта нет своего разбора — судим по самой странице (взята)",
      итог["взято"].get("a.example") == ["x", 1, 1], итог)

print("Ч5 и Ч8. Пределы")
rc.parser_rows = lambda job, html, setting=None: 3
журнал = []
итог = rc.run([item("b0.example")], обвал, читалка({"b0.example": "x"}, журнал),
              say=lambda *_: None)
check("Ч5: массовый сбой — читалки не трогаем",
      итог["пропуск"] and not журнал, итог)
часы = iter(range(0, 100000, 200))            # каждая проверка часов +200 с
журнал = []
страницы = [item("a.example", n) for n in range(1, 6)]
итог = rc.run(страницы, [], читалка({"a.example": "x"}, журнал),
              clock=lambda: next(часы), say=lambda *_: None)
check("Ч8: потолок 5 минут на сайт — взята часть страниц, ход остановлен",
      0 < итог["взято"]["a.example"][1] < 5, итог)
много = [item(f"s{n}.example") for n in range(rc.MAX_SITES + 3)]
журнал = []
итог = rc.run(много, [], читалка({}, журнал), say=lambda *_: None)
check(f"Ч8: не больше {rc.MAX_SITES} сайтов за сбор",
      итог["сайтов"] == rc.MAX_SITES and len(журнал) == rc.MAX_SITES, итог)

print("Ч6. Настоящий разбор страницы (alkass.net)")
rc.parser_rows = настоящий
job = {"domain": "alkass.net", "url": "https://www.alkass.net/tvguide",
       "day": "2026-11-14"}
check("заглушка защиты вместо расписания — 0 строк",
      rc.parser_rows(job, "<html><title>Attention Required! | Cloudflare"
                          "</title>Sorry, you have been blocked</html>") == 0)
check("у неизвестного сайта разбора нет — None",
      rc.parser_rows({"domain": "net-takogo.example", "url": "x"}, "<html>") is None)

print("Загрузчик: проверка выдачи и одна читалка")
check("у страницы есть поле «читалка»",
      fetch.Page("u", "h", False, via="reader:x", reader=("p", {})).reader == ("p", {}))
import inspect  # noqa: E402
подпись = inspect.signature(fetch.Fetcher._through_readers).parameters
check("загрузчик принимает проверку выдачи, одну читалку и срок",
      {"accept", "only", "timeout"} <= set(подпись))

print("Список живых читалок: хранится в results/, проверка раз в сутки")
import json      # noqa: E402
import tempfile  # noqa: E402
import time      # noqa: E402
sys.path.insert(0, str(ROOT / "scripts"))
import check_readers  # noqa: E402

check("список лежит в results/ (data/ закрыта .gitignore и в репозиторий не едет)",
      fetch.READERS_FILE.parent.name == "results"
      and check_readers.OUT == fetch.READERS_FILE)
файл = Path(tempfile.mkdtemp(prefix="readers-")) / "readers.json"
check("файла нет — пора проверять", check_readers.stale(файл, 20))
файл.write_text(json.dumps({"проверено": time.strftime("%Y-%m-%d %H:%M")}),
                encoding="utf-8")
check("проверяли только что — сегодня уже не проверяем",
      not check_readers.stale(файл, 20))
check("прошлой проверке 21 час — пора",
      check_readers.stale(файл, 20, time.time() + 21 * 3600))
файл.write_text("{битый", encoding="utf-8")
check("битый файл — пора проверять", check_readers.stale(файл, 20))
yml = (ROOT / ".github" / "workflows" / "crawl.yml").read_text(encoding="utf-8")
check("сбор зовёт проверку с правилом «раз в сутки»",
      "check_readers.py --if-older 20" in yml)
check("на одну читалку — не больше 30 секунд (20 читалок — не дольше 10 минут)",
      check_readers.TIMEOUT <= 30 and len(fetch.READERS) * check_readers.TIMEOUT <= 600)
check("контрольная страница — на сегодня, а не на 06.09.2026",
      "1788642000" not in check_readers.CONTROL_URL)

print(f"\nпройдено: {passed}, провалено: {len(failed)}")
for name in failed:
    print("  ✖", name)
sys.exit(1 if failed else 0)

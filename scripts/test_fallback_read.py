"""Книга 125 (15.11): запасное чтение страницы (`app/fallback_read.py`, З1–З5).

Случай: сайт сменил устройство страницы, свой разборщик возвращает ноль
строк, а расписание на странице видно глазами (football-tv.ru, сбор 14.11:
64 строки «время — матч», разборщик дал 0).

Запуск: python scripts/test_fallback_read.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="fallback-test-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import db, fallback_read, live, pipeline, sport  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import Reference  # noqa: E402

зелёных = красных = 0
ДЕНЬ = date(2026, 11, 15)
ПОЯС = "Europe/Kyiv"


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


СТРАНИЦА = """<html><head><style>.a{color:red}</style><script>var t = "23:59 Скрипт - Мусор";</script></head>
<body><h1>Программа</h1>
<div class="row"><span>19:30</span><span>Студия перед матчем</span></div>
<div class="row"><span>21:45</span><span>Spain &ndash; England. UEFA Nations League</span></div>
<p>23:50 Обзор тура</p>
<p>01:30 Qwerty Town - Asdfgh City</p>
<p>07:5</p><p>12:00</p><p>ab</p>
</body></html>"""

print("З3. Память «какой канал на какой странице»")
ключ = fallback_read.page_key("Site.TV", "https://site.tv/guide/kanal-7?day=2026-11-15&t=1794771900")
проверка("ключ страницы — без дат и меток времени, сайт строчными",
         ключ, "site.tv|https://site.tv/guide/kanal-7?day=#&t=#")
проверка("та же страница на другой день — тот же ключ",
         fallback_read.page_key("site.tv", "https://site.tv/guide/kanal-7?day=2026-11-16&t=1794858300"), ключ)
память: dict = {}
один = [Program(channel_raw="Kanal 7", title="x", start=None)] * 3
fallback_read.remember(память, "site.tv", "https://site.tv/guide/kanal-7?day=2026-11-15", один)
проверка("на странице один канал — запомнен", list(память.values()), ["Kanal 7"])
fallback_read.remember(память, "site.tv", "https://site.tv/all", один + [Program("Kanal 8", "y", None)])
проверка("общая страница с двумя каналами — помнить нечего", len(память), 1)

print("З2, З4. Чтение страницы «глазами»")
проверка("скрипты, стили и разметка убраны",
         any("Скрипт" in x or "color" in x for x in fallback_read.lines_of(СТРАНИЦА)), False)
строки = fallback_read.read(СТРАНИЦА, ДЕНЬ, ПОЯС, "Kanal 7", "https://site.tv/guide/kanal-7")
проверка("строки «время — подпись»: время и подпись соседними строками и в одной строке",
         [(p.raw_time, p.title) for p in строки],
         [("19:30", "Студия перед матчем"), ("21:45", "Spain – England"),
          ("23:50", "Обзор тура"), ("01:30", "Qwerty Town - Asdfgh City")])
проверка("хвост подписи после точки — турнир, а не часть имени команды",
         (строки[1].league_raw,
          fallback_read.cut_tail("Асколи – Палермо. Итальянская серия Б. Сезон 26/27 (12+)"),
          fallback_read.cut_tail("Kiel - St. Pauli. Bundesliga"),
          fallback_read.cut_tail("Olivieri G. A. - Reis Da Silva J."),
          fallback_read.cut_tail("Новости. Спорт")),
         ("UEFA Nations League",
          ("Асколи – Палермо", "Итальянская серия Б. Сезон 26/27 (12+)"),
          ("Kiel - St. Pauli", "Bundesliga"),
          ("Olivieri G. A. - Reis Da Silva J.", ""),
          ("Новости. Спорт", "")))
проверка("время ушло назад больше чем на 6 часов — следующие сутки",
         [p.start.strftime("%d %H:%M") for p in строки], ["15 19:30", "15 21:45", "15 23:50", "16 01:30"])
проверка("строка идёт без пометки эфира и без пары, с пометкой запасного чтения и каналом",
         [(p.live_raw, p.match_raw, p.extra.get(fallback_read.MARK), p.channel_raw) for p in строки[:1]],
         [("", " ", True, "Kanal 7")])
проверка("дня или пояса нет — читать не из чего",
         (fallback_read.read(СТРАНИЦА, None, ПОЯС, "K"), fallback_read.read(СТРАНИЦА, ДЕНЬ, None, "K"),
          fallback_read.read(СТРАНИЦА, ДЕНЬ, "Нет/Такого", "K")), ([], [], []))
проверка("страница без расписания — пусто", fallback_read.read("<p>Нет данных</p>", ДЕНЬ, ПОЯС, "K"), [])

print("З7. Сайт с одним каналом называет его сам")
from app.parsers import football_tv_ru, ipko_tv  # noqa: E402
проверка("football-tv.ru: канал и пояс названы модулем разборщика",
         fallback_read.declared(football_tv_ru.parse), ("Футбол", "Europe/Moscow"))
проверка("сайт с многими каналами ничего не называет",
         fallback_read.declared(ipko_tv.parse)[0], "")
СЕТКА = ("<p><strong>00:00</strong> Асколи – Палермо. Итальянская серия Б. Сезон 26/27 (12+)<br />"
         "<strong>1:55</strong> Абердин – Хайберниан. Шотландская Премьер-Лига. Сезон 2026/27 (12+)</p>")
проверка("у football-tv.ru свой разборщик на суточной сетке даёт ноль строк (читает только анонсы)",
         football_tv_ru.parse(СЕТКА), [])
сетка = fallback_read.read(СЕТКА, ДЕНЬ, "Europe/Moscow", "Футбол")
проверка("…а запасное чтение берёт её строки с каналом «Футбол» и турниром отдельно",
         [(p.raw_time, p.title, p.league_raw[:19], p.channel_raw) for p in сетка],
         [("00:00", "Асколи – Палермо", "Итальянская серия Б", "Футбол"),
          ("01:55", "Абердин – Хайберниан", "Шотландская Премьер", "Футбол")])

print("З4. В ленту — только то, что подтвердил эталон")
MARKERS, SPORTS = live.load(), sport.load(teams=())
ЭТАЛОН = Reference([{"sport": "F", "home": "Spain", "away": "England",
                     "league": "EUROPE: UEFA Nations League", "fs_id": "a1",
                     "start_kyiv": "2026-11-15T21:45"}])
итоги = [pipeline.classify(p, MARKERS, SPORTS, {}, {}, ЭТАЛОН, None) for p in строки]
проверка("матч, который эталон знает на это время, — в ленту; остальное со страницы — мимо",
         [(r.home, r.away) for r in итоги if r.ok or r.home], [("Spain", "England")])
проверка("…студия, обзор и незнакомая эталону пара не прошли",
         [r.ok for r in итоги if not r.home], [False, False, False])

print("З5. Счёт и уведомление")
счёт: dict = {}
fallback_read.count(счёт, "football-tv.ru", 64, "")
fallback_read.count(счёт, "ipko.tv", 9, "SuperSport 1")
fallback_read.count(счёт, "ipko.tv", 0, "SuperSport 6")
fallback_read.count(счёт, "livesoccertv.com", 2, "")
проверка("счёт по сайтам: страниц, строк, сколько страниц с известным каналом",
         счёт["ipko.tv"], {"страниц": 2, "строк": 9, "канал_известен": 2})
fallback_read.count(счёт, "bbc.co.uk", 56, "")
fallback_read.own_rows(счёт, {"football-tv.ru": 0, "ipko.tv": 626, "bbc.co.uk": 558})
проверка("в счёт дописано, сколько строк дал свой разборщик по всему сайту",
         (счёт["football-tv.ru"]["свой_разборщик"], счёт["bbc.co.uk"]["свой_разборщик"]), (0, 558))
слова = fallback_read.words(счёт)
проверка("мелочь (меньше пяти строк) — не сообщаем", "livesoccertv.com" in слова, False)
проверка("З6: сайт читается, а часть страниц намеренно пропущена (каналы не из списка) — молчим",
         "bbc.co.uk" in слова, False)
проверка("З6: сообщаем про сайт целиком без строк и про замолчавшую знакомую страницу",
         sorted(слова), ["football-tv.ru", "ipko.tv"])
проверка("канал неизвестен — сказано, что на витрину строки не идут",
         "канал страницы неизвестен" in слова["football-tv.ru"] and "64 строк" in слова["football-tv.ru"],
         True)
проверка("канал известен — сказано, что подтверждённые эталоном матчи идут на витрину",
         "на витрину идут" in слова["ipko.tv"], True)
db.init_db()
conn = db.connect()
файл = {fallback_read.COUNT_KEY: счёт}
проверка("заливка: по строке на сайт", len(fallback_read.after_import(conn, файл, "2026-11-15")), 2)
проверка("вторая заливка в тот же день — молчим", fallback_read.after_import(conn, файл, "2026-11-15"), [])
проверка("на следующий день — снова по строке", len(fallback_read.after_import(conn, файл, "2026-11-16")), 2)
проверка("файл без счёта (сбор сервера) — без падения", fallback_read.after_import(conn, {}, "2026-11-16"), [])
conn.close()

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

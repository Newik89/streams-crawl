# -*- coding: utf-8 -*-
r"""Проверки учёта посещений (владелец 05.10.2026): кто заходит, визиты,
маячок, суточные суммы, уборка, потолок журнала, страница «Посещения».

В сеть не ходит; всё пишет во временную папку — база и журнал настоящие не
трогаются. Запуск:

    python scripts/test_visits.py
    python scripts/test_visits.py --db data\channel_schedule.db   # витрина на копии базы
    python scripts/test_visits.py --real-log путь\visits-2026-10.log

`--db` — копия этой базы ляжет во временную папку (иначе — пустая база);
`--real-log` — сверка с разбором настоящего журнала 03–05.10 (файл приватный,
в репозиторий не едет). Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

ARGS = argparse.ArgumentParser()
ARGS.add_argument("--db", help="база, копию которой взять для витрины")
ARGS.add_argument("--real-log", help="настоящий журнал для сверки")
OPTS = ARGS.parse_args()

TMP = Path(tempfile.mkdtemp(prefix="visits-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")
os.environ["STREAMS_VISITS_DIR"] = str(TMP / "logs")
os.environ["STREAMS_ADMIN_PASSWORD"] = "test-admin-pass"
os.environ["STREAMS_FRIEND_PASSWORD"] = "test-friend-pass"
os.environ.pop("STREAMS_LOCAL", None)
os.environ.pop("STREAMS_SELF_IPS", None)
(TMP / "logs").mkdir()
if OPTS.db:
    shutil.copy(OPTS.db, TMP / "test.db")

from app import db, visits, visit_stats as vs  # noqa: E402

visits.AUTO_MAINTAIN = False        # фоновую уборку проверяем отдельно

CHROME_WIN = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
SAFARI_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
                 "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
                 "Mobile/15E148 Safari/604.1")
GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
BINGBOT = "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)"
GPTBOT = ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
          "GPTBot/1.2; +https://openai.com/gptbot")

passed = 0
failed: list[str] = []


def check(ok: bool, what: str) -> None:
    global passed
    if ok:
        passed += 1
    else:
        failed.append(what)
        print("  ✗", what)


def row(when, ip, path="/schedule", status=200, who="guest",
        endpoint="schedule", agent=CHROME_WIN, method="GET", vid="", ref="",
        src="", lang=""):
    return {"when": when, "ip": ip, "method": method, "path": path,
            "status": str(status), "who": who, "endpoint": endpoint,
            "agent": agent, "vid": vid, "ref": ref, "src": src, "lang": lang}


def beacon(when, vid, secs=15, acts=0):
    return {"when": when, "vid": vid, "page": "schedule", "secs": secs,
            "acts": acts}


def reset_state(folder: Path | None = None) -> Path:
    """Чистая папка журнала и обнулённые счётчики в памяти."""
    folder = folder or Path(tempfile.mkdtemp(dir=TMP))
    folder.mkdir(parents=True, exist_ok=True)
    os.environ["STREAMS_VISITS_DIR"] = str(folder)
    visits._noise.clear()
    visits._noise_hour = ""
    visits._day = ""
    visits._day_bytes = 0
    visits._day_dropped = 0
    visits._beacon_hits.clear()
    visits._beacon_day = ""
    visits._beacon_bytes = 0
    return folder


def only(found, **kw):
    return [v for v in found if all(v[k] == x for k, x in kw.items())]


# ── классификация ────────────────────────────────────────────────────────────

def test_groups():
    D = "2026-10-05 "
    rows = [
        # человек с маячком: метка выдана первой витриной («+»), вернулась
        row(D + "10:00:00", "198.51.100.1", vid="+AAAAAAAAAAAAAAAA",
            agent=SAFARI_IPHONE, lang="ru-RU", ref="t.me/channel"),
        row(D + "10:01:00", "198.51.100.1", vid="AAAAAAAAAAAAAAAA",
            agent=SAFARI_IPHONE, path="/schedule/other",
            endpoint="schedule_other"),
        # «вероятно человек» — старая строка: браузер открыл витрину
        row(D + "11:00:00", "198.51.100.2"),
        # браузерная подпись, но только «/» → вход: сканер
        row(D + "11:05:00", "198.51.100.3", path="/", status=302,
            endpoint="dashboard"),
        row(D + "11:05:01", "198.51.100.3", path="/login", endpoint="login"),
        # браузер, витрина — но и несуществующий адрес: не человек
        row(D + "11:06:00", "198.51.100.4"),
        row(D + "11:06:01", "198.51.100.4", path="/users/sign_in",
            status=302, endpoint=""),
        # поисковики — каждый отдельно
        row(D + "12:00:00", "192.0.2.10", path="/robots.txt", status=302,
            endpoint="", agent=GOOGLEBOT),
        row(D + "12:00:01", "192.0.2.10", agent=GOOGLEBOT),
        row(D + "12:00:00", "192.0.2.11", agent=BINGBOT),
        row(D + "12:00:00", "192.0.2.12",
            agent="Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)"),
        row(D + "12:00:00", "192.0.2.13",
            agent="DuckDuckBot/1.1; (+http://duckduckgo.com/duckduckbot.html)"),
        row(D + "12:00:00", "192.0.2.14", agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Safari/605.1.15 (Applebot/0.1)")),
        row(D + "12:00:00", "192.0.2.15", agent=(
            "Mozilla/5.0 (compatible; Baiduspider/2.0; "
            "+http://www.baidu.com/search/spider.html)")),
        # роботы ИИ
        row(D + "12:10:00", "192.0.2.20", agent=GPTBOT),
        row(D + "12:10:00", "192.0.2.21", agent=(
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
            "ClaudeBot/1.0; +claudebot@anthropic.com)")),
        row(D + "12:10:00", "192.0.2.22", agent=(
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
            "PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)")),
        row(D + "12:10:00", "192.0.2.23",
            agent="CCBot/2.0 (https://commoncrawl.org/faq/)"),
        row(D + "12:10:00", "192.0.2.24", agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36; compatible; "
            "OAI-SearchBot/1.3; +https://openai.com/searchbot")),
        # сервисы
        row(D + "12:20:00", "192.0.2.30", agent=(
            "Mozilla/5.0 (compatible; DotBot/1.2; +https://opensiteexplorer.org/dotbot)")),
        row(D + "12:20:00", "192.0.2.31", agent=(
            "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)")),
        row(D + "12:20:00", "192.0.2.32", agent=(
            "Mozilla/5.0+(compatible; UptimeRobot/2.0; http://www.uptimerobot.com/)")),
        row(D + "12:20:00", "192.0.2.33",
            agent="Mozilla/5.0 (compatible; CensysInspect/1.1; +https://about.censys.io/)"),
        row(D + "12:20:00", "192.0.2.34",
            agent="Mozilla/5.0 (compatible; SomeNewBot/0.1; +https://example.org/bot)"),
        # сканеры
        row(D + "13:00:00", "203.0.113.1", path="/.env", status=302,
            endpoint=""),
        row(D + "13:00:00", "203.0.113.2", path="/wp-login.php", status=302,
            endpoint="", agent=GOOGLEBOT),           # «Google» лезет в wp-login
        row(D + "13:00:00", "203.0.113.3", path="/", status=302,
            endpoint="dashboard", agent=""),
        row(D + "13:00:00", "203.0.113.4", path="/", status=302,
            endpoint="dashboard", agent="curl/8.5.0"),
        row(D + "13:00:00", "203.0.113.5", path="/", status=302,
            endpoint="dashboard", agent="python-requests/2.32"),
        row(D + "13:00:00", "203.0.113.6", path="/", status=302,
            endpoint="dashboard", agent="Mozilla/5.0 zgrab/0.x"),
        row(D + "13:00:00", "203.0.113.7", path="/", status=302,
            endpoint="dashboard", agent=(
                "Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 5.1; Trident/4.0)")),
        # подделка: один адрес за минуту — Google, Bing и GPTBot
        row(D + "13:30:00", "203.0.113.9", agent=GOOGLEBOT),
        row(D + "13:30:05", "203.0.113.9", agent=BINGBOT),
        row(D + "13:30:09", "203.0.113.9", agent=GPTBOT),
        # свои: админ; его адрес из другого браузера; сервер; GitHub
        row(D + "14:00:00", "198.51.100.50", who="admin",
            path="/sources", endpoint="sources_list"),
        row(D + "14:30:00", "198.51.100.50", agent=SAFARI_IPHONE),
        row(D + "14:00:00", "127.0.0.1", agent="curl/8.5.0"),
        row(D + "14:00:00", "192.0.2.99", path="/hook/crawl", method="POST",
            endpoint="crawl_hook_in", agent="python-requests/2.31"),
        row(D + "14:00:00", "192.0.2.98", agent="Mozilla/5.0 (X11; Linux)",
            path="/", status=302, endpoint="dashboard"),   # внешний адрес сервера
        # друг
        row(D + "15:00:00", "198.51.100.60", who="friend",
            vid="FFFFFFFFFFFFFFFF"),
        row(D + "15:01:00", "198.51.100.60", who="friend", method="POST",
            path="/schedule/run", status=302, endpoint="schedule_run",
            vid="FFFFFFFFFFFFFFFF"),
    ]
    beacons = [beacon(D + "10:00:15", "AAAAAAAAAAAAAAAA", 15, 2),
               beacon(D + "10:00:30", "AAAAAAAAAAAAAAAA", 15, 1)]
    found = vs.classify(rows, beacons, {"127.0.0.1", "192.0.2.98"})
    by_ip = {}
    for v in found:
        by_ip.setdefault(v["ip"], (v["group"], v["sub"]))
    exp = {
        "198.51.100.1": ("human", vs.SUB_BEACON),
        "198.51.100.2": ("human", vs.SUB_PROBABLE),
        "192.0.2.10": ("search", "Google"), "192.0.2.11": ("search", "Bing"),
        "192.0.2.12": ("search", "Яндекс"), "192.0.2.13": ("search", "DuckDuckGo"),
        "192.0.2.14": ("search", "Apple"), "192.0.2.15": ("search", "Baidu"),
        "192.0.2.20": ("ai", "GPTBot (OpenAI)"),
        "192.0.2.21": ("ai", "ClaudeBot (Anthropic)"),
        "192.0.2.22": ("ai", "PerplexityBot"),
        "192.0.2.23": ("ai", "CCBot (Common Crawl)"),
        "192.0.2.24": ("ai", "OAI-SearchBot (OpenAI)"),
        "192.0.2.30": ("service", "DotBot (Moz)"),
        "192.0.2.31": ("service", "Ahrefs"),
        "192.0.2.32": ("service", "UptimeRobot"),
        "192.0.2.33": ("service", "Censys"),
        "192.0.2.34": ("service", "прочие: SomeNewBot"),
        "203.0.113.9": ("scanner", "подделка под роботов"),
        "198.51.100.50": ("own", "вход в админку"),
        "127.0.0.1": ("own", "сервер"),
        "192.0.2.98": ("own", "сервер"),
        "192.0.2.99": ("own", "GitHub (стук обхода)"),
        "198.51.100.60": ("friend", ""),
    }
    for ip, want in exp.items():
        check(by_ip.get(ip) == want, f"группа {ip}: ждали {want}, вышло {by_ip.get(ip)}")
    for ip in ("198.51.100.3", "198.51.100.4", "203.0.113.1", "203.0.113.2",
               "203.0.113.3", "203.0.113.4", "203.0.113.5", "203.0.113.6",
               "203.0.113.7"):
        check(by_ip.get(ip, ("?",))[0] == "scanner",
              f"сканер {ip}: вышло {by_ip.get(ip)}")
    check(by_ip["203.0.113.2"][1].startswith("ищет уязвимости"),
          "«Google» в wp-login — сканер, ищет уязвимости")
    check(by_ip["203.0.113.3"][1] == "без подписи", "пустая подпись — без подписи")
    check(by_ip["203.0.113.4"][1].startswith("программы"), "curl — программы")
    check(by_ip["198.51.100.3"][1].startswith("браузерная подпись"),
          "браузер, только вход — сканер с браузерной подписью")
    # по человеку: одна метка — один визит, два адреса страниц, время по маячку
    h = only(found, group="human", sub=vs.SUB_BEACON)
    check(len(h) == 1, f"человек с маячком: один визит (вышло {len(h)})")
    if h:
        check(h[0]["pages"] == 2, "человек: 2 страницы")
        check(h[0]["actions"] == 3, "человек: 3 действия по маячку")
        check(h[0]["seconds"] == 30, "человек: 30 активных секунд")
        check(h[0]["lang"] == "ru-RU" and h[0]["source"] == "t.me/channel",
              "человек: язык и откуда пришёл")
        check(h[0]["device"] == "Safari, iPhone", "человек: устройство")
    p = only(found, group="human", sub=vs.SUB_PROBABLE)
    check(len(p) == 1 and p[0]["seconds"] is None,
          "вероятно человек: время «не видно» (None), а не ноль")
    f = only(found, group="friend")
    check(len(f) == 1 and f[0]["actions"] == 1, "друг: визит с нажатием кнопки")


def test_robot_cookie_not_split():
    """Робот куку не хранит: каждая витрина выдаёт ему новую метку. Такие
    метки не должны плодить посетителей — ключ остаётся «IP + подпись»."""
    D = "2026-10-05 09:"
    rows = [row(f"{D}{m:02d}:00", "192.0.2.10", agent=GOOGLEBOT,
                vid=f"+{chr(65 + m) * 16}") for m in range(5)]
    found = vs.classify(rows, [], set())
    check(len(found) == 1, f"робот с 5 новыми метками — один визит (вышло {len(found)})")
    check(len({v['key'] for v in found}) == 1, "робот — один посетитель")


def test_visit_split_and_duration():
    D = "2026-10-05 "
    V = "BBBBBBBBBBBBBBBB"
    rows = [row(D + "10:00:00", "198.51.100.7", vid="+" + V),
            row(D + "10:20:00", "198.51.100.7", vid=V),
            row(D + "11:00:00", "198.51.100.7", vid=V),        # пауза 40 мин
            row(D + "18:00:00", "198.51.100.8"),               # без маячков
            row(D + "18:10:00", "198.51.100.8"),
            row(D + "19:00:00", "198.51.100.8")]               # пауза 50 мин
    # маячки 11:00–11:45 каждые 15 с: визит не рвётся, хотя страниц нет
    t = datetime(2026, 10, 5, 11, 0, 15)
    bs = []
    while t <= datetime(2026, 10, 5, 11, 45):
        bs.append(beacon(f"{t:%Y-%m-%d %H:%M:%S}", V, 15, 0))
        t += timedelta(seconds=15)
    bs[5]["acts"] = 4
    rows.append(row(D + "11:50:00", "198.51.100.7", vid=V))   # 5 мин после маячка
    found = vs.classify(rows, bs, set())
    a = sorted(only(found, ip="198.51.100.7"), key=lambda v: v["start"])
    check(len(a) == 2, f"пауза 40 минут — два визита (вышло {len(a)})")
    if len(a) == 2:
        check(a[0]["pages"] == 2 and a[0]["seconds"] is None,
              "первый визит: 2 страницы, маячков нет — время не видно")
        check(a[1]["pages"] == 2 and a[1]["seconds"] == 15 * len(bs),
              "второй визит: маячки держат визит 50 минут, время — сумма маячков")
        check(a[1]["actions"] == 4, "действия — из маячков")
        check(a[1]["group"] == "human" and a[0]["group"] == "human",
              "посетитель с маячком — человек во всех визитах")
    b = only(found, ip="198.51.100.8")
    check(len(b) == 2, f"без метки: IP+подпись, пауза 50 минут — два визита (вышло {len(b)})")
    check(all(v["seconds"] is None for v in b), "без маячков — время не видно")
    check(vs.duration(None) == "не видно" and vs.duration(125) == "2 мин 05 с",
          "запись длительности словами")


def test_old_lines_compat():
    folder = reset_state()
    old = ("2026-10-03 20:08:24\t198.51.100.1\tGET\t/schedule\t200\tguest\t"
           "schedule\tMozilla/5.0 (proverka)\n")
    new = ("2026-10-05 10:00:00\t198.51.100.2\tGET\t/schedule\t200\tguest\t"
           "schedule\t" + CHROME_WIN + "\t+CCCCCCCCCCCCCCCC\tt.me/x\ttg\tru\n")
    junk = "битая строка\tбез полей\n" + "a\tb\tc\td\te\tf\tg\th\ti\n"
    (folder / "visits-2026-10.log").write_text(old + junk + new, encoding="utf-8")
    rows = visits.read(days=None)
    check(len(rows) == 2, f"читаются старая и новая строки, мусор — нет (вышло {len(rows)})")
    if len(rows) == 2:
        check(rows[0]["vid"] == "+CCCCCCCCCCCCCCCC" and rows[0]["src"] == "tg",
              "новая строка: метка и источник на месте (свежие сверху)")
        check(rows[1]["vid"] == "" and rows[1]["lang"] == "" and
              rows[1]["agent"] == "Mozilla/5.0 (proverka)",
              "старая строка из 8 полей: новые поля пустые")
        check(visits.kind(rows[1]) == "page" and visits.what(rows[1]) == "открыл витрину",
              "старая строка — прежние слова ленты")


# ── потолок журнала ──────────────────────────────────────────────────────────

class Clock:
    def __init__(self, start: datetime):
        self.now = start.replace(tzinfo=visits.KYIV)

    def __call__(self):
        return self.now


def lines_of(folder: Path) -> list[dict]:
    out = []
    for p in sorted(folder.glob("visits-*.log")):
        for line in p.read_text(encoding="utf-8").splitlines():
            r = visits.parse_line(line)
            if r:
                out.append(r)
    return out


def test_cap():
    folder = reset_state()
    real_now = visits._now
    clock = Clock(datetime(2026, 10, 5, 10, 0, 0))
    visits._now = clock
    try:
        for i in range(200):                    # сканер: 200 переадресаций
            visits.write("203.0.113.50", "GET", f"/x{i}", 302, False, "",
                         "curl/8")
        for i in range(500):                    # админ кликает много
            visits.write("198.51.100.1", "GET", "/sources", 200, True,
                         "sources_list", CHROME_WIN)
        for i in range(300):                    # витрина — не «шум»
            visits.write("198.51.100.2", "GET", "/schedule", 200, False,
                         "schedule", CHROME_WIN)
        got = lines_of(folder)
        check(sum(r["ip"] == "203.0.113.50" for r in got) == visits.NOISE_PER_HOUR,
              f"сканер: в час записано ровно {visits.NOISE_PER_HOUR} строк")
        check(sum(r["ip"] == "198.51.100.1" for r in got) == 500,
              "админа не режем: 500 из 500")
        check(sum(r["ip"] == "198.51.100.2" for r in got) == 300,
              "витрину не режем")
        clock.now += timedelta(hours=1)         # новый час — сводная строка
        visits.write("198.51.100.2", "GET", "/schedule", 200, False,
                     "schedule", CHROME_WIN)
        got = lines_of(folder)
        skip = [r for r in got if r["method"] == "SKIP"]
        check(len(skip) == 1 and skip[0]["status"] == "80"
              and skip[0]["ip"] == "203.0.113.50",
              f"лишние 80 запросов — одной сводной строкой (вышло {[(r['ip'], r['status']) for r in skip]})")
        check(visits.skipped(skip[0]) == 80 if skip else False,
              "сводная строка весит 80 запросов")
        found = vs.classify(got, [], set())
        sc = only(found, ip="203.0.113.50")
        check(sum(v["hits"] for v in sc) == 200, "в суммах сканер — все 200 запросов")
        check(visits.what(skip[0]).endswith("80") if skip else False,
              "лента объясняет сводную строку")
        # суточный предел: после мягкого — только витрина и свои
        reset_state(folder)
        old_soft, old_hard = visits.DAY_SOFT_BYTES, visits.DAY_HARD_BYTES
        visits.DAY_SOFT_BYTES, visits.DAY_HARD_BYTES = 5_000, 20_000
        try:
            clock.now = datetime(2026, 10, 6, 0, 0, 1, tzinfo=visits.KYIV)
            before = len(lines_of(folder))
            size0 = sum(p.stat().st_size for p in folder.glob("visits-*.log"))
            for i in range(100):                # разные адреса — мимо часового
                visits.write(f"203.0.113.{i}", "GET", "/.env", 302, False, "",
                             "")
            mid = len(lines_of(folder)) - before
            visits.write("198.51.100.2", "GET", "/schedule", 200, False,
                         "schedule", CHROME_WIN)
            visits.write("198.51.100.1", "GET", "/", 200, True, "dashboard",
                         CHROME_WIN)
            got = lines_of(folder)
            check(mid < 100, f"мягкий суточный предел режет шум (записано {mid} из 100)")
            check(got[-2]["ip"] == "198.51.100.2" and got[-1]["who"] == "admin",
                  "после мягкого предела витрина и админ пишутся")
            for i in range(400):
                visits.write("198.51.100.2", "GET", "/schedule", 200, False,
                             "schedule", CHROME_WIN)
            n1 = len(lines_of(folder))
            visits.write("198.51.100.2", "GET", "/schedule", 200, False,
                         "schedule", CHROME_WIN)
            visits.write("198.51.100.1", "GET", "/", 200, True, "dashboard",
                         CHROME_WIN)
            got = lines_of(folder)
            check(len(got) == n1 + 1 and got[-1]["who"] == "admin",
                  "после жёсткого предела — только админ")
            size = sum(p.stat().st_size for p in folder.glob("visits-*.log")) - size0
            check(size < visits.DAY_HARD_BYTES + 2_000,
                  f"за сутки файл не растёт за предел ({size} байт)")
            clock.now += timedelta(days=1)
            visits.write("198.51.100.2", "GET", "/schedule", 200, False,
                         "schedule", CHROME_WIN)
            last = lines_of(folder)[-2]
            check(last["method"] == "SKIP" and int(last["status"]) > 0,
                  "на следующий день — сводная строка «не записано за сутки»")
        finally:
            visits.DAY_SOFT_BYTES, visits.DAY_HARD_BYTES = old_soft, old_hard
    finally:
        visits._now = real_now


# ── суммы и уборка ───────────────────────────────────────────────────────────

def day_rows(day: str, n_people: int = 2) -> list[dict]:
    out = []
    for i in range(n_people):
        out.append(row(f"{day} 10:0{i}:00", f"198.51.100.{i + 1}"))
    out.append(row(f"{day} 11:00:00", "203.0.113.1", path="/.env", status=302,
                   endpoint=""))
    return out


def test_sums_idempotent():
    conn = db.connect()
    try:
        db.init_db(conn)
        conn.execute("DELETE FROM visit_days")
        conn.execute("DELETE FROM visit_days_done")
        conn.commit()
        salt = vs.salt(conn)
        check(salt == vs.salt(conn), "соль постоянна")
        rows = day_rows("2026-09-01") + day_rows("2026-09-02", 3) + \
            day_rows("2026-10-05")
        aggr = vs.aggregate(vs.classify(rows, [], set()), salt)
        done = vs.ensure_days(conn, aggr, "2026-10-05")
        check({"2026-09-01", "2026-09-02"} <= done and "2026-10-05" not in done,
              "закрытые дни записаны, сегодняшний — нет")
        snap = [tuple(r) for r in conn.execute(
            "SELECT * FROM visit_days ORDER BY day, grp, sub")]
        # тот же день ещё раз, но с другими цифрами — запись не меняется
        rows2 = rows + day_rows("2026-09-01", 9)
        aggr2 = vs.aggregate(vs.classify(rows2, [], set()), salt)
        vs.ensure_days(conn, aggr2, "2026-10-05")
        vs.ensure_days(conn, aggr2, "2026-10-05")
        snap2 = [tuple(r) for r in conn.execute(
            "SELECT * FROM visit_days ORDER BY day, grp, sub")]
        check(snap == snap2, "закрытый день пишется один раз (повтор ничего не меняет)")
        h = conn.execute("SELECT visits, visitors FROM visit_days WHERE "
                         "day='2026-09-02' AND grp='human'").fetchone()
        check(h is not None and tuple(h) == (3, 3), "сумма дня: 3 визита, 3 человека")
        # уникальные за период — объединением меток, а не сложением
        daily = vs.stored(conn, "2026-01-01")
        per = vs.periods(daily, "2026-09-02")
        hum = per[("human", vs.TOTAL)]
        check(hum["week"]["visits"] == 5 and hum["week"]["visitors"] == 3,
              f"7 дней: 5 визитов, но 3 разных человека (вышло {hum['week']['visits']}/{hum['week']['visitors']})")
        check(hum["day"]["visits"] == 3, "сегодня (02.09): 3 визита")
        months = vs.by_month(daily)
        check(months and months[0]["month"] == "2026-09" and months[0]["visitors"] == 3,
              "люди по месяцам")
        ids = conn.execute("SELECT ids FROM visit_days WHERE grp='human' "
                           "LIMIT 1").fetchone()[0]
        check("198.51" not in ids and all(len(x) == 10 for x in ids.split()),
              "в суммах — обезличенные метки, не IP")
    finally:
        conn.close()


def write_log(folder: Path, days: list[str]) -> None:
    by_month: dict[str, list[str]] = {}
    for d in days:
        for r in day_rows(d):
            line = "\t".join(r[f] for f in visits.FIELDS) + "\n"
            by_month.setdefault(d[:7], []).append(line)
    for m, lines in by_month.items():
        (folder / f"visits-{m}.log").write_text("".join(lines), encoding="utf-8")


def test_purge():
    folder = reset_state()
    today = "2026-10-20"
    days = ["2026-09-28", "2026-10-05", "2026-10-08", "2026-10-09",
            "2026-10-10", "2026-10-15", "2026-10-20"]
    write_log(folder, days)
    (folder / "beacons-2026-10.log").write_text(
        "2026-10-05 10:00:00\tAAAAAAAAAAAAAAAA\tschedule\t15\t0\n"
        "2026-10-08 10:00:00\tAAAAAAAAAAAAAAAA\tschedule\t15\t0\n"
        "2026-10-15 10:00:00\tAAAAAAAAAAAAAAAA\tschedule\t15\t0\n",
        encoding="utf-8")
    check(visits.keep_from(today) == "2026-10-10", "храним 10 дней: с 10.10 при «сегодня» 20.10")
    # записаны в суммы: 28.09, 05.10, 10.10, 15.10; НЕ записаны: 08.10, 09.10
    done = {"2026-09-28", "2026-10-05", "2026-10-10", "2026-10-15"}
    gone = visits.purge(done, today)
    left = {r["when"][:10] for r in visits.read(days=None)}
    check("2026-09-28" not in left and "2026-10-05" not in left,
          "записанные старые дни убраны")
    check({"2026-10-08", "2026-10-09"} <= left,
          "несчитанные старые дни не тронуты")
    check({"2026-10-10", "2026-10-15", "2026-10-20"} <= left,
          "последние 10 дней не тронуты, даже записанные")
    check(not (folder / "visits-2026-09.log").exists(),
          "опустевший файл прошлого месяца удалён")
    check(gone == 6 + 1, f"убрано строк: 6 журнала + 1 маячок (вышло {gone})")
    bdays = {b["when"][:10] for b in visits.read_beacons()}
    check(bdays == {"2026-10-08", "2026-10-15"}, "маячки убраны по тем же правилам")
    check(not list(folder.glob("*.tmp")), "временных файлов не осталось")
    check(visits.claim_daily(today) and not visits.claim_daily(today),
          "уборка — не чаще раза в сутки")
    check(visits.claim_daily("2026-10-21") and
          not (folder / f"visits-purge-{today}.mark").exists(),
          "назавтра можно снова, старая метка стёрта")
    # сбой уборки не роняет: файл, который нельзя прочитать, — пропускаем
    (folder / "visits-2026-08.log").mkdir()
    try:
        visits.purge(done, today)
        check(True, "сбой одного файла уборку не роняет")
    except Exception as e:                                   # noqa: BLE001
        check(False, f"уборка упала: {e}")
    (folder / "visits-2026-08.log").rmdir()


def test_refresh_end_to_end():
    """refresh: дописывает закрытые дни, убирает старые — только посчитанные."""
    folder = reset_state()
    conn = db.connect()
    try:
        conn.execute("DELETE FROM visit_days")
        conn.execute("DELETE FROM visit_days_done")
        conn.commit()
        write_log(folder, ["2026-09-01", "2026-10-01", "2026-10-19",
                           "2026-10-20"])
        now = datetime(2026, 10, 20, 12, 0, tzinfo=visits.KYIV)
        data = vs.refresh(conn, now=now)
        done = vs.done_days(conn)
        check(done == {"2026-09-01", "2026-10-01", "2026-10-19"},
              f"в суммы легли три закрытых дня (вышло {sorted(done)})")
        left = {r["when"][:10] for r in visits.read(days=None)}
        check(left == {"2026-10-19", "2026-10-20"},
              f"старые посчитанные дни убраны, свежие на месте (осталось {sorted(left)})")
        per = vs.periods(data["daily"], "2026-10-20")
        check(per[("human", vs.TOTAL)]["day"]["visits"] == 2,
              "сегодня считается на лету")
        check(per[("human", vs.TOTAL)]["year"]["visits"] == 8,
              "год = 4 дня × 2 визита (дни из базы + сегодня)")
        # второй раз в тот же день: уборки нет, суммы те же
        data2 = vs.refresh(conn, now=now)
        check(vs.periods(data2["daily"], "2026-10-20") == per,
              "повторный refresh ничего не меняет")
        # первый час суток вчерашний день ещё не закрываем
        check(vs.closable_before(datetime(2026, 10, 21, 0, 30)) == "2026-10-20",
              "00:30 — вчера ещё открыт")
        check(vs.closable_before(datetime(2026, 10, 21, 1, 30)) == "2026-10-21",
              "01:30 — вчера закрыт")
    finally:
        conn.close()


# ── веб: метка, маячок, страница ─────────────────────────────────────────────

def test_web():
    folder = reset_state()
    from app.web import create_app
    app = create_app()
    app.testing = True
    guest = app.test_client()
    env = {"REMOTE_ADDR": "198.51.100.77"}

    r = guest.get("/schedule", environ_base=env, headers={
        "User-Agent": CHROME_WIN, "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.5",
        "Referer": "https://t.me/somechannel?x=1"},
        query_string={"from": "tg<script>"})
    check(r.status_code == 200, f"витрина открывается гостю ({r.status_code})")
    cookie = r.headers.get("Set-Cookie", "")
    check(cookie.startswith("vid=") and "HttpOnly" in cookie
          and "SameSite=Lax" in cookie and "Secure" not in cookie
          and "Max-Age=" in cookie,
          f"гость получил метку: HttpOnly, SameSite=Lax, без Secure ({cookie[:120]})")
    vid = guest.get_cookie("vid").value if guest.get_cookie("vid") else ""
    body = r.get_data(as_text=True)
    check("sendBeacon" in body and "/v" in body, "на витрине есть маячок")
    r2 = guest.get("/schedule/other", environ_base=env,
                   headers={"User-Agent": CHROME_WIN})
    check(r2.status_code == 200 and "sendBeacon" in r2.get_data(as_text=True),
          "маячок и на Other Sport")
    check("Set-Cookie" not in r2.headers or "vid=" not in r2.headers["Set-Cookie"],
          "метка не переставляется, если уже есть")
    got = lines_of(folder)
    check(len(got) == 2 and got[0]["vid"] == "+" + vid and got[1]["vid"] == vid,
          "в журнале: первая строка с выданной меткой «+», вторая — с вернувшейся")
    if got:
        check(got[0]["lang"] == "uk-UA" and got[0]["ref"] == "t.me/somechannel"
              and got[0]["src"] == "tgscript",
              f"язык, откуда пришёл (без ?…), метка from очищена: {got[0]['lang']}, {got[0]['ref']}, {got[0]['src']}")

    # маячок
    r = guest.post("/v", data="p=s&s=15&a=3", environ_base=env)
    check(r.status_code == 204, f"маячок с меткой принят ({r.status_code})")
    nobody = app.test_client()
    r = nobody.post("/v", data="p=s&s=15&a=3", environ_base=env)
    check(r.status_code == 403, f"маячок без метки — отказ ({r.status_code})")
    r = guest.post("/v", data="p=s&s=15&a=3&" + "x" * 300, environ_base=env)
    check(r.status_code == 413, f"слишком большое тело — отказ ({r.status_code})")
    r = guest.post("/v", data="p=zz&s=abc&a=5e3&s=nan", environ_base=env)
    check(r.status_code == 204, f"мусор в числах — не падает ({r.status_code})")
    r = guest.post("/v", data="p=s&s=1e999&a=inf", environ_base=env)
    check(r.status_code == 204, "бесконечность — не падает, считается нулём")
    r = guest.post("/v", data=b"\xff\xfe\x00p=s&s=\xd0\x96", environ_base=env)
    check(r.status_code == 204, "двоичный мусор — не падает")
    r = guest.post("/v", data="p=s&s=99999&a=-5", environ_base=env)
    check(r.status_code == 204, "огромное число — принят с потолком")
    n_b = len(visits.read_beacons())
    r = guest.get("/v", environ_base=env)
    check(r.status_code != 204 and len(visits.read_beacons()) == n_b,
          "маячок — только POST: GET ничего не пишет")
    bs = visits.read_beacons()
    check([(b["secs"], b["acts"]) for b in bs] == [(15, 3), (0, 100), (60, 0)],
          f"в файле маячков: числа приведены и ограничены ({[(b['secs'], b['acts']) for b in bs]})")
    codes = [guest.post("/v", data="p=s&s=1&a=0", environ_base=env).status_code
             for _ in range(visits.BEACON_PER_VID_MIN + 3)]
    check(429 in codes and codes.count(204) < visits.BEACON_PER_VID_MIN,
          f"частота маячков с одной метки ограничена ({codes.count(204)} принято)")
    check(all(r["endpoint"] != "beacon" for r in lines_of(folder)),
          "маячок в общий журнал не пишется")

    # /visits: гостю и другу закрыто, админу — открыто
    r = guest.get("/visits", environ_base=env)
    check(r.status_code == 302 and "/login" in r.headers.get("Location", ""),
          "гостю «Посещения» закрыты")
    friend = app.test_client()
    r = friend.post("/login", data={"password": "test-friend-pass"},
                    environ_base={"REMOTE_ADDR": "198.51.100.78"})
    check(r.status_code == 302, "друг входит")
    r = friend.get("/visits", environ_base={"REMOTE_ADDR": "198.51.100.78"})
    check(r.status_code == 302 and "/login" in r.headers.get("Location", ""),
          "другу «Посещения» закрыты")
    r = friend.get("/schedule", environ_base={"REMOTE_ADDR": "198.51.100.78"})
    check(any(x["who"] == "friend" for x in lines_of(folder)),
          "заход друга помечен в журнале «friend»")

    admin = app.test_client()
    aenv = {"REMOTE_ADDR": "198.51.100.79"}
    r = admin.post("/login", data={"password": "test-admin-pass"},
                   environ_base=aenv)
    check(r.status_code == 302, "админ входит")
    n_before = len(lines_of(folder))
    t0 = time.perf_counter()
    r = admin.get("/visits", environ_base=aenv)
    took = time.perf_counter() - t0
    page = r.get_data(as_text=True)
    check(r.status_code == 200, f"админу «Посещения» открыты ({r.status_code})")
    for text in ("Люди", "людей", "Сегодня", "7 дней", "30 дней", "Год",
                 "Кто заходит", "Визиты за", "Лента", "По адресам",
                 "Поисковые роботы", "Сканеры и мусор"):
        check(text in page, f"на странице есть «{text}»")
    check("198.51.100.77" in page, "админ видит адрес гостя")
    check(len(lines_of(folder)) == n_before,
          "свой просмотр «Посещений» админом в журнал не пишется")
    print(f"  /visits на маленьком журнале: {took * 1000:.0f} мс")
    for g in ("all", "scanner", "own", "nonsense"):
        r = admin.get("/visits", query_string={"g": g, "only": "junk"},
                      environ_base=aenv)
        check(r.status_code == 200, f"фильтр визитов g={g} открывается")

    # публичные адреса не отдают чужих данных
    stranger = app.test_client()
    senv = {"REMOTE_ADDR": "203.0.113.200"}
    secrets_ = ("198.51.100.77", vid, "uk-UA", "t.me/somechannel")
    for method, path in (("GET", "/schedule"), ("GET", "/schedule/other"),
                         ("GET", "/login"), ("POST", "/v"), ("GET", "/logout"),
                         ("GET", "/api/v1/events"), ("GET", "/api/v1/status"),
                         ("GET", "/visits"), ("GET", "/robots.txt")):
        r = stranger.open(path, method=method, environ_base=senv,
                          headers={"User-Agent": CHROME_WIN})
        text = r.get_data(as_text=True) + str(r.headers)
        check(not any(s and s in text for s in secrets_),
              f"{method} {path}: чужих данных нет ({r.status_code})")

    # фоновая уборка: kick запускает refresh в потоке, сайт не ждёт
    import threading
    kfolder = reset_state()
    write_log(kfolder, ["2025-12-31"])
    visits.AUTO_MAINTAIN = True
    visits._kicked_day = ""
    try:
        visits.kick()
        started = [t for t in threading.enumerate() if t.name == "visits-maintain"]
        visits.kick()                       # второй раз за день — ничего
        again = [t for t in threading.enumerate() if t.name == "visits-maintain"]
        for t in again:
            t.join(10)
        check(len(started) <= 1 and len(again) <= 1,
              "kick: не больше одного фонового потока в сутки")
        conn = db.connect()
        try:
            check("2025-12-31" in vs.done_days(conn),
                  "kick: фоновая сводка записала закрытый день")
        finally:
            conn.close()
        check(any(kfolder.glob("visits-purge-*.mark")),
              "kick: фоновая уборка отметила день")
    finally:
        visits.AUTO_MAINTAIN = False


# ── скорость ─────────────────────────────────────────────────────────────────

def test_speed():
    """10 дней × 3000 строк: страница должна строиться меньше чем за секунду."""
    folder = reset_state()
    import random
    rnd = random.Random(5)
    agents = [CHROME_WIN, SAFARI_IPHONE, GOOGLEBOT, BINGBOT, GPTBOT, "",
              "curl/8.5.0", "Mozilla/5.0 zgrab/0.x"]
    today = datetime.now(visits.KYIV).replace(tzinfo=None)
    lines = []
    bl = []
    for d in range(10, -1, -1):
        day = today - timedelta(days=d)
        for i in range(3000):
            t = day.replace(hour=0, minute=0, second=0) + timedelta(
                seconds=int(i * 86400 / 3000))
            if t > today:
                break
            ip = f"203.0.{rnd.randint(0, 40)}.{rnd.randint(1, 250)}"
            ag = rnd.choice(agents)
            if rnd.random() < 0.05:
                v = f"{rnd.randint(0, 300):016d}"
                lines.append("\t".join((f"{t:%Y-%m-%d %H:%M:%S}", ip, "GET",
                                        "/schedule", "200", "guest", "schedule",
                                        CHROME_WIN, v, "", "", "ru")) + "\n")
                bl.append(f"{t:%Y-%m-%d %H:%M:%S}\t{v}\tschedule\t15\t1\n")
            else:
                path = rnd.choice(["/", "/login", "/.env", "/wp-login.php",
                                   "/robots.txt"])
                lines.append("\t".join((f"{t:%Y-%m-%d %H:%M:%S}", ip, "GET",
                                        path, "302", "guest", "", ag)) + "\n")
    by_m: dict[str, list[str]] = {}
    for line in lines:
        by_m.setdefault(line[:7], []).append(line)
    for m, ls in by_m.items():
        (folder / f"visits-{m}.log").write_text("".join(ls), encoding="utf-8")
    (folder / f"beacons-{today:%Y-%m}.log").write_text("".join(bl),
                                                      encoding="utf-8")
    from app.web import create_app
    app = create_app()
    admin = app.test_client()
    aenv = {"REMOTE_ADDR": "198.51.100.90"}
    admin.post("/login", data={"password": "test-admin-pass"}, environ_base=aenv)
    admin.get("/visits", environ_base=aenv)        # первый раз — пишет суммы
    best = 9.0
    for _ in range(3):
        t0 = time.perf_counter()
        r = admin.get("/visits", environ_base=aenv)
        best = min(best, time.perf_counter() - t0)
    print(f"  /visits на {len(lines)} строках: {best * 1000:.0f} мс")
    check(r.status_code == 200 and best < 1.0,
          f"страница на 10 днях × 3000 строк — быстрее секунды ({best:.2f} с)")
    t0 = time.perf_counter()
    for i in range(2000):
        visits.write("198.51.100.1", "GET", "/schedule", 200, False,
                     "schedule", CHROME_WIN, vid="A" * 16)
    per = (time.perf_counter() - t0) / 2000
    print(f"  запись строки: {per * 1e6:.0f} мкс")
    check(per < 0.002, f"запись строки не тормозит запрос ({per * 1e6:.0f} мкс)")


# ── настоящий журнал ─────────────────────────────────────────────────────────

def test_real_log(path: str):
    rows = [r for r in (visits.parse_line(x) for x in
                        Path(path).read_text(encoding="utf-8").splitlines()) if r]
    found = vs.classify(rows, [], {"127.0.0.1", "::1"})
    lines: dict[str, int] = {}
    for v in found:
        lines[v["group"]] = lines.get(v["group"], 0) + v["hits"]
    print("  строк по группам:", lines)
    check(len(rows) == 4331, f"строк 4331 (вышло {len(rows)})")
    scan = lines.get("scanner", 0) + lines.get("service", 0)
    check(abs(scan - 4084) <= 40,
          f"сканеры (+ Censys и прочие сервисы) ≈ 4080 строк (вышло {scan})")
    check(abs(lines.get("own", 0) - 230) <= 10,
          f"свои ≈ 230 строк (вышло {lines.get('own', 0)})")
    sub_lines: dict[str, int] = {}
    for v in found:
        sub_lines[v["sub"]] = sub_lines.get(v["sub"], 0) + v["hits"]
    check(sub_lines.get("DuckDuckGo") == 12, "DuckDuckBot — 12 строк")
    check(sub_lines.get("DotBot (Moz)") == 3, "DotBot — 3 строки")
    hum = only(found, group="human")
    check(len(hum) == 2 and len({v["key"] for v in hum}) == 1
          and all(v["sub"] == vs.SUB_PROBABLE for v in hum)
          and all("iPhone" in v["device"] for v in hum)
          and all(v["seconds"] is None for v in hum),
          "вероятный человек — 1 посетитель с iPhone, 2 визита, время не видно")


TESTS = [test_groups, test_robot_cookie_not_split, test_visit_split_and_duration,
         test_old_lines_compat, test_cap, test_sums_idempotent, test_purge,
         test_refresh_end_to_end, test_web, test_speed]


def main() -> int:
    db.init_db()
    jobs = [(t.__name__, t) for t in TESTS]
    if OPTS.real_log:
        jobs.append(("test_real_log", lambda: test_real_log(OPTS.real_log)))
    for name, fn in jobs:
        print(name)
        try:
            fn()
        except Exception:                                    # noqa: BLE001
            failed.append(f"{name}: исключение")
            traceback.print_exc()
    print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, "
          f"красных: {len(failed)}")
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

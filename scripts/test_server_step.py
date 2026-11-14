# -*- coding: utf-8 -*-
r"""Серверная половина цепочки «GitHub → повтор → читалки → сервер»
(книга 118, слова владельца 13.11.2026).

Правила — в шапке `app/site_move.py`, раздел «ЦЕПОЧКА ВЛАДЕЛЬЦА» (Ц1–Ц7).
Здесь на каждое — сценарий:

Ц1. сайт лежит — счёт не ведём, сервер не трогаем; трое суток — одно
    уведомление;
Ц2. в счёт идёт только «блокирует»;
Ц3. первый сбор с блокировкой — через 90 минут разовый сбор с сервера и
    уведомление, сайт остаётся на GitHub;
Ц4. второй подряд — проверка одним адресом, перевод, сразу сбор с сервера;
Ц5. сервер тоже заблокирован — ТРЕВОГА одна на серию; сервер получил
    таймаут — «лёг», тревоги нет;
Ц6. ход зовёт сторож; идёт заливка — молча ждём; пределы П2.
И список «Собирает сервер» на главной странице админки.

В сеть не ходит, база — временная:

    python scripts/test_server_step.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

TMP = Path(tempfile.mkdtemp(prefix="server-step-test-"))
(TMP / "visits").mkdir()
os.environ.update(STREAMS_DB=str(TMP / "test.db"),
                  STREAMS_ADMIN_PASSWORD="adm-test-1", SECRET_KEY="k" * 32,
                  STREAMS_VISITS_DIR=str(TMP / "visits"))
os.environ.pop("GITHUB_ACTIONS", None)
os.environ.pop("STREAMS_LOCAL", None)

from app import alarm_mail, db, plan_push, site_move, visits, web  # noqa: E402
import server_crawl  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
KYIV = site_move.KYIV
зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


ПЛАН = TMP / "crawl_plan.json"
plan_push.PLAN = ПЛАН
plan_push._push_plan = lambda message: "push пропущен (проверка)"
visits.write = lambda *a, **k: None

conn = db.connect()
db.init_db(conn)


def источник(домен: str, **config) -> None:
    conn.execute("INSERT INTO sources (domain, name, base_url, role, enabled, "
                 "selector_config) VALUES (?, ?, ?, 'schedule', 1, ?)",
                 (домен, домен, f"https://{домен}/",
                  json.dumps(config, ensure_ascii=False)))
    conn.commit()


def настройки(домен: str) -> dict:
    row = conn.execute("SELECT selector_config FROM sources WHERE domain = ?",
                       (домен,)).fetchone()
    return json.loads(row["selector_config"] or "{}")


def сайт_плана(домен: str) -> dict:
    return {"domain": домен, "timezone": "Europe/Kyiv", "grid": False,
            "days_inline": False, "base_url": f"https://{домен}/", "marks": {},
            "pages_per_day": 0, "max_days": 0, "days_ahead": 0,
            "by_server": False, "manual_only": False,
            "channels": [{"name": "Kanal 1",
                          "pattern": f"https://{домен}/k1/{{YYYY-MM-DD}}"}]}


def строка(домен: str, итог: str, почему: str = "") -> dict:
    return {"domain": домен, "channel": "", "day": "2026-11-14",
            "url": f"https://{домен}/k1/2026-11-14", "итог": итог, "почему": почему}


def папка(имя: str, прогон: str, строки: list) -> Path:
    p = TMP / имя
    p.mkdir(exist_ok=True)
    (p / "report.json").write_text(json.dumps(
        {"когда": "2026-11-14", "режим": "полный обход, окно 6 суток",
         "прогон": прогон, "строки": строки, "дозор": {}},
        ensure_ascii=False), encoding="utf-8")
    (p / "games.json").write_text(json.dumps(
        {"собрано": "2026-11-14 05:00", "игр": 0, "games": [], "разобрано": {}},
        ensure_ascii=False), encoding="utf-8")
    return p / "report.json"


def строки_прогонов(после: int = 0) -> list[str]:
    return [(json.loads(r["log"] or "{}") or {}).get("режим") or ""
            for r in conn.execute("SELECT id, log FROM runs WHERE id > ? "
                                  "ORDER BY id", (после,))]


def метка() -> int:
    return alarm_mail.last_row_id(conn)


class Сбор:
    """Подмена `crawl_site`: что сервер получит от сайта и кого собирали."""

    def __init__(self, итоги: dict):
        self.итоги, self.собирали = итоги, []

    def __call__(self, домен: str, дней: int) -> dict:
        self.собирали.append((домен, дней))
        return self.итоги.get(домен, {"итог": "ok", "почему": ""})


class Адрес:
    """Подмена `fetch_one` (проверка одним адресом)."""

    def __init__(self, итоги: dict):
        self.итоги, self.спросили = итоги, []

    def __call__(self, source: dict) -> dict:
        self.спросили.append(source["domain"])
        итог, почему = self.итоги.get(source["domain"], ("расписание есть", ""))
        return {"domain": source["domain"], "url": "https://x/", "итог": итог,
                "почему": почему}


T0 = datetime(2026, 11, 14, 9, 30, tzinfo=KYIV)
BAN, DOWN, NET = "HTTP 403", "HTTP 503", "ConnectTimeout: нет ответа"
ПЛАНЫ = {d: сайт_плана(d) for d in ("ban.tv", "wall.tv", "lie.tv", "two.tv",
                                     "a.tv", "b.tv", "c.tv", "d.tv")}
ПЛАН.write_text(json.dumps({"days": 2, "sources": list(ПЛАНЫ.values())},
                           ensure_ascii=False), encoding="utf-8")

print("Ц1–Ц2. Лежит — не в счёт; в счёт — только «блокирует»")
в = site_move.site_verdicts([строка("a.tv", "не открылась", DOWN),
                             строка("b.tv", "не открылась", NET),
                             строка("c.tv", "заглушка защиты", "cloudflare"),
                             строка("d.tv", "не открылась", NET),
                             строка("d.tv", "не открылась", BAN)])
проверка("HTTP 503 — класс «лежит»", в["a.tv"]["класс"], "down")
проверка("таймаут — класс «лежит»", в["b.tv"]["класс"], "down")
проверка("заглушка защиты — класс «блокирует»", в["c.tv"]["класс"], "ban")
проверка("таймаут и 403 вперемешку — сайт жив и закрылся: «блокирует»",
         (в["d.tv"]["класс"], в["d.tv"]["почему"]), ("ban", "не открылась: HTTP 403"))
cfg: dict = {}
проверка("сайт лёг — событие «down», счёт срывов не тронут",
         (site_move.apply_probe(cfg, в["a.tv"], "901", T0), cfg.get("gh_fail_streak")),
         ("down", None))
проверка("лежит вторые сутки — молчим",
         site_move.apply_probe(cfg, в["a.tv"], "902", T0 + timedelta(hours=40)), "")
проверка("лежит трое суток — пора сказать владельцу (один раз)",
         site_move.apply_probe(cfg, в["a.tv"], "903", T0 + timedelta(hours=73)), "down3")
проверка("четвёртые сутки — второй раз не говорим",
         site_move.apply_probe(cfg, в["a.tv"], "904", T0 + timedelta(hours=97)), "")
проверка("ожил — серия закрыта",
         (site_move.apply_probe(cfg, {"итог": "ok"}, "905", T0), cfg), ("reset", {}))
cfg = {}
site_move.apply_probe(cfg, в["a.tv"], "910", T0)
проверка("лежал, а теперь блокирует — срыв в счёт, пометка «лежит» снята",
         (site_move.apply_probe(cfg, в["c.tv"], "911", T0), cfg.get("gh_fail_streak"),
          cfg.get("gh_down_first")), ("fail", 1, None))
проверка("время заливки сбора со срывом записано (от него считаются 90 минут)",
         cfg.get("gh_fail_at"), "2026-11-14 09:30")
проверка("перевод — со ВТОРОГО сбора подряд (слово владельца)", site_move.FAILS_TO_MOVE, 2)

print("Ц1. Заливка: лежащий сайт — строка в журнал, на третьи сутки — одно уведомление")
источник("lie.tv")
до = метка()
сказано = site_move.after_import(conn, папка("л1", "701", [строка("lie.tv", "не открылась", DOWN)]),
                                 now=T0)
проверка("в журнале заливки — «сайт лежит … сервер и читалки не трогаю»",
         any("lie.tv: сайт лежит" in s and "не трогаю" in s for s in сказано))
проверка("счёт срывов не ведётся, строки владельцу нет",
         (настройки("lie.tv").get("gh_fail_streak"), строки_прогонов(до)), (None, []))
проверка("сервер к лежащему сайту не идёт", site_move.oneoff_due(conn, T0 + timedelta(days=1)), [])
site_move.after_import(conn, папка("л2", "702", [строка("lie.tv", "не открылась", NET)]),
                       now=T0 + timedelta(hours=74))
новые = строки_прогонов(до)
проверка("на третьи сутки — одно уведомление «не открывается трое суток», не ТРЕВОГА",
         (sum("lie.tv: не открывается трое суток" in s for s in новые),
          any("ТРЕВОГА" in s for s in новые)), (1, False))
site_move.after_import(conn, папка("л3", "703", [строка("lie.tv", "не открылась", NET)]),
                       now=T0 + timedelta(hours=98))
проверка("дальше — молчим", len(строки_прогонов(до)), 1)
проверка("пометка на странице сбоев: «лежит с 14.11 — ждём, сервер не трогаем»",
         site_move.mark(настройки("lie.tv")), "лежит с 14.11 — ждём, сервер не трогаем")

print("Ц3. Первый сбор с блокировкой → через 90 минут разовый сбор с сервера")
источник("ban.tv")
site_move.after_import(conn, папка("б1", "711", [строка("ban.tv", "не открылась", BAN)]), now=T0)
проверка("счёт 1", настройки("ban.tv").get("gh_fail_streak"), 1)
проверка("через 60 минут — ещё рано (дозабор пробует GitHub и читалки)",
         site_move.oneoff_due(conn, T0 + timedelta(minutes=60)), [])
T1 = T0 + timedelta(minutes=95)
проверка("через 95 минут — пора", [c["domain"] for c in site_move.oneoff_due(conn, T1)], ["ban.tv"])
сбор, адрес = Сбор({}), Адрес({})
проверка("идёт заливка — молча ждём следующего захода сторожа",
         (site_move.server_step(conn, T1, сбор, адрес, ПЛАНЫ, plan_push.set_mode,
                                busy="идёт заливка", free=lambda: 800), сбор.собирали), ([], []))
до = метка()
сказано = site_move.server_step(conn, T1, сбор, адрес, ПЛАНЫ, plan_push.set_mode, free=lambda: 800)
новые = строки_прогонов(до)
проверка("сервер собрал сайт один раз", [d for d, _ in сбор.собирали], ["ban.tv"])
проверка("уведомление «собрано РАЗОВО С СЕРВЕРА», не ТРЕВОГА",
         (sum("ban.tv" in s and "РАЗОВО С СЕРВЕРА" in s for s in новые),
          any("ТРЕВОГА" in s for s in новые)), (1, False))
проверка("сайт остался на GitHub, одним адресом его не проверяли",
         (настройки("ban.tv").get("by_server"), адрес.спросили), (None, []))
проверка("за этот сбор сервер больше не ходит (сторож придёт через 15 минут)",
         site_move.oneoff_due(conn, T1 + timedelta(minutes=15)), [])
site_move.after_import(conn, папка("б-доз", "712", [строка("ban.tv", "расписание есть")]),
                       now=T1 + timedelta(hours=1))
проверка("следующий сбор GitHub взял сайт — счёт обнулён, серверу делать нечего",
         (настройки("ban.tv").get("gh_fail_streak"),
          site_move.oneoff_due(conn, T1 + timedelta(days=1))), (None, []))

print("Ц4. Второй сбор подряд → проверка одним адресом, перевод, сразу сбор с сервера")
источник("two.tv")
site_move.after_import(conn, папка("д1", "721", [строка("two.tv", "заглушка защиты", "cloudflare")]),
                       now=T0)
сбор, адрес = Сбор({}), Адрес({})
site_move.server_step(conn, T1, сбор, адрес, ПЛАНЫ, plan_push.set_mode, free=lambda: 800)
до = метка()
T2 = T0 + timedelta(hours=8)
site_move.after_import(conn, папка("д2", "722", [строка("two.tv", "заглушка защиты", "cloudflare")]),
                       now=T2)
проверка("счёт 2 — строка «кандидат» владельцу",
         (настройки("two.tv").get("gh_fail_streak"),
          sum("two.tv: 2 сбора подряд блокирует GitHub и читалки" in s
              for s in строки_прогонов(до))), (2, 1))
сбор, адрес = Сбор({}), Адрес({})
site_move.server_step(conn, T2 + timedelta(minutes=95), сбор, адрес, ПЛАНЫ, plan_push.set_mode,
                      free=lambda: 800)
новые = строки_прогонов(до)
проверка("сервер проверил одним адресом и перевёл сайт на себя",
         (адрес.спросили, настройки("two.tv").get("by_server"), настройки("two.tv").get("moved_by")),
         (["two.tv"], True, "auto"))
проверка("уведомление «ПЕРЕВЕДЁН НА СЕРВЕР», не ТРЕВОГА",
         (sum("two.tv" in s and "ПЕРЕВЕДЁН НА СЕРВЕР" in s for s in новые),
          any("ТРЕВОГА" in s for s in новые)), (1, False))
проверка("сразу после перевода сайт собран с сервера — витрина не ждёт утра",
         [d for d, _ in сбор.собирали], ["two.tv"])
проверка("переведённый сайт в очередь сервера больше не встаёт",
         site_move.oneoff_due(conn, T2 + timedelta(days=1)), [])

print("Ц5. Сервер тоже заблокирован → ТРЕВОГА одна на серию; таймаут — «лёг», без тревоги")
источник("wall.tv")
site_move.after_import(conn, папка("с1", "731", [строка("wall.tv", "не открылась", BAN)]), now=T0)
до = метка()
сбор = Сбор({"wall.tv": {"итог": "ban", "почему": "заглушка защиты: cloudflare"}})
site_move.server_step(conn, T1, сбор, Адрес({}), ПЛАНЫ, plan_push.set_mode, free=lambda: 800)
новые = строки_прогонов(до)
проверка("ТРЕВОГА «жив, но не пускает ни GitHub и читалки, ни сервер»",
         sum(s.startswith("перевод сайтов: ТРЕВОГА — wall.tv жив, но не пускает") for s in новые), 1)
проверка("тревога попадёт в письмо", len(alarm_mail.new_alarms(conn, до)), 1)
проверка("сайт не переведён", настройки("wall.tv").get("by_server"), None)
источник("slow.tv")
ПЛАНЫ["slow.tv"] = сайт_плана("slow.tv")
site_move.after_import(conn, папка("с2", "741", [строка("slow.tv", "не открылась", BAN)]), now=T0)
до = метка()
сказано = site_move.server_step(conn, T1, Сбор({"slow.tv": {"итог": "down", "почему": "HTTP 503"}}),
                                Адрес({}), ПЛАНЫ, plan_push.set_mode, free=lambda: 800)
проверка("серверу сайт не ответил — в журнале «считаю, что лёг … тревоги нет»",
         any("slow.tv" in s and "лёг" in s and "тревоги нет" in s for s in сказано))
проверка("строки владельцу и письма нет", (строки_прогонов(до), len(alarm_mail.new_alarms(conn, до))),
         ([], 0))


def упал(домен, дней):
    raise ConnectionError("сеть сервера")


def забыть_проверки() -> None:
    """Суточный счёт проверок сервера (предел П2 — 5 в сутки) — с нуля."""
    conn.execute("DELETE FROM settings WHERE key = ?", (site_move.CHECKS_KEY,))
    conn.commit()


проверка("предел П2 действует и здесь: 5 ходов сервера в сутки",
         site_move.checks_today(conn, T1) >= 3 and site_move.CHECKS_PER_DAY == 5)
забыть_проверки()
источник("boom.tv")
ПЛАНЫ["boom.tv"] = сайт_плана("boom.tv")
site_move.after_import(conn, папка("с3", "751", [строка("boom.tv", "не открылась", BAN)]), now=T0)
сказано = site_move.server_step(conn, T1, упал, Адрес({}), ПЛАНЫ, plan_push.set_mode,
                                free=lambda: 800)
проверка("сбор с сервера упал с ошибкой — ход не оборван, причина в журнале",
         any("boom.tv" in s and "ConnectionError" in s for s in сказано))

print("Ц8 (книга 119). Сбор оборвался не по вине сайта — повтор, потом тревога")
проверка("упавший сбор — «в долгу», попытка 1; владельцу пока ничего",
         (настройки("boom.tv").get("server_crawl_owed"), настройки("boom.tv").get("server_tries"),
          any("попытка 1 из 3" in s and "через 15 минут" in s for s in сказано)),
         ("751", 1, True))
долг = site_move.oneoff_due(conn, T1 + timedelta(minutes=15))
проверка("через 15 минут сайт снова в очереди сервера — 90 минут не ждём",
         [(c["domain"], c["owed"]) for c in долг], [("boom.tv", True)])
до = метка()
сказано = site_move.server_step(conn, T1 + timedelta(minutes=15), упал, Адрес({}), ПЛАНЫ,
                                plan_push.set_mode, free=lambda: 800)
проверка("вторая попытка упала — «попытка 2 из 3», тревоги нет",
         (any("попытка 2 из 3" in s for s in сказано), len(alarm_mail.new_alarms(conn, до))),
         (True, 0))
сказано = site_move.server_step(conn, T1 + timedelta(minutes=30), упал, Адрес({}), ПЛАНЫ,
                                plan_push.set_mode, free=lambda: 800)
проверка("третья попытка упала — ТРЕВОГА владельцу, одно письмо",
         (any(s.startswith("ТРЕВОГА") and "boom.tv" in s and "3 раза подряд" in s for s in сказано),
          len(alarm_mail.new_alarms(conn, до))), (True, 1))
проверка("…долг снят: четвёртой попытки не будет",
         (настройки("boom.tv").get("server_crawl_owed"), настройки("boom.tv").get("server_tries"),
          site_move.oneoff_due(conn, T1 + timedelta(minutes=45))), (None, None, []))
забыть_проверки()
источник("flap.tv")
ПЛАНЫ["flap.tv"] = сайт_плана("flap.tv")
site_move.after_import(conn, папка("с4", "752", [строка("flap.tv", "не открылась", BAN)]), now=T0)
site_move.server_step(conn, T1, Сбор({"flap.tv": {"итог": site_move.FAIL, "почему": "не хватило памяти"}}),
                      Адрес({}), ПЛАНЫ, plan_push.set_mode, free=lambda: 800)
до = метка()
сбор = Сбор({})
site_move.server_step(conn, T1 + timedelta(minutes=15), сбор, Адрес({}), ПЛАНЫ,
                      plan_push.set_mode, free=lambda: 800)
проверка("первая попытка оборвалась, вторая собрала сайт — сбор завершён",
         ([d for d, _ in сбор.собирали], настройки("flap.tv").get("server_crawl_owed")),
         (["flap.tv"], None))
проверка("…владельцу — обычная строка «собрано разово с сервера», тревоги нет",
         (sum("flap.tv" in s and "РАЗОВО С СЕРВЕРА" in s for s in строки_прогонов(до)),
          len(alarm_mail.new_alarms(conn, до))), (1, 0))
проверка("…и больше сервер за этот сбор к сайту не ходит",
         site_move.oneoff_due(conn, T1 + timedelta(minutes=30)), [])
забыть_проверки()
источник("cut.tv", gh_fail_streak=1, gh_fail_last_slot="753", server_oneoff_slot="753",
         server_crawl_owed="753", server_tries=1)
ПЛАНЫ["cut.tv"] = сайт_плана("cut.tv")
сбор = Сбор({})
site_move.server_step(conn, T1, сбор, Адрес({}), ПЛАНЫ, plan_push.set_mode, free=lambda: 800)
проверка("ход прервали посреди сбора (долг записан, итога нет) — сайт собран при "
         "следующем заходе", ([d for d, _ in сбор.собирали],
                              настройки("cut.tv").get("server_crawl_owed")), (["cut.tv"], None))
источник("cut3.tv", gh_fail_streak=1, gh_fail_last_slot="754", server_oneoff_slot="754",
         server_crawl_owed="754", server_tries=3)
ПЛАНЫ["cut3.tv"] = сайт_плана("cut3.tv")
сбор = Сбор({})
сказано = site_move.server_step(conn, T1, сбор, Адрес({}), ПЛАНЫ, plan_push.set_mode,
                                free=lambda: 800)
проверка("прервали на третьей попытке — четвёртой нет, ТРЕВОГА, долг снят",
         (сбор.собирали, any(s.startswith("ТРЕВОГА") and "cut3.tv" in s for s in сказано),
          настройки("cut3.tv").get("server_crawl_owed")), ([], True, None))
источник("moved.tv", by_server=True, moved_by="auto", server_crawl_owed="755", server_tries=1)
ПЛАНЫ["moved.tv"] = сайт_плана("moved.tv")
сбор = Сбор({})
сказано = site_move.server_step(conn, T1, сбор, Адрес({}), ПЛАНЫ, plan_push.set_mode,
                                free=lambda: 800)
проверка("сайт уже переведён на сервер, а первый сбор оборвался — повтор тоже идёт",
         ([d for d, _ in сбор.собирали], настройки("moved.tv").get("server_crawl_owed"),
          настройки("moved.tv").get("by_server")), (["moved.tv"], None, True))
сбор = Сбор({})
conn.execute("UPDATE sources SET selector_config = ? WHERE domain = 'cut.tv'",
             (json.dumps({"gh_fail_streak": 1, "gh_fail_last_slot": "756",
                          "server_crawl_owed": "756", "server_tries": 1}),))
conn.commit()
site_move.server_step(conn, T1, сбор, Адрес({}), ПЛАНЫ, plan_push.set_mode, free=lambda: 100)
проверка("памяти мало — и сбор «в долгу» ждёт, не идёт", сбор.собирали, [])
conn.execute("UPDATE sources SET selector_config = '{}' WHERE domain = 'cut.tv'")
conn.commit()

print("Ц8. Сбор сайта с сервера: что считается «сбоем», а что — ответом сайта")
server_crawl.РАБОЧАЯ = TMP / "раб"
(server_crawl.РАБОЧАЯ / "x.tv").mkdir(parents=True)
ОТЧЁТ_X = server_crawl.РАБОЧАЯ / "x.tv" / "report.json"
шаги: list = []


def шаг_подмена(отчёт_строки, упал_на: str = ""):
    """Подмена `server_crawl.шаг`: сбор пишет отчёт (или не пишет — None),
    шаг с именем `упал_на` отвечает «не вышло»."""
    def шаг(команда, тег):
        шаги.append(тег)
        if тег == "качаю" and отчёт_строки is not None:
            ОТЧЁТ_X.write_text(json.dumps({"строки": отчёт_строки}), encoding="utf-8")
        return тег != упал_на
    return шаг


счёт = iter([])
server_crawl.счётчик_закрытых = lambda: next(счёт)
ЕСТЬ, ЛЕГ = [строка("x.tv", "расписание есть")], [строка("x.tv", "не открылась", NET)]
счёт = iter([7, 7])
server_crawl.шаг = шаг_подмена(ЕСТЬ)
шаги.clear()
проверка("всё прошло: страницы, разбор, заливка — «ok»",
         (server_crawl.собрать_сайт("x.tv", 2)["итог"], шаги),
         ("ok", ["качаю", "разбираю", "вливаю в базу"]))
счёт = iter([7, 7])
ОТЧЁТ_X.write_text(json.dumps({"строки": ЕСТЬ}), encoding="utf-8")   # вчерашний отчёт
server_crawl.шаг = шаг_подмена(None, упал_на="качаю")
проверка("программа сбора упала, отчёта нет — «сбой», вчерашний отчёт за свежий не принят",
         server_crawl.собрать_сайт("x.tv", 2)["итог"], site_move.FAIL)
счёт = iter([7, 8])
server_crawl.шаг = шаг_подмена(ЛЕГ)
итог = server_crawl.собрать_сайт("x.tv", 2)
проверка("страница «не открылась», а система за это время закрыла программу из-за "
         "памяти — «сбой», а не «сайт лёг»", (итог["итог"], "памяти" in итог["почему"]),
         (site_move.FAIL, True))
счёт = iter([7, 7])
server_crawl.шаг = шаг_подмена(ЛЕГ)
шаги.clear()
проверка("страница «не открылась», память в порядке — сайт лёг («down»), разбор не идёт",
         (server_crawl.собрать_сайт("x.tv", 2)["итог"], шаги), ("down", ["качаю"]))
счёт = iter([7, 7])
server_crawl.шаг = шаг_подмена([строка("x.tv", "не открылась", BAN)])
проверка("сервер тоже заблокирован — «ban», как раньше",
         server_crawl.собрать_сайт("x.tv", 2)["итог"], "ban")
счёт = iter([7, 7])
server_crawl.шаг = шаг_подмена(ЕСТЬ, упал_на="разбираю")
проверка("страницы скачаны, разбор упал — «сбой»",
         server_crawl.собрать_сайт("x.tv", 2)["итог"], site_move.FAIL)
счёт = iter([7, 7])
server_crawl.шаг = шаг_подмена(ЕСТЬ, упал_на="вливаю в базу")
проверка("страницы разобраны, заливка упала — «сбой»",
         server_crawl.собрать_сайт("x.tv", 2)["итог"], site_move.FAIL)
счёт = iter([None, None])
server_crawl.шаг = шаг_подмена(ЕСТЬ)
проверка("счётчика памяти нет (не Linux) — сбор идёт как обычно",
         server_crawl.собрать_сайт("x.tv", 2)["итог"], "ok")
vm = TMP / "vmstat"
vm.write_text("pgfault 10\noom_kill 4\nnr_free 5\n", encoding="utf-8")
проверка("счётчик системы читается из строки oom_kill; файла нет — None",
         (site_move.oom_kills(str(vm)), site_move.oom_kills(str(TMP / "нет-vmstat"))), (4, None))

print("Ц6. Пределы: память, число сайтов за заход")
for d in ("m1.tv", "m2.tv", "m3.tv", "m4.tv"):
    источник(d)
    ПЛАНЫ[d] = сайт_плана(d)
    site_move.after_import(conn, папка(f"п-{d}", f"76{d[1]}", [строка(d, "не открылась", BAN)]),
                           now=T0)
забыть_проверки()
сбор = Сбор({})
до_памяти = метка()
сказано = site_move.server_step(conn, T1, сбор, Адрес({}), ПЛАНЫ, plan_push.set_mode, free=lambda: 100)
проверка("мало памяти — сервер не собирает никого, причина в журнале",
         (сбор.собирали, any("памяти" in s for s in сказано)), ([], True))
проверка("…и владельцу — одна строка «ход сервера откладываю — мало памяти»",
         sum("откладываю" in s and "памяти" in s for s in строки_прогонов(до_памяти)), 1)
site_move.server_step(conn, T1 + timedelta(minutes=15), сбор, Адрес({}), ПЛАНЫ,
                      plan_push.set_mode, free=lambda: 100)
проверка("через 15 минут памяти всё ещё мало — вторую строку владельцу не пишем",
         sum("откладываю" in s for s in строки_прогонов(до_памяти)), 1)
print("Книга 119. Порог памяти по замеру и «закрывай сбор, а не сайт»")
проверка("порог — 250 МБ (замер 14.11: браузер берёт около 230)", site_move.MIN_FREE_MB, 250)
проверка("свободно 249 — мало", site_move.memory_short(249), True)
проверка("свободно ровно 250 — хватает", site_move.memory_short(250), False)
проверка("обычные для сервера 350–390 — хватает (при прежних 400 было «мало»)",
         (site_move.memory_short(350), site_move.memory_short(390)), (False, False))
проверка("разовая проверка: 249 — отказ с числами, 250 — можно",
         ("свободно 249 МБ" in site_move.check_refusal(0, 0, 249)
          and f"не меньше {site_move.MIN_FREE_MB}" in site_move.check_refusal(0, 0, 249),
          site_move.check_refusal(0, 0, 250)), (True, ""))
файл_уступки = TMP / "oom_score_adj"
проверка("правило 1: сбор пишет системе число уступки",
         (site_move.yield_memory(str(файл_уступки)), файл_уступки.read_text()),
         (True, str(site_move.OOM_YIELD)))
проверка("…число больше нуля: система закроет сбор раньше сайта",
         0 < site_move.OOM_YIELD <= 1000)
проверка("правило 2: файла нет (не Linux) — без падения, ответ «не получилось»",
         site_move.yield_memory(str(TMP / "нет-такой-папки" / "oom_score_adj")), False)
сбор = Сбор({})
забыть_проверки()
site_move.server_step(conn, T1, сбор, Адрес({}), ПЛАНЫ, plan_push.set_mode, free=lambda: 800)
проверка(f"за один заход — не больше {site_move.SITES_PER_RUN} сайтов",
         len(сбор.собирали), site_move.SITES_PER_RUN)
проверка("оставшийся сайт ждёт следующего захода сторожа",
         len(site_move.oneoff_due(conn, T1 + timedelta(minutes=15))), 1)

print("Ц6. Сторож: нечего делать — без замка и без сети; итог сбора по отчёту")


@contextmanager
def замок_свободен():
    взяли.append(1)
    yield ""


взяли: list = []
conn.execute("UPDATE sources SET selector_config = '{}'")
conn.commit()
проверка("сайтов к ходу нет — сторож выходит сразу, замок не трогает",
         (server_crawl.ход_по_сторожу(conn, now=T1, lock=замок_свободен), взяли), ([], []))
источник("w.tv")
site_move.after_import(conn, папка("ст1", "771", [строка("w.tv", "не открылась", BAN)]), now=T0)
сбор = Сбор({})
server_crawl.ход_по_сторожу(conn, now=T1, crawl_site=сбор, fetch_one=Адрес({}),
                            set_mode=plan_push.set_mode, plan={"w.tv": сайт_плана("w.tv")},
                            lock=замок_свободен, free=lambda: 800)
проверка("есть сайт к ходу — сторож берёт замок заливки и собирает сайт",
         (взяли, [d for d, _ in сбор.собирали]), ([1], ["w.tv"]))
отчёт = TMP / "итог.json"
отчёт.write_text(json.dumps({"строки": [строка("w.tv", "не открылась", NET),
                                         строка("w.tv", "расписание есть")]}), encoding="utf-8")
проверка("хоть одна страница с расписанием — «ok»", server_crawl.итог_сбора(отчёт)["итог"], "ok")
отчёт.write_text(json.dumps({"строки": [строка("w.tv", "не открылась", NET),
                                         строка("w.tv", "заглушка защиты", "cloudflare")]}),
                 encoding="utf-8")
проверка("сервер получил заглушку защиты — «ban» с причиной",
         server_crawl.итог_сбора(отчёт), {"итог": "ban", "почему": "заглушка защиты: cloudflare"})
отчёт.write_text(json.dumps({"строки": [строка("w.tv", "не открылась", NET)]}), encoding="utf-8")
проверка("только таймаут — «down»", server_crawl.итог_сбора(отчёт)["итог"], "down")
проверка("отчёта нет — «down»", server_crawl.итог_сбора(TMP / "нет.json")["итог"], "down")
сторож = (ROOT / "scripts" / "crawl_watch.py").read_text(encoding="utf-8")
проверка("сторож зовёт ход сервера ПОСЛЕ общего замка заявок",
         "server_move()" in сторож
         and сторож.index("code = _run(check=False)") < сторож.index("    server_move()\n    return code"))

print("Проба возврата на GitHub — с читалками (слово владельца 13.11)")
import crawl_fetch  # noqa: E402
from app import fetch  # noqa: E402


class Закрыт:
    """GitHub получает 403; читалка отдаёт страницу с расписанием."""
    browser_only = False

    def __init__(self):
        self.читалкой = []

    def get_with_fallback(self, url, **kwargs):
        return fetch.Page(url, "", False, "HTTP 403")

    def via_readers(self, url, accept=None, only=None, timeout=None):
        self.читалкой.append(url)
        html = "<p>20:45 Arsenal - Chelsea</p><p>22:00 Milan - Inter</p>"
        if accept is not None and not accept(html):
            return fetch.Page(url, "", False, "страница без расписания")
        return fetch.Page(url, html, False, via="reader:r.test", reader=("r.test", {}))


качалка = Закрыт()
итог = crawl_fetch.проба_одним_адресом(сайт_плана("back.tv"), качалка, readers=True)
проверка("GitHub не пустили, читалка взяла — проба «расписание есть (через читалку …)»",
         (итог["итог"], итог["почему"], len(качалка.читалкой)),
         ("расписание есть", "(через читалку r.test)", 1))
проверка("такая проба считается открывшейся — сайт вернётся на GitHub",
         site_move.return_opened(site_move.return_item(итог, T0)))
качалка = Закрыт()
итог = crawl_fetch.проба_одним_адресом(сайт_плана("back.tv"), качалка)
проверка("проверка с сервера читалками не пользуется: её вопрос — пускает ли сайт сам сервер",
         (итог["итог"], качалка.читалкой), ("не открылась", []))

print("Главная страница админки: список «Собирает сервер»")
conn.execute("UPDATE sources SET selector_config = '{}'")
conn.commit()
app = web.create_app()
админ = app.test_client()
админ.post("/login", data={"password": "adm-test-1"})
страница = админ.get("/").get_data(as_text=True)
проверка("ни одного сайта на сервере — так и сказано",
         "Собирает сервер" in страница and "Все сайты собирает GitHub" in страница)
conn.execute("UPDATE sources SET selector_config = ? WHERE domain = 'two.tv'",
             (json.dumps({"by_server": True, "moved_by": "auto",
                          "moved_at": "2026-11-14 11:05",
                          "server_ok_last": "2026-11-14 11:06"}),))
conn.execute("UPDATE sources SET selector_config = ? WHERE domain = 'ban.tv'",
             (json.dumps({"gh_fail_streak": 1, "gh_fail_last_slot": "9"}),))
conn.commit()
страница = админ.get("/").get_data(as_text=True)
проверка("сайт на сервере — в таблице, с причиной и временем последнего сбора",
         "two.tv" in страница and "переведён на сервер автоматически 14.11" in страница
         and "2026-11-14 11:06" in страница)
проверка("сайт на очереди к серверу — отдельной строкой",
         "На очереди у сервера" in страница and "ban.tv" in страница)
conn.close()

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

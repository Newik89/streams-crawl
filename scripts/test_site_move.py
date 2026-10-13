# -*- coding: utf-8 -*-
"""Перевод сайта на сервер и обратно — схема сбоев, шаг 11 (`app/site_move.py`).

Сценарий на каждое правило П1–П7 шапки модуля: временная база, временный
план, подменённые скачивание (никакой сети), часы, память и замок заливки.

Запуск (из папки движка): venv/Scripts/python.exe scripts/test_site_move.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

TMP = Path(tempfile.mkdtemp(prefix="site-move-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")
os.environ["STREAMS_ADMIN_PASSWORD"] = "adm-test-1"
os.environ.pop("GITHUB_ACTIONS", None)

from app import alarm_mail, crawl_hook, db, fetch, plan_push, redo, site_move, store, watch  # noqa: E402
import crawl_fetch  # noqa: E402
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


# ── временная база, план и подмены ──────────────────────────────────────────

ПЛАН = TMP / "crawl_plan.json"
plan_push.PLAN = ПЛАН                        # set_mode правит ЭТОТ план
КОММИТЫ_ПЛАНА: list[str] = []


def _push_plan_подмена(message: str) -> str:
    """git не трогаем: только запомнить, с каким словом ушёл бы план."""
    КОММИТЫ_ПЛАНА.append(message)
    return "push пропущен (проверка)"


plan_push._push_plan = _push_plan_подмена
server_crawl.ПАМЯТЬ = TMP / "server_crawl.json"   # не results/ движка

conn = db.connect()
db.init_db(conn)


def источник(домен: str, role: str = "schedule", enabled: int = 1, **config) -> None:
    conn.execute("INSERT INTO sources (domain, name, base_url, role, enabled, "
                 "selector_config) VALUES (?, ?, ?, ?, ?, ?)",
                 (домен, домен, f"https://{домен}/", role, enabled,
                  json.dumps(config, ensure_ascii=False)))
    conn.commit()


def настройки(домен: str) -> dict:
    row = conn.execute("SELECT selector_config FROM sources WHERE domain = ?",
                       (домен,)).fetchone()
    return json.loads(row["selector_config"] or "{}")


def поправить(домен: str, **поля) -> None:
    config = настройки(домен)
    for k, v in поля.items():
        if v is None:
            config.pop(k, None)
        else:
            config[k] = v
    conn.execute("UPDATE sources SET selector_config = ? WHERE domain = ?",
                 (json.dumps(config, ensure_ascii=False), домен))
    conn.commit()


def сайт_плана(домен: str, **поля) -> dict:
    s = {"domain": домен, "timezone": "Europe/Kyiv", "grid": False,
         "days_inline": False, "base_url": f"https://{домен}/", "marks": {},
         "pages_per_day": 0, "max_days": 0, "days_ahead": 0,
         "by_server": False, "manual_only": False,
         "channels": [{"name": "Kanal 1", "pattern": f"https://{домен}/k1/{{YYYY-MM-DD}}"},
                      {"name": "Kanal 2", "pattern": f"https://{домен}/k2/{{YYYY-MM-DD}}"}]}
    s.update(поля)
    return s


def записать_план(*сайты) -> None:
    ПЛАН.write_text(json.dumps({"days": 2, "sources": list(сайты)},
                               ensure_ascii=False, indent=1), encoding="utf-8")


def строка(домен: str, итог: str, почему: str = "", **поля) -> dict:
    return {"domain": домен, "channel": "", "day": "2026-10-13",
            "url": f"https://{домен}/k1/2026-10-13", "итог": итог,
            "почему": почему, **поля}


def отчёт(прогон: str, строки: list, режим: str = "полный обход, окно 6 суток",
          **ещё) -> dict:
    return {"когда": "2026-10-13", "режим": режим, "прогон": прогон,
            "строки": строки, "дозор": {"dozor.com": {}}, **ещё}


def папка(имя: str, rep: dict, разобрано: dict | None = None) -> Path:
    p = TMP / имя
    p.mkdir(exist_ok=True)
    (p / "report.json").write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    (p / "games.json").write_text(json.dumps(
        {"собрано": "2026-10-13 05:00", "игр": 0, "games": [],
         "разобрано": разобрано or {}}, ensure_ascii=False), encoding="utf-8")
    return p / "report.json"


def строки_прогонов(после: int = 0) -> list[str]:
    out = []
    for r in conn.execute("SELECT id, log FROM runs WHERE id > ? ORDER BY id", (после,)):
        out.append((json.loads(r["log"] or "{}") or {}).get("режим") or "")
    return out


def последний_прогон() -> int:
    return alarm_mail.last_row_id(conn)


T0 = datetime(2026, 10, 13, 9, 30, tzinfo=KYIV)

BAN = "HTTP 403"
NET = "ConnectTimeout: HTTPSConnectionPool(host=…)"

источник("ban.tv")
источник("ok.tv")
источник("empty.tv")
источник("srv.tv", by_server=True, manual_only=True)       # перевёл владелец
источник("dozor.com")
источник("spr.tv", role="directory")
источник("off.tv", enabled=0)
источник("www.wwwsite.tv")


# ── П1. счёт срывов ─────────────────────────────────────────────────────────

print("П1. Проба = сбор GitHub: что за заливка")
проверка("полный обход с id прогона — «сбор»",
         site_move.import_kind(отчёт("101", [])), "сбор")
проверка("кнопка «Обойти сайт» на GitHub (заливка results/site, «кто» — «кнопка») — «кнопка»",
         site_move.import_kind(отчёт("102", []), who="кнопка"), "кнопка")
проверка("…и по самому отчёту: --only даёт оценку «строгая»: false — «кнопка»",
         site_move.import_kind(отчёт("102", [], **{"оценка": {"код": 0, "строгая": False}})),
         "кнопка")
проверка("полный обход без фильтров (оценка строгая) — «сбор»",
         site_move.import_kind(отчёт("102", [], **{"оценка": {"код": 0, "строгая": True}})),
         "сбор")
проверка("переразбор (отчёт того же сбора, кто «переразбор») — «сбор»",
         site_move.import_kind(отчёт("103", []), who="переразбор"), "сбор")
проверка("дозабор (раздел «дозабор») — «дозабор»",
         site_move.import_kind(отчёт("200", [], **{"дозабор": {"из прогона": "103"}}),
                               who="дозабор"), "дозабор")
проверка("скан даты — «скан»",
         site_move.import_kind(отчёт("104", [], режим="скан даты 2026-10-20")), "скан")
проверка("серверный сбор (кто «сервер …») — «сервер»",
         site_move.import_kind(отчёт("", []), who="сервер srv.tv"), "сервер")
проверка("проба площадки — ничего",
         site_move.import_kind(отчёт("105", [], режим="проба площадки")), "")
проверка("нет id прогона GitHub (компьютер, старый отчёт) — ничего",
         site_move.import_kind(отчёт("", [строка("ban.tv", "не открылась", BAN)])), "")
проверка("id сбора у дозабора — прогон, ЧЕЙ отчёт дозабирал",
         site_move.crawl_id(отчёт("200", [], **{"дозабор": {"из прогона": "103"}})), "103")

print("П1. Итог сайта в сборе")
вердикты = site_move.site_verdicts([
    строка("ban.tv", "заглушка защиты", "cloudflare"),
    строка("ban.tv", "не открылась", BAN),
    строка("down.tv", "не открылась", "HTTP 503"),
    строка("net.tv", "не открылась", NET),
    строка("mix.tv", "пусто", "времени на странице нет"),
    строка("mix.tv", "не открылась", NET),
    строка("ok.tv", "не открылась", BAN),
    строка("ok.tv", "расписание есть"),
    строка("empty.tv", "пусто", "времени на странице нет"),
    строка("short.tv", "нет на этот день", "не поломка"),
    строка("gone.tv", "не открылась", "HTTP 404"),
    строка("parsed.tv", "пусто", ""),
    строка("dozor.com", "не открылась", BAN),
    строка("www.wwwsite.tv", "не открылась", BAN),
], parsed={"parsed.tv": 5}, never={"dozor.com"})
проверка("все страницы ban — «не дался»", вердикты.get("ban.tv", {}).get("итог"), "fail")
проверка("5xx — «не дался»", вердикты.get("down.tv", {}).get("итог"), "fail")
проверка("нет ответа — «не дался»", вердикты.get("net.tv", {}).get("итог"), "fail")
проверка("«пусто» и сеть вперемешку, расписания нет — «не дался»",
         вердикты.get("mix.tv", {}).get("итог"), "fail")
проверка("хоть одна страница с расписанием — «дался»",
         вердикты.get("ok.tv", {}).get("итог"), "ok")
проверка("разбор дал строки при «пусто» — «дался» (как log_run)",
         вердикты.get("parsed.tv", {}).get("итог"), "ok")
проверка("только «пусто» — нейтрально (не поломка)", "empty.tv" in вердикты, False)
проверка("только «нет на этот день» — нейтрально", "short.tv" in вердикты, False)
проверка("только 404 (сайт ответил «нет страницы») — нейтрально", "gone.tv" in вердикты, False)
проверка("дозорный сайт не судим", "dozor.com" in вердикты, False)
проверка("домен с www — без www", "wwwsite.tv" in вердикты, True)
проверка("причина срыва — первая упавшая строка",
         вердикты["ban.tv"]["почему"], "заглушка защиты: cloudflare")

print("П1. Один сбор — одна проба")
cfg: dict = {}
проверка("срыв сбора 101 — +1", site_move.apply_probe(cfg, {"итог": "fail", "почему": "x"}, "101", T0), "fail")
проверка("тот же сбор 101 ещё раз (второй заход, переразбор) — не считается",
         site_move.apply_probe(cfg, {"итог": "fail", "почему": "x"}, "101", T0), "same")
проверка("сбор 102 — +1", site_move.apply_probe(cfg, {"итог": "fail", "почему": "x"}, "102", T0), "fail")
проверка("счёт 2, начало серии записано",
         (cfg.get("gh_fail_streak"), cfg.get("gh_fail_first")), (2, "2026-10-13 09:30"))
проверка("удача — счёт обнулён", site_move.apply_probe(cfg, {"итог": "ok"}, "103", T0), "reset")
проверка("после обнуления полей серии нет", cfg.get("gh_fail_streak"), None)
проверка("без id сбора срыв не считаем",
         site_move.apply_probe({}, {"итог": "fail"}, "", T0), "")

print("П1. Заливка трёх сборов подряд (база)")
до = последний_прогон()
сбор_строки = [строка("ban.tv", "не открылась", BAN),
               строка("ok.tv", "расписание есть"),
               строка("empty.tv", "пусто", "времени на странице нет"),
               строка("srv.tv", "не открылась", BAN),
               строка("dozor.com", "не открылась", BAN),
               строка("spr.tv", "не открылась", BAN),
               строка("off.tv", "не открылась", BAN)]
поправить("ok.tv", gh_fail_streak=2, gh_fail_last_slot="99")
for n, прогон in enumerate(("301", "302", "303")):
    site_move.after_import(conn, папка(f"сбор{прогон}", отчёт(прогон, сбор_строки)),
                           who="", now=T0 + timedelta(hours=8 * n))
проверка("ban.tv: 3 сбора подряд", настройки("ban.tv").get("gh_fail_streak"), 3)
проверка("ban.tv: последний засчитанный сбор 303",
         настройки("ban.tv").get("gh_fail_last_slot"), "303")
проверка("ok.tv дался — счёт обнулён", настройки("ok.tv").get("gh_fail_streak"), None)
проверка("empty.tv («пусто») — не тронут", настройки("empty.tv").get("gh_fail_streak"), None)
проверка("srv.tv (качает сервер) — не считается", настройки("srv.tv").get("gh_fail_streak"), None)
проверка("дозорный — не считается", настройки("dozor.com").get("gh_fail_streak"), None)
проверка("справочник — не считается", настройки("spr.tv").get("gh_fail_streak"), None)
проверка("выключенный — не считается", настройки("off.tv").get("gh_fail_streak"), None)
новые = строки_прогонов(до)
проверка("на третьем срыве — одна строка «кандидат» в «Прогонах»",
         sum("ban.tv: 3 сбора подряд не дался GitHub" in s for s in новые), 1)
проверка("строка «кандидат» — уведомление, не ТРЕВОГА",
         any("ТРЕВОГА" in s for s in новые), False)
site_move.after_import(conn, папка("сбор303", отчёт("303", сбор_строки)), who="переразбор",
                       now=T0 + timedelta(hours=20))
проверка("повторная заливка сбора 303 — счёт тот же", настройки("ban.tv").get("gh_fail_streak"), 3)

print("П1. Скан даты и дозабор только обнуляют")
поправить("empty.tv", gh_fail_streak=1, gh_fail_last_slot="300")
site_move.after_import(conn, папка("скан1", отчёт("401", [строка("empty.tv", "не открылась", BAN)],
                                                  режим="скан даты 2026-10-20")), now=T0)
проверка("срыв в скане даты не считается", настройки("empty.tv").get("gh_fail_streak"), 1)
site_move.after_import(conn, папка("скан2", отчёт("402", [строка("empty.tv", "расписание есть")],
                                                  режим="скан даты 2026-10-20")), now=T0)
проверка("удача в скане даты — обнуляет", настройки("empty.tv").get("gh_fail_streak"), None)
источник("down.tv", gh_fail_streak=2, gh_fail_last_slot="303")
дозабор_плохой = отчёт("501", [строка("down.tv", "не открылась", "HTTP 503")],
                       **{"дозабор": {"из прогона": "304",
                                      "строки": [строка("down.tv", "не открылась", "HTTP 503")]}})
site_move.after_import(conn, папка("дозабор1", дозабор_плохой), who="дозабор", now=T0)
проверка("дозабор, где сайт снова упал, — не +1", настройки("down.tv").get("gh_fail_streak"), 2)
дозабор_хороший = отчёт("502", [строка("down.tv", "расписание есть")],
                        **{"дозабор": {"из прогона": "304",
                                       "строки": [строка("down.tv", "расписание есть")]}})
site_move.after_import(conn, папка("дозабор2", дозабор_хороший), who="дозабор", now=T0)
проверка("дозабор, выправивший сайт, — обнуляет", настройки("down.tv").get("gh_fail_streak"), None)

print("П1. Кнопка «Обойти сайт» только обнуляет")
источник("btn.tv")
for n, прогон in enumerate(("451", "452", "453")):
    site_move.after_import(conn, папка(f"кнопка{прогон}", отчёт(
        прогон, [строка("btn.tv", "не открылась", BAN)],
        **{"оценка": {"код": 0, "строгая": False}})), who="кнопка",
        now=T0 + timedelta(minutes=20 * n))
проверка("три срыва кнопкой за час — счёт 0", настройки("btn.tv").get("gh_fail_streak"), None)
проверка("…не кандидат", "btn.tv" in [c["domain"] for c in site_move.candidates(conn, T0)], False)
поправить("btn.tv", gh_fail_streak=2, gh_fail_last_slot="440")
site_move.after_import(conn, папка("кнопка454", отчёт(
    "454", [строка("btn.tv", "расписание есть")], **{"оценка": {"код": 0, "строгая": False}})),
    who="кнопка", now=T0)
проверка("удача кнопкой — обнуляет", настройки("btn.tv").get("gh_fail_streak"), None)

print("П1. Серверный сбор — только «сервер скачал»")
site_move.after_import(conn, папка("сервер", отчёт("", [строка("srv.tv", "расписание есть")])),
                       who="сервер srv.tv", now=T0)
проверка("server_ok_last у srv.tv", настройки("srv.tv").get("server_ok_last"), "2026-10-13 09:30")
проверка("счёт у srv.tv не появился", настройки("srv.tv").get("gh_fail_streak"), None)

print("П1. Массовый сбой (сеть GitHub) и закрытые владельцем")
проверка("порог массового = порог провала обхода (FAIL_DOMAINS_SHARE)",
         site_move.MASS_SHARE, crawl_fetch.FAIL_DOMAINS_SHARE)
источник("mass1.tv")
хорошие = [строка(f"g{i}.tv", "расписание есть") for i in range(8)]
site_move.after_import(conn, папка("масс", отчёт("801", [строка("mass1.tv", "не открылась", NET)]
                                                + [строка(f"m{i}.tv", "не открылась", NET)
                                                   for i in range(3)] + хорошие)), now=T0)
проверка("12 сайтов, не дались 4 (33 %) — массовый: срыв не засчитан",
         настройки("mass1.tv").get("gh_fail_streak"), None)
site_move.after_import(conn, папка("норм", отчёт("802", [строка("mass1.tv", "не открылась", NET)]
                                                + хорошие + [строка(f"h{i}.tv", "пусто")
                                                             for i in range(3)])), now=T0)
проверка("12 сайтов, не дался 1 — обычный сбор: срыв засчитан",
         настройки("mass1.tv").get("gh_fail_streak"), 1)
проверка("кнопка «Обойти сайт» (один сайт) — не массовый",
         site_move.is_mass([строка("x.tv", "не открылась", NET)], {"x.tv": {"итог": "fail"}}), False)
источник("closed.tv")
conn.execute("UPDATE sources SET status = 'closed' WHERE domain = 'closed.tv'")
conn.commit()
site_move.after_import(conn, папка("закрыт", отчёт("803", [строка("closed.tv", "не открылась", BAN)])),
                       now=T0)
проверка("закрытый владельцем (status closed) — не считается",
         настройки("closed.tv").get("gh_fail_streak"), None)
источник("bein.tv", manual_only=True)          # как beinsports.com.tr (08.10)
for n, прогон in enumerate(("811", "812", "813")):
    site_move.after_import(conn, папка(f"bein{прогон}",
                                       отчёт(прогон, [строка("bein.tv", "не открылась", BAN)])),
                           now=T0 + timedelta(minutes=20 * n))
проверка("«только по кнопке» (beinsports): три срыва — счёт не ведётся",
         настройки("bein.tv").get("gh_fail_streak"), None)
поправить("bein.tv", gh_fail_streak=3, gh_fail_last_slot="813")
проверка("…и даже со счётом 3 — не кандидат на перевод",
         "bein.tv" in [c["domain"] for c in site_move.candidates(conn, T0)], False)
проверка("…и --once его не переводит",
         "решил владелец" in site_move.server_turn(conn, T0, lambda s: {}, {}, None,
                                                   only="bein.tv")[0])
поправить("bein.tv", gh_fail_streak=None, gh_fail_last_slot=None)

print("П1. Сквозная заливка games_import.py (тот же путь, что на сервере)")
источник("e2e.tv")
путь = папка("e2e", отчёт("777", [строка("e2e.tv", "не открылась", NET)]))
готово = subprocess.run([sys.executable, str(ROOT / "scripts" / "games_import.py"),
                         "--file", str(путь.parent / "games.json"), "--who", "тест"],
                        capture_output=True, text=True, encoding="utf-8", env=os.environ)
проверка("заливка прошла", готово.returncode, 0)
проверка("в журнале заливки — строка счёта", "перевод сайтов: e2e.tv: не дался GitHub 1 сбор подряд"
         in готово.stdout)
проверка("счёт e2e.tv = 1 в базе", настройки("e2e.tv").get("gh_fail_streak"), 1)


# ── П2. кандидат: проверка с сервера одним адресом ──────────────────────────

print("П2. Кандидаты")
кандидаты = [c["domain"] for c in site_move.candidates(conn, T0 + timedelta(days=1))]
проверка("ban.tv (3 подряд) — кандидат", "ban.tv" in кандидаты)
проверка("e2e.tv (1 подряд) — нет", "e2e.tv" in кандидаты, False)
поправить("srv.tv", gh_fail_streak=5)
проверка("by_server со счётом — не кандидат",
         "srv.tv" in [c["domain"] for c in site_move.candidates(conn, T0)], False)
поправить("srv.tv", gh_fail_streak=None)
поправить("ban.tv", server_check_last="2026-10-14 00:00")
проверка("проверяли 9,5 ч назад — не кандидат (не чаще 20 ч)",
         "ban.tv" in [c["domain"] for c in site_move.candidates(conn, T0 + timedelta(days=1))], False)
проверка("через 21 ч — снова кандидат",
         "ban.tv" in [c["domain"] for c in site_move.candidates(
             conn, datetime(2026, 10, 14, 21, 0, tzinfo=KYIV))])
поправить("ban.tv", server_check_last=None)


class Качалка:
    """Подмена `fetch_one`: что вернуть по домену, и кого спросили."""

    def __init__(self, итоги: dict):
        self.итоги, self.спросили = итоги, []

    def __call__(self, source: dict) -> dict:
        self.спросили.append(source["domain"])
        итог, почему = self.итоги.get(source["domain"], ("не открылась", NET))
        return {"domain": source["domain"], "url": "https://x/", "итог": итог, "почему": почему}


записать_план(сайт_плана("ban.tv"), сайт_плана("ok.tv"), сайт_плана("srv.tv", by_server=True,
                                                                     manual_only=True),
              сайт_плана("dead.tv"), сайт_плана("a1.tv"), сайт_плана("a2.tv"),
              сайт_плана("a3.tv"), сайт_плана("a4.tv"), сайт_плана("once.tv"))
ПЛАН_ДОМЕНЫ = server_crawl.план_по_доменам()
проверка("план читается по доменам", sorted(ПЛАН_ДОМЕНЫ)[:2], ["a1.tv", "a2.tv"])
T1 = datetime(2026, 10, 14, 6, 40, tzinfo=KYIV)

print("П2. Сервер скачал → перевод на сервер (настоящий set_mode, временный план)")
поправить("ban.tv", gh_fail_why="не открылась: HTTP 403")
conn.execute("UPDATE sources SET status = 'broken', fail_count = 4 WHERE domain = 'ban.tv'")
conn.commit()
до = последний_прогон()
кач = Качалка({"ban.tv": ("расписание есть", "")})
said = site_move.server_turn(conn, T1, кач, ПЛАН_ДОМЕНЫ, plan_push.set_mode, free=lambda: 800)
c = настройки("ban.tv")
проверка("спросили ОДИН адрес ban.tv", кач.спросили, ["ban.tv"])
проверка("в базе: by_server и manual_only", (c.get("by_server"), c.get("manual_only")), (True, True))
проверка("moved_by=auto, moved_at записан", (c.get("moved_by"), bool(c.get("moved_at"))),
         ("auto", True))
проверка("коммит плана — со словом «автоматически»",
         "автоматически" in (КОММИТЫ_ПЛАНА[-1] if КОММИТЫ_ПЛАНА else ""))
проверка("счёт срывов обнулён при переводе", (c.get("gh_fail_streak"), c.get("gh_fail_last_slot")), (None, None))
проверка("server_ok_last и server_check_last", (c.get("server_ok_last"), c.get("server_check_last")),
         ("2026-10-14 06:40", "2026-10-14 06:40"))
проверка("в плане: by_server у ban.tv",
         next(s for s in json.loads(ПЛАН.read_text(encoding="utf-8"))["sources"]
              if s["domain"] == "ban.tv")["by_server"], True)
st = conn.execute("SELECT status, fail_count FROM sources WHERE domain='ban.tv'").fetchone()
проверка("клеймо «сломан» снято", (st["status"], st["fail_count"]), ("ok", 0))
новые = строки_прогонов(до)
проверка("строка владельцу «ПЕРЕВЕДЁН НА СЕРВЕР»", any("ban.tv" in s and "ПЕРЕВЕДЁН НА СЕРВЕР" in s
                                                       for s in новые))
проверка("перевод — уведомление, не ТРЕВОГА", any("ТРЕВОГА" in s for s in новые), False)
проверка("разовая проверка записана в память", site_move.checks_today(conn, T1), 1)

print("П2. Сервер тоже не скачал → не переводим, ТРЕВОГА одна на серию")
источник("dead.tv", gh_fail_streak=4, gh_fail_last_slot="310", gh_fail_why="не открылась: HTTP 503")
до = последний_прогон()
кач = Качалка({"dead.tv": ("не открылась", "HTTP 503")})
site_move.server_turn(conn, T1, кач, ПЛАН_ДОМЕНЫ, plan_push.set_mode, free=lambda: 800)
проверка("dead.tv не переведён", настройки("dead.tv").get("by_server"), None)
первые = строки_прогонов(до)
проверка("ТРЕВОГА «не отвечает ни GitHub, ни серверу»",
         sum(s.startswith("перевод сайтов: ТРЕВОГА — dead.tv не отвечает ни GitHub") for s in первые), 1)
проверка("тревога попадёт в письмо (alarm_mail)", len(alarm_mail.new_alarms(conn, до)), 1)
до = последний_прогон()
site_move.server_turn(conn, T1 + timedelta(days=1), кач, ПЛАН_ДОМЕНЫ, plan_push.set_mode,
                      free=lambda: 800)
вторые = строки_прогонов(до)
проверка("назавтра — строка без ТРЕВОГИ", (len(вторые), any("ТРЕВОГА" in s for s in вторые)), (1, False))
проверка("…и в ней сказано, когда уходило письмо", "письмо об этом уходило 14.10" in вторые[0])
site_move.after_import(conn, папка("ожил", отчёт("320", [строка("dead.tv", "расписание есть")])), now=T1)
проверка("удача на GitHub закрывает серию (и пометку письма)",
         (настройки("dead.tv").get("gh_fail_streak"), настройки("dead.tv").get("server_fail_alarm")),
         (None, None))

print("П2. Пределы: ≤3 сайта за заход, ≤5 в сутки, память, замок, план")
for d in ("a1.tv", "a2.tv", "a3.tv", "a4.tv"):
    источник(d, gh_fail_streak=3, gh_fail_last_slot="330", gh_fail_why="x")
T2 = datetime(2026, 10, 16, 6, 40, tzinfo=KYIV)
до = последний_прогон()
кач = Качалка({})
site_move.server_turn(conn, T2, кач, ПЛАН_ДОМЕНЫ, plan_push.set_mode, free=lambda: 800)
проверка("за заход — 3 сайта, по одному", кач.спросили, ["a1.tv", "a2.tv", "a3.tv"])
проверка("остальные — строкой «не больше 3»",
         any("a4.tv" in s and "не больше 3" in s for s in строки_прогонов(до)))
кач = Качалка({})
site_move.server_turn(conn, T2 + timedelta(minutes=5), кач, ПЛАН_ДОМЕНЫ, plan_push.set_mode,
                      free=lambda: 800)
проверка("второй заход через 5 мин: только a4.tv (остальных проверяли < 20 ч назад)",
         (кач.спросили, site_move.checks_today(conn, T2)), (["a4.tv"], 4))
источник("a5.tv", gh_fail_streak=3, gh_fail_last_slot="330")
источник("a6.tv", gh_fail_streak=3, gh_fail_last_slot="330")
записать_план(*[сайт_плана(d) for d in ("ban.tv", "a1.tv", "a2.tv", "a3.tv", "a4.tv",
                                         "a5.tv", "a6.tv", "dead.tv", "once.tv")])
ПЛАН_ДОМЕНЫ = server_crawl.план_по_доменам()
до = последний_прогон()
кач = Качалка({})
site_move.server_turn(conn, T2 + timedelta(minutes=10), кач, ПЛАН_ДОМЕНЫ, plan_push.set_mode,
                      free=lambda: 800)
проверка("пятая проверка за сутки — последняя", кач.спросили, ["a5.tv"])
проверка("дальше — «за сутки уже 5»", any("за сутки уже 5" in s for s in строки_прогонов(до)))
T3 = datetime(2026, 10, 17, 6, 40, tzinfo=KYIV)
кач = Качалка({})
site_move.server_turn(conn, T3, кач, ПЛАН_ДОМЕНЫ, plan_push.set_mode, free=lambda: 350)
проверка("свободно 350 МБ — никого не качаем", кач.спросили, [])
проверка("…строка «нужно не меньше 400»",
         any("свободно 350 МБ" in s and "не меньше 400" in s for s in строки_прогонов(до)))
кач = Качалка({})
site_move.server_turn(conn, T3, кач, ПЛАН_ДОМЕНЫ, plan_push.set_mode, free=lambda: None)
проверка("память неизвестна — тоже не качаем", кач.спросили, [])
до = последний_прогон()
кач = Качалка({})
site_move.server_turn(conn, T3, кач, ПЛАН_ДОМЕНЫ, plan_push.set_mode, free=lambda: 800,
                      busy="идёт заливка (streams-update.sh)")
проверка("идёт заливка — никого не качаем", кач.спросили, [])
проверка("…одна строка «откладываю — идёт заливка»",
         (len(строки_прогонов(до)), "откладываю" in строки_прогонов(до)[0]), (1, True))
источник("noplan.tv", gh_fail_streak=3, gh_fail_last_slot="330")
до = последний_прогон()
кач = Качалка({})
site_move.server_turn(conn, T3, кач, ПЛАН_ДОМЕНЫ, plan_push.set_mode, free=lambda: 800,
                      only="noplan.tv")
проверка("сайта нет в плане — не качаем, строка",
         (кач.спросили, any("noplan.tv: в плане обхода сайта нет" in s for s in строки_прогонов(до))),
         ([], True))

print("П2. Сбой внутри захода его не обрывает")
источник("boom.tv", gh_fail_streak=3, gh_fail_last_slot="370", gh_fail_why="x")
источник("boom2.tv", gh_fail_streak=3, gh_fail_last_slot="370", gh_fail_why="x")


def взрыв(source: dict) -> dict:
    if source["domain"] == "boom.tv":
        raise ConnectionError("сеть упала")
    return {"итог": "расписание есть", "почему": ""}


def set_mode_сбой(c, домен, by_server, by="owner", why="", restore=None):
    raise TimeoutError("git завис")


до = последний_прогон()
site_move.server_turn(conn, datetime(2026, 10, 18, 6, 40, tzinfo=KYIV), взрыв,
                      {"boom.tv": сайт_плана("boom.tv"), "boom2.tv": сайт_плана("boom2.tv")},
                      set_mode_сбой, free=lambda: 800, limit=10)
новые = строки_прогонов(до)
проверка("качалка упала — «не дошли» с причиной, заход идёт дальше",
         any(s.startswith("перевод сайтов: ТРЕВОГА — boom.tv") and "ConnectionError" in s
             for s in новые))
проверка("set_mode упал — строка «перевод не доделан», сайт не на сервере",
         (any("boom2.tv" in s and "перевод не доделан: TimeoutError" in s for s in новые),
          настройки("boom2.tv").get("by_server")), (True, None))
for d in ("boom.tv", "boom2.tv"):
    поправить(d, gh_fail_streak=None)

print("П2. Потолок: не больше 5 сайтов, переведённых автоматически")
уже = site_move.auto_moved(conn)
заполнители = [f"auto{i}.tv" for i in range(site_move.AUTO_MOVED_MAX - len(уже))]
for d in заполнители:
    источник(d, by_server=True, manual_only=True, moved_by="auto", moved_at="2026-10-10 06:40")
проверка("на сервере автоматически ровно 5", len(site_move.auto_moved(conn)), 5)
for d in ("cap1.tv", "cap2.tv", "cap3.tv"):
    источник(d, gh_fail_streak=3, gh_fail_last_slot="390", gh_fail_why="x")
план_потолка = {d: сайт_плана(d) for d in ("cap1.tv", "cap2.tv", "cap3.tv")}
вызовы_потолка = []


def set_mode_потолок(c, домен, by_server, by="owner", why="", restore=None):
    вызовы_потолка.append(домен)
    return "не должен звать"


T5 = datetime(2026, 10, 19, 6, 40, tzinfo=KYIV)
до = последний_прогон()
кач = Качалка({d: ("расписание есть", "") for d in план_потолка})
site_move.server_turn(conn, T5, кач, {d: план_потолка[d] for d in ("cap1.tv", "cap2.tv")},
                      set_mode_потолок, free=lambda: 800, limit=10)
новые = строки_прогонов(до)
проверка("сервер скачал cap1 и cap2, но перевода нет", (кач.спросили, вызовы_потолка,
         настройки("cap1.tv").get("by_server")), (["cap1.tv", "cap2.tv"], [], None))
проверка("одна ТРЕВОГА на обоих: «просится 6-й сайт … не режут ли сеть GitHub»",
         [s for s in новые if "ТРЕВОГА" in s].__len__() == 1 and
         any("просится 6-й сайт (cap1.tv, cap2.tv)" in s and "не режут ли сеть GitHub" in s
             for s in новые))
до = последний_прогон()
site_move.server_turn(conn, T5 + timedelta(hours=1), кач, {"cap3.tv": план_потолка["cap3.tv"]},
                      set_mode_потолок, free=lambda: 800, limit=10)
новые = строки_прогонов(до)
проверка("в те же сутки — строка без ТРЕВОГИ",
         (any("cap3.tv" in s and "предел 5" in s for s in новые),
          any("ТРЕВОГА" in s for s in новые)), (True, False))
до = последний_прогон()
site_move.server_turn(conn, T5 + timedelta(days=1), кач, план_потолка, set_mode_потолок,
                      free=lambda: 800, limit=10)
проверка("на следующие сутки — снова одна ТРЕВОГА",
         sum("ТРЕВОГА" in s for s in строки_прогонов(до)), 1)
for d in заполнители + ["cap1.tv", "cap2.tv", "cap3.tv"]:
    conn.execute("UPDATE sources SET enabled = 0 WHERE domain = ?", (d,))
conn.commit()

print("П2. --once руками")
источник("once.tv", gh_fail_streak=1, gh_fail_last_slot="340")


@contextmanager
def _свободно():
    yield ""


@contextmanager
def _занято():
    yield "идёт заливка (streams-update.sh)"


кач = Качалка({"once.tv": ("расписание есть", "")})
said = server_crawl.разовая_проверка(conn, "once.tv", now=T3, fetch_one=кач,
                                     set_mode=plan_push.set_mode, plan=ПЛАН_ДОМЕНЫ,
                                     lock=_свободно, free=lambda: 800)
проверка("не кандидат: один адрес спросили, но не переводим",
         (кач.спросили, настройки("once.tv").get("by_server")), (["once.tv"], None))
проверка("…и говорим почему", any("не кандидат" in s for s in said))
said = server_crawl.разовая_проверка(conn, "once.tv", now=T3 + timedelta(hours=1), fetch_one=кач,
                                     set_mode=plan_push.set_mode, plan=ПЛАН_ДОМЕНЫ,
                                     lock=_свободно, free=lambda: 800)
проверка("второй раз за 20 ч — не ходим", (len(кач.спросили), "не чаще" in said[0]), (1, True))
проверка("--once по сайту «качает сервер» — нечего",
         server_crawl.разовая_проверка(conn, "srv.tv", now=T3, fetch_one=кач, plan=ПЛАН_ДОМЕНЫ,
                                       lock=_свободно, free=lambda: 800)[0].endswith("проверять нечего"))
путь_замка = str(TMP / "streams-update.lock")     # не настоящий /run/…


class Флок:
    """Подмена модуля fcntl (на Windows его нет): flock по имени файла."""
    LOCK_EX, LOCK_NB, LOCK_UN = 2, 4, 8

    def __init__(self):
        self.держат, self.снято = set(), 0

    def flock(self, файл, op):
        if op & self.LOCK_UN:
            self.держат.discard(файл.name)
            self.снято += 1
            return
        if файл.name in self.держат:
            raise BlockingIOError("занят")
        self.держат.add(файл.name)


настоящий = sys.modules.get("fcntl")
флок = sys.modules["fcntl"] = Флок()
try:
    with server_crawl.замок_заливки(путь_замка) as первый:
        проверка("замок заливки свободен — он наш (пусто)", первый, "")
        with server_crawl.замок_заливки(путь_замка) as второй:
            проверка("пока замок держим, второй заход видит «идёт заливка»",
                     второй.startswith("идёт заливка"))
    проверка("после захода замок отпущен", (флок.держат, флок.снято), (set(), 1))
    with server_crawl.замок_заливки(str(TMP / "нет-папки" / "x.lock")) as третий:
        проверка("замок не открылся — тоже «нельзя», с причиной",
                 третий.startswith("замок заливки не открылся"))
finally:
    if настоящий is None:
        sys.modules.pop("fcntl", None)
    else:
        sys.modules["fcntl"] = настоящий


# ── П3. глубина ─────────────────────────────────────────────────────────────

print("П3. Глубина серверного сбора")
проверка("--days главнее всего", site_move.server_depth({"max_days": 4, "moved_by": "auto"}, 3), 3)
проверка("свой потолок владельца (mojtv.hr — 4)", site_move.server_depth({"max_days": 4}), 4)
проверка("переведён автоматически — окно планового сбора",
         site_move.server_depth({"moved_by": "auto"}), 6)
проверка("переведён владельцем без потолка — 2, как было",
         site_move.server_depth({"moved_by": "owner"}), 2)
проверка("окно переведённого = самый глубокий плановый слот watch.SCHEDULE",
         site_move.MOVED_WINDOW_DAYS, max(d for _, d in watch.SCHEDULE))
проверка("к сайту с сервера не чаще = SITE_GAP_HOURS",
         site_move.CHECK_GAP_HOURS, crawl_hook.SITE_GAP_HOURS)
поправить("srv.tv", max_days=4)
глубины = dict(server_crawl.сайты())
проверка("server_crawl.сайты: ban.tv (авто) — 6, srv.tv (потолок) — 4",
         (глубины.get("ban.tv"), глубины.get("srv.tv")), (6, 4))
проверка("server_crawl.сайты --days 2 — 2 всем",
         set(dict(server_crawl.сайты(days=2)).values()), {2})
поправить("srv.tv", max_days=None)


# ── П4. обратный путь ───────────────────────────────────────────────────────

print("П4. Когда GitHub пробует вернуть (память обхода)")
U0 = datetime(2026, 10, 13, 6, 0, tzinfo=timezone.utc)
по_серверу = [сайт_плана("srv.tv", by_server=True), сайт_плана("new.tv", by_server=True)]
пора, память = site_move.return_due(по_серверу, {"old.tv": {"когда": "2026-01-01 00:00"}}, U0)
проверка("впервые увиденный «на сервере» — не сразу", пора, [])
проверка("…его минута записана, вернувшийся (old.tv) забыт",
         (sorted(память), память["srv.tv"]), (["new.tv", "srv.tv"], {"с": "2026-10-13 06:00"}))
проверка("через 6 дней — ещё рано",
         site_move.return_due(по_серверу, память, U0 + timedelta(days=6))[0], [])
пора, память = site_move.return_due(по_серверу, память, U0 + timedelta(days=7))
проверка("через 7 дней — пора обоим", пора, ["srv.tv", "new.tv"])
site_move.return_remember(память, "srv.tv", {"итог": "не открылась"}, U0 + timedelta(days=7))
проверка("после пробы — следующая через неделю",
         site_move.return_due(по_серверу, память, U0 + timedelta(days=13))[0], ["new.tv"])
проверка("on_github: только на GitHub Actions",
         (site_move.on_github({"GITHUB_ACTIONS": "true"}), site_move.on_github({})), (True, False))
проверка("«больше половины открылось»: 1 из 1", site_move.return_opened({"адресов": 1, "открылось": 1}))
проверка("0 из 1 — нет", site_move.return_opened({"адресов": 1, "открылось": 0}), False)
проверка("1 из 2 — нет (ровно половина)", site_move.return_opened({"адресов": 2, "открылось": 1}), False)
проверка("2 из 3 — да", site_move.return_opened({"адресов": 3, "открылось": 2}))


class Страницы:
    """Подмена Fetcher: отдаёт заданную страницу, помнит адреса."""

    def __init__(self, html: str = "", error: str = ""):
        self.html, self.error, self.адреса, self.browser_only = html, error, [], False

    def get_with_fallback(self, url, **kw):
        self.адреса.append(url)
        return fetch.Page(url, self.html, False, self.error)


print("П4. Проба возврата в полном обходе GitHub (crawl_fetch)")
память_путь = TMP / "vozvrat.json"
память_путь.write_text(json.dumps({"srv.tv": {"с": "2026-10-01 06:00"}}), encoding="utf-8")
план = {"sources": [сайт_плана("srv.tv", by_server=True, manual_only=True),
                    сайт_плана("new.tv", by_server=True, manual_only=True),
                    сайт_плана("plain.tv")]}
стр = Страницы(html="<div>20:00 Match</div>" * 3)
раздел = crawl_fetch.проба_возврата(план, стр, now=U0, путь=память_путь)
проверка("ОДИН адрес — только у сайта, которому пора", len(стр.адреса), 1)
проверка("адрес — первый канал на сегодня сайта", стр.адреса[0].startswith("https://srv.tv/k1/"))
проверка("раздел «проба_возврата»: srv.tv открылся",
         (list(раздел), раздел["srv.tv"]["итог"], раздел["srv.tv"]["открылось"]),
         (["srv.tv"], "расписание есть", 1))
проверка("обычный сайт не трогали", any("plain.tv" in a for a in стр.адреса), False)
память_после = json.loads(память_путь.read_text(encoding="utf-8"))
проверка("память обхода: srv.tv — когда пробовали, new.tv — с какой минуты ждём",
         (память_после["srv.tv"].get("когда"), sorted(память_после["new.tv"])),
         ("2026-10-13 06:00", ["с"]))
проверка("crawl_fetch: один_адрес из двух каналов × окно — ровно один",
         crawl_fetch.один_адрес(сайт_плана("two.tv"))["url"].startswith("https://two.tv/k1/"))
row = crawl_fetch.проба_одним_адресом(сайт_плана("bad.tv"), Страницы(error="HTTP 403"))
проверка("проба_одним_адресом: отказ — «не открылась»", (row["итог"], row["почему"]),
         ("не открылась", "HTTP 403"))

print("П4. Заливка: итог пробы у сайта «качает сервер»")
источник("own.tv", by_server=True, manual_only=True, max_days=4)      # как mojtv.hr
до = последний_прогон()
rep = отчёт("601", [строка("ok.tv", "расписание есть")], **{site_move.SECTION: {
    "own.tv": {"когда": "2026-10-20 06:30", "итог": "расписание есть", "адресов": 1, "открылось": 1},
    "srv.tv": {"когда": "2026-10-20 06:31", "итог": "не открылась", "почему": "HTTP 403",
               "адресов": 1, "открылось": 0},
    "ok.tv": {"когда": "2026-10-20 06:32", "итог": "расписание есть", "адресов": 1, "открылось": 1}}})
site_move.after_import(conn, папка("возврат", rep), now=T3)
проверка("own.tv: открылся — пометка «вернуть утром», время пробы по Киеву",
         (настройки("own.tv").get("gh_return"), настройки("own.tv").get("gh_probe_last")),
         ("2026-10-20 09:30", "2026-10-20 09:30"))
проверка("srv.tv: не открылся — только время пробы",
         (настройки("srv.tv").get("gh_return"), настройки("srv.tv").get("gh_probe_last")),
         (None, "2026-10-20 09:31"))
проверка("ok.tv не на сервере — раздел его не трогает", настройки("ok.tv").get("gh_probe_last"), None)
новые = строки_прогонов(до)
проверка("две строки владельцу, без ТРЕВОГИ",
         (len(новые), any("ТРЕВОГА" in s for s in новые)), (2, False))

print("П4. Утро: возврат на GitHub (настоящий set_mode, временный план)")
записать_план(сайт_плана("own.tv", by_server=True, manual_only=True), сайт_плана("srv.tv",
                                                                                  by_server=True))
вызовы = []


def set_mode_запись(c, домен, by_server, by="owner", why="", restore=None):
    вызовы.append((домен, by_server, by))
    return plan_push.set_mode(c, домен, by_server, by=by, why=why, restore=restore)


def в_плане(домен: str) -> dict:
    return next(s for s in json.loads(ПЛАН.read_text(encoding="utf-8"))["sources"]
                if s["domain"] == домен)


said = site_move.return_turn(conn, T3, set_mode_запись, busy="идёт заливка (streams-update.sh)")
проверка("идёт заливка — возврат отложен", (вызовы, "откладываю" in said[0]), ([], True))
до = последний_прогон()
said = site_move.return_turn(conn, T3, set_mode_запись)
проверка("вернули только own.tv (и переведённый владельцем)", вызовы, [("own.tv", False, "auto")])
c = настройки("own.tv")
проверка("в базе: не by_server, пометки перевода сняты",
         (c.get("by_server"), c.get("gh_return"), c.get("moved_by")), (None, None, None))
проверка("как mojtv.hr (режим до перевода неизвестен): «только по кнопке» и "
         "потолок 4 дн. на месте", (c.get("manual_only"), c.get("max_days")), (True, 4))
проверка("в плане own.tv: не by_server, «только по кнопке», потолок 4",
         (в_плане("own.tv")["by_server"], в_плане("own.tv")["manual_only"],
          в_плане("own.tv")["max_days"]), (False, True, 4))
проверка("строка владельцу «ВОЗВРАЩЁН … режим владельца сохранён», без ТРЕВОГИ",
         (any("own.tv" in s and "ВОЗВРАЩЁН" in s and "«только по кнопке», потолок 4 дн." in s
              for s in строки_прогонов(до)),
          any("ТРЕВОГА" in s for s in строки_прогонов(до))), (True, False))

print("П4. Возврат восстанавливает режим ДО перевода (before_move)")
источник("wasfree.tv")                              # обычный сайт, без пометок
источник("wasbtn.tv", manual_only=True, max_days=3)  # «только по кнопке», потолок 3
записать_план(сайт_плана("wasfree.tv"), сайт_плана("wasbtn.tv", manual_only=True, max_days=3))
plan_push.set_mode(conn, "wasfree.tv", True, by="auto")
plan_push.set_mode(conn, "wasbtn.tv", True)          # кнопкой владельца
проверка("перевод запомнил режим до него",
         (настройки("wasfree.tv").get("before_move"), настройки("wasbtn.tv").get("before_move")),
         ({"manual_only": False, "max_days": 0}, {"manual_only": True, "max_days": 3}))
поправить("wasfree.tv", gh_return="2026-10-20 09:30")
поправить("wasbtn.tv", gh_return="2026-10-20 09:30")
вызовы.clear()
site_move.return_turn(conn, T3, set_mode_запись)
проверка("переведённый автоматически обычный сайт — снова в обычных сборах",
         (настройки("wasfree.tv").get("manual_only"), в_плане("wasfree.tv")["manual_only"],
          настройки("wasfree.tv").get("before_move")), (None, False, None))
проверка("переведённый владельцем «только по кнопке» — вернулся «только по кнопке», потолок 3",
         (настройки("wasbtn.tv").get("manual_only"), настройки("wasbtn.tv").get("max_days"),
          в_плане("wasbtn.tv")["manual_only"], в_плане("wasbtn.tv")["by_server"]),
         (True, 3, True, False))
plan_push.set_mode(conn, "wasfree.tv", True, by="auto")
plan_push.set_mode(conn, "wasfree.tv", False)        # кнопка «Вернуть на GitHub»
проверка("кнопка владельца «Вернуть на GitHub» — пометки сняты, как раньше",
         (настройки("wasfree.tv").get("manual_only"), настройки("wasfree.tv").get("before_move")),
         (None, None))
вызовы.clear()
поправить("ok.tv", gh_return="2026-10-20 09:30")
site_move.return_turn(conn, T3, set_mode_запись)
проверка("владелец вернул сам — пометку снимаем молча, set_mode не зовём",
         (настройки("ok.tv").get("gh_return"), len(вызовы)), (None, 0))

print("П4. Утренний ход server_crawl целиком (возврат, потом проверки)")
поправить("srv.tv", gh_return="2026-10-21 09:30")
источник("morning.tv", gh_fail_streak=3, gh_fail_last_slot="350", gh_fail_why="x")
записать_план(сайт_плана("srv.tv", by_server=True), сайт_плана("morning.tv"))
вызовы.clear()
кач = Качалка({"morning.tv": ("расписание есть", "")})
said = server_crawl.утренний_ход(conn, now=datetime(2026, 10, 22, 6, 40, tzinfo=KYIV),
                                 fetch_one=кач, set_mode=set_mode_запись, lock=_свободно, free=lambda: 800)
проверка("сначала возврат srv.tv, потом перевод morning.tv",
         вызовы, [("srv.tv", False, "auto"), ("morning.tv", True, "auto")])
проверка("morning.tv спрошен одним адресом", кач.спросили, ["morning.tv"])
вызовы.clear()
кач = Качалка({})
источник("later.tv", gh_fail_streak=3, gh_fail_last_slot="350")
said = server_crawl.утренний_ход(conn, now=datetime(2026, 10, 23, 6, 40, tzinfo=KYIV),
                                 fetch_one=кач, set_mode=set_mode_запись, lock=_занято, free=lambda: 800)
проверка("замок заливки занят — ни переводов, ни скачиваний",
         (вызовы, кач.спросили, any("идёт заливка" in s for s in said)), ([], [], True))


# ── П5. что видит владелец ──────────────────────────────────────────────────

print("П5. Пометки и страницы админки")
проверка("переведён автоматически",
         site_move.mark({"by_server": True, "moved_by": "auto", "moved_at": "2026-10-14 06:40"}),
         "переведён на сервер автоматически 14.10")
проверка("перевёл владелец (без даты — mojtv.hr)", site_move.mark({"by_server": True}),
         "на сервер перевёл владелец")
проверка("проба не открылась — дата пробы",
         site_move.mark({"by_server": True, "moved_by": "auto", "moved_at": "2026-10-14 06:40",
                         "gh_probe_last": "2026-10-21 09:30"}),
         "переведён на сервер автоматически 14.10; проба GitHub 21.10 не открылась")
проверка("серия срывов", site_move.mark({"gh_fail_streak": 2}), "не дался GitHub 2 сбора подряд")
проверка("кандидат", "кандидат на перевод" in site_move.mark({"gh_fail_streak": 3}))
обзор = {m["domain"]: m for m in site_move.overview(conn)}
проверка("«Сломанные»: ban.tv на сервере (авто), e2e.tv со срывом",
         ("автоматически" in обзор["ban.tv"]["mark"], "1 сбор подряд" in обзор["e2e.tv"]["mark"]),
         (True, True))
источник("hand.tv", gh_fail_streak=2, gh_fail_last_slot="380", gh_fail_why="x")


def source_mode(*аргументы) -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "source_mode.py"), *аргументы],
                   capture_output=True, text=True, encoding="utf-8", env=os.environ)


source_mode("hand.tv", "--by-server", "--apply")
c = настройки("hand.tv")
проверка("source_mode.py --by-server: перевёл владелец, счёт срывов снят",
         (c.get("by_server"), c.get("moved_by"), c.get("gh_fail_streak")), (True, "owner", None))
source_mode("hand.tv", "--auto", "--apply")
c = настройки("hand.tv")
проверка("source_mode.py --auto: пометки перевода сняты",
         (c.get("by_server"), c.get("moved_by"), c.get("moved_at")), (None, None, None))
from app import web  # noqa: E402

app = web.create_app()
владелец = app.test_client()
владелец.post("/login", data={"password": "adm-test-1"})
страница = re.sub(r"<[^>]+>", " ", владелец.get("/broken").get_data(as_text=True))
проверка("страница «Сломанные» показывает раздел и пометку",
         ("На сервере и срывы на GitHub" in страница,
          "переведён на сервер автоматически" in страница), (True, True))
conn.execute("INSERT INTO runs (finished_at, window_days, log) VALUES (?, 6, ?)",
             ("2026-10-14 08:00", json.dumps({"режим": "полный обход, окно 6 суток", "кто": "",
                                              "сбои": {"ban.tv": 2, "e2e.tv": 1}},
                                             ensure_ascii=False)))
conn.commit()
номер = последний_прогон()
страница = re.sub(r"<[^>]+>", " ", владелец.get(f"/runs/{номер}/failed").get_data(as_text=True))
проверка("страница сбоев прогона: «переведён на сервер автоматически» у ban.tv",
         "переведён на сервер автоматически" in страница)
проверка("…и «не дался GitHub 1 сбор подряд» у e2e.tv", "не дался GitHub 1 сбор подряд" in страница)


# ── П6. никакого полного сбора с сервера ────────────────────────────────────

print("П6. Только один адрес и только сайты «качает сервер»")
кач = Качалка({})
источник("p6.tv", gh_fail_streak=3, gh_fail_last_slot="360")
записать_план(сайт_плана("p6.tv"))
site_move.server_turn(conn, datetime(2026, 10, 25, 6, 40, tzinfo=KYIV), кач,
                      server_crawl.план_по_доменам(), plan_push.set_mode, free=lambda: 800)
проверка("проверка кандидата — один вызов «один адрес»", кач.спросили, ["p6.tv"])
команды = []
server_crawl.шаг = lambda команда, тег: команды.append(команда) or False
server_crawl.проверить_адрес = Качалка({})
server_crawl.замок_заливки = _свободно
sys.argv = ["server_crawl.py", "--force"]
server_crawl.свободно_мб = lambda: 350
до = последний_прогон()
server_crawl.main()
проверка("обычный ход: свободно 350 МБ — ни один сайт не качаем, без падения",
         [к for к in команды if "crawl_fetch.py" in " ".join(к)], [])
проверка("…строка «мало памяти, сайт … откладываю» на каждый сайт",
         sum("мало памяти" in s and "откладываю" in s for s in строки_прогонов(до)),
         len(dict(server_crawl.сайты())))
проверка("…в память сбора не записаны — следующий запуск возьмёт их",
         server_crawl.память(), {})
команды.clear()
server_crawl.свободно_мб = lambda: 800
server_crawl.main()
качали = [к for к in команды if "crawl_fetch.py" in " ".join(к)]
проверка("ежедневный ход качает только by_server, каждый — с --only <домен>",
         bool(качали) and all("--only" in к and "--full" in к for к in качали))
домены = sorted(к[к.index("--only") + 1] for к in качали)
by_server = sorted(r["domain"] for r in conn.execute(
    "SELECT domain, selector_config FROM sources WHERE enabled = 1 AND role = 'schedule'")
    if json.loads(r["selector_config"] or "{}").get("by_server"))
проверка("…ровно сайты «качает сервер»", домены, by_server)
проверка("…переведённый автоматически — на 6 дней",
         any(к[к.index("--only") + 1] == "ban.tv" and к[к.index("--days") + 1] == "6" for к in качали))


# ── П7. строки by_server не выглядят упавшими ───────────────────────────────

print("П7. Проба возврата — не «строки»: дозабор, счёт сбоев, порог не видят")
rep = отчёт("701", [строка("ok.tv", "расписание есть"), строка("net.tv", "не открылась", NET)],
            **{site_move.SECTION: {"srv.tv": {"когда": "2026-10-27 06:00", "итог": "не открылась",
                                              "почему": NET, "адресов": 1, "открылось": 0}}})
выбор = redo.pick(rep)
проверка("дозабор видит только упавшую строку net.tv",
         [r["domain"] for r in выбор.rows], ["net.tv"])
было = conn.execute("SELECT fail_count FROM sources WHERE domain='srv.tv'").fetchone()[0]
путь = папка("p7", rep)
store.log_run(conn, путь, store.SaveStats())
лог = json.loads(conn.execute("SELECT log FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0])
проверка("log_run: у srv.tv счётчик сбоев не вырос",
         conn.execute("SELECT fail_count FROM sources WHERE domain='srv.tv'").fetchone()[0], было)
проверка("log_run: srv.tv нет в «сбоях» прогона", "srv.tv" in (лог.get("сбои") or {}), False)
без = dict(rep)
без.pop(site_move.SECTION)
проверка("порог провала (assess) не зависит от раздела",
         crawl_fetch.assess(rep), crawl_fetch.assess(без))
site_move.after_import(conn, путь, now=T3)
проверка("счёт перевода у srv.tv не появился", настройки("srv.tv").get("gh_fail_streak"), None)

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
conn.close()
sys.exit(1 if красных else 0)

# -*- coding: utf-8 -*-
r"""Срок входа в админку — 24 часа (книга 111, аудит 13.11.2026).

Повод: аудит безопасности 13.11 — вход не имел срока: украденная кука входа
работала бы, пока не сменён ключ подписи. Слово владельца 13.11: «сделай 24
часа».

Правила (`app/web.py`, у `SESSION_HOURS`) и что здесь сторожится:

1. вход владельца и друга живёт 24 часа с минуты ввода пароля;
2. срок не продлевается заходами на сайт;
3. вход без отметки времени (сделан до правки) считается истёкшим;
4. истёкший вход стирается на любом адресе, и на витрине тоже.

В сеть не ходит, база — пустая временная, часы подменены:

    python scripts/test_srok_vhoda.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="srok-vhoda-"))
(TMP / "visits").mkdir()
os.environ.update(STREAMS_DB=str(TMP / "test.db"),
                  STREAMS_ADMIN_PASSWORD="adm-test-1",
                  STREAMS_FRIEND_PASSWORD="fr-test-1", SECRET_KEY="k" * 32,
                  STREAMS_VISITS_DIR=str(TMP / "visits"))
os.environ.pop("STREAMS_LOCAL", None)

from app import db, visits, web  # noqa: E402

visits.write = lambda *a, **k: None          # журнал посещений в тесте не пишем
db.init_db()
app = web.create_app()

passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


# ── часы теста: настоящие часы + сдвиг в секундах ────────────────────────────
НАСТОЯЩИЕ = web.time.time
СДВИГ = [0.0]
web.time.time = lambda: НАСТОЯЩИЕ() + СДВИГ[0]
ЧАС = 3600


def через(часов: float) -> None:
    СДВИГ[0] = часов * ЧАС


def вошёл(клиент) -> bool:
    """Пускает ли админка: главная страница админки отвечает 200."""
    return клиент.get("/").status_code == 200


def на_вход(клиент) -> bool:
    r = клиент.get("/")
    return r.status_code == 302 and "/login" in r.headers.get("Location", "")


print("1. Чистая функция срока (правила 1–3)")
T = 1_800_000_000.0
check("только что вошёл — не истёк", not web.session_expired(T, T))
check("23 ч 59 мин — не истёк", not web.session_expired(T, T + 24 * ЧАС - 60))
check("24 ч 1 мин — истёк", web.session_expired(T, T + 24 * ЧАС + 60))
check("отметки нет — истёк (вход до правки)", web.session_expired(None, T))
check("отметка не число — истёк", web.session_expired("вчера", T))
check("отметка из будущего — истёк", web.session_expired(T + 600, T))
check("срок — ровно 24 часа", web.SESSION_HOURS == 24
      and web.SESSION_SECONDS == 86400)

print("2. Владелец: вход живёт 24 часа и не продлевается")
через(0)
c = app.test_client()
r = c.post("/login", data={"password": "adm-test-1"})
check("вход по паролю принят", r.status_code == 302 and вошёл(c), r.status_code)
with c.session_transaction() as s:
    check("в сессии записано время входа", isinstance(s.get("at"), int), dict(s))
    check("сессия помечена срочной (кука с датой конца)", s.permanent is True)
через(12)
check("через 12 часов — пускает", вошёл(c))
через(23.9)
check("через 23 ч 54 мин — пускает (заход в 12 часов срок не продлил бы)",
      вошёл(c))
через(24.1)
check("через 24 ч 6 мин — на страницу входа, хотя заходил час назад",
      на_вход(c))
with c.session_transaction() as s:
    check("истёкший вход стёрт из сессии", not s.get("admin"), dict(s))
r = c.post("/login", data={"password": "adm-test-1"})
check("повторный вход паролем — снова пускает", вошёл(c))

print("3. Вход без отметки времени (сделан до правки) — истёк")
через(0)
c = app.test_client()
with c.session_transaction() as s:
    s["admin"] = True
check("кука «админ» без времени входа — на страницу входа", на_вход(c))

print("4. Друг: тот же срок, вход стирается и на витрине")
через(0)
c = app.test_client()
r = c.post("/login", data={"password": "fr-test-1"})
with c.session_transaction() as s:
    check("друг вошёл, время входа записано",
          s.get("friend") is True and isinstance(s.get("at"), int), dict(s))
через(24.1)
r = c.get("/schedule")
check("витрина открыта и после срока", r.status_code == 200, r.status_code)
with c.session_transaction() as s:
    check("через сутки вход друга стёрт (кнопки сбора закрыты)",
          not s.get("friend"), dict(s))

print("5. Гость и срок куки")
через(0)
c = app.test_client()
check("гостя без входа витрина пускает", c.get("/schedule").status_code == 200)
check("гостя админка не пускает", на_вход(c))
check("кука в браузере живёт не дольше 24 часов",
      app.config["PERMANENT_SESSION_LIFETIME"].total_seconds() == 86400)

web.time.time = НАСТОЯЩИЕ
print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, "
      f"красных: {len(failed)}")
sys.exit(1 if failed else 0)

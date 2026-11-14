# -*- coding: utf-8 -*-
r"""Красная строка витрины: прямой эфир, вид спорта которого эталон не
подтвердил (книга 113, слово владельца 13.11.2026).

Правила — в шапке `app/unconfirmed.py` (К1–К5). Здесь на каждое — проверка:

К1. в красные идёт только честная пометка эфира от сайта;
К2. красную строку видит только вошедший владелец: гость и API — нет;
К3. одна пара в одно время у нескольких каналов — одна строка;
К4. полная заливка обновляет список: узнанная эталоном строка уходит,
    строка чужого дня и чужого сайта остаётся, прошедшая уходит;
К5. удалённую владельцем строку следующий сбор не возвращает; кнопка —
    только вошедшему владельцу.

В сеть не ходит, база — пустая временная:

    python scripts/test_unconfirmed.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="unconfirmed-"))
(TMP / "visits").mkdir()
os.environ.update(STREAMS_DB=str(TMP / "test.db"),
                  STREAMS_ADMIN_PASSWORD="adm-test-1",
                  STREAMS_FRIEND_PASSWORD="fr-test-1", SECRET_KEY="k" * 32,
                  STREAMS_VISITS_DIR=str(TMP / "visits"))
os.environ.pop("STREAMS_LOCAL", None)

from app import db, pipeline, store, unconfirmed, visits, web  # noqa: E402
from app.parsers import Program                                # noqa: E402
import parse_live                                              # noqa: E402

visits.write = lambda *a, **k: None
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


# даты — от сегодняшнего дня, чтобы тест не протух
СЕЙЧАС = datetime.now().replace(second=0, microsecond=0)
ЗАВТРА = (СЕЙЧАС + timedelta(days=1)).replace(hour=19, minute=0)
ПОСЛЕЗАВТРА = ЗАВТРА + timedelta(days=1)


def T(когда: datetime) -> str:
    return когда.strftime("%Y-%m-%dT%H:%M")


def строка(дом, гости, когда, канал="Sport 1", домен="tv.example",
           лига="Premier League"):
    return {"домен": домен, "канал": канал, "home": дом, "away": гости,
            "league": лига, "start_kyiv": T(когда), "raw_title": "",
            "url": f"https://{домен}/guide", "виды": ["B", "F"]}


print("К1. В красные — только честная пометка эфира от сайта")


class Строка:
    def __init__(self, метка, extra=None):
        self.live_marker = метка
        self.program = Program(channel_raw="К", title="т", start=None,
                               extra=extra or {})


check("сайт пометил эфир — честная",
      parse_live.honest_live("tv.example", Строка("live")))
check("пометки нет — не честная",
      not parse_live.honest_live("tv.example", Строка("")))
check("эфир дал эталон, а не сайт — не честная",
      not parse_live.honest_live("tv.example",
                                 Строка(pipeline.REFERENCE_MARKER)))
check("эфир угадан программой (live_guess) — не честная",
      not parse_live.honest_live("tv.example",
                                 Строка("live", {"live_guess": True})))
угадайка = sorted(parse_live.REPEAT_GUESS_DOMAINS)[0]
check(f"сайт без своей пометки эфира ({угадайка}) — не честная",
      not parse_live.honest_live(угадайка, Строка("live")))
check("тот же сайт, но строку пометил сам (site_flag) — честная",
      parse_live.honest_live(угадайка, Строка("live", {"site_flag": "live"})))

from zoneinfo import ZoneInfo  # noqa: E402

КИЕВ = ZoneInfo("Europe/Kyiv")


class СоВременем:
    def __init__(self, когда):
        self.start_kyiv = когда


сейчас = datetime.now(КИЕВ)
check("игра завтра — не прошедшая",
      not parse_live.long_past(СоВременем(сейчас + timedelta(days=1))))
check("игра началась час назад — ещё показываем",
      not parse_live.long_past(СоВременем(сейчас - timedelta(hours=1))))
check("игра месячной давности (tring.al, 17.10) — красной не идёт",
      parse_live.long_past(СоВременем(сейчас - timedelta(days=27))))
check("строка без времени — красной не идёт",
      parse_live.long_past(СоВременем(None)))

print("Книга 117. Прошедшие строки отбрасываются сразу после разбора страницы")


def передача(когда):
    return Program(channel_raw="К", title="т", start=когда)


день = сейчас.date()
полдень = сейчас.replace(hour=12, minute=0, second=0, microsecond=0)
строки = [передача(полдень - timedelta(days=200)),      # 1 мая у tring.al
          передача(полдень - timedelta(days=2)),        # позавчера
          передача(полдень - timedelta(days=1)),        # вчера
          передача(полдень),                            # сегодня
          передача(полдень + timedelta(days=3)),        # будущее
          передача(None)]                               # без времени
осталось, отброшено = parse_live.drop_past(строки, день)
check("правило 1: полугодовой давности и позавчерашняя — отброшены",
      отброшено == 2 and строки[0] not in осталось and строки[1] not in осталось)
check("правило 2: вчерашняя, сегодняшняя и будущая — остаются",
      all(x in осталось for x in строки[2:5]))
check("правило 3: строка без времени остаётся", строки[5] in осталось)
check("пустая страница — ничего не отброшено",
      parse_live.drop_past([], день) == ([], 0))

print("К3. Одна пара в одно время у нескольких каналов — одна строка")
группа = unconfirmed.group([
    строка("Arsenal", "Hull City", ЗАВТРА, канал="Sport 1"),
    строка("ARSENAL", "hull  city", ЗАВТРА, канал="Sport 2", домен="b.example"),
    строка("Arsenal", "Hull City", ЗАВТРА, канал="Sport 1"),      # дубль
    строка("Arsenal", "Hull City", ПОСЛЕЗАВТРА),                  # другой день
    строка("", "Hull City", ЗАВТРА),                              # без пары
    строка("Roma", "Lazio", ЗАВТРА) | {"start_kyiv": "когда-то"},  # без времени
])
check("строк две: одна пара завтра и она же послезавтра", len(группа) == 2,
      группа)
check("у первой — оба канала, дубль не задвоился",
      [c["name"] for c in группа[0]["channels"]] == ["Sport 1", "Sport 2"],
      группа[0]["channels"])
check("ключ один для разного регистра и пробелов",
      unconfirmed.key(строка("ARSENAL", "hull  city", ЗАВТРА))
      == unconfirmed.key(строка("Arsenal", "Hull City", ЗАВТРА)))

print("К4. Полная заливка обновляет список")
conn = db.connect()
D1, D2 = T(ЗАВТРА)[:10], T(ПОСЛЕЗАВТРА)[:10]


def сбор(красные, дни=(D1, D2), сайты=("tv.example",)):
    return {"без_эталона": красные,
            "games": [{"start_kyiv": f"{d}T12:00"} for d in дни],
            "разобрано": {s: 5 for s in сайты}}


n = unconfirmed.after_import(conn, сбор([
    строка("Arsenal", "Hull City", ЗАВТРА),
    строка("Roma", "Lazio", ПОСЛЕЗАВТРА)]), СЕЙЧАС)
check("а) две красные строки сбора — в списке", n == 2, n)
n = unconfirmed.after_import(conn, сбор([
    строка("Roma", "Lazio", ПОСЛЕЗАВТРА)]), СЕЙЧАС)
пары = [r["home"] for r in unconfirmed.shown(conn, СЕЙЧАС)]
check("б) эталон узнал Arsenal (сбор его красным не назвал) — ушла",
      пары == ["Roma"], пары)
n = unconfirmed.after_import(conn, сбор([], дни=(D1,)), СЕЙЧАС)
check("в) скан одного дня строку другого дня не трогает", n == 1, n)
n = unconfirmed.after_import(
    conn, сбор([], сайты=("drugoy.example",)), СЕЙЧАС)
check("в) сбор без этого сайта (сайт не открылся) строку не трогает",
      n == 1, n)
n = unconfirmed.after_import(conn, {"games": []}, СЕЙЧАС)
check("старый файл сбора без ключа список не трогает", n == 1, n)
n = unconfirmed.after_import(conn, сбор([], дни=(D1,)),
                             ПОСЛЕЗАВТРА + timedelta(hours=4))
check("г) через 4 часа после начала строка ушла", n == 0, n)
check("строки сбора «без_эталона» не считаются пропавшими с сайта",
      ("tv.example", T(ЗАВТРА).replace("T", " "))
      in store.withheld_rows(сбор([строка("A", "B", ЗАВТРА)])))

print("К2 и К5. Витрина: видит и удаляет только вошедший владелец")
unconfirmed.after_import(conn, сбор([
    строка("Arsenal", "Hull City", ЗАВТРА),
    строка("Roma", "Lazio", ПОСЛЕЗАВТРА)]), СЕЙЧАС)
КЛЮЧ = unconfirmed.key(строка("Arsenal", "Hull City", ЗАВТРА))

гость = app.test_client()
страница = гость.get("/schedule").get_data(as_text=True)
check("К2: гость красную строку не видит",
      "Hull City" not in страница and "data-key=" not in страница)
r = гость.post("/unconfirmed/remove", data={"key": КЛЮЧ})
check("К5: гость удалить не может (отправлен на вход)",
      r.status_code in (302, 400, 403), r.status_code)

друг = app.test_client()
друг.post("/login", data={"password": "fr-test-1"})
check("К2: друг красную строку не видит",
      "Hull City" not in друг.get("/schedule").get_data(as_text=True))
with друг.session_transaction() as s:
    s["csrf_token"] = "t" * 16
r = друг.post("/unconfirmed/remove", data={"key": КЛЮЧ, "csrf_token": "t" * 16})
check("К5: друг удалить не может (отправлен на вход)",
      r.status_code in (302, 403), r.status_code)
check("после попыток гостя и друга строка на месте",
      any(x["unconfirmed"] == КЛЮЧ for x in unconfirmed.shown(conn, СЕЙЧАС)))

админ = app.test_client()
админ.post("/login", data={"password": "adm-test-1"})
страница = админ.get("/schedule").get_data(as_text=True)
check("К2: владелец видит обе красные строки",
      "Hull City" in страница and "Lazio" in страница)
check("строка красная, с подсказкой и кнопкой удаления",
      'class="game unconfirmed"' in страница
      and "вид спорта не подтверждён" in страница
      and f'data-key="{КЛЮЧ}"' in страница)
with админ.session_transaction() as s:
    токен = s.get("csrf_token", "")
r = админ.post("/unconfirmed/remove", data={"key": КЛЮЧ})
check("К5: без защитного токена формы — отказ", r.status_code == 400,
      r.status_code)
r = админ.post("/unconfirmed/remove", data={"key": КЛЮЧ, "csrf_token": токен})
check("К5: владелец удалил строку", r.status_code == 200
      and r.get_json().get("known") is True, r.get_data(as_text=True)[:200])
страница = админ.get("/schedule").get_data(as_text=True)
check("удалённой строки на витрине нет, вторая на месте",
      "Hull City" not in страница and "Lazio" in страница)
unconfirmed.after_import(conn, сбор([
    строка("Arsenal", "Hull City", ЗАВТРА),
    строка("Roma", "Lazio", ПОСЛЕЗАВТРА)]), СЕЙЧАС)
страница = админ.get("/schedule").get_data(as_text=True)
check("К5: следующий сбор удалённую строку не вернул",
      "Hull City" not in страница and "Lazio" in страница)

print("К2. API красные строки не отдаёт")
check("в играх базы красных строк нет (их читает API)",
      all("unconfirmed" not in g for g in store.schedule(conn)))
unconfirmed.after_import(conn, сбор([]), ПОСЛЕЗАВТРА + timedelta(days=2))
check("ключи удалённых прошедших игр вычищены",
      unconfirmed._load(conn, unconfirmed.REMOVED_KEY) == [])
conn.close()

print(f"\nпройдено: {passed}, провалено: {len(failed)}")
for name in failed:
    print("  ✖", name)
sys.exit(1 if failed else 0)

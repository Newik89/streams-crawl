# -*- coding: utf-8 -*-
r"""Проверки страницы «Названия» админки (владелец 06.10.2026: «не понятно,
что кнопки делают… нужно её проще и понятнее сделать»).

Страница переделана: у каждого вопроса видно, что увидела программа, что
она предлагает и что сделает каждая кнопка. Ответы пишутся тем же путём,
что и раньше, — здесь это и проверяется: вход, CSRF, каждая кнопка
(команда «Да, это …» и поле, «Это не команда», «Отложить», «Вернуть», вид
спорта, «Не матч»), строки «Запомнено: …», слабая догадка не подставляется
в поле, вкладки «Отсеянные» и «Ответила программа».

В сеть не ходит. База — пустая, во временной папке, вопросы заводятся
здесь же. Запуск:

    python scripts/test_names_page.py

Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="names-page-test-"))
(TMP / "visits").mkdir()
os.environ.update(STREAMS_DB=str(TMP / "test.db"),
                  STREAMS_ADMIN_PASSWORD="adm-test-1", SECRET_KEY="k" * 32,
                  STREAMS_VISITS_DIR=str(TMP / "visits"))
os.environ.pop("STREAMS_LOCAL", None)

from app import db, names_page, visits, web  # noqa: E402

visits.write = lambda *a, **k: None          # журнал в тесте не пишем
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


def sql(query, args=()):
    conn = db.connect()
    try:
        cur = conn.execute(query, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def one(query, args=()):
    conn = db.connect()
    try:
        return conn.execute(query, args).fetchone()
    finally:
        conn.close()


def token(page):
    m = re.search(r'name="csrf_token" value="([0-9a-f]+)"', page)
    return m.group(1) if m else ""


def text(page):
    """Текст страницы без тегов — проверять надписи."""
    plain = html.unescape(re.sub(r"<[^>]+>", " ", page))
    plain = re.sub(r"[ \t]+", " ", plain)
    return plain.replace("« ", "«").replace(" »", "»")


# ── данные: игра с каналом, вопросы всех видов ──────────────────────────────
завтра = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d 21:00")
src = sql("INSERT INTO sources (domain, name, base_url, country) VALUES "
          "('tvarenasport.com', 'Arena', 'https://tvarenasport.com/', 'RS')")
ch = sql("INSERT INTO channels (canonical_name, slug, country) VALUES "
         "('Arena Sport 1', 'arena-sport-1-rs', 'RS')")
ev = sql("INSERT INTO events (sport, team_home_auto, team_away_auto, "
         "league_auto, start_utc, start_kyiv) VALUES "
         "('B', 'Igokea', 'Bilbao', 'Лига Чемпионов', ?, ?)", (завтра, завтра))
sql("INSERT INTO event_channels (event_id, channel_id, source_id, source_url) "
    "VALUES (?, ?, ?, 'https://tvarenasport.com/tv-scheme')", (ev, ch, src))
BILBAO = sql("INSERT INTO moderation (kind, raw_value, suggestion) VALUES "
             "('team', 'Bilbao', 'Alba Berlin')")
BODRUM = sql("INSERT INTO moderation (kind, raw_value, suggestion) VALUES "
             "('team', 'Bodrum FK', 'Bodrumspor')")
IGOKEA = sql("INSERT INTO moderation (kind, raw_value, suggestion) VALUES "
             "('team', 'Igokea', 'Slavia Prague ERA NBK')")
LEAGUE = sql("INSERT INTO moderation (kind, raw_value, suggestion) VALUES "
             "('league', 'Лига Чемпионов', 'EUROPE: Champions League')")
SPORT_Q = sql("INSERT INTO moderation (kind, raw_value, suggestion) VALUES "
              "('sport', 'Besiktas - Erzurumspor | Prima Sport 5 (primaplay.ro)',"
              " '2026-10-06 15:00 | Besiktas – Erzurumspor')")
SPORT_Q2 = sql("INSERT INTO moderation (kind, raw_value, suggestion) VALUES "
               "('sport', 'Serbia Upside Down - Into the Unknown | Extreme "
               "Sports (tv2.no)', '2026-10-10 20:30 | Serbia Upside Down - "
               "Into the Unknown')")
AUTO = sql("INSERT INTO moderation (kind, raw_value, suggestion, status, "
           "answered_by) VALUES ('sport', 'Forma-1 - Sprintfutam | M4 Sport+ "
           "(port.hu)', '2026-10-10 22:15 | Forma-1', 'skipped', "
           "'ответила программа: правило 4 — чужой вид спорта: «Forma-1»')")

# ── 1. вход и защита ─────────────────────────────────────────────────────────
print("1. вход и защита")
guest = app.test_client()
r = guest.get("/names?kind=team")
check("без входа — на страницу входа", r.status_code == 302
      and "/login" in r.headers["Location"], r.status_code)
r = guest.post(f"/names/{BILBAO}", data={"action": "later"})
check("POST без входа — на вход, ничего не меняется",
      r.status_code == 302 and one("SELECT status FROM moderation WHERE id = ?",
                                   (BILBAO,))[0] == "open")
a = app.test_client()
r = a.post("/login", data={"password": "adm-test-1"})
check("владелец входит", r.status_code == 302)
r = a.post(f"/names/{BILBAO}", data={"action": "later", "csrf_token": "wrong"})
check("чужой CSRF — 400", r.status_code == 400, r.status_code)

# ── 2. вкладка «Команды» ─────────────────────────────────────────────────────
print("2. вкладка «Команды»")
r = a.get("/names?kind=team")
page = r.get_data(as_text=True)
plain = text(page)
tok = token(page)
check("страница открывается", r.status_code == 200, r.status_code)
check("над вкладкой — строка, что это за вопросы",
      names_page.tab_note("team") in plain)
check("у вопроса видно, что написано на сайте",
      "На сайте написано: «Bilbao»" in plain)
check("видно, где увидели: игра, время, канал, сайт",
      "Igokea — Bilbao" in plain and "Arena Sport 1" in plain
      and "tvarenasport.com ↗" in plain)
check("ссылка на игру на витрине", f'href="/schedule#g{ev}"' in page)
check("кнопки названы по-человечески",
      all(x in plain for x in ("Это не команда", "Отложить", "Сохранить")))
check("старых непонятных надписей нет",
      not any(x in plain for x in ("Закрепить", "Не название", "Не знаю")))
блок_bilbao = page[page.index(f'id="item-{BILBAO}"'):page.index(f'id="item-{BODRUM}"')] \
    if page.index(f'id="item-{BILBAO}"') < page.index(f'id="item-{BODRUM}"') else \
    page[page.index(f'id="item-{BILBAO}"'):]
check("слабая догадка (Bilbao → Alba Berlin, 60) не стоит в поле",
      'value="Alba Berlin"' not in блок_bilbao.split("Подставить")[-1]
      and "совпадение слабое" in text(блок_bilbao)
      and "Да, это «Alba Berlin»" not in text(блок_bilbao), блок_bilbao[:400])
check("сильная догадка (Bodrum FK → Bodrumspor, 75) — кнопкой «Да, это …»",
      "Да, это «Bodrumspor»" in plain)
check("у кнопок есть подсказки при наведении",
      page.count('title="Не знаю сейчас.') >= 3)

# ── 3. кнопки пишут то же, что раньше ────────────────────────────────────────
print("3. кнопки команд")
r = a.post(f"/names/{BODRUM}", data={"canonical": "Bodrumspor",
                                     "csrf_token": tok},
           headers={"Referer": "/names?kind=team"}, follow_redirects=True)
done = one("SELECT status, suggestion, answered_by FROM moderation WHERE id = ?",
           (BODRUM,))
alias = one("SELECT t.canonical_name FROM team_aliases a JOIN teams t ON "
            "t.id = a.team_id WHERE a.alias = 'Bodrum FK'")
check("«Да, это …» — имя закреплено, вопрос закрыт владельцем",
      tuple(done) == ("done", "Bodrumspor", None) and alias
      and alias[0] == "Bodrumspor", (tuple(done), alias))
check("после ответа — «Запомнено: …»",
      "Запомнено: «Bodrum FK» — это команда «Bodrumspor»"
      in text(r.get_data(as_text=True)))
r = a.post(f"/names/{BILBAO}", data={"canonical": "", "csrf_token": tok},
           follow_redirects=True)
check("пустое поле — понятная ошибка, вопрос открыт",
      "Впишите название" in text(r.get_data(as_text=True))
      and one("SELECT status FROM moderation WHERE id = ?", (BILBAO,))[0]
      == "open")
r = a.post(f"/names/{BILBAO}", data={"canonical": "Bilbao Basket",
                                     "csrf_token": tok}, follow_redirects=True)
check("поле + «Сохранить» — своё имя закреплено",
      one("SELECT status, suggestion FROM moderation WHERE id = ?",
          (BILBAO,))[:] == ("done", "Bilbao Basket"))
r = a.post(f"/names/{IGOKEA}", data={"action": "later", "csrf_token": tok},
           follow_redirects=True)
check("«Отложить» — во вкладку «Отложенные»",
      one("SELECT status FROM moderation WHERE id = ?", (IGOKEA,))[0] == "later"
      and "ждёт во вкладке «Отложенные»" in text(r.get_data(as_text=True)))
page = a.get("/names?later=1").get_data(as_text=True)
check("в «Отложенных» есть «Вернуть в список»",
      "Igokea" in text(page) and "Вернуть в список" in text(page))
r = a.post(f"/names/{IGOKEA}", data={"action": "reopen", "csrf_token": tok},
           follow_redirects=True)
check("«Вернуть в список» — снова открыт",
      one("SELECT status FROM moderation WHERE id = ?", (IGOKEA,))[0] == "open")
r = a.post(f"/names/{IGOKEA}", data={"action": "skip", "csrf_token": tok},
           follow_redirects=True)
check("«Это не команда» — в «Отсеянные», «больше не спросим»",
      one("SELECT status FROM moderation WHERE id = ?", (IGOKEA,))[0]
      == "skipped" and "не команда" in text(r.get_data(as_text=True)))
page = a.get("/names?rejected=1&kind=team").get_data(as_text=True)
check("«Отсеянные» по командам: Igokea и кнопка «Вернуть в вопросы»",
      "Igokea" in text(page) and "Вернуть в вопросы" in text(page))
r = a.post(f"/names/{LEAGUE}", data={"canonical": "EUROPE: Champions League",
                                     "csrf_token": tok}, follow_redirects=True)
check("лига: ответ закреплён",
      one("SELECT status FROM moderation WHERE id = ?", (LEAGUE,))[0] == "done"
      and "Запомнено: турнир" in text(r.get_data(as_text=True)))

# ── 4. вкладка «Вид спорта» ──────────────────────────────────────────────────
print("4. вкладка «Вид спорта»")
page = a.get("/names?kind=sport").get_data(as_text=True)
plain = text(page)
check("заголовок вопроса и чем засомневалась",
      "Какой это вид спорта?" in plain and "Почему спрашиваю:" in plain)
check("видно канал, сайт и время",
      "Prima Sport 5" in plain and "primaplay.ro" in plain
      and "06.10 15:00 (по Киеву)" in plain)
check("кнопки: Футбол / Баскетбол / Теннис / Не матч / Отложить",
      all(x in plain for x in ("Футбол", "Баскетбол", "Теннис", "Не матч",
                               "Отложить")))
check("на витрине игры нет — так и сказано",
      "На витрине этой игры пока нет" in plain)
r = a.post(f"/names/{SPORT_Q}", data={"canonical": "F", "csrf_token": tok},
           follow_redirects=True)
hint = one("SELECT sport, match_day FROM sport_hints WHERE pair = "
           "'Besiktas - Erzurumspor'")
check("«Футбол» — подсказка с днём матча, вопрос закрыт",
      hint and tuple(hint) == ("F", "2026-10-06")
      and one("SELECT status FROM moderation WHERE id = ?", (SPORT_Q,))[0]
      == "done", hint and tuple(hint))
check("после ответа — «Запомнено: … — футбол»",
      "Запомнено: «Besiktas - Erzurumspor» — футбол"
      in text(r.get_data(as_text=True)))
r = a.post(f"/names/{SPORT_Q2}", data={"action": "skip", "csrf_token": tok},
           follow_redirects=True)
check("«Не матч» — в «Отсеянные»",
      one("SELECT status FROM moderation WHERE id = ?", (SPORT_Q2,))[0]
      == "skipped" and "не матч" in text(r.get_data(as_text=True)))
page = a.get("/names?auto=1").get_data(as_text=True)
check("«Ответила программа»: видно что и почему, можно вернуть",
      "Forma-1" in text(page) and "Ответила программа: правило 4" in text(page)
      and "Вернуть в вопросы" in text(page))
page = a.get("/names?rejected=1&kind=sport").get_data(as_text=True)
check("«Отсеянные» по виду спорта: причина видна",
      "Ответила программа: правило 4" in text(page)
      and "Serbia Upside Down" in text(page))
page = a.get("/names").get_data(as_text=True)
check("вкладка «Все» открывается", "Названия — вопросы программы" in text(page))
r = a.get(f"/names?focus={SPORT_Q2}")
check("переход с витрины (?focus=) не ломает страницу", r.status_code == 200)

print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, "
      f"красных: {len(failed)}")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)

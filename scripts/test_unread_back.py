# -*- coding: utf-8 -*-
r"""Красная точка «вернуть в непрочитанные» под значком спорта.

Слово владельца 24.10.2026: «чтоб я мог метку игры не прочитанной вернуть
назад, под мячиком… окошко, в которое я клацну, и игра будет светиться как
не обработанная» (картинка — красная точка под значком спорта).

Правила (app/web.py `game_unseen`, шаблон `schedule.html`):
 1. Точка есть только у владельца; гостю её не видно, запрос гостя — отказ.
 2. Точка видна у прочитанной игры, у зелёной (непрочитанной) спрятана CSS.
 3. Клик по точке: игра снова непрочитанная (events.seen = 0) — витрина
    рисует строку зелёной; клик по строке гасит обратно (seen = 1).
 4. «new» у каналов точка не трогает.
 5. Без токена формы — отказ, база не меняется; игры нет — 404.
 6. Клик по строке, попавший в точку, строку не гасит (скрипт страницы).

Запуск: python scripts/test_unread_back.py — в сеть не ходит, база временная.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="unread-back-test-"))
(TMP / "visits").mkdir()
os.environ.update(STREAMS_DB=str(TMP / "test.db"), STREAMS_ADMIN_PASSWORD="adm-test-1",
                  SECRET_KEY="k" * 32, STREAMS_VISITS_DIR=str(TMP / "visits"))
os.environ.pop("STREAMS_LOCAL", None)

from app import db, visits, web  # noqa: E402

visits.write = lambda *a, **k: None          # журнал посещений в тесте не пишем

passed, failed = 0, []


def check(name: str, cond: bool, extra="") -> None:
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def utc(hours_ago: float) -> str:
    t = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours_ago)
    return t.strftime("%Y-%m-%d %H:%M:%S")


def make_game(conn, home: str, seen: int) -> int:
    """Игра на завтра с одним живым каналом (канал уже прочитан)."""
    day = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    cur = conn.execute(
        "INSERT INTO events (sport, league_auto, team_home_auto, team_away_auto, "
        "start_utc, start_kyiv, first_seen, last_seen, seen) "
        "VALUES ('F', 'Liga', ?, 'Гости', ?, ?, ?, ?, ?)",
        (home, f"{day} 17:00", f"{day} 20:00", utc(200), utc(0), seen))
    event_id = cur.lastrowid
    cur = conn.execute("INSERT INTO channels (canonical_name, slug, country) "
                       "VALUES (?, ?, 'XX')", (f"Канал {home}", f"kanal-{home.lower()}"))
    conn.execute(
        "INSERT INTO event_channels (event_id, channel_id, source_id, source_url, "
        "raw_title, first_seen, last_seen, miss_count, seen) "
        "VALUES (?, ?, 1, '', '', ?, ?, 0, 1)", (event_id, cur.lastrowid, utc(200), utc(0)))
    conn.commit()
    return event_id


def seen_of(event_id: int) -> tuple[int, list[int]]:
    conn = db.connect()
    try:
        game = conn.execute("SELECT seen FROM events WHERE id = ?", (event_id,)).fetchone()[0]
        chans = [r[0] for r in conn.execute(
            "SELECT seen FROM event_channels WHERE event_id = ?", (event_id,))]
    finally:
        conn.close()
    return game, chans


def row_html(page: str, event_id: int) -> str:
    m = re.search(rf'<tr id="g{event_id}".*?</tr>', page, re.S)
    return m.group(0) if m else ""


def is_fresh(row: str) -> bool:
    m = re.search(r'class="game([^"]*)"', row)
    return bool(m) and "fresh" in m.group(1).split()


def main() -> int:
    conn = db.connect()
    db.init_db(conn)
    conn.execute("INSERT INTO sources (id, domain, name, base_url, country) "
                 "VALUES (1, 'test.tv', 'Тест', 'https://test.tv/', 'XX')")
    conn.commit()
    read = make_game(conn, "Прочитана", seen=1)
    fresh = make_game(conn, "Новая", seen=0)
    conn.close()
    app = web.create_app()

    print("1. гость")
    g = app.test_client()
    page = g.get("/schedule").get_data(as_text=True)
    check("гость видит игру", bool(row_html(page, read)))
    check("у гостя точки нет", "unread-dot" not in row_html(page, read))
    def refused(r) -> bool:
        # гостя админка уводит на вход (302 → /login), как у прочих кнопок владельца
        return r.status_code in (400, 403) or (
            r.status_code == 302 and "/login" in r.headers.get("Location", ""))
    r = g.post(f"/games/{read}/unseen", data={})
    check("запрос гостя без токена отклонён", refused(r), r.status_code)
    with g.session_transaction() as s:
        s["csrf_token"] = "abc123"
    r = g.post(f"/games/{read}/unseen", data={"csrf_token": "abc123"})
    check("гость с токеном тоже отклонён", refused(r), r.status_code)
    check("база после гостя не тронута", seen_of(read)[0] == 1)

    print("2. владелец: точка на месте")
    a = app.test_client()
    r = a.post("/login", data={"password": "adm-test-1"})
    check("вход владельца", r.status_code == 302, r.status_code)
    page = a.get("/schedule").get_data(as_text=True)
    m = re.search(r'<meta name="csrf" content="([^"]+)"', page)
    tok = m.group(1) if m else ""
    check("токен страницы есть", bool(tok))
    row = row_html(page, read)
    check("у прочитанной игры — точка", 'class="unread-dot"' in row)
    check("прочитанная игра не зелёная", not is_fresh(row))
    check("точка стоит в клетке спорта",
          re.search(r'<td class="sport">[^<]*<button class="unread-dot"', row) is not None)
    check("у новой игры точка есть, но спрятана правилом CSS",
          is_fresh(row_html(page, fresh)) and "tr.game.fresh .unread-dot { display:none; }" in page)

    print("3. клик по точке и обратно")
    r = a.post(f"/games/{read}/unseen", data={"csrf_token": tok})
    check("ответ ok", r.status_code == 200 and r.get_json() == {"ok": True}, r.status_code)
    game, chans = seen_of(read)
    check("игра снова непрочитанная", game == 0)
    check("«new» каналов не тронут", chans == [1], chans)
    row = row_html(a.get("/schedule").get_data(as_text=True), read)
    check("после обновления страницы строка зелёная", is_fresh(row) and 'data-unread="1"' in row)
    r = a.post(f"/games/{read}/seen", data={"csrf_token": tok})
    check("клик по строке гасит обратно", r.status_code == 200 and seen_of(read)[0] == 1)
    r = a.post(f"/games/{read}/unseen", data={"csrf_token": tok})
    check("второй круг тоже работает", r.status_code == 200 and seen_of(read)[0] == 0)

    print("4. отказы")
    a.post(f"/games/{read}/seen", data={"csrf_token": tok})
    r = a.post(f"/games/{read}/unseen", data={"csrf_token": "wrong"})
    check("чужой токен — 400, база не тронута", r.status_code == 400 and seen_of(read)[0] == 1,
          r.status_code)
    r = a.post("/games/999999/unseen", data={"csrf_token": tok})
    check("игры нет — 404", r.status_code == 404, r.status_code)
    r = a.get(f"/games/{read}/unseen")
    check("открыть адрес в браузере нельзя (только POST)", r.status_code == 405, r.status_code)

    print("5. скрипт страницы")
    check("клик по строке, попавший в точку, строку не гасит",
          'if (ev.target.closest(".unread-dot")) return;' in page)
    check("точка шлёт /unseen и при отказе снимает подсветку",
          '"/unseen"' in page and 'row.classList.remove("fresh");' in page)

    print(f"\nПроверок: {passed + len(failed)}, провалов: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

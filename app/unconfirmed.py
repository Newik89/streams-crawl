# -*- coding: utf-8 -*-
"""Красная строка витрины: прямой эфир, вид спорта которого эталон не
подтвердил (книга 113, слово владельца 13.11.2026).

Слова владельца: «если на игре написано прямая трансляция на любом из языков —
то можно на общую витрину в красном цвете, а оттуда я её могу и удалить сам»;
кнопка удаления — «только для админа, кто залогинен».

Что это за строка. Сайт канала сам пометил передачу прямым эфиром, пара
команд прочитана, но название лиги есть у нескольких видов спорта
(«Premier League» — и футбол, и баскетбол), а эталон этой пары не знает ни в
одном. Раньше такая строка снималась или уходила вопросом владельцу.

Правила по порядку:

К1. В красные идёт только строка с ЧЕСТНОЙ пометкой эфира от сайта. Эфир
    угадан программой (`parse_live.guessed`) или пометки нет — строка
    снимается с записью в журнал, как раньше (решает `parse_live`).
К2. Красная строка — НЕ игра базы: в таблицу игр она не пишется, гостям
    витрины и клиентам API не отдаётся. Её видит только вошедший владелец.
К3. Одна пара в одно время у нескольких сайтов и каналов — одна красная
    строка со всеми каналами (`group`).
К4. Список хранится в настройке `unconfirmed_rows` и обновляется каждой
    полной заливкой (`merge`):
    а) строка, которую этот сбор назвал красной, — в списке;
    б) прежняя строка за день, который этот сбор покрыл, со страницы сайта,
       который этот сбор разобрал, но красной её сбор не назвал, — уходит:
       эталон узнал игру (она стала обычной строкой витрины) или сайт её
       убрал;
    в) прежняя строка за день, которого в этом сборе нет (скан одной даты),
       или с сайта, которого в этом сборе нет (сбор одного сайта с сервера,
       сайт не открылся), — остаётся;
    г) строка, чьё время прошло больше `KEEP_HOURS` часов назад, — уходит.
    Дозабор (докачка упавших страниц) список не трогает.
К5. Владелец удалил строку кнопкой — её ключ ложится в настройку
    `unconfirmed_removed`, и строка больше не показывается, даже если
    следующий сбор принесёт её снова (`remove`, `shown`). Ключи прошедших
    игр из списка удалённых вычищаются (`merge`).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

#: настройка со списком красных строк и настройка с ключами удалённых
ROWS_KEY = "unconfirmed_rows"
REMOVED_KEY = "unconfirmed_removed"
#: К4г: сколько часов после начала красная строка ещё стоит на витрине
KEEP_HOURS = 3
#: подсказка на витрине
HINT = ("Вид спорта не подтверждён эталоном: название лиги есть у нескольких "
        "видов спорта, а flashscore этой пары не знает ни в одном. Сайт "
        "канала пометил передачу прямым эфиром. Строку видите только вы")


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def key(row: dict) -> str:
    """Ключ красной строки: время по Киеву и пара (К3, К5)."""
    when = (row.get("start_kyiv") or "").replace(" ", "T")[:16]
    return f"{when}|{_norm(row.get('home'))}|{_norm(row.get('away'))}"


def _when(row: dict) -> datetime | None:
    try:
        return datetime.fromisoformat((row.get("start_kyiv") or "")[:16])
    except ValueError:
        return None


def group(rows: list[dict]) -> list[dict]:
    """К3: строки сбора → красные строки, одна на пару и время; каналы
    собраны списком без повторов. Строка без пары или времени не берётся."""
    out: dict[str, dict] = {}
    for r in rows or []:
        if not isinstance(r, dict) or _when(r) is None \
                or not _norm(r.get("home")) or not _norm(r.get("away")):
            continue
        k = key(r)
        got = out.setdefault(k, {
            "key": k, "home": r.get("home") or "", "away": r.get("away") or "",
            "league": r.get("league") or "",
            "start_kyiv": (r.get("start_kyiv") or "").replace(" ", "T")[:16],
            "виды": sorted(r.get("виды") or []), "channels": []})
        chan = {"name": r.get("канал") or r.get("домен") or "",
                "домен": r.get("домен") or "", "url": r.get("url") or ""}
        if chan["name"] and not any(c["name"] == chan["name"]
                                    and c["домен"] == chan["домен"]
                                    for c in got["channels"]):
            got["channels"].append(chan)
    return sorted(out.values(), key=lambda x: (x["start_kyiv"], x["key"]))


def _bare(domain: str) -> str:
    return (domain or "").lower().removeprefix("www.")


def merge(old: list[dict], new: list[dict], covered: set[str],
          sites: set[str], now: datetime) -> list[dict]:
    """К4: прежний список + красные строки этого сбора → новый список.
    `covered` — дни («ГГГГ-ММ-ДД» по Киеву), которые этот сбор покрыл;
    `sites` — сайты, с которых этот сбор разобрал хоть одну строку."""
    edge = now - timedelta(hours=KEEP_HOURS)
    out = {r["key"]: r for r in group_passthrough(new)}
    for r in old or []:
        if not isinstance(r, dict) or r.get("key") in out:
            continue
        свои = {_bare(c.get("домен")) for c in r.get("channels") or []}
        день_покрыт = (r.get("start_kyiv") or "")[:10] in covered
        if день_покрыт and свои & sites:                     # К4б
            continue
        out[r["key"]] = r                                    # К4в
    alive = [r for r in out.values()
             if (_when(r) or datetime.min) >= edge]          # К4г
    return sorted(alive, key=lambda x: (x["start_kyiv"], x["key"]))


def group_passthrough(rows: list[dict]) -> list[dict]:
    """Список уже сгруппированных строк (есть `key` и `channels`) — как есть;
    сырые строки сбора — через `group`."""
    rows = [r for r in rows or [] if isinstance(r, dict)]
    if rows and all("key" in r and "channels" in r for r in rows):
        return rows
    return group(rows)


def covered_days(data: dict) -> set[str]:
    """Дни, которые сбор покрыл: дни его игр и его красных строк."""
    days = {(g.get("start_kyiv") or "")[:10] for g in data.get("games") or []
            if isinstance(g, dict)}
    days |= {(r.get("start_kyiv") or "")[:10]
             for r in data.get("без_эталона") or [] if isinstance(r, dict)}
    days.discard("")
    return days


def parsed_sites(data: dict) -> set[str]:
    """Сайты, с которых сбор разобрал хоть одну строку (ключ «разобрано»)."""
    got = data.get("разобрано") or {}
    if not isinstance(got, dict):
        return set()
    return {_bare(d) for d, n in got.items() if n}


def _load(conn, name: str) -> list:
    row = conn.execute("SELECT value FROM settings WHERE key = ?",
                       (name,)).fetchone()
    try:
        got = json.loads(row["value"]) if row and row["value"] else []
    except (ValueError, TypeError):
        return []
    return got if isinstance(got, list) else []


def _save(conn, name: str, value: list) -> None:
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                 (name, json.dumps(value, ensure_ascii=False)))
    conn.commit()


def after_import(conn, data: dict, now: datetime | None = None) -> int:
    """Полная заливка сбора: обновить список красных строк (К4) и вычистить
    ключи удалённых, чьё время прошло (К5). Возвращает число строк в списке.
    Сбор без ключа «без_эталона» (старый файл) список не трогает."""
    if "без_эталона" not in data:
        return len(_load(conn, ROWS_KEY))
    now = now or datetime.now()
    rows = merge(_load(conn, ROWS_KEY), group(data.get("без_эталона") or []),
                 covered_days(data), parsed_sites(data), now)
    _save(conn, ROWS_KEY, rows)
    edge = (now - timedelta(hours=KEEP_HOURS)).strftime("%Y-%m-%dT%H:%M")
    removed = [k for k in _load(conn, REMOVED_KEY)
               if isinstance(k, str) and k[:16] >= edge]
    _save(conn, REMOVED_KEY, removed)
    return len(rows)


def remove(conn, row_key: str) -> bool:
    """К5: владелец удалил красную строку. True — такая строка была."""
    row_key = (row_key or "").strip()
    if not row_key:
        return False
    known = any(r.get("key") == row_key for r in _load(conn, ROWS_KEY))
    removed = _load(conn, REMOVED_KEY)
    if row_key not in removed:
        removed.append(row_key)
        _save(conn, REMOVED_KEY, removed)
    return known


def shown(conn, now: datetime | None = None) -> list[dict]:
    """Красные строки в виде строк витрины (те же поля, что у
    `store.schedule`), для вошедшего владельца (К2). Удалённые (К5) и
    прошедшие (К4г) не показываются."""
    now = now or datetime.now()
    edge = now - timedelta(hours=KEEP_HOURS)
    removed = set(_load(conn, REMOVED_KEY))
    out = []
    for n, r in enumerate(_load(conn, ROWS_KEY), 1):
        start = _when(r) if isinstance(r, dict) else None
        if start is None or start < edge or r.get("key") in removed:
            continue
        out.append({
            "id": f"u{n}", "unconfirmed": r["key"], "hint": HINT,
            "pending": 0, "title": False, "sport": "",
            "league": r.get("league") or "", "league_auto": "",
            "home": r.get("home") or "", "away": r.get("away") or "",
            "home_auto": "", "away_auto": "", "named": True,
            "start": start, "date": start.date(),
            "time": start.strftime("%H:%M"),
            "live": start <= now < start + timedelta(hours=2),
            "first_seen": "", "is_new": False, "unread": False,
            "moved_from": "", "doubt": "",
            "channels": [{"id": 0, "name": c.get("name") or "",
                          "country": "", "url": c.get("url") or "",
                          "new": False, "new_ever": False, "seen": True,
                          "time_off": False, "custom": True,
                          "new_source": False}
                         for c in r.get("channels") or []],
            "gone_channels": [],
        })
    return out

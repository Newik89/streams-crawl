# -*- coding: utf-8 -*-
"""Словари названий в базе и очередь модерации (ТЗ разд. 8).

Разделение труда со словарём слов `data/aliases.json`:

  - `aliases.json` — куски названий: `BREMA` → `BREMEN`, `SANKT` → `SAINT`.
    Одно слово чинит сразу много имён, ведёт его ассистент;
  - таблицы здесь — **целые имена**: `Мидълзбро` → `Middlesbrough`. Их
    подтверждает владелец, и подтверждённое держится навсегда.

Не опознали имя — не выбрасываем и не гадаем: строка ложится в `moderation`
как «сырое имя + предложение системы», владелец подтверждает или правит.

**Канал — это имя И страна.** `Nova Sport 1` бывает греческий и чешский, это
разные каналы (решение владельца 31.08). Поэтому у канала обязательна
страна, а алиас привязан к сайту, на котором встретился: одно и то же
написание на греческом и чешском телегиде ведёт к разным каналам.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata

KINDS = ("team", "league", "channel", "sport")

_SLUG_TRIM = re.compile(r"[^a-z0-9]+")


def slugify(name: str, fallback: str = "x") -> str:
    """`ENGLAND: Championship` → `england-championship`. Нужен как стабильный
    внешний идентификатор (ТЗ разд. 8)."""
    folded = unicodedata.normalize("NFKD", name or "")
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    slug = _SLUG_TRIM.sub("-", ascii_only.lower()).strip("-")
    return slug or fallback


def _unique_slug(conn: sqlite3.Connection, table: str, base: str) -> str:
    """У `slug` в схеме стоит UNIQUE: два разных клуба могут дать одинаковую
    основу, поэтому второму добавляем номер."""
    slug, n = base, 2
    while conn.execute(f"SELECT 1 FROM {table} WHERE slug = ?", (slug,)).fetchone():
        slug, n = f"{base}-{n}", n + 1
    return slug


# ── чтение словарей ──────────────────────────────────────────────────────────

def team_overrides(conn: sqlite3.Connection) -> dict[str, str]:
    """Сырое имя → каноническое. Отдаём готовым словарём: в разборе он
    спрашивается на каждое имя, а ходить в базу столько раз незачем."""
    return {r["alias"]: r["canonical_name"] for r in conn.execute(
        "SELECT a.alias, t.canonical_name FROM team_aliases a "
        "JOIN teams t ON t.id = a.team_id")}


def league_overrides(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["alias"]: r["canonical_name"] for r in conn.execute(
        "SELECT a.alias, l.canonical_name FROM league_aliases a "
        "JOIN leagues l ON l.id = a.league_id")}


def channel_overrides(conn: sqlite3.Connection) -> dict[tuple[str, int | None], dict]:
    """Ключ — пара (написание, сайт). Именно пара, а не одно написание:
    `Nova Sport 1` на греческом и на чешском телегиде — разные каналы."""
    out: dict[tuple[str, int | None], dict] = {}
    for r in conn.execute(
            "SELECT a.alias, a.source_id, c.canonical_name, c.country "
            "FROM channel_aliases a JOIN channels c ON c.id = a.channel_id"):
        out[(r["alias"], r["source_id"])] = {"name": r["canonical_name"],
                                             "country": r["country"]}
    return out


# ── запись подтверждённого ───────────────────────────────────────────────────

def remember_team(conn: sqlite3.Connection, raw: str, canonical: str,
                  country: str | None = None, lang: str | None = None) -> int:
    """Закрепляет «сырое имя → команда». Команда с таким каноническим именем
    уже есть — цепляем алиас к ней, а не заводим двойника."""
    row = conn.execute("SELECT id FROM teams WHERE canonical_name = ?",
                       (canonical,)).fetchone()
    if row:
        team_id = row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO teams (canonical_name, slug, country) VALUES (?, ?, ?)",
            (canonical, _unique_slug(conn, "teams", slugify(canonical, "team")),
             country))
        team_id = cur.lastrowid
    conn.execute("INSERT OR IGNORE INTO team_aliases (team_id, alias, lang) "
                 "VALUES (?, ?, ?)", (team_id, raw, lang))
    conn.commit()
    return team_id


def remember_league(conn: sqlite3.Connection, raw: str, canonical: str,
                    sport: str | None = None, country: str | None = None,
                    lang: str | None = None) -> int:
    row = conn.execute("SELECT id FROM leagues WHERE canonical_name = ?",
                       (canonical,)).fetchone()
    if row:
        league_id = row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO leagues (slug, canonical_name, sport, country) "
            "VALUES (?, ?, ?, ?)",
            (_unique_slug(conn, "leagues", slugify(canonical, "league")),
             canonical, sport, country))
        league_id = cur.lastrowid
    conn.execute("INSERT OR IGNORE INTO league_aliases (league_id, alias, lang) "
                 "VALUES (?, ?, ?)", (league_id, raw, lang))
    conn.commit()
    return league_id


def remember_channel(conn: sqlite3.Connection, raw: str, canonical: str,
                     country: str, source_id: int | None = None,
                     language: str | None = None) -> int:
    """Канал ищем по паре (имя, страна) — по одному имени нельзя, см. шапку.
    Страна обязательна: без неё греческий и чешский `Nova Sport 1` сольются."""
    if not country:
        raise ValueError("каналу нужна страна: одно имя бывает у разных каналов")
    row = conn.execute(
        "SELECT id FROM channels WHERE canonical_name = ? AND country = ?",
        (canonical, country)).fetchone()
    if row:
        channel_id = row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO channels (canonical_name, slug, country, language) "
            "VALUES (?, ?, ?, ?)",
            (canonical,
             _unique_slug(conn, "channels",
                          slugify(f"{canonical}-{country}", "channel")),
             country, language))
        channel_id = cur.lastrowid
    conn.execute("INSERT OR IGNORE INTO channel_aliases (channel_id, alias, "
                 "source_id) VALUES (?, ?, ?)", (channel_id, raw, source_id))
    conn.commit()
    return channel_id


def remember_sport(conn: sqlite3.Connection, raw_value: str,
                   letter: str) -> None:
    """Владелец сказал, какой это спорт. Ключ — пара команд, как её написал
    сайт: «Kocaelispor - Samsunspor | beIN SPORTS 1 (beinsports.com.tr)» →
    помним «Kocaelispor - Samsunspor». Канал и домен отбрасываем: та же
    пара приходит и с других каналов.
    """
    пара = (raw_value or "").split("|")[0].strip()
    letter = (letter or "").strip().upper()[:1]
    if not пара or letter not in ("F", "B", "T"):
        raise ValueError("нужен вид спорта: F, B или T")
    conn.execute("INSERT INTO sport_hints (pair, sport) VALUES (?, ?) "
                 "ON CONFLICT (pair) DO UPDATE SET sport = excluded.sport",
                 (пара, letter))
    conn.commit()


def sport_hints(conn: sqlite3.Connection) -> dict[str, str]:
    """Все подсказки владельца: пара команд → буква вида спорта."""
    return {r["pair"]: r["sport"] for r in
            conn.execute("SELECT pair, sport FROM sport_hints")}


REMEMBER = {"team": remember_team, "league": remember_league}


# ── очередь модерации ────────────────────────────────────────────────────────

def enqueue(conn: sqlite3.Connection, kind: str, raw_value: str,
            suggestion: str = "", source_id: int | None = None) -> bool:
    """Кладёт непознанное имя в очередь. Возвращает, добавилась ли новая
    строка: одно и то же имя приходит с каждым обходом, и плодить дубли
    нельзя — очередь станет нечитаемой."""
    if kind not in KINDS:
        raise ValueError(f"неизвестный вид записи: {kind}")
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return False
    exists = conn.execute(
        "SELECT 1 FROM moderation WHERE kind = ? AND raw_value = ? "
        "AND (source_id IS ? OR source_id = ?) AND status IN ('open', 'later')",
        (kind, raw_value, source_id, source_id)).fetchone()
    if exists:
        return False
    # Уже разобранное второй раз не спрашиваем: владелец сказал «пропустить» —
    # значит эта строка не имя команды, и напоминать о ней каждое утро незачем.
    done = conn.execute(
        "SELECT 1 FROM moderation WHERE kind = ? AND raw_value = ? "
        "AND status IN ('done', 'skipped')", (kind, raw_value)).fetchone()
    if done:
        return False
    conn.execute("INSERT INTO moderation (kind, raw_value, source_id, suggestion) "
                 "VALUES (?, ?, ?, ?)", (kind, raw_value, source_id, suggestion))
    conn.commit()
    return True


def open_items(conn: sqlite3.Connection, kind: str = "",
               limit: int = 200, first: int = 0,
               later: bool = False) -> list[sqlite3.Row]:
    """`first` — номер записи, которую надо показать ПЕРВОЙ: с витрины
    приходят прямо на неё (оранжевая строка игры, 10.09), и искать её среди
    двухсот других владелец не должен. Если она не попала в выборку по
    лимиту — добавляем отдельно."""
    # `later` — вкладка «Отложенные»: то, на что владелец нажал «Не знаю»
    where = "WHERE m.status = 'later'" if later else "WHERE m.status = 'open'"
    params: list = []
    if kind:
        where += " AND m.kind = ?"
        params.append(kind)
    params.append(limit)
    # Страну сайта отдаём как заготовку для канала: чаще всего канал той же
    # страны, что и телегид. Владелец правит, когда канал иностранный.
    rows = conn.execute(
        f"SELECT m.*, s.domain, s.country AS source_country FROM moderation m "
        f"LEFT JOIN sources s ON s.id = m.source_id {where} "
        f"ORDER BY m.kind, m.raw_value LIMIT ?", params).fetchall()
    if not first:
        return rows
    picked = [r for r in rows if r["id"] == first]
    if not picked:
        picked = conn.execute(
            "SELECT m.*, s.domain, s.country AS source_country FROM moderation m "
            "LEFT JOIN sources s ON s.id = m.source_id "
            "WHERE m.id = ? AND m.status IN ('open', 'later')",
            (first,)).fetchall()
    return list(picked) + [r for r in rows if r["id"] != first]


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT kind, COUNT(*) c FROM moderation "
                        "WHERE status = 'open' GROUP BY kind")
    return {r["kind"]: r["c"] for r in rows}


def resolve(conn: sqlite3.Connection, item_id: int, canonical: str,
            country: str = "") -> None:
    """Владелец подтвердил имя: закрепляем навсегда и закрываем строку."""
    item = conn.execute("SELECT * FROM moderation WHERE id = ?",
                        (item_id,)).fetchone()
    if item is None:
        raise LookupError(f"нет записи модерации {item_id}")
    canonical = (canonical or "").strip()
    if not canonical:
        raise ValueError("пустое название")

    if item["kind"] == "sport":
        # тут закрепляется не название, а вид спорта: «F», «B» или «T»
        remember_sport(conn, item["raw_value"], canonical)
        conn.execute("UPDATE moderation SET status = 'done', suggestion = ? "
                     "WHERE id = ?", (canonical, item_id))
        conn.commit()
        return
    if item["kind"] == "channel":
        remember_channel(conn, item["raw_value"], canonical, country,
                         item["source_id"])
    else:
        remember = REMEMBER.get(item["kind"])
        if remember is None:
            raise ValueError(f"нечего закреплять для вида {item['kind']}")
        remember(conn, item["raw_value"], canonical)

    conn.execute("UPDATE moderation SET status = 'done', suggestion = ? "
                 "WHERE id = ?", (canonical, item_id))
    conn.commit()


def later(conn: sqlite3.Connection, item_id: int) -> None:
    """«Не знаю» — отложить: запись не удаляется и не считается решённой,
    просто уходит из основного списка во вкладку «Отложенные», откуда её
    можно достать и ответить позже (просьба владельца 11.09)."""
    conn.execute("UPDATE moderation SET status = 'later' WHERE id = ?",
                 (item_id,))
    conn.commit()


def back_to_open(conn: sqlite3.Connection, item_id: int) -> None:
    """Вернуть отложенную запись в основной список."""
    conn.execute("UPDATE moderation SET status = 'open' WHERE id = ? "
                 "AND status = 'later'", (item_id,))
    conn.commit()


def later_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM moderation "
                        "WHERE status = 'later'").fetchone()[0]


def skip(conn: sqlite3.Connection, item_id: int) -> None:
    """«Это не команда» — например заголовок турнира вместо пары клубов.
    Строку не удаляем: иначе она вернётся следующим же обходом."""
    conn.execute("UPDATE moderation SET status = 'skipped' WHERE id = ?",
                 (item_id,))
    conn.commit()

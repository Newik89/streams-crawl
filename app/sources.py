# -*- coding: utf-8 -*-
"""Работа со списком источников: выборка, правка, добавление пачкой.

Логика отделена от веба, чтобы её можно было прогнать скриптом и проверить
на реальных данных, а не только кликами в браузере.
"""

from __future__ import annotations

import sqlite3
from urllib.parse import urlsplit

# Что владелец может править руками. Всё остальное ставит разведка/парсер.
EDITABLE = ("name", "timezone", "role", "access", "priority", "url_pattern",
            "parse_level", "status", "notes")

ROLES = {"schedule": "расписание", "directory": "справочник"}
ACCESS = {"open": "открыт", "registration": "нужна регистрация",
          "paid": "платная подписка", "unknown": "неясно"}
STATUSES = {"new": "новый", "ok": "работает", "broken": "сломан",
            "closed": "не пускает"}


def domain_of(url: str) -> str:
    """Домен без www. Дубль источника считаем по домену (ТЗ разд. 11)."""
    host = urlsplit(url.strip()).netloc.lower()
    if not host:                       # ссылку вставили без http://
        host = urlsplit("http://" + url.strip()).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]


def normalize_url(url: str) -> str:
    url = url.strip()
    if url and not urlsplit(url).scheme:
        url = "http://" + url
    return url


# ── выборка ──────────────────────────────────────────────────────────────────

def list_sources(conn: sqlite3.Connection, *, q: str = "", role: str = "",
                 status: str = "", access: str = "", level: str = "",
                 enabled: str = "", protection: str = "") -> list[sqlite3.Row]:
    """Список с фильтрами. Поиск `q` идёт и по названию, и по ссылкам —
    чтобы владелец мог проверить, добавлен ли уже конкретный адрес.
    `protection`: `yes` — только сайты с защитой, `no` — только без неё.
    Такие сайты рабочие, отдельного списка у них больше нет (29.08.2026),
    поэтому нужен способ показать их одной кучкой."""
    sql = ["SELECT s.*, (SELECT COUNT(*) FROM source_urls u WHERE u.source_id = s.id) "
           "AS urls_count FROM sources s WHERE 1=1"]
    args: list = []

    if q:
        like = f"%{q.strip().lower()}%"
        sql.append("AND (LOWER(s.domain) LIKE ? OR LOWER(s.name) LIKE ? "
                   "OR EXISTS (SELECT 1 FROM source_urls u "
                   "WHERE u.source_id = s.id AND LOWER(u.url) LIKE ?))")
        args += [like, like, like]
    for field, value in (("role", role), ("status", status),
                         ("access", access), ("parse_level", level)):
        if value:
            sql.append(f"AND s.{field} = ?")
            args.append(value)
    if enabled in ("0", "1"):
        sql.append("AND s.enabled = ?")
        args.append(int(enabled))
    if protection == "yes":
        sql.append("AND s.protection IS NOT NULL AND s.protection <> ''")
    elif protection == "no":
        sql.append("AND (s.protection IS NULL OR s.protection = '')")

    # Сверху самые полезные: сначала готовый JSON, потом читаемые из HTML,
    # непонятные — в конце.
    sql.append("ORDER BY s.enabled DESC, CASE s.parse_level "
               "WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 "
               "WHEN 'D' THEN 4 ELSE 5 END, s.domain")
    return conn.execute(" ".join(sql), args).fetchall()


def get_source(conn: sqlite3.Connection, source_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()


def get_urls(conn: sqlite3.Connection, source_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM source_urls WHERE source_id = ? ORDER BY id", (source_id,)
    ).fetchall()


def find_by_url(conn: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    """Ищем по домену: вторая ссылка на тот же сайт — это дубль."""
    return conn.execute(
        "SELECT * FROM sources WHERE domain = ?", (domain_of(url),)).fetchone()


def counts(conn: sqlite3.Connection) -> dict:
    def one(sql: str, *a) -> int:
        return conn.execute(sql, a).fetchone()[0]

    return {
        "total": one("SELECT COUNT(*) FROM sources"),
        "enabled": one("SELECT COUNT(*) FROM sources WHERE enabled = 1"),
        "schedule": one("SELECT COUNT(*) FROM sources WHERE role = 'schedule'"),
        "directory": one("SELECT COUNT(*) FROM sources WHERE role = 'directory'"),
        "broken": one("SELECT COUNT(*) FROM sources WHERE status = 'broken'"),
        "closed": one("SELECT COUNT(*) FROM sources WHERE status = 'closed'"),
        "need_review": one("SELECT COUNT(*) FROM sources WHERE access <> 'open'"),
        "urls": one("SELECT COUNT(*) FROM source_urls"),
        "level_a": one("SELECT COUNT(*) FROM sources WHERE parse_level = 'A'"),
        "level_b": one("SELECT COUNT(*) FROM sources WHERE parse_level = 'B'"),
        "level_d": one("SELECT COUNT(*) FROM sources WHERE parse_level = 'D'"),
    }


# ── правка ───────────────────────────────────────────────────────────────────

def update_source(conn: sqlite3.Connection, source_id: int, data: dict) -> None:
    fields = {k: (v.strip() if isinstance(v, str) else v)
              for k, v in data.items() if k in EDITABLE}
    if not fields:
        return
    if "priority" in fields:
        fields["priority"] = int(fields["priority"] or 100)
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE sources SET {sets} WHERE id = ?",
                 (*fields.values(), source_id))
    conn.commit()


def toggle_enabled(conn: sqlite3.Connection, source_id: int) -> int:
    """Выключенный источник не обходится, но остаётся в базе (мягкое удаление)."""
    row = conn.execute("SELECT enabled FROM sources WHERE id = ?",
                       (source_id,)).fetchone()
    new = 0 if row["enabled"] else 1
    conn.execute("UPDATE sources SET enabled = ? WHERE id = ?", (new, source_id))
    conn.commit()
    return new


def delete_source(conn: sqlite3.Connection, source_id: int) -> None:
    """Настоящее удаление. Только по кнопке владельца, сам никто не удаляет."""
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()


def add_url(conn: sqlite3.Connection, source_id: int, url: str) -> bool:
    try:
        conn.execute("INSERT INTO source_urls (source_id, url) VALUES (?,?)",
                     (source_id, normalize_url(url)))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def delete_url(conn: sqlite3.Connection, url_id: int) -> None:
    conn.execute("DELETE FROM source_urls WHERE id = ?", (url_id,))
    conn.commit()


# ── добавление пачкой ────────────────────────────────────────────────────────

def bulk_add(conn: sqlite3.Connection, text: str) -> dict:
    """Разбирает вставленный список ссылок.

    Возвращает отчёт тремя списками:
      added     — новые источники;
      duplicate — сайт уже есть: показываем, какая это запись, чтобы владелец
                  мог перейти на неё и решить (ТЗ разд. 11);
      invalid   — не похоже на ссылку.

    Ссылки не проверяются запросом к сайту: массовые обходы ловят баны.
    Доступность проверяет разведка отдельной кнопкой.
    """
    report = {"added": [], "duplicate": [], "invalid": []}
    seen_in_batch: dict[str, dict] = {}

    for raw in text.splitlines():
        raw = raw.strip().strip(",;")
        if not raw:
            continue

        url = normalize_url(raw)
        domain = domain_of(url)
        if not domain or "." not in domain:
            report["invalid"].append({"url": raw, "reason": "не похоже на ссылку"})
            continue

        existing = conn.execute("SELECT id, domain, name FROM sources WHERE domain = ?",
                                (domain,)).fetchone()
        if existing:
            is_new_url = add_url(conn, existing["id"], url)
            report["duplicate"].append({
                "url": url, "domain": domain,
                "source_id": existing["id"], "name": existing["name"],
                "url_added": is_new_url,   # сайт был, но эта ссылка новая
            })
            continue

        if domain in seen_in_batch:       # дубль внутри самой вставленной пачки
            first = seen_in_batch[domain]
            add_url(conn, first["source_id"], url)
            report["duplicate"].append({
                "url": url, "domain": domain, "source_id": first["source_id"],
                "name": first["name"], "url_added": True,
            })
            continue

        cur = conn.execute(
            "INSERT INTO sources (domain, name, base_url, status, access) "
            "VALUES (?,?,?, 'new', 'unknown')", (domain, domain, url))
        source_id = cur.lastrowid
        conn.execute("INSERT INTO source_urls (source_id, url) VALUES (?,?)",
                     (source_id, url))
        entry = {"url": url, "domain": domain, "source_id": source_id, "name": domain}
        seen_in_batch[domain] = entry
        report["added"].append(entry)

    conn.commit()
    return report

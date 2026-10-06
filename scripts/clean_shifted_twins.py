# -*- coding: utf-8 -*-
r"""Разовая уборка: двойники ночных игр, сдвинутые на сутки старым разбором.

До пачки 06.10 разборы ntvplus.tv, sport5.co.il и ещё семи сайтов ставили
ночную строку страницы на СЛЕДУЮЩИЕ сутки («час < 6 → завтра», ветка
ref-midnight). Новый код ставит её верно — на день страницы, и первая же
заливка заводит игру на сутки раньше. Старое событие на D+1 не гаснет само:
свежий сбор о нём не знает (правило 2 `app/miss.py` — «игры нет в сборе»),
и на витрине у одной игры двойник через ровно 24 часа. На копии базы после
заливки #205 таких 7, все sport5 (предсезонка NBA и полуфиналы WNBA).

Двойник — событие, у которого ВСЁ сразу:
  1. оно ещё впереди и свежая заливка его не подтвердила (ни одна его
     отметка не видена с момента `--since`);
  2. все его отметки — от сайтов, чей разбор сменил правило дня
     (`СМЕНИЛИ_ПРАВИЛО_ДНЯ`);
  3. у каждой его живой отметки есть близнец, подтверждённый свежей
     заливкой: тот же сайт, тот же канал, тот же заголовок строки — у игры
     ровно на `СДВИГ` раньше. Заголовок различает настоящие разные игры тех
     же команд («полуфинал — игра 2» и «игра 3» WNBA).

Что делает `--apply`: гасит живые отметки двойника ТАК ЖЕ, как гасит
заливка (`store._add_miss`: пропуск +1, на витрине канал «снят»); событие
не удаляет — удаление только по слову владельца, а игра без живых каналов
уйдёт сама по сроку. Повторный запуск ничего не меняет (живых отметок у
двойника уже нет). Без `--apply` только показывает. К сайтам не обращается.

Порядок на сервере — после выкладки пачки и ПЕРВОЙ полной заливки новым
кодом (до неё двойников ещё нет; метка `--since` по умолчанию — последняя
заливка, у скана даты она охватывает один день — тогда указать метку
полной заливки явно):

    ssh root@157.245.77.140 "cd streams-schedule && \
        venv/bin/python scripts/clean_shifted_twins.py"             — показ
    ssh root@157.245.77.140 "cd streams-schedule && \
        venv/bin/python scripts/clean_shifted_twins.py --apply"     — запись

Откат: отметки, погашенные уборкой, скрипт печатает списком id — вернуть
их `scripts/miss_repair.py --ids <список> --apply`.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, store  # noqa: E402

#: сайты, чей разбор сменил правило дня ночных строк (ветка ref-midnight,
#: коммит 2587524): жёсткое «час < N → завтра» заменено порядком страницы
СМЕНИЛИ_ПРАВИЛО_ДНЯ = frozenset({
    "ntvplus.tv", "sport5.co.il", "oneplaysport.cz", "trt.net.tr", "rts.rs",
    "skai.gr", "rtcg.me", "atv.com.tr", "mojtv.hr"})

#: на сколько старый разбор сдвигал ночную строку
СДВИГ = timedelta(days=1)

ФОРМАТ = "%Y-%m-%d %H:%M"


@dataclass
class Двойник:
    """Устаревшее событие и игры, где его строки теперь подтверждены."""
    event_id: int
    start: str
    title: str
    #: живые отметки двойника: (id, сайт, канал, заголовок строки)
    отметки: list[tuple[int, str, str, str]] = field(default_factory=list)
    #: события ровно на `СДВИГ` раньше, где те же строки подтверждены
    близнецы: set[int] = field(default_factory=set)


def найти(conn: sqlite3.Connection, since: str, now: str) -> list[Двойник]:
    """Двойники по правилам 1–3 шапки. `since` — момент свежей заливки,
    `now` — сейчас по Киеву (оба `ГГГГ-ММ-ДД ЧЧ:ММ`)."""
    marks: dict[int, list[sqlite3.Row]] = {}
    for m in conn.execute(
            "SELECT ec.id, ec.event_id, ec.source_id, ec.channel_id, "
            "ec.raw_title, ec.last_seen, ec.miss_count, s.domain, "
            "c.canonical_name AS channel, e.start_kyiv "
            "FROM event_channels ec JOIN sources s ON s.id = ec.source_id "
            "JOIN channels c ON c.id = ec.channel_id "
            "JOIN events e ON e.id = ec.event_id"):
        marks.setdefault(m["event_id"], []).append(m)
    # подтверждённые свежей заливкой строки: (сайт, канал, заголовок, начало)
    свежие: dict[tuple, set[int]] = {}
    for rows in marks.values():
        for m in rows:
            if m["last_seen"] >= since and (m["raw_title"] or "").strip():
                ключ = (m["source_id"], m["channel_id"], m["raw_title"],
                        m["start_kyiv"])
                свежие.setdefault(ключ, set()).add(m["event_id"])

    out: list[Двойник] = []
    for e in conn.execute(
            "SELECT id, start_kyiv, team_home_auto, team_away_auto FROM events "
            "WHERE start_kyiv > ? ORDER BY start_kyiv, id", (now,)):
        rows = marks.get(e["id"], [])
        if not rows or any(m["last_seen"] >= since for m in rows):
            continue                                            # правило 1
        if any(m["domain"].removeprefix("www.") not in СМЕНИЛИ_ПРАВИЛО_ДНЯ
               for m in rows):
            continue                                            # правило 2
        живые = [m for m in rows if m["miss_count"] < store.MISS_LIMIT]
        if not живые:
            continue                                   # уже погашено раньше
        раньше = (datetime.strptime(e["start_kyiv"], ФОРМАТ) - СДВИГ) \
            .strftime(ФОРМАТ)
        двойник = Двойник(e["id"], e["start_kyiv"],
                          f"{e['team_home_auto']} - {e['team_away_auto']}")
        for m in живые:                                         # правило 3
            близнецы = свежие.get((m["source_id"], m["channel_id"],
                                   m["raw_title"], раньше), set())
            if not близнецы:
                break
            двойник.отметки.append((m["id"], m["domain"], m["channel"],
                                    m["raw_title"]))
            двойник.близнецы |= близнецы
        else:
            out.append(двойник)
    return out


def погасить(conn: sqlite3.Connection, двойники: list[Двойник]) -> list[int]:
    """Живые отметки двойников — +1 к пропускам, как у заливки. Вернёт id
    погашенных отметок (для отката через `miss_repair.py`)."""
    погашены = []
    for двойник in двойники:
        for mark_id, *_ in двойник.отметки:
            if store._add_miss(conn, mark_id):
                погашены.append(mark_id)
    conn.commit()
    return погашены


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="погасить отметки двойников (без флага — только показ)")
    ap.add_argument("--since", default="",
                    help="момент свежей заливки ГГГГ-ММ-ДД ЧЧ:ММ (часы сервера, "
                         "как last_seen); по умолчанию — последняя заливка")
    args = ap.parse_args()

    conn = db.connect()
    try:
        since = args.since or conn.execute(
            "SELECT MAX(last_seen) FROM event_channels").fetchone()[0] or ""
        now = datetime.now(ZoneInfo("Europe/Kyiv")).strftime(ФОРМАТ)
        print(f"база {db.db_path()}; свежая заливка с {since}; сейчас (Киев) {now}")
        двойники = найти(conn, since, now)
        for д in двойники:
            близнецы = ", ".join(
                f"#{r['id']} {r['start_kyiv']} {r['team_home_auto']} - "
                f"{r['team_away_auto']}" for r in conn.execute(
                    f"SELECT id, start_kyiv, team_home_auto, team_away_auto "
                    f"FROM events WHERE id IN ({','.join('?' * len(д.близнецы))})",
                    sorted(д.близнецы)))
            print(f"  двойник #{д.event_id} {д.start} {д.title}\n"
                  f"     подтверждён на сутки раньше: {близнецы}")
            for mark_id, domain, channel, title in д.отметки:
                print(f"     отметка {mark_id}: {domain} {channel} — «{title}»")
        print(f"двойников: {len(двойники)}, живых отметок у них: "
              f"{sum(len(д.отметки) for д in двойники)}")
        if not двойники or not args.apply:
            if двойники:
                print("это показ; погасить — с флагом --apply")
            return 0
        погашены = погасить(conn, двойники)
        print(f"погашено отметок: {len(погашены)}; откат — "
              f"scripts/miss_repair.py --ids {','.join(map(str, погашены))} --apply")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

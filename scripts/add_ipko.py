# -*- coding: utf-8 -*-
r"""Завести источник ipko.tv (добавил владелец 22.09.2026) и 29 каналов:
группа Sport целиком (28) + RTK 1, которого владелец просил.

Идемпотентен: повторный запуск ничего не дублирует. Гонять в ОБЕИХ базах:
    venv\Scripts\python.exe scripts/add_ipko.py
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_ipko.py"

Кухня сайта — шлюз titan (см. шапку `app/parsers/ipko_tv.py`): POST на канал
и день, даты метками `{UNIXDAY}`/`{UNIXDAYEND}` (строками ручка тоже ест,
проверено 22.09), канал несёт свой адрес (`?channel_id=slug`, как webtv.sk).
Интерфейс сайта показывает только «до завтра», но ручка отдаёт всю неделю
(проверка окном +2..+7: по ~40 передач на день) — глубину не ограничиваем.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402

DOMAIN = "ipko.tv"
BASE = "https://ipko.tv/tv-guide/rtk-1"
API = "https://stargate.ipko.tv/api/titan.tv.WebEpg/GetWebEpgData"
CONFIG = {
    # тело запроса: метки дат подставит `crawl_fetch.json_body`, канал — из
    # адреса строки (`?channel_id=`); ручка терпит даты строками
    "post_json": {"ch_ext_id": "{channel_id}",
                  "from": "{UNIXDAY}", "to": "{UNIXDAYEND}"},
    "headers": {"Origin": "https://ipko.tv", "Referer": "https://ipko.tv/"},
}

#: slug на сайте → (имя канала, страна). Страны: RTK/K-Sport/Sport/KB Peja —
#: Косово; SuperSport/Tring — албанские пакеты; TRT Spor и A Spor — турецкие
#: (тёзки уже живут в базе с TR — не плодим двойников)
CHANNELS = [
    ("rtk-1", "RTK 1", "XK"),
    ("sport-1", "Sport 1", "XK"), ("sport-2", "Sport 2", "XK"),
    ("sport-3", "Sport 3", "XK"), ("sport-4", "Sport 4", "XK"),
    ("sport-5", "Sport 5", "XK"), ("sport-6", "Sport 6", "XK"),
    ("k-sport-1", "K-Sport 1", "XK"), ("k-sport-2", "K-Sport 2", "XK"),
    ("k-sport-3", "K-Sport 3", "XK"), ("k-sport-4", "K-Sport 4", "XK"),
    ("kb-peja", "KB Peja", "XK"),
    ("trt-spor", "TRT Spor", "TR"), ("a-spor", "A Spor", "TR"),
    ("tring-sport-news", "Tring Sport News", "AL"),
    ("supersport-1", "SuperSport 1", "AL"), ("supersport-2", "SuperSport 2", "AL"),
    ("supersport-3", "SuperSport 3", "AL"), ("supersport-4", "SuperSport 4", "AL"),
    ("supersport-5", "SuperSport 5", "AL"), ("supersport-6", "SuperSport 6", "AL"),
    ("supersport-7", "SuperSport 7", "AL"),
    ("tring-sport-1", "Tring Sport 1", "AL"), ("tring-sport-2", "Tring Sport 2", "AL"),
    ("tring-sport-3", "Tring Sport 3", "AL"), ("tring-sport-4", "Tring Sport 4", "AL"),
    ("tring-sport-5", "Tring Sport 5", "AL"), ("tring-sport-6", "Tring Sport 6", "AL"),
    ("tring-sport-7", "Tring Sport 7", "AL"),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = db.connect()
    row = conn.execute("SELECT id FROM sources WHERE domain = ?",
                       (DOMAIN,)).fetchone()
    notes = ("сайт-приложение titan (Telekom SI); расписание — POST на "
             "stargate.ipko.tv, канал и день в теле; интерфейс кажет 2 дня, "
             "ручка отдаёт неделю; эфир — первым показом пары (22.09.2026)")
    if row:
        source_id = row["id"]
        conn.execute(
            "UPDATE sources SET base_url = ?, country = 'XK', "
            "timezone = 'Europe/Belgrade', role = 'schedule', access = 'open', "
            "url_pattern = '', parse_strategy = 'structured', "
            "parse_level = 'A', enabled = 1, status = 'ok', "
            "selector_config = ?, notes = ? WHERE id = ?",
            (BASE, json.dumps(CONFIG, ensure_ascii=False), notes, source_id))
        print(f"источник обновлён: id {source_id}")
    else:
        cur = conn.execute(
            "INSERT INTO sources (domain, name, base_url, country, timezone, "
            "role, access, url_pattern, parse_strategy, parse_level, "
            "selector_config, enabled, status, notes) "
            "VALUES (?, ?, ?, 'XK', 'Europe/Belgrade', 'schedule', 'open', "
            "'', 'structured', 'A', ?, 1, 'ok', ?)",
            (DOMAIN, "IPKO TV (Косово) — гид titan", BASE,
             json.dumps(CONFIG, ensure_ascii=False), notes))
        source_id = cur.lastrowid
        print(f"источник заведён: id {source_id}")

    added = 0
    for slug, name, country in CHANNELS:
        channel_id = dictionary.remember_channel(
            conn, name, name, country, source_id=source_id)
        page = f"{API}?channel_id={slug}"
        have = conn.execute(
            "SELECT id FROM source_channels WHERE source_id = ? "
            "AND raw_name = ?", (source_id, name)).fetchone()
        if have:
            conn.execute(
                "UPDATE source_channels SET channel_id = ?, page_url = ?, "
                "include = 1 WHERE id = ?", (channel_id, page, have["id"]))
        else:
            conn.execute(
                "INSERT INTO source_channels (source_id, raw_name, "
                "channel_id, page_url, include) VALUES (?, ?, ?, ?, 1)",
                (source_id, name, channel_id, page))
            added += 1
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM source_channels "
                         "WHERE source_id = ?", (source_id,)).fetchone()[0]
    print(f"каналов у источника: {total} (новых {added})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

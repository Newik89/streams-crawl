# -*- coding: utf-8 -*-
r"""Заполнить каналы четырёх пилотных источников — по СОХРАНЁННЫМ страницам.

Зачем. В закладках владельца у половины сайтов стоял один-единственный канал,
и часто неспортивный (`recon/channels_map.md`): на `teleman.pl` — `Eleven
Sports 2` из 26 спортивных, на `nova.bg` — только `Nova Sport` из четырёх.
Обходить надо все спортивные, поэтому список каналов должен лежать в базе
(`source_channels`), а не в адресе закладки.

Скрипт читает списки каналов **из уже скачанных копий** в `recon/raw_deep/`
и к сайтам не обращается. Запускать можно сколько угодно: повторный запуск
обновляет строки, а не плодит их (`UNIQUE (source_id, raw_name)`).

Что ставится:
  * `source_channels` — все каналы сайта; `include=1` только у спортивных,
    остальные остаются в базе выключенными, чтобы владелец видел выбор;
  * `sources.parse_strategy` — `structured` там, где сайт отдаёт готовый JSON,
    `selectors` там, где разбираем разметку;
  * `sources.selector_config.url_marks` — метки для `app.urls.resolve()`.

Запуск:
    venv\Scripts\python.exe scripts/setup_pilot_channels.py
    venv\Scripts\python.exe scripts/setup_pilot_channels.py --dry-run
"""

from __future__ import annotations

import gzip
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db                                          # noqa: E402
from app.parsers import nova_bg, sporttv_pt, teleman_pl, tv_nova_cz  # noqa: E402

RAW = ROOT / "recon" / "raw_deep"
BACKUP = ROOT / f"backup_{date.today():%d.%m.%Y}_этап2"


def read(name: str) -> str:
    path = RAW / name
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace").read()
    return path.read_text(encoding="utf-8", errors="replace")


def plans() -> list[dict]:
    """Что записать по каждому пилоту: каналы, спортивные из них, стратегия."""
    bg = nova_bg.list_channels(read("nova.bg.html"))
    cz = tv_nova_cz.list_channels(read("tv.nova.cz.full.html.gz"))
    pl_all = teleman_pl.list_channels(read("teleman.pl.html"))
    pl_sport = teleman_pl.sport_channels(read("teleman.pl.html"))
    pt = sporttv_pt.list_channels(read("sporttv.pt.html"))

    return [
        {"domain": "nova.bg", "strategy": "selectors", "mark": "channel_id",
         "channels": bg, "sport": {"4", "5", "6", "8"}},
        {"domain": "tv.nova.cz", "strategy": "structured", "mark": "channel_id",
         "channels": cz, "sport": {f"nova-sport-{i}" for i in range(1, 7)}},
        {"domain": "teleman.pl", "strategy": "selectors", "mark": "slug",
         "channels": pl_all, "sport": set(pl_sport)},
        {"domain": "sporttv.pt", "strategy": "structured", "mark": "channel_id",
         "channels": pt, "sport": set(pt)},
    ]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    dry = "--dry-run" in sys.argv

    conn = db.connect()
    if not dry:
        BACKUP.mkdir(exist_ok=True)
        copy = BACKUP / "channel_schedule_before_stage2.db"
        if not copy.exists():
            conn.commit()
            shutil.copy2(db.db_path(), copy)
            print(f"копия базы: {copy}")

    for plan in plans():
        row = conn.execute("SELECT id, url_pattern, base_url, selector_config "
                           "FROM sources WHERE domain=?", (plan["domain"],)).fetchone()
        if not row:
            print(f"{plan['domain']}: в базе нет, пропускаю")
            continue

        config = json.loads(row["selector_config"] or "{}")
        marks = config.setdefault("url_marks", {})
        added = updated = 0
        for key, name in plan["channels"].items():
            include = 1 if key in plan["sport"] else 0
            # В `page_url` подставляем только канал, дату оставляем меткой:
            # так уже сделано у btv.bg, и так адрес не устареет. Готовую
            # ссылку на нужный день строит `app.urls.resolve()` при обходе —
            # закладки с датой 2024 года мы на этом уже обожглись.
            page = (row["url_pattern"] or row["base_url"] or "").replace(
                "{" + plan["mark"] + "}", key)
            before = conn.execute(
                "SELECT include FROM source_channels WHERE source_id=? AND raw_name=?",
                (row["id"], name)).fetchone()
            if not dry:
                conn.execute(
                    "INSERT INTO source_channels (source_id, raw_name, page_url, include, last_seen) "
                    "VALUES (?,?,?,?,datetime('now')) "
                    "ON CONFLICT(source_id, raw_name) DO UPDATE SET "
                    "page_url=excluded.page_url, include=excluded.include, "
                    "last_seen=excluded.last_seen",
                    (row["id"], name, page, include))
            added += 0 if before else 1
            updated += 1 if before else 0

        config.setdefault("channel_mark", plan["mark"])
        if not dry:
            conn.execute("UPDATE sources SET parse_strategy=?, selector_config=? WHERE id=?",
                         (plan["strategy"], json.dumps(config, ensure_ascii=False), row["id"]))
        print(f"{plan['domain']}: каналов {len(plan['channels'])}, "
              f"спортивных {len(plan['sport'])}, новых {added}, обновлено {updated}, "
              f"разбор — {plan['strategy']}")

    if dry:
        print("\n--dry-run: в базу ничего не записано")
    else:
        conn.commit()
        print("\nзаписано в базу")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

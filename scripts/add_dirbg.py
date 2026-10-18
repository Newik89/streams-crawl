# -*- coding: utf-8 -*-
r"""Завести источник tv.dir.bg — телегид портала dir.bg (слово владельца
18.10.2026: «нужно расписание bTV Action — важный канал»; сам btv.bg закрыт
Cloudflare) и семь каналов, которые он выбрал: bTV Action, bTV, Ring.bg
(bTV Sport), BNT 1–4.

Кухня сайта — в шапке `app/parsers/tv_dir_bg.py`: `GET /init` даёт ключ
`csrfToken` и куки, дальше `POST /load/programs?channel=<id>&day=<день>` с
телом `_token=<ключ>`. В карточке источника: `warmup_url` — страница ключа,
`post_fields` — тело с меткой `{WARMKEY}` (её подставляет `app/fetch.py`),
адрес с номером канала — в `page_url` каждого канала, дата — меткой
`{YYYY-MM-DD}` (её подставляет обход в день запуска). Обход: адрес на канал
и день, 7 каналов × окно.

Имена каналов — как сайт пишет в `alt` на `/channels` (`NAMES` парсера);
переименовать — владелец (✎ в админке). Канал = имя + страна: БНТ, возможно,
уже есть в базе от источника bnt.bg («BNT 3», «БНТ 1»…) — тогда привязываем
существующий `channels.id`, а не плодим двойников (`_existing`: сравнение
без регистра, пробелов и знаков, кириллица «БНТ» читается как «BNT»,
скобочное имя — `Ring.bg (bTV Sport)` — пробуется и целиком, и по частям).

Идемпотентен: повторный запуск ничего не дублирует. Гонять в ОБЕИХ базах:
    venv\Scripts\python.exe scripts/add_dirbg.py --apply
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_dirbg.py --apply"

Без `--apply` только показывает, что сделает. К сайтам не обращается.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary, translit  # noqa: E402
from app.parsers import tv_dir_bg  # noqa: E402

COUNTRY, ZONE = "BG", "Europe/Sofia"

#: номер канала на сайте → имя (как в alt на /channels, 18.10.2026)
CHANNELS = list(tv_dir_bg.NAMES.items())

PAGE = "https://tv.dir.bg/load/programs?channel={id}&day={{YYYY-MM-DD}}"

SOURCE = {
    "domain": tv_dir_bg.DOMAIN,
    "name": "Телегид dir.bg — bTV Action, bTV, Ring.bg, БНТ (България)",
    "base": "https://tv.dir.bg/",
    # шаблон для вида: рабочие адреса лежат в page_url каналов
    "pattern": "https://tv.dir.bg/load/programs?channel={channel_id}&day={YYYY-MM-DD}",
    "config": {
        "warmup_url": "https://tv.dir.bg/init",
        "post_fields": {"_token": "{WARMKEY}"},
    },
    "notes": ("телегид dir.bg: ключ csrfToken с GET /init (warmup_url) + куки, "
              "затем POST /load/programs?channel=<id>&day=<день> с телом "
              "_token (post_fields, метка {WARMKEY}); ответ JSON с html, три "
              "панели вчера/день/завтра — берём день; эфир — приставка ПРЯКО; "
              "каналы bTV Action, bTV, Ring.bg, БНТ 1–4 выбрал владелец "
              "18.10.2026; парсер tv_dir_bg"),
}


def key(text: str) -> str:
    """Имя канала для сравнения: латиницей, без регистра, пробелов и знаков
    (`БНТ 1` = `BNT1` = `bnt 1`)."""
    latin = translit.to_english(text or "")
    return "".join(c for c in latin.casefold() if c.isalnum())


def name_keys(name: str) -> set[str]:
    """Все написания имени сайта: целиком, до скобки и внутри скобки
    (`Ring.bg (bTV Sport)` → ringbg, btvsport, ringbgbtvsport)."""
    out = {key(name)}
    head, bracket, tail = name.partition("(")
    if bracket:
        out.add(key(head))
        out.add(key(tail.rstrip(") ")))
    return {k for k in out if k}


def _existing(conn, name: str) -> int | None:
    """Канал Болгарии, который в базе уже есть: по имени или написанию."""
    want = name_keys(name)
    for r in conn.execute("SELECT id, canonical_name FROM channels WHERE country = ?",
                          (COUNTRY,)):
        if name_keys(r["canonical_name"]) & want:
            return r["id"]
    for r in conn.execute("SELECT a.channel_id, a.alias FROM channel_aliases a "
                          "JOIN channels c ON c.id = a.channel_id WHERE c.country = ?",
                          (COUNTRY,)):
        if name_keys(r["alias"]) & want:
            return r["channel_id"]
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="записать в базу (без флага — только показ)")
    args = ap.parse_args()

    conn = db.connect()
    src = SOURCE
    row = conn.execute("SELECT id FROM sources WHERE domain = ?",
                       (src["domain"],)).fetchone()
    have = {r["raw_name"] for r in conn.execute(
        "SELECT raw_name FROM source_channels WHERE source_id = ?",
        (row["id"],))} if row else set()
    new = [name for _, name in CHANNELS if name not in have]
    print(f"{src['domain']}: {'есть, id ' + str(row['id']) if row else 'нет — заведу'}; "
          f"каналов в списке {len(CHANNELS)}, новых у источника {len(new)}")
    print(f"   разогрев: {src['config']['warmup_url']}; "
          f"тело: {src['config']['post_fields']}")
    for cid, name in CHANNELS:
        found = _existing(conn, name)
        print(f"   {name:<22} канал {cid:>3}  →  "
              f"{'канал в базе уже есть, id ' + str(found) if found else 'новый канал'}"
              f"   {PAGE.format(id=cid)}")
    if not args.apply:
        print("это показ; записать — с флагом --apply")
        conn.close()
        return 0

    config = json.dumps(src["config"], ensure_ascii=False)
    if row:
        source_id = row["id"]
        conn.execute(
            "UPDATE sources SET name = ?, base_url = ?, country = ?, "
            "timezone = ?, role = 'schedule', access = 'open', url_pattern = ?, "
            "parse_strategy = 'structured', parse_level = 'A', enabled = 1, "
            "status = 'ok', selector_config = ?, notes = ? WHERE id = ?",
            (src["name"], src["base"], COUNTRY, ZONE, src["pattern"],
             config, src["notes"], source_id))
    else:
        source_id = conn.execute(
            "INSERT INTO sources (domain, name, base_url, country, timezone, "
            "role, access, url_pattern, parse_strategy, parse_level, "
            "selector_config, enabled, status, notes) VALUES (?, ?, ?, ?, ?, "
            "'schedule', 'open', ?, 'structured', 'A', ?, 1, 'ok', ?)",
            (src["domain"], src["name"], src["base"], COUNTRY, ZONE,
             src["pattern"], config, src["notes"])).lastrowid
    for cid, name in CHANNELS:
        channel_id = _existing(conn, name)
        if channel_id is None:
            channel_id = dictionary.remember_channel(conn, name, name, COUNTRY,
                                                     source_id=source_id)
        else:
            # написание сайта — к уже известному каналу, чтобы сверка имён
            # знала его и дальше
            conn.execute("INSERT OR IGNORE INTO channel_aliases (channel_id, alias, "
                         "source_id) VALUES (?, ?, ?)", (channel_id, name, source_id))
        page = PAGE.format(id=cid)
        got = conn.execute("SELECT id FROM source_channels WHERE source_id = ? "
                           "AND raw_name = ?", (source_id, name)).fetchone()
        if got:
            conn.execute("UPDATE source_channels SET channel_id = ?, page_url = ?, "
                         "include = 1 WHERE id = ?", (channel_id, page, got["id"]))
        else:
            conn.execute("INSERT INTO source_channels (source_id, raw_name, "
                         "channel_id, page_url, include) VALUES (?, ?, ?, ?, 1)",
                         (source_id, name, channel_id, page))
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM source_channels WHERE source_id = ?",
                         (source_id,)).fetchone()[0]
    print(f"   записано: id {source_id}, каналов у источника {total}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

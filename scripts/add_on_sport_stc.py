# -*- coding: utf-8 -*-
r"""ON Sport вторым источником (yallakora.com) и STC TV одной платформой
(страница канала livesoccertv) — книга 167, слова владельца 19.11.2026.

Разведка 18–19.11 (пробы GitHub #508, #509): открытой телепрограммы у ON
Sport и STC TV нет. У yallakora.com у матча стоит канал ON Sport (на день
игры, включая гандбол); у livesoccertv есть страница платформы STC TV
(Серия А). Слова владельца: про ON Sport — «да, делаем», «к трём
нынешним»; про STC TV — «завести просто, что игра показывается этой
платформой, а клиент сам подберёт нужный канал», «ok».

Правила по порядку:

 А. yallakora.com — новый источник: страна EG, пояс Africa/Cairo, адрес на
    день `match-center?date={MM/DD/YYYY}`, глубина 2 дня (`max_days`):
    канал у матча сайт ставит к дню игры. Тип — дневная сетка
    (`crawl.DAY_GRID_DOMAINS`), разбор `app/parsers/yallakora_com.py`.
 Б. Три канала ON Sport у него — ТЕ ЖЕ каналы Египта, что уже идут с
    livesoccertv (`ПАРЫ`: имя у yallakora → имя у livesoccertv). Канал
    ищется по написанию у livesoccertv; имя канала на витрине НЕ меняется —
    три из них владелец переименовал сам. Нет канала — заводится в EG.
 В. «ON Sport 2» больше не существует (с 2026 это ON Sport Max): его
    страницу у livesoccertv перестаём обходить (`include = 0`). Канал и его
    написания остаются в базе — ничего не удаляется.
 Г. STC TV — страница платформы у livesoccertv, канал страны SA; имя на
    витрине — по правилам `channel_rules.apply`.
 Д. Идемпотентно; без `--apply` — только показ, база не меняется.

Гонять в ОБЕИХ базах (сначала без `--apply`):
    venv\Scripts\python.exe scripts/add_on_sport_stc.py --apply
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/add_on_sport_stc.py --apply"
К сайтам не обращается. После — пересобрать план (`crawl_plan.py`), сверить
(`plan_diff.py`) и выложить (`push_plan.py`). Тест: `scripts/test_on_sport_stc.py`.

Откат: `source_config.py`-ом ничего не нужно — выключить источник
yallakora.com в админке (или `UPDATE sources SET enabled = 0`), вернуть
`include = 1` странице «ON Sport 2», выключить страницу «STC TV».
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import channel_rules, db, dictionary  # noqa: E402
from app.parsers import yallakora_com  # noqa: E402

LSTV = "livesoccertv.com"
LSTV_PAGE = "https://www.livesoccertv.com/channels/{}/"

#: правило А
YALLA = {
    "domain": yallakora_com.DOMAIN,
    "name": "Yallakora — матчи дня с каналом показа (Египет)",
    "base": "https://www.yallakora.com/match-center",
    "pattern": "https://www.yallakora.com/match-center?date={MM/DD/YYYY}",
    "country": "EG",
    "zone": yallakora_com.TZ,
    "max_days": 2,
    "notes": ("матчи дня по турнирам, у матча — канал показа (ON Sport — к дню игры); арабский, "
              "время каирское; все строки — эфир по слову сайта; глубина 2 дня; парсер "
              "yallakora_com (слово владельца 19.11.2026, книга 167)"),
}
#: правило Б: (имя канала у yallakora, имя того же канала у livesoccertv)
ПАРЫ = [("ON Sport", "ON Sport 1"), ("ON Sport Max", "ON Sport Max"), ("ON Sport Plus", "ON Sport Plus")]
#: правило В
СНЯТЬ_СТРАНИЦУ = "ON Sport 2"
#: правило Г: (имя канала со страницы livesoccertv, слаг страницы, страна)
STC = ("STC TV", "stc-tv", "SA")


def _key(text: str) -> str:
    return "".join(c for c in (text or "").casefold() if c.isalnum())


def find_channel(conn, name: str, country: str) -> int | None:
    """Канал страны по имени или написанию (без регистра и пробелов)."""
    want = _key(name)
    for r in conn.execute("SELECT id, canonical_name FROM channels WHERE country = ?", (country,)):
        if _key(r["canonical_name"]) == want:
            return r["id"]
    for r in conn.execute("SELECT a.channel_id, a.alias FROM channel_aliases a "
                          "JOIN channels c ON c.id = a.channel_id WHERE c.country = ?", (country,)):
        if _key(r["alias"]) == want:
            return r["channel_id"]
    return None


def _canonical(conn, channel_id: int) -> str:
    return conn.execute("SELECT canonical_name FROM channels WHERE id = ?", (channel_id,)).fetchone()["canonical_name"]


def _page(conn, source_id: int, raw: str, channel_id: int, page: str) -> str:
    """Строка `source_channels`: есть — обновить, нет — завести."""
    row = conn.execute("SELECT id FROM source_channels WHERE source_id = ? AND raw_name = ?",
                       (source_id, raw)).fetchone()
    if row:
        conn.execute("UPDATE source_channels SET channel_id = ?, page_url = ?, include = 1 WHERE id = ?",
                     (channel_id, page, row["id"]))
        return "обновлена"
    conn.execute("INSERT INTO source_channels (source_id, raw_name, channel_id, page_url, include) "
                 "VALUES (?, ?, ?, ?, 1)", (source_id, raw, channel_id, page))
    return "заведена"


def _yallakora_source(conn, write: bool) -> tuple[int | None, str]:
    """Правило А. Вернёт (id источника или None при показе, строка отчёта)."""
    row = conn.execute("SELECT id, selector_config FROM sources WHERE domain = ?", (YALLA["domain"],)).fetchone()
    if not write:
        return (row["id"] if row else None,
                f"{YALLA['domain']}: {'есть, id ' + str(row['id']) if row else 'нет — заведу'}; адрес {YALLA['pattern']}")
    try:
        config = json.loads(row["selector_config"] or "{}") if row else {}
    except ValueError:
        config = {}
    config["max_days"] = YALLA["max_days"]
    fields = (YALLA["name"], YALLA["base"], YALLA["country"], YALLA["zone"], YALLA["pattern"],
              json.dumps(config, ensure_ascii=False), YALLA["notes"])
    if row:
        conn.execute("UPDATE sources SET name = ?, base_url = ?, country = ?, timezone = ?, role = 'schedule', "
                     "access = 'open', url_pattern = ?, selector_config = ?, parse_strategy = 'structured', "
                     "parse_level = 'A', enabled = 1, status = 'ok', notes = ? WHERE id = ?", (*fields, row["id"]))
        return row["id"], f"{YALLA['domain']}: карточка обновлена, id {row['id']}"
    source_id = conn.execute(
        "INSERT INTO sources (domain, name, base_url, country, timezone, role, access, url_pattern, "
        "selector_config, parse_strategy, parse_level, enabled, status, notes) "
        "VALUES (?, ?, ?, ?, ?, 'schedule', 'open', ?, ?, 'structured', 'A', 1, 'ok', ?)",
        (YALLA["domain"], *fields)).lastrowid
    return source_id, f"{YALLA['domain']}: источник заведён, id {source_id}"


def apply(conn, *, write: bool) -> list[str]:
    """Правила А–Д. Возвращает строки отчёта; write=False — только показ."""
    out: list[str] = []
    lstv = conn.execute("SELECT id FROM sources WHERE domain = ?", (LSTV,)).fetchone()

    # А и Б: yallakora.com и три канала ON Sport
    source_id, line = _yallakora_source(conn, write)
    out.append(line)
    for raw, lstv_name in ПАРЫ:
        channel_id = find_channel(conn, lstv_name, YALLA["country"]) or find_channel(conn, raw, YALLA["country"])
        was = f"канал есть — «{_canonical(conn, channel_id)}» (id {channel_id})" if channel_id else "канала нет — заведу"
        if not write:
            out.append(f"  {raw}: {was}")
            continue
        canonical = _canonical(conn, channel_id) if channel_id \
            else channel_rules.apply(raw, YALLA["country"])
        channel_id = dictionary.remember_channel(conn, raw, canonical, YALLA["country"], source_id=source_id)
        how = _page(conn, source_id, raw, channel_id, "")
        out.append(f"  {raw}: {was}; строка канала у источника {how}")

    # В: страница «ON Sport 2» у livesoccertv — не обходить
    if lstv:
        row = conn.execute("SELECT id, include FROM source_channels WHERE source_id = ? AND raw_name = ?",
                           (lstv["id"], СНЯТЬ_СТРАНИЦУ)).fetchone()
        if row is None:
            out.append(f"{СНЯТЬ_СТРАНИЦУ}: страницы у {LSTV} нет — нечего снимать")
        elif not row["include"]:
            out.append(f"{СНЯТЬ_СТРАНИЦУ}: страница у {LSTV} уже не обходится")
        else:
            if write:
                conn.execute("UPDATE source_channels SET include = 0 WHERE id = ?", (row["id"],))
            out.append(f"{СНЯТЬ_СТРАНИЦУ}: страница у {LSTV} {'снята с обхода' if write else 'будет снята с обхода'} "
                       "(канал в базе остаётся)")

        # Г: STC TV — страница платформы у livesoccertv
        name, slug, country = STC
        page = LSTV_PAGE.format(slug)
        channel_id = find_channel(conn, name, country)
        was = f"канал есть (id {channel_id})" if channel_id else "канал новый"
        if write:
            canonical = _canonical(conn, channel_id) if channel_id else channel_rules.apply(name, country)
            channel_id = dictionary.remember_channel(conn, name, canonical, country, source_id=lstv["id"])
            how = _page(conn, lstv["id"], name, channel_id, page)
            out.append(f"{name}: {was} → id {channel_id} ({country}), страница {how}: {page}")
        else:
            out.append(f"{name}: {was}, страница: {page}")
    else:
        out.append(f"источника {LSTV} в базе нет — страницы «{СНЯТЬ_СТРАНИЦУ}» и «{STC[0]}» не тронуты")
    if write:
        conn.commit()
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="ON Sport с yallakora.com и STC TV с livesoccertv")
    ap.add_argument("--apply", action="store_true", help="записать (без него — показ)")
    args = ap.parse_args()
    conn = db.connect()
    try:
        print(f"база: {db.db_path()}" + ("" if args.apply else "  (только показ)"))
        for line in apply(conn, write=args.apply):
            print("  " + line)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

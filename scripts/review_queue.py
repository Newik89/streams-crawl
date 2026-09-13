# -*- coding: utf-8 -*-
r"""Пересмотр очереди «Названия»: убрать то, что спрашивать уже не нужно.

Очередь копилась с 05.09 и к 10.09 разрослась до 364 строк «вид спорта».
Владелец справедливо возмутился: там висят матчи недельной давности и
строки, чей вид спорта система теперь определяет сама — словарь лиг с тех
пор пополнился, появились подсказки по парам команд.

Скрипт проходит по открытым записям и закрывает те, что отпали:

* **прошло** — матч в строке уже сыгран (время видно в подсказке);
* **знаем** — вид спорта теперь определяется сам: по словам в тексте
  (`app/sport.py`), по лиге из словаря или по подсказке владельца;
* **сайт снят** — источник выключен или отложен.

    venv\Scripts\python.exe scripts/review_queue.py            # показать
    venv\Scripts\python.exe scripts/review_queue.py --apply    # закрыть

Закрытая запись не удаляется: у неё ставится `skipped`, и повторно её не
спросят. Если строка вернётся с новым обходом и снова не разберётся —
появится заново.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import canon, db, leagues, names, sport  # noqa: E402


def teams_from_reference(path: Path | None = None) -> dict[str, str]:
    """Команда → вид спорта по эталону flashscore из последнего обхода.

    Клуб играет в одном виде спорта, поэтому известное имя закрывает вопрос
    само. Имена, за которыми числится больше одного вида («Barcelona» — и
    футбол, и баскетбол), пропускаем.
    """
    import json
    файл = path or ROOT / "results" / "games.json"
    try:
        данные = json.loads(файл.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    виды: dict[str, set] = {}
    for r in данные.get("эталон") or []:
        вид = r.get("sport") or "F"
        for сторона in ("home", "away"):
            имя = (r.get(сторона) or "").strip()
            ключ = (names.readings(имя) or ("",))[0] if имя else ""
            if ключ:
                виды.setdefault(ключ, set()).add(вид)
    return {k: v for k, v in виды.items()}          # виды по ключу, без свёртки

#: сколько дней после матча запись ещё имеет смысл. По умолчанию 0 —
#: закрываем всё, что уже отыграно (с запасом в 3 часа на длинный матч):
#: собирать прошедшее незачем (слово владельца 10.09)
ЖИВЁТ_ДНЕЙ = 0
#: запас после начала: матч мог только начаться и ещё идёт
ИДЁТ_ЧАСОВ = 3
_ВРЕМЯ = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})")


def когда(item) -> datetime | None:
    """Время матча из подсказки: «2026-09-06 17:00 | Kasımpaşa - Amed SF»."""
    m = _ВРЕМЯ.search(item["suggestion"] or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def знаем_спорт(текст: str, sports, лиги: dict) -> str:
    """Определяется ли вид спорта сам — теми же правилами, что и в обходе.

    Возвращает «-», если это ЧУЖОЙ вид: волейбол, гандбол, хоккей. Такую
    строку тоже спрашивать незачем (владелец 10.09: «тут прямо в описании
    написано, что это волейбол»).
    """
    letter, _ = sports.detect(текст)
    if letter:
        return letter
    for кусок in re.split(r"[|()]", текст):
        буква = лиги.get(" ".join(кусок.lower().split()))
        if буква:
            return буква
    return ""


def teams_from_base(conn) -> dict[str, str]:
    """Команда → вид спорта по играм, которые уже лежат в нашей базе."""
    виды: dict[str, set] = {}
    for row in conn.execute(
            "SELECT t.canonical_name AS имя, e.sport AS вид "
            "FROM events e JOIN teams t "
            "  ON t.id IN (e.team_home_id, e.team_away_id) "
            "GROUP BY t.canonical_name, e.sport"):
        виды.setdefault(row["имя"], set()).add(row["вид"])
    return {k: next(iter(v)) for k, v in виды.items()
            if len(v) == 1 and next(iter(v))}      # имя → единственный вид


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kind", default="sport", help="какой раздел очереди")
    ap.add_argument("--days", type=int, default=ЖИВЁТ_ДНЕЙ,
                    help="сколько дней после матча запись ещё нужна")
    ap.add_argument("--apply", action="store_true", help="без него — показ")
    args = ap.parse_args()

    conn = db.connect()
    try:
        sports = sport.load()
        лиги = leagues.sports_map()
        подсказки = leagues.pair_sports()
        по_ключам = teams_from_reference()
        # и наша собственная база: там команд больше, чем в эталоне дня
        for имя, вид in teams_from_base(conn).items():
            ключ = (names.readings(имя) or ("",))[0]
            if ключ:
                по_ключам.setdefault(ключ, set()).add(вид)
        # ключ, за которым стоят разные виды («PARIS» — и футбольный Paris
        # FC, и баскетбольный Paris Basketball), решать не помогает
        команды = {k: next(iter(v)) for k, v in по_ключам.items()
                   if len(v) == 1}
        if команды:
            print(f"команд с известным видом спорта в эталоне: {len(команды)}")
        rows = conn.execute(
            "SELECT m.id, m.raw_value, m.suggestion, s.domain, s.enabled, "
            "       s.status "
            "FROM moderation m LEFT JOIN sources s ON s.id = m.source_id "
            # отложенные («Не знаю») тоже пересматриваем: отыгранный матч
            # незачем держать и там
            "WHERE m.kind = ? AND m.status IN ('open', 'later')",
            (args.kind,)).fetchall()
        порог = (datetime.now() - timedelta(days=args.days)
                 - timedelta(hours=ИДЁТ_ЧАСОВ))
        причины: dict[str, list] = {"прошло": [], "знаем": [], "сайт снят": [],
                                    "чужой спорт": []}
        for r in rows:
            текст = f"{r['raw_value']} {r['suggestion'] or ''}"
            матч = когда(r)
            пара = (r["raw_value"] or "").split("|")[0].strip()
            if r["domain"] and (not r["enabled"]
                                or r["status"] in ("parked", "deferred", "closed")):
                причины["сайт снят"].append(r)
            elif матч and матч < порог:
                причины["прошло"].append(r)
            elif (буква := знаем_спорт(текст, sports, лиги)) or подсказки.get(пара):
                причины["чужой спорт" if буква == "-" else "знаем"].append(r)
            elif команды:
                стороны = [x.strip() for x in re.split(r" - | — ", пара) if x.strip()]
                буквы = {команды.get((names.readings(x) or ("",))[0])
                         for x in стороны}
                # обе стороны должны быть известны: у сборных за одним именем
                # стоят разные виды спорта
                известные = {b for b in буквы if b}
                клубы = not any(names.is_country(x) for x in стороны)
                if len(стороны) == 2 and len(буквы) == 1 and None not in буквы:
                    причины["знаем"].append(r)
                elif len(стороны) == 2 and len(известные) == 1 and клубы:
                    # знакома одна сторона, и обе — клубы: клуб играет в
                    # одном виде спорта, значит и пара из него. У сборных
                    # так нельзя — страна выступает во всех видах сразу
                    причины["знаем"].append(r)
                elif len(стороны) == 2 and not any(буквы)                         and canon._script(пара) == "lat":
                    # Ни одна команда не знакома ни эталону недели (весь
                    # футбол, баскет и теннис), ни нашей базе — значит это
                    # чужой вид спорта: THW Kiel и SG Flensburg играют в
                    # гандбол, Houston Texans — американский футбол, Moto3 —
                    # мотогонки. Спрашивать про них незачем. Иврит и другие
                    # алфавиты не трогаем: там имена просто не читаются
                    причины["чужой спорт"].append(r)
        всего = sum(len(v) for v in причины.values())
        print(f"в очереди «{args.kind}»: {len(rows)}; можно закрыть: {всего}")
        for имя, куча in причины.items():
            print(f"   {имя}: {len(куча)}")
            for r in куча[:3]:
                print(f"      {r['raw_value'][:64]}")
        if not всего:
            return 0
        if not args.apply:
            print("\nчтобы закрыть — добавьте --apply")
            return 0
        conn.executemany("UPDATE moderation SET status = 'skipped' WHERE id = ?",
                         [(r["id"],) for куча in причины.values() for r in куча])
        conn.commit()
        print(f"закрыто записей: {всего}; осталось: {len(rows) - всего}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

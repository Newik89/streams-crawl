# -*- coding: utf-8 -*-
r"""Пересмотр очереди «Названия»: убрать то, что спрашивать уже не нужно.

Очередь копилась с 05.09 и к 10.09 разрослась до 364 строк «вид спорта».
Владелец справедливо возмутился: там висят матчи недельной давности и
строки, чей вид спорта система теперь определяет сама — словарь лиг с тех
пор пополнился, появились подсказки по парам команд.

Скрипт проходит по открытым записям и закрывает те, что отпали.
Закрывает ТОЛЬКО стопроцентное (условие владельца 15.09 — «риски отсева
навсегда не устраивают»):

* **прошло** — матч в строке уже сыгран (время видно в подсказке);
* **знаем** — вид спорта теперь определяется сам: по словам в тексте
  (`app/sport.py`), по лиге из словаря или по действующей подсказке;
* **чужой спорт** — в тексте прямо написан не наш вид (слово из
  `markers.json → чужие`: Hokej, MotoGP…);
* **дубль пары** — та же пара команд висит с другого канала;
* **сайт снят** — источник выключен или отложен.

Гадательное правило «ни одна команда не знакома» больше НЕ закрывает:
такие строки только показываются счётчиком, решает их владелец.

    venv\Scripts\python.exe scripts/review_queue.py            # показать
    venv\Scripts\python.exe scripts/review_queue.py --apply    # закрыть

Закрытая запись не удаляется: у неё ставится `skipped` (видно во вкладке
«Отсеянные», кнопка «Вернуть» возвращает). Если строка вернётся с новым
обходом и снова не разберётся — появится заново.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary, leagues, names, pipeline, sport  # noqa: E402


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
        db.init_db(conn)                     # досыпает свежие колонки
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
                                    "чужой спорт": [], "дубль пары": []}
        # Дубли одной пары с разных каналов (владелец 15.09): остаётся
        # строка с самым поздним матчем, остальные закрываются. Сведения
        # копий при этом СКЛАДЫВАЮТСЯ: один сайт пишет лигу, другой нет —
        # вместе они отвечают на вопрос, который поодиночке не решался
        # (идея владельца 15.09: «найти информацию на одном из каналов»)
        дубли_ids: set[int] = set()
        тексты_пары: dict[str, str] = {}
        if args.kind == "sport":
            по_парам: dict[str, list] = {}
            for r in rows:
                по_парам.setdefault(dictionary.norm_pair(r["raw_value"]),
                                    []).append(r)
            for пара, куча in по_парам.items():
                тексты_пары[пара] = " ".join(
                    f"{r['raw_value']} {r['suggestion'] or ''}" for r in куча)
                if len(куча) > 1:
                    куча = sorted(куча, key=lambda r: (
                        (r["suggestion"] or "")[:16], r["id"]))
                    причины["дубль пары"].extend(куча[:-1])
            дубли_ids = {r["id"] for r in причины["дубль пары"]}
        похоже_чужое: list = []      # гадательное: показываем, но НЕ закрываем
        # найденный и ПОДТВЕРЖДЁННЫЙ вид (слово спорта/лиги в тексте копий,
        # команды известны эталону) записывается бессрочной подсказкой:
        # обход выводит игру в расписание, лигу и имена даёт эталон, а если
        # что-то не так — владелец спросит за событие (его слово 15.09).
        # Срок ±36 ч остаётся только у ручных ответов на сомнительные пары
        новые_подсказки: dict[str, str] = {}
        for r in rows:
            if r["id"] in дубли_ids:
                continue
            матч = когда(r)
            пара = dictionary.norm_pair(r["raw_value"])
            текст = тексты_пары.get(пара) \
                or f"{r['raw_value']} {r['suggestion'] or ''}"
            hint = подсказки.get(пара)
            if r["domain"] and (not r["enabled"]
                                or r["status"] in ("parked", "deferred", "closed")):
                причины["сайт снят"].append(r)
            elif матч and матч < порог:
                причины["прошло"].append(r)
            elif (буква := знаем_спорт(текст, sports, лиги)) \
                    or (hint and pipeline.hint_fresh(hint[1], матч)):
                # просроченная подсказка (день матча далеко) не считается
                причины["чужой спорт" if буква == "-" else "знаем"].append(r)
                if буква in ("F", "B", "T") and not hint:
                    новые_подсказки[пара] = буква
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
                    if (б := next(iter(буквы))) in ("F", "B", "T"):
                        новые_подсказки[пара] = б
                elif len(стороны) == 2 and len(известные) == 1 and клубы:
                    # знакома одна сторона, и обе — клубы: клуб играет в
                    # одном виде спорта, значит и пара из него. У сборных
                    # так нельзя — страна выступает во всех видах сразу
                    причины["знаем"].append(r)
                    if (б := next(iter(известные))) in ("F", "B", "T"):
                        новые_подсказки[пара] = б
                elif len(стороны) == 2 and not any(буквы):
                    # Ни одна команда не знакома — ПОХОЖЕ на чужой спорт
                    # (THW Kiel — гандбол), но это догадка, а не факт.
                    # Автоматом не закрываем (владелец 15.09: «риски отсева
                    # не устраивают») — только показываем счётчиком
                    похоже_чужое.append(r)
        всего = sum(len(v) for v in причины.values())
        print(f"в очереди «{args.kind}»: {len(rows)}; можно закрыть: {всего}")
        for имя, куча in причины.items():
            print(f"   {имя}: {len(куча)}")
            for r in куча[:3]:
                print(f"      {r['raw_value'][:64]}")
        if похоже_чужое:
            print(f"   похоже на чужой спорт (НЕ закрываем, решает владелец): "
                  f"{len(похоже_чужое)}")
            for r in похоже_чужое[:3]:
                print(f"      {r['raw_value'][:64]}")
        if not всего:
            return 0
        if not args.apply:
            print("\nчтобы закрыть — добавьте --apply")
            return 0
        conn.executemany("UPDATE moderation SET status = 'skipped' WHERE id = ?",
                         [(r["id"],) for куча in причины.values() for r in куча])
        conn.commit()
        for пара, буква in новые_подсказки.items():
            dictionary.remember_sport(conn, пара, буква)
        if новые_подсказки:
            print(f"подтверждённых подсказок записано: {len(новые_подсказки)} — "
                  f"обход выведет эти игры в расписание")
        print(f"закрыто записей: {всего}; осталось: {len(rows) - всего}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

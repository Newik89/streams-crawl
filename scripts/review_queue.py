# -*- coding: utf-8 -*-
r"""Пересмотр очереди «Названия»: убрать то, что спрашивать уже не нужно.

Очередь копилась с 05.09 и к 10.09 разрослась до 364 строк «вид спорта».
Владелец справедливо возмутился: там висят матчи недельной давности и
строки, чей вид спорта система теперь определяет сама — словарь лиг с тех
пор пополнился, появились подсказки по парам команд.

Скрипт проходит по открытым и отложенным записям и закрывает те, что
отпали. Закрывает ТОЛЬКО бесспорное (условие владельца 15.09 — «риски
отсева навсегда не устраивают»):

* **сайт снят** — источник выключен или отложен;
* **прошло** — матч в строке уже сыгран (время видно в подсказке);
* **дубль пары** — та же пара команд висит с другого канала;
* **ответила программа** — вопрос решает `app/sport_question.py` (тот же
  `Sports.decide`, что в обходе, плюс эталон целиком и словари базы):
  наш вид спорта — ответом, как кнопкой «Футбол»; запись, студия, чужой
  вид спорта, показ не в час матча — в «Отсеянные». У каждого ответа
  пометка «ответила программа: правило N — улика»;
* **обе команды известны** — обе стороны пары знакомы эталону или базе в
  одном виде спорта (не сборные).

Гадательное «ни одна команда не знакома» и «знакома одна сторона» НЕ
закрывают: такие строки только показываются счётчиком, решает владелец.

Раздел «Команды» (`--kind team`, разбор 06.10, #2100 «Igokea» → «Slavia
Prague ERA NBK») закрывается по двум бесспорным правилам:

* **имя уже в словаре** — имя стало каноном команды или её алиасом
  (`canon.known_team`; вид спорта — по играм с этим именем, если он один);
* **игра с меткой flashscore** — все игры в базе с этим именем уже уверенно
  сопоставлены с эталоном (метка `fs:`), спрашивать не о чем.

    venv\Scripts\python.exe scripts/review_queue.py            # показать
    venv\Scripts\python.exe scripts/review_queue.py --apply    # закрыть
    venv\Scripts\python.exe scripts/review_queue.py --kind team          # команды: показать
    venv\Scripts\python.exe scripts/review_queue.py --kind team --apply  # команды: закрыть

Закрытая без ответа запись не удаляется: у неё ставится `skipped` (видно
во вкладке «Отсеянные» с причиной, кнопка «Вернуть» возвращает). Ответ
видом спорта пишется тем же путём, что кнопка админки (`dictionary.resolve`:
подсказка с днём матча — обход выведет игру в расписание).
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import canon, db, dictionary, names, watch  # noqa: E402
from app.sport_question import SPORT_WORDS, Judge, Question, settle  # noqa: E402


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


def pairs_from_reference(path: Path | None = None) -> list[dict]:
    """Записи эталона flashscore последнего обхода целиком — сверять пару.
    Берём все файлы обхода (полный прогон и скан даты): у скана даты свой
    день, которого в полном может не быть."""
    import json
    файлы = [path] if path else [ROOT / "results" / "games.json",
                                 ROOT / "results" / "day" / "games.json"]
    записи, виденные = [], set()
    for файл in файлы:
        try:
            данные = json.loads(файл.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in данные.get("эталон") or []:
            ключ = (r.get("home"), r.get("away"), r.get("start_kyiv"))
            if ключ not in виденные:
                виденные.add(ключ)
                записи.append(r)
    return записи


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


def team_closures(conn) -> dict[str, list]:
    """Раздел «Команды»: открытые и отложенные записи, спрашивать которые
    уже незачем. Закрываем только бесспорное (условие владельца 15.09):

    * «имя уже в словаре» — имя стало каноном команды или её алиасом
      (`canon.known_team`). Вид спорта берём по играм базы с этим именем,
      если он у них один: баскетбольный «Bilbao» футбольный вопрос не снимает;
    * «игра с меткой flashscore» — в базе есть игры с этим именем, и ВСЕ
      они уже уверенно сопоставлены с эталоном (метка `fs:`).

    Остальное — настоящие вопросы владельцу, их не трогаем."""
    причины: dict[str, list] = {"имя уже в словаре": [],
                                "игра с меткой flashscore": []}
    for r in conn.execute(
            "SELECT id, raw_value, suggestion FROM moderation "
            "WHERE kind = 'team' AND status IN ('open', 'later') "
            "ORDER BY id").fetchall():
        имя = (r["raw_value"] or "").strip()
        игры = conn.execute(
            "SELECT sport, flags FROM events "
            "WHERE team_home_auto = ? OR team_away_auto = ?",
            (имя, имя)).fetchall()
        виды = {g["sport"] for g in игры if g["sport"]}
        вид = next(iter(виды)) if len(виды) == 1 else ""
        if canon.known_team(conn, имя, вид):
            причины["имя уже в словаре"].append(r)
        elif игры and all(str(g["flags"] or "").startswith("fs:")
                          for g in игры):
            причины["игра с меткой flashscore"].append(r)
    return причины


def review_teams(conn, apply: bool) -> int:
    """`--kind team`: показать, что закроется; с `apply` — закрыть
    (`skipped`, вкладка «Отсеянные», кнопка «Вернуть») и оставить строку
    в «Прогонах» админки — сколько и почему."""
    всего_в_очереди = conn.execute(
        "SELECT COUNT(*) FROM moderation WHERE kind = 'team' "
        "AND status IN ('open', 'later')").fetchone()[0]
    причины = team_closures(conn)
    всего = sum(len(v) for v in причины.values())
    print(f"в очереди «team»: {всего_в_очереди}; можно закрыть: {всего}")
    for имя, куча in причины.items():
        print(f"   {имя}: {len(куча)}")
        for r in куча:
            print(f"      #{r['id']} {r['raw_value'][:48]} "
                  f"(подсказка: {(r['suggestion'] or '')[:40]})")
    if not всего:
        return 0
    if not apply:
        print("\nчтобы закрыть — добавьте --apply")
        return 0
    conn.executemany("UPDATE moderation SET status = 'skipped', "
                     "answered_by = ? WHERE id = ?",
                     [(УБОРКА.format(имя), r["id"])
                      for имя, куча in причины.items() for r in куча])
    conn.commit()
    watch.note(conn, f"очередь «Названия» (команды): закрыто {всего} ("
                     + "; ".join(f"{имя}: {len(куча)}"
                                 for имя, куча in причины.items() if куча)
                     + ") — вкладка «Отсеянные», кнопка «Вернуть»",
               who="автомат")
    print(f"закрыто записей: {всего}; осталось: {всего_в_очереди - всего}")
    return 0




def known_team_sports(conn) -> dict[str, str]:
    """Ключ команды (`names.readings`) → её единственный вид спорта: по
    эталону последнего обхода и по играм нашей базы. Ключ, за которым стоят
    разные виды («PARIS» — и футбольный Paris FC, и баскетбольный Paris
    Basketball), решать не помогает и сюда не входит."""
    по_ключам = teams_from_reference()
    for имя, вид in teams_from_base(conn).items():
        ключ = (names.readings(имя) or ("",))[0]
        if ключ:
            по_ключам.setdefault(ключ, set()).add(вид)
    return {k: next(iter(v)) for k, v in по_ключам.items() if len(v) == 1}


#: пометка `answered_by` у записей, закрытых уборкой без ответа
УБОРКА = "уборка очереди: {}"


def review_sport(conn, apply: bool, days: int = ЖИВЁТ_ДНЕЙ,
                 judge: Judge | None = None,
                 команды: dict[str, str] | None = None) -> int:
    """Раздел «Вид спорта»: показать, что закроется; с `apply` — закрыть.
    `judge` и `команды` подставляют проверки; по умолчанию — эталон
    последнего обхода и словари базы."""
    if judge is None:
        judge = Judge(conn, pairs_from_reference())
    if команды is None:
        команды = known_team_sports(conn)
    rows = conn.execute(
        "SELECT m.id, m.raw_value, m.suggestion, "
        "       s.domain, s.enabled, s.status "
        "FROM moderation m LEFT JOIN sources s ON s.id = m.source_id "
        # отложенные («Не знаю») тоже пересматриваем: отыгранный матч
        # незачем держать и там
        "WHERE m.kind = 'sport' AND m.status IN ('open', 'later') "
        "ORDER BY m.id").fetchall()
    порог = (datetime.now() - timedelta(days=days)
             - timedelta(hours=ИДЁТ_ЧАСОВ))
    уборка: dict[str, list] = {"сайт снят": [], "прошло": [],
                               "дубль пары": []}
    # Дубли одной пары с разных каналов (владелец 15.09): остаётся строка с
    # самым поздним матчем, остальные закрываются. Лигу, которую написал
    # только один из сайтов, оставшаяся копия берёт себе: вместе копии
    # отвечают на вопрос, который поодиночке не решался (идея владельца
    # 15.09: «найти информацию на одном из каналов»)
    по_парам: dict[str, list] = {}
    for r in rows:
        по_парам.setdefault(dictionary.norm_pair(r["raw_value"]), []).append(r)
    лиги_пары: dict[str, str] = {}
    for пара, куча in по_парам.items():
        лиги_пары[пара] = next(
            (q.league for q in (Question.parse(r["raw_value"], r["suggestion"])
                                for r in куча) if q.league), "")
        if len(куча) > 1:
            куча = sorted(куча, key=lambda r: ((r["suggestion"] or "")[:16],
                                               r["id"]))
            уборка["дубль пары"].extend(куча[:-1])
    дубли = {r["id"] for r in уборка["дубль пары"]}

    к_суду: list = []
    for r in rows:
        if r["id"] in дубли:
            continue
        матч = когда(r)
        if r["domain"] and (not r["enabled"]
                            or r["status"] in ("parked", "deferred", "closed")):
            уборка["сайт снят"].append(r)
        elif матч and матч < порог:
            уборка["прошло"].append(r)
        else:
            q = Question.parse(r["raw_value"], r["suggestion"])
            q.league = q.league or лиги_пары.get(
                dictionary.norm_pair(r["raw_value"]), "")
            к_суду.append((r, q))

    ответы = settle(conn, judge, к_суду, apply=False)
    программа = [(r, a) for r, a in ответы if a.letter]
    # Обе команды пары известны в одном виде спорта (не сборные: у сборных
    # за одним именем разные виды) — ответ. Одна сторона или ни одной —
    # только ПОХОЖЕ, решает владелец: футбольный «Balkan Botevgrad» и
    # баскетбольный «Balkan» — разные клубы одного города (#4335/#4336)
    по_командам: list = []
    примета: dict[int, str] = {}
    for r, a in ответы:
        if a.letter:
            continue
        стороны = [x.strip() for x in re.split(
            r" - | — ", dictionary.norm_pair(r["raw_value"])) if x.strip()]
        if len(стороны) != 2:
            continue
        буквы = {команды.get((names.readings(x) or ("",))[0]) for x in стороны}
        известные = {b for b in буквы if b}
        клубы = not any(names.is_country(x) for x in стороны)
        if len(буквы) == 1 and None not in буквы and клубы:
            по_командам.append((r, next(iter(буквы))))
        elif len(известные) == 1 and клубы:
            примета[r["id"]] = "знакома одна сторона"
        elif not известные:
            примета[r["id"]] = "ни одна команда не знакома"
    по_командам_ids = {r["id"] for r, _ in по_командам}

    всего = (sum(len(v) for v in уборка.values()) + len(программа)
             + len(по_командам))
    print(f"в очереди «sport»: {len(rows)}; можно закрыть: {всего}")
    for имя, куча in уборка.items():
        print(f"   {имя}: {len(куча)}")
        for r in куча[:3]:
            print(f"      #{r['id']} {r['raw_value'][:64]}")
    print(f"   ответила программа: {len(программа)}")
    for r, a in программа:
        print(f"      #{r['id']} {r['raw_value'][:56]} → {a.plain} [{a.rule}]")
    print(f"   обе команды известны: {len(по_командам)}")
    for r, буква in по_командам:
        print(f"      #{r['id']} {r['raw_value'][:56]} → {буква}")
    оставлено = [r for r, a in ответы
                 if not a.letter and r["id"] not in по_командам_ids]
    print(f"   остаётся владельцу (НЕ закрываем): {len(оставлено)}")
    for r in оставлено:
        мета = f" ({примета[r['id']]})" if r["id"] in примета else ""
        print(f"      #{r['id']} {r['raw_value'][:64]}{мета}")
    if not всего:
        return 0
    if not apply:
        print("\nчтобы закрыть — добавьте --apply")
        return 0
    # закрытое уборкой — поимённо, по номеру записи: `dictionary.skip`
    # закрыл бы всю пару, а у дубля живая копия остаётся
    conn.executemany(
        "UPDATE moderation SET status = 'skipped', answered_by = ? "
        "WHERE id = ?", [(УБОРКА.format(имя), r["id"])
                         for имя, куча in уборка.items() for r in куча])
    conn.commit()
    # ответы программы — тем же путём, что кнопки админки
    решённые = {r["id"] for r, _ in программа}
    settle(conn, judge, [(r, q) for r, q in к_суду if r["id"] in решённые],
           apply=True)
    # обе команды известны — ответ видом спорта, как кнопкой
    for r, буква in по_командам:
        dictionary.resolve(conn, r["id"], буква, answered_by=(
            "ответила программа: обе команды известны — "
            f"{SPORT_WORDS.get(буква, буква)}"))
    watch.note(conn, f"очередь «Названия» (вид спорта): закрыто {всего} ("
                     + "; ".join(f"{имя}: {len(куча)}"
                                 for имя, куча in уборка.items() if куча)
                     + f"; ответила программа: {len(программа)}"
                     + f"; обе команды известны: {len(по_командам)}"
                     + ") — ответы с пометкой, отсеянное во вкладке "
                       "«Отсеянные», кнопка «Вернуть»", who="автомат")
    осталось = conn.execute(
        "SELECT COUNT(*) FROM moderation WHERE kind = 'sport' "
        "AND status IN ('open', 'later')").fetchone()[0]
    print(f"закрыто записей: {всего}; осталось: {осталось}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kind", default="sport",
                    help="какой раздел очереди: sport (по умолчанию) или team")
    ap.add_argument("--days", type=int, default=ЖИВЁТ_ДНЕЙ,
                    help="сколько дней после матча запись ещё нужна")
    ap.add_argument("--apply", action="store_true", help="без него — показ")
    args = ap.parse_args()

    conn = db.connect()
    try:
        db.init_db(conn)                     # досыпает свежие колонки
        if args.kind == "team":
            return review_teams(conn, args.apply)
        return review_sport(conn, args.apply, args.days)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

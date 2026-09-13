# -*- coding: utf-8 -*-
r"""Проверка склейки игр — по сохранённому отчёту, без выхода в сеть.

Два режима:

    venv\Scripts\python.exe scripts/merge_report.py
        читает `results/matches.md` и показывает, что склеилось, что нет и
        какие пары застряли у порога (кандидаты в `data/aliases.json`);

    venv\Scripts\python.exe scripts/merge_report.py --scale
        считает похожесть на списке пар, про которые ответ известен заранее:
        сверху заведомо ОДНА команда, снизу заведомо РАЗНЫЕ.

Второй режим обязателен после каждой правки `data/aliases.json`. Проверять
порог только на «своих» парах нельзя: так уже был пропущен случай, когда
`Манчестер Юнайтед` и `Манчестер Сити` совпадали на 100 (см. `ГРАБЛИ.md`).
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary, merge, names                # noqa: E402

DEFAULT_MD = ROOT / "results" / "matches.md"
YEAR_FALLBACK = datetime.now().year

# Таблица «Строки по сайтам». Колонка с лигой появилась позже, поэтому она
# необязательная: старые отчёты должны читаться так же.
ROW_RE = re.compile(
    r"^\|\s*(?P<day>\d{2})\.(?P<mon>\d{2})\s+(?P<hh>\d{2}):(?P<mm>\d{2})\s*"
    r"\|\s*(?P<site>[^|]+?)\s*\|\s*(?P<channel>[^|]+?)\s*\|\s*(?P<match>[^|]+?)\s*"
    r"(?:\|\s*(?P<league>[^|]*?)\s*)?\|\s*$")
SPLIT_RE = re.compile(r"\s+[-–—]\s+")

# Пары с известным ответом. Верхняя половина — одна команда, нижняя — разные.
# Пополнять при каждом новом случае из жизни.
KNOWN_SAME = [
    ("Aberdeen FC", "ABERDEEN"),
    ("Chelsea FC", "Челси"),
    ("SC Freiburg", "Фрайбург"),
    ("FC Kaiserslautern", "Кайзерслаутерн"),
    ("Manchester United FC", "Манчестър Юнайтед"),
    ("Stade Rennais FC", "RENNES"),
    ("Olympique Marsylia", "MARSELHA"),
    ("SSC Napoli", "NÁPOLES"),
    ("Inter Mediolan", "INTER DE MILÃO"),
    ("Le Mans FC", "Льо Ман"),
    ("Werder Brema", "Вердер Бремен"),
    ("FC St. Pauli", "Санкт Паули"),
    # контрольный матч проекта — пример из ТЗ разд. 8
    ("Middlesbrough FC", "Мидълзбро"),
    ("West Bromwich Albion", "Уест Бромич Албиън"),
    ("Sunderland", "Съндърланд"),
    ("Fulham", "Фулъм"),
    ("Leeds United", "Лийдс Юнайтед"),
    ("Olympique Lyon", "Лион"),
    ("Le Havre AC", "Льо Авър"),
]
KNOWN_DIFFERENT = [
    ("Manchester United FC", "Manchester City FC"),
    ("Real Madryt CF", "Real Sociedad"),
    ("AC Sparta Praga", "SK Slavia Praga"),
    ("Ботев Пловдив", "Ботев Враца"),
    ("SL Benfica", "SL Benfica B"),
    ("Arsenal FC", "Aston Villa FC"),
    ("Levski W", "Levski"),
    ("Спартак Варна", "Спартак Плевен"),
    ("Atalanta BC", "Atletico Madrid"),
]


def read_entries(path: Path) -> list[merge.Entry]:
    """Строки сайтов из markdown-отчёта. Годится и старый формат (одна
    таблица), и новый (таблица «Строки по сайтам»)."""
    out: list[merge.Entry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = ROW_RE.match(line)
        if not m or m.group("site") in ("Сайт", "---"):
            continue
        pair = SPLIT_RE.split(m.group("match"))
        if len(pair) != 2:
            continue
        out.append(merge.Entry(
            source=m.group("site"), channel=m.group("channel"),
            home=pair[0].strip(), away=pair[1].strip(),
            league=(m.group("league") or "").strip(),
            start=datetime(YEAR_FALLBACK, int(m.group("mon")), int(m.group("day")),
                           int(m.group("hh")), int(m.group("mm")))))
    return out


def show_scale() -> int:
    """Похожесть на парах с известным ответом. Возвращает число ошибок."""
    bad = 0
    print(f"порог: {names.SIMILAR_ENOUGH}\n")
    for title, pairs, expect in (("ОДНА команда", KNOWN_SAME, True),
                                 ("РАЗНЫЕ команды", KNOWN_DIFFERENT, False)):
        print(f"=== {title} ===")
        for a, b in pairs:
            score = names.similarity(a, b)
            wall = names.category(a) != names.category(b)
            verdict = names.same_team(a, b)
            note = "  (стена: пол/возраст/состав)" if wall else ""
            flag = "" if verdict == expect else "   <-- ОШИБКА"
            bad += 0 if verdict == expect else 1
            print(f"  {score:3}  {a:24} {b:22}{note}{flag}")
        print()
    print("ошибок нет" if not bad else f"ОШИБОК: {bad}")
    return bad


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default=str(DEFAULT_MD))
    ap.add_argument("--scale", action="store_true",
                    help="проверить пары с известным ответом")
    ap.add_argument("--threshold", type=int, default=names.SIMILAR_ENOUGH)
    ap.add_argument("--no-db", action="store_true",
                    help="без подтверждённых имён из базы — видно, что даёт "
                         "один только словарь слов")
    args = ap.parse_args()

    # Подтверждённые владельцем имена сильнее любых догадок по буквам, и
    # проверять склейку без них — значит проверять не то, что работает.
    if not args.no_db:
        conn = db.connect()
        try:
            names.set_overrides(dictionary.team_overrides(conn))
        finally:
            conn.close()

    if args.scale:
        return 1 if show_scale() else 0

    path = Path(args.md)
    if not path.exists():
        print(f"нет файла {path} — сначала обход или укажите --md")
        return 1

    entries = read_entries(path)
    games = merge.merge(entries, args.threshold)
    merged = [g for g in games if len(g.entries) > 1]
    print(f"строк с сайтов: {len(entries)}")
    print(f"игр после склейки: {len(games)} (порог {args.threshold}, "
          f"окно ±{merge.WINDOW_MINUTES} мин)")
    print(f"склеено групп: {len(merged)}\n")

    for g in merged:
        print(f"{g.start:%d.%m %H:%M}  {g.home} — {g.away}   [{', '.join(g.sources)}]")
        for e in sorted(g.entries, key=lambda x: x.start):
            print(f"    {e.start:%H:%M}  {e.source:12} {e.channel:24} "
                  f"{e.home} — {e.away}")
        print(f"    каналы: {', '.join(g.channels)}")

    # Пары, не дотянувшие до порога: их разбирают и, если это одна игра,
    # добавляют слово в `data/aliases.json`.
    near = []
    for i, a in enumerate(entries):
        for b in entries[i + 1:]:
            if abs((a.start - b.start).total_seconds()) > merge.WINDOW_MINUTES * 60:
                continue
            score = min(names.similarity(a.home, b.home),
                        names.similarity(a.away, b.away))
            if args.threshold - 20 <= score < args.threshold:
                near.append((score, a, b))
    if near:
        print("\n=== у порога — проверить и, если одна игра, дополнить "
              "data/aliases.json ===")
        for score, a, b in sorted(near, key=lambda x: -x[0]):
            print(f"  {score:3}  {a.home} — {a.away}  [{a.source}]")
            print(f"       {b.home} — {b.away}  [{b.source}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

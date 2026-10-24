# -*- coding: utf-8 -*-
r"""Проверка перед выкладкой узнаёт игру, которой новый код дописал метку
пола/возраста из эталона (24.10.2026, довыкладка правила 5 `confirm`).

Сравнение старого и нового разбора на GitHub сочло WNBA «Golden State
Valkyries — Atlanta Dream» 02:00 «пропавшей», когда новый код дал
«Golden State Valkyries W — Atlanta Dream W» 01:55 (время эталона):
`proverka._same_pair` сравнивал пары через `canon._pair_score`, где
«W» ≠ «без метки» → 0. Правила `_same_pair`:
 1. Пары сходятся как раньше — та же игра.
 2. У одной игры меток нет вовсе, у другой одна и та же у обеих команд —
    сравниваем без меток (в обе стороны).
 3. Метки у обеих игр разные, или у одной из сторон только у одной
    команды — как раньше: разные игры.
`twin` на таких парах даёт «имя» (то же время) или «время» (сдвиг ≤ 3 ч
ближе к эталону).

Запуск: python scripts/test_proverka_metki.py — в сеть не ходит.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

spec = importlib.util.spec_from_file_location("proverka", ROOT / "scripts" / "proverka.py")
proverka = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proverka)

passed, failed = 0, []


def check(name: str, cond: bool, extra="") -> None:
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def game(home: str, away: str, start: str, chans=()) -> dict:
    return {"home": home, "away": away, "start_kyiv": start, "sport": "B",
            "entries": [{"source": s, "channel": c} for c, s in chans]}


def main() -> int:
    same = proverka._same_pair
    old = game("Golden State Valkyries", "Atlanta Dream", "2026-10-27T02:00")
    new = game("Golden State Valkyries W", "Atlanta Dream W", "2026-10-27T01:55")
    print("1–2. метка из эталона у обеих команд")
    check("без меток ↔ W у обеих — та же игра", same(old, new))
    check("и в обратную сторону", same(new, old))
    check("без меток ↔ U19 у обеих — та же игра",
          same(game("Man City", "Psg", "2026-10-14T17:00"),
               game("Manchester City U19", "Paris Saint-Germain U19", "2026-10-14T16:55")))
    check("как раньше: одинаковые имена сходятся", same(old, old))
    print("3. стена остаётся, где метки есть у обеих")
    check("W у обеих ↔ U19 у обеих — разные игры",
          not same(new, game("Golden State Valkyries U19", "Atlanta Dream U19", "2026-10-27T01:55")))
    check("метка только у одной команды — разные игры",
          not same(old, game("Golden State Valkyries W", "Atlanta Dream", "2026-10-27T01:55")))
    check("другие команды — разные игры",
          not same(old, game("Las Vegas Aces W", "Atlanta Dream W", "2026-10-27T01:55")))

    print("4. twin: пропавшая игра находится среди новых")
    refs = [{"home": "Golden State Valkyries W", "away": "Atlanta Dream W",
             "start_kyiv": "2026-10-27T01:55"}]
    found, how = proverka.twin(old, [new], refs)
    check("сдвиг 02:00 → 01:55 в допуске 10 мин — «имя»", found is new and how == "имя",
          (found is new, how))
    far = game("Golden State Valkyries", "Atlanta Dream", "2026-10-27T02:30")
    found, how = proverka.twin(far, [new], refs)
    check("сдвиг 02:30 → 01:55 ближе к эталону — «время»", found is new and how == "время",
          (found is new, how))
    found, how = proverka.twin(game("Ζρίνσκι", "ΠΑΟΚ", "2026-10-28T17:00"),
                               [game("Ζρίνσκι U19", "ΠΑΟΚ U19", "2026-10-28T17:00")], [])
    check("то же время — «имя»", found is not None and how == "имя", how)
    found, how = proverka.twin(old, [game("Las Vegas Aces W", "Atlanta Dream W",
                                          "2026-10-27T01:55")], refs)
    check("другая пара — не находится", found is None, how)

    print(f"\nПроверок: {passed + len(failed)}, провалов: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

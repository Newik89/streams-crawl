# -*- coding: utf-8 -*-
r"""Книга 134 (15.11.2026): файл папки `data/`, который читает код, должен
ехать на GitHub и сервер.

Грабля 13.11: `.gitignore` закрывает `data/*` целиком, наружу едут только
файлы, названные строкой `!data/имя`. Новый справочник `sport_grid.json`
без такой строки молча не уехал: локально всё зелёное, а на GitHub и сервере
файла нет. Тогда проверку вписали в тест одного этого файла; этот тест —
общий, на все файлы сразу.

Правила:
  1. Что читает код: имена из `"data" / "имя"` и из путей `data/имя.json`
     (а также .txt, .csv, .db) во всех файлах `app/` и `scripts/`, кроме
     самих тестов.
  2. Каждое такое имя должно быть открыто строкой `!data/имя` в `.gitignore`…
  3. …либо стоять в списке `ТОЛЬКО_ЗДЕСЬ` с причиной, почему файл наружу не
     едет. Новый файл в этот список — осознанное решение, не привычка.
  4. Открытый в `.gitignore` файл должен лежать в репозитории (иначе строка
     есть, а файла нет — то же молчаливое расхождение).

Запуск: python scripts/test_data_otkryty.py — в сеть не ходит.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8")

#: правило 3: что из `data/` наружу не едет — и почему
ТОЛЬКО_ЗДЕСЬ = {
    "channel_schedule.db": "база — живёт на сервере и на компьютере, в git не ездит",
    "pages": "кэш скачанных страниц",
    "readers.json": "старое имя в справке check_readers.py; файл читается из results/readers.json",
}
_USED = re.compile(r'"data"\s*/\s*"([^"]+)"|[\'"`/ ]data/([A-Za-z0-9_.-]+\.(?:json|txt|csv|db))')

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def used(root: Path) -> dict[str, list[str]]:
    """Правило 1: {имя файла data: где упомянут}."""
    out: dict[str, list[str]] = {}
    files = list((root / "app").rglob("*.py")) + list((root / "scripts").glob("*.py"))
    for path in files:
        if path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for found in _USED.finditer(text):
            name = found.group(1) or found.group(2)
            out.setdefault(name, []).append(path.relative_to(root).as_posix())
    return out


def opened(root: Path) -> set[str]:
    """Правило 2: имена, открытые строкой `!data/имя` в `.gitignore`."""
    text = (root / ".gitignore").read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^!data/(\S+)\s*$", text, re.M)}


def closed(names: dict, opened_names: set, local: dict) -> list[str]:
    """Правила 2–3: файлы, которые код читает, а наружу они не едут."""
    return sorted(n for n in names if n not in opened_names and n not in local)


читает, открыты = used(ROOT), opened(ROOT)
print("Правила 1–3. Каждый файл data, который читает код, открыт в .gitignore или объяснён")
проверка("код вообще что-то читает из data (поиск имён работает)",
         {"markers.json", "dictionaries.json", "sport_grid.json"} <= set(читает))
проверка("закрытых файлов, которые читает код, нет",
         [(n, читает[n][:2]) for n in closed(читает, открыты, ТОЛЬКО_ЗДЕСЬ)], [])
проверка("в списке «только здесь» нет лишнего: каждый файл из него код действительно упоминает",
         sorted(n for n in ТОЛЬКО_ЗДЕСЬ if n not in читает), [])

print("Правило 4. Открытый файл лежит в репозитории")
в_git = set(subprocess.run(["git", "ls-files", "data"], cwd=str(ROOT), capture_output=True,
                           text=True, encoding="utf-8").stdout.split())
проверка("каждый открытый в .gitignore файл data есть в git",
         sorted(n for n in открыты if f"data/{n}" not in в_git), [])

print("Сторож ловит то, ради чего написан")
проверка("новый справочник без строки в .gitignore — пойман",
         closed({"novyy_spravochnik.json": ["app/x.py"], "markers.json": ["app/live.py"]},
                {"markers.json"}, ТОЛЬКО_ЗДЕСЬ), ["novyy_spravochnik.json"])
проверка("поиск видит обе записи пути: через «/» и строкой",
         sorted({(m.group(1) or m.group(2)) for m in _USED.finditer(
             'P = ROOT / "data" / "a.json"\nQ = "data/b.json"\nW = open("results/c.json")')}),
         ["a.json", "b.json"])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

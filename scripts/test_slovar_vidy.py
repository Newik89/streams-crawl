# -*- coding: utf-8 -*-
r"""Книга 097 (08.11.2026): подсказки видов спорта команд (`team_sports` в
data/dictionaries.json) не забываются с суточной текучкой событий.

Повод: автокоммит словаря 65591b8 (dict_push 16:00) выбросил из team_sports
107 команд, чьи матчи уже прошли и ушли из базы; проверка main #144
покраснела: «ПРОПАЛА 08.11 07:45 FCSB — Corvinul [Prima Sport 3/primaplay.ro]»
— сайт без вида спорта читается только по подсказке. Код не менялся, менялся
только словарь. Все прежние автокоммиты (#89–#139) были зелёными случайно.

Правила (`scripts/dict_sync.merge_team_sports`, `previous_team_sports`):
  В1. Команда есть в базе с одним видом → этот вид (поверх памяти).
  В2. Команды в базе уже нет, но она была в прежнем файле → вид из памяти.
  В3. У команды в базе два вида → её нет ни в выдаче, ни в памяти.
  В4. Пустой вид и не-строки в памяти — не подсказки.
  В5. Прежнего файла нет или он битый → память пустая, выгрузка не падает.
  В6. Выдача отсортирована по имени (стабильный diff в git).

Запуск: venv\Scripts\python.exe scripts\test_slovar_vidy.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import dict_sync  # noqa: E402

total = green = 0


def check(name: str, ok: bool, got=None) -> None:
    global total, green
    total += 1
    green += bool(ok)
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"   ← {got!r}"))


prev = {"Corvinul": "F", "FCSB": "F", "Barcelona": "F", "Старая": "B", "Пустая": "", "Кривая": 7}
виды = {"FCSB": {"F"}, "Barcelona": {"F", "B"}, "Новая": {"T"}, "Без вида": {""}, "Сменила": {"H"}}
prev_clean = {"Corvinul": "F", "FCSB": "F", "Barcelona": "F", "Старая": "B", "Сменила": "F"}
out = dict_sync.merge_team_sports(prev_clean, виды)

print("В1. команда в базе с одним видом → вид из базы")
check("FCSB → F", out.get("FCSB") == "F", out)
check("Новая (её нет в памяти) → T", out.get("Новая") == "T", out)
check("Сменила вид (в памяти F, в базе H) → H, база главнее", out.get("Сменила") == "H", out)
print("В2. команды в базе нет, но она в памяти → вид из памяти")
check("Corvinul → F из прежнего файла", out.get("Corvinul") == "F", out)
check("Старая → B из прежнего файла", out.get("Старая") == "B", out)
print("В3. два вида в базе → выброшена и из памяти")
check("Barcelona (F и B) → нет", "Barcelona" not in out, out)
print("В4. пустой вид — не подсказка")
check("«Без вида» → нет", "Без вида" not in out, out)
tmp = Path(tempfile.mkdtemp(prefix="slovar-vidy-"))
f = tmp / "dictionaries.json"
f.write_text(json.dumps({"team_sports": prev}, ensure_ascii=False), encoding="utf-8")
mem = dict_sync.previous_team_sports(f)
check("память из файла: пустая строка и число отброшены", mem == {"Corvinul": "F", "FCSB": "F", "Barcelona": "F", "Старая": "B"}, mem)
print("В5. файла нет или битый → память пустая")
check("нет файла → {}", dict_sync.previous_team_sports(tmp / "net.json") == {})
(tmp / "bitый.json").write_text("{не json", encoding="utf-8")
check("битый файл → {}", dict_sync.previous_team_sports(tmp / "bitый.json") == {})
check("файл без team_sports → {}", (lambda p: (p.write_text("{}", encoding="utf-8"), dict_sync.previous_team_sports(p))[1])(tmp / "pusto.json") == {})
print("В6. выдача отсортирована")
check("ключи по алфавиту", list(out) == sorted(out), list(out))
print("Сценарий 08.11: матч FCSB — Corvinul прошёл, команд в событиях нет")
after = dict_sync.merge_team_sports(out, {"Другая": {"F"}})
check("Corvinul и FCSB остались футбольными", after.get("Corvinul") == "F" and after.get("FCSB") == "F", after)

print()
print(f"проверок: {total}, зелёных: {green}, красных: {total - green}")
sys.exit(0 if green == total else 1)

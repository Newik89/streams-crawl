# -*- coding: utf-8 -*-
r"""Сторож «страны в словаре команд» и правило С13 (книга 110, аудит 13.11.2026).

Повод: сверка копии живого словаря 13.11 — 14 написаний стран за чужой
сборной (С12 их не читает), 3 «та же страна, чужая пометка» («Аргентина
U20» за Argentina U20 W — словарь ЧИТАЛ, мужская игра могла получить женскую
сборную), 32 «страна за клубом» и 8 клубов-тёзок стран. Сторожа не было.

Что сторожится:

1. С13: запись «страна с чужой пометкой» словарь не читает; верные записи
   той же сборной — читает; в базе запись остаётся;
2. сторож (`scripts/slovar_strany.py`) раскладывает записи по четырём
   классам А–Г;
3. первый запуск сторожа только запоминает; новая запись — строка в
   «Прогоны»; повторный запуск молчит.

В сеть не ходит, база — временная:

    python scripts/test_slovar_strany.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="slovar-strany-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")

from app import db, dictionary          # noqa: E402
import slovar_strany                    # noqa: E402

passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


conn = db.connect()
db.init_db(conn)


def team(name: str) -> int:
    slug = name.lower().replace(" ", "-")
    conn.execute("INSERT INTO teams (canonical_name, slug) VALUES (?, ?)",
                 (name, slug))
    return conn.execute("SELECT id FROM teams WHERE slug = ?",
                        (slug,)).fetchone()[0]


def alias(text: str, team_id: int, lang: str | None = None) -> None:
    """Запись словаря как есть — в обход правил записи: так лежат старые
    ошибки живой базы."""
    conn.execute("INSERT INTO team_aliases (team_id, alias, lang) "
                 "VALUES (?, ?, ?)", (team_id, text, lang))
    conn.commit()


T = {name: team(name) for name in (
    "Argentina U20", "Argentina U20 W", "Czech Republic", "Czech Republic W",
    "Ireland", "Iceland", "Niger", "Niger Tornadoes", "Brasilia", "Arsenal")}
alias("Аргентина U20", T["Argentina U20 W"])          # Б: чужая пометка
alias("Аргентина U20 (Ж)", T["Argentina U20 W"], "ru")  # верная
alias("Češka", T["Czech Republic W"])                 # Б
alias("Češka Ž", T["Czech Republic W"], "hr")         # верная
alias("Česko", T["Czech Republic"], "cs")             # верная
alias("Island", T["Ireland"])                         # А: чужая сборная
alias("Island", T["Iceland"], "cs")                   # верная
alias("Niger", T["Niger Tornadoes"], "pl")            # В: страна за клубом
alias("Arsenal FC", T["Arsenal"])                     # обычный клуб


def читает(написание: str) -> list[str]:
    вердикт, команды = dictionary.TeamNames(conn).decide(написание)
    return sorted(dictionary.TeamNames(conn).canon_of[t] for t in команды) \
        if вердикт == dictionary.DECIDED else [вердикт]


print("1. С13: страна с чужой пометкой — словарь не читает")
check("«Аргентина U20» за Argentina U20 W не читается",
      читает("Аргентина U20") != ["Argentina U20 W"], читает("Аргентина U20"))
check("«Аргентина U20 (Ж)» → Argentina U20 W — читается",
      читает("Аргентина U20 (Ж)") == ["Argentina U20 W"],
      читает("Аргентина U20 (Ж)"))
check("«Češka» за Czech Republic W не читается",
      читает("Češka") != ["Czech Republic W"], читает("Češka"))
check("«Češka Ž» → Czech Republic W — читается",
      читает("Češka Ž") == ["Czech Republic W"], читает("Češka Ž"))
check("«Česko» → Czech Republic — читается",
      читает("Česko") == ["Czech Republic"], читает("Česko"))
check("клуб читается как раньше: «Arsenal FC» → Arsenal",
      читает("Arsenal FC") == ["Arsenal"], читает("Arsenal FC"))
check("запись в базе остаётся (ничего не удалено)",
      conn.execute("SELECT COUNT(*) FROM team_aliases WHERE alias = "
                   "'Аргентина U20'").fetchone()[0] == 1)
check("`wrong_mark`: написания нет в справочнике буква в букву — не трогаем",
      not dictionary.wrong_mark("Arg. U20", "Argentina U20 W"))

print("2. Сторож раскладывает записи по классам")
отчёт = slovar_strany.collect(conn)
check("А: страна за чужой сборной — «Island» → Ireland",
      отчёт["А"] == [("Island", "Ireland")], отчёт["А"])
check("Б: чужая пометка — «Češka» и «Аргентина U20»",
      отчёт["Б"] == [("Češka", "Czech Republic W"),
                     ("Аргентина U20", "Argentina U20 W")], отчёт["Б"])
check("В: страна за клубом — «Niger» → Niger Tornadoes",
      отчёт["В"] == [("Niger", "Niger Tornadoes")], отчёт["В"])
check("Г: клуб-тёзка — «Brasilia» (по-фински Бразилия)",
      отчёт["Г"] == [("Brasilia", "BRAZIL")], отчёт["Г"])
check("верные записи и обычные клубы в отчёт не попали",
      not any("Arsenal" in a or a in ("Česko", "Češka Ž")
              for rows in отчёт.values() for a, _ in rows))


def строк_в_прогонах() -> int:
    return conn.execute("SELECT COUNT(*) FROM runs WHERE log LIKE "
                        "'%словарь и страны%'").fetchone()[0]


print("3. Сторож помнит виденное и говорит только о новом")
новые = slovar_strany.note_new(conn, отчёт)
check("первый запуск только запоминает", новые == [] and строк_в_прогонах() == 0,
      (новые, строк_в_прогонах()))
T["Kosova"] = team("Kosova")
conn.commit()
новые = slovar_strany.note_new(conn, slovar_strany.collect(conn))
check("новый клуб-тёзка «Kosova» — одна строка в «Прогоны»",
      len(новые) == 1 and "Kosova" in новые[0] and строк_в_прогонах() == 1,
      (новые, строк_в_прогонах()))
новые = slovar_strany.note_new(conn, slovar_strany.collect(conn))
check("повторный запуск молчит", новые == [] and строк_в_прогонах() == 1,
      (новые, строк_в_прогонах()))

conn.close()
print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, "
      f"красных: {len(failed)}")
sys.exit(1 if failed else 0)

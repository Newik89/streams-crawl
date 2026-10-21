# -*- coding: utf-8 -*-
"""Код в ночную копию (`scripts/code_copy.py`): правила 1–6 по очереди.

«GitHub» и репо копий — локальные папки во временной директории, в сеть не
ходит. Нужна программа git. Запуск:

    venv\\Scripts\\python.exe scripts/test_code_copy.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import code_copy  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="code-copy-"))
зелёных = красных = 0


def проверка(имя, вышло, ждём):
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✗ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def g(папка: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(папка), "-c", "user.name=t", "-c", "user.email=t@t",
                        "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def исходник(имя: str) -> Path:
    п = TMP / имя
    п.mkdir()
    g(п, "init", "-q", "-b", "main")
    коммит(п, "первый")
    return п


def коммит(п: Path, слово: str) -> str:
    (п / "f.txt").write_text(слово, encoding="utf-8")
    g(п, "add", "f.txt")
    g(п, "commit", "-q", "-m", слово)
    return g(п, "rev-parse", "HEAD")


def в_копии(копия: Path, ref: str) -> str:
    r = subprocess.run(["git", "-C", str(копия), "rev-parse", "-q", "--verify", ref],
                       capture_output=True, text=True)
    return r.stdout.strip()


def ночь(копия: Path, *repos: tuple[str, Path]) -> list[str]:
    return code_copy.run(TMP / "box.git", str(копия), "",
                         [(имя, str(п), "") for имя, п in repos])


def main() -> int:
    движок, кухня = исходник("engine"), исходник("kitchen")
    g(движок, "tag", "prod-1")
    g(движок, "branch", "vetka")
    копия = TMP / "backup.git"
    g(TMP, "init", "-q", "--bare", str(копия))

    print("правило 1: первая ночь — код ложится ссылками refs/kod/<имя>/")
    m1 = g(движок, "rev-parse", "HEAD")
    проверка("провалов нет", ночь(копия, ("streams-crawl", движок), ("streams-schedule", кухня)), [])
    проверка("main движка", в_копии(копия, "refs/kod/streams-crawl/heads/main"), m1)
    проверка("ветка движка", в_копии(копия, "refs/kod/streams-crawl/heads/vetka"), m1)
    проверка("метка движка", в_копии(копия, "refs/kod/streams-crawl/tags/prod-1"), m1)
    проверка("main кухни", в_копии(копия, "refs/kod/streams-schedule/heads/main"),
             g(кухня, "rev-parse", "HEAD"))
    проверка("прошлой ночи ещё нет", в_копии(копия, "refs/kod-previous/streams-crawl/heads/main"), "")
    проверка("ветка main копии данных не тронута", в_копии(копия, "refs/heads/main"), "")

    print("правило 2: вторая ночь — прежнее уезжает в refs/kod-previous/")
    m2 = коммит(движок, "второй")
    проверка("провалов нет", ночь(копия, ("streams-crawl", движок)), [])
    проверка("эта ночь", в_копии(копия, "refs/kod/streams-crawl/heads/main"), m2)
    проверка("прошлая ночь", в_копии(копия, "refs/kod-previous/streams-crawl/heads/main"), m1)
    проверка("кухня не звана — её копия на месте",
             в_копии(копия, "refs/kod/streams-schedule/heads/main"), g(кухня, "rev-parse", "HEAD"))

    print("правило 4: удалённая на GitHub ветка в копии остаётся")
    g(движок, "branch", "-D", "vetka")
    m3 = коммит(движок, "третий")
    проверка("провалов нет", ночь(копия, ("streams-crawl", движок)), [])
    проверка("ветка цела", в_копии(копия, "refs/kod/streams-crawl/heads/vetka"), m1)
    проверка("main свежий", в_копии(копия, "refs/kod/streams-crawl/heads/main"), m3)

    print("правило 3: переписанная история main — копия не тронута")
    g(движок, "reset", "-q", "--hard", m1)
    чужой = коммит(движок, "переписано")
    итог = ночь(копия, ("streams-crawl", движок))
    проверка("один провал", len(итог), 1)
    проверка("причина — история переписана", "переписана" in (итог or [""])[0], True)
    проверка("эта ночь прежняя", в_копии(копия, "refs/kod/streams-crawl/heads/main"), m3)
    проверка("прошлая ночь прежняя", в_копии(копия, "refs/kod-previous/streams-crawl/heads/main"), m2)
    проверка("чужого коммита в копии нет", в_копии(копия, f"{чужой}^{{commit}}"), "")
    g(движок, "reset", "-q", "--hard", m3)

    print("правило 3: на GitHub нет main — копия не тронута")
    g(движок, "branch", "-m", "main", "drugaya")
    итог = ночь(копия, ("streams-crawl", движок))
    проверка("причина — нет main", "нет ветки main" in (итог or [""])[0], True)
    проверка("копия прежняя", в_копии(копия, "refs/kod/streams-crawl/heads/main"), m3)
    g(движок, "branch", "-m", "drugaya", "main")

    print("правило 5: один репо не скачался — второй всё равно едет")
    k2 = коммит(кухня, "кухня два")
    итог = ночь(копия, ("streams-crawl", TMP / "net-takogo"), ("streams-schedule", кухня))
    проверка("один провал", len(итог), 1)
    проверка("провал — у пропавшего репо", "не скачался" in (итог or [""])[0], True)
    проверка("кухня доехала", в_копии(копия, "refs/kod/streams-schedule/heads/main"), k2)
    проверка("движок прежний", в_копии(копия, "refs/kod/streams-crawl/heads/main"), m3)

    print("правило 5: репо копий не читается — ничего не трогаем")
    итог = ночь(TMP / "net-kopii", ("streams-crawl", движок))
    проверка("провал про репо копий", "репо копий не читается" in (итог or [""])[0], True)

    print("восстановление: из копии поднимается репо со всеми ветками и метками")
    новый = TMP / "restored.git"
    g(TMP, "init", "-q", "--bare", str(новый))
    g(новый, "fetch", "-q", str(копия), "+refs/kod/streams-crawl/heads/*:refs/heads/*",
      "+refs/kod/streams-crawl/tags/*:refs/tags/*")
    проверка("main поднят", в_копии(новый, "refs/heads/main"), m3)
    проверка("метка поднята", в_копии(новый, "refs/tags/prod-1"), m1)
    проверка("файл на месте", g(новый, "show", "main:f.txt"), "третий")

    print(f"\nзелёных {зелёных}, красных {красных}")
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if красных else 0


if __name__ == "__main__":
    sys.exit(main())

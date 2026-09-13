# -*- coding: utf-8 -*-
"""AI-самопочинка несложных поломок разметки (этап 6д, слой 2).

Работает на **бесплатной** модели — решение владельца 02.09: бесплатный слой
чинит простое сразу, подключение Claude API для сложных случаев — в конце
проекта. GitHub Models закрылся 30.07.2026, поэтому провайдер настраивается
переменными (`ai_fallback.py`, шапка): по умолчанию бесплатный тариф Google
AI Studio, ключ — секрет репозитория `STREAMS_AI_KEY`.

Порядок:
  1. кандидаты — из `ai_fallback.detect()`: страница живая, парсер дал 0 строк;
  2. модели отдаются исходник парсера и кусок свежей страницы, ответ —
     исправленный файл целиком;
  3. проверка БЕЗ сети: файл компилируется, парсер запускается на сохранённой
     странице и должен вернуть строки с парой команд;
  4. зелёно — файл коммитится и пушится (пуш с ребейзом); на сервере его ещё
     раз проверит самопроверка с откатом. Красно — файл возвращается как был;
  5. после удачной починки перегоняется parse_live — строки сайта попадают в
     сегодняшний же games.json.

Запуск:
    python scripts/ai_repair.py --selftest           проверка связи с моделью
    python scripts/ai_repair.py --auto               починить кандидатов (до 2)
    python scripts/ai_repair.py --domain teleman.pl  указать сайт руками
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import ai_fallback  # noqa: E402  (детект и адрес модели — оттуда)

RAW = ROOT / "recon" / "raw_live"
MAX_REPAIRS = 2                      # за прогон: беречь бесплатный лимит

PROMPT = (
    "Ты чинишь парсер телепрограммы на Python. Сайт немного поменял разметку, "
    "и функция parse() стала возвращать пустой список. Ниже исходник модуля и "
    "кусок СВЕЖЕЙ страницы. Найди, что изменилось (селектор, регулярка, "
    "формат ссылки), и поправь МИНИМАЛЬНО: не переписывай модуль заново, "
    "сохрани интерфейс parse(html, *, day, tz, url, channels), комментарии и "
    "стиль. Верни ТОЛЬКО полный исправленный текст файла, без пояснений и "
    "без ограждений ```.")


def _model_call(content: str) -> str:
    token = os.environ.get("AI_API_KEY", "")
    if not token:
        raise RuntimeError("нет AI_API_KEY (секрет STREAMS_AI_KEY)")
    body = json.dumps({
        "model": ai_fallback.MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        ai_fallback.MODELS_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
    with urllib.request.urlopen(req, timeout=180) as resp:
        answer = json.loads(resp.read())
    return answer["choices"][0]["message"]["content"]


def selftest() -> int:
    try:
        reply = _model_call("Ответь ровно одним словом: работает")
    except Exception as e:                               # noqa: BLE001
        print(f"модель недоступна: {type(e).__name__}: {e}")
        return 1
    print(f"модель ответила: {reply.strip()[:60]}")
    return 0


def _page_for(domain: str) -> Path | None:
    """Самая свежая сохранённая страница этого сайта."""
    matches = sorted(
        [p for p in RAW.glob("*.html")
         if p.name.startswith((domain, f"www.{domain}"))],
        key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _snippet(html: str, limit: int = 18000) -> str:
    """Кусок страницы вокруг первой метки времени — там и живёт сетка."""
    m = re.search(r"\b\d{1,2}[:.]\d{2}\b", html)
    if not m:
        return html[:limit]
    start = max(0, m.start() - limit // 3)
    return html[start:start + limit]


def repair(domain: str) -> bool:
    from app import parsers
    fn = parsers.get(domain)
    if fn is None:
        print(f"  {domain}: своего парсера нет — чинить нечего, это к людям")
        return False
    module = sys.modules[fn.__module__]
    path = Path(inspect.getfile(module))
    page = _page_for(domain)
    if page is None:
        print(f"  {domain}: нет сохранённой страницы — не с чем проверять")
        return False

    original = path.read_text(encoding="utf-8")
    html = page.read_text(encoding="utf-8", errors="replace")
    ask = (f"{PROMPT}\n\n===== ФАЙЛ {path.name} =====\n{original}\n\n"
           f"===== КУСОК СТРАНИЦЫ =====\n{_snippet(html)}")
    try:
        fixed = _model_call(ask).strip()
    except Exception as e:                               # noqa: BLE001
        print(f"  {domain}: модель не ответила — {type(e).__name__}: {e}")
        return False
    if fixed.startswith("```"):
        fixed = fixed.strip("`\n")
        fixed = fixed.split("\n", 1)[1] if fixed.startswith("python") else fixed

    # защита от бессмыслицы до записи файла
    if "@register(" not in fixed or "def parse(" not in fixed:
        print(f"  {domain}: ответ модели не похож на парсер — пропуск")
        return False
    try:
        compile(fixed, str(path), "exec")
    except SyntaxError as e:
        print(f"  {domain}: модель вернула битый Python ({e}) — пропуск")
        return False

    path.write_text(fixed, encoding="utf-8")
    try:
        importlib.reload(module)
        fresh = parsers.get(domain)
        if fresh is None:
            raise ValueError("после правки парсер пропал из реестра")
        programs = fresh(html)
        pairs = [p for p in programs
                 if " - " in (p.match_raw or "") or (p.title or "").strip()]
        if not programs or not pairs:
            raise ValueError(f"строк {len(programs)}, осмысленных {len(pairs)}")
    except Exception as e:                               # noqa: BLE001
        path.write_text(original, encoding="utf-8")
        importlib.reload(module)
        print(f"  {domain}: починка не прошла проверку ({e}) — откат")
        return False
    print(f"  {domain}: починено, строк со страницы: {len(programs)}")
    return True


def _git_push(domains: list[str]) -> None:
    """Закоммитить починенные файлы поимённо и запушить с ребейзом."""
    from app import parsers
    files = []
    for d in domains:
        fn = parsers.get(d)
        if fn:
            files.append(str(Path(inspect.getfile(sys.modules[fn.__module__]))
                             .relative_to(ROOT)))
    if not files:
        return
    run = lambda *cmd: subprocess.run(cmd, cwd=ROOT, capture_output=True,  # noqa: E731
                                      text=True)
    run("git", "config", "user.name", "AI-починка парсеров")
    run("git", "config", "user.email", "actions@github.com")
    run("git", "add", *files)
    run("git", "commit", "-m",
        f"AI-починка парсеров: {', '.join(domains)} (проверено на сохранённой странице)")
    for _ in range(3):
        if run("git", "push").returncode == 0:
            print(f"починка запушена: {', '.join(files)}")
            return
        run("git", "pull", "--rebase")
    print("пуш починки не прошёл — файлы остались в рабочей копии прогона")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--auto", action="store_true", help="починить кандидатов")
    ap.add_argument("--domain", default="", help="конкретный сайт")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if os.environ.get("STREAMS_AI", "").lower() != "on":
        print("STREAMS_AI не включён — самопочинка спит")
        return 0

    domains = [args.domain] if args.domain else list(ai_fallback.detect())
    domains = domains[:MAX_REPAIRS]
    if not domains:
        print("кандидатов на починку нет")
        return 0
    repaired = [d for d in domains if repair(d)]
    if not repaired:
        return 1
    if os.environ.get("GITHUB_ACTIONS") == "true":
        _git_push(repaired)
    # перегнать разбор, чтобы строки починенного сайта попали в сегодняшний итог
    subprocess.run([sys.executable, "scripts/parse_live.py", "--days",
                    os.environ.get("AI_DAYS", "2")], cwd=ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

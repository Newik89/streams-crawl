# -*- coding: utf-8 -*-
r"""Провал обхода → issue в репозитории, чтобы владельцу дошло письмо.

GitHub шлёт письмо о красном прогоне только тому, кто его запустил: плановый
и запущенный ботом `queue.yml` (кнопки сайта) — никому. Issue с меткой
`обход-упал` приходит письмом всегда (аудит 07.09, A4). Открытая issue уже
есть — дописываем в неё комментарий, а не плодим новые: провал по два раза в
день неделю подряд — это одна беседа, не четырнадцать.

Запуск (в crawl.yml, шаг `if: failure() || cancelled()`):
    python scripts/crawl_alarm.py --run-url <ссылка на прогон> --mode "<что запускали>"

Ключ — из `GITHUB_TOKEN` (в Actions); локально его отдаёт git, как в
github_run.py. Только стандартная библиотека: шаг должен отработать, даже
если провалился сам `pip install`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

API = "https://api.github.com"
LABEL = "обход-упал"
RAW = ROOT / "recon" / "raw_live"
BROKEN = ("не открылась", "заглушка защиты")


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    from github_run import _token as git_token
    return git_token()


def _slug() -> str:
    slug = os.environ.get("GITHUB_REPOSITORY", "")
    if slug:
        return slug
    from github_run import repo_slug
    return repo_slug()


def call(token: str, method: str, path: str, body: dict | None = None):
    """Один запрос к API GitHub: (код ответа, разобранный JSON или текст)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "streams-schedule"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as answer:
            text = answer.read().decode("utf-8", "replace")
            return answer.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(text)
        except ValueError:
            return e.code, text


def ensure_label(token: str, slug: str) -> None:
    """Метка нужна заранее: issue с несуществующей меткой GitHub не примет."""
    status, _ = call(token, "POST", f"/repos/{slug}/labels",
                     {"name": LABEL, "color": "b60205",
                      "description": "обход телесайтов упал или прерван — смотреть прогон"})
    if status not in (201, 422):            # 422 — уже есть, это норма
        print(f"метка «{LABEL}»: GitHub ответил {status}")


def open_issue(token: str, slug: str) -> int:
    """Номер открытой issue с нашей меткой, 0 — нет такой."""
    query = urllib.parse.urlencode({"labels": LABEL, "state": "open",
                                    "per_page": 5})
    status, items = call(token, "GET", f"/repos/{slug}/issues?{query}")
    if status != 200 or not isinstance(items, list):
        return 0
    for item in items:                      # этот список отдаёт и PR-ы
        if "pull_request" not in item:
            return int(item["number"])
    return 0


def _load(folder: Path, name: str) -> dict:
    try:
        return json.loads((folder / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _human(note: str) -> str:
    return note.replace("::error::", "❌ ").replace("::warning::", "⚠️ ")


def body_text(run_url: str, mode: str, folder: Path = RAW) -> str:
    """Текст issue/комментария: ссылка на прогон, оценка, кто не открылся."""
    report, games = _load(folder, "report.json"), _load(folder, "games.json")
    now = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M")
    lines = [f"**Прогон:** {run_url}", f"**Что запускали:** {mode or '?'}",
             f"**Когда:** {now} UTC", ""]
    if not report:
        lines += ["Отчёта обхода нет — упало раньше (установка, сеть) или по "
                  "таймауту; причина — в логе прогона по ссылке.", ""]
    else:
        notes = (report.get("оценка") or {}).get("строки") or []
        verdict = games.get("оценка") or ""
        lines.append("**Оценка:**")
        lines += [f"- {_human(n)}" for n in notes]
        if verdict:
            lines.append(f"- {_human(verdict)}")
        if not notes and not verdict:
            lines.append("- оценки нет: обход прерван до конца или шёл с фильтром")
        rows = report.get("строки") or []
        broken: dict[str, int] = {}
        for r in rows:
            if r.get("итог") in BROKEN:
                broken[r["domain"]] = broken.get(r["domain"], 0) + 1
        games_n = games.get("игр")
        lines += ["", f"Страниц: {len(rows)}, не открылись: {sum(broken.values())}"
                  + (f", игр после разбора: {games_n}" if games_n is not None else "")]
        if broken:
            lines += ["", "| Сайт | Не открылись |", "|---|---|"]
            lines += [f"| {d} | {n} |" for d, n in
                      sorted(broken.items(), key=lambda x: -x[1])[:15]]
    lines += ["", "Результат в `results/` не обновлялся — на сайте остаётся "
              "прошлый удачный обход."]
    return "\n".join(lines)


def watch(folder: Path, run_url: str) -> int:
    """Дозор пустил — заводим issue, чтобы владельцу пришло письмо.

    Сайт вроде `liveonsat.com` закрыт Cloudflare и в обходе стоит дозором:
    один заход в сутки. Если он вдруг ответил расписанием, это новость —
    сайт можно возвращать в обход полностью.
    """
    report = _load(folder, "report.json")
    opened = [d for d, info in (report.get("дозор") or {}).items()
              if (info or {}).get("итог") == "расписание есть"]
    if not opened:
        print("дозор: никто не пустил")
        return 0
    token, slug = _token(), _slug()
    ensure_label(token, slug)
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    text = ("Сайт снова отвечает расписанием — можно возвращать в обход "
            "целиком (страница «Сломанные» → кнопка «В обход»).\n\n"
            + "\n".join(f"- **{d}**" for d in sorted(opened))
            + f"\n\nПрогон: {run_url}")
    status, answer = call(token, "POST", f"/repos/{slug}/issues",
                          {"title": f"Дозор: {', '.join(sorted(opened))} снова "
                                    f"пускает — {today}"[:200],
                           "body": text, "labels": [LABEL]})
    if status != 201:
        print(f"issue не завелась: {status}: {str(answer)[:200]}")
        return 1
    print("дозор:", ", ".join(sorted(opened)), "→",
          answer.get("html_url", "") if isinstance(answer, dict) else "")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-url", default="", help="ссылка на прогон")
    ap.add_argument("--mode", default="", help="что запускали, словами")
    ap.add_argument("--raw", default=str(RAW),
                    help="папка с report.json/games.json прогона")
    ap.add_argument("--watch", action="store_true",
                    help="не тревога, а добрая весть: сайт-дозор снова пускает "
                         "(решение владельца 09.09 — «дать сигнал»)")
    args = ap.parse_args()

    if args.watch:
        return watch(Path(args.raw), args.run_url)

    token, slug = _token(), _slug()
    ensure_label(token, slug)
    text = body_text(args.run_url, args.mode, Path(args.raw))
    number = open_issue(token, slug)
    if number:
        status, answer = call(token, "POST", f"/repos/{slug}/issues/{number}/comments",
                              {"body": text})
        what = f"комментарий в открытую issue #{number}"
    else:
        today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
        status, answer = call(token, "POST", f"/repos/{slug}/issues",
                              {"title": f"Обход упал — {today}: {args.mode or 'прогон'}"[:200],
                               "body": text, "labels": [LABEL]})
        what = "новая issue"
    if status != 201:
        print(f"issue не завелась: GitHub ответил {status}: {str(answer)[:300]}")
        return 1
    url = answer.get("html_url", "") if isinstance(answer, dict) else ""
    print(f"{what}: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

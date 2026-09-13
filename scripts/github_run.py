# -*- coding: utf-8 -*-
r"""Работа с GitHub без ручных действий: репозиторий, запуск обхода, результат.

Ключ **нигде не хранится и не печатается**. Скрипт спрашивает его у самого
`git` — той же командой `git credential fill`, которой пользуется обычный
`git push`. То есть ничего нового наружу не отдаётся: ключ как лежал в
диспетчере учётных данных Windows, так и лежит.

Команды:
    python scripts/github_run.py whoami          кто мы на GitHub
    python scripts/github_run.py create ИМЯ      создать приватный репозиторий
    python scripts/github_run.py dispatch        запустить обход (проба)
    python scripts/github_run.py dispatch --full --days 2
    python scripts/github_run.py runs            последние запуски
    python scripts/github_run.py wait            дождаться конца запуска
    python scripts/github_run.py fetch           забрать артефакт в recon/raw_live
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"
WORKFLOW = "crawl.yml"


def _token() -> str:
    """Ключ у git — так же, как его берёт `git push`. На экран не выводится."""
    answer = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, cwd=ROOT)
    for line in answer.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise SystemExit("git не отдал ключ для github.com — проверьте вход в GitHub")


class _DropAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Скачивание артефакта уводит на хранилище файлов, а туда наш ключ
    посылать нельзя — оно отвечает 401. Поэтому при переходе по ссылке
    заголовок с ключом снимаем: дальше работает подпись в самом адресе."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            for name in ("Authorization", "authorization"):
                new.headers.pop(name, None)
                new.unredirected_hdrs.pop(name, None)
        return new


_OPENER = urllib.request.build_opener(_DropAuthOnRedirect)


def call(method: str, path: str, body: dict | None = None, raw: bool = False):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "streams-schedule",
        "Content-Type": "application/json",
    })
    try:
        with _OPENER.open(request) as answer:
            payload = answer.read()
            if raw:
                return answer.status, payload
            return answer.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            return exc.code, json.loads(payload)
        except ValueError:
            return exc.code, {"сообщение": payload[:400].decode("utf-8", "replace")}


def repo_slug() -> str:
    """`Newik89/streams-schedule` — из адреса, который стоит у origin."""
    out = subprocess.run(["git", "remote", "get-url", "origin"],
                         capture_output=True, text=True, cwd=ROOT).stdout.strip()
    if not out:
        raise SystemExit("у репозитория нет origin — сначала `create`")
    return out.rsplit("github.com/", 1)[-1].removesuffix(".git")


def cmd_whoami(args) -> int:
    status, me = call("GET", "/user")
    print(f"{status}  вход как: {me.get('login')}  ({me.get('name') or '—'})")
    return 0 if status == 200 else 1


def cmd_create(args) -> int:
    status, answer = call("POST", "/user/repos", {
        "name": args.name, "private": True, "auto_init": False,
        "description": "Расписания ТВ-каналов: обход телесайтов и поиск прямых трансляций",
    })
    if status == 201:
        print(f"создан приватный репозиторий: {answer['html_url']}")
    elif status == 422:
        print(f"репозиторий {args.name} уже есть — используем его")
    else:
        print(f"{status}: {answer}")
        return 1

    login = call("GET", "/user")[1].get("login")
    url = f"https://github.com/{login}/{args.name}.git"
    subprocess.run(["git", "remote", "remove", "origin"], cwd=ROOT,
                   capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", url], cwd=ROOT, check=True)
    print(f"origin: {url}")
    return 0


def cmd_dispatch(args) -> int:
    slug = repo_slug()
    status, answer = call(
        "POST", f"/repos/{slug}/actions/workflows/{WORKFLOW}/dispatches",
        {"ref": "main", "inputs": {
            # значения латиницей: GitHub не принял кириллицу в списке вариантов
            "mode": "full" if args.full else "proba",
            "days": str(args.days), "delay": str(args.delay),
            "only": args.only, "urls": args.urls, "post": args.post,
            "warmup": args.warmup,
            "browser": "yes" if args.browser else "no"}})
    if status == 204:
        print(f"обход запущен: {'полный' if args.full else 'проба'}, "
              f"пауза {args.delay} с")
        return 0
    print(f"{status}: {answer}")
    return 1


def _runs(slug: str, limit: int = 5) -> list[dict]:
    status, answer = call("GET", f"/repos/{slug}/actions/runs?per_page={limit}")
    return answer.get("workflow_runs", []) if status == 200 else []


def cmd_runs(args) -> int:
    for run in _runs(repo_slug()):
        print(f"  #{run['run_number']}  {run['status']:<12} "
              f"{run.get('conclusion') or '—':<10} {run['created_at']}  "
              f"{run['html_url']}")
    return 0


def cmd_wait(args) -> int:
    slug = repo_slug()
    for _ in range(args.timeout // 10):
        runs = _runs(slug, 1)
        if runs:
            run = runs[0]
            if run["status"] == "completed":
                print(f"запуск #{run['run_number']}: {run['conclusion']}")
                print(f"  {run['html_url']}")
                return 0 if run["conclusion"] == "success" else 1
            print(f"  #{run['run_number']}: {run['status']}…")
        time.sleep(10)
    print("не дождались")
    return 1


def cmd_fetch(args) -> int:
    slug = repo_slug()
    runs = _runs(slug, 10)
    if not runs:
        print("запусков ещё не было")
        return 1
    if args.run_number:
        matched = [r for r in runs if r["run_number"] == args.run_number]
        if not matched:
            print(f"запуск #{args.run_number} не найден среди последних {len(runs)}")
            return 1
        run = matched[0]
    else:
        run = runs[0]
    status, answer = call("GET", f"/repos/{slug}/actions/runs/{run['id']}/artifacts")
    items = answer.get("artifacts", []) if status == 200 else []
    if not items:
        # плановый запуск, увидевший «сегодня уже ходили», завершается пустым —
        # тогда молча берём ближайший прогон с артефактом
        if not args.run_number:
            for r in runs[1:]:
                st, a = call("GET", f"/repos/{slug}/actions/runs/{r['id']}/artifacts")
                if st == 200 and a.get("artifacts"):
                    run, items = r, a["artifacts"]
                    print(f"у последнего запуска артефактов нет, "
                          f"беру #{run['run_number']} ({run['created_at']})")
                    break
        if not items:
            print(f"у запуска #{run['run_number']} артефактов нет")
            return 1
    art = items[0]
    status, blob = call("GET", art["archive_download_url"], raw=True)
    if status != 200:
        print(f"{status}: не скачалось")
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        z.extractall(out)
        print(f"распаковано {len(z.namelist())} файл(ов) в {out}")
    for name in ("report.md", "matches.md"):
        path = out / name
        if path.exists():
            print(f"\n──── {name} ────")
            print(path.read_text(encoding="utf-8")[:4000])
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("whoami").set_defaults(run=cmd_whoami)
    p = sub.add_parser("create"); p.add_argument("name"); p.set_defaults(run=cmd_create)
    p = sub.add_parser("dispatch")
    p.add_argument("--full", action="store_true")
    p.add_argument("--days", type=int, default=2)
    p.add_argument("--delay", type=float, default=3)
    p.add_argument("--only", default="", help="только эти домены, через запятую")
    p.add_argument("--urls", default="", help="проверить сторонние адреса")
    p.add_argument("--post", default="",
                   help="поля формы `k=v&k2=v2`: адреса из --urls уйдут POST-ом")
    p.add_argument("--warmup", default="",
                   help="сперва открыть эту страницу той же сессией (куки)")
    p.add_argument("--browser", action="store_true",
                   help="сразу браузером: сайт отвечает 200, а расписание "
                        "рисует скриптом")
    p.set_defaults(run=cmd_dispatch)
    sub.add_parser("runs").set_defaults(run=cmd_runs)
    p = sub.add_parser("wait"); p.add_argument("--timeout", type=int, default=600)
    p.set_defaults(run=cmd_wait)
    p = sub.add_parser("fetch")
    p.add_argument("--out", default=str(ROOT / "recon" / "raw_live"))
    p.add_argument("--run", type=int, default=0, dest="run_number",
                   help="номер конкретного прогона (по умолчанию — последний с артефактом)")
    p.set_defaults(run=cmd_fetch)
    args = ap.parse_args()
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())

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
    python scripts/github_run.py fetch           забрать страницы сбора в recon/raw_live
    python scripts/github_run.py fetch --run 376 страницы конкретного прогона

Страницы сбора с 31.10 лежат в кэше GitHub одним файлом (crawl.yml, ключ
`sbor-N-pages`), а кэш наружу не скачивается: `fetch` сам заказывает задание
«Выдать сбор» (vydat.yml) — оно кладёт архив артефактом `vydacha-N` на сутки.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"
WORKFLOW = "crawl.yml"
#: задание «Выдать сбор №»: страницы из кэша → артефакт vydacha-N на сутки
VYDAT = "vydat.yml"
#: шаг crawl.yml, который кладёт страницы; прошёл — страницы у прогона есть
STEP_PAGES = "Забрать страницы и отчёты"


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


#: SHA коммита целиком — только так `crawl.yml` принимает `code_ref`
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def cmd_dispatch(args) -> int:
    slug = repo_slug()
    code_ref = (args.code_ref or "").strip().lower()
    if code_ref and not _SHA40.match(code_ref):
        print(f"--code-ref: нужен SHA коммита целиком (40 знаков), а не {code_ref!r}")
        return 1
    status, answer = call(
        "POST", f"/repos/{slug}/actions/workflows/{WORKFLOW}/dispatches",
        {"ref": args.ref, "inputs": {
            # значения латиницей: GitHub не принял кириллицу в списке вариантов
            "mode": "full" if args.full else "proba",
            "days": str(args.days), "delay": str(args.delay),
            "only": args.only, "urls": args.urls, "post": args.post,
            "warmup": args.warmup,
            "browser": "yes" if args.browser else "no",
            # workflow — с main (или с ветки --ref), а код обхода — с этого
            # коммита: так проба бежит кодом ветки до слияния (18.10, dirbg)
            "code_ref": code_ref}})
    if status == 204:
        print(f"обход запущен: {'полный' if args.full else 'проба'}, "
              f"пауза {args.delay} с"
              + (f", код {code_ref[:10]}" if code_ref else "")
              + (f", workflow с ветки {args.ref}" if args.ref != "main" else ""))
        return 0
    print(f"{status}: {answer}")
    return 1


def _runs(slug: str, limit: int = 5) -> list[dict]:
    """Прогоны ОБХОДА (crawl.yml), свежие первыми. Только его: в общем списке
    репозитория идут и `queue.yml`, и `alarm.yml`, и ежечасный `alive.yml`
    (12.10) — `wait` «дождался» бы чужого прогона, а `fetch` не нашёл бы
    утренний сбор среди последних 30."""
    status, answer = call("GET", f"/repos/{slug}/actions/workflows/crawl.yml/runs"
                                 f"?per_page={limit}")
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


def _artifacts(slug: str, run_id: int) -> list[dict]:
    status, answer = call("GET", f"/repos/{slug}/actions/runs/{run_id}/artifacts")
    return [a for a in answer.get("artifacts", []) if not a["expired"]] \
        if status == 200 else []


def _has_pages(slug: str, run: dict) -> bool:
    """У прогона были страницы: шаг «Забрать страницы и отчёты» прошёл.
    Плановый запуск, увидевший «сегодня уже ходили», и переразбор страниц
    не кладут — шаг у них пропущен."""
    status, answer = call("GET", f"/repos/{slug}/actions/runs/{run['id']}/jobs?per_page=5")
    for job in answer.get("jobs", []) if status == 200 else []:
        for step in job.get("steps", []):
            if step["name"] == STEP_PAGES:
                return step.get("conclusion") == "success"
    return False


def _vydacha(slug: str, number: int, ref: str) -> list[dict]:
    """Страницы сбора лежат в кэше GitHub (crawl.yml, ключ sbor-N-pages), а
    кэш наружу не скачивается. Заказываем задание «Выдать сбор» (vydat.yml):
    оно кладёт архив обычным артефактом vydacha-N на сутки. Уже выдан и жив —
    берём его, задание не заказываем. `ref` — ветка того прогона: кэш виден
    только ей и main."""
    def ready() -> list[dict]:
        status, answer = call("GET", f"/repos/{slug}/actions/artifacts?name=vydacha-{number}")
        return [a for a in answer.get("artifacts", []) if not a["expired"]] \
            if status == 200 else []

    have = ready()
    if have:
        return have
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
    status, answer = call("POST", f"/repos/{slug}/actions/workflows/{VYDAT}/dispatches",
                          {"ref": ref, "inputs": {"number": str(number)}})
    if status != 204:
        print(f"{status}: выдача сбора #{number} не заказалась: {answer}")
        return []
    print(f"страницы #{number} лежат в кэше GitHub — заказана выдача, ждём…")
    title = f"Выдать сбор #{number}"
    for _ in range(36):                       # до 6 минут
        time.sleep(10)
        status, answer = call("GET", f"/repos/{slug}/actions/workflows/{VYDAT}/runs?per_page=5")
        for run in answer.get("workflow_runs", []) if status == 200 else []:
            if (run["display_title"] != title or run["created_at"] < since
                    or run["status"] != "completed"):
                continue
            if run["conclusion"] == "success":
                return ready()
            print(f"выдача #{number} не удалась ({run['conclusion']}): в кэше "
                  f"страниц нет — сбор старше ~7 дней или без страниц\n  {run['html_url']}")
            return []
    print("выдача не дождалась за 6 минут")
    return []


def _unpack(blob: bytes, out: Path) -> int:
    """Артефакт — zip. Старый вид (до 31.10): страницы россыпью. Новый: внутри
    один obhod.tar.xz (crawl.yml, шаг «Упаковать страницы одним файлом»), в
    нём папка raw_live/ — её содержимое кладём прямо в out, как раньше."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = z.namelist()
        if names != ["obhod.tar.xz"]:
            z.extractall(out)
            return len(names)
        packed = z.read("obhod.tar.xz")
    n = 0
    with tarfile.open(fileobj=io.BytesIO(packed), mode="r:xz") as tar:
        for member in tar:
            _, _, rest = member.name.partition("/")
            if not rest:                      # сама папка raw_live
                continue
            member.name = rest
            tar.extract(member, out, filter="data")
            n += int(member.isfile())
    return n


def cmd_fetch(args) -> int:
    slug = repo_slug()
    # 30, а не 10: за сутки прогонов бывает больше десятка (сборы, пробы,
    # очередь queue.yml идёт тем же списком), и утренний сбор уже не попадал
    # в выборку — `fetch --run 205` отвечал «не найден» (06.10). С номером —
    # 100: кэш GitHub держит страницы до 7 дней, это глубже 30 прогонов
    runs = _runs(slug, 100 if args.run_number else 30)
    if not runs:
        print("запусков ещё не было")
        return 1
    if args.run_number:
        matched = [r for r in runs if r["run_number"] == args.run_number]
        if not matched:
            print(f"запуск #{args.run_number} не найден среди последних {len(runs)}")
            return 1
        runs = matched
    run, items = runs[0], []
    # старый вид — артефакт obhod-N у самого прогона; новый — страницы в кэше,
    # их выдаёт vydat.yml. Без --run: плановый запуск, увидевший «сегодня уже
    # ходили», и переразбор страниц не кладут — берём ближайший прогон с ними
    for r in runs:
        if not _has_pages(slug, r):
            continue
        items = _artifacts(slug, r["id"]) or \
            _vydacha(slug, r["run_number"], r.get("head_branch") or "main")
        if items:
            if r is not runs[0]:
                print(f"у последнего запуска страниц нет, "
                      f"беру #{r['run_number']} ({r['created_at']})")
            run = r
            break
        if args.run_number:
            break
    if not items:
        print(f"у запуска #{run['run_number']} страниц нет")
        return 1
    art = items[0]
    status, blob = call("GET", art["archive_download_url"], raw=True)
    if status != 200:
        print(f"{status}: не скачалось")
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"распаковано {_unpack(blob, out)} файл(ов) в {out}")
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
    p.add_argument("--code-ref", default="", dest="code_ref",
                   help="SHA коммита (40 знаков): обход бежит кодом этого "
                        "коммита, а не main — проба ветки до слияния")
    p.add_argument("--ref", default="main",
                   help="ветка, с которой берётся сам crawl.yml (проверка "
                        "правок workflow до слияния; код — тоже с неё, если "
                        "--code-ref не задан). Проба не пишет в main")
    p.set_defaults(run=cmd_dispatch)
    sub.add_parser("runs").set_defaults(run=cmd_runs)
    p = sub.add_parser("wait"); p.add_argument("--timeout", type=int, default=600)
    p.set_defaults(run=cmd_wait)
    p = sub.add_parser("fetch")
    p.add_argument("--out", default=str(ROOT / "recon" / "raw_live"))
    p.add_argument("--run", type=int, default=0, dest="run_number",
                   help="номер конкретного прогона (по умолчанию — последний со страницами)")
    p.set_defaults(run=cmd_fetch)
    args = ap.parse_args()
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())

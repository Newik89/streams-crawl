# -*- coding: utf-8 -*-
r"""Жив ли сервер — смотрит GitHub (схема сбоев, шаг 9, 12.10.2026).

Сервер лёг — сам он об этом не напишет. Поэтому GitHub (workflow
`alive.yml`, по расписанию) открывает страницу сервера `/alive`
(`app/alive.py`): она отвечает, кто из сторожей сервера давно молчит.
Беда — issue с меткой `сервер-лёг`, и GitHub шлёт владельцу письмо.

Правила (`verdict` и `action`), по порядку:
  Ж1. `/alive` ответил «жив» (или 404 и не JSON — код с этой страницей ещё
      не приехал на сервер, но сервер отвечает) → в порядке. Открыта issue
      `сервер-лёг` → комментарий «снова в порядке» (второе письмо) и закрыть.
  Ж2. Не ответил ни на одну из `TRIES` проб (`GAP` с между ними; 5xx — тоже
      не ответ: nginx жив, а витрина нет) → беда «сервер не отвечает».
  Ж3. Ответил, но кто-то молчит → беда «сервер отвечает, но …» (слова с
      сервера: сторож заказов или витрины молчит, письма тревог не уходят).
  Беда: открытой issue нет → новая (письмо). Есть → молчим, пока с её
  последнего обновления не прошло `REMIND_HOURS`; потом комментарий «всё
  ещё …» (ещё письмо). GitHub не отдал список issue → ничего не делаем.

Адрес сервера — из секрета `CRAWL_HOOK_URL` (туда же стучит обход); в журнал
он не выводится (`::add-mask::`), в текст issue не попадает (`hide`).

    python scripts/server_alive.py               проверить (в alive.yml)
    python scripts/server_alive.py --proba-down  проба письма: стучимся в
        закрытый порт сервера → «не отвечает» с пометкой ПРОБА (тег
        `alive-proba-down-…`); следующая обычная проверка её закроет
Только стандартная библиотека.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crawl_alarm import _slug, _token, call, ensure_label, open_issues  # noqa: E402

LABEL = "сервер-лёг"
#: проб до вывода «не отвечает» и пауза между ними, с
TRIES = 3
GAP = 60
#: ждать ответа одной пробы, с
TIMEOUT = 30
#: открытая беда: напоминать письмом не чаще
REMIND_HOURS = 24
#: закрытый порт для пробы письма (`--proba-down`)
PROBA_PORT = 1

try:
    from zoneinfo import ZoneInfo
    KYIV = ZoneInfo("Europe/Kyiv")
except Exception:                               # noqa: BLE001 — нет базы поясов
    KYIV = timezone.utc

_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")


def base_url(hook_url: str) -> str:
    """`http://адрес/crawl-hook` → `http://адрес` (схема и хост с портом)."""
    parts = urllib.parse.urlsplit(hook_url.strip())
    if not parts.scheme or not parts.netloc:
        raise SystemExit("CRAWL_HOOK_URL пуст или не адрес — проверять нечего")
    return f"{parts.scheme}://{parts.netloc}"


def hide(text: str, base: str) -> str:
    """Адрес сервера — вон из текста: репозиторий публичный."""
    host = urllib.parse.urlsplit(base).netloc
    if host:
        text = text.replace(base, "<сервер>").replace(host, "<сервер>")
    return _IP_RE.sub("<адрес>", text)


def probe(url: str, timeout: int = TIMEOUT) -> tuple[str, object]:
    """Одна проба: ("ok", ответ-словарь) / ("old", слова) — сервер ответил,
    но страницы /alive у него нет / ("down", почему не ответил)."""
    request = urllib.request.Request(url, headers={"User-Agent": "streams-alive"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            text = r.read(20000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return ("down" if e.code >= 500 else "old"), f"HTTP {e.code}"
    except Exception as e:                      # noqa: BLE001 — таймаут, отказ, DNS
        return "down", f"{type(e).__name__}: {e}"[:200]
    try:
        data = json.loads(text)
    except ValueError:
        return "old", "ответ не JSON"
    return ("ok", data) if isinstance(data, dict) else ("old", "ответ не JSON")


def look(url: str, tries: int = TRIES, gap: int = GAP, sleep=time.sleep,
         one=probe) -> tuple[str, object]:
    """До `tries` проб с паузой `gap`; первая не-«down» — итог."""
    kind, data = "down", "проб не было"
    for n in range(tries):
        if n:
            sleep(gap)
        kind, data = one(url)
        print(f"проба {n + 1}: {kind}")
        if kind != "down":
            break
    return kind, data


def verdict(kind: str, data) -> tuple[bool, str]:
    """Правила Ж1–Ж3: (в порядке ли, слова беды)."""
    if kind == "old":                                              # Ж1
        return True, ""
    if kind == "ok":
        if data.get("жив", True):                                  # Ж1
            return True, ""
        silent = "; ".join(str(s) for s in data.get("молчат") or []) or "?"
        return False, f"сервер отвечает, но {silent}"              # Ж3
    return False, f"сервер не отвечает ({data})"                   # Ж2


def _at(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def action(ok: bool, issues: list[dict], now: datetime) -> tuple[str, int]:
    """Что делать с issue: ("close", номер) / ("open", 0) / ("remind", номер)
    / ("none", 0). `issues` — открытые с меткой, свежие первыми."""
    if ok:
        return ("close", int(issues[0]["number"])) if issues else ("none", 0)
    if not issues:
        return "open", 0
    newest = issues[0]
    updated = _at(newest.get("updated_at") or "") or now
    if now - updated >= timedelta(hours=REMIND_HOURS):
        return "remind", int(newest["number"])
    return "none", 0


def kyiv(now: datetime) -> str:
    return now.astimezone(KYIV).strftime("%d.%m.%Y %H:%M")


def body_text(words: str, now: datetime, run_url: str, owner: str,
              proba: bool) -> str:
    lines = []
    if owner:
        lines.append(f"@{owner} — письмо проверки «Сервер жив?» (GitHub).")
    if proba:
        lines += ["", "**ПРОБА письма** — сервер в порядке, это проверка, что "
                      "письмо доходит. Следующая обычная проверка закроет её."]
    lines += ["", f"**Что:** {words}", f"**Когда:** {kyiv(now)} по Киеву"]
    if run_url:
        lines.append(f"**Проверка:** {run_url}")
    lines += ["", "Что делать: открыть чат Claude «Streams Schedule» и написать "
                  "«сервер лёг» — дальше он сделает сам. Не поднимается вовсе — "
                  "панель DigitalOcean → Droplet → Power cycle.",
              "Когда сервер снова ответит, сюда придёт «снова в порядке», и "
              "issue закроется сама."]
    return "\n".join(lines)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--proba-down", action="store_true",
                    help="проба письма: закрытый порт вместо сервера")
    ap.add_argument("--run-url", default="", help="ссылка на этот прогон")
    args = ap.parse_args()

    base = base_url(os.environ.get("CRAWL_HOOK_URL", ""))
    host = urllib.parse.urlsplit(base).netloc
    print(f"::add-mask::{base}")
    print(f"::add-mask::{host}")
    print(f"::add-mask::{host.split(':')[0]}")
    url = base + "/alive"
    if args.proba_down:
        bare = urllib.parse.urlsplit(base)
        url = f"{bare.scheme}://{bare.hostname}:{PROBA_PORT}/alive"
        kind, data = look(url, tries=1)
    else:
        kind, data = look(url)
    ok, words = verdict(kind, data)
    words = hide(words, base)
    now = datetime.now(timezone.utc)
    print("итог:", "в порядке" if ok else words)

    token, slug = _token(), _slug()
    issues = open_issues(token, slug, LABEL)
    if issues is None:
        # красный прогон — запасное письмо: о красном прогоне по расписанию
        # GitHub пишет тому, кто последним правил расписание
        print("GitHub не отдал список issue — в этот раз ничего не делаю")
        return 0 if ok else 1
    what, number = action(ok, issues, now)
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    if what == "open":
        ensure_label(token, slug, LABEL,
                     "сервер не отвечает или его сторожа молчат — письмо владельцу")
        short = "не отвечает" if kind == "down" else "молчат сторожа"
        title = (("ПРОБА: " if args.proba_down else "")
                 + f"Сервер {short} — {kyiv(now)}")
        status, answer = call(token, "POST", f"/repos/{slug}/issues",
                              {"title": title[:200], "labels": [LABEL],
                               "body": body_text(words, now, args.run_url,
                                                 owner, args.proba_down)})
    elif what == "remind":
        status, answer = call(token, "POST",
                              f"/repos/{slug}/issues/{number}/comments",
                              {"body": f"Всё ещё: {words} ({kyiv(now)} по Киеву)"})
    elif what == "close":
        status, answer = call(token, "POST",
                              f"/repos/{slug}/issues/{number}/comments",
                              {"body": f"Сервер снова в порядке — {kyiv(now)} "
                                       f"по Киеву. Закрываю."})
        if status == 201:
            for item in issues:
                call(token, "PATCH", f"/repos/{slug}/issues/{item['number']}",
                     {"state": "closed", "state_reason": "completed"})
    else:
        print("issue: ничего нового")
        return 0
    if status != 201:
        print(f"issue ({what}): GitHub ответил {status}: {str(answer)[:300]}")
        return 1
    print(f"issue ({what}):", answer.get("html_url", "") if isinstance(answer, dict) else "")
    return 0                  # письмо ушло issue; красный прогон дал бы второе


if __name__ == "__main__":
    raise SystemExit(main())

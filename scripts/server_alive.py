# -*- coding: utf-8 -*-
r"""Жив ли сервер — смотрит GitHub (схема сбоев, шаг 9, 12.10.2026).

Сервер лёг — сам он об этом не напишет. Поэтому GitHub (workflow
`alive.yml`, по расписанию) открывает страницу сервера `/alive`
(`app/alive.py`): она отвечает, кто из сторожей сервера давно молчит.
Беда — issue с меткой `сервер-лёг`, и GitHub шлёт владельцу письмо.

Правила (`verdict` и `action`), по порядку:
  Ж1. `/alive` ответил «жив» → в порядке. Открыта issue `сервер-лёг` →
      комментарий «снова в порядке» (второе письмо) и закрыть.
  Ж2. Не ответил ни на одну из `TRIES` проб (`GAP` с между ними; 5xx — тоже
      не ответ: nginx жив, а витрина нет) → беда вида `down`.
  Ж3. Ответил, но кто-то молчит → беда вида `silent:<кто>` (слова с
      сервера: сторож заказов или витрины молчит, письма тревог не уходят;
      в виде — состав молчащих, `кто` из ответа /alive).
  Ж4. Ответил не JSON или 4xx (страницы /alive нет) → до `OLD_GRACE_UNTIL`
      (код с ней едет на сервер) — в порядке с предупреждением; потом — беда
      вида `wrong` «сервер отвечает не тем»: на его адресе чужой сайт,
      заглушка или nginx не пускает.
  Беда: открытой issue нет → новая (письмо). Есть, и вид беды тот же →
  молчим, пока с её последнего обновления не прошло `REMIND_HOURS`; потом
  комментарий «всё ещё …». Вид сменился (молчали сторожа — лёг весь сервер)
  → комментарий сразу (письмо). Вид беды хранится в теле issue меткой
  `<!-- вид:… -->` (`issue_kind`). GitHub не отдал список issue → красный
  прогон (о нём GitHub пишет тому, кто правил расписание).

Адрес сервера — из секрета `CRAWL_HOOK_URL` (туда же стучит обход); в журнал
он не выводится (`::add-mask::`), в текст issue не попадает (`hide`).

    python scripts/server_alive.py               проверить (в alive.yml)
    python scripts/server_alive.py --proba-down  проба письма: стучимся в
        закрытый порт сервера и заводим ОТДЕЛЬНУЮ issue «ПРОБА: …», которую
        тут же закрываем (тег `alive-proba-down-…`); открытые беды не трогаем
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crawl_alarm import _slug, _token, call_retry, ensure_label  # noqa: E402

LABEL = "сервер-лёг"
#: проб до вывода «не отвечает» и пауза между ними, с
TRIES = 3
GAP = 60
#: ждать ответа одной пробы, с
TIMEOUT = 30
#: открытая беда того же вида: напоминать письмом не чаще
REMIND_HOURS = 24
#: закрытый порт для пробы письма (`--proba-down`)
PROBA_PORT = 1
#: до этого дня (включительно) «страницы /alive нет» — ещё не беда (Ж4):
#: код с ней едет на сервер обычным забором
OLD_GRACE_UNTIL = date(2026, 10, 15)

try:
    from zoneinfo import ZoneInfo
    KYIV = ZoneInfo("Europe/Kyiv")
except Exception:                               # noqa: BLE001 — нет базы поясов
    KYIV = timezone.utc

_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
_KIND_RE = re.compile(r"<!-- вид:([\w:+?]+) -->")
TITLES = {"down": "не отвечает", "wrong": "отвечает не тем"}


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
    но не JSON страницы /alive / ("down", почему не ответил)."""
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


def verdict(kind: str, data, today: date) -> tuple[str, str]:
    """Правила Ж1–Ж4: (вид беды — "" если в порядке, "down", "silent",
    "wrong"; слова беды)."""
    if kind == "ok":
        if data.get("жив") is True:                                # Ж1
            return "", ""
        silent = "; ".join(str(s) for s in data.get("молчат") or []) or "?"
        # вид — с составом молчащих: добавился «письма не уходят» к «сторож
        # молчит» — это новая беда, письмо сразу
        names = "+".join(sorted(str(n) for n in data.get("кто") or [])) or "?"
        return f"silent:{names}", f"сервер отвечает, но {silent}"  # Ж3
    if kind == "old":                                              # Ж4
        if today <= OLD_GRACE_UNTIL:
            print(f"::warning::страницы /alive на сервере нет ({data}) — "
                  f"код с ней ещё не приехал")
            return "", ""
        return "wrong", f"сервер отвечает не тем ({data}) — страницы /alive нет"
    return "down", f"сервер не отвечает ({data})"                  # Ж2


def _at(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def issue_kind(issue: dict) -> str:
    """Вид беды, о котором issue писала последним (метка в теле)."""
    found = _KIND_RE.findall(issue.get("body") or "")
    return found[-1] if found else ""


def action(bad: str, issues: list[dict], now: datetime) -> tuple[str, int]:
    """Что делать с issue: ("close", номер) / ("open", 0) / ("change", номер)
    / ("remind", номер) / ("none", 0). `bad` — вид беды ("" — в порядке);
    `issues` — открытые с меткой, свежие первыми."""
    if not bad:
        return ("close", int(issues[0]["number"])) if issues else ("none", 0)
    if not issues:
        return "open", 0
    newest = issues[0]
    if issue_kind(newest) != bad:
        return "change", int(newest["number"])
    updated = _at(newest.get("updated_at") or "") or now
    if now - updated >= timedelta(hours=REMIND_HOURS):
        return "remind", int(newest["number"])
    return "none", 0


def kyiv(now: datetime) -> str:
    return now.astimezone(KYIV).strftime("%d.%m.%Y %H:%M")


def title_text(bad: str, words: str, now: datetime, proba: bool) -> str:
    """Заголовок: «Сервер не отвечает — …» или первые слова беды."""
    if bad in TITLES:
        what = f"Сервер {TITLES[bad]}"
    else:
        what = "Сервер: " + words.removeprefix("сервер отвечает, но ").split(";")[0]
    return (("ПРОБА: " if proba else "") + f"{what} — {kyiv(now)}")[:200]


def body_text(bad: str, words: str, now: datetime, run_url: str, owner: str,
              proba: bool) -> str:
    lines = []
    if owner:
        lines.append(f"@{owner} — письмо проверки «Сервер жив?» (GitHub).")
    if proba:
        lines += ["", "**ПРОБА письма** — сервер в порядке, это проверка, что "
                      "письмо доходит. Закрываю её сразу."]
    lines += ["", f"**Что:** {words}", f"**Когда:** {kyiv(now)} по Киеву"]
    if run_url:
        lines.append(f"**Проверка:** {run_url}")
    lines += ["", "Что делать: открыть чат Claude «Streams Schedule» и написать "
                  "«сервер лёг» — дальше он сделает сам. Не поднимается вовсе — "
                  "панель DigitalOcean → Droplet → Power cycle.",
              "Когда сервер снова ответит, сюда придёт «снова в порядке», и "
              "issue закроется сама.", "", f"<!-- вид:{bad} -->"]
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
    now = datetime.now(timezone.utc)
    if args.proba_down:
        bare = urllib.parse.urlsplit(base)
        kind, data = look(f"{bare.scheme}://{bare.hostname}:{PROBA_PORT}/alive", tries=1)
    else:
        kind, data = look(base + "/alive")
    bad, words = verdict(kind, data, now.astimezone(KYIV).date())
    words = hide(words, base)
    print("итог:", words or "в порядке")

    token, slug = _token(), _slug()
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    if args.proba_down:
        return proba(token, slug, bad or "down", words or "проба", now,
                     args.run_url, owner)
    status, issues = call_retry(token, "GET", f"/repos/{slug}/issues?" + urllib.parse.urlencode(
        {"labels": LABEL, "state": "open", "per_page": 10}))
    if status != 200 or not isinstance(issues, list):
        print(f"GitHub не отдал список issue ({status}) — в этот раз ничего не делаю")
        return 0 if not bad else 1
    issues = [i for i in issues if "pull_request" not in i]
    what, number = action(bad, issues, now)
    if what == "open":
        ensure_label(token, slug, LABEL,
                     "сервер не отвечает или его сторожа молчат — письмо владельцу")
        status, answer = call_retry(token, "POST", f"/repos/{slug}/issues",
                                    {"title": title_text(bad, words, now, False),
                                     "labels": [LABEL],
                                     "body": body_text(bad, words, now, args.run_url,
                                                       owner, False)})
    elif what in ("remind", "change"):
        lead = "Всё ещё" if what == "remind" else "Теперь"
        status, answer = call_retry(token, "POST",
                                    f"/repos/{slug}/issues/{number}/comments",
                                    {"body": f"{lead}: {words} ({kyiv(now)} по Киеву)"})
        if status == 201 and what == "change":
            body = _KIND_RE.sub("", issues[0].get("body") or "").rstrip()
            patched, _ = call_retry(token, "PATCH", f"/repos/{slug}/issues/{number}",
                                    {"body": f"{body}\n\n<!-- вид:{bad} -->"})
            if patched != 200:
                # старая метка осталась — следующая проверка снова написала бы
                # «Теперь: …»; красный прогон покажет, что тут что-то не так
                print(f"метку вида в #{number} обновить не вышло ({patched})")
                return 1
    elif what == "close":
        status, answer = call_retry(token, "POST",
                                    f"/repos/{slug}/issues/{number}/comments",
                                    {"body": f"Сервер снова в порядке — {kyiv(now)} "
                                             f"по Киеву. Закрываю."})
        if status == 201:
            for item in issues:
                call_retry(token, "PATCH", f"/repos/{slug}/issues/{item['number']}",
                           {"state": "closed", "state_reason": "completed"})
    else:
        print("issue: ничего нового")
        return 0
    if status != 201:
        print(f"issue ({what}): GitHub ответил {status}: {str(answer)[:300]}")
        return 1
    print(f"issue ({what}):", answer.get("html_url", "") if isinstance(answer, dict) else "")
    return 0                  # письмо ушло issue; красный прогон дал бы второе


def proba(token: str, slug: str, bad: str, words: str, now: datetime,
          run_url: str, owner: str) -> int:
    """Проба письма: отдельная issue «ПРОБА: …» — завести и тут же закрыть.
    Открытые настоящие беды не трогаем."""
    ensure_label(token, slug, LABEL,
                 "сервер не отвечает или его сторожа молчат — письмо владельцу")
    status, answer = call_retry(token, "POST", f"/repos/{slug}/issues",
                                {"title": title_text(bad, words, now, True),
                                 "labels": [LABEL],
                                 "body": body_text(bad, words, now, run_url, owner, True)})
    if status != 201 or not isinstance(answer, dict):
        print(f"проба: GitHub ответил {status}: {str(answer)[:300]}")
        return 1
    number = answer.get("number")
    call_retry(token, "PATCH", f"/repos/{slug}/issues/{number}",
               {"state": "closed", "state_reason": "completed"})
    print("проба:", answer.get("html_url", ""), "— закрыта")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

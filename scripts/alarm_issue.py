# -*- coding: utf-8 -*-
r"""Тревога сервера → issue → письмо владельцу (схема сбоев, шаг 9, 12.10.2026).

Сервер (`app/alarm_mail.py`) пушит тег `alarm-<время>` с текстом новых
тревог в сообщении тега; workflow `alarm.yml` зовёт этот скрипт. Правила
по порядку:
  Т1. Берём ВСЕ теги `alarm-*`, старые первыми: прогон, который GitHub
      отменил в очереди (у группы `alarm` ждать может только один) или
      который упал, доберёт следующий — тревога не теряется.
  Т2. Текст — из тега через API (ссылка → объект тега → его сообщение).
      Тег лёгкий или без текста → пишем, что текста нет. API не ответил →
      стоп, теги остаются до следующего прогона.
  Т3. Issue — одна на киевский день: «Тревоги сервера — ДД.ММ.ГГГГ», метка
      `тревога-сервера`. Есть сегодняшняя открытая → комментарий (письмо).
      Нет → новая с упоминанием владельца (так письмо приходит наверняка),
      а открытые за прошлые дни — молча закрыть.
  Т4. Тег удаляется ТОЛЬКО после того, как GitHub принял issue или
      комментарий (201). Не принял → стоп, красный прогон.
Запросы к API повторяются до `TRIES` раз при сбое связи или 5xx. Адреса
IPv4 в тексте заменяются на «<адрес>»: репозиторий публичный.

    python scripts/alarm_issue.py
Только стандартная библиотека.
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crawl_alarm import _slug, _token, call_retry, ensure_label  # noqa: E402

LABEL = "тревога-сервера"
TITLE = "Тревоги сервера — "
PREFIX = "alarm-"
#: знаков текста в одном комментарии (у GitHub предел 65 536)
MAX_CHARS = 6000
#: попыток на один запрос к API и пауза между ними, с
TRIES = 3
PAUSE = 5

try:
    from zoneinfo import ZoneInfo
    KYIV = ZoneInfo("Europe/Kyiv")
except Exception:                               # noqa: BLE001 — нет базы поясов
    KYIV = timezone.utc

_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
_TAG_RE = re.compile(r"^alarm-[0-9A-Za-z_-]{1,40}$")


def api(token: str, method: str, path: str, body: dict | None = None):
    """`call` с повторами: сбой связи или 5xx — ещё раз через `PAUSE` с."""
    return call_retry(token, method, path, body, tries=TRIES, pause=PAUSE)


def _order(name: str) -> tuple[int, str]:
    digits = re.findall(r"\d+", name)
    return (int(digits[-1]) if digits else 0), name


def pending_tags(refs: list[dict]) -> list[str]:
    """Т1: имена тегов `alarm-*` из ответа `matching-refs`, старые первыми."""
    names = [str(r.get("ref", "")).removeprefix("refs/tags/") for r in refs]
    return sorted((n for n in names if _TAG_RE.match(n)), key=_order)


#: тега уже нет (разобран прошлым прогоном) — пропустить
GONE = "<тега уже нет>"


def tag_text(token: str, slug: str, tag: str) -> str | None:
    """Т2: сообщение аннотированного тега; "" — текста нет; `GONE` — тега уже
    нет; None — API не ответил."""
    quoted = urllib.parse.quote(tag, safe="")
    status, ref = api(token, "GET", f"/repos/{slug}/git/ref/tags/{quoted}")
    if status == 404:
        return GONE
    if status != 200 or not isinstance(ref, dict):
        return None
    obj = ref.get("object") or {}
    if obj.get("type") != "tag":
        return ""
    status, data = api(token, "GET", f"/repos/{slug}/git/tags/{obj.get('sha')}")
    if status != 200 or not isinstance(data, dict):
        return None
    return str(data.get("message") or "").strip()


def clean(text: str) -> str:
    text = _IP_RE.sub("<адрес>", text)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n…(обрезано)"


def today_title(now: datetime) -> str:
    return TITLE + now.astimezone(KYIV).strftime("%d.%m.%Y")


def plan(issues: list[dict], title: str) -> tuple[int, list[int]]:
    """Т3: (номер сегодняшней открытой issue или 0, номера прошлых открытых)."""
    today = [int(i["number"]) for i in issues if i.get("title") == title]
    old = [int(i["number"]) for i in issues if i.get("title") != title]
    return (today[0] if today else 0), old


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    token, slug = _token(), _slug()
    status, refs = api(token, "GET", f"/repos/{slug}/git/matching-refs/tags/{PREFIX}")
    if status != 200 or not isinstance(refs, list):
        print(f"GitHub не отдал список тегов ({status}) — письма не ушли")
        return 1
    tags = pending_tags(refs)
    if not tags:
        print("тегов-писем нет — их уже разобрал прошлый прогон")
        return 0
    status, issues = api(token, "GET", f"/repos/{slug}/issues?" + urllib.parse.urlencode(
        {"labels": LABEL, "state": "open", "per_page": 10}))
    if status != 200 or not isinstance(issues, list):
        print(f"GitHub не отдал список issue ({status}) — письма не ушли")
        return 1
    issues = [i for i in issues if "pull_request" not in i]
    title = today_title(datetime.now(timezone.utc))
    number, old = plan(issues, title)
    for tag in tags:
        text = tag_text(token, slug, tag)
        if text is None:
            print(f"{tag}: GitHub не отдал текст тега — стоп, тег остаётся")
            return 1
        if text == GONE:
            print(f"{tag}: тега уже нет — пропускаю")
            continue
        text = clean(text or f"Сервер прислал тревогу (тег {tag}), но текста в "
                             f"теге нет — смотреть «Прогоны» в админке.")
        if number:
            status, answer = api(token, "POST",
                                 f"/repos/{slug}/issues/{number}/comments",
                                 {"body": text})
            what = f"комментарий в #{number}"
        else:
            ensure_label(token, slug, LABEL, "тревоги сервера — письмом владельцу")
            owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
            head = (f"@{owner} — тревоги сервера за день приходят сюда, по "
                    f"комментарию на каждую; подробности — «Прогоны» в админке.\n\n"
                    if owner else "")
            status, answer = api(token, "POST", f"/repos/{slug}/issues",
                                 {"title": title, "labels": [LABEL],
                                  "body": head + text})
            what = "новая issue"
            if status == 201 and isinstance(answer, dict):
                number = int(answer.get("number") or 0)
                for n in old:                   # вчерашние — молча закрыть
                    api(token, "PATCH", f"/repos/{slug}/issues/{n}",
                        {"state": "closed", "state_reason": "completed"})
        if status != 201:
            print(f"{tag}: {what} — GitHub ответил {status}: {str(answer)[:300]}; "
                  f"стоп, тег остаётся")
            return 1
        url = answer.get("html_url", "") if isinstance(answer, dict) else ""
        status, _ = api(token, "DELETE", f"/repos/{slug}/git/refs/tags/"
                                         f"{urllib.parse.quote(tag, safe='')}")
        print(f"{tag}: {what} {url}; тег удалён: {status == 204}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

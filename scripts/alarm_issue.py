# -*- coding: utf-8 -*-
r"""Тревога сервера → issue → письмо владельцу (схема сбоев, шаг 9, 12.10.2026).

Сервер (`app/alarm_mail.py`) пушит тег `alarm-<время>` с текстом новых
тревог в сообщении тега; workflow `alarm.yml` зовёт этот скрипт. Правила
по порядку:
  Т1. Текст — из тега через API (ссылка → объект тега → его сообщение).
      Тег лёгкий или пустой → берём что есть и пишем, что текста нет.
  Т2. Issue — одна на киевский день: «Тревоги сервера — ДД.ММ.ГГГГ», метка
      `тревога-сервера`. Есть сегодняшняя открытая → комментарий (письмо).
      Нет → новая с упоминанием владельца (так письмо приходит наверняка),
      а открытые за прошлые дни — закрыть со ссылкой на новую.
  Т3. Тег удаляет workflow (шаг `if: always()`): своё он отслужил.
Адреса IPv4 в тексте заменяются на «<адрес>»: репозиторий публичный.

    python scripts/alarm_issue.py --tag alarm-1760300000
Только стандартная библиотека.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crawl_alarm import _slug, _token, call, ensure_label, open_issues  # noqa: E402

LABEL = "тревога-сервера"
TITLE = "Тревоги сервера — "
#: знаков текста в одном комментарии (у GitHub предел 65 536)
MAX_CHARS = 6000

try:
    from zoneinfo import ZoneInfo
    KYIV = ZoneInfo("Europe/Kyiv")
except Exception:                               # noqa: BLE001 — нет базы поясов
    KYIV = timezone.utc

_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
_TAG_RE = re.compile(r"^alarm-[0-9A-Za-z_-]{1,40}$")


def tag_text(token: str, slug: str, tag: str) -> str:
    """Т1: сообщение аннотированного тега; пусто — не вышло."""
    quoted = urllib.parse.quote(tag, safe="")
    status, ref = call(token, "GET", f"/repos/{slug}/git/ref/tags/{quoted}")
    if status != 200 or not isinstance(ref, dict):
        return ""
    obj = ref.get("object") or {}
    if obj.get("type") != "tag":
        return ""
    status, data = call(token, "GET", f"/repos/{slug}/git/tags/{obj.get('sha')}")
    if status != 200 or not isinstance(data, dict):
        return ""
    return str(data.get("message") or "").strip()


def clean(text: str) -> str:
    text = _IP_RE.sub("<адрес>", text)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n…(обрезано)"


def today_title(now: datetime) -> str:
    return TITLE + now.astimezone(KYIV).strftime("%d.%m.%Y")


def plan(issues: list[dict], title: str) -> tuple[int, list[int]]:
    """Т2: (номер сегодняшней открытой issue или 0, номера прошлых открытых)."""
    today = [int(i["number"]) for i in issues if i.get("title") == title]
    old = [int(i["number"]) for i in issues if i.get("title") != title]
    return (today[0] if today else 0), old


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True, help="имя тега alarm-…")
    args = ap.parse_args()
    if not _TAG_RE.match(args.tag):
        print(f"::error::тег «{args.tag}» не похож на alarm-<время> — не трогаю")
        return 1

    token, slug = _token(), _slug()
    text = tag_text(token, slug, args.tag) or (
        f"Сервер прислал тревогу (тег {args.tag}), но текста в теге нет — "
        f"смотреть «Прогоны» в админке.")
    text = clean(text)
    now = datetime.now(timezone.utc)
    title = today_title(now)
    issues = open_issues(token, slug, LABEL)
    if issues is None:
        print("GitHub не отдал список issue — письмо не ушло")
        return 1                  # красный прогон — запасное письмо
    number, old = plan(issues, title)
    if number:
        status, answer = call(token, "POST",
                              f"/repos/{slug}/issues/{number}/comments",
                              {"body": text})
        what = f"комментарий в #{number}"
    else:
        ensure_label(token, slug, LABEL, "тревоги сервера — письмом владельцу")
        owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
        head = (f"@{owner} — тревоги сервера за день приходят сюда, по "
                f"комментарию на каждую; подробности — «Прогоны» в админке.\n\n"
                if owner else "")
        status, answer = call(token, "POST", f"/repos/{slug}/issues",
                              {"title": title, "labels": [LABEL],
                               "body": head + text})
        what = "новая issue"
        if status == 201 and isinstance(answer, dict):
            for n in old:
                call(token, "POST", f"/repos/{slug}/issues/{n}/comments",
                     {"body": f"Дальше — в #{answer.get('number')}."})
                call(token, "PATCH", f"/repos/{slug}/issues/{n}",
                     {"state": "closed", "state_reason": "completed"})
    if status != 201:
        print(f"{what}: GitHub ответил {status}: {str(answer)[:300]}")
        return 1
    print(f"{what}:", answer.get("html_url", "") if isinstance(answer, dict) else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

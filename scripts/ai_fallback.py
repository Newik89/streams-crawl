# -*- coding: utf-8 -*-
"""AI-запасной разбор (этап 6д): сломанная разметка не останавливает источник.

Подготовлено 02.09.2026, **подключение — в конце проекта** (решение
владельца): без переменной `STREAMS_AI=on` шаг с моделью не выполняется.
Включение: репозиторий GitHub → Settings → Variables → `STREAMS_AI` = `on`.

Как работает:
  --detect   найти сайты, где страница живая («расписание есть»), а парсер
             дал 0 сырых строк — признак сломанной разметки. Сети и модели
             не касается, работает всегда.
  --run      для каждого такого сайта отдать текст страницы бесплатной
             модели (по умолчанию Google AI Studio, ключ — секрет
             STREAMS_AI_KEY) и достать матчи в recon/raw_live/ai_rows.json.
  --merge    подмешать достанутое в games.json (пометка "ai": 1) — дальше
             обычный путь: games_import, витрина.

Модель — только запасной путь: её строки помечены, времени верим по поясу
сайта из плана обхода, а как только парсер починен, слой сам замолкает
(детект перестаёт находить сайт).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "recon" / "raw_live"
AI_ROWS = RAW / "ai_rows.json"

#: справочники дают 0 строк в ленту по замыслу — это не поломка
REFERENCE_DOMAINS = {"flashscore.mobi", "sporteventz.com", "liveonsat.com",
                     "livesoccertv.com"}

# Провайдер модели настраивается переменными окружения (в Actions — из
# секретов). GitHub Models закрылся 30.07.2026, поэтому по умолчанию —
# бесплатный тариф Google AI Studio (ключ без карты, лимитов хватает):
#   AI_API_URL  — OpenAI-совместимый адрес chat/completions
#   AI_MODEL    — имя модели
#   AI_API_KEY  — ключ (секрет STREAMS_AI_KEY в репозитории)
MODELS_URL = os.environ.get(
    "AI_API_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
MODEL = os.environ.get("AI_MODEL", "gemini-2.0-flash")

PROMPT = (
    "Ниже текст страницы телепрограммы. Выпиши ТОЛЬКО спортивные трансляции "
    "(футбол, баскетбол, теннис) в JSON: {\"games\": [{\"date\": \"YYYY-MM-DD "
    "или пусто\", \"time\": \"HH:MM\", \"home\": \"...\", \"away\": \"...\", "
    "\"league\": \"...\", \"channel\": \"...\", \"live\": true/false}]}. "
    "Время оставляй как на странице. Повторы и записи не включай. "
    "Ответ — только JSON, без пояснений.")


def _bare(domain: str) -> str:
    return (domain or "").removeprefix("www.")


def detect() -> dict[str, dict]:
    """Сайт «расписание есть», а сырых строк 0 → кандидат на запасной разбор."""
    # utf-8-sig: терпим BOM, если файл готовили руками на Windows
    report = json.loads((RAW / "report.json").read_text(encoding="utf-8-sig"))
    games = json.loads((RAW / "games.json").read_text(encoding="utf-8-sig"))
    counts = games.get("разобрано", {})
    out: dict[str, dict] = {}
    for row in report.get("строки", []):
        bare = _bare(row.get("domain", ""))
        if (row.get("итог") == "расписание есть"
                and bare not in REFERENCE_DOMAINS
                and counts.get(bare, 0) == 0
                and row.get("файл") and (RAW / row["файл"]).exists()):
            out.setdefault(bare, {"files": [], "channel": row.get("channel", ""),
                                  "day": row.get("day", "")})
            out[bare]["files"].append(row["файл"])
    return out


def _page_text(path: Path, limit: int = 60000) -> str:
    """Видимый текст страницы: модели не нужны скрипты и стили."""
    html = path.read_text(encoding="utf-8", errors="replace")
    try:
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        for bad in tree.css("script, style, noscript"):
            bad.decompose()
        text = tree.body.text(separator="\n") if tree.body else html
    except Exception:                                    # noqa: BLE001
        text = html
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)[:limit]


def _ask_model(text: str) -> list[dict]:
    token = os.environ.get("AI_API_KEY", "")
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT + "\n\n" + text}],
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(MODELS_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        answer = json.loads(resp.read())
    content = answer["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`\n")
        content = content[content.find("{"):]
    return json.loads(content).get("games", [])


def run(candidates: dict[str, dict]) -> int:
    if os.environ.get("STREAMS_AI", "").lower() != "on":
        print("STREAMS_AI не включён — запасной разбор подготовлен, но спит "
              "(включение — в конце проекта, переменная репозитория)")
        return 0
    if not os.environ.get("AI_API_KEY"):
        print("нет AI_API_KEY (секрет STREAMS_AI_KEY) — модель недоступна, "
              "ждём ключ от владельца")
        return 0
    got: dict[str, list] = {}
    for domain, info in candidates.items():
        rows: list[dict] = []
        for fname in info["files"][:3]:      # беречь бесплатный лимит модели
            try:
                rows += _ask_model(_page_text(RAW / fname))
            except Exception as e:           # noqa: BLE001
                print(f"  {domain} {fname}: модель не ответила — "
                      f"{type(e).__name__}: {e}")
        if rows:
            got[domain] = rows
            print(f"  {domain}: модель достала строк — {len(rows)}")
    AI_ROWS.write_text(json.dumps(
        {"когда": datetime.now().strftime("%Y-%m-%d %H:%M"), "sites": got},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"итог: {AI_ROWS}")
    return 0


def merge() -> int:
    """Подмешать ai_rows.json в games.json — обычным форматом игр."""
    if not AI_ROWS.exists():
        print("ai_rows.json нет — подмешивать нечего")
        return 0
    plan = {}
    plan_path = ROOT / "data" / "crawl_plan.json"
    if plan_path.exists():
        plan = {s["domain"]: s.get("timezone")
                for s in json.loads(plan_path.read_text(encoding="utf-8"))
                .get("sources", [])}
    kyiv = ZoneInfo("Europe/Kyiv")
    payload = json.loads((RAW / "games.json").read_text(encoding="utf-8"))
    data = json.loads(AI_ROWS.read_text(encoding="utf-8"))
    added = 0
    for domain, rows in data.get("sites", {}).items():
        zone = ZoneInfo(plan.get(domain) or "Europe/Kyiv")
        for r in rows:
            try:
                d = date.fromisoformat(r.get("date") or date.today().isoformat())
                hh, mm = str(r.get("time", "")).split(":")
                start = datetime(d.year, d.month, d.day, int(hh), int(mm),
                                 tzinfo=zone).astimezone(kyiv)
            except (ValueError, TypeError):
                continue
            if not r.get("home") or not r.get("away"):
                continue
            payload["games"].append({
                "sport": "", "league": (r.get("league") or "")[:120],
                "home": r["home"].strip(), "away": r["away"].strip(),
                "start_kyiv": start.strftime("%Y-%m-%dT%H:%M"),
                "start_utc": start.astimezone(ZoneInfo("UTC"))
                .strftime("%Y-%m-%dT%H:%M"),
                "ai": 1,
                "entries": [{"source": domain,
                             "channel": (r.get("channel") or "").strip() or "?",
                             "url": "", "raw_title":
                                 f"{r['home']} - {r['away']} (AI)"}],
            })
            added += 1
    payload["игр"] = len(payload["games"])
    (RAW / "games.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"подмешано игр от модели: {added}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--detect", action="store_true", help="только показать кандидатов")
    ap.add_argument("--run", action="store_true", help="спросить модель")
    ap.add_argument("--merge", action="store_true", help="подмешать в games.json")
    args = ap.parse_args()

    candidates = detect()
    print("кандидаты на запасной разбор (страница живая, строк 0):")
    for domain, info in candidates.items() or []:
        print(f"  {domain}: файлов {len(info['files'])}")
    if not candidates:
        print("  нет — все живые страницы разобраны своими парсерами")
    if args.run:
        code = run(candidates)
        if code:
            return code
    if args.merge:
        return merge()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

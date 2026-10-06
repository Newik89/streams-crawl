# -*- coding: utf-8 -*-
r"""Сравнить два плана обхода по ВСЕМ полям каждого сайта.

Зачем: план (`data/crawl_plan.json`) пересобирается на сервере из базы, и
пересборка уже молча теряла настройки. 22.09 сервер пересобрал план с
отставшей копии настроек, и `cosmotetv.gr` 11 дней отдавал ноль игр —
настройка жила только в прежнем файле плана (`ГРАБЛИ.md`, строка про
`crawl_plan.py`). Сверять домены глазами мало: пропажа была внутри полей
одного сайта.

Что показывает: исчезнувшие и новые домены, а у общих — каждое поле, где
значения разошлись (адреса страниц, `include`, `parser`, `post_fields`,
`days_ahead`, заголовки…). Список адресов сравнивается как набор, поэтому
переставленные строки за изменение не считаются.

    venv/bin/python scripts/plan_diff.py /root/backups/crawl_plan.json.2026-10-06 \
        data/crawl_plan.json

Ничего не меняет, к сайтам не обращается. Код возврата 1 — отличия есть
(удобно в цепочке: пересобрал → сверил → выложил).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

#: поля, которые у сайта сравниваем по отдельности; «channels» разбираем
#: особо — это список страниц, порядок в нём не важен
ОСОБОЕ = "channels"


def прочитать(путь: str) -> dict[str, dict]:
    """План → {домен: карточка сайта}."""
    d = json.load(io.open(путь, encoding="utf-8"))
    сайты = d.get("sources", d) if isinstance(d, dict) else d
    if isinstance(сайты, dict):
        сайты = list(сайты.values())
    return {s.get("domain", ""): s for s in сайты}


def страницы(карточка: dict) -> set[tuple[str, str]]:
    """Страницы сайта как набор пар (имя канала, адрес)."""
    out = set()
    for ch in карточка.get(ОСОБОЕ) or []:
        if isinstance(ch, dict):
            out.add((str(ch.get("name") or ""), str(ch.get("pattern") or "")))
        else:
            out.add(("", str(ch)))
    return out


def сравнить(старый: dict[str, dict], новый: dict[str, dict]) -> int:
    пропали = sorted(set(старый) - set(новый))
    пришли = sorted(set(новый) - set(старый))
    изменились = 0
    if пропали:
        print(f"ПРОПАЛИ сайты ({len(пропали)}): {', '.join(пропали)}")
    if пришли:
        print(f"новые сайты ({len(пришли)}): {', '.join(пришли)}")
        for d in пришли:
            print(f"   {d}: страниц {len(страницы(новый[d]))}")
    for домен in sorted(set(старый) & set(новый)):
        a, b = старый[домен], новый[домен]
        строки = []
        for поле in sorted(set(a) | set(b)):
            if поле == ОСОБОЕ:
                continue
            if a.get(поле) != b.get(поле):
                строки.append(f"      {поле}: {a.get(поле)!r} → {b.get(поле)!r}")
        было, стало = страницы(a), страницы(b)
        if было != стало:
            ушли = sorted(было - стало)
            добавились = sorted(стало - было)
            строки.append(f"      страниц было {len(было)}, стало {len(стало)}")
            for имя, адрес in ушли[:10]:
                строки.append(f"         ушла «{имя}» {адрес}")
            for имя, адрес in добавились[:10]:
                строки.append(f"         пришла «{имя}» {адрес}")
        if строки:
            изменились += 1
            print(f"   {домен}:")
            print("\n".join(строки))
    print(f"\nсайтов: было {len(старый)}, стало {len(новый)}; "
          f"пропавших {len(пропали)}, новых {len(пришли)}, "
          f"изменённых {изменились}")
    return 1 if (пропали or пришли or изменились) else 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("старый", help="план до пересборки (копия из /root/backups)")
    ap.add_argument("новый", help="план после пересборки")
    args = ap.parse_args()
    for путь in (args.старый, args.новый):
        if not Path(путь).exists():
            print(f"нет файла: {путь}")
            return 2
    return сравнить(прочитать(args.старый), прочитать(args.новый))


if __name__ == "__main__":
    raise SystemExit(main())

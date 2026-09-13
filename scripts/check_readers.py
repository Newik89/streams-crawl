# -*- coding: utf-8 -*-
r"""Проверка читалок: какие из них сейчас пробивают закрытый сайт.

Часть сайтов не пускает никакие серверы — ни раннер GitHub, ни наш
DigitalOcean (`cosmotetv.gr` отвечает им заглушкой Imperva, а владельцу в
браузере отдаёт всё расписание). Капчу мы не обходим и свой адрес не
подделываем: такие страницы берёт открытая читалка — публичный сервис,
который отдаёт разметку чужой страницы.

Читалки живут своей жизнью: сегодня отвечает одна, завтра она лежит (522) или
упирается в лимит (429). Поэтому список проверяется отдельно от обхода, а
результат ложится в `data/readers.json` — его читает `app/fetch.py` и ходит
по рабочим, в порядке от быстрой к медленной.

Запуск (сам ходит в сеть — только с сервера или из GitHub Actions):

    python scripts/check_readers.py
    python scripts/check_readers.py --url https://пример/страница --word Ποδόσφαιρο

Проверка идёт по одному контрольному адресу: читалка засчитывается, только
если вернула большую страницу с контрольным словом внутри. Иначе засчитать
нельзя — половина сервисов на отказ отвечает бодрым `200` с пустышкой.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import fetch                                        # noqa: E402

OUT = ROOT / "data" / "readers.json"
#: контрольная страница: закрыта для серверов и заведомо содержит слово
CONTROL_URL = ("https://www.cosmotetv.gr/program?date=1788642000"
               "&category=%CE%91%CE%B8%CE%BB%CE%B7%CF%84%CE%B9%CE%BA%CE%AC")
CONTROL_WORD = "Ποδόσφαιρο"
TIMEOUT = 90


def check(pattern: str, extra: dict, url: str, word: str) -> dict:
    """Одна читалка: что ответила и годится ли."""
    import requests

    # переводчик Google собирает адрес по-своему (`mojtv-hr.translate.goog`)
    части = urlsplit(url)
    translate = (f"https://{части.netloc.replace('-', '--').replace('.', '-')}"
                 f".translate.goog{части.path}"
                 f"{'?' + части.query + '&' if части.query else '?'}"
                 f"_x_tr_sl=auto&_x_tr_tl=en&_x_tr_hl=en")
    through = pattern.format(url=url, enc=quote(url, safe=""),
                             translate=translate)
    name = urlsplit(through).netloc
    started = time.monotonic()
    try:
        answer = requests.get(through, timeout=TIMEOUT,
                              headers={**fetch.headers(fetch.AGENTS[0]), **extra})
    except Exception as exc:
        return {"читалка": name, "шаблон": pattern, "заголовки": extra,
                "годится": False, "почему": f"{type(exc).__name__}",
                "секунд": round(time.monotonic() - started, 1)}
    if "charset" not in (answer.headers.get("content-type") or "").lower():
        answer.encoding = "utf-8"
    html = answer.text
    spent = round(time.monotonic() - started, 1)
    if answer.status_code != 200:
        why = f"HTTP {answer.status_code}"
    elif fetch.protection_text(html):
        why = "принесла заглушку защиты"
    elif len(html) < fetch.READER_MIN_BYTES:
        why = f"пусто ({len(html)} байт)"
    elif word and word not in html:
        why = "страница без контрольного слова"
    else:
        why = ""
    return {"читалка": name, "шаблон": pattern, "заголовки": extra,
            "годится": not why, "почему": why, "байт": len(html), "секунд": spent}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=CONTROL_URL, help="контрольный адрес")
    ap.add_argument("--word", default=CONTROL_WORD, help="слово, которое обязано быть")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    print(f"проверяю {len(fetch.READERS)} читалок на {args.url[:60]}…\n")
    rows = []
    for pattern, extra in fetch.READERS:
        row = check(pattern, extra, args.url, args.word)
        rows.append(row)
        mark = "да " if row["годится"] else "нет"
        print(f"  {mark} {row['читалка'].ljust(28)} {row.get('байт', 0):>8} байт  "
              f"{row['секунд']:>5} с  {row['почему']}")

    good = [r for r in rows if r["годится"]]
    good.sort(key=lambda r: r["секунд"])           # быструю ставим первой
    Path(args.out).write_text(json.dumps({
        "проверено": time.strftime("%Y-%m-%d %H:%M"),
        "контрольный адрес": args.url,
        "рабочие": [{"шаблон": r["шаблон"], "заголовки": r["заголовки"],
                     "читалка": r["читалка"], "секунд": r["секунд"]} for r in good],
        "все": rows,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nрабочих: {len(good)} из {len(rows)} → {args.out}")
    if not good:
        print("НИ ОДНА НЕ ОТВЕТИЛА — сайты из VIA_READER в этом обходе не откроются")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
r"""Прогон парсера по четырём пилотным сайтам — по СОХРАНЁННЫМ страницам.

К сайтам скрипт не обращается вообще: страницы уже лежат в `recon/raw_deep/`
(правило из `HANDOFF.md` → «Грабли»: лишние обходы — риск бана по IP).
Поэтому его можно гонять сколько угодно, пока правится логика.

Что показывает:
  * сколько блоков разобрано, сколько прошло отсев и почему отсеялось остальное;
  * найден ли контрольный матч `Middlesbrough vs West Brom` на каждом сайте
    и сходится ли у всех время после перевода в Киев.

Запуск:
    venv\Scripts\python.exe scripts/parse_pilots.py
    venv\Scripts\python.exe scripts/parse_pilots.py --all   (и отсеянные тоже)
"""

from __future__ import annotations

import gzip
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import live, pipeline, sport                      # noqa: E402
from app.parsers import nova_bg, sporttv_pt, teleman_pl, tv_nova_cz  # noqa: E402

DAY = date(2026, 8, 29)          # день, за который сохранены копии
CONTROL = ("middlesbro", "мидълзбро")   # контрольный матч, ищем по хозяевам

RAW = ROOT / "recon" / "raw_deep"
SPORT_CHANNELS_CZ = {f"nova-sport-{i}" for i in range(1, 7)}


def read(name: str) -> str:
    path = RAW / name
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace").read()
    return path.read_text(encoding="utf-8", errors="replace")


def pilots():
    """Четыре сайта: как читаем страницу и чем разбираем."""
    yield ("nova.bg  (Болгария)", lambda: nova_bg.parse(
        read("nova.bg.html"), day=DAY, tz=nova_bg.TZ,
        url="https://nova.bg/schedule/index/4/2026/08/29/"))
    yield ("tv.nova.cz (Чехия)", lambda: tv_nova_cz.parse(
        read("tv.nova.cz.full.html.gz"), day=DAY, channels=SPORT_CHANNELS_CZ,
        url="https://tv.nova.cz/program"))
    yield ("teleman.pl (Польша)", lambda: teleman_pl.parse(
        read("teleman.pl.html"), day=DAY, tz=teleman_pl.TZ,
        url="https://www.teleman.pl/program-tv/stacje/Eleven-Sports-2?date=2026-08-29"))
    yield ("sporttv.pt (Португалия)", lambda: sporttv_pt.parse(
        read("sporttv.pt.html"), day=DAY, tz=sporttv_pt.TZ,
        url="https://www.sporttv.pt/guia"))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")   # русский текст в консоли Windows
    show_all = "--all" in sys.argv
    markers, sports = live.load(), sport.load()
    control: list[str] = []
    total_ok = 0

    for title, load_rows in pilots():
        rows = pipeline.run(load_rows(), markers, sports)
        rows.sort(key=lambda r: (r.start_kyiv is None, r.start_kyiv))
        taken = [r for r in rows if r.ok]
        review = [r for r in rows if r.needs_review]
        total_ok += len(taken)

        print("=" * 78)
        print(f"{title}: блоков {len(rows)}, в ленту {len(taken)}, "
              f"на проверку {len(review)}")
        print("-" * 78)
        for row in taken:
            print(f"  {row.when}  {row.program.channel_raw[:14].ljust(14)} "
                  f"{row.home[:24].ljust(24)} — {row.away[:24].ljust(24)} "
                  f"[{row.sport}] {row.live_marker}")
            if any(k in (row.home + row.away).lower() for k in CONTROL):
                control.append(f"{title}: {row.when} Киев, "
                               f"{row.program.channel_raw}, {row.home} — {row.away}")
        if review:
            print("  ── на проверку владельцу ──")
            for row in review:
                print(f"  {row.when}  {row.program.title[:52].ljust(52)} {row.reason}")
        why = Counter(r.reason for r in rows if not r.ok and not r.needs_review)
        if why:
            print("  ── отсеяно ──")
            for reason, n in why.most_common():
                print(f"  {str(n).rjust(4)}  {reason}")
        if show_all:
            print("  ── все отсеянные построчно ──")
            for row in rows:
                if not row.ok:
                    print(f"  {row.when}  {row.program.title[:46].ljust(46)} {row.reason}")

    print("=" * 78)
    print(f"ИТОГО в ленту: {total_ok} событий за {DAY.strftime('%d.%m.%Y')}")
    print(f"\nКонтрольный матч Middlesbrough vs West Brom — "
          f"найден на {len(control)} сайтах из 4:")
    for line in control:
        print("  •", line)
    return 0 if len(control) >= 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())

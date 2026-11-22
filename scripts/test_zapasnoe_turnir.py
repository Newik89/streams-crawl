# -*- coding: utf-8 -*-
r"""Запасное чтение: турнир без пары идёт названием турнира (книга 173, слово
владельца 22.11.2026: «такое просто и записывать как обговаривалось просто
название турнира, ведь это название турнира, а при повторном сборе ближе к
дате там возможно появятся имена»).

Повод: проба книги 171 на сборе 20.11.2026 — запасное чтение не вернуло 12
отметок из 267: «Nitto ATP Finals: Halve Finale» (ziggosport.nl), «Τένις:
Nitto ATP Finals 2026 (Ζ)» (cosmotetv.gr). Пометку эфира запасное чтение не
видит, а правило Т5 `pipeline.tournament_whole` берёт турнир без пометки
только у сайта, который эфир не помечает вовсе.

Что сторожится:

1. `fallback_read.blind`: страница, все строки которой дало запасное чтение,
   — «сайт эфир не помечает»; обычная страница и пустая — нет;
2. строка запасного чтения с названием турнира, в минуту матча этого турнира
   по эталону — игра «название турнира — tournament»; у сайта с честной
   пометкой (обычное чтение, пометки нет) — по-прежнему нет;
3. турнира в эталоне рядом с показом нет — не игра; повтор и обзор — не игра;
4. детектор: `parse_live` передаёт отсеву `fallback_read.blind`.

В сеть не ходит, база не нужна:

    python scripts/test_zapasnoe_turnir.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ["STREAMS_DB"] = str(Path(tempfile.mkdtemp(prefix="zapturnir-")) / "t.db")

from app import broadcast, fallback_read, live, pipeline, site_lang, sport  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import Reference  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def когда(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=KYIV)


M, ВИДЫ = live.load(), sport.load()
ТУРИН = "ATP - SINGLES: Finals - Turin (World), hard (indoor)"
судья = Reference([{"sport": "T", "home": "Alcaraz C.", "away": "Tiafoe F.", "league": ТУРИН, "fs_id": "t1",
                    "start_kyiv": "2026-11-21T13:00"}])


def строка(title: str, start: str = "2026-11-21T13:00", запасное: bool = True) -> Program:
    extra = {fallback_read.MARK: True, "day": start[:10]} if запасное else {}
    return Program(channel_raw="Ziggo Sport 4", title=title, start=когда(start), match_raw=" ", live_raw="",
                   extra=extra)


def разбор(домен: str, programs: list):
    """Как в `parse_live`: отсеву говорим, помечает ли сайт эфир."""
    guess = fallback_read.blind(programs)
    return [pipeline.classify(p, M, ВИДЫ, reference=судья, langs=site_lang.of(домен), guess_site=guess)
            for p in programs]


print("1. `blind`: страницу прочитало запасное чтение")
проверка("все строки с пометкой запасного чтения — да", fallback_read.blind([строка("A"), строка("B")]))
проверка("обычная страница — нет", fallback_read.blind([строка("A", запасное=False)]), False)
проверка("часть строк своя — нет", fallback_read.blind([строка("A"), строка("B", запасное=False)]), False)
проверка("пустая страница — нет", fallback_read.blind([]), False)

print("2. Турнир без пары в минуту матча турнира по эталону")
for домен, заголовок in (("ziggosport.nl", "Nitto ATP Finals: Halve Finale"),
                         ("cosmotetv.gr", "Τένις: Nitto ATP Finals 2026 (Ζ)"),
                         ("tv-program.aktuality.sk", "ATP: Nitto ATP Finals (6. den - dvouhra)")):
    row = разбор(домен, [строка(заголовок)])[0]
    проверка(f"{домен}: «{заголовок}» — игра названием турнира",
             (row.ok, row.away), (True, broadcast.SESSION))
row = разбор("ziggosport.nl", [строка("Nitto ATP Finals: Halve Finale", запасное=False)])[0]
проверка("та же строка обычного чтения без пометки эфира — не игра (сайт эфир помечает сам)", row.ok, False)

print("3. Без подтверждения эталона, повтор и обзор — не игра")
проверка("матча турнира рядом с показом нет (через 9 часов)",
         разбор("ziggosport.nl", [строка("Nitto ATP Finals: Halve Finale", start="2026-11-21T22:00")])[0].ok, False)
проверка("повтор и обзор в заголовке",
         [r.ok for r in разбор("ziggosport.nl", [строка("Nitto ATP Finals: Halve Finale (herhaling)"),
                                                 строка("ATP Finals Turin: Samenvatting")])], [False, False])

print("4. Детектор: `parse_live` передаёт отсеву `fallback_read.blind`")
код = (ROOT / "scripts" / "parse_live.py").read_text(encoding="utf-8")
проверка("вызов `fallback_read.blind(programs)` стоит рядом с `REPEAT_GUESS_DOMAINS`",
         "fallback_read.blind(programs)\n                         or _bare_domain(domain) in REPEAT_GUESS_DOMAINS))"
         in код.replace("\r\n", "\n"))

print(f"\nИТОГ: зелёных {зелёных}, красных {красных}")
sys.exit(1 if красных else 0)

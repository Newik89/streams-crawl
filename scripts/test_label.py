"""Книга 168 (19.11): общий читатель подписи канала в ячейке (`app/parsers/label.py`).

Сайты держат имя канала в разных местах ячейки и меняют их без спроса
(mojtv.hr 19.11: была подпись картинки, стал текст). `labels` собирает все
места по порядку П1–П4, `key` даёт имя для сверки.

Запуск: python scripts/test_label.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from selectolax.parser import HTMLParser  # noqa: E402

from app.parsers import label  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def подписи(разметка: str, что: str = "a") -> list[str]:
    return label.labels(HTMLParser(разметка).css_first(что))


print("Где лежит имя канала: порядок П1–П4")
проверка("П1: подпись картинки (`alt`), как у mojtv.hr до 19.11",
         подписи('<a href="/tv-program/kanal/62/sk1"><img src="62.png" alt="SK1 tv program"></a>'),
         ["SK1 tv program", "sk1"])
проверка("П3: имя текстом, как у mojtv.hr с 19.11 (настоящая ячейка, с переносами строк)",
         подписи('<a href="/tv-program/kanal/62/sk1" class="channel-logo-slot" id="channel-logo-62">\n'
                 '                        SK1 \n                    </a>'), ["SK1", "sk1"])
проверка("все места сразу — по порядку: alt, title картинки, title и aria-label ячейки, текст, хвост адреса",
         подписи('<a href="/k/7/hvost" title="Т" aria-label="А"><img alt="К1" title="К2"> Текст  ячейки </a>'),
         ["К1", "К2", "Т", "А", "Текст ячейки", "hvost"])
проверка("повторы и пустое убраны", подписи('<a href="/k/SK1" title="SK1"><img alt="SK1" title=""> SK1 </a>'), ["SK1"])
проверка("ячейка — сама картинка", подписи('<img alt="Nova Sport" title="Nova">', "img"), ["Nova Sport", "Nova"])
проверка("несколько картинок: сперва все `alt`, потом все `title`",
         подписи('<a><img alt="А1" title="Т1"><img alt="А2"></a>'), ["А1", "А2", "Т1"])
проверка("пустая ячейка — пусто", подписи("<a></a>"), [])
проверка("узла нет — пусто, без падения", label.labels(None), [])

print("Хвост адреса")
проверка("запрос, якорь и косая в конце не мешают",
         (label.tail_of("/tv-program/kanal/62/sk1/?x=1#y"), label.tail_of("https://site.tv/kanal/sk-golf")),
         ("sk1", "sk-golf"))
проверка("адреса нет или в нём нет пути — пусто", (label.tail_of(""), label.tail_of(None), label.tail_of("#")), ("", "", ""))

print("Имя для сверки")
проверка("регистр, пробелы, дефисы и знаки не важны",
         {label.key(x) for x in ("SK1", "sk 1", "Sk-1", " S.K_1 ")}, {"sk1"})
проверка("буквы других письменностей остаются", (label.key("Нова Спорт"), label.key("ΕΡΤ-1")), ("новаспорт", "ερτ1"))
проверка("пустое имя — пустой ключ", (label.key(""), label.key(None)), ("", ""))

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

# -*- coding: utf-8 -*-
"""Подпись канала в ячейке страницы — общий читатель (книга 168, 19.11.2026).

Случай: mojtv.hr 19.11 убрал из ячейки канала картинку-логотип и стал писать
имя канала просто текстом. Разборщик искал имя только в подписи к картинке
(`alt`) — и не прочитал со страниц ни одной строки, хотя вся сетка на месте.

Сайты держат имя канала в ячейке в разных местах и меняют их без спроса.
Поэтому разборщик страницы с несколькими каналами спрашивает не одно место,
а все по порядку (`labels`) и берёт первое имя, которое знает.

ПРАВИЛА (`labels`, где ищем — по порядку надёжности):
  П1. подпись картинки внутри ячейки: `alt`, потом `title`;
  П2. подпись самой ячейки: `title`, потом `aria-label`; за ней — те же
      подписи ссылок внутри ячейки (книга 170: у sports.kz ячейка — пункт
      списка, а имя стоит в `title` ссылки внутри него);
  П3. видимый текст ячейки;
  П4. хвост адреса ячейки и ссылок внутри неё:
      «/tv-program/kanal/62/sk1» → «sk1».
Пробелы сжаты, пустое и повторы убраны. Ячейка может быть из нескольких
узлов (логотип и подпись рядом с ним) — тогда узлы идут по очереди.

ПРАВИЛА (`pick`, какая из подписей — имя канала; книга 170, 20.11.2026).
Случай: кроме mojtv.hr, имя канала из ОДНОГО места ячейки брали ещё восемь
разборщиков — перенеси сайт имя из подписи картинки в текст, и сайт
замолчал бы так же. Теперь разборщик спрашивает имя здесь:
  В1. Подписи по порядку: первой — та, где имя стоит у сайта сегодня (её
      называет разборщик, `first`), за ней все подписи ячейки (`labels`).
      Пока сайт ничего не менял, имя выходит то же, что и раньше.
  В2. Сайт украшает имя («Ver canal DAZN 1») — разборщик даёт `clean`,
      украшение снимается с каждой подписи.
  В3. Есть список каналов владельца (`known`): берём первую подпись,
      которая в списке есть, — буква в букву либо по `key` (без регистра,
      пробелов и знаков) — и отдаём имя так, как оно записано в списке.
      Два имени списка с одним ключом сверяются только буква в букву.
      `keep_case` — исключение для сайта, у которого разборщик и раньше
      сверял имя без регистра (movistarplus.es пишет «DAZN LALIGA», в
      списке «DAZN LaLiga», и база знает канал под написанием сайта):
      подпись, отличная от списочной только регистром букв, отдаётся как
      на сайте.
  В4. Знакомой подписи нет или списка нет — первая подпись из П1–П3 не
      длиннее `NAME_MAX` знаков (длиннее — это не имя канала, а текст).
      Хвост адреса (П4) — примета, а не имя: годится только знакомый.
      Чужой канал разборщик отсеет сам, как и раньше.
  В5. Ничего не нашлось — пустая строка; что делать дальше, решает разборщик.

`key` — имя для сверки: без регистра, пробелов, дефисов и знаков
(«SK1», «sk-1», «Sk 1» → «sk1»).
"""
from __future__ import annotations

import re

_SPACE = re.compile(r"\s+")
_NOT_WORD = re.compile(r"[\W_]+", re.UNICODE)


def _clean(text: str | None) -> str:
    return _SPACE.sub(" ", text or "").strip()


def key(name: str | None) -> str:
    """Имя канала для сверки: только буквы и цифры, в нижнем регистре."""
    return _NOT_WORD.sub("", (name or "").lower())


def tail_of(href: str | None) -> str:
    """П4: последний кусок адреса без запроса и якоря."""
    path = (href or "").split("#", 1)[0].split("?", 1)[0].rstrip("/")
    return _clean(path.rsplit("/", 1)[-1]) if "/" in path else ""


#: В4: подпись длиннее — не имя канала (самое длинное имя в списках владельца
#: на 20.11.2026 — 28 знаков)
NAME_MAX = 60


def _places(cell) -> list[tuple[str, bool]]:
    """Подписи ячейки по порядку П1–П4: (подпись, это хвост адреса).
    `cell` — узел selectolax либо список узлов (пустые места в нём — None)."""
    out: list[tuple[str, bool]] = []
    seen: set[str] = set()

    def add(text: str | None, tail: bool = False) -> None:
        text = _clean(text)
        if text and text not in seen:
            seen.add(text)
            out.append((text, tail))

    for node in (cell if isinstance(cell, (list, tuple)) else [cell]):
        if node is None:
            continue
        images = [node] if node.tag == "img" else node.css("img")
        # сама ячейка и ссылки внутри неё (повтор самой ячейки уберёт `seen`)
        cells = [node] if node.tag == "img" else [node, *node.css("a")]
        for attr in ("alt", "title"):                               # П1
            for img in images:
                add(img.attributes.get(attr))
        for one in cells:                                           # П2
            for attr in ("title", "aria-label"):
                add(one.attributes.get(attr))
        add(node.text())                                            # П3
        for one in cells:                                           # П4
            add(tail_of(one.attributes.get("href")), tail=True)
    return out


def labels(cell) -> list[str]:
    """Все подписи ячейки канала по порядку П1–П4."""
    return [text for text, _ in _places(cell)]


def pick(cell, known=None, *, first: str | None = None, clean=None,
         keep_case: bool = False) -> str:
    """Имя канала ячейки — правила В1–В5 в шапке модуля.
    `known` — список каналов владельца по сайту (или None), `first` —
    подпись, где имя стоит сегодня, `clean` — как снять украшение сайта,
    `keep_case` — регистр букв оставить как на сайте (В3)."""
    places: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for text, tail in [(_clean(first), False), *_places(cell)]:     # В1
        if clean is not None:                                       # В2
            text = _clean(clean(text))
        if text and text not in seen:
            seen.add(text)
            places.append((text, tail))
    if known:                                                       # В3
        exact = set(known)
        by_key: dict[str, str] = {}
        twice: set[str] = set()
        for name in exact:
            k = key(name)
            if k in by_key:
                twice.add(k)
            by_key[k] = name
        for text, _ in places:
            if text in exact:
                return text
            k = key(text)
            if k and k in by_key and k not in twice:
                same_letters = text.casefold() == by_key[k].casefold()
                return text if keep_case and same_letters else by_key[k]
    return next((text for text, tail in places                      # В4, В5
                 if not tail and len(text) <= NAME_MAX), "")

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
  П2. подпись самой ячейки: `title`, потом `aria-label`;
  П3. видимый текст ячейки;
  П4. хвост адреса ячейки: «/tv-program/kanal/62/sk1» → «sk1».
Пробелы сжаты, пустое и повторы убраны. Какое из имён «своё», решает
разборщик сайта: общий читатель только собирает, где имя может лежать.

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


def labels(node) -> list[str]:
    """Все подписи ячейки канала по порядку П1–П4 (узел selectolax)."""
    out: list[str] = []

    def add(text: str | None) -> None:
        text = _clean(text)
        if text and text not in out:
            out.append(text)

    if node is None:
        return out
    images = [node] if node.tag == "img" else node.css("img")
    for attr in ("alt", "title"):                                   # П1
        for img in images:
            add(img.attributes.get(attr))
    for attr in ("title", "aria-label"):                            # П2
        add(node.attributes.get(attr))
    add(node.text())                                                # П3
    add(tail_of(node.attributes.get("href")))                       # П4
    return out

# -*- coding: utf-8 -*-
"""Распаковка `__NUXT_DATA__` (формат devalue).

Сайты на Nuxt 3 кладут все данные страницы в один массив, где вместо самих
значений стоят **номера элементов этого же массива**: так они экономят место
на повторах. `sporttv.pt` — как раз такой (`recon/deep_report.md`, разд. 4).

Пример: `[{"canal":3,"nome":5}, ..., "SPORT.TV2"]` — чтобы прочитать `canal`,
надо взять элемент №3, и так по цепочке.

Отрицательные номера — служебные значения самого формата: `-1` это
`undefined`, `-3` — `NaN`, `-4` и `-5` — бесконечности. Нам они не нужны,
но пропустить их нельзя, иначе распаковка встанет.
"""

from __future__ import annotations

import json
import re

_SCRIPT = re.compile(
    r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S | re.I)

_HOLE = object()  # пропуск в массиве, в Python его заменяем на None

_SPECIALS = {-1: None, -2: _HOLE, -3: float("nan"),
             -4: float("inf"), -5: float("-inf"), -6: 0.0}


def extract_payload(html: str) -> list | None:
    """Достаёт сам массив из HTML. Нет скрипта — None."""
    m = _SCRIPT.search(html)
    if not m:
        return None
    return json.loads(m.group(1))


def unflatten(flat: list, index: int = 0):
    """Разворачивает массив в обычные словари и списки.

    Ссылки по кругу (элемент ссылается сам на себя через цепочку) обрываются
    значением `None`: в данных расписания их нет, но подстраховка дешёвая.
    """
    seen: dict[int, object] = {}

    def walk(i, stack: frozenset):
        if isinstance(i, int) and i < 0:
            v = _SPECIALS.get(i, None)
            return None if v is _HOLE else v
        if not isinstance(i, int) or i >= len(flat):
            return None
        if i in seen:
            return seen[i]
        if i in stack:
            return None
        node = flat[i]
        here = stack | {i}
        if isinstance(node, list):
            # ["Date", n] и подобные — тип, названный первым элементом
            if node and node[0] == "Date":
                out = walk(node[1], here)
            elif node and node[0] in ("Set", "Map", "RegExp", "BigInt", "null"):
                out = [walk(x, here) for x in node[1:]]
            else:
                out = [walk(x, here) for x in node]
        elif isinstance(node, dict):
            out = {k: walk(v, here) for k, v in node.items()}
        else:
            out = node
        seen[i] = out
        return out

    return walk(index, frozenset())


def rows_with(flat: list, key: str) -> list[dict]:
    """Все словари массива, где есть ключ `key`, уже развёрнутые.

    На `sporttv.pt` передачи узнаются по полю `tipoEmissao` — искать их так
    надёжнее, чем идти по вложенности страницы: вёрстку авторы меняют,
    состав полей передачи — нет.
    """
    out = []
    for i, node in enumerate(flat):
        if isinstance(node, dict) and key in node:
            out.append(unflatten(flat, i))
    return out

# -*- coding: utf-8 -*-
r"""Правила канонических имён каналов — правки владельца (6е, B4/B10 и по ходу).

Жили в `scripts/channel_names.py` и применялись только его ручным запуском —
поэтому канал, заведённый ПОСЛЕ прогона, оставался с сырым именем: 19.09
владелец увидел на витрине «אתר ערוץ הספורט» ивритом (#3039), хотя вся
израильская линейка давно переведена. Теперь правила лежат здесь и их
применяют двое:

  - `store._channel_id` — новый канал сразу рождается с каноническим именем
    (а если такое имя в стране уже есть, `remember_channel` найдёт его по
    паре (имя, страна) и просто добавит алиас — дубля не будет);
  - `scripts/channel_names.py` — причёсывает уже заведённые каналы; он
    запускается сервером после каждой заливки, так что правило, добавленное
    позже канала, тоже доедет само.

Правило — (страна, регулярка, замена). Канал опознаётся парой (имя, страна),
поэтому правил без страны не пишем.
"""

from __future__ import annotations

import re

RULES = [
    # владелец 03.09: «Cytavision Sports4 HD» → «Cytavision Sports 4»
    ("CY", re.compile(r"^Cytavision Sports(\d+) HD$"), r"Cytavision Sports \1"),
    # B4: вся линейка sporttv.pt — точку на пробел
    ("PT", re.compile(r"^SPORT\.TV(\d+)$"), r"SPORT TV \1"),
    ("PT", re.compile(r"^SPORT\.TV \+$"), "SPORT TV +"),
    # владелец 04.09: страну у ВСЕХ каналов рисует витрина префиксом
    # «BG| …» — свой префикс из имени MAX Sport убираем (был с 03.09),
    # иначе задвоится
    ("BG", re.compile(r"^bg\| MAX Sport (\d+)$"), r"MAX Sport \1"),
    # B10: канонические имена sport5.co.il — латиницей, вся линейка.
    # Правила без групп: подстановка \1 однажды превратилась в мусорный
    # байт (см. журнал 03.09), поэтому каждое имя — явной парой
    ("IL", re.compile(r"^ספורט 5 Live$"), "Sport 5 Live"),
    ("IL", re.compile(r"^ספורט 5 Stars$"), "Sport 5 Stars"),
    ("IL", re.compile(r"^ספורט 5 Gold$"), "Sport 5 Gold"),
    ("IL", re.compile(r"^ספורט 5\+$"), "Sport 5 Plus"),
    ("IL", re.compile(r"^ספורט 5$"), "Sport 5"),
    # 19.09, #3039: «сайт Спортканала» у sport5.co.il — по-английски,
    # в пару к «ערוץ הספורט» → Sport Channel (✎ владельца)
    ("IL", re.compile(r"^אתר ערוץ הספורט$"), "Sport Channel Website"),
    # владелец 04.09: голландская линейка ESPN — «ESPN» без номера значит
    # первый канал; на источнике второй пишут «ESPN 2», так и на витрине
    ("INT", re.compile(r"^ESPN Netherlands$"), "ESPN 1"),
    ("INT", re.compile(r"^ESPN (\d) Netherlands$"), r"ESPN \1"),
    # владелец 05.09: OneSoccer -> One Soccer
    ("CA", re.compile(r"^OneSoccer$"), "One Soccer"),
]


def apply(name: str, country: str) -> str:
    """Каноническое имя по правилам; нет подходящего правила — имя как есть."""
    for rule_country, pattern, repl in RULES:
        if country != rule_country:
            continue
        new = pattern.sub(repl, name)
        if new != name:
            return new
    return name

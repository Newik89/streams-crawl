# -*- coding: utf-8 -*-
"""Трансляция турнира без пары игроков (теннис).

Сайт часто показывает турнир целиком, не называя, кто играет: «ATP 500 Tokyo
- 1/4 Finale», «China Open - Beijing», «TÓQUIO 2026 - QUARTOS DE FINAL»,
«ATP 500: רבעי גמר - 2 משחקים». Разбор делит заголовок по тире и получает
«пару» из названия турнира и стадии: на витрине она стояла как «ATP 500
Tokyo vs 1/4 Finale», висела в «Names to fix» и портила долю игр без канона
(04.10: 48 из 84 таких «игр» — заголовки пяти сайтов).

Решение владельца 04.10: оставлять, показывать трансляцией турнира без «vs»;
назовёт сайт игроков — следующий сбор приносит матч с именами, а заголовок
уходит (`store.save_games` гасит его отметки, `store.schedule` прячет строку
без живых каналов).

Слова — `data/markers.json`, раздел `tournament`, пополняются без правки
кода. Достаточно слова в одной из сторон: у настоящей пары ни в одной
фамилии нет «ATP», «Open» или «Finale». Игру, которую узнал эталон
flashscore, заголовком не считаем никогда — это решает вызывающий.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .live import MARKERS_FILE, _flatten, _pattern, greek_plain

#: стадия дробью («1/4 Finale», «1/2 Finale B») и год турнира («TÓQUIO 2026»):
#: в словарь их не положить, а у игроков таких «слов» не бывает. Дробь пары
#: («Hijikata/Uesugi», «TBD/TBD») сюда не попадает — в ней нет цифр
_STAGE = re.compile(r"(?<![\w/])1/(?:2|4|8|16|32|64)(?![\w/])|(?<!\d)20\d\d(?!\d)")


@lru_cache(maxsize=4)
def _words(path: Path | None = None) -> re.Pattern | None:
    data = json.loads((path or MARKERS_FILE).read_text(encoding="utf-8"))
    return _pattern(_flatten(data.get("tournament")))


def _side(text: str) -> bool:
    text = greek_plain(text or "")
    if _STAGE.search(text):
        return True
    words = _words()
    return bool(words and words.search(text))


def is_title(sport: str, home: str, away: str) -> bool:
    """«Пара» — название турнира или стадии, а не игроки. Только теннис:
    там трансляция турнира без пары — обычная строка телепрограммы."""
    if (sport or "") != "T":
        return False
    return _side(home) or _side(away)

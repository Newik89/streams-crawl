# -*- coding: utf-8 -*-
"""Автоперевод названия лиги, которой нет в словаре лиг.

Решение владельца 12.10.2026: «переводить спортивные слова в названиях лиг
по словарю: «Кубок» → Cup, «плей-офф» → Playoff». До этого «автоперевод» был
только транслитом букв: на витрине висели «Kubok Germanii. 1/8 Finala»,
«Wnba - Pliiaof», «Sreshta Ot Grupovata Faza Na Fiba Europe Cup».

Правила по порядку (`auto_english`):
  1. фразы словаря (`data/league_words.json`, «фразы») — длинные первыми:
     «Кубок Германии» → «Germany Cup», «1/8 финала» → «Round of 16»;
  2. слова словаря («слова») — целыми словами: «плей-офф» → «Playoff»;
  3. сравнение без учёта регистра; у слова, написанного с заглавной, перевод
     тоже с заглавной;
  4. оставшиеся слова не латиницей — транслит (`names.suggest_canonical`),
     латиницу без совпадений не трогаем («Liga BPI» остаётся как есть).
Словарь правится без кода; новое слово — строкой в файл.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import names

WORDS_FILE = Path(__file__).resolve().parent.parent / "data" / "league_words.json"


@lru_cache(maxsize=1)
def _table() -> tuple[re.Pattern | None, dict[str, str]]:
    try:
        data = json.loads(WORDS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, {}
    pairs: dict[str, str] = {}
    for block in ("фразы", "слова"):
        for k, v in (data.get(block) or {}).items():
            if isinstance(k, str) and isinstance(v, str) and k.strip():
                pairs.setdefault(" ".join(k.lower().split()), v)
    if not pairs:
        return None, {}
    keys = sorted(pairs, key=len, reverse=True)
    body = "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in keys)
    return re.compile(rf"(?<!\w)(?:{body})(?!\w)", re.I | re.U), pairs


def _non_latin(word: str) -> bool:
    return any(ord(c) > 0x2FF for c in word)


def auto_english(text: str | None) -> str:
    """Название лиги → английский по словарю спортивных слов, остальное
    не латиницей — транслит. Пустое — пустое."""
    text = (text or "").strip()
    if not text:
        return ""
    pattern, pairs = _table()
    if pattern is not None:
        def swap(m: re.Match) -> str:
            found = m.group(0)
            out = pairs.get(" ".join(found.lower().split()), found)
            # слово с заглавной — перевод с заглавной (правило 3)
            if found[:1].isupper() and out[:1].islower():
                out = out[:1].upper() + out[1:]
            return out
        text = pattern.sub(swap, text)
    words = text.split(" ")
    words = [names.suggest_canonical(w) if _non_latin(w) else w for w in words]
    return " ".join(w for w in words if w).strip()

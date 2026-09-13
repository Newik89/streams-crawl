# -*- coding: utf-8 -*-
"""Вид спорта по тексту страницы (ТЗ разд. 2 и 6).

Берём только футбол, баскетбол и теннис. Всё остальное — мото, NASCAR,
гольф, регби, сёрф — отбрасывается здесь, а не копится в базе: на одном
`sporttv.pt` за сутки таких блоков больше, чем матчей.

**Сначала проверяем чужие виды спорта, потом свои.** Порядок не случайный:
`americký fotbal` (это NFL) и `futebol americano` содержат слово «футбол»
целиком, и при обратном порядке американский футбол уехал бы в ленту как
обычный. На `tv.nova.cz` такие строки идут каждый день.

Не узнали спорт — событие не выбрасываем, а помечаем на проверку владельцем
(ТЗ разд. 6: «уходит в очередь модерации, а не в ленту»).

Слова лежат в `data/markers.json`, раздел `sport` — пополняются без правки кода.
Там же подраздел `кроме`: фразы, где слово спорта — часть чужого названия
(«AFC Wimbledon» — футбольный клуб, а не турнир; 07.09 игра #1455 уехала в
теннис). Такие фразы вырезаются из текста до проверки этой буквы.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .live import MARKERS_FILE, _flatten, _pattern, greek_plain

import json

#: буква вида спорта → как называем владельцу
NAMES = {"F": "футбол", "B": "баскетбол", "T": "теннис"}


@dataclass
class Sports:
    alien: object          # чужие виды спорта
    kinds: dict            # буква → шаблон слов
    exclude: dict | None = None   # буква → шаблон фраз, которые не считаются

    def detect(self, text: str) -> tuple[str | None, str]:
        """Буква вида спорта и слово, по которому решили.
        Чужой спорт — `("-", слово)`. Ничего не нашли — `(None, "")`."""
        if not text:
            return None, ""
        # греческие ударения снимаем и здесь: в заголовках их ставят как
        # придётся, «Ποδοσφαίρου» против словарного «ποδόσφαιρο» (10.09)
        text = greek_plain(text)
        if self.alien:
            skip = (self.exclude or {}).get("чужие")
            probe = skip.sub(" ", text) if skip else text
            m = self.alien.search(probe)
            if m:
                return "-", m.group(0)
        for letter, pattern in self.kinds.items():
            if not pattern:
                continue
            skip = (self.exclude or {}).get(letter)
            probe = skip.sub(" ", text) if skip else text
            m = pattern.search(probe)
            if m:
                return letter, m.group(0)
        return None, ""


def load(path: Path | None = None, override: dict | None = None) -> Sports:
    data = json.loads((path or MARKERS_FILE).read_text(encoding="utf-8"))
    node = (override or {}).get("sport") or data.get("sport") or {}
    skip = node.get("кроме") or {}
    return Sports(
        alien=_pattern(_flatten(node.get("чужие"))),
        kinds={letter: _pattern(_flatten(node.get(letter)))
               for letter in ("F", "B", "T")},
        exclude={letter: _pattern(_flatten(skip.get(letter)))
                 for letter in ("F", "B", "T", "чужие")},
    )

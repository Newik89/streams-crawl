# -*- coding: utf-8 -*-
r"""Каталог имён flashscore из истории эталона — для классификатора словаря.

Слово владельца 09.11.2026: «имена должны браться в первую очередь с
flashscore, а если нет этого вида спорта, турнира или лиги — тогда наш
алгоритм; чего нет и не было на flashscore — остаётся автопереводом и
проверяется поиском». Рабочий алгоритм имён (`app/canon.py`) не меняется:
каталог читает только то, что эталон уже кладёт каждый день.

Откуда: `results/games.json`, ключ «эталон» (кладёт `parse_live.py`) — игры
flashscore дня: вид, английские имена сторон, лига «СТРАНА: Лига», переводы
имён на языки местных зеркал flashscore (`names`: язык → [хозяева, гости]).
Каталог — все выпуски этого файла в истории git (с 13.09.2026: 168 выпусков,
~967 тыс. игр, ~22 тыс. имён — замер 09.11).

Правила каталога:
  Ф-к1. Имя flashscore — английское имя стороны как есть; сравнение — по
        `slovar_otchet.norm` (без диакритики, регистра, знаков).
  Ф-к2. Страна — часть лиги до «:»; турниры частей света и мира (WORLD,
        EUROPE, ASIA…) страной не считаются: клуб в Лиге чемпионов остаётся
        клубом своей страны.
  Ф-к3. Перевод принадлежит имени flashscore вместе с видом и страной игры:
        «Wisła Kraków» (pl) → (Wisla, F, POLAND).
  Ф-к4. Имя у нескольких стран в одном виде (Rangers: SCOTLAND и CHILE) —
        двусмысленное: по одному имени клуб не определить.
  Ф-к6. Серия имён с тире: английское «La Duchere - X» у flashscore с разными X
        (Feurs, Toulon, Nimes) — одна команда с разными соперниками, то есть
        обрывки пар матчей (зеркало режет строку игры по первому тире); у
        настоящего клуба вторая половина одна («Banik Most - Sous», «- Sous B»,
        «- Sous W» — составы одного клуба).
  Ф-к5. Перевод засчитывается, только если он встретился в `MIN_GAMES`
        разных играх flashscore (fs_id): зеркала порой ставят команды игры
        в другом порядке, и шведское «Gabon U20» ложилось переводом
        «Congo U20» (замер 09.11). Перевод, равный имени соперника в той
        же игре, — перестановка: язык этой игры не читается вовсе.

    python scripts/fs_katalog.py --out fs_katalog.json   # собрать из git и сохранить
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from slovar_otchet import norm  # noqa: E402

GAMES = "results/games.json"
#: Ф-к2: «страны» эталона, которые на деле турниры частей света и мира
#: Ф-к5: в скольких разных играх должен встретиться перевод
MIN_GAMES = 2
NOT_COUNTRY = {"WORLD", "EUROPE", "ASIA", "AFRICA", "SOUTH AMERICA", "NORTH & CENTRAL AMERICA",
               "AUSTRALIA & OCEANIA", "NORTH AMERICA", "CENTRAL AMERICA", "OCEANIA"}


#: разделитель пары матча (как `dictionary._PAIR_RE`)
PAIR_SPLIT = re.compile(r"\s+(?:-|–|—|vs\.?|v)\s+", re.IGNORECASE)
#: кавычки вокруг половин («Italijos lyga. "Napoli" - "Bologna»)
QUOTES = " \"'«»„“”"
#: пометки состава в конце имени — для Ф-к6 клубы не различают
_SQUAD = {"w", "b", "c", "ii", "iii", "2", "3", "u17", "u18", "u19", "u20", "u21", "u23",
          "n", "z", "k", "f", "d", "v", "zeny", "women"}


def core(name: str) -> str:
    """Имя без пометок состава в конце: `Sous B` → `sous`, `Sous W` → `sous`."""
    words = norm((name or "").strip(QUOTES)).split()
    while len(words) > 1 and words[-1] in _SQUAD:
        words.pop()
    return " ".join(words)


def country_of(league: str) -> str | None:
    """Ф-к2: `POLAND: Ekstraklasa` → POLAND; `EUROPE: Champions League` → None."""
    head = (league or "").split(":", 1)[0].strip().upper()
    if not head or ":" not in (league or "") or head in NOT_COUNTRY:
        return None
    return head


class Katalog:
    """Имена flashscore: вид, страны, переводы. Ключи — `norm` имени."""

    def __init__(self, min_games: int = MIN_GAMES) -> None:
        self.min_games = min_games
        #: norm имени → английские написания flashscore
        self.names: dict[str, set[str]] = defaultdict(set)
        #: norm имени → виды
        self.sports: dict[str, set[str]] = defaultdict(set)
        #: (norm имени, вид) → страны (Ф-к2)
        self.countries: dict[tuple[str, str], set[str]] = defaultdict(set)
        #: norm перевода → {(norm имени flashscore, вид, страна|None): игры} (Ф-к3, Ф-к5);
        #: при сборке игры — множество fs_id, из файла — их число
        self.tr: dict[str, dict[tuple, set | int]] = defaultdict(dict)
        self.games = 0

    # ── сборка ──
    def add_game(self, g: dict) -> None:
        sport = g.get("sport") or "?"
        # у тенниса «лига» — турнир («ITF WOMEN - SINGLES: …»), страны нет
        country = None if sport == "T" else country_of(g.get("league") or "")
        self.games += 1
        game_id = g.get("fs_id") or f"{g.get('home')}|{g.get('away')}|{g.get('start_kyiv')}"
        english = [norm(g.get("home") or ""), norm(g.get("away") or "")]
        langs = {}
        for lang, pair in (g.get("names") or {}).items():
            if not (isinstance(pair, list) and len(pair) == 2):
                continue
            mine = [norm(pair[0] or ""), norm(pair[1] or "")]
            if mine[0] == english[1] or mine[1] == english[0]:
                continue                      # Ф-к5: перестановка сторон в зеркале
            langs[lang] = mine
        for i, side in enumerate(("home", "away")):
            name = (g.get(side) or "").strip()
            if not name:
                continue
            key = norm(name)
            self.names[key].add(name)
            self.sports[key].add(sport)
            if country:
                self.countries[(key, sport)].add(country)
            for mine in langs.values():
                t = mine[i]
                if t and t != key:
                    self.tr[t].setdefault((key, sport, country), set()).add(game_id)

    # ── вопросы ──
    def known(self, name: str) -> bool:
        """Ф-к1: такое английское имя есть у flashscore."""
        return norm(name) in self.names

    def sports_of(self, name: str) -> set[str]:
        return set(self.sports.get(norm(name), set()))

    def countries_of(self, name: str, sport: str | None = None) -> set[str]:
        key = norm(name)
        out: set[str] = set()
        for s in ([sport] if sport else self.sports.get(key, set())):
            out |= self.countries.get((key, s), set())
        return out

    def ambiguous(self, name: str) -> bool:
        """Ф-к4: в каком-то виде имя у нескольких стран."""
        key = norm(name)
        return any(len(self.countries.get((key, s), set())) > 1
                   for s in self.sports.get(key, set()))

    def _series_index(self) -> dict:
        """Ф-к6: половина английского имени с тире → разные другие половины
        (без пометок состава W, B, U19…)."""
        if getattr(self, "_series", None) is None:
            index: dict[tuple[str, str], set[str]] = defaultdict(set)
            for spellings in self.names.values():
                for name in spellings:
                    for m in PAIR_SPLIT.finditer(name):
                        left, right = core(name[:m.start()]), core(name[m.end():])
                        if left and right:
                            index[("L", left)].add(right)
                            index[("R", right)].add(left)
            self._series = index
        return self._series

    def series(self, left: str, right: str) -> bool:
        """Ф-к6: половина `left` (или `right`) стоит у flashscore в английских
        именах с тире при двух и больше разных других половинах."""
        index = self._series_index()
        return (len(index.get(("L", core(left)), ())) >= 2
                or len(index.get(("R", core(right)), ())) >= 2)

    def tr_entries(self, text: str) -> set[tuple]:
        """Ф-к3, Ф-к5: надёжные записи перевода `text` — (norm имени, вид,
        страна), встреченные не меньше чем в `min_games` разных играх."""
        out = set()
        for entry, games in self.tr.get(norm(text), {}).items():
            if (len(games) if isinstance(games, set) else games) >= self.min_games:
                out.add(entry)
        return out

    def translated_to(self, text: str) -> set[str]:
        """Ф-к3: каким именам flashscore принадлежит перевод `text` (norm)."""
        return {key for key, _s, _c in self.tr_entries(text)}

    def is_translation_of(self, text: str, name: str) -> bool:
        return norm(name) in self.translated_to(text)

    def is_team_name(self, text: str) -> bool:
        """Имя одной команды у flashscore: английское имя или перевод."""
        return self.known(text) or bool(self.translated_to(text))

    # ── файл ──
    def to_json(self) -> dict:
        return {"games": self.games,
                "names": {k: sorted(v) for k, v in self.names.items()},
                "sports": {k: sorted(v) for k, v in self.sports.items()},
                "countries": [[k, s, sorted(v)] for (k, s), v in self.countries.items()],
                "tr": {t: sorted([[*e, len(n) if isinstance(n, set) else n] for e, n in v.items()], key=str)
                       for t, v in self.tr.items()}}

    @classmethod
    def from_json(cls, data: dict) -> "Katalog":
        k = cls()
        k.games = data.get("games", 0)
        for key, v in data["names"].items():
            k.names[key] = set(v)
        for key, v in data["sports"].items():
            k.sports[key] = set(v)
        for key, s, v in data["countries"]:
            k.countries[(key, s)] = set(v)
        for t, v in data["tr"].items():
            k.tr[t] = {tuple(x[:3]): x[3] for x in v}
        return k


def from_git(repo: Path = ROOT, ref: str = "HEAD") -> Katalog:
    """Все выпуски `results/games.json` из истории git репозитория `repo`
    (до коммита `ref`; на сервере — HEAD, локально — origin/main)."""
    shas = subprocess.run(["git", "-C", str(repo), "log", "--format=%H", ref, "--", GAMES],
                          capture_output=True, text=True, check=True).stdout.split()
    kat = Katalog()
    for sha in shas:
        raw = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:{GAMES}"],
                             capture_output=True).stdout
        try:
            ref = json.loads(raw.decode("utf-8")).get("эталон") or []
        except (ValueError, UnicodeDecodeError, AttributeError):
            continue
        for g in ref:
            if isinstance(g, dict):
                kat.add_game(g)
    return kat


def load(path: str | Path) -> Katalog:
    return Katalog.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Каталог имён flashscore из истории эталона")
    ap.add_argument("--repo", default=str(ROOT), help="репозиторий с историей results/games.json")
    ap.add_argument("--ref", default="HEAD", help="до какого коммита читать историю")
    ap.add_argument("--out", required=True, help="куда сохранить каталог (json)")
    args = ap.parse_args()
    kat = from_git(Path(args.repo), args.ref)
    Path(args.out).write_text(json.dumps(kat.to_json(), ensure_ascii=False), encoding="utf-8")
    print(f"каталог flashscore: игр {kat.games}, имён {len(kat.names)}, переводов {len(kat.tr)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

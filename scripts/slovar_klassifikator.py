# -*- coding: utf-8 -*-
r"""Классификатор словаря команд — шаг 4 карточки словаря 09.11.2026.

Разовый прогон по базе. Решение владельца 08.11: ничего не удалять — ошибки
в книгу ошибок (`dictionary_errors`), дубли клубов — слить с сохранением
написаний. Слово владельца 09.11 12:30: «имена берутся в первую очередь с
flashscore; нет этого вида спорта, турнира или лиги — работает наш алгоритм;
чего нет и не было на flashscore — остаётся автопереводом и проверяется
поиском; нужна чёткая информация». Рабочий алгоритм имён (`app/canon.py`)
классификатор не трогает. Ни одна строка `team_aliases`/`teams` не стирается.

Каталог flashscore — `scripts/fs_katalog.py`: все выпуски эталона из истории
git (имя, вид, страна, переводы на зеркалах flashscore).

    venv/bin/python scripts/slovar_klassifikator.py --fs-katalog k.json            # показ, база не меняется
    venv/bin/python scripts/slovar_klassifikator.py --fs-katalog k.json \
        --spisok s.md --na-poisk p.json                                           # и списки
    venv/bin/python scripts/slovar_klassifikator.py --fs-katalog k.json \
        --poisk resheniya.json --apply                                            # записать (копия базы и «да»)

Правила по порядку:

  К1. Кандидаты в слияние — пары `slovar_otchet.collect` (правило С6, `decide`).
      «сливать точно», «сливать по уликам», «возможный дубль» — на проверку
      flashscore (Ф0–Ф5); «тёзки по виду», «Д: голое имя», «разные: …» — не
      трогать: улики против слияния сильнее. Дубли канонов (Дк) — так же.
  Ф0. Теннисная пара с хвостом WO / RETIRED — те же игроки: сливать.
  Ф1. Виды обеих команд известны и не пересекаются — НЕ сливать.
  Ф2. Имена совпали после нормализации (Górnik / Gornik): сливать, выживший —
      написание flashscore. Имя flashscore в одном виде у нескольких стран
      (Platense: Аргентина и Гондурас) — решает поиск.
  Ф2а. Оба написания есть у flashscore («Al Shabab» — Саудовская Аравия,
      «Al-Shabab» — Оман; теннисистки «Li A.» и «li a.»): решает поиск.
  Ф3. Оба имени — разные команды flashscore (Rangers / Rangers FC,
      Din. Zagreb / Dinamo Zagreb баскетбол): НЕ сливать, в книгу не писать.
  Ф4. Одно имя у flashscore, другое — его перевод на зеркале flashscore той
      же категории (W, U19, B) и вида («Wisła Kraków» → Wisla): сливать в имя
      flashscore. Перевод чужого клуба flashscore — не сливать. Перевод у
      нескольких имён flashscore или имя flashscore у нескольких стран
      (Rangers: Шотландия и Чили) — решает поиск.
  Ф5. Обоих имён нет у flashscore, но оба — переводы одного имени flashscore —
      сливать; переводы разных имён — не сливать.
  Ф6. Иначе (имени нет и не было на flashscore; хоккея, гандбола, волейбола
      у эталона нет вовсе) — решает проверка поиском (`--poisk`): «один клуб» —
      сливать, «разные» — нет. Решения ещё нет — команды не трогать, в книгу
      «возможный дубль» с пометкой «ждёт проверки поиском», в список «на поиск».
  К2. Выживший — команда с именем flashscore (Ф2, Ф4); иначе у кого больше
      написаний с языком, событий, написаний, короче имя (`_выживший`
      отчёта). Каждое слияние — строка книги «слито» с причиной и источником.
      Написания проигравшего переезжают к выжившему; такое же написание
      (alias, lang) у выжившего уже есть — запись проигравшего остаётся и
      идёт в книгу «слито». События — на выжившего. У проигравшего
      `teams.merged_into` = выживший; слитые в проигравшего — тоже на выжившего.
  К3. Слияние кругами, пока находится новое (не больше `КРУГОВ`).
  К4. Пара как имя — карантин «пара», но сначала flashscore (`pair_verdict`;
      имя с тире у flashscore бывает обрывком — зеркало режет строку игры
      по первому тире, поэтому решает он только явное):
      П1. половина текста — сама команда-владелец («Βράμπλε - Ζβόλεν» у
          Zvolen): обрывок пары, карантин;
      П2. обе половины — команды flashscore, а целиком такого имени у
          flashscore нет («Genoa - Milan»): карантин;
      П2б. у flashscore половина английского имени стоит с разными другими
          половинами («La Duchere - Feurs», «- Toulon», «- Nimes»): обрывки
          пар матчей, карантин (составы одного клуба — Sous, Sous B, Sous W —
          разными не считаются, `fs_katalog.core`);
      П3. текст — имя владельца у flashscore, у владельца в имени тире,
          половины текста — не команды и имя владельца не делится на две
          команды («Фльори – Мерожи» у Fleury-Merogis): не трогать
          («La Duchere - Feurs» делится на два клуба — это П4);
      П4. иначе решает поиск: «пара» — карантин, «одна команда» — нет;
          решения нет — не трогать, в список «на поиск».
  К5. Коллизия — написание X у команды A равно канону другой команды B, а
      сходство A и B ниже `SAME_CLUB`:
      Кл1. X — перевод flashscore имени A: написание законно, не трогать;
      Кл2. A и B — команды flashscore разных видов (Sp. Subotica футбол /
           Spartak Subotica баскетбол): тёзки по виду, не трогать;
      Кл3а. X — короткая форма имени самой A, подтверждённого flashscore
           («Sporting» у Gijon, а «Sporting Gijón» — перевод Gijon на зеркале):
           по flashscore не решить — поиск;
      Кл3. A и B — команды flashscore одного вида («Bayer Leverkusen» у
           Bayern Munich): карантин «коллизия»;
      Кл4. иначе решает поиск: «чужое» — карантин, «своё» — нет; решения
           нет — не трогать, в список «на поиск».
      Карантин и пар, и коллизий — на состоянии ПОСЛЕ слияний.
  К6. Повтор ничего не портит (С7, С9): второй прогон — 0 новых строк книги
      и 0 переездов.
  К7. Без `--apply` — показ на копии базы во временной папке.
  К8. Сверка «игр старым/новым словарём»: сколько живых игр поменяли имя.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app import db, dictionary, names  # noqa: E402
from app.dictionary import SAME_CLUB  # noqa: E402
import fs_katalog  # noqa: E402
import slovar_otchet  # noqa: E402
from slovar_otchet import norm  # noqa: E402

#: К3: кругов слияния самое большее (замер 09.11 на копии — хватает двух)
КРУГОВ = 5
#: вердикты `decide`, которые идут на проверку flashscore (К1)
НА_ПРОВЕРКУ = ("сливать точно", "сливать по уликам", "возможный дубль")
ВОЗМОЖНЫЙ_ДУБЛЬ = "возможный дубль"
#: решения проверки flashscore
СЛИВАТЬ, РАЗНЫЕ, ПОИСК = "сливать", "разные", "поиск"
#: разделитель пары матча (как `dictionary._PAIR_RE`)
_PAIR_SPLIT = re.compile(r"\s+(?:-|–|—|vs\.?|v)\s+", re.IGNORECASE)


# ── проверка поиском: решения из файла ───────────────────────────────────────

def poisk_key(kind: str, *texts: str) -> tuple:
    """Ключ решения поиска: вид («слияние», «пара», «коллизия») и имена (norm).
    Для слияния порядок имён не важен."""
    keys = tuple(norm(t) for t in texts)
    return (kind, tuple(sorted(keys)) if kind == "слияние" else keys)


def poisk_index(items: list[dict]) -> dict:
    """Файл решений поиска → {ключ: решение}. Строка файла: {"вид", "имена",
    "решение", "источник", "почему"}."""
    return {poisk_key(it["вид"], *it["имена"]): it for it in items or []}


# ── Ф0–Ф6: сначала flashscore ────────────────────────────────────────────────

def _fs_names_of(kat: fs_katalog.Katalog, text: str, cat: str, sports: set) -> set[str]:
    """Ф4: имена flashscore (norm), чей перевод — `text`, той же категории
    (W, U19, B) и, если вид известен, того же вида."""
    out = set()
    for key, sport, _country in kat.tr_entries(text):
        spelled = next(iter(kat.names.get(key) or {key}))
        if names.category(spelled) != cat:
            continue
        if sports and sport not in sports:
            continue
        out.add(key)
    return out


def fs_verdict(kat: fs_katalog.Katalog, a: str, b: str, sa: set, sb: set,
               tails: bool = False) -> tuple[str, str, str | None]:
    """Ф0–Ф6 для пары имён команд словаря (a, b) с видами (sa, sb).
    → (решение, почему, norm имени flashscore выжившего или None)."""
    if tails:
        return СЛИВАТЬ, "Ф0: теннисная пара, хвост WO/RETIRED", None
    if sa and sb and not (sa & sb):
        return РАЗНЫЕ, f"Ф1: виды {''.join(sorted(sa))}/{''.join(sorted(sb))}", None
    na, nb = norm(a), norm(b)
    ka, kb = kat.known(a), kat.known(b)
    if na == nb:
        spelled = kat.names.get(na, set())
        if a != b and a in spelled and b in spelled:
            return ПОИСК, (f"Ф2а: у flashscore оба написания — «{a}» и «{b}»: бывают два "
                           f"разных клуба или игрока (Al Shabab / Al-Shabab, Li A. / li a.)"), None
        if (ka or kb) and kat.ambiguous(a if ka else b):
            return ПОИСК, f"Ф2: имя flashscore у нескольких стран ({_where(kat, a if ka else b)})", None
        return СЛИВАТЬ, "Ф2: одно имя после нормализации", na if (ka or kb) else None
    if ka and kb:
        return РАЗНЫЕ, (f"Ф3: у flashscore две разные команды ({a}: {_where(kat, a)}; "
                        f"{b}: {_where(kat, b)})"), None
    if ka or kb:
        fs_name, other, s_other = (a, b, sb) if ka else (b, a, sa)
        hits = _fs_names_of(kat, other, names.category(other), s_other)
        if not hits:
            return ПОИСК, f"Ф6: «{other}» нет на flashscore (есть «{fs_name}»: {_where(kat, fs_name)})", None
        if norm(fs_name) not in hits:
            return РАЗНЫЕ, (f"Ф4: «{other}» у flashscore — перевод другого клуба "
                            f"({', '.join(sorted(hits))[:80]})"), None
        if len(hits) > 1:
            return ПОИСК, f"Ф4: перевод «{other}» у нескольких имён flashscore ({', '.join(sorted(hits))[:80]})", None
        if kat.ambiguous(fs_name):
            return ПОИСК, f"Ф4: имя «{fs_name}» у flashscore в нескольких странах ({_where(kat, fs_name)})", None
        return СЛИВАТЬ, f"Ф4: «{other}» — перевод «{fs_name}» на зеркале flashscore ({_where(kat, fs_name)})", norm(fs_name)
    ha = _fs_names_of(kat, a, names.category(a), sa)
    hb = _fs_names_of(kat, b, names.category(b), sb)
    if len(ha) == 1 and ha == hb:
        return СЛИВАТЬ, f"Ф5: оба — переводы одного имени flashscore ({next(iter(ha))})", None
    if ha and hb and not (ha & hb):
        return РАЗНЫЕ, "Ф5: переводы разных имён flashscore", None
    return ПОИСК, "Ф6: обоих имён нет на flashscore", None


def _where(kat: fs_katalog.Katalog, name: str) -> str:
    """«F POLAND; B BELARUS» — виды и страны имени у flashscore."""
    parts = []
    for s in sorted(kat.sports_of(name)):
        c = sorted(kat.countries_of(name, s))
        parts.append(f"{s} {', '.join(c) if c else 'турниры'}")
    return "; ".join(parts)


# ── К1–К3: слияние ───────────────────────────────────────────────────────────

def _merge(conn: sqlite3.Connection, win: int, lose: int, why: str) -> Counter:
    """К2: команда `lose` сливается в `win`. Ничего не стирается."""
    got = Counter()
    win_name = conn.execute("SELECT canonical_name FROM teams WHERE id = ?", (win,)).fetchone()[0]
    lose_name = conn.execute("SELECT canonical_name FROM teams WHERE id = ?", (lose,)).fetchone()[0]
    if dictionary.note_error(conn, lose_name, "слито", team_id=lose, led_to=lose_name,
                             truth=win_name, note=f"слияние: {why}"):
        got["книга: слито"] += 1
    for a in conn.execute("SELECT id, alias, lang FROM team_aliases WHERE team_id = ?",
                          (lose,)).fetchall():
        if conn.execute("SELECT 1 FROM team_aliases WHERE team_id = ? AND alias = ? "
                        "AND lang IS ?", (win, a["alias"], a["lang"])).fetchone():
            if dictionary.note_error(conn, a["alias"], "слито", lang=a["lang"], team_id=lose,
                                     led_to=lose_name, truth=win_name,
                                     note=f"такое же написание уже у выжившего; {why}"):
                got["книга: слито"] += 1
            got["написание осталось у проигравшего"] += 1
        else:
            conn.execute("UPDATE team_aliases SET team_id = ? WHERE id = ?", (win, a["id"]))
            got["написаний переехало"] += 1
    got["событий переехало"] += conn.execute(
        "UPDATE events SET team_home_id = ? WHERE team_home_id = ?", (win, lose)).rowcount
    got["событий переехало"] += conn.execute(
        "UPDATE events SET team_away_id = ? WHERE team_away_id = ?", (win, lose)).rowcount
    conn.execute("UPDATE teams SET merged_into = ? WHERE merged_into = ?", (win, lose))
    conn.execute("UPDATE teams SET merged_into = ? WHERE id = ?", (win, lose))
    got["слияний"] += 1
    return got


def _evidence(conn: sqlite3.Connection, kat: fs_katalog.Katalog, tid: int, name: str) -> dict:
    """Улики команды для списка «на поиск»: наши игры и написания, flashscore."""
    ev = Counter(r[0] for r in conn.execute(
        "SELECT sport FROM events WHERE team_home_id = ? OR team_away_id = ?", (tid, tid)))
    al = [f"{r['alias']} [{r['lang'] or '-'}]" for r in conn.execute(
        "SELECT alias, lang FROM team_aliases WHERE team_id = ? ORDER BY id LIMIT 12", (tid,))]
    return {"имя": name, "игр": dict(ev), "написания": al,
            "flashscore": _where(kat, name) if kat.known(name) else "нет"}


def merge_round(conn: sqlite3.Connection, kat: fs_katalog.Katalog, poisk: dict,
                plan: list | None = None, na_poisk: list | None = None,
                zhurnal: list | None = None) -> Counter:
    """Один круг К1–К2 по текущему состоянию базы. `plan` — куда записать
    слияния (выживший, проигравший, вердикт, почему); `na_poisk` — пары,
    которые решает только поиск (Ф6)."""
    report = slovar_otchet.collect(conn)
    decide, survivor, teams = report["_решить"], report["_выживший"], report["_команды"]
    sport_of = report["_вид"]
    pairs = [(x, y, langs) for x, y, _sim, langs in report["_пары"]]
    for ids in report["_дк"]:                                 # дубли канонов
        pairs += [(ids[0], other, frozenset()) for other in ids[1:]]
    got = Counter()
    gone: set[int] = set()                    # слиты в этом круге — в следующем
    for x, y, langs in pairs:
        if x in gone or y in gone or x not in teams or y not in teams:
            continue
        verdict, why = decide(x, y, langs)
        if verdict not in НА_ПРОВЕРКУ:
            continue
        nx, ny = teams[x]["canonical_name"], teams[y]["canonical_name"]
        tails = verdict == "сливать точно" and ("WO, RETIRED" in why) and (
            nx.endswith(slovar_otchet.WO_TAIL) or ny.endswith(slovar_otchet.WO_TAIL)
            or "RETIRED" in nx or "RETIRED" in ny)
        fs, fs_why, fs_name = fs_verdict(kat, nx, ny, sport_of(x), sport_of(y), tails)
        if zhurnal is not None:
            zhurnal.append({"вид": "слияние", "имена": [nx, ny], "решение": fs, "почему": fs_why})
        label = "сливать: flashscore"
        if fs == ПОИСК:
            found = poisk.get(poisk_key("слияние", nx, ny))
            if found and found["решение"] == "один клуб":
                fs, label = СЛИВАТЬ, "сливать: поиск"
                fs_why = f"поиск: {found.get('почему', '')} — {found.get('источник', '')}"
            elif found and found["решение"] == "разные":
                got["поиск: разные"] += 1
                continue
            else:
                if dictionary.note_error(conn, ny, ВОЗМОЖНЫЙ_ДУБЛЬ, team_id=x, led_to=nx,
                                         truth=ny, note=f"{fs_why}; ждёт проверки поиском"):
                    got["книга: возможный дубль"] += 1
                got["на поиск: слияние"] += 1
                if na_poisk is not None:
                    na_poisk.append({"вид": "слияние", "имена": [nx, ny], "почему": fs_why,
                                     "улики": [_evidence(conn, kat, x, nx),
                                               _evidence(conn, kat, y, ny)]})
                continue
        if fs == РАЗНЫЕ:
            got["flashscore: разные"] += 1
            continue
        win, lose = survivor(x, y)
        if fs_name is not None:               # К2: выживший — имя flashscore
            spelled = kat.names.get(fs_name, set())
            for cand, other in ((x, y), (y, x)):
                if teams[cand]["canonical_name"] in spelled or (
                        norm(teams[cand]["canonical_name"]) == fs_name
                        and teams[other]["canonical_name"] not in spelled):
                    win, lose = cand, other
                    break
        got.update(_merge(conn, win, lose, f"{label}: {fs_why}"))
        got[label] += 1
        gone.add(lose)
        if plan is not None:
            plan.append((teams[win]["canonical_name"], teams[lose]["canonical_name"],
                         label, fs_why))
    return got


# ── К4–К5: карантин ──────────────────────────────────────────────────────────

def _splits(text: str) -> list[tuple[str, str]]:
    """Все разрезы текста по разделителю пары: «A - B - C» → (A, B - C), (A - B, C)."""
    return [(text[:m.start()].strip(fs_katalog.QUOTES), text[m.end():].strip(fs_katalog.QUOTES))
            for m in _PAIR_SPLIT.finditer(text)]


def pair_verdict(kat: fs_katalog.Katalog, text: str, owner: str) -> tuple[str, str]:
    """П1–П4 для текста `text`, похожего на пару матча, у команды `owner` →
    (решение, почему); решение: «пара» | «команда» | «поиск».

    Тонкость данных flashscore (замер 09.11): зеркало режет строку игры по
    первому тире, и у клубов с тире в имени получаются обрывки — греческое
    «Ζλάτε Μόραφτσε - Βράμπλε - Ζβόλεν» дало «Βράμπλε - Ζβόλεν» переводом
    Zvolen, а в английских именах эталона есть «Sous B - Klasterec n. Oh.».
    Поэтому имя с тире у flashscore само по себе не доказывает ни пару, ни
    команду: flashscore решает только явное, остальное — поиск."""
    splits = _splits(text)
    is_own = norm(text) == norm(owner)
    for left, right in splits:
        for half in (left, right):
            if not is_own and (norm(half) == norm(owner) or kat.is_translation_of(half, owner)):
                return "пара", f"П1: половина «{half}» — сама команда «{owner}»: обрывок пары матча"
    if not kat.is_team_name(text) and any(kat.is_team_name(l) and kat.is_team_name(r)
                                          for l, r in splits):
        return "пара", "П2: обе половины — команды flashscore, целиком имени нет"
    english = [text] if kat.known(text) else []
    if "-" in owner or "–" in owner:
        english.append(owner)
    for name in english:
        for left, right in _splits(name):
            if kat.series(left, right):
                return "пара", (f"П2б: у flashscore «{left} - …» или «… - {right}» стоит с "
                                f"разными соперниками — обрывок пары матча")
    halves_named = any(kat.is_team_name(h) for pair in splits for h in pair) or any(
        kat.is_team_name(l) and kat.is_team_name(r) for l, r in _splits(owner))
    owners_name = (is_own and kat.known(text)) or kat.is_translation_of(text, owner)
    if owners_name and "-" in owner and not halves_named:
        return "команда", f"П3: «{text}» — имя «{owner}» у flashscore, половины — не команды"
    return ПОИСК, "П4: flashscore не решает (имя с тире или обрывок неясен)"


def collision_verdict(kat: fs_katalog.Katalog, alias: str, me: str, him: str,
                      my_names: list[str] | tuple = ()) -> tuple[str, str]:
    """Кл1–Кл4: написание `alias` у команды `me` равно канону `him` →
    (решение, почему); решение: «чужое» | «своё» | «поиск». `my_names` —
    прочие написания команды `me` (для Кл3а)."""
    if kat.is_translation_of(alias, me):
        return "своё", f"Кл1: «{alias}» — перевод flashscore имени «{me}»"
    if kat.known(me) and kat.known(him):
        sm, sh = kat.sports_of(me), kat.sports_of(him)
        if not (sm & sh):
            return "своё", (f"Кл2: тёзки по виду у flashscore ({me}: {''.join(sorted(sm))}; "
                            f"{him}: {''.join(sorted(sh))})")
        for mine in my_names:
            # своё имя — только подтверждённое flashscore: у Bayern Munich лежит и
            # чужое «Bayer 04 Leverkusen», оно «Bayer Leverkusen» своим не делает
            if not (norm(mine) == norm(me) or kat.is_translation_of(mine, me)):
                continue
            if norm(mine) != norm(alias) and slovar_otchet.words_inside(alias, mine):
                return ПОИСК, (f"Кл3а: «{alias}» — короткая форма своего же имени «{mine}» "
                               f"(«Sporting» у Gijon — Sporting Gijón): по flashscore не решить")
        return "чужое", f"Кл3: у flashscore две команды одного вида ({me}: {_where(kat, me)}; {him}: {_where(kat, him)})"
    return ПОИСК, "Кл4: flashscore не знает обе команды"


def quarantine(conn: sqlite3.Connection, kat: fs_katalog.Katalog, poisk: dict,
               na_poisk: list | None = None, zhurnal: list | None = None) -> Counter:
    """Пары как имя (К4) и коллизии (К5) — в книгу ошибок классами карантина,
    сначала проверка flashscore. Только активные команды (не слитые)."""
    got = Counter()
    teams = {r["id"]: r["canonical_name"] for r in conn.execute(
        "SELECT id, canonical_name FROM teams WHERE merged_into IS NULL")}
    by_canon: dict[str, list[int]] = {}
    for tid, canon in teams.items():
        by_canon.setdefault(canon.casefold(), []).append(tid)
    asked: set[tuple] = set()
    rows = conn.execute("SELECT alias, lang, team_id FROM team_aliases ORDER BY id").fetchall()
    names_of: dict[int, list[str]] = {}
    for a in rows:
        names_of.setdefault(a["team_id"], []).append(a["alias"])
    for a in rows:
        tid = a["team_id"]
        if tid not in teams:
            continue
        me = teams[tid]
        if dictionary.is_pair_name(a["alias"]) or dictionary.is_pair_name(me):
            text = a["alias"] if dictionary.is_pair_name(a["alias"]) else me
            verdict, why = pair_verdict(kat, text, me)
            if zhurnal is not None:
                zhurnal.append({"вид": "пара", "имена": [text, me], "язык": a["lang"],
                                "решение": verdict, "почему": why})
            if verdict == ПОИСК:
                found = poisk.get(poisk_key("пара", text))
                if found and found["решение"] in ("пара", "одна команда"):
                    verdict = "пара" if found["решение"] == "пара" else "команда"
                    why = f"поиск: {found.get('почему', '')} — {found.get('источник', '')}"
                else:
                    key = poisk_key("пара", text)
                    if key not in asked:
                        asked.add(key)
                        got["на поиск: пара"] += 1
                        if na_poisk is not None:
                            na_poisk.append({"вид": "пара", "имена": [text], "почему": why,
                                             "улики": [_evidence(conn, kat, tid, me)]})
                    continue
            if verdict == "команда":
                got["поиск: не пара" if why.startswith("поиск") else "flashscore: не пара"] += 1
                continue
            what = ("написание — пара матча" if dictionary.is_pair_name(a["alias"])
                    else "каноническое имя команды — пара матча")
            if dictionary.note_error(conn, a["alias"], "пара", lang=a["lang"], team_id=tid,
                                     led_to=me, note=f"{what}; {why}"):
                got["книга: пара"] += 1
            continue
        for other in by_canon.get(a["alias"].casefold(), []):
            him = teams[other]
            if other == tid or dictionary.is_pair_name(him):
                continue
            sim = names.similarity(me, him)
            if sim >= SAME_CLUB:
                continue                      # тот же клуб? решает слияние (К1)
            verdict, why = collision_verdict(kat, a["alias"], me, him, names_of.get(tid, ()))
            if zhurnal is not None:
                zhurnal.append({"вид": "коллизия", "имена": [a["alias"], me, him], "язык": a["lang"],
                                "решение": verdict, "почему": why})
            if verdict == ПОИСК:
                found = poisk.get(poisk_key("коллизия", a["alias"], me))
                if found and found["решение"] in ("чужое", "своё"):
                    verdict = found["решение"]
                    why = f"поиск: {found.get('почему', '')} — {found.get('источник', '')}"
                else:
                    key = poisk_key("коллизия", a["alias"], me)
                    if key not in asked:
                        asked.add(key)
                        got["на поиск: коллизия"] += 1
                        if na_poisk is not None:
                            na_poisk.append({"вид": "коллизия", "имена": [a["alias"], me],
                                             "чьё имя": him, "язык": a["lang"], "почему": why,
                                             "улики": [_evidence(conn, kat, tid, me),
                                                       _evidence(conn, kat, other, him)]})
                    continue
            if verdict == "своё":
                got["поиск: написание своё" if why.startswith("поиск")
                    else "flashscore: написание своё"] += 1
                continue
            if dictionary.note_error(conn, a["alias"], "коллизия", lang=a["lang"],
                                     team_id=tid, led_to=me, truth=him,
                                     note=f"написание = имя другой команды, сходство {sim}; {why}"):
                got["книга: коллизия"] += 1
    return got


# ── К8: сверка «игр старым/новым словарём» ──────────────────────────────────

def shown_names(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    """Имя игры на витрине (как `store.schedule`): канон команды, иначе
    бесспорное написание словаря, иначе догадка транслитом."""
    known = dictionary.team_overrides(conn)

    def show(canon, raw):
        raw = (raw or "").strip()
        return canon or known.get(raw) or names.suggest_canonical(raw)

    return {r["id"]: (show(r["h"], r["team_home_auto"]), show(r["a"], r["team_away_auto"]))
            for r in conn.execute(
                "SELECT e.id, e.team_home_auto, e.team_away_auto, "
                "th.canonical_name AS h, ta.canonical_name AS a FROM events e "
                "LEFT JOIN teams th ON th.id = e.team_home_id "
                "LEFT JOIN teams ta ON ta.id = e.team_away_id")}


# ── прогон ───────────────────────────────────────────────────────────────────

def run(conn: sqlite3.Connection, kat: fs_katalog.Katalog, poisk: dict | None = None,
        plan: list | None = None, na_poisk: list | None = None,
        zhurnal: list | None = None) -> dict:
    """К1–К6 по базе `conn` (в транзакции; фиксирует вызывающий). `zhurnal` —
    каждое решение (вид, имена, решение, почему) для проверки владельцем."""
    db.init_db(conn)
    poisk = poisk or {}
    before = shown_names(conn)
    total = Counter()
    rounds = []
    for i in range(КРУГОВ):
        got = merge_round(conn, kat, poisk, plan, na_poisk if i == 0 else None,
                          zhurnal if i == 0 else None)
        rounds.append(got["слияний"])
        # круги после первого видят те же пары заново: считаем только слияния
        total.update(got if i == 0 else {k: v for k, v in got.items()
                                         if not k.startswith(("на поиск", "flashscore:", "поиск:"))})
        if not got["слияний"]:
            break
    total.update(quarantine(conn, kat, poisk, na_poisk, zhurnal))
    after = shown_names(conn)
    changed = [(eid, before[eid], after.get(eid)) for eid in before if before[eid] != after.get(eid)]
    return {"итог": total, "круги": rounds, "игр": len(before), "игр_с_другим_именем": changed}


KEYS = ("слияний", "сливать: flashscore", "сливать: поиск", "flashscore: разные", "поиск: разные",
        "на поиск: слияние", "написаний переехало", "написание осталось у проигравшего",
        "событий переехало", "книга: слито", "книга: возможный дубль",
        "flashscore: не пара", "поиск: не пара", "книга: пара", "на поиск: пара",
        "flashscore: написание своё", "поиск: написание своё", "книга: коллизия",
        "на поиск: коллизия")


def show_result(res: dict) -> None:
    t = res["итог"]
    print(f"круги слияния: {res['круги']} (слияний по кругам)")
    for key in KEYS:
        print(f"  {key}: {t.get(key, 0)}")
    print(f"игр в базе: {res['игр']}, имя на витрине поменялось у {len(res['игр_с_другим_именем'])}")
    for eid, old, new in res["игр_с_другим_именем"][:15]:
        print(f"  #{eid}: {old[0]} — {old[1]}  →  {new[0]} — {new[1]}")


def load_katalog(path: str) -> fs_katalog.Katalog:
    """Каталог flashscore: из файла, а нет файла — из истории git (и в файл)."""
    if path and Path(path).exists():
        return fs_katalog.load(path)
    kat = fs_katalog.from_git(ROOT)
    if path:
        Path(path).write_text(json.dumps(kat.to_json(), ensure_ascii=False), encoding="utf-8")
    return kat


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Классификатор словаря команд (шаг 4 карточки)")
    ap.add_argument("--apply", action="store_true", help="записать в базу (после копии и «да»)")
    ap.add_argument("--fs-katalog", default="", help="каталог flashscore (json; нет файла — собрать из git)")
    ap.add_argument("--poisk", default="", help="решения проверки поиском (json)")
    ap.add_argument("--spisok", default="", help="записать список слияний в файл (markdown)")
    ap.add_argument("--na-poisk", default="", help="записать список «на поиск» (json)")
    ap.add_argument("--zhurnal", default="", help="записать журнал всех решений (json)")
    args = ap.parse_args()
    target = Path(db.db_path())
    if not target.exists():
        print(f"нет базы {target}")
        return 1
    kat = load_katalog(args.fs_katalog)
    print(f"каталог flashscore: игр {kat.games}, имён {len(kat.names)}")
    poisk = poisk_index(json.loads(Path(args.poisk).read_text(encoding="utf-8"))) if args.poisk else {}
    work = target
    tmp = None
    if not args.apply:                                   # К7: показ — на копии
        tmp = Path(tempfile.mkdtemp(prefix="slovar-klass-"))
        work = tmp / "kopiya.db"
        src = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        dst = sqlite3.connect(work)
        src.backup(dst)
        src.close()
        dst.close()
    os.environ["STREAMS_DB"] = str(work)
    conn = db.connect(db.BUSY_TIMEOUT_SCRIPT)
    plan: list = []
    na_poisk: list = []
    zhurnal: list = []
    try:
        res = run(conn, kat, poisk, plan, na_poisk, zhurnal)
        conn.commit()
    finally:
        conn.close()
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    print(("ЗАПИСАНО в " if args.apply else "ПОКАЗ (база не менялась): ") + str(target))
    show_result(res)
    if args.spisok:
        lines = ["# Слияния словаря команд (классификатор, шаг 4)\n",
                 "| Выживший | Проигравший | Вердикт | Почему |", "|---|---|---|---|"]
        lines += [f"| {w} | {l} | {v} | {why} |" for w, l, v, why in plan]
        Path(args.spisok).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"список слияний: {args.spisok} ({len(plan)} строк)")
    if args.na_poisk:
        Path(args.na_poisk).write_text(json.dumps(na_poisk, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
        print(f"на поиск: {args.na_poisk} ({len(na_poisk)} строк)")
    if args.zhurnal:
        Path(args.zhurnal).write_text(json.dumps(zhurnal, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        print(f"журнал решений: {args.zhurnal} ({len(zhurnal)} строк)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

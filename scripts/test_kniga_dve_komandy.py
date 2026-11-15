# -*- coding: utf-8 -*-
r"""Книга 139 (15.11.2026): лишнее слово или часть имени — решает число РАЗНЫХ
команд, рядом с которыми слова срезались.

На живом сборе 15.11 в книгу знаний попали «of Midlothian» (после «Heart»),
«Enea Łaciate Astoria» (перед «Bydgoszcz») и «Tasomix Rosiek Stal» (перед
«Ostrów Wielkopolski»): эталон пишет эти клубы короче, и по одному эталону
часть имени клуба не отличить от лишних слов. Отличает их другое: лишнее
слово стоит рядом с РАЗНЫМИ командами («ligová fáze» — перед шестью
сборными), часть имени — всегда рядом с одной.

Правила: `pipeline.trim_by_reference` (пометка `BESIDE`), `parse_live`
(«с кем» в итоге сбора), `dictionary.note_trims` (З6), `dictionary.
remember_beside`, `pipeline.book_rule` (Д1, Д2), `pipeline.known_trims`.
В сеть не ходит, база временная. Запуск: python scripts/test_kniga_dve_komandy.py
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="kniga-dve-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import db, dictionary, live, pipeline, site_lang  # noqa: E402
from app.reference import Confirmed  # noqa: E402
import dict_sync  # noqa: E402
import games_import  # noqa: E402
import parse_live  # noqa: E402

T = datetime(2026, 11, 15, 19, 0)
зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


class Эталон:
    """Вместо эталона: {(хозяева, гости): запись} — пара сходится целиком."""

    def __init__(self, answers: dict):
        self.answers = answers

    def may_know(self, home, away):
        return True

    def knows_team(self, name):
        return False

    def confirm(self, home, away, start, sport=""):
        entry = self.answers.get((home, away))
        return None if entry is None else Confirmed(entry=entry, start=start, how="пара", swapped=False)


def матч(ключ, хозяева, гости):
    return {"fs_id": ключ, "home": хозяева, "away": гости, "names": {}}


print("Срез помнит, рядом с какой командой стояли слова (`pipeline.BESIDE`)")
перед = pipeline.trim_by_reference([("ligová fáze Finsko", "San Marino")],
                                   Эталон({("Finsko", "San Marino"): матч("a", "Finsko", "San Marino")}), T)
после = pipeline.trim_by_reference([("Dundee", "Heart of Midlothian")],
                                   Эталон({("Dundee", "Heart"): матч("b", "Dundee", "Heart")}), T)
оба = pipeline.trim_by_reference([("Bundesliga live Rapid", "Sturm Das Spiel")],
                                 Эталон({("Rapid", "Sturm"): матч("c", "Rapid", "Sturm")}), T)
проверка("слова перед хозяевами — команда хозяев; после гостей — команда гостей; с двух краёв — обе",
         [got and got[3][pipeline.BESIDE] for got in (перед, после, оба)],
         [["Finsko", ""], ["", "Heart"], ["Rapid", "Sturm"]])

print("Итог сбора несёт «с кем» (`scripts/parse_live.py`)")
источник = inspect.getsource(parse_live)
проверка("сбор копит разные команды у каждого среза и кладёт их в итог — не больше `BESIDE_CAP`",
         ("срез.get(pipeline.BESIDE)" in источник, "\"с кем\": {\"перед\": sorted(перед)[:BESIDE_CAP]" in источник,
          parse_live.BESIDE_CAP), (True, True, 8))

print("Книга копит команды (`dictionary.note_trims`, правило З6; `dictionary.remember_beside`)")
db.init_db()
conn = db.connect()


def сбор(сайт, где, слова, перед=(), после=(), по="эталон"):
    return {сайт: [{"где": где, "срезано": слова, "по": по, "раз": 1, "пример": "было → стало",
                    "с кем": {"перед": list(перед), "после": list(после)}}]}


def строка(слова):
    row = conn.execute("SELECT * FROM dictionary_errors WHERE alias = ?", (слова,)).fetchone()
    return None if row is None else (pipeline.seen_teams(row["seen_with"]), pipeline.book_rule(dict(row)))


dictionary.note_trims(conn, сбор("start.sportdigital.de", live.TRIM_AWAY, "of Midlothian", после=["Heart"]))
dictionary.note_trims(conn, сбор("teleman.pl", live.TRIM_HOME, "Enea Łaciate Astoria", перед=["Bydgoszcz"]))
проверка("Д2: слова рядом с одной командой — в книге лежат, правилом не стали (часть имени клуба)",
         (строка("of Midlothian"), строка("Enea Łaciate Astoria")),
         ((["heart"], False), (["bydgoszcz"], False)))
dictionary.note_trims(conn, сбор("start.sportdigital.de", live.TRIM_AWAY, "of Midlothian", после=["HEART", " heart "]))
проверка("З6: та же команда в другом сборе и другим регистром второй командой не считается",
         строка("of Midlothian"), (["heart"], False))
dictionary.note_trims(conn, сбор("webtv.sk", live.TRIM_HOME, "ligová fáze", перед=["Finsko"]))
до = строка("ligová fáze")
dictionary.note_trims(conn, сбор("webtv.sk", live.TRIM_HOME, "ligová fáze", перед=["Lotyšsko"]))
проверка("Д2: вторая РАЗНАЯ команда — пусть и в другом сборе — делает слова правилом",
         (до, строка("ligová fáze")), ((["finsko"], False), (["finsko", "lotyšsko"], True)))
dictionary.note_trims(conn, сбор("tv.orf.at", live.TRIM_BOTH, "Bundesliga live … Das Spiel",
                                 перед=["Rapid", "LASK"], после=["Sturm"]))
проверка("срез с двух краёв: у каждого края свои команды — «перед» правилом стало, «после» ждёт",
         (строка("Bundesliga live"), строка("Das Spiel")), ((["lask", "rapid"], True), (["sturm"], False)))
dictionary.note_trims(conn, сбор("webtv.sk", live.TRIM_HOME, "Liga majstrov", перед=["Ajax", "Porto"], по="книга"))
проверка("З1 цело: срез, сделанный по самой книге, знанием не считается и команд не добавляет",
         строка("Liga majstrov"), None)
много = [f"Team {i}" for i in range(30)]
dictionary.note_trims(conn, сбор("webtv.sk", live.TRIM_HOME, "ligová fáze", перед=много))
проверка("строка помнит не больше `SEEN_CAP` команд",
         (len(строка("ligová fáze")[0]), dictionary.SEEN_CAP), (12, 12))
проверка("строки нет — дописывать некуда; битое поле читается как пустое",
         (dictionary.remember_beside(conn, "нет такой", live.KNOWN_HOME, "sk", ["A", "B"]),
          pipeline.seen_teams("не json"), pipeline.seen_teams(7), pipeline.seen_teams(["A", " a ", ""])),
         (0, [], [], ["a"]))

print("Какая строка книги — правило (`pipeline.book_rule`, Д1–Д2)")
dictionary.note_error(conn, "Liga e Kombeve", live.KNOWN_HOME, lang="sq", source_domain="ipko.tv",
                      answered_by="владелец 15.11")
проверка("Д1: строку записал владелец — правило сразу, без команд",
         строка("Liga e Kombeve"), ([], True))
проверка("Д2: счёт идёт по РАЗНЫМ командам; запись программы без команд (старая строка) ждёт",
         [pipeline.book_rule(x) for x in (
             {"answered_by": "программа", "seen_with": ["a", "b"]},
             {"answered_by": "программа", "seen_with": ["a", "A"]},
             {"answered_by": "программа"}, {"seen_with": "[\"a\", \"b\"]"}, {})],
         [True, False, False, True, False])
проверка("журнал заливки: сколько записей стали правилом и сколько ждут вторую команду",
         (dictionary.trims_state(conn), "dictionary.trims_state(conn)" in inspect.getsource(games_import)),
         ((3, 3), True))

print("Весь путь: база → файл словаря → разбор → другая база")
файл = TMP / "dictionaries.json"
dict_sync.export(conn, файл)
в_файле = {r["alias"]: r.get("seen_with") for r in json.loads(файл.read_text(encoding="utf-8"))["dictionary_errors"]
           if r["class"] in (live.KNOWN_HOME, live.KNOWN_AWAY)}
проверка("выгрузка словаря несёт команды списком",
         (в_файле["of Midlothian"], в_файле["Das Spiel"], в_файле["Liga e Kombeve"]),
         (["heart"], ["sturm"], []))
известное = pipeline.known_trims(файл)
проверка("разбор берёт из файла только строки-правила: «of Midlothian», «Enea Łaciate Astoria» и «Das Spiel» ждут",
         (sorted(известное[pipeline.KNOWN_HOME]), sorted(известное[pipeline.KNOWN_AWAY])),
         (["bundesliga live", "liga e kombeve", "ligová fáze"], []))
проверка("по книге «Heart of Midlothian» больше не режется, а «ligová fáze …» — режется",
         (pipeline.trim_by_book("Dundee", "Heart of Midlothian", известное, site_lang.of("start.sportdigital.de")),
          pipeline.trim_by_book("ligová fáze Česko", "Gruzie", известное, site_lang.of("webtv.sk"))[:2]),
         (None, ("Česko", "Gruzie")))
conn.close()
os.environ["STREAMS_DB"] = str(TMP / "t2.db")
db.init_db()
другая = db.connect()
dict_sync.load(другая, файл)
проверка("загрузка словаря в другую базу переносит и команды",
         {r["alias"]: pipeline.seen_teams(r["seen_with"]) for r in другая.execute(
             "SELECT alias, seen_with FROM dictionary_errors WHERE alias IN ('of Midlothian', 'Bundesliga live')")},
         {"of Midlothian": ["heart"], "Bundesliga live": ["lask", "rapid"]})
другая.execute("ALTER TABLE dictionary_errors DROP COLUMN seen_with")
старый = TMP / "старый.json"
dict_sync.export(другая, старый)
проверка("база без нового поля (до миграции) выгружает книгу как раньше, а не теряет её",
         len([r for r in json.loads(старый.read_text(encoding="utf-8"))["dictionary_errors"]
              if r["class"] in (live.KNOWN_HOME, live.KNOWN_AWAY)]), 6)
другая.close()

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

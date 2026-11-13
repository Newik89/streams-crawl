# -*- coding: utf-8 -*-
r"""«Friendly Match Qatar vs. Australia» — матч, а не баскетбол (книга 112).

Жалоба владельца 13.11.2026: товарищеский матч Катар — Австралия шёл на
Al Kass One и Four, эталон flashscore его знал, а на витрине его не было.
Две ошибки подряд:

* читалка alkass.net отрезала «Friendly» турниром, слово «Match» оставила
  хозяевам («Match Qatar»), и правило 6 сняло «Qatar» как приписку страны
  клуба — вышла пара «Match - Australia»;
* словарь лиг давал слову «Friendly» баскетбол — от лиги «BASKETBALL:
  Friendly» (часть названия после двоеточия) — и строку снял фильтр
  «угаданный эфир без эталона (баскет/теннис)».

Что сторожится (весь класс, а не слова жалобы):

1. правило 5а читалки: служебное слово («Match», «Game», «Fixture») после
   названия турнира уходит в турнир; сборные и клубы остаются целыми;
2. прежние заголовки читаются как раньше;
3. правило К2 словаря лиг: часть после «:» — не ключ, если перед «:» стоит
   сам вид спорта;
4. правило К3: название, которое есть у лиг разных видов спорта, вида не
   называет — на ВСЁМ файле словаря (слово владельца 13.11: такие лиги
   записаны за несколькими видами, чтобы эталон искали в каждом из них);
   строка с таким названием, которой эталон не знает ни в одном виде, —
   не вопрос владельцу, а снята с записью в журнал;
5. строка жалобы целиком: вид спорта — не баскетбол.

В сеть не ходит, базу не трогает:

    python scripts/test_friendly_match.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import leagues, sport                      # noqa: E402
from app.parsers import alkass_net                  # noqa: E402

passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


print("1. Служебное слово после турнира — часть турнира (правило 5а)")
for заголовок, лига, пара in (
        ("Friendly Match Qatar vs. Australia",
         "Friendly Match", "Qatar - Australia"),
        ("Friendly Match Saudi Arabia U23 vs. South Korea U23",
         "Friendly Match", "Saudi Arabia U23 - South Korea U23"),
        ("Friendly Match Iraq vs. Lebanon", "Friendly Match", "Iraq - Lebanon"),
        ("Friendly Match United Arab Emirates vs. Honduras",
         "Friendly Match", "United Arab Emirates - Honduras"),
        ("Friendly Match Al Sadd vs. Al Rayyan",
         "Friendly Match", "Al Sadd - Al Rayyan"),
        ("Friendly Game Al Sadd vs. Al Rayyan",
         "Friendly Game", "Al Sadd - Al Rayyan"),
        ("AFC Asian Cup Qualifiers Match Qatar vs. Iran",
         "AFC Asian Cup Qualifiers Match", "Qatar - Iran"),
        ("Friendly Qatar vs. Australia", "Friendly", "Qatar - Australia")):
    вышло = alkass_net.split_title(заголовок)
    check(f"«{заголовок}» → {пара}", вышло == (лига, пара), вышло)

print("2. Прежние заголовки читаются как раньше")
for заголовок, лига, пара in (
        ("Qatar Stars League Al Sadd vs. Al Duhail",
         "Qatar Stars League", "Al Sadd - Al Duhail"),
        ("Amir Cup Final Al Sadd vs. Qatar SC",
         "Amir Cup Final", "Al Sadd - Qatar SC"),
        ("Jetour League Al-Waab vs. Qatar U-23 National Team",
         "Jetour League", "Al-Waab - Qatar U23"),
        ("Qatar vs. Australia", "", "Qatar - Australia"),
        # турнира нет — слово «Match» не трогаем: это может быть имя
        ("Match Day Studio vs. Something", "", "Match Day Studio - Something")):
    вышло = alkass_net.split_title(заголовок)
    check(f"«{заголовок}» → {пара}", вышло == (лига, пара), вышло)

print("3–4. Словарь лиг: ключи К2 и К3 на подставном файле")
СЛОВАРЬ = {"leagues": [
    {"name": "BASKETBALL: Friendly", "sport": "B", "aliases": []},
    {"name": "WORLD: Friendly International", "sport": None,
     "aliases": ["Friendly"]},
    {"name": "DENMARK: Superliga", "sport": "F", "aliases": []},
    {"name": "ALBANIA: Superliga", "sport": "B", "aliases": []},
    {"name": "SPAIN: LaLiga", "sport": "F", "aliases": ["Liga hiszpańska"]},
    {"name": "SPAIN: ACB", "sport": "B", "aliases": ["Liga hiszpańska"]},
    {"name": "USA: NBA", "sport": "B", "aliases": ["НБА"]},
    {"name": "TENNIS: Wimbledon", "sport": "T", "aliases": ["Уимблдон"]},
]}
файл = Path(tempfile.mkdtemp(prefix="friendly-")) / "dictionaries.json"
файл.write_text(json.dumps(СЛОВАРЬ, ensure_ascii=False), encoding="utf-8")
карта = leagues.sports_map(файл)
check("К2: «Friendly» из «BASKETBALL: Friendly» — не ключ",
      "friendly" not in карта, карта.get("friendly"))
check("К2: полное имя «BASKETBALL: Friendly» остаётся баскетболом",
      карта.get("basketball: friendly") == "B")
check("К2: «Wimbledon» из «TENNIS: Wimbledon» — не ключ, алиас «Уимблдон» — ключ",
      "wimbledon" not in карта and карта.get("уимблдон") == "T", карта)
check("К3: «Superliga» (футбол Дании и баскетбол Албании) вида не называет",
      "superliga" not in карта, карта.get("superliga"))
check("К3: полные имена с страной вид называют",
      карта.get("denmark: superliga") == "F"
      and карта.get("albania: superliga") == "B")
check("К3: общий алиас двух видов «Liga hiszpańska» вида не называет",
      "liga hiszpańska" not in карта)
check("однозначные: «NBA», «НБА», «LaLiga», «ACB» — как раньше",
      (карта.get("nba"), карта.get("нба"), карта.get("laliga"),
       карта.get("acb")) == ("B", "B", "F", "B"), карта)

print("4. Настоящий словарь: ни один спорный ключ не даёт букву")
настоящий = json.loads((ROOT / "data" / "dictionaries.json")
                       .read_text(encoding="utf-8"))
карта = leagues.sports_map()


def norm(s: str) -> str:
    return " ".join((s or "").lower().split())


претенденты: dict[str, set] = {}
for лига in настоящий.get("leagues") or []:
    буква = лига.get("sport")
    if буква not in ("F", "B", "T"):
        continue
    имена = [лига.get("name") or ""] + list(лига.get("aliases") or [])
    голова, двоеточие, хвост = имена[0].partition(":")
    if двоеточие and norm(голова) not in leagues.SPORT_HEADS:
        имена.append(хвост)
    for имя in имена:
        if norm(имя):
            претенденты.setdefault(norm(имя), {}).setdefault(
                буква, set()).add(norm(лига.get("name") or ""))
виды = {k: set(v) for k, v in претенденты.items()}
спорные = {k for k, v in виды.items() if len(v) > 1}
check(f"названий, общих для нескольких видов спорта, {len(спорные)} — "
      "ни одно не называет вид", not (спорные & set(карта)),
      sorted(спорные & set(карта))[:8])
check("однозначные названия все в карте с той же буквой",
      all(карта.get(k) == next(iter(v)) for k, v in виды.items()
          if len(v) == 1))
таблица = leagues.contested()
check("`contested` отдаёт те же названия и их виды спорта",
      таблица == {k: виды[k] for k in спорные},
      sorted(set(таблица) ^ спорные)[:6])
check("«Premier League» и «Superliga» — общие для футбола и баскетбола",
      таблица.get("premier league") == {"F", "B"}
      and таблица.get("superliga") == {"F", "B"},
      (таблица.get("premier league"), таблица.get("superliga")))

print("4а. Строка с общим названием лиги — судьбу решает эталон (parse_live)")
sys.path.insert(0, str(ROOT / "scripts"))
import parse_live                                   # noqa: E402
from app.parsers import Program                     # noqa: E402


class Строка:
    def __init__(self, лига, сырая="", рубрика=""):
        self.league = лига
        self.program = Program(channel_raw="К", title="т", start=None,
                               league_raw=сырая, sport_raw=рубрика)


check("лига «Premier League» — общая: виды F и B",
      parse_live.contested_league(Строка("Premier League"), таблица)
      == {"F", "B"})
check("с хвостом сезона «Premier League (T26/27)» — тоже общая",
      parse_live.contested_league(Строка("Premier League (T26/27)"), таблица)
      == {"F", "B"})
check("сырая лига сайта «SUPERLIGA» — общая",
      parse_live.contested_league(Строка("", сырая="SUPERLIGA"), таблица)
      == {"F", "B"})
check("«NBA» — не общая", parse_live.contested_league(Строка("NBA"), таблица)
      == set())
check("лиги нет — не общая",
      parse_live.contested_league(Строка(""), таблица) == set())
check("причина снятия названа словами",
      "нескольких видах спорта" in parse_live.СНЯТО_СПОРНАЯ_ЛИГА)
check("«friendly» вида не называет", "friendly" not in карта,
      карта.get("friendly"))
for ключ, буква in (("la liga", "F"), ("serie a", "F"), ("nba", "B"),
                    ("eurocup", "B"), ("wta", "T"), ("us open", "T")):
    check(f"«{ключ}» → {буква}, как раньше", карта.get(ключ) == буква,
          карта.get(ключ))

print("5. Строка жалобы: вид спорта — не баскетбол")
SPORTS = sport.load()
лига, пара = alkass_net.split_title("Friendly Match Qatar vs. Australia")
стороны = tuple(пара.split(" - "))
вердикт = SPORTS.decide(f"{лига} {пара}", f"{лига}: {пара}", стороны)
check("«Friendly Match: Qatar - Australia» — не баскетбол и не чужой вид",
      вердикт.letter not in ("B", "T", "-"), (вердикт.letter, вердикт.word))

print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, "
      f"красных: {len(failed)}")
sys.exit(1 if failed else 0)

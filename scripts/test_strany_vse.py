# -*- coding: utf-8 -*-
r"""Книги 104 и 105: справочник стран — все страны, все письменности.

Замечание владельца 12.11.2026 (вечер): «нужно не пропускать такие
элементарные моменты… предусматривать возможные пробелы и ошибки». Книга 102
научила словарь странам, но проверена была на трёх словах из жалобы. Сверка
со всем классом нашла дыры:

  * справочник знал 81 страну из двухсот с лишним (не было Ирана, Мальты,
    Перу) — `data/countries.json`, 212 стран;
  * читалась только латиница: «Шотландия», «Σκωτία», «סקוטלנד» странами не
    считались;
  * имя не латиницей с латинским хвостом — «Аль-Васл (UAE)», «Скотт К.
    (Usa)» — читалось страной (чужие буквы выбрасывались, оставалось «UAE»);
  * клуб с именем страны или её местным написанием — «Kuwait SC», «Franca»
    (Франция по-португальски без значка), «Grecia» — считался сборной: на
    страну выходило две команды, и словарь переставал учить её написания;
  * «Czech Republic» и «Czechia» были двумя разными странами;
  * «Suomi N W» (финская буква «N» — женская команда) не читалась (книга 105).

Правила — `app/names.py`, Т1–Т7 над `_country_file`; сборная в словаре —
`dictionary._country_teams`. В сеть не ходит, база — во временной папке.

Запуск: venv\Scripts\python.exe scripts\test_strany_vse.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="strany-vse-"))
os.environ["STREAMS_DB"] = str(TMP / "test.db")

from app import canon, db, dictionary, names  # noqa: E402

total = green = 0


def check(name: str, ok: bool, got=None) -> None:
    global total, green
    total += 1
    green += bool(ok)
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"   ← {got!r}"))


def owner(conn, alias: str) -> list[str]:
    return sorted(r[0] for r in conn.execute(
        "SELECT t.canonical_name FROM team_aliases a JOIN teams t ON t.id = a.team_id "
        "WHERE a.alias = ?", (alias,)))


def countries(*spellings: str) -> list[str]:
    return [names.country_of(s) for s in spellings]


FILE = json.loads((ROOT / "data" / "countries.json").read_text(encoding="utf-8"))
MAINS = list(FILE["страны"])

print("Т1: все страны на месте")
check("стран в справочнике не меньше 205", len(MAINS) >= 205, len(MAINS))
lost = [m for m in MAINS if not names.country_of(m) or not names.country_in_english(m)]
check("каждое английское имя файла — страна и английское имя", not lost, lost)
dead = [(m, s) for m, ss in FILE["страны"].items() for s in ss if names.country_of(s) != names.country_of(m)]
check("КАЖДОЕ написание файла читается своей страной (мёртвых строк нет)", not dead, dead[:10])
for mark in (" W", " U21", " (Ж)", " U19 W"):
    off = [(m, s) for m, ss in FILE["страны"].items() for s in (m, *ss)
           if names.country_of(s + mark) != names.country_of(m)]
    check(f"и с пометкой «{mark.strip()}» — тоже", not off, off[:10])
check("страны, которых не было: Иран, Мальта, Перу, Чили, Катар, Сенегал, Тунис, Узбекистан",
      "" not in countries("Iran", "Malta", "Peru", "Chile", "Qatar", "Senegal", "Tunisia", "Uzbekistan"),
      countries("Iran", "Malta", "Peru", "Chile", "Qatar", "Senegal", "Tunisia", "Uzbekistan"))

print("Т2: любые буквы — кириллица, греческий, иврит, значки")
check("«Шотландия», «Шотландія», «Σκωτία», «סקוטלנד» — Шотландия",
      set(countries("Шотландия", "Шотландія", "Σκωτία", "סקוטלנד")) == {"SCOTLAND"},
      countries("Шотландия", "Шотландія", "Σκωτία", "סקוטלנד"))
check("«Иран», «Іран», «Ιράν», «איראן», «İran», «Irán» — Иран",
      set(countries("Иран", "Іран", "Ιράν", "איראן", "İran", "Irán")) == {"IRAN"},
      countries("Иран", "Іран", "Ιράν", "איראן", "İran", "Irán"))
check("буквы, которые не раскладываются на букву и значок: «Mađarska», «Kırgızistan», «Østerrike»",
      countries("Mađarska", "Kırgızistan", "Østerrike") == ["HUNGARY", "KYRGYZSTAN", "AUSTRIA"],
      countries("Mađarska", "Kırgızistan", "Østerrike"))
check("пометка пола чужими буквами: «Шотландия (Ж)», «Σκωτία Γ»",
      set(countries("Шотландия (Ж)", "Σκωτία Γ")) == {"SCOTLAND"}, countries("Шотландия (Ж)", "Σκωτία Γ"))

print("языки без зеркала flashscore")
pairs = {"Norsunluurannikko": "IVORY COAST", "Päiväntasaajan Guinea": "EQUATORIAL GUINEA",   # финский
         "Saksamaa": "GERMANY", "Lõuna-Korea": "SOUTH KOREA",                                 # эстонский
         "Dienvidāfrika": "SOUTH AFRICA", "Jaunzēlande": "NEW ZEALAND", "Francija": "FRANCE",  # латышский
         "Prancūzija": "FRANCE", "Vokietija": "GERMANY",                                      # литовский
         "Nemčija": "GERMANY", "Madžarska": "HUNGARY",                                        # словенский
         "Skoci": "SCOTLAND", "Maqedoni": "NORTH MACEDONIA", "Zvicra": "SWITZERLAND",         # албанский
         "Tyskland": "GERMANY", "Frankrike": "FRANCE",                                        # норвежский
         "גינאה המשוונית": "EQUATORIAL GUINEA", "חוף השנהב": "IVORY COAST"}                    # иврит
wrong = {s: names.country_of(s) for s, want in pairs.items() if names.country_of(s) != want}
check("финский, эстонский, латышский, литовский, словенский, албанский, норвежский, иврит", not wrong, wrong)

print("Т3: короткие написания")
check("«Fas» (Марокко по-турецки) — не страна: так зовут клуб FAS", names.country_of("Fas") == "",
      names.country_of("Fas"))
check("короткое английское имя — страна: «Peru», «Mali», «Iran», «Cuba», «Togo»",
      countries("Peru", "Mali", "Iran", "Cuba", "Togo") == ["PERU", "MALI", "IRAN", "CUBA", "TOGO"],
      countries("Peru", "Mali", "Iran", "Cuba", "Togo"))
check("разрешённое короткое: «JAR» (ЮАР по-чешски), «RPA» (по-польски)",
      countries("JAR", "RPA") == ["SOUTH AFRICA", "SOUTH AFRICA"], countries("JAR", "RPA"))

print("Т4: одно написание — одна страна")
owners: dict[str, set] = defaultdict(set)
for main, spellings in FILE["страны"].items():
    for spelling in (main, *spellings):
        for key in names._country_keys(spelling):
            owners[key].add(names._tidy(main, exonyms=False))
clash = {k: sorted(v) for k, v in owners.items() if len(v) > 1}
check("в файле нет написания, общего двум странам", not clash, clash)
check("Судан и Южный Судан не путаются",
      countries("Szudán", "Южный Судан", "Sudan", "South Sudan") == ["SUDAN", "SOUTH SUDAN", "SUDAN", "SOUTH SUDAN"],
      countries("Szudán", "Южный Судан", "Sudan", "South Sudan"))
check("венгерское «Dél-» («Южный») — не предлог «del»: «Dél-Szudán», «Dél-Afrika», «Dél-Korea U20»",
      countries("Dél-Szudán", "Dél-Afrika", "Dél-Korea U20") == ["SOUTH SUDAN", "SOUTH AFRICA", "SOUTH KOREA"]
      and countries("Independiente del Valle", "Afrika") == ["", ""],
      (countries("Dél-Szudán", "Dél-Afrika", "Dél-Korea U20"), countries("Independiente del Valle", "Afrika")))
check("Нигер и Нигерия, Конго и ДР Конго, Доминика и Доминикана — разные",
      len(set(countries("Niger", "Nigeria", "Kongo", "DR Kongo", "Dominica", "Dominikana"))) == 6,
      countries("Niger", "Nigeria", "Kongo", "DR Kongo", "Dominica", "Dominikana"))

print("Т5: одна страна — одно имя")
check("«Czech Republic», «Czechia», «Česko», «Tšekki», «Rep. Ceke» — одна страна",
      len(set(countries("Czech Republic", "Czechia", "Česko", "Tšekki", "Rep. Ceke"))) == 1
      and names.country_of("Czechia") != "",
      countries("Czech Republic", "Czechia", "Česko", "Tšekki", "Rep. Ceke"))
check("Босния: «&», «and», «ja», «i», «BiH» — одна страна",
      len(set(countries("Bosnia & Herzegovina", "Bosnia and Herzegovina", "Bosnia ja Hertsegovina",
                        "Bosna i Hercegovina", "BiH"))) == 1 and names.country_of("BiH") != "",
      countries("Bosnia & Herzegovina", "Bosnia and Herzegovina", "Bosnia ja Hertsegovina",
                "Bosna i Hercegovina", "BiH"))
old = {}
for section, block in json.loads((ROOT / "data" / "aliases.json").read_text(encoding="utf-8")).items():
    if section.startswith("_сборные") and isinstance(block, dict):
        old.update(block)
moved = {k: (v, names._country_exonyms().get(k.upper())) for k, v in old.items()
         if names._country_exonyms().get(k.upper()) != names._country_exonyms().get(v.upper(), v.upper())}
check("старый раздел aliases.json читается как раньше", not moved, dict(list(moved.items())[:6]))

print("клуб — не страна")
check("клуб-тёзка местного написания: «Franca», «Granada», «Columbia», «Santa Lucia», «Monaco»",
      countries("Franca", "Granada", "Columbia", "Santa Lucia", "Monaco") == [""] * 5,
      countries("Franca", "Granada", "Columbia", "Santa Lucia", "Monaco"))
check("слово формы клуба: «Kuwait SC», «FC Andorra», «Andorra CF», «Mexico FC», «Stade Tunisien»",
      countries("Kuwait SC", "FC Andorra", "Andorra CF", "Mexico FC", "Stade Tunisien") == [""] * 5,
      countries("Kuwait SC", "FC Andorra", "Andorra CF", "Mexico FC", "Stade Tunisien"))
check("английскому имени страны слово «US» не мешает", names.country_of("US Virgin Islands") != "",
      names.country_of("US Virgin Islands"))
check("не латиница с латинским хвостом: «Аль-Васл (UAE)», «Скотт К. (Usa) ВІДМОВА»",
      countries("Аль-Васл (UAE)", "Скотт К. (Usa) ВІДМОВА") == ["", ""]
      and not names.is_country("Аль-Васл (UAE)"),
      (countries("Аль-Васл (UAE)", "Скотт К. (Usa) ВІДМОВА"), names.is_country("Аль-Васл (UAE)")))
check("и на витрину такое имя страной не выходит",
      "Emirates" not in names.suggest_canonical("Аль-Васл (UAE)"), names.suggest_canonical("Аль-Васл (UAE)"))
check("английское имя: «Scotland W», «Czech Republic», «D.R. Congo», «Trinidad & Tobago» — да",
      all(names.country_in_english(x) for x in ("Scotland W", "Czech Republic", "D.R. Congo",
                                                "Trinidad & Tobago", "USA U23")),
      [x for x in ("Scotland W", "Czech Republic", "D.R. Congo", "Trinidad & Tobago", "USA U23")
       if not names.country_in_english(x)])
check("«Franca», «Grecia», «Kuwait SC», «Skoci», «Шотландия» — не английские имена стран",
      not any(names.country_in_english(x) for x in ("Franca", "Grecia", "Kuwait SC", "Skoci", "Шотландия")),
      [x for x in ("Franca", "Grecia", "Kuwait SC", "Skoci", "Шотландия") if names.country_in_english(x)])

print("найдено на живых сборах 13.11: неопределённые албанские формы, сербские, «Bosnia», иврит")
found = {"Ceki": "CZECHIA", "Itali": "ITALY", "Serbi": "SERBIA", "Angli": "ENGLAND", "Austri": "AUSTRIA",
         "Maqedoni V": "NORTH MACEDONIA", "Letonija": "LATVIA", "Farska Ostrva U19": "FAROE ISLANDS",
         "Νησιά Φερόε": "FAROE ISLANDS", "Република Ирландия": "IRELAND", "Bosnia": "BOSNIA HERZEGOVINA",
         "EUA": "USA", "קניה": "KENYA", "סודן": "SUDAN", "מלאווי": "MALAWI", "Martinique": "MARTINIQUE"}
wrong = {s: names.country_of(s) for s, want in found.items() if names.country_of(s) != want}
check("«Ceki», «Itali», «Letonija», «Νησιά Φερόε», «Република Ирландия», «Bosnia», «קניה» — страны", not wrong, wrong)
check("«Bosna» и «Босна» — баскетбольный клуб из Сараева, не страна",
      countries("Bosna", "Босна") == ["", ""], countries("Bosna", "Босна"))

print("Т8: новое знание не ухудшает догадку по буквам")
kept = names.readings("Repubblica Ceca")
check("написание страны сводится к английскому имени, но чтение «как написано» остаётся",
      kept[0] == "CZECHIA" and "REPUBBLICA CECA" in kept, kept)
check("незнакомое соседнее написание по-прежнему похоже: «Repubblica Cecha» ↔ «Repubblica Ceca»",
      names.similarity("Repubblica Cecha", "Repubblica Ceca") >= names.SIMILAR_ENOUGH,
      names.similarity("Repubblica Cecha", "Repubblica Ceca"))
check("первое чтение — по-прежнему английское имя (ключ вида спорта по командам)",
      names.readings("Dienvidāfrika")[0] == "SOUTH AFRICA" and names.readings("Scotland")[0] == "SCOTLAND",
      (names.readings("Dienvidāfrika"), names.readings("Scotland")))

print("книга 106: пара сборных не получает вид спорта «по командам»")
sys.path.insert(0, str(ROOT / "scripts"))
import parse_live  # noqa: E402

single = {parse_live.sport_key(n): letter for n, letter in (
    ("France", "F"), ("South Africa", "F"), ("Wales", "F"), ("New Zealand", "F"), ("Kasimpasa", "F"),
    ("Amedspor", "F"), ("Andorra", "B"), ("Tenerife", "B"), ("Barcelona W", "B"))}
check("«Francie - JAR», «Wales - Nový Zéland» (регби на Nova Sport) — не решаем",
      parse_live.sport_by_teams("Francie", "JAR", single) == ""
      and parse_live.sport_by_teams("Wales", "Nový Zéland", single) == "",
      (parse_live.sport_by_teams("Francie", "JAR", single), parse_live.sport_by_teams("Wales", "Nový Zéland", single)))
check("клубы — как раньше: «Kasımpaşa - Amedspor» → футбол",
      parse_live.sport_by_teams("Kasımpaşa", "Amedspor", single) == "F",
      parse_live.sport_by_teams("Kasımpaşa", "Amedspor", single))
check("клуб-тёзка страны с клубом: «Andorra - Tenerife» → баскетбол",
      parse_live.sport_by_teams("Andorra", "Tenerife", single) == "B",
      parse_live.sport_by_teams("Andorra", "Tenerife", single))
pairs = parse_live.country_pairs([
    {"home": "Argentina", "away": "Uruguay", "sport": "F", "start_kyiv": "2026-11-14T01:00"},
    {"home": "Spain W", "away": "France W", "sport": "B", "start_kyiv": "2026-11-13T20:00"},
    {"home": "Spain", "away": "France", "sport": "F", "start_kyiv": "2026-11-15T21:45"},
    {"home": "Real Madrid", "away": "Barcelona", "sport": "F", "start_kyiv": "2026-11-15T22:00"}])
check("пару сборных решает эталон: «Argentina - Uruguay» есть в его окне → футбол (повторы снимут фильтры записей)",
      parse_live.sport_by_teams("Argentina", "Uruguay", single, pairs) == "F"
      and parse_live.sport_by_teams("Urugwaj", "Argentyna", single, pairs) == "F",
      (parse_live.sport_by_teams("Argentina", "Uruguay", single, pairs),
       parse_live.sport_by_teams("Urugwaj", "Argentyna", single, pairs)))
check("пары в эталоне нет («Francie - JAR») или она в двух видах спорта («España - Francia») — не решаем",
      parse_live.sport_by_teams("Francie", "JAR", single, pairs) == ""
      and parse_live.sport_by_teams("España", "Francia", single, pairs) == "",
      (parse_live.sport_by_teams("Francie", "JAR", single, pairs),
       parse_live.sport_by_teams("España", "Francia", single, pairs)))
check("одна сторона неизвестна или виды разные — не решаем",
      parse_live.sport_by_teams("Kasımpaşa", "Neznamy", single) == ""
      and parse_live.sport_by_teams("Kasımpaşa", "Tenerife", single) == "",
      (parse_live.sport_by_teams("Kasımpaşa", "Neznamy", single),
       parse_live.sport_by_teams("Kasımpaşa", "Tenerife", single)))

print("Т6: словарь подтверждённых имён справочнику не указ")
names.set_overrides({"Anglia": "Scotland", "Škotska": "Croatia"})
names.country_of.cache_clear()
check("ошибочная запись словаря страну не меняет", countries("Anglia", "Škotska") == ["ENGLAND", "SCOTLAND"],
      countries("Anglia", "Škotska"))
names.set_overrides({})

print("Т7 (книга 105): местная буква пола после страны")
check("«Suomi N W», «Polska K W», «Italia D W», «Nederland V W» — страна",
      countries("Suomi N W", "Polska K W", "Italia D W", "Nederland V W") == ["FINLAND", "POLAND", "ITALY",
                                                                              "NETHERLANDS"],
      countries("Suomi N W", "Polska K W", "Italia D W", "Nederland V W"))
check("без «W» буква — часть имени: «Suomi N» не страна", names.country_of("Suomi N") == "",
      names.country_of("Suomi N"))
check("клуб с буквой: «Real Madrid C W» не страна", names.country_of("Real Madrid C W") == "",
      names.country_of("Real Madrid C W"))

print("показ на витрине: страна — по-английски, как у flashscore")
shown = {s: names.suggest_canonical(s) for s in ("Шотландия (Ж)", "Suomi N W", "Salwador", "Tšekki U21",
                                                 "סקוטלנד", "Dienvidāfrika")}
check("«Шотландия (Ж)» → Scotland W, «Suomi N W» → Finland W, «Salwador» → El Salvador",
      shown == {"Шотландия (Ж)": "Scotland W", "Suomi N W": "Finland W", "Salwador": "El Salvador",
                "Tšekki U21": "Czech Republic U21", "סקוטלנד": "Scotland", "Dienvidāfrika": "South Africa"}, shown)
check("клуб показывается как раньше", names.suggest_canonical("Górnik Zabrze") == "Górnik Zabrze"
      and names.suggest_canonical("PSG") == "PSG",
      (names.suggest_canonical("Górnik Zabrze"), names.suggest_canonical("PSG")))

print("стена книги 103 видит все письменности")
check("«Шотландия» алиасом Хорватии не станет, Шотландии — станет",
      not canon._learnable("Шотландия", "Croatia") and canon._learnable("Шотландия", "Scotland"),
      (canon._learnable("Шотландия", "Croatia"), canon._learnable("Шотландия", "Scotland")))
check("«Иран» не Ирак, «Island» не Ирландия, «Bulharsko» не Израиль",
      not canon._learnable("Иран", "Iraq") and not canon._learnable("Island", "Ireland")
      and not canon._learnable("Bulharsko", "Israel"),
      (canon._learnable("Иран", "Iraq"), canon._learnable("Island", "Ireland"),
       canon._learnable("Bulharsko", "Israel")))
check("клубу стена не мешает: «Franca» ↔ «Franca», «Аль-Васл (UAE)» → «Al Wasl»",
      canon._learnable("Franca", "Franca") and canon._learnable("Аль-Васл (UAE)", "Al Wasl"),
      (canon._learnable("Franca", "Franca"), canon._learnable("Аль-Васл (UAE)", "Al Wasl")))

print("словарь: сборная — команда с английским именем страны")
conn = db.connect()
db.init_db(conn)
for name in ("France", "Franca", "Kuwait", "Kuwait SC", "Finland", "Finland W", "Iran", "Scotland",
             "United Arab Emirates", "Al Wasl", "Greece", "Grecia", "Czech Republic"):
    dictionary.remember_team(conn, name, name)
teams = dictionary._country_teams(conn)
check("клубы «Franca», «Kuwait SC», «Grecia» сборными не считаются",
      [n for _, n in teams.get(("FRANCE", ""), [])] == ["France"]
      and [n for _, n in teams.get(("KUWAIT", ""), [])] == ["Kuwait"]
      and [n for _, n in teams.get(("GREECE", ""), [])] == ["Greece"],
      {k: v for k, v in teams.items() if k[0] in ("FRANCE", "KUWAIT", "GREECE")})
got = dictionary.learn_country_sides(conn, ["Ranska", "Кувейт", "Иран", "Σκωτία", "Kreikka", "Tšekki"])
check("написания учатся, клуб-тёзка не мешает: «Ranska» → France, «Кувейт» → Kuwait, «Kreikka» → Greece",
      owner(conn, "Ranska") == ["France"] and owner(conn, "Кувейт") == ["Kuwait"]
      and owner(conn, "Kreikka") == ["Greece"] and not got["спор"], got)
check("новая страна и чужие буквы: «Иран» → Iran, «Σκωτία» → Scotland, «Tšekki» → Czech Republic",
      owner(conn, "Иран") == ["Iran"] and owner(conn, "Σκωτία") == ["Scotland"]
      and owner(conn, "Tšekki") == ["Czech Republic"],
      (owner(conn, "Иран"), owner(conn, "Σκωτία"), owner(conn, "Tšekki")))
got = dictionary.learn_country_sides(conn, ["Suomi N W"])
check("книга 105: «Suomi N W» → Finland W", owner(conn, "Suomi N W") == ["Finland W"],
      (owner(conn, "Suomi N W"), got))
check("а «Suomi N» мужской сборной не достаётся", owner(conn, "Suomi N") == [], owner(conn, "Suomi N"))
got = dictionary.learn_country_sides(conn, ["Аль-Васл (UAE)", "Kuwait SC U19", "Franca"])
check("клуб с хвостом страны, клуб с формой, клуб-тёзка — сборной не становятся",
      not got["выучено"] and owner(conn, "Аль-Васл (UAE)") == [] and owner(conn, "Kuwait SC U19") == []
      and owner(conn, "Franca") == ["Franca"], (got, owner(conn, "Franca")))

print("зеркало flashscore отдало пару в обратном порядке — страны местами не меняются")
for name in ("Congo U20", "Gabon U20", "Iraq"):
    dictionary.remember_team(conn, name, name)
learned = canon.learn_by_id(conn, [
    {"sport": "F", "home": "Congo U20", "away": "Gabon U20", "fs_id": "swap0001", "league": "AFRICA: U20",
     "start_kyiv": "2026-11-14T18:00", "names": {"da": ["Gabon U20", "Congo U20"], "ru": ["Конго U20", "Габон U20"]}},
    {"sport": "F", "home": "Iran", "away": "Iraq", "fs_id": "norm0001", "league": "ASIA: WCQ",
     "start_kyiv": "2026-11-14T19:00", "names": {"bg": ["Иран", "Ирак"], "hu": ["Irán", "Irak"]}}])
check("перевёрнутая пара не выучена: «Gabon U20» (da) не стал Congo U20",
      owner(conn, "Gabon U20") == ["Gabon U20"] and owner(conn, "Congo U20") == ["Congo U20"],
      (owner(conn, "Gabon U20"), owner(conn, "Congo U20")))
check("верный порядок учится как раньше: «Конго U20», «Габон U20», «Ирак», «Irak»",
      owner(conn, "Конго U20") == ["Congo U20"] and owner(conn, "Габон U20") == ["Gabon U20"]
      and owner(conn, "Ирак") == ["Iraq"] and owner(conn, "Irak") == ["Iraq"] and learned[0] >= 4,
      (owner(conn, "Конго U20"), owner(conn, "Габон U20"), owner(conn, "Ирак"), owner(conn, "Irak"), learned))

print("точное знание (`country_exact`) — для правила С12")
exact = {s: names.country_exact(s) for s in ("Island", "ISLÂNDIA", "Ισλανδία", "איסלנד", "Shqiperi", "Конго U20",
                                             "Gabon U20", "Dél-Szudán", "Franca", "Kuwait SC", "Fas",
                                             "Suomi N W", "Аль-Васл (UAE)")}
check("написание буква в букву из справочника — страна; клуб, короткое и догадка — нет",
      exact == {"Island": "ICELAND", "ISLÂNDIA": "ICELAND", "Ισλανδία": "ICELAND", "איסלנד": "ICELAND",
                "Shqiperi": "ALBANIA", "Конго U20": "CONGO", "Gabon U20": "GABON", "Dél-Szudán": "SOUTH SUDAN",
                "Franca": "", "Kuwait SC": "", "Fas": "", "Suomi N W": "", "Аль-Васл (UAE)": ""}, exact)
loose = [s for main, ss in FILE["страны"].items() for s in (main, *ss)
         if names.country_exact(s) != names.country_of(s)]
check("точный поиск не расходится с полным ни на одном написании файла", not loose, loose[:8])

print("С12: старую запись «страна A → сборная страны B» словарь не читает (в базе она остаётся)")
for name in ("Ireland", "Iceland", "Israel", "Bulgaria", "Austria", "Austria Vienna"):
    dictionary.remember_team(conn, name, name)
dictionary.remember_team(conn, "Island", "Ireland")              # ошибка, как в живом словаре
dictionary.remember_team(conn, "Island", "Iceland", lang="cs")   # верная запись зеркала
dictionary.remember_team(conn, "Bulharsko", "Israel")            # ошибка, верной записи нет
dictionary.remember_team(conn, "Austrija", "Austria Vienna")     # клуб — не трогаем
book = dictionary.team_names(conn)
verdict, ids = book.decide("Island")
check("«Island»: запись за Ирландией не читается — отвечает Исландия, спора нет",
      verdict == dictionary.DECIDED and book.canon_of[ids[0]] == "Iceland",
      (verdict, [book.canon_of[i] for i in ids]))
check("«Bulharsko» за Израилем — словарь молчит, а не врёт", book.decide("Bulharsko")[0] == dictionary.UNKNOWN,
      book.decide("Bulharsko"))
check("клуб читается как раньше: «Austrija» → Austria Vienna",
      (book.owner("Austrija") or (0, ""))[1] == "Austria Vienna", book.owner("Austrija"))
check("записи из базы не удалены", sorted(owner(conn, "Island")) == ["Iceland", "Ireland"]
      and owner(conn, "Bulharsko") == ["Israel"], (owner(conn, "Island"), owner(conn, "Bulharsko")))
got = dictionary.learn_country_sides(conn, ["Bulharsko"])
check("и верной команде такая запись не мешает: «Bulharsko» выучено за Bulgaria",
      "Bulgaria" in owner(conn, "Bulharsko") and got["выучено"] == [("Bulharsko", "Bulgaria")]
      and (dictionary.team_names(conn).owner("Bulharsko") or (0, ""))[1] == "Bulgaria",
      (got, owner(conn, "Bulharsko"), dictionary.team_names(conn).owner("Bulharsko")))
conn.close()

print(f"\n{green}/{total} зелёных")
raise SystemExit(0 if green == total else 1)

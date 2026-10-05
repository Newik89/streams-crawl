# -*- coding: utf-8 -*-
r"""Проверки решения «наш вид спорта или чужой» (владелец 06.10.2026).

Игра #4710, ПСЖ — Ле-Ман: слово «le mans» в `data/markers.json` — признак
автоспорта, и футбольный матч Лиги 1 с восьми сайтов уезжал во вкладку
Other Sport, а на витрине оставался один канал. Теперь всё решение живёт в
одном месте — `app/sport.py` → `Sports.decide`, десять правил по номерам.
Здесь на каждое правило свои сценарии, с именами; номер сработавшего правила
проверяется вместе с ответом.

Плюс три проверки вокруг правил:
  * СТОРОЖ словаря: ни одна команда словаря, написанная как в словаре, не
    читается чужим видом спорта, когда она — сторона пары. Список слов,
    совпавших с именами команд, печатается: добавили в markers.json слово,
    совпавшее с клубом, — оно появится здесь само;
  * слова наших видов спорта на языках всех сайтов плана;
  * разные написания одной команды (PSG, Paris St G, Paris Saint-Germain,
    PARIS ST GERMAIN…) сводятся в одну игру.

В сеть не ходит, базу и файлы не трогает: строки собраны по настоящим
страницам прогона #201 (05.10.2026). Запуск:

    python scripts/test_sport_words.py

Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import leagues, live, merge, names, pipeline, sport   # noqa: E402
from app.live import greek_plain                               # noqa: E402
from app.parsers import Program                                # noqa: E402
from app.reference import REF_SURE, REF_WINDOW, Reference      # noqa: E402

passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


KYIV = ZoneInfo("Europe/Kyiv")
MARKERS = live.load()
SPORTS = sport.load()                       # слова и словарь команд — настоящие
#: команды заданы прямо здесь — сценарии не зависят от того, что сейчас
#: лежит в data/dictionaries.json
СВОИ = sport.load(teams=(
    "Le Mans", "Le Mans FC", "Remo", "Gimnasia y Esgrima La Plata",
    "UFC Fehring", "Box Hill", "Shooting Stars", "Dakar SC", "Marathon",
    "Enduro FC", "Πολόνια Βαρσοβίας"))
БЕЗ_КОМАНД = sport.load(teams=())
#: маленький эталон flashscore: то, что он знает на вечер 10.10 и на 07.10
ЭТАЛОН = Reference([
    {"sport": "F", "home": "PSG", "away": "Le Mans", "league": "FRANCE: Ligue 1",
     "start_kyiv": "2026-10-10T21:45",
     "names": {"bg": ["ПСЖ", "Льо Ман"], "de": ["PSG", "Le Mans FC"]}},
    {"sport": "B", "home": "Tortona", "away": "Le Mans",
     "league": "EUROPE: Eurocup", "start_kyiv": "2026-10-07T20:30"},
    {"sport": "F", "home": "Braga", "away": "Sporting CP",
     "league": "PORTUGAL: Liga Portugal", "start_kyiv": "2026-10-09T22:15"},
    {"sport": "F", "home": "Decic", "away": "Petrovac",
     "league": "MONTENEGRO: Prva liga", "start_kyiv": "2026-10-10T16:00"},
    {"sport": "B", "home": "St. Polten", "away": "Traiskirchen Lions",
     "league": "AUSTRIA: Superliga", "start_kyiv": "2026-10-09T19:00"},
    # дерби одних клубов в один вечер и в футболе, и в баскетболе
    {"sport": "F", "home": "Partizan", "away": "Crvena zvezda",
     "league": "SERBIA: Super Liga", "start_kyiv": "2026-10-11T18:00"},
    {"sport": "B", "home": "Partizan", "away": "Crvena zvezda",
     "league": "EUROPE: ABA League", "start_kyiv": "2026-10-11T20:00"},
])


def решение(title, league="", kind="", match="", description="", *,
            when="2026-10-10T21:45", sports=None, reference=None,
            league_sports=None, pair_sports=None):
    """Чем кончил конвейер и какое правило сработало: («F», 5), («чужой», 4),
    («?», 10) — «?» значит «вид спорта не определён»: строка уйдёт на досбор,
    а не в Other Sport."""
    start = datetime.fromisoformat(when).replace(tzinfo=KYIV)
    program = Program(channel_raw="Тест Sport 1", title=title, start=start,
                      description=description, league_raw=league,
                      sport_raw=kind, live_raw="live", match_raw=match)
    row = pipeline.classify(program, MARKERS, sports or СВОИ,
                            league_sports or {}, pair_sports or {}, reference)
    if row.ok:
        return row.sport, row.sport_rule
    if row.reason.startswith("другой вид спорта"):
        return "чужой", row.sport_rule
    if row.reason == "вид спорта не определён":
        return "?", row.sport_rule
    return row.reason, row.sport_rule


def сценарии(список, **общее):
    """(имя сценария, ждём, правило, заголовок, лига, категория, пара,
    описание, время)."""
    for имя, ждём, правило, title, *rest in список:
        league, kind, match, description, when = (list(rest) + [""] * 5)[:5]
        доп = dict(общее)
        if when:
            доп["when"] = when
        вышло = решение(title, league, kind, match, description, **доп)
        check(f"{имя}: «{match or title}» → {ждём}, правило {правило}",
              вышло == (ждём, правило), f"(вышло: {вышло})")


# ── правило 1: слово жанра ───────────────────────────────────────────────────
print("Правило 1 — слово жанра: передача о матче — не матч")
сценарии([
    ("передача о матче остаётся передачей, хотя эталон матч знает",
     "чужой", 1, "SC BRAGA X SPORTING CP", "JOGO GRANDE - INFORMAÇÃO",
     "INFORMAÇÃO", "", "", "2026-10-09T22:15"),
    ("передача о матче без эталона — тоже не матч",
     "чужой", 1, "MARÍTIMO X FC PORTO", "JOGO GRANDE - INFORMAÇÃO",
     "INFORMAÇÃO"),
], reference=ЭТАЛОН)

# ── правило 2: эталон flashscore ─────────────────────────────────────────────
print("Правило 2 — эталон flashscore знает пару в это время")
check("порог сходства пары с эталоном — 95", REF_SURE == 95)
check("окно времени вокруг матча эталона — 3 часа",
      REF_WINDOW == timedelta(hours=3))
# настоящие строки прогона #201: одна игра, восемь написаний
ПСЖ_ЛЕМАН = [
    ("sporttv.pt SPORT.TV3", "PARIS ST GERMAIN X LE MANS",
     "LIGA FRANCESA - FUTEBOL", "FUTEBOL", "PARIS ST GERMAIN X LE MANS", "",
     "2026-10-10T21:40"),
    ("teleman.pl Eleven Sports 3", "Piłka nożna: Liga francuska",
     "Piłka nożna: Liga francuska", "Piłka nożna",
     "Paris Saint-Germain - Le Mans FC",
     "mecz: Paris Saint-Germain - Le Mans FC", "2026-10-10T21:40"),
    ("tvarenasport.ba Arena Premium 1", "PSG - Le Mans", "Francuska liga",
     "Fudbal", "PSG - Le Mans", "", "2026-10-10T21:45"),
    ("tvarenasport.hr Arena Sport 1", "PSG - LE MANS", "FRANCUSKA LIGA",
     "Nogomet", "PSG - LE MANS", "", "2026-10-10T21:45"),
    ("oneplay.cz Nova Sport 3", "PSG - Le Mans FC", "", "", "PSG - Le Mans FC",
     "", "2026-10-10T21:40"),
    ("tv3.lt Go3 Sport 2", 'Ligue 1. PSG - "Le Mans"', "Ligue 1", "",
     "PSG - Le Mans", "8 serija", "2026-10-10T21:35"),
    ("epg.cyta.com.cy Cablenet Sports 2 HD", "Paris Saint-Germain - Le Mans",
     "", "", "Paris Saint-Germain - Le Mans", "", "2026-10-10T21:45"),
    ("tvsporten.dk TV3 Sport", "Paris Saint Germain - Le Mans", "Ligue 1",
     "Fodbold", "Paris Saint Germain - Le Mans", "", "2026-10-10T21:45"),
]
сценарии([(f"матч из эталона — футбол, хотя «Le Mans» ещё и гонка ({где})",
           "F", 2, title, league, kind, match, description, when)
          for где, title, league, kind, match, description, when in ПСЖ_ЛЕМАН],
         reference=ЭТАЛОН, sports=БЕЗ_КОМАНД)
сценарии([
    ("баскетбольный Ле-Ман из эталона — баскетбол",
     "B", 2, "Košarka - Eurocup: Tortona - Le Mans", "Eurocup", "Košarka",
     "Tortona - Le Mans", "", "2026-10-07T20:30"),
    ("эталон сильнее слова чужого вида в лиге (CFL — лига Черногории)",
     "F", 2, "Dečić - Petrovac", "CFL - 8. kolo", "", "", "",
     "2026-10-10T16:00"),
    ("эталон сильнее названия турнира (Superliga записана за футболом)",
     "B", 2, "LIVE Basketball Herren Superliga 4. Runde: SKN St. Pölten - "
     "Traiskirchen Lions", "LIVE Basketball Herren Superliga", "", "", "",
     "2026-10-09T18:55"),
    ("эталон сильнее лиги из словаря лиг",
     "B", 2, "Tortona - Le Mans", "Liga Evropa", "", "", "",
     "2026-10-07T20:30"),
], reference=ЭТАЛОН, sports=БЕЗ_КОМАНД, league_sports={"liga evropa": "F"})
сценарии([
    ("эталон знает пару и в футболе, и в баскетболе — он не судья, решает "
     "слово сайта", "B", 5, "Partizan - Crvena zvezda", "ABA liga", "Košarka",
     "", "", "2026-10-11T19:00"),
    ("…и гандбол тех же клубов остаётся гандболом",
     "чужой", 4, "Partizan - Crvena zvezda", "Superliga", "Rukomet", "", "",
     "2026-10-11T19:00"),
    ("время не то (пять часов до матча) — эталон молчит",
     "чужой", 4, "PSG - Le Mans", "", "", "", "", "2026-10-10T16:30"),
    ("вторая команда другая — эталон молчит",
     "?", 10, "PSG - Lens", "", "", "", "", "2026-10-10T21:45"),
], reference=ЭТАЛОН, sports=БЕЗ_КОМАНД)

# ── правило 3: сайт назвал наш вид спорта, чужое слово — внутри команды ──────
print("Правило 3 — сайт назвал наш вид спорта, а слово чужого вида стоит "
      "внутри названия команды (словарь команд не нужен)")
сценарии([(f"сайт пишет «футбол», «Le Mans» — команда в паре ({где})", "F", 3,
           title, league, kind, match, description, when)
          for где, title, league, kind, match, description, when in ПСЖ_ЛЕМАН
          if kind or "Piłka" in title], sports=БЕЗ_КОМАНД)
сценарии([
    ("слово вида спорта в описании (oneplay.cz)", "F", 3, "PSG - Le Mans FC",
     "", "", "PSG - Le Mans FC", "PSG - Le Mans FC Přímý přenos 6. kola "
     "nejvyšší francouzské fotbalové ligy Ligue 1 McDonald's"),
    ("слово вида спорта в описании по-гречески (cyta)", "F", 3,
     "Paris Saint-Germain - Le Mans", "", "", "",
     "Οι δεκαοχτώ καλύτερες ομάδες του Γαλλικού ποδοσφαίρου συναγωνίζονται"),
    ("баскетбол по-литовски (tv3.lt)", "B", 3,
     "Prancūzijos LNB krepšinio lyga. Le Mans - Paris",
     "Prancūzijos LNB krepšinio lyga", "", "Le Mans - Paris"),
    ("баскетбол по-сербски (tvarenasport.com)", "B", 3, "Le Mans - Paris",
     "FRANCUSKA LIGA", "Košarka"),
    ("имя команды длиннее чужого слова: Clube do Remo", "F", 3,
     "CLUBE DO REMO X FLAMENGO", "BRASILEIRÃO - FUTEBOL"),
    ("…Gimnasia y Esgrima", "F", 3,
     "GIMNASIA Y ESGRIMA LA PLATA RESERVA X BOCA JUNIORS",
     "LIGA ARGENTINA - FUTEBOL"),
    ("…Box Hill", "F", 3, "Box Hill United - Preston Lions",
     "NPL Victoria - Football"),
    ("…UFC Fehring", "F", 3, "UFC Fehring - SV Lafnitz",
     "Regionalliga Mitte - Fußball"),
    ("…Dakar SC в баскетболе", "B", 3, "Dakar SC - AS Douanes",
     "Basketball Africa League"),
    ("…греческое написание", "F", 3, "Πολόνια Βαρσοβίας - Λέγκια",
     "Ποδόσφαιρο"),
], sports=БЕЗ_КОМАНД)
print("Правило 3 не срабатывает — чужое слово стоит не в имени команды")
сценарии([
    ("канадский футбол: «CFL» в лиге, хотя рядом «Football» (tvpassport.com)",
     "чужой", 4, "CFL Football: Edmonton Elks - Hamilton Tiger-Cats",
     "CFL Football"),
    ("пляжный футбол: тёзка «Le Mans» в паре, но «FUTEBOL PRAIA» в категории",
     "чужой", 4, "LE MANS X BRASIL", "MUNDIALITO", "FUTEBOL PRAIA"),
    ("футзал: слово в лиге, категория «Futebol»", "чужой", 4,
     "SPORTING CP X SL BENFICA", "LIGA PLACARD - FUTSAL", "FUTEBOL"),
    ("гонка: «Le Mans» перед парой, а не в ней", "чужой", 4,
     "24 Horas de Le Mans: Porsche - Toyota", "Futebol e Motores"),
], sports=СВОИ)

# ── правило 4: слово чужого вида спорта, не имя команды ──────────────────────
print("Правило 4 — слово чужого вида спорта, которое не имя команды из пары")
сценарии([
    # гонки в Ле-Мане остаются гонками и при команде «Le Mans» в словаре
    ("гонка: чужое слово в лиге", "чужой", 4, "24 HORAS DE LE MANS - CORRIDA",
     "WEC - AUTOMOBILISMO", "AUTOMOBILISMO"),
    ("гонка: чужое слово в категории", "чужой", 4,
     "24 Stunden von Le Mans - Start", "", "Motorsport"),
    ("гонка: целое название серии", "чужой", 4,
     "Michelin Le Mans Cup - Portimão"),
    ("гонка: слово не в паре, а перед ней", "чужой", 4,
     "European Le Mans Series: Spa - Race"),
    ("гонка: сторона — команда словаря, но в лиге WEC", "чужой", 4,
     "Le Mans - Start", "WEC"),
    ("гонка: сторона — команда словаря, но рядом «závod»", "чужой", 4,
     "Le Mans - Závod"),
    ("гонка: GP", "чужой", 4, "GP Monza - Race", "Formula 1"),
    ("ралли", "чужой", 4, "Rally Dakar - Etapa 5"),
    ("гребля у команды-тёзки", "чужой", 4, "Remo - Final A", "World Rowing Cup"),
    ("марафон у команды-тёзки", "чужой", 4, "Marathon - Olimpia", "Atletismo"),
    # настоящие строки прогона #201, где слово стоит ВНУТРИ стороны пары
    ("мотогонки movistarplus.es", "чужой", 4,
     "MotoGP - GP de Japón (T2026): Carrera MotoGP", "", "Deportes"),
    ("мотогонки tring.al", "чужой", 4, "France GP - Gara MotoGP", "MotoGP"),
    ("велоспорт tv3.lt", "чужой", 4,
     "Велоспорт - Чемпионат Европы на шоссе. Любляна"),
    ("снукер tv3.lt", "чужой", 4,
     "Снукер - Home Nations Series English Open. English Open"),
    ("регби oneplay.cz", "чужой", 4, "Leicester Tigers - Gloucester Rugby"),
    ("регби sporttv.pt", "чужой", 4, "MONTPELLIER HÉRAULT RUGBY X RC TOULON",
     "RUGBY TOP 14 - RUGBY", "RUGBY"),
    ("хоккей allente.no", "чужой", 4,
     "Tampa Bay Lightning - Philadelphia Flyers", "NHL", "Ishockey"),
    ("хоккей без лиги — по именам клубов НХЛ", "чужой", 4,
     "Dallas Stars - Florida Panthers"),
    ("хоккей со словом перед парой", "чужой", 4,
     "Hokej: Sparta Praha - Kometa Brno"),
    ("единоборства sporttv.pt", "чужой", 4, "UFC 332 - SILVA X WANG",
     "UFC PPV - DESPORTOS COMBATE"),
    ("экстрим tv2.no", "чужой", 4, "X Games - Minneapolis"),
])
print("Правило 4 — составные чужие виды: слово «футбол» или «теннис» внутри названия")
сценарии([
    ("американский футбол rte.ie", "чужой", 4, "NFL Live", "NFL",
     "American Football", "Washington Commanders - Indianapolis Colts"),
    ("американский футбол: одна категория, без NFL (сербский)", "чужой", 4,
     "Dallas - Tampa Bay", "", "Američki fudbal"),
    ("американский футбол: одна категория (хорватский)", "чужой", 4,
     "CAROLINA - DETROIT", "", "Američki nogomet"),
    ("американский футбол (норвежский)", "чужой", 4,
     "Dallas Cowboys - New York Giants", "", "Amerikansk fotball"),
    ("американский футбол (греческий)", "чужой", 4,
     "Αμερικάνικο Ποδόσφαιρο: Καρολάινα Πάνθερς - Ντιτρόιτ Λάιονς"),
    ("американский футбол (словацкий)", "чужой", 4,
     "Dallas Cowboys - New York Giants", "", "Americký futbal"),
    ("пляжный футбол sporttv.pt", "чужой", 4, "BRASIL X PORTUGAL",
     "MUNDIALITO BEACH SOCCER - FUTEBOL PRAIA", "FUTEBOL PRAIA"),
    ("пляжный футбол: одна категория, без «beach soccer»", "чужой", 4,
     "ESPANHA X PORTUGAL", "MUNDIALITO", "FUTEBOL PRAIA"),
    ("мини-футбол news.by", "чужой", 4,
     "Мини-футбол. Чемпионат Беларуси. Столица (Минск) - МФК Борисов-900",
     "Чемпионат Беларуси", "Мини-футбол", "Столица - МФК Борисов-900"),
    ("футзал (испанский)", "чужой", 4, "Barça - ElPozo Murcia",
     "Primera División", "Fútbol Sala"),
    ("австралийский футбол tvpassport.com", "чужой", 4,
     "AFL Women's Premiership Football: Collingwood Magpies vs. Melbourne Demons",
     "AFL Women's Premiership Football", "",
     "Collingwood Magpies - Melbourne Demons"),
    ("гэльские игры rte.ie", "чужой", 4, "GAA Beo", "GAA Beo", "Gaelic Games",
     "Glenswilly - Naomh Conaill"),
    ("гандбол с «Superliga» teleman.pl", "чужой", 4,
     "Piłka ręczna mężczyzn: LOTTO Superliga",
     "Piłka ręczna mężczyzn: LOTTO Superliga", "Piłka ręczna mężczyzn",
     "PGE Wybrzeże Gdańsk - Corotop Gwardia Opole"),
    ("волейбол с «Премьер-лига» ntvplus.tv", "чужой", 4,
     "Волейбол. Бундеслига. Женщины. Премьер-лига", "Бундеслига", "Волейбол",
     "Дрезден - Штутгарт"),
    ("настольный теннис (португальский)", "чужой", 4, "PORTUGAL X ESPANHA",
     "CAMPEONATO DA EUROPA - TÉNIS DE MESA", "TÉNIS DE MESA"),
    ("настольный теннис (польский)", "чужой", 4,
     "Tenis stołowy: Polska - Niemcy"),
    ("настольный теннис (хорватский)", "чужой", 4,
     "Stolni tenis: Hrvatska - Srbija"),
    ("настольный теннис (немецкий)", "чужой", 4,
     "Tischtennis Bundesliga: Düsseldorf - Ochsenhausen"),
    ("падел (испанский)", "чужой", 4, "Pádel: Galán/Chingotto - Coello/Tapia",
     "Premier Padel"),
    # падежи составных видов: слово «футбола», «tenisa» само по себе — наше
    ("американский футбол, родительный (русский)", "чужой", 4,
     "Матч американского футбола: Даллас - Нью-Йорк"),
    ("американский футбол, родительный (хорватский)", "чужой", 4,
     "Prijenos američkog nogometa: Dallas - Tampa Bay"),
    ("настольный теннис, дательный (русский)", "чужой", 4,
     "Чемпионат Европы по настольному теннису: Россия - Сербия"),
    ("мини-футбол, предложный (русский)", "чужой", 4,
     "Кубок по мини-футболе: Столица - Борисов-900"),
    ("настольный теннис, родительный (хорватский)", "чужой", 4,
     "Prvenstvo stolnog tenisa: Hrvatska - Srbija"),
    ("футзал, родительный (хорватский)", "чужой", 4,
     "Prvenstvo futsala: Olmissum - Futsal Pula"),
])

# ── имя команды из словаря: сторона пары, а не вид спорта ────────────────────
print("Имя команды по словарю — не слово вида спорта (правила 4, 9 и 10)")
сценарии([
    ("сторона — ровно команда словаря, сайт молчит: не чужой, на досбор",
     "?", 10, "Nice - Le Mans"),
    ("то же заглавными и с «FC»", "?", 10, "LE MANS FC - BREST"),
    ("то же в кавычках", "?", 10, 'PSG - "Le Mans"'),
    ("соперника словарь не знает (cyta: Derthona)", "?", 10,
     "Derthona - Le Mans"),
    ("другие команды-тёзки: Remo, Enduro FC, Gimnasia", "?", 10,
     "Remo - Flamengo"),
    ("…", "?", 10, "Enduro FC - Lens"),
    ("…", "?", 10, "Gimnasia y Esgrima La Plata - Boca Juniors"),
    ("правило 9: имя команды — лишь часть стороны, сайт молчит → чужой",
     "чужой", 9, "24 Hours of Le Mans - Race"),
    ("правило 9: «Clube do Remo» без слова вида спорта → чужой",
     "чужой", 9, "Clube do Remo - Flamengo"),
    ("правило 9: «Berlin Marathon» → чужой", "чужой", 9,
     "Berlin Marathon - Elite"),
])
сценарии([("без команды в словаре то же слово — чужой вид, как и было",
           "чужой", 4, "Enduro FC - Lens")], sports=БЕЗ_КОМАНД)

# ── правило 5: сайт сам назвал наш вид спорта ────────────────────────────────
print("Правило 5 — сайт сам назвал наш вид спорта (чужих слов в строке нет)")
сценарии([
    ("слово вида спорта в категории", "F", 5, "Benfica - Porto", "Liga Portugal",
     "Futebol"),
    ("слово вида спорта только в описании", "F", 5, "Benfica - Porto", "", "",
     "", "Přímý přenos fotbalového utkání"),
    ("слово вида спорта сильнее названия турнира (Basketball + Superliga)",
     "B", 5, "LIVE Basketball Herren Superliga 4. Runde: SKN St. Pölten - "
     "Traiskirchen Lions", "LIVE Basketball Herren Superliga"),
    ("…то же по-русски (Баскетбол + Премьер-лига)", "B", 5,
     "Баскетбол. Премьер-лига. Женщины. УГМК - Динамо Курск"),
    ("…название турнира работает, когда слова вида спорта нет", "F", 5,
     "Superliga: FCSB - Rapid"),
    ("заголовок сильнее описания (Tenis в заголовке, fotbal в описании)",
     "T", 5, "Tenis: ATP Tokio: Alcaraz - Munar", "", "", "",
     "Po zápase následuje fotbal"),
])

# ── правила 6–8 и 10 ─────────────────────────────────────────────────────────
print("Правила 6, 7, 8 и 10 — лига из словаря, женский клуб, подсказка, «не определён»")
сценарии([("правило 6: лига строки есть в словаре лиг", "F", 6,
           'Ligue 1. PSG - "Le Mans"', "Ligue 1", "", "PSG - Le Mans")],
         league_sports={"ligue 1": "F"})
сценарии([("правило 7: сугубо женский клуб", "B", 7,
           "USK Prague - Athinaikos Qualco")])
сценарии([("правило 8: подсказка владельца по паре", "B", 8,
           "Derthona - Le Mans")],
         pair_sports={"Derthona - Le Mans": ("B", None)})
сценарии([
    ("правило 8: подсказка на другой день не действует", "?", 10,
     "Derthona - Le Mans")],
    pair_sports={"Derthona - Le Mans": ("B", "2026-09-01")})
сценарии([("правило 10: никто ничего не сказал", "?", 10, "Alfa - Beta")])

# ── сторож: слова чужих видов против имён команд словаря ─────────────────────
print("Сторож — слова чужих видов спорта в именах команд словаря")
совпадения: dict[str, dict[str, None]] = {}     # слово → написания команд
for имя in sport._dictionary_teams():
    for слово in SPORTS._alien_hits(greek_plain(имя or "")):
        совпадения.setdefault(слово.lower(), {})[имя] = None
слова_имена = SPORTS.team_words()
check("словарь команд прочитан, совпадения найдены", bool(совпадения))
check("«le mans» — среди слов, совпавших с командой", "le mans" in слова_имена)
check("правило знает каждое совпавшее слово",
      set(совпадения) == set(слова_имена),
      f"(расходятся: {sorted(set(совпадения) ^ set(слова_имена))})")
for слово in sorted(совпадения):
    имена = list(совпадения[слово])
    print(f"     «{слово}» [{SPORTS.group_of(слово)}] — написаний {len(имена)}: "
          + " | ".join(имена[:4]) + (" …" if len(имена) > 4 else ""))
голые, со_словом, гонки = [], [], []
for слово, имена in совпадения.items():
    for имя in имена:
        пара = ("Testovci", имя)
        if SPORTS.decide(f"Testovci - {имя}", pair=пара).letter == "-":
            голые.append(имя)
        if SPORTS.decide(f"Testovci - {имя} Football", pair=пара).letter != "F":
            со_словом.append(имя)
        # то же имя с лишним словом и без слова нашего вида — может быть
        # гонкой («24 Hours of Le Mans»): остаётся чужим (правило 9)
        длинное = f"Superspecial {имя}"
        if SPORTS.decide(f"{длинное} - Start", pair=(длинное, "Start")).rule != 9:
            гонки.append(имя)
всего = sum(len(v) for v in совпадения.values())
check(f"команда словаря как сторона пары — не чужой вид ({всего} написаний)",
      not голые, f"(чужим остались: {голые[:8]})")
check("та же пара со словом Football от сайта → футбол",
      not со_словом, f"(не футбол: {со_словом[:8]})")
check("имя с лишним словом и без слова нашего вида → чужой, правило 9",
      not гонки, f"(не правило 9: {гонки[:8]})")

# ── слова наших видов спорта на языках сайтов ────────────────────────────────
print("Слова наших видов спорта на языках всех сайтов плана")
# язык: (футбол, баскетбол, теннис) — как пишут сайты; пусто — слова нет
ЯЗЫКИ = {
    "английский": ("Football", "Basketball", "Tennis"),
    "английский (США)": ("Soccer", "Basketball", "Tennis"),
    "немецкий": ("Fußball", "Basketball", "Tennis"),
    "немецкий без ß": ("Fussball", "Basketball", "Tennis"),
    "французский": ("Football", "Basket", "Tennis"),
    "итальянский": ("Calcio", "Pallacanestro", "Tennis"),
    "испанский": ("Fútbol", "Baloncesto", "Tenis"),
    "испанский без ударения": ("Futbol", "Baloncesto", "Tenis"),
    "португальский": ("Futebol", "Basquetebol", "Ténis"),
    "нидерландский": ("Voetbal", "Basketbal", "Tennis"),
    "датский": ("Fodbold", "Basketball", "Tennis"),
    "норвежский": ("Fotball", "Basketball", "Tennis"),
    "шведский": ("Fotboll", "Basket", "Tennis"),
    "финский": ("Jalkapallo", "Koripallo", "Tennis"),
    "эстонский": ("Jalgpall", "Korvpall", "Tennis"),
    "латышский": ("Futbols", "Basketbols", "Teniss"),
    "литовский": ("Futbolas", "Krepšinis", "Tenisas"),
    "польский": ("Piłka nożna", "Koszykówka", "Tenis"),
    "польский без диакритики": ("Pilka nozna", "Koszykowka", "Tenis"),
    "чешский": ("Fotbal", "Basketbal", "Tenis"),
    "словацкий": ("Futbal", "Basketbal", "Tenis"),
    "словацкий, как на webtv.sk": ("MS 2026 vo futbale", "", ""),
    "венгерский": ("Labdarúgás", "Kosárlabda", "Tenisz"),
    "венгерский, как на port.hu": ("UEFA Labdarúgó Nemzetek Ligája", "", ""),
    "румынский": ("Fotbal", "Baschet", "Tenis"),
    "хорватский и словенский": ("Nogomet", "Košarka", "Tenis"),
    "сербский и боснийский": ("Fudbal", "Košarka", "Tenis"),
    "сербский кириллицей": ("Фудбал", "Кошарка", "Тенис"),
    "болгарский": ("Футбол", "Баскетбол", "Тенис"),
    "русский и казахский": ("Футбол", "Баскетбол", "Теннис"),
    "украинский": ("Футбол", "Баскетбол", "Теніс"),
    "белорусский": ("Футбол", "Баскетбол", "Тэніс"),
    "греческий": ("Ποδόσφαιρο", "Μπάσκετ", "Τένις"),
    "греческий, родительный": ("Ποδοσφαίρου", "Καλαθοσφαίρισης", "Τένις"),
    "турецкий": ("Futbol", "Basketbol", "Tenis"),
    "албанский": ("Futboll", "Basketboll", "Tenis"),
    "иврит": ("כדורגל", "כדורסל", "טניס"),
    # падежи — как их пишут сайты прогона #201
    "хорватский, падежи (sportklub.hr)": ("nogometne reprezentacije",
                                          "košarkaške lige", "teniski turnir"),
    "сербский, падежи (tvarenasport.com)": ("srce nemačkog fudbala",
                                            "Mi živimo za košarku", "tenisa"),
    "русский, родительный": ("Обзор футбола", "О баскетболе", "Тенниса"),
    "турецкий, как на ssport.tv": ("Dünyanın Futbolu", "Basketbolu", ""),
    "румынский, родительный": ("Fotbalului", "Baschetului", "Asii tenisului"),
    "чешский, дательный (oneplay.cz)": ("k fotbalovému utkání", "", ""),
}
не_узнаны = []
for язык, слова in ЯЗЫКИ.items():
    for буква, слово in zip("FBT", слова):
        # заглавными греки пишут без ударений («ΠΟΔΟΣΦΑΙΡΟ») — так и проверяем
        for написание in ((слово, greek_plain(слово).upper(), слово.lower())
                          if слово else ()):
            v = SPORTS.decide(f"{написание}: Alfa - Beta",
                              f"{написание}: Alfa - Beta", ("Alfa", "Beta"))
            if (v.letter, v.rule) != (буква, 5):
                не_узнаны.append(f"{язык}: {написание!r} → {v.letter}")
check(f"футбол, баскетбол, теннис на {len(ЯЗЫКИ)} языках и написаниях",
      not не_узнаны, f"(не узнаны: {не_узнаны})")

# ── написания одной команды сводятся в одну игру ─────────────────────────────
print("Написания одной команды: PSG — одна команда и одна игра")
ПСЖ = ["PSG", "Paris St G", "Paris Saint-Germain", "Paris Saint Germain",
       "PARIS ST GERMAIN", "Paris SG", "Paris St. Germain"]
for написание in ПСЖ:
    check(f"«{написание}» читается как PSG эталона",
          names.same_team(написание, "PSG"),
          f"(чтения: {names.readings(написание)})")
    check(f"«{написание} - Le Mans» эталон узнаёт как футбол",
          ЭТАЛОН.sport_of(написание, "Le Mans",
                          datetime(2026, 10, 10, 21, 40)) == "F")
строки = []
for где, title, league, kind, match, description, when in ПСЖ_ЛЕМАН:
    program = Program(channel_raw=где, title=title,
                      start=datetime.fromisoformat(when).replace(tzinfo=KYIV),
                      description=description, league_raw=league,
                      sport_raw=kind, live_raw="live", match_raw=match)
    row = pipeline.classify(program, MARKERS, SPORTS, {}, {}, ЭТАЛОН)
    строки.append(merge.Entry(source=где, channel=где, home=row.home,
                              away=row.away, start=row.start_kyiv,
                              sport=row.sport, league=row.league, payload=row))
игры = merge.merge(строки)
check(f"восемь сайтов с разными написаниями — одна игра ({len(игры)}) "
      f"со всеми каналами",
      len(игры) == 1 and len(игры[0].channels) == len(ПСЖ_ЛЕМАН),
      f"(игр: {[(g.home, g.away, len(g.entries)) for g in игры]})")
# порядок строк в одну минуту не должен плодить двойников (прогон #201)
def _строка(сайт, хозяева, гости, ч, м):
    return merge.Entry(source=сайт, channel=сайт, home=хозяева, away=гости,
                       start=datetime(2026, 10, 8, ч, м), sport="B")
for порядок in ("cyta первой", "cyta последней"):
    мост = [_строка("tv3.lt", "Maccabi", "Olimpia Milano", 18, 45)]
    пара = [_строка("epg.cyta.com.cy", "Maccabi Tel Aviv", "Armani Milano", 19, 0),
            _строка("tvarenasport.ba", "Maccabi Tel Aviv", "Milano", 19, 0)]
    if порядок == "cyta последней":
        пара.reverse()
    игры = merge.merge(мост + пара)
    check(f"строка-мост сводит две игры в одну ({порядок})",
          len(игры) == 1 and len(игры[0].entries) == 3,
          f"(игр: {[(g.home, g.away, len(g.entries)) for g in игры]})")

# ── без пары и пересмотр очереди ─────────────────────────────────────────────
print("Короткая форма без пары и пересмотр очереди")
check("detect без пары: «Le Mans - Lens» → чужой (как было до правки)",
      SPORTS.detect("Le Mans - Lens") == ("-", "Le Mans"))
check("detect без пары: «Futebol: Benfica x Porto» → F",
      SPORTS.detect("Futebol: Benfica x Porto")[0] == "F")
check("detect с парой: «AFC Wimbledon - Barnet» + Football → F (старое «кроме»)",
      SPORTS.detect("AFC Wimbledon - Barnet Football",
                    ("AFC Wimbledon", "Barnet"))[0] == "F")

import review_queue                                           # noqa: E402

очередь = ("Nice - Le Mans | beIN SPORTS 4 (beinsports.com.tr) "
           "2026-10-06 16:00 | Nice - Le Mans")
check("очередь: «Nice - Le Mans» не закрывается как чужой спорт",
      review_queue.знаем_спорт(очередь, SPORTS, {}, "Nice - Le Mans") == "")
check("очередь: «Dallas Stars - Florida Panthers» — чужой спорт, как раньше",
      review_queue.знаем_спорт(
          "Dallas Stars - Florida Panthers | Nova Sport 2 (oneplay.cz)",
          SPORTS, {}, "Dallas Stars - Florida Panthers") == "-")
check("очередь: «Kiel - Flensburg | Handball» — чужой спорт, как раньше",
      review_queue.знаем_спорт("Kiel - Flensburg | Handball | Sport 1",
                               SPORTS, {}, "Kiel - Flensburg") == "-")

print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, "
      f"красных: {len(failed)}")
sys.exit(1 if failed else 0)

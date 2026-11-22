"""Книга 171 (21.11): запасное чтение страницы с НЕСКОЛЬКИМИ каналами
(`app/fallback_many.py`, М1–М6).

Случай: запасное чтение книги 125 знает канал только у страницы с одним
каналом. Теперь страницу с несколькими каналами сбор читает ещё и общим
способом «в тени»; сошлось со своим разборщиком в обе стороны — страница
запоминается, и когда свой разборщик замолчит, её прочитает общий способ.

Страницы в тесте повторяют устройство настоящих (сбор 20.11): sport5.co.il
(шапка канала картинкой и текстом, время и название в соседних ячейках),
ntvplus.tv (шапка ссылкой, канал вне списка владельца между знакомыми),
ziggosport.nl (служебный ответ: канал — запись, передачи — внутри неё),
allente.no (служебный ответ: имя канала в полях самой передачи).

Запуск: python scripts/test_fallback_many.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import fallback_many, fallback_read, live, pipeline, sport  # noqa: E402
from app.parsers import Program  # noqa: E402
from app.reference import Reference  # noqa: E402

зелёных = красных = 0
ДЕНЬ = date(2026, 11, 20)
ПОЯС = "Asia/Jerusalem"
ЗОНА = ZoneInfo(ПОЯС)
АДРЕС = "https://www.sport5.co.il/Ajax/GetBroadcastSheetData.aspx?date=20%2F11%2F2026"


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def строка(время: str, название: str) -> str:
    return (f'<tr><td class="date"><div> {время} </div><div><img src="/images/img-live.png" alt="ישיר" '
            f'title="ישיר" /></div></td><td><div class="spaceleft"></div></td><td class="text">{название}</td></tr>')


def своя(канал: str, часы: int, минуты: int, название: str, сутки: int = 0) -> Program:
    """Строка, как её отдал бы свой разборщик сайта."""
    start = datetime(ДЕНЬ.year, ДЕНЬ.month, ДЕНЬ.day, часы, минуты, tzinfo=ЗОНА) + timedelta(days=сутки)
    return Program(channel_raw=канал, title=название, start=start)


# sport5.co.il: первый канал подписан картинкой, второй — текстом (книга 170)
СТРАНИЦА = (
    '<table><tr class="tr-header"><th colspan="4"><img src="/Images/channels/SPORT5.svg" alt="ערוץ הספורט" '
    'title="ערוץ הספורט" /><span class="channel_numbers"></span></th></tr>'
    + строка("19:00", "חדשות הספורט: סיכום שבוע") + строка("21:45", "Spain &ndash; England. UEFA Nations League")
    + строка("23:30", "יורוליג: ערב היורוליג") + строка("01:15", "NBA: לייקרס - בוסטון")
    + '<tr class="tr-header"><th colspan="4"><span class="channel-text">ספורט 2</span></th></tr>'
    + строка("16:00", "Sassuolo - Genoa") + строка("21:45", "Ajax - ADO Den Haag") + "</table>")
СВОИ = [своя("ערוץ הספורט", 19, 0, "חדשות הספורט: סיכום שבוע"),
        своя("ערוץ הספורט", 21, 45, "Spain – England. UEFA Nations League"),
        своя("ערוץ הספורט", 23, 30, "יורוליג: ערב היורוליג"),
        своя("ערוץ הספורט", 1, 15, "NBA: לייקרס - בוסטון", сутки=1),
        своя("ספורט 2", 16, 0, "Sassuolo - Genoa"),
        своя("ספורט 2", 21, 45, "Ajax - ADO Den Haag")]
КАНАЛЫ = ["ערוץ הספורט", "ספורט 2"]

print("М3. Общий способ на странице с разметкой")
ряд = fallback_many.rows(СТРАНИЦА, ДЕНЬ, ПОЯС, КАНАЛЫ)
проверка("канал строки — последняя подпись знакомого канала выше неё (картинка и текст)",
         [(к, н.strftime("%d %H:%M")) for к, н, _ in ряд],
         [("ערוץ הספורט", "20 19:00"), ("ערוץ הספורט", "20 21:45"), ("ערוץ הספורט", "20 23:30"),
          ("ערוץ הספורט", "21 01:15"), ("ספורט 2", "20 16:00"), ("ספורט 2", "20 21:45")])
проверка("название — следующий кусок текста после времени", ряд[4][2], "Sassuolo - Genoa")
проверка("у нового канала сутки считаются заново (16:00 после 01:15 — снова день страницы)",
         ряд[4][1].date(), ДЕНЬ)
проверка("подпись «прямой эфир» у времени именем канала не стала", {к for к, _, _ in ряд}, set(КАНАЛЫ))
проверка("без имён каналов, без дня, с кривым поясом — пусто",
         (fallback_many.rows(СТРАНИЦА, ДЕНЬ, ПОЯС, []), fallback_many.rows(СТРАНИЦА, None, ПОЯС, КАНАЛЫ),
          fallback_many.rows(СТРАНИЦА, ДЕНЬ, "Нет/Такого", КАНАЛЫ)), ([], [], []))

print("М1. Сверка в тени — в обе стороны")
проверка("общий способ дал те же строки — расхождений нет", fallback_many.differs(СВОИ, ряд), (0, 0))
проверка("а) строки своего разборщика у общего способа нет — не сошлось",
         fallback_many.differs(СВОИ + [своя("ספורט 2", 22, 30, "Студия")], ряд), (1, 0))
проверка("а) то же время, другой канал — не сошлось",
         fallback_many.differs([своя("ספורט 2", 19, 0, "חדשות הספורט: סיכום שבוע")] + СВОИ[1:], ряд)[0], 1)
# ntvplus.tv: между знакомыми каналами — канал вне списка; его шапку общий способ не узнаёт
NTV = ('<div class="channel-header--title"><a href="/channel/match-premier-hd-1" class="link--inherit">МАТЧ ПРЕМЬЕР HD</a></div>'
       '<div class="tv-schedule--item"><div class="tv-schedule--item-time">06:00</div>'
       '<a href="/tv/review/1" class="tv-schedule--item-title">Футбол. Зенит - Спартак</a></div>'
       '<div class="tv-schedule--item"><div class="tv-schedule--item-time">09:00</div>'
       '<a href="/tv/review/2" class="tv-schedule--item-title">Все на Матч!</a></div>'
       '<div class="tv-schedule--item"><div class="tv-schedule--item-time">23:00</div>'
       '<a href="/tv/review/3" class="tv-schedule--item-title">Хоккей. СКА - ЦСКА</a></div>'
       '<div class="channel-header--title"><a href="/channel/drugoy-9" class="link--inherit">Другой канал</a></div>'
       '<div class="tv-schedule--item"><div class="tv-schedule--item-time">23:30</div>'
       '<a href="/tv/review/4" class="tv-schedule--item-title">Самбо. Чемпионат мира</a></div>'
       '<div class="channel-header--title"><a href="/channel/khl-hd-5" class="link--inherit">KHL HD</a></div>'
       '<div class="tv-schedule--item"><div class="tv-schedule--item-time">07:00</div>'
       '<a href="/tv/review/5" class="tv-schedule--item-title">Хоккей. Авангард - Трактор</a></div>'
       '<div class="tv-schedule--item"><div class="tv-schedule--item-time">23:45</div>'
       '<a href="/tv/review/6" class="tv-schedule--item-title">Хоккей. Локомотив - Динамо</a></div>')
МСК = ZoneInfo("Europe/Moscow")


def мск(канал, ч, м, название):
    return Program(channel_raw=канал, title=название, start=datetime(2026, 11, 20, ч, м, tzinfo=МСК))


СВОИ_NTV = [мск("МАТЧ ПРЕМЬЕР HD", 6, 0, "Футбол. Зенит - Спартак"), мск("МАТЧ ПРЕМЬЕР HD", 9, 0, "Все на Матч!"),
            мск("МАТЧ ПРЕМЬЕР HD", 23, 0, "Хоккей. СКА - ЦСКА"),
            мск("KHL HD", 7, 0, "Хоккей. Авангард - Трактор"), мск("KHL HD", 23, 45, "Хоккей. Локомотив - Динамо")]
ряд_ntv = fallback_many.rows(NTV, ДЕНЬ, "Europe/Moscow", ["МАТЧ ПРЕМЬЕР HD", "KHL HD"])
проверка("б) строка канала вне списка ушла соседу — лишняя внутри окна, не сошлось",
         fallback_many.differs(СВОИ_NTV, ряд_ntv), (0, 1))
хвост = ряд + [("ספורט 2", datetime(2026, 11, 21, 16, 0, tzinfo=ЗОНА), "Завтрашняя передача")]
проверка("б) строка общего способа за окном времени страницы (хвост завтра) — не в счёт",
         fallback_many.differs(СВОИ, хвост), (0, 0))
проверка("название со служебной записью знака — то же название",
         fallback_many.same_title("King\\&#039;s Resort Events (46)", "King's Resort Events (46)"))
проверка("разные названия — разные", fallback_many.same_title("Sassuolo - Genoa", "Ajax - ADO Den Haag"), False)

print("М2. Память страниц")
память, вердикты = {}, {}
ключ = fallback_read.page_key("www.sport5.co.il", АДРЕС)
проверка("сошлось — страница запомнена",
         (fallback_many.shadow(память, вердикты, "www.sport5.co.il", АДРЕС, СТРАНИЦА, ДЕНЬ, ПОЯС, СВОИ),
          {k: v for k, v in память.get(ключ).items() if k != fallback_many.LIVE}),
         (True, {"каналы": sorted(КАНАЛЫ), "окно": [16, 26]}))
проверка("ключ страницы один на все дни (дата «день впереди», «%2F», «месяц/день/год»)",
         [fallback_read.page_key("a.b", u) for u in (
             "https://a.b/x?date=21%2F11%2F2026", "https://a.b/x?date=20.11.2026", "https://a.b/x?date=11/22/2026",
             "https://a.b/x?date=2026-11-23")], ["a.b|https://a.b/x?date=#"] * 4)
завтра = АДРЕС.replace("20%2F11", "21%2F11")
проверка("вторая страница того же ключа не сошлась — ключ убран",
         (fallback_many.shadow(память, вердикты, "www.sport5.co.il", завтра, СТРАНИЦА, ДЕНЬ, ПОЯС,
                               СВОИ + [своя("ספורט 2", 22, 30, "Студия")]), ключ in память), (False, False))
проверка("…и третья, сошедшаяся, в этом сборе его не возвращает",
         (fallback_many.shadow(память, вердикты, "www.sport5.co.il", АДРЕС, СТРАНИЦА, ДЕНЬ, ПОЯС, СВОИ), ключ in память),
         (True, False))
прошлая = {ключ: {"каналы": ["ספורט 5 4K", "ספורט 2"], "окно": [0, 30]}}
fallback_many.shadow(прошлая, {}, "www.sport5.co.il", АДРЕС, СТРАНИЦА, ДЕНЬ, ПОЯС, СВОИ)
проверка("имена каналов копятся из сбора в сбор, окно — по этому сбору",
         {k: v for k, v in прошлая[ключ].items() if k != fallback_many.LIVE},
         {"каналы": sorted(КАНАЛЫ + ["ספורט 5 4K"]), "окно": [16, 26]})
проверка("канал один, строк мало, день неизвестен — сверять нечего",
         [fallback_many.shadow({}, {}, "s", "u", СТРАНИЦА, ДЕНЬ, ПОЯС, СВОИ[:4]),
          fallback_many.shadow({}, {}, "s", "u", СТРАНИЦА, ДЕНЬ, ПОЯС, [СВОИ[0], СВОИ[4]]),
          fallback_many.shadow({}, {}, "s", "u", СТРАНИЦА, None, ПОЯС, СВОИ)], [None, None, None])
память_ntv = {}
проверка("канал вне списка между знакомыми — страница не запоминается",
         (fallback_many.shadow(память_ntv, {}, "ntvplus.tv", "https://ntvplus.tv/tv?date=20.11.2026", NTV, ДЕНЬ,
                               "Europe/Moscow", СВОИ_NTV), память_ntv), (False, {}))
проверка("тот же канал назван в списке владельца (`also`), а свой разборщик его не читает — не сошлось",
         fallback_many.shadow({}, {}, "ntvplus.tv", "u", NTV, ДЕНЬ, "Europe/Moscow", СВОИ_NTV, ["Другой канал"]), False)

print("М4. Служебный ответ без разметки")
ZIGGO = json.dumps([
    {"channel": "Ziggo Sport 1", "screenshot": "https://x/thumb.jpg", "programming": [
        {"channelId": 1, "title": "Nitto ATP Finals: Groepsfase", "dateStart": "2026-11-20T06:00:00+00:00"},
        {"channelId": 1, "title": "Ajax - Feyenoord", "dateStart": "2026-11-20T19:00:00+00:00"}]},
    {"channel": "Ziggo Sport 2", "programming": [
        {"channelId": 2, "title": "Formule 1: Las Vegas", "dateStart": "2026-11-20T23:30:00+00:00"}]}])
ряд_z = fallback_many.rows(ZIGGO, None, "Europe/Amsterdam", ["Ziggo Sport 1", "Ziggo Sport 2"])
проверка("канал — ближайшая сверху запись с именем знакомого канала; время — в поясе сайта",
         [(к, н.strftime("%d %H:%M"), т) for к, н, т in ряд_z],
         [("Ziggo Sport 1", "20 07:00", "Nitto ATP Finals: Groepsfase"), ("Ziggo Sport 1", "20 20:00", "Ajax - Feyenoord"),
          ("Ziggo Sport 2", "21 00:30", "Formule 1: Las Vegas")])
ALLENTE = json.dumps({"events": [
    {"title": "Premier League: Arsenal - Chelsea", "time": "2026-11-20T17:30:00+00:00", "channelName": "V Sport Premier League"},
    {"title": "Megan's the Ride to Win", "time": "2026-11-20T20:00:00+00:00", "channelName": "Horse & Country"}]})
проверка("имя канала в полях самой передачи; передача незнакомого канала остаётся без канала",
         [(к, т) for к, _, т in fallback_many.rows(ALLENTE, None, "Europe/Oslo", ["V Sport Premier League"])],
         [("V Sport Premier League", "Premier League: Arsenal - Chelsea"), ("", "Megan's the Ride to Win")])
проверка("не служебный ответ и не страница — пусто", fallback_many.rows('{"a": ', None, "UTC", ["K"]), [])

print("М5. Свой разборщик замолчал — читаем общим способом по памяти")
запись = {"каналы": КАНАЛЫ, "окно": [16, 26]}
прочитано = fallback_many.read(СТРАНИЦА, ДЕНЬ, ПОЯС, запись, АДРЕС)
проверка("те же шесть строк, каждая со своим каналом",
         [(p.channel_raw, p.raw_time) for p in прочитано],
         [("ערוץ הספורט", "19:00"), ("ערוץ הספורט", "21:45"), ("ערוץ הספורט", "23:30"), ("ערוץ הספורט", "01:15"),
          ("ספורט 2", "16:00"), ("ספורט 2", "21:45")])
проверка("строка — как у книги 125: без пометки эфира, без пары, с пометкой запасного чтения, турнир отрезан",
         (прочитано[1].live_raw, прочитано[1].match_raw, прочитано[1].extra.get(fallback_read.MARK),
          прочитано[1].title, прочитано[1].league_raw, прочитано[1].source_url),
         ("", " ", True, "Spain – England", "UEFA Nations League", АДРЕС))
проверка("строка за окном времени из памяти не берётся",
         [p.raw_time for p in fallback_many.read(СТРАНИЦА, ДЕНЬ, ПОЯС, {"каналы": КАНАЛЫ, "окно": [16, 22]})],
         ["19:00", "21:45", "16:00", "21:45"])
проверка("строка до первой подписи канала не берётся",
         [p.channel_raw for p in fallback_many.read("<table>" + строка("12:00", "Без канала") + "</table>" + СТРАНИЦА,
                                                     ДЕНЬ, ПОЯС, запись)].count(""), 0)
проверка("сетка положена на страницу дважды — строки берутся раз",
         len(fallback_many.read(СТРАНИЦА + СТРАНИЦА, ДЕНЬ, ПОЯС, запись)), 6)
проверка("канал из списка владельца (`also`), которого в памяти нет, тоже знаком",
         {p.channel_raw for p in fallback_many.read(СТРАНИЦА, ДЕНЬ, ПОЯС, {"каналы": ["ספורט 2"], "окно": [16, 26]},
                                                    "", ["ערוץ הספורט"])}, set(КАНАЛЫ))
проверка("служебный ответ читается по памяти так же",
         [(p.channel_raw, p.raw_time) for p in fallback_many.read(
             ZIGGO, ДЕНЬ, "Europe/Amsterdam", {"каналы": ["Ziggo Sport 1", "Ziggo Sport 2"], "окно": [0, 30]})],
         [("Ziggo Sport 1", "07:00"), ("Ziggo Sport 1", "20:00"), ("Ziggo Sport 2", "00:30")])

print("М5. В ленту — только то, что подтвердил эталон (как З4 книги 125)")
MARKERS, SPORTS = live.load(), sport.load(teams=())
ЭТАЛОН = Reference([{"sport": "F", "home": "Spain", "away": "England", "league": "EUROPE: UEFA Nations League",
                     "fs_id": "a1", "start_kyiv": "2026-11-20T21:45"}])
итоги = [pipeline.classify(p, MARKERS, SPORTS, {}, {}, ЭТАЛОН, None) for p in прочитано]
проверка("матч, который эталон знает на это время, — в ленту; остальное со страницы — мимо",
         [(r.home, r.away) for r in итоги if r.ok or r.home], [("Spain", "England")])

print("М6. Страницы в памяти нет — ничего не делаем")
проверка("нет записи памяти — пусто", (fallback_many.read(СТРАНИЦА, ДЕНЬ, ПОЯС, None),
                                         fallback_many.read(СТРАНИЦА, ДЕНЬ, ПОЯС, ["ספורט 2"]),
                                         fallback_many.read(СТРАНИЦА, None, ПОЯС, запись)), ([], [], []))

print("Разбор сбора зовёт тень и чтение")
разбор = (ROOT / "scripts" / "parse_live.py").read_text(encoding="utf-8")
проверка("`parse_live.py`: тень на прочитанной странице, чтение на замолчавшей, память — в итог сбора",
         [x in разбор for x in ("fallback_many.shadow(", "fallback_many.read(", "payload[fallback_many.MANY_KEY]")],
         [True, True, True])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

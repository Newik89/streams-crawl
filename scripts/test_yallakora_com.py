# -*- coding: utf-8 -*-
"""Книга 167 (19.11.2026): yallakora.com — «матчи дня» с каналом показа, второй
источник для ON Sport (слово владельца: «да, делаем»).

Здесь — правила разборщика на разметке сайта (как в пробе GitHub #508).
Настоящая страница проверяется случаем книги (срез `proba-508-yallakora`).

Запуск: python scripts/test_yallakora_com.py — в сеть не ходит.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import crawl, parsers, site_lang  # noqa: E402
from app.parsers import SITE_FLAG, SITE_LIVE, yallakora_com as Y  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def матч(дом: str, гости: str, время: str, канал: str = "", стадия: str = "دور الـ 16") -> str:
    блок = f'<div class="channel icon-channel">{канал}</div>' if канал else ""
    return f"""<div liveScoreMatchId="1" class="item future liItem"><a href="/x"><div class="allData">
 {блок}<div class="topData"><div class="date">{стадия} </div><div class="matchStatus"><span>لم تبدأ</span></div></div>
 <div class="teamCntnr"><div class="teamsData">
  <div class="teams teamA"><img alt="{дом}" /><p>{дом}</p></div>
  <div class="MResult"><span class="score">-</span><span>-</span><span class="score">-</span><span class="time">{время}</span></div>
  <div class="teams teamB"><img alt="{гости}" /><p>{гости}</p></div>
 </div></div></div></a></div>"""


def турнир(имя: str, английское: str, матчи: str) -> str:
    return f"""<div class="3066 matchCard matchesList"><div class="title"><a class="tourTitle" href="/tour/1">
 <div class="imgCntnr"><img alt="{имя}" enName="{английское}" /></div><h2> {имя} </h2></a></div>
 <div class="ul">{матчи}</div></div>"""


def страница(вкладка: str = "11/19/2026") -> str:
    дни = f'<button class="dayTabLinks" date="11/18/2026"></button><button class="dayTabLinks active" date="{вкладка}"></button>' \
        if вкладка else ""
    return "<html><body>" + дни + турнир(
        "كأس مصر", "Egypt-Cup",
        матч("المصري", "بترول أسيوط", "17:00", "ON Sport")
        + матч("المقاولون العرب", "القناة", "17:00", "ON Sport MAX")
        + матч("زد", "سموحة", "20:00", "ON Sport MAX")
        + матч("زد", "سموحة", "20:00", "ON Sport MAX")            # та же строка дважды
        + матч("الأهلي", "بيراميدز", "21:00")                       # без канала
    ) + турнир(
        "كرة يد - السوبر المصري", "Egyptian Handball Super Cup",
        матч("الأهلي", "الزمالك", "18:30", "ON Sport PLUS", "المباراة النهائية")
    ) + турнир(
        "كأس العالم تحت 17 عاما", "كأس العالم تحت 17 عاما",
        матч("فرنسا", "هايتي", "15:00", "الكأس 1", "الجولة الأولى")
    ) + "</body></html>"


URL = "https://www.yallakora.com/match-center?date=11/19/2026"
ON = {"ON Sport", "ON Sport Max", "ON Sport Plus"}

print("Строки страницы")
все = Y.parse(страница(), url=URL)
проверка("матч без канала — не строка; одинаковая строка берётся один раз; чужой канал разбор не выбрасывает",
         [(p.channel_raw, p.raw_time, p.match_raw) for p in все],
         [("ON Sport", "17:00", "المصري - بترول أسيوط"), ("ON Sport Max", "17:00", "المقاولون العرب - القناة"),
          ("ON Sport Max", "20:00", "زد - سموحة"), ("ON Sport Plus", "18:30", "الأهلي - الزمالك"),
          ("الكأس 1", "15:00", "فرنسا - هايتي")])
свои = Y.parse(страница(), url=URL, channels=ON)
проверка("какие каналы брать, решает список каналов сайта в плане",
         [p.channel_raw for p in свои], ["ON Sport", "ON Sport Max", "ON Sport Max", "ON Sport Plus"])
проверка("имя канала выравнивается по списку: «ON Sport MAX» → «ON Sport Max», «on sport plus» → «ON Sport Plus»",
         (Y.channel_name("ON Sport MAX"), Y.channel_name("on  sport plus"), Y.channel_name("الكأس 1")),
         ("ON Sport Max", "ON Sport Plus", "الكأس 1"))
p = свои[0]
проверка("время каирское, день — из активной вкладки", p.start.isoformat(), "2026-11-19T17:00:00+02:00")
проверка("футбол: лига — английское имя турнира, дефисы пробелами; стадия — в описании",
         (p.league_raw, p.sport_raw, p.description), ("Egypt Cup", "Soccer", "دور الـ 16"))
проверка("все строки — эфир по слову сайта", [(q.live_raw, q.extra.get(SITE_FLAG)) for q in свои],
         [("live", SITE_LIVE)] * 4)
p = свои[3]
проверка("приставка турнира «كرة يد -» — гандбол; лига — английское имя",
         (p.sport_raw, p.league_raw), ("Handball", "Egyptian Handball Super Cup"))
проверка("английского имени у турнира нет (в enName арабское) — лига арабская",
         все[4].league_raw, "كأس العالم تحت 17 عاما")

print("Вид спорта и лига по имени турнира")
проверка("«كرة اليد - دوري المحترفين» (с артиклем), английского имени нет — гандбол, лига без приставки",
         Y.sport_and_league("كرة اليد - دوري المحترفين", ""), ("Handball", "دوري المحترفين"))
проверка("«كرة السلة - أفريقيا» — баскетбол", Y.sport_and_league("كرة السلة - أفريقيا", "")[0], "Basketball")
проверка("«الكرة الطائرة - الدوري» — волейбол", Y.sport_and_league("الكرة الطائرة - الدوري", "")[0], "Volleyball")
проверка("тире без приставки вида спорта («دوري القسم الثاني-أ») — футбол, имя целиком",
         Y.sport_and_league("دوري القسم الثاني-أ", "Egyptian Second Division"), ("Soccer", "Egyptian Second Division"))
проверка("незнакомая приставка перед тире — футбол, арабское имя целиком",
         Y.sport_and_league("كأس السوبر - النهائي", ""), ("Soccer", "كأس السوبر - النهائي"))

print("День страницы")
проверка("вкладки дня нет — день из адреса", Y.parse(страница(""), url=URL)[0].start.strftime("%d.%m"), "19.11")
проверка("ни вкладки, ни даты в адресе — день из запроса",
         Y.parse(страница(""), url="https://www.yallakora.com/match-center", day=date(2026, 11, 21))[0]
         .start.strftime("%d.%m"), "21.11")
проверка("вкладка главнее адреса (сайт перенаправил на другой день)",
         Y.parse(страница("11/20/2026"), url=URL)[0].start.strftime("%d.%m"), "20.11")
проверка("пустая страница — пусто, без падения", Y.parse("<html></html>", url=URL), [])

print("Сайт прописан в обходе")
проверка("дневная сетка: адрес на день, каналы все разом", "yallakora.com" in crawl.DAY_GRID_DOMAINS)
проверка("язык сайта — арабский", site_lang.SITE_LANGS.get("yallakora.com"), ("ar",))
проверка("разборщик подключён к общему списку (иначе разбор скажет «своего парсера нет»)",
         parsers.get("yallakora.com") is Y.parse)
проверка("и по адресу с www", parsers.get("www.yallakora.com") is Y.parse)

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

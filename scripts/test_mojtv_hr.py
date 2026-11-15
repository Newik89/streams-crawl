"""Книга 127 (15.11): mojtv.hr переделали за ночь — новый адрес и новая разметка.

Нашёл ход «сайт переехал» (книга 126) в первый же день работы: все страницы
`/tv-program/-2/sportski/<дата>.aspx` ответили «такой страницы нет».
Новый адрес — `/tv-program/sportski/<дата>`, разметка — сетка `grid-row` /
`grid-card`. Разборщик понимает обе разметки.

Запуск: python scripts/test_mojtv_hr.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.parsers import mojtv_hr  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def карточка(время: str, заголовок: str, описание: str = "") -> str:
    return (f'<div class="grid-card" data-time="{время}"><div class="card-meta-header">'
            f'<span class="grid-card-time">{время}</span><div></div></div>'
            f'<span class="grid-card-title">{заголовок}</span>'
            f'<span class="grid-card-desc">{описание}</span></div>')


def страница(title: str = "Tv program - Sportski - ponedjeljak, 16.11.2026. | MojTV") -> str:
    return f"""<html><head><title>{title}</title></head><body>
<div class="sticky-channels-column">
 <a class="channel-logo-slot" id="channel-logo-722"><img alt="MaxSport1 tv program"></a>
 <a class="channel-logo-slot" id="channel-logo-179"><img alt="Arena Sport 1 tv program"></a>
 <a class="channel-logo-slot" id="channel-logo-62"><img alt="SK1 tv program"></a>
</div>
<div class="grid-row" data-channel-target="channel-logo-722">
 {карточка("08:00", "Odbojka: Odbojka: Dubrovnik &#x2013; Dinamo, SuperSport Superliga za seniorke 2026./2027.")}
 {карточка("20:00", "Sport: MAXSport kviz powered by PSK (U&#x17D;IVO)")}
</div>
<div class="grid-row" data-channel-target="channel-logo-179">
 {карточка("12:00", "Nogomet: Arena - Kanal")}
</div>
<div class="grid-row" data-channel-target="channel-logo-62">
 {карточка("08:10", "Nogomet - Liga nacija: France - Turkiye", "snimka")}
 {карточка("20:45", "Nogomet - Liga nacija: Germany - Netherlands (U&#x17D;IVO)")}
 {карточка("23:30", "NBA: Boston - Orlando (U&#x17D;IVO)", "NBA 2026./2027.")}
 {карточка("01:00", "JutroSK")}
 {карточка("", "Bez vremena")}
</div></body></html>"""


print("Новая разметка (с 15.11.2026)")
строки = mojtv_hr.parse(страница(), url="https://mojtv.hr/tv-program/sportski/2026-11-16")
проверка("каналы — только из списка, с каноничными именами; чужой ряд (Arena) и карточка без времени — мимо",
         [(p.channel_raw, p.raw_time) for p in строки],
         [("MAXSport 1", "08:00"), ("MAXSport 1", "20:00"), ("Sport Klub 1", "08:10"),
          ("Sport Klub 1", "20:45"), ("Sport Klub 1", "23:30"), ("Sport Klub 1", "01:00")])
сеть = {p.raw_time + p.channel_raw[-1]: p for p in строки}
p = сеть["20:451"]
проверка("прямой эфир: пара, лига из рубрики, вид спорта, пометка «(UŽIVO)» снята с заголовка",
         (p.match_raw, p.league_raw, p.sport_raw, p.live_raw, p.title),
         ("Germany - Netherlands", "Liga nacija", "Nogomet", "uživo",
          "Nogomet - Liga nacija: Germany - Netherlands"))
p = сеть["08:001"]
проверка("двойная рубрика и длинное тире: пара после последнего двоеточия, турнир — хвост после запятой",
         (p.match_raw, p.league_raw, p.live_raw),
         ("Dubrovnik - Dinamo", "SuperSport Superliga za seniorke 2026./2027.", ""))
p = сеть["08:101"]
проверка("повтор без пометки эфира — не эфир", (p.match_raw, p.live_raw), ("France - Turkiye", ""))
p = сеть["23:301"]
проверка("рубрика без тире: лига — из описания карточки",
         (p.match_raw, p.league_raw, p.sport_raw), ("Boston - Orlando", "NBA 2026./2027.", "NBA"))
проверка("передача без пары — пары нет", сеть["20:001"].match_raw, " ")
проверка("день — из заголовка страницы; ночь после полуночи — следующая дата",
         [p.start.strftime("%d.%m %H:%M") for p in строки if p.channel_raw == "Sport Klub 1"],
         ["16.11 08:10", "16.11 20:45", "16.11 23:30", "17.11 01:00"])
сегодня = mojtv_hr.parse(страница("Tv program - Sportski - Danas | MojTV"),
                         url="https://mojtv.hr/tv-program/sportski/2026-11-15")
проверка("в заголовке нет даты («Danas») — день из адреса", сегодня[0].start.strftime("%d.%m"), "15.11")
сегодня = mojtv_hr.parse(страница("Tv program - Sportski - Danas | MojTV"), day=date(2026, 11, 20),
                         url="https://mojtv.hr/tv-program/sportski")
проверка("нет даты ни в заголовке, ни в адресе — день из запроса", сегодня[0].start.strftime("%d.%m"), "20.11")

print("Прежняя разметка читается как раньше")
СТАРАЯ = """<html><body><script>init('16.11.2026. 6:00:00')</script>
<h2 class="hide">SK1</h2><div class="programsingle"><div class="pt"><div class="pi">
<a href="#"><em>20:55</em><strong>Nogomet: Varaždin - Rudeš (UŽIVO)</strong><br>SuperSport HNL 2026./2027.</a>
</div></div></div></body></html>"""
старые = mojtv_hr.parse(СТАРАЯ, url="https://mojtv.hr/tv-program/-2/sportski/2026-11-16.aspx")
проверка("старая страница: канал, пара, эфир, лига — без изменений",
         [(p.channel_raw, p.match_raw, p.live_raw, p.league_raw, p.start.strftime("%d.%m %H:%M")) for p in старые],
         [("Sport Klub 1", "Varaždin - Rudeš", "uživo", "SuperSport HNL 2026./2027.", "16.11 20:55")])
проверка("пустая страница — пусто, без падения", mojtv_hr.parse("<html></html>"), [])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

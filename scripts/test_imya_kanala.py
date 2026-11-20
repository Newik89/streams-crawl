"""Книга 170 (20.11.2026): имя канала — из любого места ячейки, у всех разборщиков класса.

Случай: mojtv.hr 19.11 перенёс имя канала из подписи картинки в текст — и
разборщик, знавший одно место, замолчал (книга 168). Замер класса нашёл ещё
восемь разборщиков, берущих имя из одного места: ert.gr, movistarplus.es,
nova.bg, oneplaysport.cz, sport5.co.il, sports.kz, tv.dir.bg, vsetv.com.
Теперь все они спрашивают имя у общего читателя (`app/parsers/label.py`,
`pick`).

Что проверяем по каждому сайту (ячейки канала — настоящие, со страниц сбора
18.11.2026; расписание сокращено до одной строки):
  1. страница как сегодня — имя канала то же, что и до правки;
  2. сайт перенёс имя в другое место ячейки (убрал подпись, оставил текст;
     убрал картинку; оставил только подсказку) — строки по-прежнему читаются
     и канал тот же;
  3. живые находки замера: movistarplus.es пишет «M+ Liga de Campeones  3» с
     двумя пробелами — прежний код терял канал целиком; sport5.co.il
     подписывает чужие каналы текстом без логотипа — они ждут слова владельца.
  4. детектор класса: ни один разборщик не кладёт в имя канала подпись
     картинки или ячейки напрямую, мимо общего читателя.

Запуск: python scripts/test_imya_kanala.py
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.parsers import (ert_gr, movistarplus_es, nova_bg, oneplaysport_cz,  # noqa: E402
                         sport5_co_il, sports_kz, tv_dir_bg, vsetv_com)

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def каналы(programs) -> list[str]:
    return sorted({p.channel_raw for p in programs})


ДЕНЬ = date(2026, 11, 18)

# ── ert.gr ───────────────────────────────────────────────────────────────────
print("ert.gr — имя в `title` ссылки-шапки колонки")
ERT_СПИСОК = {"ΕΡΤ2 ΣΠΟΡ", "ΕΡΤ1", "ΕΡΤ Sports 1"}


def ert(шапка: str) -> str:
    return ('<div class="slide-items"><div class="column">' + шапка +
            '<div class="broadcast bg-base-2 column" data-start-time="2026-11-18 21:00:00+0200">'
            '<span>21:00</span><strong> Ποδόσφαιρο | Ολυμπιακός - ΠΑΟΚ </strong></div></div></div>')


def ert_каналы(шапка: str) -> list[str]:
    return каналы(ert_gr.parse(ert(шапка), day=ДЕНЬ, tz="Europe/Athens", url="https://www.ert.gr/tv/program/",
                               channels=ERT_СПИСОК))


проверка("как сегодня",
         ert_каналы('<a class="row" href="/tv/program/ert2/?dt=2026-11-18" title="ΕΡΤ2 ΣΠΟΡ">'
                    '<img src="ert2-spor-logo-hor.svg" alt="ΕΡΤ2 ΣΠΟΡ" height="24"></a>'), ["ΕΡΤ2 ΣΠΟΡ"])
проверка("сайт убрал `title` у ссылки — имя из подписи картинки",
         ert_каналы('<a class="row" href="/tv/program/ert2/?dt=2026-11-18"><img src="x.svg" alt="ΕΡΤ2 ΣΠΟΡ"></a>'),
         ["ΕΡΤ2 ΣΠΟΡ"])
проверка("сайт убрал картинку и подписи — имя текстом",
         ert_каналы('<a class="row" href="/tv/program/ert2/?dt=2026-11-18"> ΕΡΤ2 ΣΠΟΡ </a>'), ["ΕΡΤ2 ΣΠΟΡ"])
проверка("канал не из списка владельца по-прежнему не читается",
         ert_каналы('<a class="row" href="/tv/program/ertnews/" title="ΕΡΤ NEWS"><img alt="ΕΡΤ NEWS"></a>'), [])

# ── movistarplus.es ──────────────────────────────────────────────────────────
print("movistarplus.es — имя текстом ссылки «Ver canal …»")
MOVI_СПИСОК = {"M+ Liga de Campeones 3", "DAZN LaLiga", "M+ Deportes 2"}
MOVI_URL = "https://www.movistarplus.es/programacion-tv/MLC3/2026-11-18"


def movi(шапка: str) -> list[str]:
    страница = ('<div class="main-guide">' + шапка + '<div class="container_box"><ul><li class="time">21:00</li>'
                '<li class="title">Liga de Campeones (T26/27): Real Madrid - Arsenal</li>'
                '<li class="genre">Fútbol</li></ul></div></div>')
    return каналы(movistarplus_es.parse(страница, day=ДЕНЬ, tz="Europe/Madrid", url=MOVI_URL, channels=MOVI_СПИСОК))


проверка("как сегодня",
         movi('<div class="info-canal"><div class="titulo"><a href="https://www.movistarplus.es/canal/m-plus-deportes-2?id=arthur">'
              ' Ver canal  M+ Deportes 2 </a></div></div>'), ["M+ Deportes 2"])
проверка("живая находка: два пробела внутри имени («M+ Liga de Campeones  3») — канал больше не теряется",
         movi('<div class="info-canal"><div class="titulo"><a href="https://www.movistarplus.es/canal/m-plus-liga-de-campeones-3?id=chap2">'
              ' Ver canal  M+ Liga de Campeones  3 </a></div></div>'), ["M+ Liga de Campeones 3"])
проверка("регистр букв остаётся как на сайте (под ним канал знает база)",
         movi('<div class="info-canal"><div class="titulo"><a href="/canal/dazn-laliga"> Ver canal  DAZN LALIGA </a></div></div>'),
         ["DAZN LALIGA"])
проверка("сайт убрал ссылку, имя — подписью картинки в том же блоке",
         movi('<div class="info-canal"><div class="titulo"><img src="mlc3.png" alt="M+ Liga de Campeones 3"></div></div>'),
         ["M+ Liga de Campeones 3"])
проверка("чужой канал по-прежнему не читается",
         movi('<div class="info-canal"><div class="titulo"><a href="/canal/la1"> Ver canal  LA 1 </a></div></div>'), [])
проверка("полоса логотипов: имя из `title`, а без него — из `alt`",
         movistarplus_es.list_channels('<div class="canalnumber"><img src="TVE.png" title="LA 1"></div>'
                                       '<div class="canalnumber"><img src="LA2.png" alt="LA 2"></div>'), ["LA 1", "LA 2"])

# ── nova.bg ──────────────────────────────────────────────────────────────────
print("nova.bg — имя в `alt` логотипа переключателя каналов")
NOVA_СПИСОК = {"nova sport", "diemasport"}


def nova(ячейка: str) -> list[str]:
    страница = ('<html><head><link rel="canonical" href="https://nova.bg/schedule/index/5/2026/11/18/"></head><body>'
                '<a class="gtm-TVProgramaDays-click" href="https://nova.bg/schedule/index/5/2026/11/19/">Четвъртък 19 ноември</a>'
                + ячейка +
                '<ul><li id="production1"><div class="timeline-hour">21:45</div><div class="timeline-show">'
                '<h2>Арсенал - Челси</h2><span>12 кръг, Футбол: Премиър лийг 2026/2027, директно</span></div></li></ul>'
                '</body></html>')
    return каналы(nova_bg.parse(страница, day=ДЕНЬ, tz="Europe/Sofia", url="https://nova.bg/schedule/index/5/2026/11/18/",
                                channels=NOVA_СПИСОК))


проверка("как сегодня",
         nova('<a class="gtm-TVProgramaChannels-click" href="https://nova.bg/schedule/index/5/2026/11/18/">'
              '<img src="novasport_re.svg" class="img-responsive" alt="nova sport"></a>'), ["nova sport"])
проверка("сайт убрал `alt`, оставил подсказку картинки",
         nova('<a class="gtm-TVProgramaChannels-click" href="https://nova.bg/schedule/index/5/2026/11/18/">'
              '<img src="novasport_re.svg" title="nova sport"></a>'), ["nova sport"])
проверка("сайт убрал картинку — имя текстом в ячейке переключателя",
         nova('<a class="gtm-TVProgramaChannels-click" href="https://nova.bg/schedule/index/5/2026/11/18/"> Nova Sport </a>'),
         ["nova sport"])
проверка("ссылка дня («Четвъртък 19 ноември») именем канала не становится; имени нет — «канал 5», как раньше",
         nova(""), ["канал 5"])

# ── oneplaysport.cz ──────────────────────────────────────────────────────────
print("oneplaysport.cz — имя в `alt` логотипа шапки блока")
ONE_СПИСОК = {"Oneplay Sport 1", "Oneplay Sport 2"}


def oneplay(шапка: str) -> list[str]:
    страница = ('<div class="channel">' + шапка + '<div class="channel-content">'
                '<a href="https://www.oneplay.cz/program?channelId=033" data-start="20:30" data-end="23:30" class="program-item">'
                '<span class="date">20:30 - 23:30</span><span class="name">CHL: FC Viktoria Plzeň-AC Sparta Praha</span></a>'
                '</div></div>')
    return каналы(oneplaysport_cz.parse(страница, day=ДЕНЬ, tz="Europe/Prague",
                                        url="https://oneplaysport.cz/program?date=2026-11-18", channels=ONE_СПИСОК))


проверка("как сегодня",
         oneplay('<div class="mobile-channel"><img src="/assets/front/img/channels/ops_1.png" alt="Oneplay Sport 1"></div>'),
         ["Oneplay Sport 1"])
проверка("сайт убрал `alt`, оставил подсказку", oneplay('<div class="mobile-channel"><img src="ops_1.png" title="Oneplay Sport 1"></div>'),
         ["Oneplay Sport 1"])
проверка("сайт убрал картинку — имя текстом (как сделал mojtv.hr 19.11)",
         oneplay('<div class="mobile-channel"> Oneplay Sport 1 </div>'), ["Oneplay Sport 1"])
проверка("шапки нет совсем — блок пропущен, без падения", oneplay(""), [])

# ── sport5.co.il ─────────────────────────────────────────────────────────────
print("sport5.co.il — имя в `alt` логотипа строки-шапки")


def sport5(шапка: str) -> list[str]:
    страница = ('<table><tr class="tr-header"><th colspan="4">' + шапка + '<span class="channel_numbers"></span></th></tr>'
                '<tr><td class="date"><div>21:30</div></td><td class="text">בונדסליגה: באיירן מינכן - קלן, מחזור 10</td></tr></table>')
    return каналы(sport5_co_il.parse(страница, day=ДЕНЬ, tz="Asia/Jerusalem",
                                     url="https://www.sport5.co.il/Ajax/GetBroadcastSheetData.aspx?date=18%2F11%2F2026"))


проверка("как сегодня",
         sport5('<img src="/Images/channels/5PLUS_CHANNEL_white.svg" alt="ספורט 5+" title="ספורט 5+">'), ["ספורט 5+"])
проверка("сайт убрал `alt`, оставил подсказку", sport5('<img src="5PLUS_CHANNEL_white.svg" title="ספורט 5+">'), ["ספורט 5+"])
проверка("у логотипа подписей нет, имя текстом рядом", sport5('<img src="5PLUS_CHANNEL_white.svg"><span>ספורט 5+</span>'),
         ["ספורט 5+"])
проверка("живая находка: шапка без логотипа (чужой канал «ספורט 1» текстом) пока не читается — ждёт слова владельца",
         sport5('<span class="channel-text">ספורט 1</span>'), [])

# ── sports.kz ────────────────────────────────────────────────────────────────
print("sports.kz — имя в `title` ссылки первого пункта списка")
KZ_СПИСОК = {"Телеканал «Qazsport»"}


def kz(пункт: str) -> list[str]:
    страница = ('<div class="tv_day_"><h3>ср <span>18 ноября</span></h3><ul class="tv_telekanal-1">' + пункт +
                '<li><span>19:55</span><p>Футбол. УЕФА Еуропа Лигасы. «Қайрат» (Қазақстан) — «Андерлехт» (Бельгия). '
                'Прямая трансляция</p></li></ul></div>')
    return каналы(sports_kz.parse(страница, day=ДЕНЬ, tz="Asia/Almaty", url="https://www.sports.kz/tv", channels=KZ_СПИСОК))


проверка("как сегодня",
         kz('<li><i class="lazy"></i><a href="/tv/telekanal-kazsport" title="Телеканал «Qazsport»">Телеканал «Qazsport»</a></li>'),
         ["Телеканал «Qazsport»"])
проверка("сайт убрал `title` у ссылки — имя текстом",
         kz('<li><i class="lazy"></i><a href="/tv/telekanal-kazsport">Телеканал «Qazsport»</a></li>'), ["Телеканал «Qazsport»"])
проверка("имя осталось только подписью картинки",
         kz('<li><a href="/tv/telekanal-kazsport"><img src="q.jpg" alt="Телеканал «Qazsport»"></a></li>'),
         ["Телеканал «Qazsport»"])

# ── vsetv.com ────────────────────────────────────────────────────────────────
print("vsetv.com — имя в `alt` логотипа шапки страницы")
VSE_СПИСОК = {"Суспільне Спорт", "2+2"}


def vsetv(шапка: str) -> list[str]:
    страница = ('<table><tr><td class="main">' + шапка +
                '<div class="time">19:00</div><div class="prname2">Футбол. Чемпионат Украины. Шахтер - Динамо.</div>'
                '<div class="time">21:00</div><div class="prname2">Новости.</div></td></tr></table>')
    return каналы(vsetv_com.parse(страница, day=ДЕНЬ, tz="Europe/Kyiv",
                                  url="https://www.vsetv.com/schedule_channel_1952_day_2026-11-18.html", channels=VSE_СПИСОК))


ЛОГО = '<div class="chlogo"><img src="/pic/channel_logos/1952.gif" alt="Суспільне Спорт" width="75" height="55" class="pic"></div>'
ПОДПИСЬ = '<div class="chname"><table><tr><td nowrap class="channeltitle">Суспільне Спорт</td></tr></table></div>'
проверка("как сегодня", vsetv(ЛОГО + ПОДПИСЬ), ["Суспільне Спорт"])
проверка("сайт убрал `alt` у логотипа — имя из подписи рядом",
         vsetv('<div class="chlogo"><img src="/pic/channel_logos/1952.gif" class="pic"></div>' + ПОДПИСЬ), ["Суспільне Спорт"])
проверка("сайт убрал логотип совсем — имя из подписи рядом", vsetv(ПОДПИСЬ), ["Суспільне Спорт"])
проверка("имени нет нигде — «vsetv 1952», как раньше (не из списка — страница пропущена)", vsetv(""), [])

# ── tv.dir.bg (страница списка каналов; расписание идёт по номеру канала) ─────
print("tv.dir.bg — список каналов: имя в `alt` логотипа")
проверка("как сегодня, без `alt` (подсказка) и без картинки (текст)",
         tv_dir_bg.list_channels(
             '<div class="channel_cont"><a class="channel_link" href="/programa/95"><img src="a.png" alt="bTV"></a></div>'
             '<div class="channel_cont"><a class="channel_link" href="/programa/12"><img src="b.png" title="BNT1 (БНТ1)"></a></div>'
             '<div class="channel_cont"><a class="channel_link" href="/programa/13"> BNT2 (БНТ2) </a></div>'),
         {"95": "bTV", "12": "BNT1 (БНТ1)", "13": "BNT2 (БНТ2)"})

# ── детектор класса ──────────────────────────────────────────────────────────
print("Детектор: имя канала из подписи картинки или ячейки — только через общий читатель")
#: строка «channel… = …attributes…("alt"|"title"|"aria-label")…» без `label.` —
#: разборщик снова берёт имя из одного места
ОДНО_МЕСТО = re.compile(r"^\s*channel\w*\s*=.*attributes(?:\.get\(|\[)\"(?:alt|title|aria-label)\"")
#: разборщики, где такая строка разобрана и оставлена: (файл, почему)
РАЗОБРАНО = {
    "cosmotetv_gr.py": "старая разметка сайта (сбор идёт служебным ответом); берёт `alt`, а без него текст ячейки",
}
нарушители = []
for path in sorted((ROOT / "app" / "parsers").glob("*.py")):
    if path.name in РАЗОБРАНО or path.name == "label.py":
        continue
    lines = path.read_text(encoding="utf-8").splitlines()
    for n, line in enumerate(lines):
        if ОДНО_МЕСТО.search(line) and "label." not in line and "label." not in "".join(lines[n + 1:n + 3]):
            нарушители.append(f"{path.name}:{n + 1}")
проверка("таких разборщиков нет", нарушители, [])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

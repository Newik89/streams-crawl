# -*- coding: utf-8 -*-
r"""Сколько запросов уйдёт на обход — до того, как куда-то идти.

К сайтам не обращается: только считает адреса по базе. Нужен, чтобы
владелец видел нагрузку заранее и выбирал окно (ТЗ разд. 2 — 2 суток или
5 дней), а не узнавал цену обхода после бана по IP.

Запуск:
    venv\Scripts\python.exe scripts/crawl_plan.py
    venv\Scripts\python.exe scripts/crawl_plan.py --days 5 --show
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datetime import date  # noqa: E402

from app import crawl, db   # noqa: E402

PILOTS = ["nova.bg", "tv.nova.cz", "teleman.pl", "sporttv.pt", "tvarenasport.com",
          "tvarenasport.ba", "tvarenasport.hr", "tvarenasport.si",
          "trtspor.com.tr", "allente.no", "programetv.ro", "skysports.com",
          "ceskatelevize.cz", "maxsport.live", "bnt.bg", "srf.ch", "poverkhnost.tv", "mojtv.hr", "tring.al", "football-tv.ru",
          # шесть сайтов по ссылкам владельца, разобраны 31.08: чешский
          # OnePlay даёт Nova Sport 1-6 в обход Cloudflare, НТВ-ПЛЮС — весь
          # пакет МАТЧ!, `rtcg.me` берётся только браузером
          "oneplaysport.cz", "ntvplus.tv", "ert.gr", "rtcg.me", "rtrs.tv",
          "sport1.maariv.co.il",
          # пачка 01.09: румынский Digi Sport (4 канала, неделя на странице)
          # и турецкий TRT (16 каналов одним запросом)
          "digisport.ro", "trt.net.tr",
          # третья пачка 01.09: венгерский M4 Sport (закрыл дыру из
          # ОТЛОЖЕНО), казахский Qazsport и румынский Prima Sport
          "mediaklikk.hu", "sports.kz", "primaplay.ro",
          # четвёртая пачка 01.09: словацкий Aktuality (11 спортканалов
          # одной страницей), кипрский Cyta (неделя трансляций одним
          # ответом), испанский Movistar+ (41 канал), австрийский ORF,
          # португальский RTP и украинский УНІАН
          "tv-program.aktuality.sk", "epg.cyta.com.cy", "movistarplus.es",
          "tv.orf.at", "rtp.pt", "unian.tv",
          # пятая пачка 01.09: турецкий S Sport (2 канала, неделя одним
          # запросом), французский programme-tv.net (29 эфирных каналов)
          # и турецкий A Spor
          "ssport.tv", "programme-tv.net", "aspor.com.tr",
          # шестая пачка 01.09: немецкий RTL и британский BBC
          "rtl.de", "bbc.co.uk",
          # седьмая пачка 01.09: турецкий beIN SPORTS (Süper Lig и еврокубки),
          # хорватский HRT через старый текстовый вывод и TV8
          "beinsports.com.tr", "raspored.hrt.hr", "tv8.com.tr",
          # девятая проба 01.09: болгарский пакет Diema — неделя на канал
          "diemaxtra.nova.bg",
          # 16.09: Sport Klub (SK 1–12 и др.) — ручка United Cloud с гостевым
          # ключом (app/fetch.py TOKEN_HOSTS), канал на запрос, окно неделя
          "sportklub.hr",
          # десятая проба 01.09: немецкий SPORT1 через api.sport1.info и
          # нидерландский Ziggo Sport через дневной файл кэша
          "tv.sport1.de", "ziggosport.nl",
          # RaiPlay вернулся в обход 01.09: эфир определяем первым показом
          # пары, как у ert.gr — до этого источник стоял без признака эфира
          "raiplay.it",
          # первая пачка 02.09 из раздела «сетку рисует скрипт»: норвежский
          # TV 2 (69 каналов одним запросом), ирландский RTE (17 файлов по
          # каналу, десять суток в каждом) и турецкий atv
          "tv2.no", "rte.ie", "atv.com.tr",
          # индивидуальный разбор 01.09: израильский Sport5 (параметр
          # `date=ДД/ММ/ГГГГ` у ajax-ручки) и русскоязычный vsetv, где
          # цифры времени спрятаны картинками и вычисляются по сетке.
          # Каналы vsetv выбрал владелец: 2+2 и Суспільне Спорт
          "sport5.co.il", "vsetv.com",
          # dagenstv.com — витрина, данные лежат на kolla.tv (адрес нашёлся
          # в его же бандле). 16 шведских каналов одним запросом на день
          "dagenstv.com",
          # разобрано 01.09 по подсказкам владельца: у `npo.nl` дата в ручке
          # в виде ДД-ММ-ГГГГ (из-за формата и был 403), у `rts.rs` сетку
          # отдаёт адрес БЕЗ `www`
          "npo.nl", "rts.rs",
          # греческие: COSMOTE Sport 1-9 (закрыт для серверов, берётся через
          # читалку — `app/fetch.py` → VIA_READER) и ΣΚΑΪ по ссылке владельца
          "cosmotetv.gr", "skai.gr",
          # словацкий Kanal 1 Sport (бывший arenatv.sk): сетку отдаёт только
          # браузером с ожиданием догрузки, зато обоими каналами разом
          "kanal1sport.sk",
          # Canal 11 (Португалия): данные не на сайте, а на платформе
          # Pixellot — адрес взят из соседнего проекта (reference/canal11.py)
          "canal11.pt",
          # венгерский port.hu: закрыл дыру со Spíler1/Spíler2 и Match4;
          # адрес ручки подсмотрен в открытом проекте iptv-org/epg
          "port.hu",
          # словацкий webtv.sk: закрыл JOJ Šport и JOJ Šport 2, которые не
          # дались на самом joj.sk; адрес тоже из iptv-org/epg
          "webtv.sk",
          # вторая пачка 02.09: Sport1 CZ/SK (три канала одной страницей,
          # только браузером) и TRT Avaz (один канал, адрес на день)
          "sport1tv.cz", "trtavaz.com.tr",
          # третья пачка 02.09: австралийский tvguidetonight — адреса каналов
          # сменились на слаги с городом, взяты 10 Bold, 7mate и 9Gem
          "tvguidetonight.com.au",
          # четвёртая пачка 02.09: венгерский sport1tv.hu (одна тема с
          # чешским, общий парсер) и датский DR — открытый JSON dr-massive,
          # id каналов вынуты из ссылки «LIVE» на странице гида
          "sport1tv.hu", "dr.dk",
          # пятая пачка 02.09: британский tv24.co.uk (через iptv-org) —
          # TNT Sports 1–4 взамен закрытого tntsports.co.uk; слаги
          # iptv-org устарели, живые tnt-sports-N-hd
          "tv24.co.uk",
          # шестая пачка 02.09 (сайты дал владелец + браузерная разведка):
          # греческий Novasports сеткой и эстонский ERR открытым API
          "novasports.gr", "jupiter.err.ee",
          # белорусский Беларусь 5 (сетка в props astro, браузером) и
          # канадский OneSoccer (виджет Opta, браузером) — сайты владельца
          "news.by", "onesoccer.ca",
          # Fox Soccer Plus (США) — официального EPG у FOX нет, расписание
          # берём с телегида tvpassport.com (канал попросил владелец 02.09)
          "tvpassport.com",
          # аналоги для дыр (задача владельца 02.09): немецкие Das Erste и
          # ZDF через австрийский телегид, TSN 1-5 добраны в tvpassport,
          # албанские SuperSport — точечно через liveonsat (include-фильтр)
          "tvheute.at", "liveonsat.com",
          # sporteventz снова в обходе — НЕ источник витрины, а ЭТАЛОН живых
          # матчей: угаданный live топ-лиги без пары в нём считается записью
          # (просьба владельца 02.09 «сверять справочниками», parse_live)
          "sporteventz.com",
          # фид flashscore — второй эталон live (слово владельца 02.09):
          # полный календарь футбола дня, ключ x-fsign в заголовках источника
          # mobi-версия flashscore — главный эталон (фид ninja закрыт для
          # дата-центров): ~370 матчей дня, en-имена, время, ID
          "flashscore.mobi",
          # этап 6в (03.09, после «продолжаем» владельца): страницы 7 каналов
          # SuperSport Албания на livesoccertv — единственная замена
          # закрывшемуся liveonsat, 7 запросов в день
          "livesoccertv.com",
          # этап 6е (03.09): языковые версии эталона — те же fs_id, имена
          # по-местному; словарь учится по ним без угадывания по буквам.
          # Глубина у каждой своя (`days_ahead` в карточке): греческая,
          # венгерская, болгарская — 7 дней (они и давали игры без канона),
          # остальные — по странице в день
          "m.flashscore.gr", "m.flashscore.bg", "m.eredmenyek.com",
          "m.flashscore.ro", "m.flashscore.com.tr", "m.flashscore.pl",
          "m.flashscore.ru", "m.flashscore.ua", "m.livesport.cz",
          "m.rezultati.com",
          # Литва 06.09 (вопрос владельца про BTV): телегид tv3.lt,
          # канал × день через ?d=; 16 каналов выбрал владелец —
          # спортивные все + BTV, LNK, TV3, TV6, TV8, TV3 Plus, LRT,
          # LRT Plius. Запасные телегиды в ОТЛОЖЕНО.md
          "tv3.lt",
          ]
# СПРАВОЧНИКИ, не источники: liveonsat.com (решение 01.09) и
# sporteventz.com (решение 02.09) в ежедневный обход не входят. Оба —
# «матч → каналы мира»: уточнить название команды/лиги, время, найти
# замену отвалившемуся источнику. Разовая проба sporteventz:
#   github_run.py dispatch --urls "https://sporteventz.com/index.php?option=com_magictable&language_code=en&table=1&accesskey={WARMKEY}&se_date=&se_module=&se_id=&Itemid=211&client_tz_offset=%2B0300" --warmup "https://sporteventz.com/en/"
# liveonsat.com в
# ежедневный обход не входит. К нему обращаемся точечно — когда у канала
# нет своего сайта или тот закрыт капчей:
#   github_run.py dispatch --urls "https://liveonsat.com/2day.php?start_dd=DD&start_mm=MM&start_yyyy=YYYY&end_dd=DD&end_mm=MM&end_yyyy=YYYY&postponed=0"
# Парсер `app/parsers/liveonsat_com.py` готов и разбирает такой ответ.

# СПРАВОЧНИК №2 (решение владельца 01.09): livesoccertv.com — тоже не в
# ежедневном обходе. Сводка `/schedules/` каналы прячет (с американского
# адреса «Available on-demand»), зато СТРАНИЦА МАТЧА отдаёт полную таблицу
# «страна → каналы» откуда угодно:
#   github_run.py dispatch --urls "https://www.livesoccertv.com/match/<матч>"
# Ссылку матча берём со сводки; разбирает `app/parsers/livesoccertv_com.py`.

# резерв (решение владельца 31.08): polsatsport.pl — не в ежедневном обходе,
# перепроверка запускается руками: github_run.py dispatch --only polsatsport.pl


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="окно в сутках")
    ap.add_argument("--all", action="store_true", help="все источники, не только пилоты")
    ap.add_argument("--show", action="store_true", help="показать сами адреса")
    ap.add_argument("--json", metavar="ФАЙЛ", default="",
                    help="выгрузить план в файл — его читает обход на GitHub")
    args = ap.parse_args()

    conn = db.connect()
    domains = None if args.all else PILOTS
    for days in ([args.days] if args.days else [2, 5]):
        targets = crawl.plan(conn, domains, days=days)
        by_domain = Counter(t.domain for t in targets)
        print(f"── окно {days} суток ──")
        for domain, count in sorted(by_domain.items(), key=lambda x: -x[1]):
            note = "сетка, один ответ на все каналы" if domain in crawl.GRID_DOMAINS \
                else "адрес на канал и день"
            print(f"  {domain.ljust(12)} {str(count).rjust(4)} запрос(ов)   {note}")
        print(f"  {'ВСЕГО'.ljust(12)} {str(len(targets)).rjust(4)}\n")
        if args.show:
            for t in targets:
                print(f"    {t.day or '—'}  {t.channel[:22].ljust(22)} {t.url}")
            print()
    if args.json:
        days = args.days or 2
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "days": days,
            "built": str(date.today()),
            "note": "дата в адресах — метка, подставляется в день обхода",
            "sources": crawl.templates(conn, domains),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        # у источника со своей глубиной (`days_ahead`) дней столько, сколько
        # у него, а не сколько в окне — как и развернёт обход на GitHub
        count = sum((s.get("days_ahead") or days) * s["pages_per_day"]
                    if s["pages_per_day"]
                    else len(s["channels"])
                    * (1 if s["grid"] or s.get("days_inline")
                       else (s.get("days_ahead") or days))
                    for s in crawl.templates(conn, domains))
        print(f"план записан: {out}  ({count} адрес(ов), окно {days} суток)")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

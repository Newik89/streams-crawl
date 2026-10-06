# -*- coding: utf-8 -*-
r"""Проверки «признак эфира сайта читается, а не угадывается» (аудит 06.10).

Почему: у port.hu в данных лежали `is_live_mp`/`is_repeat`, а разбор угадывал
эфир первым показом пары и сверял с эталоном — живой Ferencváros — DVSC
пропал на сокращении. Аудит всех сайтов обхода #205 нашёл тот же класс у
tv2.no, tv.sport1.de, programme-tv.net, programetv.ro, sports.kz, webtv.sk,
HRT, BBC, РТРС, err.ee, tvheute.at, tvpassport.com и «слово не в словаре» у
tv.orf.at (`übertragung`).

Правила, которые здесь сторожатся:
  1. `site_says` — пометка сайта: слово в `live_raw` (эфир — из раздела live
     `data/markers.json`, повтор — из not_live) и вердикт в `extra`.
  2. `mark_first_show` строки с пометкой сайта не трогает: повтор не станет
     «первым показом», эфир не сотрётся; показ без пометки той пары, что сайт
     назвал эфиром, — не эфир; угаданное метится `live_guess`.
  3. По каждому изменённому сайту — урезанная НАСТОЯЩАЯ страница обхода #205
     (`scripts/testdata/live_flags/`) и что из неё должно выйти.
  4. Самопроверка `scripts/audit_run.py` ловит флаг в данных, слово вне
     словаря и кличку (DVSC ↔ Debrecen).

В сеть не ходит, базу не трогает. Запуск:

    python scripts/test_live_flags.py

Выход 0 — все проверки зелёные.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.mkdtemp()) / "none.db"))

from app import live, pipeline                                   # noqa: E402
from app.parsers import (SITE_FLAG, SITE_LIVE, SITE_LIVE_WORD,   # noqa: E402
                         SITE_REPEAT, SITE_REPEAT_WORD, Program, get,
                         mark_first_show, site_says)
import audit_run                                                 # noqa: E402
import parse_live as parse_live_mod                              # noqa: E402

DATA = ROOT / "scripts" / "testdata" / "live_flags"
KYIV = ZoneInfo("Europe/Kyiv")
MARKERS = live.load()

passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


def page(name: str) -> str:
    return (DATA / name).read_text(encoding="utf-8")


def parse(domain: str, name: str, url: str, tz: str | None = None,
          day: date | None = date(2026, 10, 6)):
    return get(domain)(page(name), day=day, tz=tz, url=url)


def find(programs, text: str, hour: str | None = None):
    """Передачи, где в заголовке есть `text` (и начало в `hour`, ЧЧ:ММ), по
    времени начала."""
    return sorted((p for p in programs if text in p.title
                   and (hour is None or p.start.strftime("%H:%M") == hour)),
                  key=lambda p: p.start)


def said(p) -> str:
    return (p.extra or {}).get(SITE_FLAG) or ""


def passes(p) -> bool:
    """Строка проходит проверку эфира (`app/live.py`) — маркер найден."""
    return bool(MARKERS.found(MARKERS.live, p.live_raw)) \
        and not MARKERS.found(MARKERS.not_live, p.live_raw)


def rejected_as_record(p) -> bool:
    return bool(MARKERS.found(MARKERS.not_live, p.live_raw))


def prg(title: str, hour: int, pair: str) -> Program:
    return Program(channel_raw="K", title=title, match_raw=pair,
                   start=datetime(2026, 10, 6, hour, 0, tzinfo=KYIV))


# ── общее: слова и угадывание ────────────────────────────────────────────────
print("Общие правила (app/parsers/__init__.py)")
check("слово эфира сайта есть в разделе live markers.json",
      MARKERS.found(MARKERS.live, SITE_LIVE_WORD) == SITE_LIVE_WORD)
check("слово повтора сайта есть в разделе not_live",
      MARKERS.found(MARKERS.not_live, SITE_REPEAT_WORD) == SITE_REPEAT_WORD)

rows = [prg("повтор вчерашнего", 8, "A - B"),
        prg("матч", 20, "A - B"),
        prg("ночной повтор", 23, "B - A")]
site_says(rows[0], False)
mark_first_show(rows, "live")
check("повтор по слову сайта не становится «первым показом»",
      rows[0].live_raw == SITE_REPEAT_WORD and said(rows[0]) == SITE_REPEAT
      and not rows[0].extra.get("live_guess"))
check("первым показом становится следующий, он помечен live_guess",
      rows[1].live_raw == "live" and rows[1].extra.get("live_guess") is True)
check("поздний перевёрнутый показ — повтор", rows[2].live_raw == ""
      and rows[2].extra.get("repeat_guess") is True)

rows = [prg("студия до матча", 19, "C - D"), prg("матч", 20, "C - D"),
        prg("повтор", 23, "C - D")]
site_says(rows[1], True)
mark_first_show(rows, "live")
check("эфир по слову сайта не стирается угадыванием",
      rows[1].live_raw == SITE_LIVE_WORD and said(rows[1]) == SITE_LIVE)
check("показы без пометки той пары, что сайт назвал эфиром, — не эфир",
      rows[0].live_raw == "" and rows[2].live_raw == "")

# ── сайты: урезанные настоящие страницы обхода #205 ──────────────────────────
print("tv2.no — флаги live/replay своих каналов, гости угадываются")
tv2 = parse("tv2.no", "tv2no_2026-10-06.json",
            "https://tv2no-epg-api.public.tv2.no/epg/days/2026/10/06")
kroatia = find(tv2, "Kroatia - Spania")
check("Kroatia - Spania 20:30 (live) — эфир сайта, проходит отсев; 02:00 "
      "(replay) — повтор, отсев режет как запись",
      len(kroatia) == 2 and said(kroatia[0]) == SITE_LIVE and passes(kroatia[0])
      and said(kroatia[1]) == SITE_REPEAT and rejected_as_record(kroatia[1]))
check("Romania - Sverige 06:00 (replay, первый показ на странице) — не эфир "
      "(до 06.10 угадывание давало эфир)",
      all(not passes(p) for p in find(tv2, "Romania - Sverige")))
both = find(tv2, "Saint-Raphaël - Elverum")
check("Saint-Raphaël - Elverum (live и replay сразу) — эфир: live главнее",
      both and said(both[0]) == SITE_LIVE)
quiet = find(tv2, "England - Tsjekkia")
check("England - Tsjekkia 00:00 у своего канала без флагов — не эфир и не "
      "угадывается", quiet and not quiet[0].live_raw
      and not quiet[0].extra.get("live_guess"))
guest = [p for p in tv2 if p.channel_raw == "TVNorge"]
check("у канала-гостя (TVNorge) флагов нет — эфир угадывается первым показом",
      len(guest) == 2 and not any(said(p) for p in guest)
      and guest[0].extra.get("live_guess") and guest[1].extra.get("repeat_guess"))

print("Словари, которые понадобились честным строкам (регресс #205)")
from app import names, sport                                     # noqa: E402
check("AFL Women's Premiership Football (tvpassport, data-live=1) — не футбол, "
      "а «Other Sport»: до 06.10 такие строки снимались как угаданные",
      sport.load().detect("AFL Women's Premiership Football: Sydney Swans vs. "
                          "Carlton Blues")[0] == "-")
from app import leagues                                          # noqa: E402
check("казахское «(әйелдер)» — женский турнир (W): sports.kz, Қазақстан — "
      "Ирландия 09.10", leagues.category(
          "Футбол. Әлем Чемпионаты-2027 Iріктеу турнирі (әйелдер). Қазақстан "
          "— Ирландия. Прямая трансляция") == "W")
check("сборные: Australien / Lettonie / Færøyene / Kasakhstan = эталон",
      all(names.same_team(a, b) for a, b in (
          ("Australien W", "Australia W"), ("Lettonie W", "Latvia W"),
          ("Færøyene", "Faroe Islands"), ("Kasakhstan", "Kazakhstan"))))

print("tv.sport1.de — emissionType")
s1 = parse("tv.sport1.de", "sport1de_2026-10-06.json",
           "https://api.sport1.info/v3/de/tv/epg")
half = find(s1, "Fußball-Halbzeit")
check("«45 - Die Fußball-Halbzeit» (live) — эфир сайта",
      half and said(half[0]) == SITE_LIVE and passes(half[0]))
check("Wiederholung — повтор, слово «wiederholung» из not_live",
      all(said(p) == SITE_REPEAT and rejected_as_record(p)
          for p in find(s1, "Hausmeister Krause")))
check("Erstausstrahlung — не эфир", all(said(p) == SITE_REPEAT
                                        for p in find(s1, "Sechserpack")))
check("Exklusiv — сайт промолчал", all(not said(p)
                                       for p in find(s1, "Fight Night")))

print("tvpassport.com — data-repeat главнее угадывания")
tp = parse("tvpassport.com", "tvpassport_fox-soccer-plus_2026-10-06.html",
           "https://www.tvpassport.com/tv-listings/stations/fox-soccer-plus/7538/2026-10-06",
           tz="America/New_York")
hj = find(tp, "Honduras vs. Jamaica")
check("Honduras vs. Jamaica 04:30 (data-repeat=1, первый показ на странице) "
      "— повтор, а не эфир (до 06.10 угадывание давало эфир)",
      hj and said(hj[0]) == SITE_REPEAT and not passes(hj[0]))
ss = find(tp, "Scotland vs. Slovenia")
check("Scotland vs. Slovenia 14:30 (data-live=1) — эфир, ночной показ — повтор",
      len(ss) == 2 and passes(ss[0]) and said(ss[0]) == SITE_LIVE
      and said(ss[1]) == SITE_REPEAT)

print("bbc.co.uk — (R) в описании")
bbc = parse("bbc.co.uk", "bbc_p00fzl67_2026-10-06.html",
            "https://www.bbc.co.uk/schedules/p00fzl67/2026/10/06")
check("передачи с (R) — повтор сайта, без (R) — без пометки",
      sum(said(p) == SITE_REPEAT for p in bbc) == 3
      and sum(not said(p) for p in bbc) == 2)

print("rtrs.tv — div.rerun")
rt = parse("rtrs.tv", "rtrs_c1.html", "https://www.rtrs.tv/program/raspored.php?c=1",
           tz="Europe/Sarajevo")
check("строки с div.rerun — повтор сайта и отсев режет их как запись",
      sum(said(p) == SITE_REPEAT and rejected_as_record(p) for p in rt) == 4)

print("programetv.ro — поля live/replay Prima Sport")
pr = parse("programetv.ro", "programetv_prima-sport-2.html",
           "https://www.programetv.ro/program-tv/prima-sport-2/")
cl = find(pr, "Cipru")
check("Cipru – Letonia 19:00 (live: true) — эфир сайта", cl
      and said(cl[0]) == SITE_LIVE and passes(cl[0]))
it = find(pr, "Italia")
check("Italia - Turcia 21:45 — эфир, Italia – Turcia 02:45 (replay) — повтор",
      len(it) == 2 and said(it[0]) == SITE_LIVE and said(it[1]) == SITE_REPEAT)
check("Kosovo – Austria 08:30 (replay) больше не угадывается эфиром",
      all(said(p) == SITE_REPEAT and not passes(p) for p in find(pr, "Kosovo")))

print("webtv.sk — «Priamy prenos» / «Záznam» в описании")
wt = parse("webtv.sk", "webtv_joj_sport.json",
           "https://api.webtv.sk/epg/channel?channel_id=joj_sport")
check("Priamy prenos — эфир сайта", any(said(p) == SITE_LIVE and passes(p)
                                        for p in wt))
check("Záznam — повтор сайта", sum(said(p) == SITE_REPEAT
                                   and rejected_as_record(p) for p in wt) == 3)

print("tv.orf.at — LIVE в заголовке и слово угадывания из словаря")
orf = parse("tv.orf.at", "orf_sport_plus.html",
            "https://tv.orf.at/program/orfs/index.html")
check("LIVE в заголовке — эфир сайта", sum(said(p) == SITE_LIVE for p in orf) == 2)
guessed_orf = [p for p in orf if p.extra.get("live_guess")]
check("угаданный эфир «Übertragung» несёт слово словаря (было «übertragung» — "
      "его в markers.json нет, отсев молча резал все такие строки)",
      guessed_orf and all(passes(p) for p in guessed_orf))

print("raspored.hrt.hr — (R) и «prijenos»")
hrt = parse("raspored.hrt.hr", "hrt_mreza=3_datum=2026-10-08.txt",
            "https://raspored.hrt.hr/format/text.xml?mreza=3&datum=2026-10-08",
            day=date(2026, 10, 8))
check("(R) — повтор сайта", sum(said(p) == SITE_REPEAT for p in hrt) == 3)
misa = find(hrt, "Misa")
check("«Zadar: Misa, prijenos» — эфир сайта, «prijenos» есть в словаре",
      misa and said(misa[0]) == SITE_LIVE and passes(misa[0]))

print("jupiter.err.ee — automaticReplay")
err = parse("jupiter.err.ee", "err_etv2_2026-10-10.json",
            "https://services.err.ee/api/tvSchedule/getTimelineSchedule?day=10"
            "&month=10&year=2026&channel=etv2")
check("automaticReplay=Y — повтор сайта словом «kordus» (not_live)",
      sum(said(p) == SITE_REPEAT and rejected_as_record(p) for p in err) == 3)

print("programme-tv.net — значки Direct / Rediffusion")
ptv = parse("programme-tv.net", "programmetv_canalplus_2026-10-10.html",
            "https://www.programme-tv.net/programme/chaine/2026-10-10/"
            "programme-canalplus-2.html")
ars = find(ptv, "Arsenal / Leeds United")
check("Arsenal / Leeds United 13h25 (Direct) — эфир сайта словом «en direct»",
      ars and said(ars[0]) == SITE_LIVE and passes(ars[0]))
check("Rediffusion — повтор сайта", sum(said(p) == SITE_REPEAT
                                        and rejected_as_record(p) for p in ptv) == 2)

print("sports.kz — «Прямая трансляция» в заголовке")
kz = parse("sports.kz", "sportskz_day.html", "https://www.sports.kz/tv",
           tz="Asia/Almaty")
kf = find(kz, "Қазақстан — Фарер")
check("Қазақстан — Фарер аралдары. Прямая трансляция — эфир сайта",
      kf and said(kf[0]) == SITE_LIVE and passes(kf[0]))
sm = find(kz, "Словакия — Молдова")
check("утренний показ без пометки — угадывается (live_guess), не «эфир сайта»",
      sm and not said(sm[0]) and sm[0].extra.get("live_guess"))

print("tvheute.at — (Wh.) и сверка угаданного")
th = parse("tvheute.at", "tvheute_zdf_06-10-2026.html",
           "https://tvheute.at/part/channel-shows/partial/zdf/06-10-2026")
check("(Wh.) в заголовке — повтор сайта", any(said(p) == SITE_REPEAT
                                              and rejected_as_record(p) for p in th))
check("угаданный эфир помечен live_guess — сверка с эталоном включится "
      "(домена не было в REPEAT_GUESS_DOMAINS)",
      all(p.extra.get("live_guess") for p in th if p.live_raw == "live"))
th9 = parse("tvheute.at", "tvheute_zdf_09-10-2026.html",
            "https://tvheute.at/part/channel-shows/partial/zdf/09-10-2026")
de = find(th9, "Australien")
check("рубрика «FUßBALL» срезана с подзаголовка: пара «Deutschland - Australien» "
      "(была «FUßBALL Deutschland» — не сходилась с эталоном Germany W)",
      de and de[0].match_raw == "Deutschland - Australien"
      and "FUßBALL" in de[0].sport_raw)

print("trtspor.com.tr — сетка переехала в pageComponents")
tr = parse("trtspor.com.tr", "trtspor_2026-10-06.html",
           "https://www.trtspor.com.tr/yayin-akisi/trt-spor")
bourg = [p for p in tr if "BOURG - TOFAŞ" in p.title]
check("строки снова разбираются (было 0 при «расписание есть»)", len(tr) > 5)
check("BKT EuroCup Bourg - Tofaş 20:30 — эфир, ночной показ (isRepeat) — нет",
      len(bourg) == 2 and bourg[0].live_raw == "canlı" and bourg[1].live_raw == ""
      and bourg[0].channel_raw == "TRT SPOR")
check("время trtspor «20:30Z» — местное: 20:30 по Киеву, как у эталона "
      "(как UTC было бы 23:30)",
      bourg and bourg[0].start.astimezone(KYIV).strftime("%d.%m %H:%M")
      == "06.10 20:30")

# ── поздний угаданный показ на другом канале (проверка 06.10) ────────────────
print("parse_live — первый показ пары и по строкам, помеченным сайтом")
import parse_live                                                # noqa: E402


def shown(channel: str, hour: int, pair: str, sport: str = "F",
          site_live: bool | None = None, guess: bool = False):
    """Строка `found` у сайта со страницей на канал (tvpassport.com)."""
    p = Program(channel_raw=channel, title=pair, match_raw=pair,
                start=datetime(2026, 10, 6, hour, 0, tzinfo=KYIV))
    site_says(p, site_live)
    if guess:
        p.extra["live_guess"] = True
    home, _, away = pair.partition(" - ")
    return ("www.tvpassport.com", pipeline.Row(
        program=p, ok=True, home=home, away=away, sport=sport, start_kyiv=p.start))


found = [shown("TSN2", 14, "Scotland - Slovenia", site_live=True),
         shown("TSN5", 16, "Slovenia - Scotland", guess=True),
         shown("TSN4", 12, "Canada - Mexico", guess=True),
         shown("TSN1", 15, "Canada - Mexico", site_live=True),
         shown("TSN1", 18, "Partizan - Crvena zvezda", site_live=True),
         shown("TSN3", 20, "Partizan - Crvena zvezda", sport="B", guess=True)]
firsts = parse_live.first_shows(found)
late = [r.program.channel_raw for domain, r in found
        if parse_live.late_show(domain, r, firsts)]
check("угаданный показ на другом канале позже эфира, помеченного сайтом, — "
      "запись (TSN5); помеченное, первое угаданное и баскетбол после "
      "футбольного дерби не трогаются", late == ["TSN5"], late)

# ── самопроверка прогона scripts/audit_run.py ────────────────────────────────
print("audit_run.py — известные классы ошибок")
flags = audit_run.raw_flags(page("porthu_290_2026-10-06.json"), MARKERS)
check("флаг port.hu `is_live_mp` виден в сырых данных",
      flags.get(("live", "json:is_live_mp=true")) == 2
      and flags.get(("repeat", "json:is_repeat=true")) == 2)
flags = audit_run.raw_flags(page("tvpassport_fox-soccer-plus_2026-10-06.html"), MARKERS)
check("data-live / data-repeat tvpassport видны",
      flags.get(("live", "attr:data-live=1")) and flags.get(("repeat", "attr:data-repeat=1")))
check("закомментированный значок (oneplaysport.cz) признаком не считается",
      not audit_run.raw_flags('<!--<div class="live">Živě</div>-->', MARKERS))

site = audit_run.Site("port.hu")
site.pages, site.programs, site.guessed_live = 3, 90, 20
site.flags[("live", "json:is_live_mp=true")] = 9
problems, _ = audit_run.check_flags({"port.hu": site})
check("флаг в данных при нуле честного эфира — подозрение «не читается»",
      any("port.hu" in x and "не читается" in x for x in problems), problems)

no_word = live.Markers(live=live._pattern(["live"]), not_live=None, stop_title=None)
site = audit_run.Site("jupiter.err.ee")
audit_run.uncovered_words("Jalgpall: Eesti - Norra, otseülekanne", no_word, site)
check("слово эфира, которого нет в словаре, найдено («otseülekanne», 03.10)",
      site.words.get("otseülekanne") == 1)
site = audit_run.Site("tvarenasport.si")
audit_run.uncovered_words("Fudbal v živo", MARKERS, site)
check("слово внутри словарного выражения («živo» в «v živo») не подозрение",
      not site.words)

ref = {"sport": "F", "home": "Ferencvaros", "away": "Debrecen",
       "league": "HUNGARY: NB I", "fs_id": "x1", "start_kyiv": "2026-10-04T19:00"}
# сокращение, которого нет в словаре (вымышленное «DBRC»; детектор ловит
# клички на ту же первую букву или по местному имени). Сам DVSC
# с 06.10 записан в aliases.json (ветка hu-live) и сходится — детектор
# должен ловить именно НЕзнакомые клички
row = pipeline.Row(program=Program(channel_raw="M4 Sport", title="Ferencváros - DBRC",
                                   start=None, league_raw="Labdarúgó NB I"),
                   ok=True, home="Ferencváros", away="DBRC", sport="F",
                   start_kyiv=datetime(2026, 10, 4, 19, 0, tzinfo=KYIV))
site = audit_run.Site("port.hu")
site.rows.append((row, "page"))
games = {"окно": 0, "собрано": "2026-10-04 04:00", "эталон": [ref],
         "games": [{"start_kyiv": "2026-10-04T19:00"}]}
aliases, zones, _ = audit_run.check_aliases_and_zones({"port.hu": site}, games)
check("кличка: «DBRC» ≠ «Debrecen» при твёрдо совпавшей второй команде",
      any("DBRC" in x and "Debrecen" in x for x in aliases), aliases)

twin = {"эталон": [{"fs_id": "0K7iLNL7", "home": "Olimpia Asuncion",
                    "away": "Nacional Asuncion", "start_kyiv": t}
                   for t in ("2026-10-06T01:15", "2026-10-07T01:15")]}
lines = audit_run.check_reference(twin)
check("эталон: один fs_id с двумя временами (ровно сутки — полночь страниц)",
      lines and "ровно на сутки" in lines[0] and "разнесены 1" in lines[0], lines)

# ── второй круг самопроверки (сбор #205, 06.10) ──────────────────────────────
print("Второй круг: лиги, клички, ORF, проверки 5/6/7/10 audit_run")
check("«Liga Next Gen» (canal11.pt) — турнир U23: команды получают U23",
      leagues.category("Liga Next Gen: FC FELGUEIRAS - CF ESTRELA") == "U23"
      and leagues.category("Liga Revelação") == "U23")
check("«Premier League 2» — U21, а «Premier League 2. kolo» (тур взрослой) — нет",
      leagues.category("Premier League 2: Chelsea - Arsenal") == "U21"
      and leagues.category("Premier League 2. kolo: Chelsea - Arsenal") == "")
check("«(k)» — женский: «Fodbold: Canada - Danmark (k), direkte» (dr.dk)",
      leagues.category("Fodbold: Canada - Danmark (k), direkte") == "W")
check("клички: QPR, Barca, VENEZA, UAE, Hapoel TA, BiH U21, Internazionale, "
      "Brose = эталон",
      all(names.same_team(a, b) for a, b in (
          ("QPR", "Queens Park Rangers"), ("QPR", "Куинс Парк Рейнджърс"),
          ("Barca", "Barcelona"), ("VENEZA", "Venezia"),
          ("UAE", "United Arab Emirates"), ("Hapoel TA", "Hapoel Tel Aviv"),
          ("BiH U21", "Bosnia & Herzegovina U21"), ("Internazionale", "Inter"),
          ("Brose", "Bamberg"),
          ("Crvena Zvezda Bělehrad", "Crvena Zvezda Meridianbet"))))
check("соседи кличек не сходятся: QPR ≠ Queen's Park, Hapoel TA ≠ Maccabi Tel "
      "Aviv, VENEZA ≠ Venezuela, BiH U21 ≠ взрослой BiH",
      not any(names.same_team(a, b) for a, b in (
          ("Queens Park Rangers", "Queens Park"), ("Hapoel TA", "Maccabi Tel Aviv"),
          ("VENEZA", "Venezuela"), ("BiH U21", "Bosnia & Herzegovina"),
          ("Internazionale", "Inter Turku"))))

orf_rows = parse("tv.orf.at", "orf_sport_plus.html",
                 "https://tv.orf.at/program/orfs/index.html")
check("tv.orf.at отдаёт строки в порядке страницы (самопроверка видела «время "
      "пошло назад» из-за склейки угадываемых и остальных)",
      [p.start for p in orf_rows] == sorted(p.start for p in orf_rows))

kolla_json = ('{"status": true, "content": {"channels": [{"name": "SVT1", "programs": ['
              '{"name": "Fotboll: Allsvenskan, AIK - Hammarby", "startTime": 1791313200000},'
              '{"name": "Nyheter", "startTime": 1791291600000}]}]}}')
kolla = get("dagenstv.com")(kolla_json, day=date(2026, 10, 6), url="")
check("kolla.tv: передачи канала по времени (ручка отдаёт вразнобой)",
      [p.title for p in kolla] == ["Nyheter", "Fotboll: Allsvenskan, AIK - Hammarby"],
      [p.title for p in kolla])

copy = Program(channel_raw="Diema Sport", title="Черно море - Левски", start=None)
row_a = pipeline.Row(program=copy, ok=True, home="Черно море", away="Левски", sport="F",
                     start_kyiv=datetime(2026, 10, 11, 17, 30, tzinfo=KYIV))
row_b = pipeline.Row(program=Program(channel_raw="Diema Sport", title="Черно море - Левски",
                                     start=None),
                     ok=True, home="Черно море", away="Левски", sport="F",
                     start_kyiv=datetime(2026, 10, 11, 17, 30, tzinfo=KYIV))
kept, dropped = parse_live_mod.unique_rows([("diemaxtra.nova.bg", row_a),
                                            ("diemaxtra.nova.bg", row_b),
                                            ("nova.bg", row_b)])
check("одна передача с двух страниц сайта — одна строка (другой сайт — своя)",
      dropped == 1 and len(kept) == 2, (dropped, len(kept)))

site = audit_run.Site("dagenstv.com")
for d in ("2026-10-06", "2026-10-07", "2026-10-08"):
    site.by_content["same"].append((d, "", f"kolla_{d}.html"))
site.by_content["other"].append(("2026-10-06", "SVT1", "x.html"))
same = audit_run.check_same_pages({"dagenstv.com": site})
check("проверка 10: три даты — один файл → 2 запроса впустую",
      len(same) == 1 and "2 запрос" in same[0], same)

site = audit_run.Site("tv.orf.at")
site.undated_yesterday.append(("ORF SPORT+", date(2026, 10, 6), "index: вчера"))
site.undated_yesterday.append(("ORF 1", date(2026, 10, 6), "index: вчера"))
site.days_held.add(("ORF SPORT+", date(2026, 10, 6)))
lines = audit_run.check_days({"tv.orf.at": site})
check("проверка 5: «сегодня» без даты отдало вчера — подозрение, только если "
      "день не скачан другой страницей (ORF SPORT+ скачан ссылкой, ORF 1 — нет)",
      len(lines) == 1 and "1 стр." in lines[0], lines)

ref_round = [{"fs_id": f"w{i}", "league": "BOSNIA AND HERZEGOVINA: WWIN Liga BiH",
              "start_kyiv": "2026-10-10T18:00", "home": f"H{i}", "away": f"A{i}"}
             for i in range(5)]
ref_round.append({"fs_id": "pl1", "league": "ENGLAND: Premier League",
                  "start_kyiv": "2026-10-10T17:00", "home": "Ipswich", "away": "Fulham"})


def lost_row(channel, title, home, away, hour, day=11):
    prog = Program(channel_raw=channel, title=title, start=None,
                   extra={SITE_FLAG: SITE_LIVE})
    return pipeline.Row(program=prog, ok=True, home=home, away=away, sport="F",
                        start_kyiv=datetime(2026, 10, day, hour, 0, tzinfo=KYIV))


arena = audit_run.Site("tvarenasport.ba")
arena.rows.append((lost_row("Arena Premium 1", "Sloga - Zrinjski", "Sloga",
                            "Zrinjski", 17), "p"))
diema = audit_run.Site("diemaxtra.nova.bg")
diema.rows.append((lost_row("Diema Sport 2", "Ипсуич Таун - Фулъм", "Ипсуич Таун",
                            "Фулъм", 16, 12), "p"))
games_lost = {"окно": 6, "собрано": "2026-10-06 03:20", "эталон": ref_round,
              "games": [], "на_разбор": [], "снято": [
                  {"фильтр": parse_live_mod.СНЯТО_СЫГРАН, "домен": "tvarenasport.ba",
                   "канал": "Arena Premium 1", "заголовок": "Sloga - Zrinjski",
                   "почему": "эталон: Sloga Meridian - Zrinjski 10.10 18:00 (fs_id w0)"},
                  {"фильтр": parse_live_mod.СНЯТО_СЫГРАН, "домен": "diemaxtra.nova.bg",
                   "канал": "Diema Sport 2", "заголовок": "Ипсуич Таун - Фулъм",
                   "почему": "эталон: Ipswich - Fulham 10.10 17:00 (fs_id pl1)"}]}
lost, info = audit_run.check_lost({"tvarenasport.ba": arena,
                                   "diemaxtra.nova.bg": diema}, games_lost)
check("проверка 6: снятое «повтор по flashscore» при заглушке тура в эталоне — "
      "подозрение (Arena BA), при настоящем времени — справка (Diema)",
      len(lost) == 1 and "tvarenasport.ba" in lost[0] and "заглушка" in lost[0]
      and any("diemaxtra" in x and "снято фильтром" in x for x in info), (lost, info))

row = pipeline.Row(program=Program(channel_raw="Arena Sport 1", title="X", start=None,
                                   league_raw="SRPSKA LIGA"),
                   ok=True, home="Radnički Obrenovac", away="BSK 1926", sport="F",
                   start_kyiv=datetime(2026, 10, 11, 12, 0, tzinfo=KYIV))
site = audit_run.Site("tvarenasport.com")
site.rows.append((row, "page"))
games_bsk = {"окно": 0, "собрано": "2026-10-11 04:00", "games": [{"start_kyiv": "2026-10-11T12:00"}],
             "эталон": [{"sport": "F", "home": "Radnicki Obrenovac", "away": "Bacevac",
                         "league": "SERBIA: Srpska Liga - Belgrade", "fs_id": "b1",
                         "start_kyiv": "2026-10-11T12:00"}]}
aliases_bsk, _, info_bsk = audit_run.check_aliases_and_zones({"tvarenasport.com": site},
                                                             games_bsk)
check("проверка 7: двусмысленная кличка из KNOWN_NOT_ALIASES (BSK 1926) — в "
      "справку, не в подозрения", not aliases_bsk
      and any("BSK 1926" in x and "проверено" in x for x in info_bsk),
      (aliases_bsk, info_bsk))

print(f"\nИтого: {passed} зелёных, {len(failed)} красных")
for name in failed:
    print("  ✖", name)
sys.exit(1 if failed else 0)

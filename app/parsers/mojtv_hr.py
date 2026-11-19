# -*- coding: utf-8 -*-
"""mojtv.hr — Хорватия, агрегатор; даёт Sport Klub 1–6, MAXSport, SPTV.

Ценность: сайт самого Sport Klub (`sportklub.hr`) закрыт Cloudflare-ом,
а здесь его сетка лежит открыто. Arena-каналы пропускаем — они уже идут
напрямую с рамки Arena; Eurosport HR не берём (дубли тем же временем).

Страницы: `/tv-program/-2/sportski/danas.aspx` (сегодня) и `sutra.aspx`
(завтра) — все спортканалы разом. В плане обхода они заведены как две
«строки-канала» (`source_channels`: danas/sutra) типа «канальная сетка»,
поэтому параметр `channels` парсер ИГНОРИРУЕТ — отбор каналов у него свой
(`KEEP` ниже).

Разметка: `h2.hide` — имя канала, дальше его `div.programsingle`:

    div.pt > .pi > a
      em                `20:55` (+ иконка)
      strong            `Nogomet: Varaždin - Rudeš`
      хвост после <br>  `SuperSport HNL 2026./2027. (UŽIVO)`

`(UŽIVO)` — честный маркер: он и у студий «до/после матча»
(`Emisija prije/nakon utakmice X - Y (UŽIVO)`) — их режут стоп-слова
(`prije utakmice`, `nakon utakmice` в `data/markers.json`).

Дата дня лежит в инициализации сетки: `'29.8.2026. 6:00:00'` — берём её,
а не аргумент `day` (страница «sutra» иначе легла бы на сегодня).
Телегид-день идёт 06:00 → 06:00: ночь после полуночи — следующая дата
(`daytime.walk_programs`, по порядку страницы).
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from .. import daytime
from . import Program, label, register

DOMAIN = "mojtv.hr"
TZ = "Europe/Zagreb"

#: как канал подписан в `h2.hide` → каноничное имя для базы
KEEP = {
    "SK1": "Sport Klub 1", "SK2": "Sport Klub 2", "SK3": "Sport Klub 3",
    "SK4": "Sport Klub 4", "SK5": "Sport Klub 5", "SK6": "Sport Klub 6",
    "MaxSport1": "MAXSport 1", "MaxSport2": "MAXSport 2",
    "Sportska Televizija": "SPTV",
}

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})")
_UZIVO = re.compile(r"\(\s*UŽIVO\s*\)", re.I)
_GRID_DATE = re.compile(r"'(\d{1,2})\.(\d{1,2})\.(\d{4})\.? 6:00")


#: ── новая разметка (книга 127, с 15.11.2026: сайт переделали за ночь) ──
#: адрес: /tv-program/sportski/2026-11-16 (был /tv-program/-2/sportski/<дата>.aspx)
#:   a.channel-logo-slot#channel-logo-62 > img[alt="SK1 tv program"]   — канал
#:     (с 19.11 картинки нет, имя текстом — см. `_channel_of`, книга 168)
#:   div.grid-row[data-channel-target="channel-logo-62"]               — его ряд
#:     div.grid-card[data-time="08:10"]
#:       span.grid-card-time   `08:10`
#:       span.grid-card-title  `Nogomet - Liga nacija: France - Turkiye (UŽIVO)`
#:       span.grid-card-desc   описание (у повторов — «snimka»)
#: день — в <title>: «Tv program - Sportski - ponedjeljak, 16.11.2026. | MojTV»;
#: у страницы «сегодня» даты в заголовке нет — берём день из адреса или запроса
_NEW_MARK = 'class="grid-row"'
_TITLE_DATE = re.compile(r"<title>[^<]*?(\d{1,2})\.(\d{1,2})\.(\d{4})\.", re.I)
_URL_DATE = re.compile(r"/(\d{4})-(\d{2})-(\d{2})(?:[/?#]|$)")
_ALT_TAIL = re.compile(r"\s*tv program\s*$", re.I)


#: ── имя канала в ячейке (книга 168, 19.11.2026) ──
#: 19.11 сайт убрал из ячейки картинку с `alt` и пишет имя текстом:
#:   <a href="/tv-program/kanal/62/sk1" class="channel-logo-slot" id="channel-logo-62"> SK1 </a>
#: Разборщик читал только `alt` — ноль строк со всех страниц. Теперь имя
#: ищем везде, где оно может лежать (`label.labels`), а не найдя — берём
#: номер канала из адреса ячейки: он у сайта не менялся ни при переделке
#: 15.11, ни 19.11.
#: имя для сверки (`label.key`) → каноничное имя: подписи сайта и сами имена
_KEEP_KEY = {label.key(k): v for k, v in KEEP.items()} | {label.key(v): v for v in KEEP.values()}
#: номер канала в адресе ячейки (`/tv-program/kanal/62/sk1`) → каноничное имя
KEEP_NUM = {
    "62": "Sport Klub 1", "63": "Sport Klub 2", "296": "Sport Klub 3",
    "240": "Sport Klub 4", "241": "Sport Klub 5", "242": "Sport Klub 6",
    "722": "MAXSport 1", "723": "MAXSport 2", "244": "SPTV",
}
_KANAL_NUM = re.compile(r"/kanal/(\d+)(?:/|$)")


def _channel_of(slot) -> str | None:
    """Канал ячейки `a.channel-logo-slot`; None — канал не из `KEEP`.
    Правила по порядку:
      1. подписи ячейки (`label.labels`: картинка → сама ячейка → текст →
         хвост адреса) без хвоста «tv program»; сверка без регистра, пробелов
         и дефисов — первая знакомая подпись и есть канал;
      2. ни одна подпись не знакома — номер канала из адреса ячейки
         (`KEEP_NUM`): сайт переименовал канал или убрал имя совсем."""
    for text in label.labels(slot):
        name = _KEEP_KEY.get(label.key(_ALT_TAIL.sub("", text)))
        if name:
            return name
    m = _KANAL_NUM.search(slot.attributes.get("href") or "")
    return KEEP_NUM.get(m.group(1)) if m else None


#: ── часы сайта и «телевизионный день» (книга 166, 18.11.2026) ──
#: Сутки у сайта идут 06:00 → 06:00 (сетка начинается с 06:00). Пока на
#: часах сайта нет шести утра, он считает, что ещё идёт вчерашний день, и
#: страница с датой Д показывает программу дня Д−1 — хотя в заголовке и в
#: навигации стоит Д. Замер 17–18.11.2026: страницы, скачанные сервером в
#: 05:40 по Загребу, все сдвинуты на сутки (27 эфирных пар из 27 стояли у
#: sportklub.hr на день раньше); те же адреса в 10:00 и в 22:22 — верные.
#: Часы сайта стоят на самой странице, в полоске дней:
#:   <span class="day-name">sada</span> <span class="day-number">05:40</span>
#: Точный час переключения не замерен: 06:00 — по началу сетки.
ТЕЛЕДЕНЬ_С = 6
_SITE_CLOCK = re.compile(
    r'class="day-name">\s*sada\s*</span>\s*<span[^>]*class="day-number">\s*(\d{1,2}):(\d{2})',
    re.I)


def _site_clock(html: str) -> tuple[int, int] | None:
    """Который час на сайте в момент, когда он отдал страницу («sada 05:40»);
    None — часов на странице нет."""
    m = _SITE_CLOCK.search(html)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _named_day(html: str, url: str, day: _date | None, tz: str) -> _date:
    """День, которым страница НАЗВАНА: из заголовка, иначе из адреса, иначе
    из запроса."""
    m = _TITLE_DATE.search(html)
    if m:
        return _date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = _URL_DATE.search(url or "")
    if m:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return day or daytime.today(tz)


def _new_day(html: str, url: str, day: _date | None, tz: str) -> _date:
    """День ПРОГРАММЫ новой страницы. Правила по порядку:
      1. страница названа днём Д (`_named_day`: заголовок → адрес → запрос);
      2. на часах сайта раньше `ТЕЛЕДЕНЬ_С` — программа на ней дня Д−1
         (книга 166); страница «сегодня» без даты до шести утра вживую не
         проверялась — считается так же, по тому же телевизионному дню;
      3. часов на странице нет или на них шесть утра и позже — день Д."""
    named = _named_day(html, url, day, tz)
    clock = _site_clock(html)
    if clock is not None and clock[0] < ТЕЛЕДЕНЬ_С:
        return named - timedelta(days=1)
    return named


def _split_title(title: str) -> tuple[str, str, str, str]:
    """Заголовок карточки → (чистый заголовок, пара «A - B» или « », лига,
    вид спорта). Правила:
      1. «(UŽIVO)» вырезается (эфир определяет вызывающий);
      2. пара — после ПОСЛЕДНЕГО «: » («Odbojka: Odbojka: Dubrovnik – Dinamo»);
      3. у гостей хвост после запятой — турнир («Dinamo, SuperSport Superliga…»);
      4. рубрика до двоеточия: «Nogomet - Liga nacija» → вид спорта «Nogomet»,
         лига «Liga nacija»; хвост после запятой главнее."""
    clean = " ".join(_UZIVO.sub("", title).split())
    head, sep_, rest = clean.rpartition(": ")
    rest = rest.strip() or clean
    head = head.split(": ")[0].strip() if sep_ else ""
    sport, _, rubric = head.partition(" - ")
    pair, league = " ", rubric.strip()
    for sep in (" - ", " – "):
        if sep in rest:
            home, _, away = rest.partition(sep)
            away, _, tail = away.partition(", ")
            if home.strip() and away.strip():
                pair = f"{home.strip()} - {away.strip()}"
                league = tail.strip() or league
            break
    return clean, pair, league, sport.strip()


def _parse_new(html: str, day: _date | None, tz: str, url: str) -> list[Program]:
    """Разбор новой разметки (книга 127). Каналы — только из `KEEP`."""
    zone = ZoneInfo(tz)
    day = _new_day(html, url, day, tz)
    tree = HTMLParser(html)
    names = {}
    for slot in tree.css("a.channel-logo-slot"):
        names[slot.attributes.get("id") or ""] = _channel_of(slot)
    out: list[Program] = []
    for row in tree.css("div.grid-row"):
        channel = names.get(row.attributes.get("data-channel-target") or "")
        if not channel:
            continue
        for card in row.css("div.grid-card"):
            time_node = card.css_first(".grid-card-time")
            title_node = card.css_first(".grid-card-title")
            hm = _HHMM.match((time_node.text(strip=True) if time_node else "")
                             or (card.attributes.get("data-time") or ""))
            title = title_node.text(strip=True) if title_node else ""
            if not hm or not title:
                continue
            desc_node = card.css_first(".grid-card-desc")
            desc = " ".join((desc_node.text() if desc_node else "").split())
            live = bool(_UZIVO.search(title) or _UZIVO.search(desc))
            clean, pair, league, sport = _split_title(title)
            out.append(Program(
                channel_raw=channel, title=clean,
                start=datetime(day.year, day.month, day.day,
                               int(hm.group(1)), int(hm.group(2)), tzinfo=zone),
                raw_time=hm.group(0),
                description=_UZIVO.sub("", desc).strip()[:200],
                # лига: хвост после запятой или рубрика, а нет их — описание
                # карточки (как «хвост после <br>» в прежней разметке)
                league_raw=(league or _UZIVO.sub("", desc).strip())[:120]
                if pair != " " else "",
                sport_raw=sport[:60],
                live_raw="uživo" if live else "",
                match_raw=pair, source_url=url,
                extra={"day": day.isoformat()},
            ))
    # ряды каналов идут друг за другом, у каждого сутки 06:00 → 06:00:
    # полночь считаем по каждому каналу отдельно
    result: list[Program] = []
    for name in dict.fromkeys(p.channel_raw for p in out):
        result += daytime.walk_programs([p for p in out if p.channel_raw == name], day, tz)
    return result


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    if _NEW_MARK in html:
        return _parse_new(html, day, tz or TZ, url)
    zone = ZoneInfo(tz or TZ)
    gd = _GRID_DATE.search(html)
    if gd:
        day = _date(int(gd.group(3)), int(gd.group(2)), int(gd.group(1)))
    day = day or daytime.today(tz or TZ)
    tree = HTMLParser(html)

    out: list[Program] = []
    channel = None
    for node in tree.root.traverse():
        if node.tag == "h2" and "hide" in (node.attributes.get("class") or ""):
            channel = KEEP.get(node.text(strip=True))
        elif node.tag == "div" and channel \
                and "programsingle" in (node.attributes.get("class") or ""):
            for a in node.css("div.pt a"):
                em = a.css_first("em")
                strong = a.css_first("strong")
                if not em or not strong:
                    continue
                hm = _HHMM.match(em.text(strip=True))
                title = strong.text(strip=True)
                if not hm or not title:
                    continue
                whole = a.text(strip=True)
                tail = whole.replace(em.text(strip=True), "", 1) \
                            .replace(title, "", 1).strip()
                live = bool(_UZIVO.search(whole))
                clean = _UZIVO.sub("", title).strip()
                _, _, rest = clean.partition(":")
                rest = rest.strip() or clean
                pair = " "
                for sep in (" - ", " – "):
                    if sep in rest:
                        home, _, away = rest.partition(sep)
                        if home.strip() and away.strip():
                            pair = f"{home.strip()} - {away.strip()}"
                        break
                d = day    # дата — ниже, по порядку страницы
                out.append(Program(
                    channel_raw=channel, title=clean,
                    start=datetime(d.year, d.month, d.day,
                                   int(hm.group(1)), int(hm.group(2)),
                                   tzinfo=zone),
                    raw_time=hm.group(0),
                    description=_UZIVO.sub("", tail).strip()[:200],
                    league_raw=_UZIVO.sub("", tail).strip()[:120]
                    if pair != " " else "",
                    sport_raw=clean.split(":", 1)[0] if ":" in clean else "",
                    live_raw="uživo" if live else "",
                    match_raw=pair, source_url=url,
                    extra={"day": d.isoformat()},
                ))
    # Телегид-день 06:00 → 06:00; вместо порога «час < 6 → завтра» — общее
    # правило полуночи по порядку страницы (07.10, сбор #205: тот же порог
    # у ntvplus и sport5 ставил ночной эфир на сутки позже)
    return daytime.walk_programs(out, day, tz or TZ)

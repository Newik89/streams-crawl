# -*- coding: utf-8 -*-
"""flashscore.mobi — ЭТАЛОН: весь мировой футбол дня одной страницей.

Владелец назвал flashscore лучшим справочником имён и времени (02–02.09).
Полноценный фид (`…flashscore.ninja/…/x/feed/…`) пускает только жилые IP —
даже с верным ключом `x-fsign` дата-центрам отвечает 401. Зато упрощённая
версия `www.flashscore.mobi` отдаётся серверу обычным запросом: ~370 матчей
дня, лиги заголовками, время, статус и ID матча.

    <h4>AUSTRIA: Bundesliga …</h4>
    <span>20:30</span>Salzburg - SK Rapid <a href="/match/YmWtmp0k/" class="sched">-</a>
    <span class="live">8'</span>… <a … class="live">0-1</a>   — идёт сейчас
    <a … class="fin">7-2</a>                                  — закончен

Пояс — CET/CEST (`Europe/Paris`): летом +2 (сверено по Зальцбург — Рапид
с нашей базой 02.09, страница показывала 20:30 = 21:30 Киева), зимой +1 —
перевод стрелок ZoneInfo делает сам (C1 аудита, 12.09). День листается `/?d=1`.

Роль на разборе особая: строки НЕ идут на витрину — `parse_live.py`
складывает их в эталонный набор (пары + время + канонические английские
написания), которым подтверждается «угаданный» live и сверяются имена.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from . import Program, register

DOMAIN = "flashscore.mobi"
TZ = "Europe/Paris"                     # CET/CEST — см. шапку

#: языковые версии эталона (этап 6е, A2): те же матчи и те же `fs_id`, а
#: имена — как их пишет местная пресса: `Τζένοα`, `Дженоа`, `Genova`. По
#: `fs_id` словарь учит «местное → английское» без угадывания по буквам.
#: Проба 03.09 из GitHub (12 адресов): открылись эти 9; `m.flashscore.co.il`
#: и `m.flashscore.rs` не существуют — иврит и сербский идут таблицами
#: экзонимов. Значение — язык, если страница его не назвала в `<html lang>`.
#: Время у локалей местное и нам не нужно — берём только имена.
LOCALES = {
    "m.flashscore.gr": "el", "m.flashscore.bg": "bg", "m.eredmenyek.com": "hu",
    "m.flashscore.ro": "ro", "m.flashscore.com.tr": "tr", "m.flashscore.pl": "pl",
    "m.flashscore.ru": "ru", "m.flashscore.ua": "uk", "m.livesport.cz": "cs",
    # вторая проба 03.09: сербохорватский — арена-сетки, mojtv, rtcg, rtrs
    # пишут именно так; иврита и сербской кириллицы у livesport в mobi нет
    "m.rezultati.com": "hr",
    # третья проба 25.09 (идея владельца: «языки источников знаем — пусть
    # словарь заполняется сам»): проверены с сервера, все отдали расписание.
    # Норвежского, албанского и ивритского у flashscore в mobi нет вовсе —
    # `flashscore.co.il` уводит на международную версию, их написания
    # по-прежнему ведём руками в `data/aliases.json`
    "m.flashscore.sk": "sk", "m.flashscore.de": "de", "m.flashscore.pt": "pt",
    "m.flashscore.it": "it", "m.flashscore.fr": "fr", "m.flashscore.es": "es",
    "m.flashscore.nl": "nl", "m.flashscore.se": "sv", "m.flashscore.dk": "da",
}

_ZONE = ZoneInfo(TZ)
#: блок матча: время (или живая минута), пара, ссылка со статусом
#: у ссылки матча бывает хвост запроса (`/match/pdmRhdwH/?s=1` — появился
#: 02.09 и сломал разбор, поймано обкаткой) — берём id до слэша, хвост не важен
_ROW = re.compile(
    r"<span(?: class=\"(?P<live>live)\")?>(?P<time>[^<]{1,7})</span>"
    r"(?P<pair>[^<]{3,120}?)"
    # у языковых версий слово в пути своё: `/match/` (en, el, bg),
    # `/meci/` (ro), `/mac/` (tr) — само слово не важно, важен id за ним
    r"<a href=\"/[a-z\-]+/(?P<id>[^/\"?]+)/(?:\?[^\"]*)?\" "
    r"class=\"(?P<status>sched|live|fin)\"")
_LANG = re.compile(r"<html[^>]* lang=.([A-Za-z-]+).")   # <html lang="el">
_H4 = re.compile(r"<h4>(?P<league>[^<]{3,120})")
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
#: у тенниса и баскетбола к имени приклеен код страны: `Monfils G. (Fra)`,
#: `Liaoning (Chn)`, `Medvedev D. (Wrl)` — сравнению имён он только мешает
_COUNTRY_TAG = re.compile(r"\s*\([A-Za-z]{2,3}\)\s*$")


def _sport_from_url(url: str) -> str:
    """Раздел сайта в адресе — вид спорта (этап 6б: баскет и теннис в
    эталоне). У локалей раздел зовётся по-своему: `basketbol` (tr),
    `kosarka` (hr), `basketbal` (cs), `kosarlabda` (hu)."""
    if any(w in url for w in ("/basketball", "/basketbol", "/kosarka",
                              "/basketbal", "/kosarlabda")):
        return "Basketball"
    if any(w in url for w in ("/tennis", "/tenis", "/tenisz")):
        return "Tennis"
    return "Soccer"


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    day = day or _date.today()
    sport = _sport_from_url(url)
    # язык страницы (этап 6е, A2): у локалей `m.flashscore.gr` те же fs_id,
    # что у английской, — по нему словарь учит «Τζένοα» = «Genoa» без
    # угадывания по буквам. Английская отдаёт `en`
    lm = _LANG.search(html[:2000])
    lang = (lm.group(1).split("-")[0].lower() if lm
            else LOCALES.get(urlsplit(url).netloc, "en"))
    out: list[Program] = []
    league = ""
    # идём по документу: заголовки лиг перемежаются строками матчей
    events = sorted(
        [(m.start(), "h4", m) for m in _H4.finditer(html)] +
        [(m.start(), "row", m) for m in _ROW.finditer(html)])
    for _, kind, m in events:
        if kind == "h4":
            league = " ".join(m.group("league").split()).strip()
            continue
        pair = " ".join(m.group("pair").split()).strip(" - ")
        if " - " not in pair:
            continue
        home, _, away = pair.partition(" - ")
        status = m.group("status")
        hm = _TIME.match(m.group("time").strip())
        if hm:
            begin = datetime(day.year, day.month, day.day, int(hm.group(1)),
                             int(hm.group(2)), tzinfo=_ZONE)
        elif status == "live":
            # у идущего матча вместо времени минута (`8'`) — старт
            # восстанавливать не из чего, ставим «сейчас», допуска эталона
            # (±3 часа) этого достаточно
            begin = datetime.now(tz=_ZONE)
        else:
            continue
        home = _COUNTRY_TAG.sub("", home.strip())
        away = _COUNTRY_TAG.sub("", away.strip())
        out.append(Program(
            channel_raw="flashscore", title=pair,
            start=begin,
            raw_time=begin.strftime("%H:%M"),
            league_raw=league[:120],
            sport_raw=sport,
            live_raw="live" if status == "live" else "",
            match_raw=f"{home} - {away}",
            source_url=url,
            extra={"day": begin.date().isoformat(),
                   "fs_id": m.group("id"), "status": status, "lang": lang},
        ))
    return out


# у языковых версий разметка та же — тот же разбор под их доменами
for _domain in LOCALES:
    register(_domain)(parse)

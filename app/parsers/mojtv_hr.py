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
Телегид-день идёт 06:00 → 06:00: времена до 6 утра — следующая дата.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

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


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    gd = _GRID_DATE.search(html)
    if gd:
        day = _date(int(gd.group(3)), int(gd.group(2)), int(gd.group(1)))
    day = day or _date.today()
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
                d = day + timedelta(days=1) if int(hm.group(1)) < 6 else day
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
    return out

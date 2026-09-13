# -*- coding: utf-8 -*-
"""tvarenaprogram.com — рамка Arena Sport для Боснии/Хорватии/Словении,
уровень B (разметка HTML, «slider»).

Один движок обслуживает несколько стран: `tvarenaprogram.com/live_v2/ba`
(Босния, 12 каналов), `tvarenasport.hr/wp-content/tv-program.php` (Хорватия,
10 каналов), предположительно и `.si`. Сербский `tvarenasport.com` — другой
движок (инлайн-JSON), у него свой модуль.

Разметка (копии 31.08 в `recon/raw_manual/`):

    section.tv-scheme-chanel                 один канал
      .tv-scheme-chanel-header-logo img      имя канала только в имени файла
                                             логотипа: chanel-a1p, chanel-05…
      .tv-scheme-days > a[data-slider-index] 7 дней, дата третьим span: `31.08`
      .tv-scheme-new-slider-item             7 штук, по порядку = дни
        .slider-content                      одна передача
          .slider-content-top span           время `06:00`
          .slider-content-middle span        вид спорта (`Fudbal`) или имя
                                             передачи, если это не матч
          .slider-content-bottom p           пара команд: `BSK - Sloga`
          .slider-content-bottom span        лига: `WWIN liga BiH`
          .live-title … `Uživo`              маркер эфира; нет — запись

Что важно:

* **`Uživo` — честный флаг** (в копии BA 168 из 1308 блоков): переводим в
  маркер `uživo` из `data/markers.json`, как у сербского сайта.
* Дата в днях без года (`31.08`) — год берём от дня обхода, с поправкой на
  стык декабрь/январь.
* Дни календарные: следующий день начинается с `00:00`, переносить время
  через полночь не нужно.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, register

DOMAIN = "tvarenaprogram.com"
TZ = "Europe/Sarajevo"

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_DDMM = re.compile(r"^(\d{1,2})\.(\d{1,2})\.?$")
_ICON = re.compile(r"/([\w-]+)\.(?:png|jpg|svg|webp)", re.I)

#: имя файла логотипа → имя канала (в тексте страницы имён нет вообще)
_ICON_NAMES = [
    (re.compile(r"^chanel-a(\d+)p$"), "Arena Premium {}"),
    (re.compile(r"^arena(\d+)premium$"), "Arena Premium {}"),
    (re.compile(r"^chanel-0*(\d+)$"), "Arena Sport {}"),
    (re.compile(r"^arenasport(\d+)$"), "Arena Sport {}"),
]


def _channel_name(icon_src: str) -> str:
    m = _ICON.search(icon_src or "")
    slug = m.group(1) if m else (icon_src or "").strip()
    for rx, pattern in _ICON_NAMES:
        hit = rx.match(slug)
        if hit:
            return pattern.format(int(hit.group(1)))
    return slug  # незнакомый логотип: отдать слаг, пусть попадёт на проверку


def _year_for(d: int, mo: int, anchor: _date) -> _date | None:
    """Дата `дд.мм` без года: берём год дня обхода, чиня стык декабря."""
    for year in (anchor.year, anchor.year + 1, anchor.year - 1):
        try:
            candidate = _date(year, mo, d)
        except ValueError:
            continue
        if abs((candidate - anchor).days) <= 180:
            return candidate
    return None


@register(DOMAIN)
@register("tvarenasport.hr")
@register("tvarenasport.ba")
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    anchor = day or datetime.now(ZoneInfo(tz or TZ)).date()
    zone = ZoneInfo(tz or TZ)

    out: list[Program] = []
    for section in HTMLParser(html).css("section.tv-scheme-chanel"):
        icon = section.css_first(".tv-scheme-chanel-header-logo img")
        channel = _channel_name(icon.attributes.get("src", "") if icon else "")
        if channels and channel not in channels:
            continue

        # индекс слайда → дата из списка дней этого же канала
        dates: dict[int, _date] = {}
        for a in section.css(".tv-scheme-days a[data-slider-index]"):
            spans = [s.text(strip=True) for s in a.css("span")]
            dm = next((m for t in spans if (m := _DDMM.match(t))), None)
            if dm is None:
                continue
            d = _year_for(int(dm.group(1)), int(dm.group(2)), anchor)
            if d is not None:
                try:
                    dates[int(a.attributes.get("data-slider-index", ""))] = d
                except ValueError:
                    pass

        for idx, item in enumerate(section.css(".tv-scheme-new-slider-item")):
            d = dates.get(idx)
            for block in item.css(".slider-content"):
                top = block.css_first(".slider-content-top span")
                hm = _HHMM.match(top.text(strip=True) if top else "")
                bottom = block.css_first(".slider-content-bottom")
                title_node = bottom.css_first("p") if bottom else None
                title = title_node.text(strip=True) if title_node else ""
                if not title or not hm or d is None:
                    continue

                middle = block.css_first(".slider-content-middle span")
                league = next(
                    (s.text(strip=True) for s in bottom.css("span")
                     if not (s.attributes.get("class") or "")), "")
                live = block.css_first(".live-title") is not None

                out.append(Program(
                    channel_raw=channel, title=title,
                    start=datetime(d.year, d.month, d.day,
                                   int(hm.group(1)), int(hm.group(2)),
                                   tzinfo=zone),
                    raw_time=top.text(strip=True),
                    league_raw=league,
                    sport_raw=middle.text(strip=True) if middle else "",
                    live_raw="uživo" if live else "",
                    match_raw=title, source_url=url,
                    extra={"day": d.isoformat()},
                ))
    return out


# ---------------------------------------------------------------------------
# tvarenasport.si — та же семья Arena, но движок третий: «вертикальная сетка».
# Одна страница `/tv-spored/` = ТЕКУЩИЙ день, 5 каналов (Arena Sport 1–4 и 8).
# Остальные дни грузятся POST-ом `ajax/ajax_tv_guide.php` со скрытыми id
# каналов — не ходим: обход ежедневный, текущего дня достаточно.
#
#     div.vertical_program_scheme.arenasportN     канал (имя — слаг в классе)
#       .vertical_program_scheme_record           одна передача
#         .first_column                           ` 8:25` (бывает без нуля)
#         .status span.live_icon                  `v živo` — эфир
#         .status span.first_icon                 `prvič` — премьера, не эфир
#         span.sport / .title / .event            спорт, матч, лига
#
# Дата дня — в активной вкладке `#tv_guide_dates li.active a[data-date_time]`.
# ---------------------------------------------------------------------------

_SI_SLUG = re.compile(r"\barenasport(\d+)\b")


@register("tvarenasport.si")
def parse_si(html: str, *, day: _date | None = None, tz: str | None = None,
             url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or "Europe/Ljubljana")
    tree = HTMLParser(html)

    page_day = None
    active = tree.css_first("#tv_guide_dates li.active a[data-date_time]") \
        or tree.css_first("#tv_guide_dates a[data-date_time]")
    if active:
        try:
            page_day = _date.fromisoformat(active.attributes.get("data-date_time", ""))
        except ValueError:
            pass
    if page_day is None:
        page_day = day or datetime.now(zone).date()

    out: list[Program] = []
    for block in tree.css("div.vertical_program_scheme"):
        slug = _SI_SLUG.search(block.attributes.get("class") or "")
        channel = f"Arena Sport {int(slug.group(1))}" if slug else "Arena Sport"
        if channels and channel not in channels:
            continue
        for rec in block.css(".vertical_program_scheme_record"):
            t = rec.css_first(".first_column")
            hm = _HHMM.match(t.text(strip=True) if t else "")
            title_node = rec.css_first(".title")
            title = title_node.text(strip=True) if title_node else ""
            if not title or not hm:
                continue
            sport_node = rec.css_first("span.sport")
            event = rec.css_first(".event")
            live = rec.css_first(".status .live_icon")
            out.append(Program(
                channel_raw=channel, title=title,
                start=datetime(page_day.year, page_day.month, page_day.day,
                               int(hm.group(1)), int(hm.group(2)), tzinfo=zone),
                raw_time=t.text(strip=True),
                league_raw=event.text(strip=True) if event else "",
                sport_raw=sport_node.text(strip=True) if sport_node else "",
                live_raw="v živo" if live else "",
                match_raw=title, source_url=url,
                extra={"day": page_day.isoformat()},
            ))
    return out

# -*- coding: utf-8 -*-
r"""kanal1sport.sk — Словакия, каналы Kanal 1 Sport и Kanal 1 Xtra.

Это бывший `arenatv.sk`: старый адрес уводит редиректом сюда, и сайт был
записан в «закрытые» зря — он живой. С сервера его страницы поначалу
приходили без сетки, а файлы темы отвечали таймаутом; помогло взять
страницу **браузером с ожиданием догрузки** (`needs_js=1`): расписание
приезжает отдельным запросом уже после загрузки.

    https://www.kanal1sport.sk/tv-program/

Одна страница держит две недели вперёд, поэтому дата в адрес не нужна:

    <div class="item" data-from="1788246000" data-to="1788247800" data-category="1">
      <div class="time">09:00 - 09:30</div>
      <div class="title">Motoride</div>
      <div class="description">Novinky a testy pre motorkárov</div>
      <div class="logo"><img src="…/logos/kanal-1-sport.png"></div>
      <div class="live"><span>Vysielame</span></div>

Время берём из `data-from` — это секунды, и они не зависят от того, как
сайт нарисовал часы. Канал — из имени файла логотипа: у обоих каналов
разметка одинаковая, отличается только картинка. Пометку `Vysielame`
(«вещаем») сайт ставит всем строкам подряд, эфиром её считать нельзя —
первый показ пары определяем сами.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timezone
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "kanal1sport.sk"
TZ = "Europe/Bratislava"

_LOGO = re.compile(r"/logos/([a-z0-9-]+)\.png", re.I)
NAMES = {"kanal-1-sport": "Kanal 1 Sport", "kanal-1-xtra": "Kanal 1 Xtra"}


def _pair(text: str) -> str:
    tail = text.split(":", 1)[1] if ":" in text else text
    for sep in (" - ", " – ", " vs ", " x "):
        if sep in tail:
            home, _, away = tail.partition(sep)
            if home.strip() and away.strip():
                return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)

    out: list[Program] = []
    for item in tree.css("div.item"):
        stamp = item.attributes.get("data-from") or ""
        head = item.css_first("div.title")
        if not stamp.isdigit() or not head:
            continue
        title = " ".join(head.text().split())
        if not title:
            continue
        logo = item.css_first("div.logo img")
        got = _LOGO.search((logo.attributes.get("src") or "") if logo else "")
        channel = NAMES.get(got.group(1).lower(), got.group(1)) if got \
            else "Kanal 1 Sport"
        if channels and channel not in channels:
            continue
        about = item.css_first("div.description")
        about = " ".join(about.text().split()) if about else ""
        start = datetime.fromtimestamp(int(stamp), tz=timezone.utc).astimezone(zone)
        out.append(Program(
            channel_raw=channel, title=title, start=start,
            raw_time=start.strftime("%H:%M"), description=about[:300],
            match_raw=_pair(title) if _pair(title).strip() else _pair(about),
            source_url=url, extra={"day": start.date().isoformat()},
        ))
    return mark_first_show(out, "priamy prenos")

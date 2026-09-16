# -*- coding: utf-8 -*-
"""Адрес расписания на нужный день.

В закладках владельца у половины источников адрес содержит дату того дня,
когда закладку сделали: `protv.ro/program?day=5-4-2025`, `bbc.co.uk/.../2024/11/19`.
По такому адресу сайт отдаёт прошлогоднюю страницу — а мы записывали её как
«расписания нет». Поэтому у источника есть колонка `url_pattern`: тот же адрес,
где дата заменена метками.

Метки даты пишутся как в разведке (`recon/deep_report.md`) — заглавными,
и целиком, и по частям:

    https://nova.bg/schedule/index/{channel_id}/{YYYY}/{MM}/{DD}/
    https://www.teleman.pl/program-tv/stacje/{slug}?date={YYYY-MM-DD}
    https://ntvplus.tv/tv/{genre}/?date={DD.MM.YYYY}

Любая скобка, внутри которой только буквы Y, M, D и разделители, считается
датой: `{YYYY}`, `{DD}`, `{YYYY-MM-DD}`, `{DD.MM.YYYY}`, `{MM/DD/YYYY}`.
`{UNIXDAY}` — начало суток в секундах (`cosmotetv.gr`), `{UNIXDAYEND}` —
конец тех же суток (ручка EPG Magenta). `{KYIVOFF}` — смещение Киева на
этот день, закодированное для адреса (`%2B0300` летом, `%2B0200` зимой):
`sporteventz.com` отдаёт время в поясе `client_tz_offset` из запроса, и
жёсткое `+0300` после перевода стрелок 25.10 разъехалось бы с Киевом
(C1 аудита).
Остальные метки (`{channel_id}`, `{slug}`, `{genre}`, `{lang}`) подставляются
из аргументов; чего не передали — остаётся в адресе как есть, чтобы пропажу
было видно, а не молча получить битую ссылку.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_MARK = re.compile(r"\{([^{}]+)\}")
_DATE_ONLY = re.compile(r"^[YMD][YMD\-./ :]*$")


def _date_mark(mark: str, d: _date) -> str:
    """`YYYY-MM-DD` → `2026-08-29`. Разделители сохраняются как есть."""
    out = mark
    for part, value in (("YYYY", f"{d.year}"), ("YY", f"{d.year % 100:02d}"),
                        ("MM", f"{d.month:02d}"), ("DD", f"{d.day:02d}"),
                        ("M", str(d.month)), ("D", str(d.day))):
        out = out.replace(part, value)
    return out


#: день недели по-турецки: `beinsports.com.tr/yayin-akisi/{канал}/{sali}`
#: — у них в адресе не дата, а название дня
_WEEKDAY_TR = ("pazartesi", "sali", "carsamba", "persembe", "cuma",
               "cumartesi", "pazar")

#: хвост адреса дня у `tvguidetonight.com.au`: сегодня — без хвоста,
#: завтра — `/tomorrow`, дальше — имя дня недели (`/friday`)
_WEEKDAY_EN = ("monday", "tuesday", "wednesday", "thursday", "friday",
               "saturday", "sunday")



def resolve(url_pattern: str | None, base_url: str = "",
            day: _date | None = None, **marks: str) -> str:
    """Адрес расписания на день `day` (по умолчанию — сегодня).
    Шаблона нет — возвращаем `base_url` как есть."""
    if not url_pattern:
        return base_url
    d = day or _date.today()

    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name == "UNIXDAY":
            # начало суток в секундах: `cosmotetv.gr/program?date=1788642000`
            return str(int(datetime(d.year, d.month, d.day,
                                    tzinfo=timezone.utc).timestamp()))
        if name == "UNIXDAYEND":
            # конец тех же суток: ручка EPG Magenta ждёт `from={UNIXDAY}&
            # to={UNIXDAYEND}` и окна шире суток не принимает
            return str(int(datetime(d.year, d.month, d.day,
                                    tzinfo=timezone.utc).timestamp()) + 86399)
        if name == "UNIXMSDAY":
            # начало суток в миллисекундах: ручка United Cloud (`sportklub.hr`)
            # просит fromTime/toTime в мс
            return str(int(datetime(d.year, d.month, d.day,
                                    tzinfo=timezone.utc).timestamp()) * 1000)
        if name == "UNIXMSWEEK":
            # конец окна через неделю, в мс: одним запросом на канал та же
            # ручка отдаёт всю опубликованную сетку (у Sport Klub ~4 дня, 16.09)
            return str((int(datetime(d.year, d.month, d.day,
                                     tzinfo=timezone.utc).timestamp())
                        + 7 * 86400) * 1000 - 1)
        if name == "KYIVOFF":
            # полдень — чтобы не попасть в ночной час перевода стрелок
            off = datetime(d.year, d.month, d.day, 12,
                           tzinfo=ZoneInfo("Europe/Kyiv")).utcoffset()
            return f"%2B{int(off.total_seconds() // 3600):02d}00"
        if name == "WEEKDAY_TR":
            return _WEEKDAY_TR[d.weekday()]
        if name == "AU_DAYPATH":
            today = _date.today()
            if d == today:
                return ""
            if d == today + timedelta(days=1):
                return "/tomorrow"
            return "/" + _WEEKDAY_EN[d.weekday()]
        if _DATE_ONLY.match(name):
            return _date_mark(name, d)
        return marks.get(name, m.group(0))

    return _MARK.sub(sub, url_pattern)

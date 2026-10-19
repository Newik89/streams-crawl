# -*- coding: utf-8 -*-
"""tv.dir.bg — Болгария: телегид портала dir.bg (bTV Action, bTV, Ring.bg, БНТ).

Слово владельца 18.10.2026: «нужно расписание bTV Action — важный канал».
Сам `btv.bg` закрыт Cloudflare, поэтому расписание берём с телегида dir.bg;
каналы выбрал владелец: bTV Action, bTV, Ring.bg (bTV Sport), BNT 1–4.

**Кухня сайта** (проверено с сервера 18.10):

    GET  https://tv.dir.bg/init
         → {"csrfToken": "<40 знаков>"} + куки XSRF-TOKEN, dir_session
    POST https://tv.dir.bg/load/programs?channel=95&day=2026-10-22
         тело `_token=<csrfToken>`, заголовок X-Requested-With: XMLHttpRequest
         → {"status": true, "html": "…"}

Канал и день сайт читает ИЗ АДРЕСА, в теле только ключ; один ключ и куки
годятся на много запросов подряд. В карточке источника: `warmup_url` =
`/init`, `post_fields = {"_token": "{WARMKEY}"}`, адрес с номером канала —
в `page_url` каждого канала (`scripts/add_dirbg.py`; ключ по хосту —
`app/fetch.py`, `WARMKEY_PATTERNS`).

**Разметка** поля `html` (описания, жанра и даты у строки нет):

    div.panels > div.panel                  — одни телесутки; панелей три:
      p.broadcast-item-name                   `21.10` | `Днес` | `Утре`
      div.broadcast-item                    — одна передача
        img[alt="Екоавтомобили"]              название без хвоста сериала
        div.broadcast-time                    `19:45`
        div.broadcast-title[data-id]          `ПРЯКО: УЕФА Шампионска лига: Комо - Манчестър Юнайтед`
                                              `Екоавтомобили , сезон 2 , епизод 7`

Ответ на день `D` несёт панели `D-1`, `D`, `D+1` (на запрос 22.10 пришли
21.10, 22.10, 23.10; на 19.10 — «Днес», «Утре», 20.10 — сняты 18.10).

Правила разбора по порядку:

1. Ответ — JSON, разметка в поле `html`; `status` ложный или поля нет —
   пусто. Не JSON — считаем, что дали уже саму разметку.
2. Канал — по `?channel=<id>` из адреса запроса: `NAMES` (имена — как сайт
   пишет в `alt` на `/channels`, `list_channels`). Неизвестный номер —
   канал `tv.dir.bg`, строки не теряем. Фильтр `channels` карточки.
3. День запроса — `&day=ГГГГ-ММ-ДД` из адреса; нет — `day` от обхода; нет —
   сегодня по часам Софии.
4. Панель — телесутки. Подпись `ДД.ММ` → дата (год — ближайший к дню
   запроса); словесная подпись («Днес», «Утре») — по соседней панели с
   датой: панели идут подряд по дням. Дат нет ни у одной — средняя панель
   считается днём запроса. Берём ТОЛЬКО панель дня запроса: соседние дни
   приходят своими запросами, иначе каждая передача шла бы трижды.
5. Время `ЧЧ:ММ`, телесутки с ~06:00: время, меньшее предыдущего, — уже
   следующие календарные сутки (`daytime.walk_day`). Пояс Europe/Sofia.
6. Название — текст `.broadcast-title` одной строкой, запятые хвоста сериала
   прижаты (`Екоавтомобили, сезон 2, епизод 7`); хвост `, сезон N, епизод M`
   снимается перед разбором пары (`strip_series`).
7. Эфир — приставка `ПРЯКО:` в начале названия: пометка самого сайта
   (`site_says`, слово «пряко» из `data/markers.json`), приставка из
   названия снимается. Без приставки сайт эфира не обещает: маркера нет,
   разбор снимет строку как повтор/запись («нет маркера»).
8. Лига и пара — по ПОСЛЕДНЕМУ «: »: слева турнир (`league_raw`), справа
   «Дом - Гости». Пара берётся только там, где перед ней стоит турнир с
   двоеточием ИЛИ есть приставка ПРЯКО: сериал с дефисом в названии
   («Костенурките нинджа - нова мутация») пары не даёт; матч без ПРЯКО
   («УЕФА Шампионска лига: Астън Вила - Викинг», 01:15) пару даёт — его
   снимет разбор как запись, и книге это видно как «нет».
9. `match_raw` = «Дом - Гости» только при двух непустых именах, иначе " ".
   Студия («Студио "УЕФА Шампионска лига"») пары не имеет — её снимают
   стоп-слова разбора. `extra["day"]` — календарная дата начала,
   `source_url` — адрес запроса.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, timedelta

from selectolax.parser import HTMLParser

from .. import daytime
from . import Program, register, site_says

DOMAIN = "tv.dir.bg"
TZ = "Europe/Sofia"

#: правило 2: номер канала на сайте → имя, как оно стоит в `alt` на
#: `https://tv.dir.bg/channels` (18.10.2026); семь каналов выбрал владелец
NAMES = {
    "95": "bTV Action",
    "61": "bTV",
    "59": "Ring.bg (bTV Sport)",
    "57": "BNT1 (БНТ1)",
    "99": "BNT2 (БНТ2)",
    "82": "BNT3 (БНТ3)",
    "64": "BNT4 (БНТ4)",
}

_CHANNEL = re.compile(r"[?&]channel=(\d+)")
_DAY = re.compile(r"[?&]day=(\d{4}-\d{2}-\d{2})")
_LINK_ID = re.compile(r"/programa/(\d+)")

#: правило 4: подпись панели `21.10`
_DDMM = re.compile(r"^(\d{1,2})\.(\d{1,2})\.?$")

_HHMM = re.compile(r"^\d{1,2}:\d{2}$")

#: правило 6: хвост сериала `, сезон 3, епизод 12` (бывает и один из двух)
_SERIES_TAIL = re.compile(r"(?:\s*,\s*сезон\s*\d+)?(?:\s*,\s*епизод\s*\d+)?\s*$",
                          re.I)

#: правило 7: приставка эфира
_LIVE_PREFIX = re.compile(r"^ПРЯКО\s*:\s*", re.I)
LIVE_WORD = "пряко"

#: правило 8: дефис пары — с пробелами по обе стороны (дефис внутри слова
#: не делит: «Нордшеланд» и «Ring.bg» целы)
_SEPS = (" - ", " – ", " — ")


def strip_series(title: str) -> str:
    """Правило 6: `Костенурките нинджа - нова мутация, сезон 3, епизод 12` →
    `Костенурките нинджа - нова мутация`."""
    return _SERIES_TAIL.sub("", title).strip()


def clean_title(text: str) -> str:
    """Правило 6: текст заголовка одной строкой, запятые хвоста прижаты."""
    text = " ".join(text.split())
    return text.replace(" ,", ",")


def split_title(title: str) -> tuple[bool, str, str]:
    """Правила 7–9: название → (эфир, лига, «Дом - Гости» или " ").

    Приставка ПРЯКО снята, хвост сериала снят, пара — после последнего «: ».
    """
    live = bool(_LIVE_PREFIX.match(title))
    body = strip_series(_LIVE_PREFIX.sub("", title, count=1))
    league, colon, tail = body.rpartition(": ")
    if not colon:                       # турнира с двоеточием нет
        league, tail = "", body
    if not colon and not live:          # правило 8: без турнира и без ПРЯКО — не матч
        return live, "", " "
    for sep in _SEPS:
        if sep in tail:
            home, _, away = tail.partition(sep)
            home, away = home.strip(), away.strip()
            if home and away:           # правило 9
                return live, league.strip(), f"{home} - {away}"
            break
    return live, league.strip(), " "


def list_channels(html: str) -> dict[str, str]:
    """Страница `/channels`: номер канала → имя из `alt` логотипа
    (`div.channel_cont img[alt]`, ссылка `a.channel_link[href=/programa/<id>]`).
    Нужна, чтобы сверять `NAMES` с сайтом, в обход не ходит."""
    out: dict[str, str] = {}
    for block in HTMLParser(html).css("div.channel_cont"):
        link = block.css_first("a.channel_link")
        img = block.css_first("img")
        got = _LINK_ID.search(link.attributes.get("href") or "") if link else None
        alt = " ".join((img.attributes.get("alt") or "").split()) if img else ""
        if got and alt:
            out.setdefault(got.group(1), alt)
    return out


def _page_html(text: str) -> str:
    """Правило 1: JSON `{"status": true, "html": "…"}` → разметка."""
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return text                     # уже разметка
    try:
        data = json.loads(stripped)
    except ValueError:
        return ""
    if not isinstance(data, dict) or not data.get("status", True):
        return ""
    html = data.get("html")
    return html if isinstance(html, str) else ""


def request_day(url: str, day: _date | None, zone: str) -> _date:
    """Правило 3: день запроса — из адреса, иначе от обхода, иначе сегодня."""
    got = _DAY.search(url or "")
    if got:
        try:
            return _date.fromisoformat(got.group(1))
        except ValueError:
            pass
    return day or daytime.today(zone)


def _label_date(label: str, near: _date) -> _date | None:
    """Правило 4: `21.10` → дата с годом, ближайшим к дню запроса."""
    got = _DDMM.match(label.strip())
    if not got:
        return None
    dd, mm = int(got.group(1)), int(got.group(2))
    best: _date | None = None
    for year in (near.year - 1, near.year, near.year + 1):
        try:
            candidate = _date(year, mm, dd)
        except ValueError:
            continue
        if best is None or abs((candidate - near).days) < abs((best - near).days):
            best = candidate
    return best


def panel_days(labels: list[str], asked: _date) -> list[_date]:
    """Правило 4: подписи панелей → даты. Панели идут подряд по дням:
    словесная подпись берёт дату от ближайшей панели с числом; чисел нет —
    средняя панель = день запроса."""
    dates: list[_date | None] = [_label_date(x, asked) for x in labels]
    if not any(dates):
        middle = len(labels) // 2
        return [asked + timedelta(days=i - middle) for i in range(len(labels))]
    known = [i for i, d in enumerate(dates) if d is not None]
    out: list[_date] = []
    for i, d in enumerate(dates):
        if d is None:
            j = min(known, key=lambda k: abs(k - i))
            d = dates[j] + timedelta(days=i - j)
        out.append(d)
    return out


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = tz or TZ
    page = _page_html(html)
    if not page:
        return []

    # правило 2
    got = _CHANNEL.search(url or "")
    channel = NAMES.get(got.group(1), DOMAIN) if got else DOMAIN
    if channels and channel not in channels:
        return []

    asked = request_day(url, day, zone)                     # правило 3
    tree = HTMLParser(page)
    panels = tree.css("div.panel")
    labels = []
    for panel in panels:
        name = panel.css_first("p.broadcast-item-name")
        labels.append(" ".join(name.text().split()) if name else "")
    days = panel_days(labels, asked)                        # правило 4

    out: list[Program] = []
    for panel, panel_day in zip(panels, days):
        if panel_day != asked:
            continue
        rows: list[tuple[str, str]] = []
        for item in panel.css("div.broadcast-item"):
            when = item.css_first("div.broadcast-time")
            name = item.css_first("div.broadcast-title")
            raw = when.text(strip=True) if when else ""
            title = clean_title(name.text()) if name else ""
            if not title or not _HHMM.match(raw):
                continue
            rows.append((raw, title))
        starts = daytime.walk_day([r for r, _ in rows], panel_day, zone)   # правило 5
        for (raw, title), start in zip(rows, starts):
            if start is None:
                continue
            live, league, pair = split_title(title)         # правила 7–9
            program = Program(
                channel_raw=channel,
                title=_LIVE_PREFIX.sub("", title, count=1),
                start=start, raw_time=raw,
                league_raw=league[:120], match_raw=pair,
                source_url=url, extra={"day": start.date().isoformat()},
            )
            if live:
                site_says(program, True, LIVE_WORD)
            out.append(program)
    return out

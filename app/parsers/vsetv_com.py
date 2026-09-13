# -*- coding: utf-8 -*-
r"""vsetv.com — русскоязычная сетка (Setanta, Матч ТВ); цифры времени спрятаны
картинками.

Разметка простая — пары `div.time` + `div.prname2`:

    <div class="time">19:<img src="/pic/cv.gif"><img src="/pic/cv.gif"></div>
    <div class="prname2">Футбол. Чемпионат Англии. Премьер-лига. Борнмут - Эвертон.</div>

Сложность одна: **часть цифр сайт заменяет картинками**, и имя файла меняется
от запроса к запросу (`cv.gif`, `n6.gif`, `tb.gif`). Внутри одной страницы
соответствие постоянное: одна картинка — одна цифра.

Картинки мы не скачиваем и не распознаём. Цифры вычисляются из самого
расписания: в сетке канала время идёт по возрастанию, минуты кратны пяти,
часы меньше 24. Скрытых картинок на странице обычно одна-две, поэтому
перебрать все их значения (`10^k`) и оставить единственный вариант, при
котором сетка складывается в правильный день, — дело нескольких тысяч
проверок.

Если однозначного ответа нет (страница слишком короткая), берём вариант, где
раньше начинается день: перепутать время лучше не наугад, а хотя бы
предсказуемо. Такие строки видно по `raw_time` — там остаются знаки `?`.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from itertools import product
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from . import Program, mark_first_show, register

DOMAIN = "vsetv.com"
TZ = "Europe/Kyiv"

_DAY = re.compile(r"day_(\d{4})-(\d{2})-(\d{2})")
_CHANNEL = re.compile(r"channel_(\d+)")
_PIC = re.compile(r"/pic/([a-z0-9]+)\.gif", re.I)
#: сколько разных картинок готовы перебрать: 4 — это 10 000 вариантов
MAX_UNKNOWN = 4


def _slots(node) -> list[str]:
    """Метка времени как список знаков: цифра, `:` или имя картинки.

    `19:<cv><cv>` → `['1', '9', ':', '#cv', '#cv']`

    Имя картинки помечаем решёткой: у сайта попадаются имена из одних цифр
    (`36.gif`), и без пометки такой слот выглядел бы готовой цифрой.
    """
    out: list[str] = []
    for part in node.iter(include_text=True):
        name = part.tag
        if name == "img":
            got = _PIC.search(part.attributes.get("src") or "")
            out.append("#" + got.group(1) if got else "#?")
        elif name == "-text":
            out.extend(ch for ch in part.text() if ch.isdigit() or ch == ":")
    return out


def _read(slots: list[str], answer: dict[str, str]) -> tuple[int, int] | None:
    """Метка с подставленными цифрами → часы и минуты."""
    text = "".join(answer.get(s, s) for s in slots)
    if not re.fullmatch(r"\d{1,2}:\d{2}", text):
        return None
    hour, minute = (int(x) for x in text.split(":"))
    return (hour, minute) if hour < 24 and minute < 60 else None


def _fits(times: list[tuple[int, int]]) -> bool:
    """Годится ли расшифровка: день идёт по возрастанию с одним переходом
    через полночь (сетка начинается утром).

    Кратность минут пяти в отбор не входит: у «Суспільне Спорт» попадается
    `09:02`. Она учитывается позже, при выборе лучшего из подошедших.
    """
    turns = 0
    for was, now in zip(times, times[1:]):
        if now < was:
            turns += 1
            if turns > 1 or now[0] > 6:
                # падение времени бывает один раз — на переходе в ночь;
                # и после него это именно ночные часы, а не середина дня
                return False
    return True


def decode(marks: list[list[str]]) -> dict[str, str]:
    """Какая картинка какой цифрой была. Пустой ответ — не разгадали."""
    unknown = sorted({s for mark in marks for s in mark if s.startswith("#")})
    if not unknown:
        return {}
    if len(unknown) > MAX_UNKNOWN:
        return {}
    good: list[dict[str, str]] = []
    for guess in product("0123456789", repeat=len(unknown)):
        answer = dict(zip(unknown, guess))
        times = [_read(mark, answer) for mark in marks]
        if any(t is None for t in times):
            continue
        if not _fits(times):                       # type: ignore[arg-type]
            continue
        good.append(answer)
    if not good:
        return {}

    def odd(answer: dict[str, str]) -> tuple[int, tuple[int, int]]:
        """Чем меньше некруглых минут, тем правдоподобнее расшифровка.
        При равенстве берём вариант, где день начинается раньше."""
        times = [_read(mark, answer) for mark in marks]
        rough = sum(1 for t in times if t and t[1] % 5)
        return rough, (_read(marks[0], answer) or (99, 99))

    return min(good, key=odd)


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    zone = ZoneInfo(tz or TZ)
    tree = HTMLParser(html)

    got = _DAY.search(url or "")
    base = _date(int(got.group(1)), int(got.group(2)), int(got.group(3))) \
        if got else (day or _date.today())

    logo = tree.css_first("img.pic")
    channel = (logo.attributes.get("alt") or "").strip() if logo else ""
    if not channel:
        num = _CHANNEL.search(url or "")
        channel = f"vsetv {num.group(1)}" if num else "vsetv"
    if channels and channel not in channels:
        return []

    # строки идут парами: метка времени, следом название передачи. Идём по
    # всем `div` подряд: селектор через запятую selectolax отдаёт группами,
    # а не в порядке страницы, и пары бы развалились
    rows = []
    waiting: list[str] | None = None
    for node in tree.css("div"):
        classes = node.attributes.get("class") or ""
        if classes == "time":
            waiting = _slots(node)
        elif waiting is not None and classes.startswith("prname"):
            rows.append((waiting, " ".join(node.text().split())))
            waiting = None
    if not rows:
        return []

    answer = decode([slots for slots, _ in rows])

    out: list[Program] = []
    turned = False
    last: tuple[int, int] | None = None
    for slots, title in rows:
        when = _read(slots, answer)
        raw = "".join(answer.get(s, "?" if s.startswith("#") else s)
                      for s in slots)
        if when is None or not title:
            continue
        if last is not None and when < last:
            turned = True
        last = when
        d = base + timedelta(days=1) if turned else base
        out.append(Program(
            channel_raw=channel, title=title,
            start=datetime(d.year, d.month, d.day, when[0], when[1], tzinfo=zone),
            raw_time=raw, match_raw=_pair(title), source_url=url,
            league_raw=_league(title)[:120],
            extra={"day": d.isoformat()},
        ))
    return mark_first_show(out, "прямой эфир")


def _parts(title: str) -> list[str]:
    """Заголовок у сайта — предложения через точку: `Футбол. Чемпионат Англии.
    Премьер-лига. Борнмут - Эвертон.`"""
    return [p.strip() for p in title.split(".") if p.strip()]


def _pair(title: str) -> str:
    """Пара команд — в последнем куске заголовка, через дефис с пробелами."""
    for part in reversed(_parts(title)):
        for sep in (" - ", " – ", " — "):
            if sep in part:
                home, _, away = part.partition(sep)
                if home.strip() and away.strip():
                    return f"{home.strip()} - {away.strip()}"
    return " "


def _league(title: str) -> str:
    """Всё между видом спорта и парой команд: `Чемпионат Англии. Премьер-лига`."""
    parts = _parts(title)
    if len(parts) < 3:
        return ""
    tail = parts[1:]
    if any(sep in tail[-1] for sep in (" - ", " – ", " — ")):
        tail = tail[:-1]
    return ". ".join(tail)

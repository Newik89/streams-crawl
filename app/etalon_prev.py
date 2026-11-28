# -*- coding: utf-8 -*-
"""Книга 184: обход одного сайта берёт эталон прошлого полного сбора.

Находка 28.11: обход по списку сайтов (`--only` — кнопка «Обойти сайт»,
утренний сбор сайтов «качает сервер», заказ сторожа) страниц эталона
flashscore не качает, и разбор шёл вслепую: правила, которые спрашивают
эталон, молчали или ошибались. Живой случай: sportklub.hr 28.11 06:06 —
«Košarka - NBA liga: Washington - Orlando» 29.11 00:00 снята как «повтор:
матч сыгран несколько дней назад» (память сборов помнила игру 23.11), хотя
в эту ночь команды играют снова: эталон это знает, а у обхода его не было.
Слово владельца 28.11 на «обход одного сайта берёт эталон прошлого сбора»:
«Да, делаем».

Правила:
  З1. Занимаем, только когда обход шёл по списку сайтов (в отчёте обхода
      раздел `ONLY_KEY` — его пишет `crawl_fetch.py` при `--only`) и своих
      записей эталона в нём нет. Полный сбор, скан даты, проба адресов и
      срезы книги без этого раздела идут как раньше.
  З2. Берём запись «эталон» из итога прошлого ПОЛНОГО сбора
      (`results/games.json`) целиком — с местными именами.
  З3. Свежесть: прошлый сбор собран не позже «сейчас» и не раньше чем за
      `MAX_AGE` до него. Иначе не берём — разбор идёт без эталона, как
      раньше; причина печатается в журнал разбора.
  З4. Край. Справочник качается на неделю от дня сбора; последний день его
      записей — хвост последней страницы, неполный. Целиком покрыты дни до
      ПРЕДПОСЛЕДНЕГО (`edge`). Строки сайта позже края правила «пары нет в
      эталоне — снять» не трогают (`beyond`): обход ночью и утром, до
      первого полного сбора дня, берёт вчерашний эталон, и шестой день
      окна в нём пуст. Какие правила молчат за краем — в `parse_live.main`
      рядом с пометкой «книга 184, З4».
  З5. Итог обхода несёт занятый эталон под ключом «эталон» и пометку `KEY`
      (когда собран, сколько записей, край) — сервер сверяет игры файла с
      эталоном так же, как у полного сбора.
  З6. Местные имена, скачанные этим же обходом (страницы языковых версий
      без flashscore.mobi), дописываются к записям; прежние языки остаются
      (`add_names`).
Предел: за краем обход одного сайта работает как раньше — без эталона.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

#: З1: раздел отчёта обхода — список сайтов из `--only`
ONLY_KEY = "только"
#: З5: пометка в итоге обхода «эталон занят у прошлого сбора»
KEY = "эталон_занят"
#: З3: старше — не берём. Сборов три в день (перерыв до 12 часов); полтора
#: суток покрывают два сорванных сбора подряд
MAX_AGE = timedelta(hours=36)
KYIV = ZoneInfo("Europe/Kyiv")


@dataclass
class Loan:
    """Что занято: записи эталона, край (З4), пометка в итог (З5) и причина,
    если занять не вышло (З3). Обход не по списку сайтов — всё пусто."""
    records: list = field(default_factory=list)
    edge: date | None = None
    mark: dict = field(default_factory=dict)
    why: str = ""


def _collected(previous: dict) -> datetime | None:
    """Метка «собрано» прошлого сбора (UTC) — временем; нет или битая — None."""
    try:
        return datetime.strptime(str(previous.get("собрано") or ""),
                                 "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _day(record: dict) -> str:
    """День записи эталона «ГГГГ-ММ-ДД» (по Киеву); нет или битый — пусто."""
    day = str(record.get("start_kyiv") or "")[:10]
    try:
        date.fromisoformat(day)
    except ValueError:
        return ""
    return day


def edge(records: list) -> date | None:
    """З4: последний день, который записи эталона покрывают целиком, —
    предпоследний день записей; день один — он сам; записей нет — None."""
    days = sorted({_day(r) for r in records if isinstance(r, dict)} - {""})
    if not days:
        return None
    return date.fromisoformat(days[-2] if len(days) > 1 else days[-1])


def beyond(day: date, край: date | None) -> bool:
    """З4: день строки позже края занятого эталона. Эталон свой (не занят,
    `край` — None) — края нет, False."""
    return край is not None and day > край


def borrow(report: dict, own: list, previous: dict,
           now: datetime | None = None) -> Loan:
    """Занять эталон прошлого полного сбора (З1–З5). `report` — отчёт обхода
    (`report.json`), `own` — записи эталона этого обхода, `previous` — итог
    прошлого полного сбора (`results/games.json`), `now` — «сейчас» (UTC)."""
    only = report.get(ONLY_KEY) if isinstance(report, dict) else None
    if not only or own:                                                  # З1
        return Loan()
    previous = previous if isinstance(previous, dict) else {}
    records = [r for r in previous.get("эталон") or [] if isinstance(r, dict)]
    if not records:                                                      # З2
        return Loan(why="в итоге прошлого полного сбора эталона нет")
    collected = _collected(previous)
    now = now or datetime.now(timezone.utc)
    if collected is None:                                                # З3
        return Loan(why="у прошлого полного сбора нет метки «собрано»")
    if collected > now:
        return Loan(why=f"прошлый полный сбор помечен будущим временем "
                        f"({previous.get('собрано')} UTC)")
    if now - collected > MAX_AGE:
        return Loan(why=f"прошлый полный сбор старше "
                        f"{int(MAX_AGE.total_seconds() // 3600)} ч "
                        f"(собран {previous.get('собрано')} UTC)")
    край = edge(records)                                                 # З4
    return Loan(records=records, edge=край,
                mark={"собрано": previous.get("собрано"),                # З5
                      "записей": len(records),
                      "край": край.isoformat() if край else ""})


def football(records: list) -> list[tuple]:
    """Футбольные записи эталона кортежами (хозяева, гости, начало по Киеву)
    — тот же вид, в каком `parse_live.add_reference` копит эталон для сверки
    угаданного эфира. Запись без пары или без времени пропускается."""
    out = []
    for r in records:
        if r.get("sport", "F") != "F" or not r.get("home") or not r.get("away"):
            continue
        try:
            start = datetime.strptime(r.get("start_kyiv") or "", "%Y-%m-%dT%H:%M")
        except ValueError:
            continue
        out.append((r["home"], r["away"], start.replace(tzinfo=KYIV)))
    return out


def add_names(record: dict, names: dict, leagues: dict) -> None:
    """З6: местные имена и лиги языковых версий — в запись эталона. Языки,
    которые в записи уже есть и которых этот обход не качал, остаются."""
    record["names"] = {**(record.get("names") or {}), **(names or {})}
    record["leagues"] = {**(record.get("leagues") or {}), **(leagues or {})}

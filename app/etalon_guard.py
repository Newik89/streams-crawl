# -*- coding: utf-8 -*-
"""Сторож эталона и сторож «сайт просел на дату» (книга 114, аудит 13.11.2026).

Повод. Аудит сбоев 13.11: flashscore отдал пустой или урезанный список
матчей — сбор остаётся «зелёным», а разбор без эталона портит витрину
(подставной прогон: 133 двойника игр, 185 сдвигов времени, 80 снятых
каналов). Слово владельца 13.11: сравнивать не «весь сбор с прошлым», а «ту
же дату с прошлым сбором» — будни и выходные, клубные дни и дни сборных
тогда не мешают.

ЧАСТЬ 1. ЭТАЛОН (`etalon_verdict`) — красный сбор и тревога сразу.
Считаем матчи эталона по дням (по Киеву), футбол и баскетбол отдельно.
Теннис не считаем: сетки турниров на дальние дни неизвестны, ноль — норма.

Э1. Ноль футбола в любой день от сегодня до `ZERO_DAYS` дней вперёд — эталон
    пустой. Футбол в мире идёт каждый день, эталон даёт его на неделю вперёд
    (за 14 сборов 09–13.11 меньше 98 матчей в полном дне не было).
Э2. День из прошлого сбора (кроме сегодняшнего): матчей вида спорта стало
    меньше `SHARE` (60 %) от прошлого сбора той же даты — эталон урезан.
    Судим, только если в прошлом сборе на этот день было не меньше `BASE`
    матчей (маленькое число скачет само).
Э3. Сегодняшний день по доле не судим: прошедшие матчи эталон убирает, и к
    вечеру число честно падает (13.11: баскетбол 200 → 155). Сегодня — только
    правило нуля.
Э4. Прошлого сбора нет — работает только правило нуля.
При красной оценке GitHub результат в репозиторий не кладёт: витрина
остаётся на прошлом сборе, владельцу уходит тревога (`crawl_alarm.py`), а
следующий сбор сравнивается с последним ХОРОШИМ — порог сам себя не опускает.

ЧАСТЬ 2. САЙТ ПРОСЕЛ НА ДАТУ (`site_drops`) — пока ТОЛЬКО ЗАПИСЬ.
Слово владельца: первую неделю только записывать «сработал бы», потом
показать ему список и число ложных — и лишь тогда решать про тревогу.

С1. Считаем игры сайта по дням: игра засчитана сайту в день своей строки.
С2. Сравниваем только дни, которые видели ОБА сбора, и только будущие:
    от завтра до последнего дня окна каждого из двух сборов. Сегодняшний
    день не считаем (сайты убирают прошедшее), самый дальний день нового
    окна не сравниваем (прошлый сбор его не видел).
С3. Просадка: в прошлом сборе у сайта на эту дату было не меньше
    `SITE_BASE` игр, а стало меньше половины (`SITE_SHARE`).
С4. «Подряд»: сколько сборов подряд держится просадка этого сайта на эту
    дату (счёт едет в games.json прошлого сбора, поле `просадки`). Тревогой
    она станет только при двух подряд — и только после слова владельца.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

#: Э1: на сколько дней вперёд (считая сегодня = 0) ноль футбола — пустой эталон
ZERO_DAYS = 5
#: Э2: доля от прошлого сбора той же даты, ниже которой эталон урезан
SHARE = 0.6
#: Э2: при скольких матчах в прошлом сборе день уже судим
BASE = 30
#: виды спорта, по которым судим эталон, и их имена для текста тревоги
SPORTS = {"F": "футбол", "B": "баскетбол"}
#: С3: доля и наименьшее прежнее число игр сайта на дату
SITE_SHARE = 0.5
SITE_BASE = 6


def etalon_counts(reference: list) -> Counter:
    """(«ГГГГ-ММ-ДД» по Киеву, вид спорта) → сколько матчей в эталоне."""
    out: Counter = Counter()
    for rec in reference or []:
        if not isinstance(rec, dict):
            continue
        day = (rec.get("start_kyiv") or "")[:10]
        if len(day) == 10:
            out[(day, rec.get("sport") or "F")] += 1
    return out


def etalon_verdict(reference: list, previous: list, today: date) -> list[str]:
    """Э1–Э4: причины считать эталон пустым или урезанным; пусто — норма."""
    now, was = etalon_counts(reference), etalon_counts(previous)
    reasons = []
    for shift in range(ZERO_DAYS + 1):                                # Э1
        day = (today + timedelta(days=shift)).isoformat()
        if now[(day, "F")] == 0:
            reasons.append(f"на {day} в эталоне нет ни одного футбольного "
                           "матча")
    сегодня = today.isoformat()
    for (day, sport), prev in sorted(was.items()):                    # Э2
        if sport not in SPORTS or day <= сегодня or prev < BASE:      # Э3
            continue
        got = now[(day, sport)]
        if got and got < prev * SHARE:      # ноль футбола уже назвало Э1
            reasons.append(f"на {day} в эталоне {SPORTS[sport]}: {got} "
                           f"матч(ей), а в прошлом сборе было {prev}")
        elif not got and not (sport == "F" and any(day in r for r in reasons)):
            reasons.append(f"на {day} в эталоне {SPORTS[sport]}: 0 "
                           f"матчей, а в прошлом сборе было {prev}")
    return reasons


def etalon_error(reasons: list[str]) -> str:
    """Строка оценки сбора (её читает `crawl_alarm.py`); пусто — норма."""
    if not reasons:
        return ""
    head = "; ".join(reasons[:4])
    more = f" (и ещё {len(reasons) - 4})" if len(reasons) > 4 else ""
    return (f"::error::эталон flashscore пустой или урезанный — {head}{more}. "
            "Результат не заливается, витрина остаётся на прошлом сборе")


def site_counts(games: list) -> Counter:
    """С1: (сайт, «ГГГГ-ММ-ДД») → сколько игр у сайта в этот день."""
    out: Counter = Counter()
    for game in games or []:
        if not isinstance(game, dict):
            continue
        seen = set()
        for entry in game.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            site = (entry.get("source") or "").lower().removeprefix("www.")
            day = (entry.get("start_kyiv") or game.get("start_kyiv") or "")[:10]
            if site and len(day) == 10:
                seen.add((site, day))
        for pair in seen:
            out[pair] += 1
    return out


def _last_day(collected: str, window: int) -> str:
    """Последний день окна сбора: день сбора + окно − 1. Нет данных — ''."""
    try:
        start = date.fromisoformat((collected or "")[:10])
    except ValueError:
        return ""
    return (start + timedelta(days=max(int(window or 0), 1) - 1)).isoformat()


def site_drops(games: list, previous: dict, today: date,
               window: int) -> list[dict]:
    """С1–С4: просадки «сайт, дата» против прошлого сбора. `previous` —
    games.json прошлого полного сбора (ключи games, собрано, окно, просадки)."""
    if not isinstance(previous, dict) or not previous.get("games"):
        return []
    край = min(_last_day(today.isoformat(), window),
               _last_day(previous.get("собрано") or "",
                         previous.get("окно") or 0) or "")
    if not край:
        return []
    now, was = site_counts(games), dict(site_counts(previous.get("games")))
    # С4: просадка прошлого сбора ещё держится — мерим от числа ДО просадки
    # («было» из прошлой записи), а не от просевшего прошлого сбора: иначе
    # второй сбор подряд сравнивался бы с уже плохим и молчал
    подряд = {}
    for x in previous.get("просадки") or []:
        if isinstance(x, dict) and x.get("сайт") and x.get("дата"):
            пара = (x["сайт"], x["дата"])
            подряд[пара] = int(x.get("подряд") or 0)
            was[пара] = max(was.get(пара, 0), int(x.get("было") or 0))
    out = []
    for (site, day), prev in sorted(was.items()):
        if not (today.isoformat() < day <= край) or prev < SITE_BASE:   # С2, С3
            continue
        got = now[(site, day)]
        if got < prev * SITE_SHARE:
            out.append({"сайт": site, "дата": day, "было": prev, "стало": got,
                        "подряд": подряд.get((site, day), 0) + 1})      # С4
    return out

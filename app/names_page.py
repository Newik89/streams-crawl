# -*- coding: utf-8 -*-
"""Страница «Названия» админки: что показать у каждого вопроса — простыми
словами.

Владелец 06.10: «на скрине вообще не понятно, что кнопки делают… нужно её
проще и понятнее сделать». Он не программист. Поэтому у каждого вопроса
видно:

* что увидела программа — как написано на сайте, какой сайт и канал, время,
  ссылка на игру на витрине (если она там есть);
* что программа предлагает и насколько уверена. Слабую догадку («Bilbao» →
  «Alba Berlin», сходство 60) готовым ответом НЕ подставляем: поле пустое,
  догадка видна рядом с пометкой «скорее всего, другая» (`HINT_READY`);
* что сделает каждая кнопка — надпись и подсказка при наведении;
* после ответа — строка «Запомнено: …» и что изменится (`result_message`).

Ответы пишутся тем же путём, что и раньше (`dictionary.resolve` / `skip` /
`later` / `back_to_open`, маршрут `/names/<id>`): меняются только вид и
слова. Здесь — только подготовка данных для шаблона `moderation.html`.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta

from . import dictionary, names, store
from .sport_question import Question

#: С какого сходства догадку программы показываем готовым ответом (кнопка
#: «Да, это …»). Ниже — поле пустое, догадка видна рядом с пометкой
#: «скорее всего, другая»: «Bilbao» → «Alba Berlin» (60), «Igokea» →
#: «Slavia Prague ERA NBK» (44), «Λιθουανία» → «Andorra» (40) — владелец
#: 06.10 не понял, откуда такое. Выше — «Bodrum FK» → «Bodrumspor» (75)
HINT_READY = 70

#: сколько игр с этим именем показать у вопроса — хватает одной-двух
GAMES_SHOWN = 2
#: сколько каналов игры перечислить
CHANNELS_SHOWN = 3
#: насколько давние игры ещё ищем для подписи «где увидели»
GAMES_LOOKBACK = timedelta(days=7)

#: вкладки по видам вопросов: ключ, надпись, одна строка «что это и зачем»
TABS = (
    ("", "Все",
     "Все вопросы сразу. У каждого свои кнопки — отвечайте прямо здесь или "
     "по вкладкам."),
    ("team", "Команды",
     "Программа не уверена, какая это команда. Ответ запомнится, и в "
     "следующий раз она узнает это написание сама."),
    ("league", "Лиги",
     "Программа не уверена, что это за турнир. Ответ запомнится, и в "
     "расписании лига будет называться правильно."),
    ("channel", "Каналы",
     "Новый канал: как его называть на сайте и какой он страны. Ответ "
     "запомнится для этого сайта."),
    ("sport", "Вид спорта",
     "Программа не поняла, какой это вид спорта. Пока нет ответа, игры нет "
     "в расписании. Ответ действует на эту пару команд около этой даты "
     "(±1,5 суток)."),
)

#: служебные вкладки: что в них лежит
LATER_NOTE = ("Вопросы, на которые нажали «Отложить». Никуда не пропадают и "
              "ждут здесь, пока не будет ответа.")
#: срок «свежего» во вкладках и чистки — одно число на всех
#: (`dictionary.FRESH_DAYS`), чтобы тексты не соврали при его смене
_ДНЕЙ = dictionary.FRESH_DAYS
REJECTED_NOTE = (f"Закрытое без ответа за последние {_ДНЕЙ} дней: нажали "
                 "«Не матч» или «Это не команда» — или программа убрала сама "
                 "(написано почему). Кнопка «Вернуть в вопросы» вернёт вопрос "
                 f"в список. Что закрыла программа, через {_ДНЕЙ} дней "
                 "стирается; ваши ответы остаются.")
AUTO_NOTE = (f"На что программа ответила сама за последние {_ДНЕЙ} дней — и "
             "почему. Отсеянное можно вернуть кнопкой «Вернуть в вопросы». "
             f"Старше {_ДНЕЙ} дней стирается: понадобится — программа решит "
             "заново.")

#: вид вопроса → как назвать владельцу
KIND_TITLES = {"team": "Команда", "league": "Лига", "channel": "Канал",
               "sport": "Вид спорта"}
#: что такое «не то» для каждого вида: надпись кнопки `skip`
NOT_THIS = {"team": "Это не команда", "league": "Это не лига",
            "channel": "Это не канал", "sport": "Не матч"}
#: вопрос владельцу — заголовок над кнопками
ASK = {"team": "Какая это команда? Как называть её у нас?",
       "league": "Что это за турнир? Как называть его у нас?",
       "channel": "Как называть этот канал на сайте и какой он страны?",
       "sport": "Какой это вид спорта?"}
#: «скорее всего, это …» — при слабой догадке
OTHER = {"team": "другая команда", "league": "другой турнир",
         "channel": "другой канал"}
#: чем является имя — для подсказок кнопок
WHAT = {"team": "команда", "league": "турнир", "channel": "канал"}
#: буква вида спорта → слово
SPORTS = {"F": "футбол", "B": "баскетбол", "T": "теннис"}


def tab_note(kind: str) -> str:
    return next((note for key, _, note in TABS if key == kind), "")


def describe(conn: sqlite3.Connection, rows, now: datetime | None = None
             ) -> list[dict]:
    """Строки очереди → карточки для шаблона: что видно на сайте, где
    увидели, догадка программы и её надёжность."""
    now = now or datetime.now()
    rows = [dict(r) for r in rows]
    games = _games_by_name(conn, rows, now)
    team_names = dictionary.team_overrides(conn)
    league_names = dictionary.league_overrides(conn)
    sites = {r["domain"]: r["base_url"] for r in conn.execute(
        "SELECT domain, base_url FROM sources")}
    out = []
    for d in rows:
        kind = d.get("kind") or ""
        d["title"] = KIND_TITLES.get(kind, kind)
        d["not_this"] = NOT_THIS.get(kind, "Не то")
        d["ask"] = ASK.get(kind, "")
        d["other"] = OTHER.get(kind, "другое")
        d["what"] = WHAT.get(kind, "название")
        d["answered_by"] = d.get("answered_by") or ""
        if kind == "sport":
            _sport_card(d, team_names, league_names, sites)
        else:
            raw = (d.get("raw_value") or "").strip()
            d["games"] = games.get((kind, raw), [])[:GAMES_SHOWN]
            _hint(d)
        out.append(d)
    return out


def _hint(d: dict) -> None:
    """Догадка программы и её надёжность: готовый ответ или «скорее всего,
    другая»."""
    hint = (d.get("suggestion") or "").strip() if d.get("status") != "done" \
        else ""
    d["hint"] = hint
    d["hint_score"] = names.similarity(d.get("raw_value") or "", hint) \
        if hint else 0
    d["hint_ready"] = bool(hint) and d["hint_score"] >= HINT_READY


def _games_by_name(conn, rows, now: datetime) -> dict[tuple, list]:
    """Игры базы, где встретилось имя вопроса: (вид, имя) → игры, ближайшие
    будущие первыми, потом недавние. Одной выборкой на страницу."""
    wanted = {(r.get("kind"), (r.get("raw_value") or "").strip())
              for r in rows if r.get("kind") in ("team", "league")}
    if not wanted:
        return {}
    edge = (now - GAMES_LOOKBACK).strftime("%Y-%m-%d %H:%M")
    found: dict[tuple, list] = {}
    events: dict[int, dict] = {}
    for e in conn.execute(
            "SELECT e.id, e.sport, e.start_kyiv, e.team_home_auto AS home, "
            "e.team_away_auto AS away, e.league_auto, "
            "l.canonical_name AS league_canon "
            "FROM events e LEFT JOIN leagues l ON l.id = e.league_id "
            "WHERE e.start_kyiv >= ?", (edge,)):
        keys = [("team", (e["home"] or "").strip()),
                ("team", (e["away"] or "").strip()),
                ("league", (e["league_auto"] or "").strip())]
        hit = [k for k in keys if k in wanted]
        if not hit:
            continue
        events[e["id"]] = dict(e)
        for k in hit:
            found.setdefault(k, []).append(e["id"])
    if not events:
        return {}
    channels: dict[int, list] = {}
    marks = ",".join("?" * len(events))
    for c in conn.execute(
            f"SELECT ec.event_id, c.canonical_name AS name, s.domain, "
            f"ec.source_url, s.base_url FROM event_channels ec "
            f"JOIN channels c ON c.id = ec.channel_id "
            f"LEFT JOIN sources s ON s.id = ec.source_id "
            f"WHERE ec.event_id IN ({marks}) ORDER BY ec.id", list(events)):
        channels.setdefault(c["event_id"], []).append({
            "name": c["name"], "domain": c["domain"] or "",
            "url": store.human_url(c["source_url"], c["base_url"])})
    now_text = now.strftime("%Y-%m-%d %H:%M")
    out: dict[tuple, list] = {}
    for key, ids in found.items():
        games = []
        for i in ids:
            e = events[i]
            start = e["start_kyiv"] or ""
            games.append({
                "id": e["id"],
                "when": _when(start),
                # на витрине — только будущие и идущие игры
                "upcoming": start >= now_text,
                "pair": f"{e['home'] or ''} — {e['away'] or ''}",
                "league": e["league_canon"] or e["league_auto"] or "",
                "sport": SPORTS.get(e["sport"] or "", ""),
                "channels": channels.get(i, [])[:CHANNELS_SHOWN]})
        games.sort(key=lambda g: (not g["upcoming"], g["when"]))
        out[key] = games
    return out


def _when(start: str) -> str:
    """«2026-10-06 20:00» → «06.10 20:00»."""
    m = re.match(r"\d{4}-(\d{2})-(\d{2})[ T](\d{2}:\d{2})", start or "")
    return f"{m[2]}.{m[1]} {m[3]}" if m else (start or "")


def _english(text: str, words: dict) -> str:
    """Перевод на английский для «≈»: словарь подтверждённых имён, незнакомое
    не латиницей — транслит (иврит и греческий владелец читать не обязан,
    жалоба 15.09)."""
    text = (text or "").strip()
    if not text:
        return ""
    if text in words:
        return words[text]
    if any(ord(c) > 0x2FF for c in text):
        return names.suggest_canonical(text)
    return text


def _sport_card(d: dict, team_names: dict, league_names: dict,
                sites: dict) -> None:
    """Вопрос «вид спорта»: части строки очереди, перевод и сайт."""
    # у отвеченного в подсказке уже не время и заголовок, а сам ответ («F»)
    q = Question.parse(d.get("raw_value") or "",
                       d.get("suggestion") or "" if d.get("status") != "done"
                       else "")
    d["pair"] = q.pair_text
    d["league"] = q.league
    d["channel"] = q.channel
    d["site"] = q.domain
    d["site_url"] = sites.get(q.domain) or ""
    # страница именно этого канала и дня — владелец открывает её одним
    # кликом (просьба 08.10); у старых вопросов адреса нет — остаётся сайт
    d["page_url"] = q.url
    d["when"] = q.when.strftime("%d.%m %H:%M") if q.when else ""
    # строка сайта как есть — всегда, даже когда она равна паре: владелец
    # сверяет по ней перевод (просьба 08.10: «как именно написано на самом
    # сайте, чтоб я понимал, правильно переведено или нет»)
    d["site_title"] = q.title or q.pair_text
    if q.pair:
        перевод = (f"{_english(q.pair[0], team_names)} — "
                   f"{_english(q.pair[1], team_names)}")
    else:
        перевод = _english(q.pair_text, team_names)
    перевод_лиги = _english(q.league, league_names)
    # заголовок карточки — перевод, а не строка сайта (владелец 09.10: «всё
    # должно быть переведено автопереводом минимум»); строка сайта как есть
    # остаётся ниже, в «На сайте написано»
    d["headline"] = перевод
    # и перевод — тоже всегда: совпал со строкой сайта — значит, переводить
    # было нечего, и это тоже ответ
    d["preview"] = " · ".join(x for x in (перевод, перевод_лиги) if x)
    # чем программа засомневалась — тем, чего в строке НЕТ
    d["doubt"] = ("На странице не написан вид спорта, а турнир «"
                  f"{q.league}» программе незнаком." if q.league else
                  "На странице не написаны ни вид спорта, ни турнир, а по "
                  "названиям команд вид спорта однозначно не определить.")


def result_message(item, action: str, answer: str = "") -> str:
    """Строка после нажатия кнопки: что запомнено и что изменится. `item` —
    запись очереди ДО ответа."""
    kind = item["kind"]
    raw = (item["raw_value"] or "").strip()
    shown = dictionary.norm_pair(raw) if kind == "sport" else raw
    if action == "skip":
        тут = {"sport": "не матч", "team": "не команда",
               "league": "не лига", "channel": "не канал"}.get(kind, "не то")
        return (f"Запомнено: «{shown}» — {тут}. Больше не спросим; вопрос во "
                "вкладке «Отсеянные», передумаете — там кнопка «Вернуть в "
                "вопросы».")
    if action == "later":
        return (f"Отложено: «{shown}» ждёт во вкладке «Отложенные» — "
                "ответить можно в любой момент.")
    if action == "reopen":
        return f"Вернули в список вопросов: «{shown}»."
    if kind == "sport":
        день = re.search(r"(\d{4})-(\d{2})-(\d{2})", item["suggestion"] or "")
        около = f" (на {день[3]}.{день[2]} ±1,5 суток)" if день else ""
        return (f"Запомнено: «{shown}» — {SPORTS.get(answer, answer)}{около}. "
                "Игра появится в расписании после следующего сбора.")
    if kind == "channel":
        return (f"Запомнено: канал «{raw}» называется «{answer}». На сайте он "
                "будет под этим именем после следующего сбора.")
    if kind == "league":
        return (f"Запомнено: турнир «{raw}» — это «{answer}». В расписании "
                "лига будет под этим именем.")
    return (f"Запомнено: «{raw}» — это команда «{answer}». На витрине это "
            "написание будет показано как «" + answer + "», и программа "
            "больше не спросит.")

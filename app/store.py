# -*- coding: utf-8 -*-
"""Игры в базе: запись склеенных игр, срок жизни, выборка для сайта.

Обход отдаёт `games.json` (его пишет `scripts/parse_live.py`), сюда он
попадает через `scripts/games_import.py`. Здесь три обязанности:

  - `save_games()` — влить свежие игры в `events` / `event_channels`.
    Игра, которой в этом прогоне не было, НЕ удаляется (ТЗ разд. 10):
    из базы её убирает только срок жизни.
  - `purge_expired()` — убрать игры, у которых время вышло. Правило одно:
    начало + грейс по виду спорта (или свой `grace_minutes` у игры).
  - `schedule()` — готовые строки для публичной страницы.

Свежая строка от сайта считается точнее лежащей в базе: время и лига
обновляются, если пришли лучше. Канал, пропавший из источника, после первого
же неподтверждения (`MISS_LIMIT`, `event_channels.miss_count`; когда сбор вправе
считать канал пропавшим — правила в `app/miss.py`) не исчезает молча: на витрине
он остаётся перечёркнутым «снят» (владелец 22.09, случай #3354), а в API не
отдаётся. Вернулся в расписание — заливка сбросит счётчик, канал оживёт сам.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from . import broadcast, channel_owner, merge, miss, names

# Грейс после начала, минуты (ТЗ разд. 10). Число-уговор, не измерение;
# правится в админке («Настройки»), здесь только значения по умолчанию.
GRACE_MINUTES = {"F": 130, "B": 190, "T": 240}
DEFAULT_GRACE = 240          # незнакомый спорт живёт по самому долгому правилу
#: Канал гаснет (на витрине — перечёркнут «снят») после стольких обходов
#: подряд, доказавших, что ЕГО сайт канал больше не показывает (что считать
#: доказательством — правила `app/miss.py`).
#: Было 3; владелец 03.10: «да» на один — неверный канал уходит сразу
#: (#2579: maxsport.live перенёс матч с MAX Sport 4 на MAX Sport 1).
MISS_LIMIT = 1
#: подсветка нового (правка владельца 12.09: «вчерашние игры уже не новые,
#: новые — только каналы, которые к ним добавились»): игра зелёная лишь
#: полсуток после первого появления, канальный бейдж живёт двое суток
FRESH_GAME_HOURS = 12        # сколько часов игра считается «новой»
FRESH_CHANNEL_HOURS = 48     # сколько часов «новым» считается добавленный канал
OTHER_SPORT_GRACE_MIN = 180  # начавшееся на вкладке «Other Sport» держим 3 часа
#: канал «добавился», если появился у игры хотя бы на столько позже неё
#: самой — иначе каждый канал свежей игры носил бы бейдж
FRESH_CHANNEL_GAP = timedelta(hours=3)

#: адрес, которым программу читала МАШИНА: API-ручка или файл выгрузки.
#: Человеку такая ссылка показывает сырой JSON или ошибку (кейс PPV2/PPV3
#: у #686, 04.09) — кнопка ↗ ведёт тогда на обычную страницу источника
_MACHINE_URL_RE = re.compile(
    r"/api/|ajax|tvapi|\.json(\?|$)|\.xml(\?|$)|data-feed|/cache/|/epg/",
    re.I)


def human_url(source_url: str | None, base_url: str | None) -> str:
    """Ссылка «Открыть расписание канала»: страница как есть, а вместо
    API-ручки — страница источника без query (в base_url бывают старые
    даты из закладок, без них главная всегда живая)."""
    if not source_url or not _MACHINE_URL_RE.search(source_url):
        return source_url or ""
    if not base_url:
        return ""
    p = urlsplit(base_url)
    return f"{p.scheme}://{p.netloc}{p.path}" if p.scheme else base_url


def grace_map(conn: sqlite3.Connection) -> dict[str, int]:
    """Грейсы с учётом правок владельца в админке (`settings`: grace_F …)."""
    from . import db as _db
    out = dict(GRACE_MINUTES)
    for sport in out:
        value = _db.get_setting(conn, f"grace_{sport}")
        if value.isdigit():
            out[sport] = int(value)
    return out


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _parse_dt(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "").strip())


def grace_for(sport: str, own: int | None,
              table: dict[str, int] | None = None) -> int:
    return own if own else (table or GRACE_MINUTES).get(sport or "", DEFAULT_GRACE)


# ── запись ───────────────────────────────────────────────────────────────────

@dataclass
class SaveStats:
    new: int = 0
    updated: int = 0
    channels: int = 0
    repeats: int = 0    # guess-игры, чья пара уже лежала в базе раньше
    time_off: int = 0   # строки, прилипшие к игре flashscore вопреки времени сайта
    titles_gone: int = 0  # отметки заголовков турниров, которых сайт больше не показывает
    gone: int = 0       # отметки каналов, погашенные этим сбором (`app/miss.py`)
    #: отметки игр-сирот — игр, которых в файле нет вовсе (сайт перенёс матч
    #: на другой день, #5104); те же правила `app/miss.py`
    orphans_gone: int = 0
    #: строки агрегаторов, не взятые потому, что у канала есть свой сайт
    #: (`app/channel_owner.py`), и строка для журнала по сайтам
    not_own: int = 0
    not_own_note: str = ""
    #: снятые прежние отметки тех же агрегаторов по тем же каналам
    not_own_dropped: int = 0


def _хозяева_канала(conn: sqlite3.Connection, games: list[dict],
                    now: datetime) -> channel_owner.Хозяева:
    """Первый проход по файлу: чьи каналы и на какую глубину дали свои сайты.

    Идём только по строкам официальных источников — у остальных строк чей
    канал, спросим во втором проходе (`Хозяева.пропустить`)."""
    хозяева = channel_owner.Хозяева(conn, now)
    if not хозяева.официальные:
        return хозяева
    srcs = _sources_by_domain(conn)
    for game in games:
        день = (game.get("start_kyiv") or "")[:10]
        if not день:
            continue
        for entry in game.get("entries", []):
            source = srcs.get(entry.get("source") or "")
            if source is None or not хозяева.свой(source["id"]):
                continue
            channel_id = _channel_id(conn, entry.get("channel") or "?", source)
            if channel_id is not None:
                хозяева.учесть(source["id"], channel_id, день)
    return хозяева


def _sources_by_domain(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {r["domain"]: r for r in conn.execute(
        "SELECT id, domain, country FROM sources")}


def _is_latin(name: str) -> bool:
    """Написано ли имя латиницей. Половины букв хватает: `Bodø/Glimt` и
    `Málaga` — латиница, `Кремонезе` — нет."""
    letters = [c for c in (name or "") if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if "A" <= c.upper() <= "Z")
    return latin * 2 >= len(letters)


def _find_event(conn: sqlite3.Connection, game: dict) -> sqlite3.Row | None:
    """Ищем игру среди лежащих в базе теми же правилами, какими склеивали
    строки между сайтами (`app/merge.py`): спорт + обе команды + окно времени."""
    start = _parse_dt(game["start_kyiv"])
    lo = _iso(start - timedelta(minutes=merge.WINDOW_MINUTES))
    hi = _iso(start + timedelta(minutes=merge.WINDOW_MINUTES))
    incoming = merge.Entry(source="", channel="", home=game["home"],
                           away=game["away"], start=start,
                           sport=game.get("sport", ""))
    for row in conn.execute(
            "SELECT id, sport, team_home_auto, team_away_auto, start_kyiv "
            "FROM events WHERE start_kyiv BETWEEN ? AND ?", (lo, hi)):
        stored = merge.Entry(source="", channel="",
                             home=row["team_home_auto"] or "",
                             away=row["team_away_auto"] or "",
                             start=_parse_dt(row["start_kyiv"]),
                             sport=row["sport"] or "")
        if merge._same_game(stored, incoming, names.SIMILAR_ENOUGH):
            return row
    return None


def _fs_twin(conn: sqlite3.Connection, game: dict,
             team_ids: dict[str, int]) -> sqlite3.Row | None:
    """Игра с меткой flashscore в тот же киевский день и с теми же командами
    по канону — даже если время у сайта вне окна склейки.

    Кейс #2483/#2400 (14.09): `tvarenasport.com` написал «Dresden - Hertha
    13:00 uzivo», эталон — 20:30; строка легла двойней на 14:00, и владелец
    видел игру без каналов. Время игры — по flashscore (владелец 04.09),
    поэтому канал прилипает к игре эталона, а на витрине горит красной
    пометкой «время у сайта расходится». Не подтвердит его обход ближе к
    дате — погаснет обычным счётчиком пропусков. Кандидат должен быть ровно
    один: две игры тех же команд в один день (кубок + лига) — не гадаем."""
    home = _team_id(team_ids, game["home"])
    away = _team_id(team_ids, game["away"])
    if not home or not away or home == away:
        return None
    day = _iso(_parse_dt(game["start_kyiv"]))[:10]
    sport = game.get("sport") or ""
    rows = [r for r in conn.execute(
        "SELECT id, sport, team_home_auto, team_away_auto, start_kyiv FROM events "
        "WHERE substr(start_kyiv, 1, 10) = ? AND flags LIKE '%fs:%' AND "
        "((team_home_id = ? AND team_away_id = ?) OR "
        " (team_home_id = ? AND team_away_id = ?))",
        (day, home, away, away, home))
        if not sport or not r["sport"] or r["sport"] == sport]
    return rows[0] if len(rows) == 1 else None


def _earlier_show(conn: sqlite3.Connection, game: dict) -> bool:
    """Та же пара уже лежит в базе с началом на 3–30 часов раньше — новая
    guess-игра почти наверняка повтор вчерашнего эфира. Дедуп внутри одного
    прогона этого не видит: файлы соседних дней парсятся порознь (этап 6б,
    зацепка из ОТЛОЖЕНО: ERT2 крутила `Greece - Poland` наутро после матча)."""
    start = _parse_dt(game["start_kyiv"])
    lo = _iso(start - timedelta(hours=30))
    hi = _iso(start - timedelta(hours=3))
    for row in conn.execute(
            "SELECT team_home_auto, team_away_auto, sport FROM events "
            "WHERE start_kyiv BETWEEN ? AND ?", (lo, hi)):
        if game.get("sport") and row["sport"] and game["sport"] != row["sport"]:
            continue
        h, a = row["team_home_auto"] or "", row["team_away_auto"] or ""
        if ((names.same_team(game["home"], h) and names.same_team(game["away"], a))
                or (names.same_team(game["home"], a)
                    and names.same_team(game["away"], h))):
            return True
    return False


def _channel_id(conn: sqlite3.Connection, raw: str,
                source: sqlite3.Row | None) -> int | None:
    """Канал опознаём парой (написание, сайт); новый заводим со страной
    источника — без страны нельзя (`dictionary.remember_channel`)."""
    source_id = source["id"] if source else None
    row = conn.execute(
        "SELECT channel_id FROM channel_aliases WHERE alias = ? "
        "AND (source_id IS ? OR source_id = ?)",
        (raw, source_id, source_id)).fetchone()
    if row:
        return row["channel_id"]
    country = (source["country"] if source else "") or "??"
    from . import channel_rules, dictionary
    # каноническое имя — сразу по правилам владельца (`app/channel_rules.py`):
    # раньше новый канал рождался с сырым именем и до ручного прогона
    # `channel_names.py` висел на витрине как есть — ивритом (#3039, 19.09)
    return dictionary.remember_channel(conn, raw, channel_rules.apply(raw, country),
                                       country, source_id)


def _team_id(overrides_ids: dict[str, int], raw: str) -> int | None:
    return overrides_ids.get((raw or "").strip())


def _team_ids(conn: sqlite3.Connection) -> dict[str, int]:
    # только бесспорные написания: «Dinamo» трёх клубов id не ставит (14.09)
    from . import dictionary
    return {alias: team_id for alias, (team_id, _)
            in dictionary.team_alias_map(conn).items()}


def _league_ids(conn: sqlite3.Connection) -> dict[str, int]:
    # и алиасы, и сами канонические имена: игра приходит уже с каноном
    from . import dictionary
    out = {r["canonical_name"]: r["id"] for r in conn.execute(
        "SELECT id, canonical_name FROM leagues")}
    out.update({alias: league_id for alias, (league_id, _)
                in dictionary.league_alias_map(conn).items()})
    return out


def save_games(conn: sqlite3.Connection, games: list[dict],
               now: datetime | None = None, punish: bool = True,
               coverage: miss.Покрытие | None = None,
               collected: str = "") -> SaveStats:
    """Вливает игры из `games.json`. Формат: список словарей с полями
    sport / league / home / away / start_kyiv / start_utc / entries,
    где entries — строки по сайтам: source / channel / url / raw_title.

    Каналы игры, которых этот сбор не подтвердил, гасятся только по
    правилам `app/miss.py` (там они списком). `punish=False` — повторная
    заливка того же файла; `coverage` — что сбор реально скачал (из
    `report.json`, `miss.покрытие_из_отчёта`), без отчёта не гасится ничего;
    `collected` — момент сбора по Киеву `ГГГГ-ММ-ДД ЧЧ:ММ`."""
    now = now or datetime.now()
    stats = SaveStats()
    graces = grace_map(conn)
    # до записи игр: правилу 6 нужны отметки, жившие до этой заливки
    гашение = miss.Гашение(conn, coverage, punish, collected, MISS_LIMIT)
    # чей канал: у канала со своим сайтом строки агрегаторов не берём, пока
    # свой сайт этот день показывает (`app/channel_owner.py`, правила там)
    хозяева = _хозяева_канала(conn, games, now)
    # подтверждённые каналы копим ПО СОБЫТИЮ за весь файл, а штраф
    # раздаём после всех игр: один матч бывает в файле ДВУМЯ играми
    # (пока словарь не связал написания — «Wolverhampton» и «Wolves»),
    # обе находят одно событие, и раньше каждая гасила каналы другой —
    # SPORT TV + у Шеффилд - Вулвз докапал так до порога и пропал с
    # витрины (владелец 12.09: «затирает каналы, которые раньше были»)
    event_seen: dict[int, set[int]] = {}
    event_start: dict[int, str] = {}
    srcs = _sources_by_domain(conn)
    team_ids, league_ids = _team_ids(conn), _league_ids(conn)

    for game in games:
        # игра из файла, чьё время уже вышло, в базу не идёт — иначе старый
        # games.json воскрешает то, что срок жизни уже убрал
        if _parse_dt(game["start_kyiv"]) + timedelta(
                minutes=grace_for(game.get("sport", ""), None, graces)) < now:
            continue
        found = _find_event(conn, game)
        time_off = 0
        via_twin = False
        if found is None:
            found = _fs_twin(conn, game, team_ids)
            if found is not None:
                # по канону команд нашлась игра эталона; красная пометка —
                # только если время сайта и правда вне окна склейки (иначе
                # не совпали лишь написания имён: «Dresden» / «Dynamo Drezno»)
                via_twin = True
                gap = abs(_parse_dt(game["start_kyiv"])
                          - _parse_dt(found["start_kyiv"]))
                time_off = int(gap > timedelta(minutes=merge.WINDOW_MINUTES))
                stats.time_off += time_off
        # (сведённая трансляция турнира — «ATP Beijing» — зовётся одинаково
        # во всех сессиях турнира: вторая сессия дня не повтор первой)
        if found is None and game.get("guess") \
                and game.get("away") != broadcast.SESSION \
                and _earlier_show(conn, game):
            stats.repeats += 1
            continue
        start_kyiv = _iso(_parse_dt(game["start_kyiv"]))
        start_utc = _iso(_parse_dt(game["start_utc"])) if game.get("start_utc") \
            else start_kyiv
        league = game.get("league") or ""
        if found is None:
            cur = conn.execute(
                "INSERT INTO events (sport, league_id, team_home_id, "
                "team_away_id, league_auto, team_home_auto, team_away_auto, "
                "start_utc, start_kyiv, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (game.get("sport") or "", league_ids.get(league),
                 _team_id(team_ids, game["home"]), _team_id(team_ids, game["away"]),
                 league, game["home"], game["away"],
                 start_utc, start_kyiv, _iso(now)))
            event_id = cur.lastrowid
            stats.new += 1
        else:
            event_id = found["id"]
            # свежий прогон точнее базы: время могло сдвинуться, лига — уточниться
            sets = {"last_seen": _iso(now), "start_utc": start_utc,
                    "start_kyiv": start_kyiv}
            if via_twin:
                # прилипли по канону к игре эталона: время остаётся эталонным
                del sets["start_utc"], sets["start_kyiv"]
                start_kyiv = found["start_kyiv"]
            # Латиница вытесняет кириллицу: игра могла попасть в базу с
            # русского сайта (`Кремонезе`), а потом прийти с испанского
            # (`Cremonese`). Без этого в витрине оставалась обратная
            # перезапись латиницей — `Parma vs Kremoneze` (01.09).
            for field, value in (("team_home_auto", game["home"]),
                                 ("team_away_auto", game["away"])):
                if _is_latin(value) and not _is_latin(found[field] or ""):
                    sets[field] = value
            if league and not league.upper().endswith(": FOOTBALL"):
                sets["league_auto"] = league
                if league_ids.get(league):
                    sets["league_id"] = league_ids[league]
            conn.execute(
                "UPDATE events SET " + ", ".join(f"{k} = ?" for k in sets) +
                " WHERE id = ?", (*sets.values(), event_id))
            stats.updated += 1

        seen_channel_ids: set[int] = set()
        строки = []
        for entry in game.get("entries", []):
            source = srcs.get(entry.get("source") or "")
            if source is None:
                # домен из games.json неизвестен базе (свежий сервер, отставший
                # sources.csv) — отметку канала пропускаем, игру не роняем;
                # лечится scripts/export_sources.py на машине с полной базой
                continue
            channel_id = _channel_id(conn, entry.get("channel") or "?", source)
            if channel_id is None:
                continue
            строки.append((entry, source, channel_id))
        # правило «свой сайт важнее агрегатора» не оставляет игру ВОВСЕ без
        # каналов: если под него попали все строки игры и других живых
        # отметок у неё нет, берём строки как раньше — пустая запись на
        # витрине хуже, чем канал с агрегатора (слово владельца: «mojtv —
        # запасом»)
        отдаём = [с for с in строки
                  if хозяева.почему(с[1]["id"], с[2], start_kyiv[:10]) != 3]
        # живые отметки игры, кроме тех самых, что правило и собирается снять
        снимаем = {(с[2], с[1]["id"]) for с in строки if с not in отдаём}
        чужие_живые = [
            1 for r in conn.execute(
                "SELECT channel_id, source_id FROM event_channels "
                "WHERE event_id = ? AND miss_count = 0", (event_id,))
            if (r["channel_id"], r["source_id"]) not in снимаем]
        беречь = not отдаём and not чужие_живые
        for entry, source, channel_id in строки:
            if not беречь and хозяева.пропустить(
                    source["id"], channel_id, start_kyiv[:10],
                    source["domain"]):
                # у канала есть свой сайт, и он этот день показывает — строку
                # агрегатора не берём (слово владельца 07.10), а прежнюю его
                # отметку снимаем: гашение её не возьмёт (шапка
                # `app/channel_owner.py`), и она висела бы вечно
                stats.not_own_dropped += conn.execute(
                    "DELETE FROM event_channels WHERE event_id = ? "
                    "AND channel_id = ? AND source_id = ?",
                    (event_id, channel_id, source["id"])).rowcount
                continue
            seen_channel_ids.add(channel_id)
            гашение.учесть(source["id"], start_kyiv[:10], event_id, channel_id)
            conn.execute(
                "INSERT INTO event_channels (event_id, channel_id, source_id, "
                "source_url, raw_title, last_seen, miss_count, time_off) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, ?) "
                "ON CONFLICT (event_id, channel_id, source_id) DO UPDATE SET "
                "last_seen = excluded.last_seen, miss_count = 0, "
                "source_url = excluded.source_url, time_off = excluded.time_off",
                (event_id, channel_id,
                 source["id"] if source else None,
                 entry.get("url") or "", entry.get("raw_title") or "",
                 _iso(now), time_off))
            stats.channels += 1
        # каналы игры, не подтверждённые этим прогоном, — кандидаты на
        # счётчик; сам штраф — после всех игр файла, когда набор
        # подтверждённых у события полон
        event_start[event_id] = start_kyiv
        event_seen.setdefault(event_id, set()).update(seen_channel_ids)

    def погасить(marks: list[sqlite3.Row], start: str, в_сборе: bool) -> int:
        """Отметкам, которые разрешают правила `app/miss.py`, — +1 к
        счётчику; вернёт, сколько из них этим погасло."""
        gone = 0
        for mark in marks:
            if not гашение.почему_нельзя(
                    source_id=mark["source_id"], channel_id=mark["channel_id"],
                    адрес=mark["source_url"] or "", start=start,
                    в_сборе=в_сборе):
                gone += _add_miss(conn, mark["id"])
        return gone

    # хвосты агрегаторов по каналам со своим сайтом — строки, которых в этом
    # файле уже не было (`Хозяева.дочистить`, там же почему гашение их не берёт)
    stats.not_own_dropped += хозяева.дочистить(conn)

    # Канал, подтверждённый у игры хоть одним сайтом, не гаснет ни от
    # какого сайта; остальные отметки игры — по правилам `app/miss.py`
    for event_id, seen in event_seen.items():
        marks = ",".join("?" * len(seen))
        stats.gone += погасить(conn.execute(
            "SELECT id, channel_id, source_id, source_url FROM event_channels "
            f"WHERE event_id = ? AND channel_id NOT IN ({marks})",
            (event_id, *seen)).fetchall(), event_start[event_id], bool(seen))

    # Трансляция турнира без пары («ATP 500 Tokyo — 1/4 Finale»,
    # `app/broadcast.py`) живёт, пока сайт не назовёт игроков: тогда в
    # файле приходит матч с именами, а заголовка в нём уже нет — и штраф
    # выше его не касается (он раздаётся только событиям из файла).
    # Заголовок висел рядом с матчами до конца трансляции (mojtv.hr,
    # #4145). Гасим его отметки от сайтов, которые в этом прогоне отдали
    # расписание на его день и заголовка не показали (владелец 04.10:
    # «появятся имена — должно обновиться») — по тем же правилам
    заголовки: set[int] = set()
    for r in conn.execute(
            "SELECT id, sport, team_home_auto, team_away_auto, start_kyiv "
            "FROM events WHERE sport = 'T' "
            "AND (flags IS NULL OR flags NOT LIKE 'fs:%')").fetchall():
        if r["id"] in event_seen or not broadcast.is_title(
                r["sport"], r["team_home_auto"] or "",
                r["team_away_auto"] or ""):
            continue
        заголовки.add(r["id"])
        stats.titles_gone += погасить(conn.execute(
            "SELECT id, channel_id, source_id, source_url FROM event_channels "
            "WHERE event_id = ?", (r["id"],)).fetchall(), r["start_kyiv"], True)
    # Сироты: будущие игры, которых в файле нет ВОВСЕ — ни один сайт их
    # не держит. Сайт перенёс матч на другой день (#5104 Motherwell —
    # Celtic, 09.10: teleman с субботы переставил на воскресенье), и старая
    # запись висела с живым каналом: штраф выше идёт только по событиям
    # файла, а правило 2 `miss.py` её не трогало. Слово владельца 09.10:
    # «если игра не встретилась — проверить её на сайте и снять, хотя бы
    # канал перечеркнуть». Проверка та же, что у всех: правила 3–6 — сайт
    # ответил, страница того же вида за день игры цела, игр на день дал
    # достаточно (правило 6 не даст погасить по неполному сбору)
    if punish and coverage is not None:
        for r in conn.execute(
                "SELECT DISTINCT e.id, e.start_kyiv FROM events e "
                "JOIN event_channels ec ON ec.event_id = e.id "
                "WHERE e.start_kyiv > ? AND ec.miss_count < ?",
                (collected or _iso(now), MISS_LIMIT)).fetchall():
            if r["id"] in event_seen or r["id"] in заголовки:
                continue
            stats.orphans_gone += погасить(conn.execute(
                "SELECT id, channel_id, source_id, source_url "
                "FROM event_channels WHERE event_id = ? AND miss_count < ?",
                (r["id"], MISS_LIMIT)).fetchall(), r["start_kyiv"], True)
    conn.commit()
    stats.not_own = sum(хозяева.пропущено.values())
    stats.not_own_note = хозяева.отчёт(stats.not_own_dropped)
    return stats


def _add_miss(conn: sqlite3.Connection, mark_id: int) -> int:
    """+1 к счётчику пропусков отметки; вернёт 1, если отметка этим
    погасла (дошла до `MISS_LIMIT`)."""
    conn.execute("UPDATE event_channels SET miss_count = miss_count + 1 "
                 "WHERE id = ?", (mark_id,))
    return int(conn.execute("SELECT miss_count FROM event_channels WHERE id = ?",
                            (mark_id,)).fetchone()[0] == MISS_LIMIT)


# ── срок жизни ───────────────────────────────────────────────────────────────

def purge_expired(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """Игру убирает только время: начало + грейс (ТЗ разд. 10). Историю не
    храним, поэтому удаление настоящее, вместе с каналами (каскад)."""
    now = now or datetime.now()
    graces = grace_map(conn)
    dead = [r["id"] for r in conn.execute(
        "SELECT id, sport, start_kyiv, grace_minutes FROM events")
        if _parse_dt(r["start_kyiv"])
        + timedelta(minutes=grace_for(r["sport"], r["grace_minutes"], graces)) < now]
    if dead:
        marks = ",".join("?" * len(dead))
        conn.execute(f"DELETE FROM events WHERE id IN ({marks})", dead)
    # техжурналы не копим вечно, иначе к зиме база распухнет (РИСКИ.md):
    # сырые страницы старше месяца и прогоны старше трёх — вон
    conn.execute("DELETE FROM raw_rows WHERE fetched_at < ?",
                 (_iso(now - timedelta(days=30)),))
    conn.execute("DELETE FROM runs WHERE started_at < ?",
                 (_iso(now - timedelta(days=90)),))
    # вкладка «Other Sport»: прошедшие дни не нужны (владелец 03.10)
    conn.execute("DELETE FROM other_sport WHERE start_kyiv < ?",
                 ((now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),))
    conn.commit()
    return len(dead)


# ── выборка для сайта ────────────────────────────────────────────────────────

def _badge(name: str, note: str | None, country: str | None,
           custom: int) -> str | None:
    """Что показать перед именем канала. Пусто — ничего не показываем.

    Пометку владельца показываем всегда, кроме случая, когда он вписал ту же
    приставку и в само название («NL| ESPN 3» с пометкой «NL») — иначе на
    витрине выходило «NL| NL| ESPN 3» (10.09). У автоматических имён перед
    названием стоит страна, как было заведено 05.09.
    """
    имя = (name or "").strip()
    метка = (note or "").strip()
    if метка:
        голова = имя.split("|", 1)[0].strip().upper()
        return None if голова == метка.upper() else метка
    return None if custom else country


def schedule(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict]:
    """Все живые игры по времени: прошедшие ещё в грейсе — с пометкой live.
    Фильтры и поиск накладывает страница — объём (сотни строк) это позволяет."""
    now = now or datetime.now()
    graces = grace_map(conn)
    # только бесспорные написания (пакет C, 14.09): «Dinamo» трёх клубов
    # витрина по словарю не называет — имя даёт канон игры
    from . import dictionary
    team_names = dictionary.team_overrides(conn)
    # переименование лиги действует сразу, не дожидаясь следующего импорта:
    # событие ещё держит league_auto, а показываем уже канон из алиаса
    league_names = dictionary.league_overrides(conn)

    # Что уже лежит в очереди на подтверждение (страница «Имена»): по этим
    # играм ответ найден, но ждёт вашего слова. Раньше витрина о них молчала,
    # и владелец узнавал о находке, только если сам открывал очередь
    # (жалоба 10.09) — теперь строка красится и ведёт прямо на запись.
    waiting: dict[tuple[str, str], int] = {}
    for r in conn.execute(
            "SELECT id, kind, raw_value FROM moderation "
            "WHERE status = 'open' AND kind IN ('team', 'league')"):
        waiting.setdefault((r["kind"], (r["raw_value"] or "").strip()), r["id"])

    # подсветка нового (просьба владельца 12.09): свежепоявившаяся игра
    # красится зелёным, канал, добавившийся к уже известной игре, получает
    # бейдж «new». `first_seen` в базе — UTC (datetime('now')), поэтому и
    # пороги считаем в UTC, а не от серверного `now`
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    game_edge = (utc_now - timedelta(hours=FRESH_GAME_HOURS)
                 ).strftime("%Y-%m-%d %H:%M:%S")
    channel_edge = (utc_now - timedelta(hours=FRESH_CHANNEL_HOURS)
                    ).strftime("%Y-%m-%d %H:%M:%S")

    def _dt(text: str):
        try:
            return datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return None

    games: list[dict] = []
    for row in conn.execute(
            "SELECT e.id, e.sport, e.league_auto, e.team_home_auto, "
            "e.team_away_auto, e.start_kyiv, e.grace_minutes, e.first_seen, "
            "e.seen, e.flags, e.league_id, l.canonical_name AS league_canon, "
            "l.slug AS league_slug, "
            "th.canonical_name AS home_canon, ta.canonical_name AS away_canon "
            "FROM events e "
            "LEFT JOIN leagues l ON l.id = e.league_id "
            "LEFT JOIN teams th ON th.id = e.team_home_id "
            "LEFT JOIN teams ta ON ta.id = e.team_away_id "
            "ORDER BY e.start_kyiv"):
        start = _parse_dt(row["start_kyiv"])
        ends = start + timedelta(
            minutes=grace_for(row["sport"], row["grace_minutes"], graces))
        if ends < now:
            continue

        def show(canon: str | None, raw: str | None) -> str:
            raw = (raw or "").strip()
            return canon or team_names.get(raw) or names.suggest_canonical(raw)

        def named(canon: str | None, raw: str | None) -> bool:
            """Есть ли у имени закреплённый канон (команда в базе или алиас).
            Нет — транслит-догадка: такие игры владелец смотрит фильтром
            «Names to fix» и правит кнопкой ✎."""
            return bool(canon or team_names.get((raw or "").strip()))

        channels = []
        # канал, докапавший счётчик пропаж: не прячем, а показываем на
        # витрине перечёркнутым «снят» (владелец 22.09, случай #3354);
        # API этот список не отдаёт
        gone_channels = []
        seen_channels: set[int] = set()
        # заголовки живых отметок — по ним сведённая трансляция турнира
        # узнаёт стадию («ATP Beijing — Quarterfinals»)
        live_titles: list[str] = []
        # источник моложе трёх дней — канал помечается на витрине «на
        # обкатке» (просьба владельца 05.09: новое должно быть видно;
        # порог в неделю метил 274 канала — проект сам моложе)
        new_edge = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        for r in conn.execute(
                "SELECT c.id, c.canonical_name AS name, c.country, "
                "       c.custom_name, c.note, ec.first_seen AS ch_first_seen, "
                "       ec.source_url, s.base_url, s.created_at, ec.time_off, "
                "       ec.miss_count, ec.seen AS ch_seen, ec.raw_title "
                "FROM event_channels ec "
                "JOIN channels c ON c.id = ec.channel_id "
                "LEFT JOIN sources s ON s.id = ec.source_id "
                "WHERE ec.event_id = ? "
                # живые отметки первыми: канал, подтверждённый хоть одним
                # сайтом, выходит живым, а не «снятым». Дальше как раньше:
                # тот же канал от двух сайтов — первой отметка с верным
                # временем, красная пометка остаётся только без подтверждения
                "ORDER BY (ec.miss_count >= ?), ec.time_off, ec.id",
                (row["id"], MISS_LIMIT)):
            if r["id"] in seen_channels:
                continue
            seen_channels.add(r["id"])
            gone = r["miss_count"] >= MISS_LIMIT
            if not gone:
                live_titles.append(r["raw_title"] or "")
            # снятую отметку владелец убрал кликом (seen=2) — не показываем;
            # вернись канал в расписание, он выйдет живым как ни в чём не бывало
            if gone and r["ch_seen"] == 2:
                continue
            (gone_channels if gone else channels).append(
                            {"id": r["id"], "name": r["name"],
                             # перед именем — пометка владельца, а если её
                             # нет, приставка страны у автоматических имён
                             # (правила 09.09 и 10.09). Она вне копируемого
                             # куска: клик берёт только само название
                             # пометка перед именем; если владелец вписал ту
                             # же приставку в само название, второй раз её не
                             # рисуем — но копируется название целиком, как
                             # он его написал (правило владельца 10.09)
                             "country": _badge(r["name"], r["note"],
                                               r["country"], r["custom_name"]),
                             "note": r["note"] or "",
                             # имя правил владелец — тогда копируем ровно
                             # его, без приставки (уточнение 10.09 к
                             # правилу 05.09 «канал копируется со страной»)
                             "custom": bool(r["custom_name"] or r["note"]),
                             "url": human_url(r["source_url"], r["base_url"]),
                             # сайт канала пишет другое время, чем flashscore
                             # (14.09) — красным, «перепроверить»
                             # у «снятого» канала служебные пометки гасим:
                             # осталась одна — «снят»
                             "time_off": bool(r["time_off"]) and not gone,
                             "new_source": bool(not gone and r["created_at"]
                                                and str(r["created_at"])
                                                >= new_edge),
                             # клик владельца по зелёному каналу — «прочитан»,
                             # бейдж «new» ему больше не рисуем (22.09)
                             "seen": bool(r["ch_seen"]),
                             # бейдж «new»: канал появился у игры недавно И
                             # заметно позже неё самой — то есть именно
                             # ДОБАВИЛСЯ, а не приехал вместе с игрой
                             # (правка владельца 12.09)
                             "new": bool(
                                 not gone
                                 and r["ch_first_seen"]
                                 and str(r["ch_first_seen"]) >= channel_edge
                                 and (ch_dt := _dt(str(r["ch_first_seen"])))
                                 and (ev_dt := _dt(str(row["first_seen"] or "")))
                                 and ch_dt - ev_dt >= FRESH_CHANNEL_GAP),
                             # то же самое, но БЕЗ срока: владельцу бейдж
                             # гаснет только его кликом (слово владельца
                             # 08.10: «чтоб метки не пропадали через время,
                             # а исчезали, если я клацнул на канал»).
                             # Гостю остаётся «new» по часам — он не кликает
                             "new_ever": bool(
                                 not gone
                                 and r["ch_first_seen"]
                                 and (ch_dt2 := _dt(str(r["ch_first_seen"])))
                                 and (ev_dt2 := _dt(str(row["first_seen"] or "")))
                                 and ch_dt2 - ev_dt2 >= FRESH_CHANNEL_GAP)})
        # Трансляция турнира без пары игроков («ATP 500 Tokyo — 1/4 Finale»,
        # `app/broadcast.py`): показываем одной строкой без «vs» и как сайт
        # написал — словарь тут только вредит («Tokyo» он знает как клуб).
        # Сайт назвал игроков — отметки заголовка гаснут (`save_games`), и
        # строка без живых каналов с витрины уходит (владелец 04.10)
        title = (not str(row["flags"] or "").startswith("fs:")
                 and broadcast.is_title(row["sport"], row["team_home_auto"] or "",
                                        row["team_away_auto"] or ""))
        if title and not channels:
            continue
        if title:
            # канал, чей сайт уже назвал игроков, переехал в строку матча —
            # в строке турнира его «снят» только путал бы (владелец 04.10:
            # «появятся имена — он перезапишет?»)
            gone_channels = []
        # запись очереди по этой игре: сперва команды, потом лига
        pending = None
        for kind, raw in (() if title else
                          (("team", row["team_home_auto"]),
                           ("team", row["team_away_auto"]),
                           ("league", row["league_auto"]))):
            pending = waiting.get((kind, (raw or "").strip()))
            if pending:
                break
        if title:
            # не латиница (иврит) — транслит, как у лиги ниже; латиницу не
            # трогаем: транслит ломал регистр («Atp 1000»)
            def plain(raw: str | None) -> str:
                raw = (raw or "").strip()
                return (names.suggest_canonical(raw)
                        if any(ord(c) > 0x2FF for c in raw) else raw)
            home_shown = plain(row["team_home_auto"])
            away_shown = plain(row["team_away_auto"])
            if row["team_away_auto"] == broadcast.SESSION:
                # сведённая трансляция: вместо служебной второй стороны —
                # стадия, если её назвал хоть один сайт (первая по отметкам)
                away_shown = next((s for s in map(broadcast.stage, live_titles)
                                   if s), "")
        else:
            home_shown = show(row["home_canon"], row["team_home_auto"])
            away_shown = show(row["away_canon"], row["team_away_auto"])
        games.append({
            "id": row["id"],
            "pending": pending or 0,
            "title": title,
            "sport": row["sport"],
            "league": (row["league_canon"]
                       or league_names.get((row["league_auto"] or "").strip())
                       # лига не переведена и написана не латиницей — хотя бы
                       # транслит, а не иврит как есть (владелец 15.09);
                       # латинскую не трогаем, чтобы не менять регистр
                       or (names.suggest_canonical(row["league_auto"])
                           if any(ord(c) > 0x2FF for c in row["league_auto"] or "")
                           else row["league_auto"] or "")),
            "league_id": row["league_id"],
            "league_slug": row["league_slug"] or "",
            "league_auto": row["league_auto"] or "",
            "home": home_shown,
            "away": away_shown,
            "home_auto": row["team_home_auto"] or "",
            "away_auto": row["team_away_auto"] or "",
            # заголовку турнира канон не нужен — в «Names to fix» не идёт
            "named": title or (named(row["home_canon"], row["team_home_auto"])
                               and named(row["away_canon"], row["team_away_auto"])),
            "start": start,
            "date": start.date(),
            "time": start.strftime("%H:%M"),
            "live": start <= now < ends,
            "first_seen": row["first_seen"] or "",
            "is_new": bool(row["first_seen"]
                           and str(row["first_seen"]) >= game_edge),
            # «непрочитанная»: висит новой, пока владелец не кликнет по строке
            # или не нажмёт «Прочитано всё» (21.09); гостям остаётся is_new
            "unread": not row["seen"],
            "channels": channels,
            # перечёркнутые «снят» — только витрине; API их не отдаёт
            "gone_channels": gone_channels,
        })
    return games


def load_games_json(path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("games", [])


#: Итоги обхода, которые считаем НЕИСПРАВНОСТЬЮ сайта. «Пусто» сюда не
#: входит: у сайта бывает пустой день, а счётчик меток времени вдобавок не
#: видит расписание в JSON (`programetv.ro`, `sport1.maariv.co.il` — 01.09
#: оба «пусты», хотя разбор дал строки). Ломается сайт тогда, когда страница
#: не открылась или вместо неё пришла заглушка защиты.
BROKEN_VERDICTS = ("не открылась", "заглушка защиты")
#: страница открылась, но матчей на ней не нашлось. Раньше такая строка шла
#: наравне с удачной, и сайт, переставший давать игры, годами числился
#: здоровым — «Молчат» на /broken пустовала (аудит 07.09, A6)
EMPTY_VERDICT = "пусто"
#: сайт публикует программу на меньший срок, чем наше окно обхода: дальние
#: дни он не отдаёт вовсе. Не успех и не поломка — такие строки в здоровье
#: источника не участвуют (владелец 23.09.2026, случай RTP Açores)
SHORT_DEPTH_VERDICT = "нет на этот день"


def _bare(domain: str) -> str:
    """`www.movistarplus.es` → `movistarplus.es`: в отчёте обхода домен идёт
    так, как он записан в адресе, а в базе — без `www.`. Без приведения
    здоровье источника не обновлялось вовсе (01.09)."""
    return (domain or "").strip().lower().removeprefix("www.")


def kyiv_from_utc(text: str) -> str:
    """Метка «собрано» из games.json (часы GitHub, UTC) → киевское время
    `ГГГГ-ММ-ДД ЧЧ:ММ`. Не разобрали — пусто."""
    from zoneinfo import ZoneInfo
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            made = datetime.strptime((text or "").strip(), fmt)
        except ValueError:
            continue
        return _iso(made.replace(tzinfo=timezone.utc)
                    .astimezone(ZoneInfo("Europe/Kyiv")))
    return ""


def _audit_for(folder: Path, crawled: str) -> dict | None:
    """Самопроверка прогона (`scripts/audit_run.py --json`, лежит рядом с
    `games.json` как `audit.json`) — в строку «Прогоны». Берём, только если
    она про этот же обход: метка «собрано» совпадает с заливаемой; иначе
    (старый файл рядом с новым сбором) — молчим, чужих подозрений не клеим."""
    try:
        data = json.loads((folder / "audit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if crawled and data.get("собрано") and data["собрано"] != crawled:
        return None
    разделы = [{"название": str(r.get("название") or ""),
                "строки": [str(x) for x in (r.get("строки") or [])]}
               for r in (data.get("разделы") or []) if isinstance(r, dict)]
    return {"подозрений": int(data.get("подозрений") or 0), "разделы": разделы}


def log_run(conn: sqlite3.Connection, report_path, stats: SaveStats,
            crawled: str = "", who: str = "") -> None:
    """Строка в `runs` и здоровье источников (ТЗ разд. 14): каждый импорт
    отмечает, кто из сайтов отработал, а кто нет. Отчёта нет — не беда,
    запишем только счётчики игр.

    `crawled` — метка «собрано» обхода (UTC). В отчёте обхода есть только
    дата, и на витрине три сбора за день выглядели одинаково: владелец
    просил видеть, какой сбор во сколько был (18.09). `who` — чей сбор,
    если не плановый GitHub: «сервер mojtv.hr»."""
    ok_by: dict[str, int] = {}          # страниц с расписанием
    empty_by: dict[str, int] = {}       # открылись, но матчей нет
    fail_by: dict[str, int] = {}        # не открылись вовсе
    why_by: dict[str, str] = {}         # чем сайт ответил: «HTTP 520», защита
    rows_found = 0
    when = kyiv_from_utc(crawled)
    mode = ""
    days = None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        when = when or report.get("когда", "")
        # «полный обход, окно 6 суток» / «скан даты 2026-09-13»: владелец
        # просил видеть в отчёте глубину и дату скана (09.09)
        mode = report.get("режим", "") or ""
        got = re.search(r"окно (\d+)", mode)
        if got:
            days = int(got.group(1))
        for row in report.get("строки", []):
            rows_found += 1
            domain = _bare(row["domain"])
            verdict = row.get("итог")
            if verdict == SHORT_DEPTH_VERDICT:
                continue          # дня у сайта просто нет — судить не о чем
            target = (fail_by if verdict in BROKEN_VERDICTS else
                      empty_by if verdict == EMPTY_VERDICT else ok_by)
            target[domain] = target.get(domain, 0) + 1
            # причину держим одну на домен: владелец 20.09 — «в отчёте нет
            # упоминания, что сайт не отдаёт расписание именно GitHub»
            if verdict in BROKEN_VERDICTS and domain not in why_by:
                why_by[domain] = " ".join(
                    f"{verdict}: {row.get('почему') or ''}".split())[:160]
    except (OSError, ValueError):
        pass
    # сколько строк парсер вытащил по каждому домену: страница бывает «пустой»
    # на один день и полной на другой, а разбор считает по всему прогону
    parsed: dict[str, int] = {}
    try:
        raw = json.loads((report_path.parent / "games.json")
                         .read_text(encoding="utf-8")).get("разобрано") or {}
        parsed = {_bare(d): int(n) for d, n in raw.items()}
    except (OSError, ValueError, AttributeError):
        pass
    #: сайт «отработал», если дал расписание хоть на одной странице или его
    #: строки дошли до разбора; ответил, но пусто — это «Молчит», не успех
    answered = set(ok_by) | set(empty_by)
    worked = {d for d in answered if ok_by.get(d) or parsed.get(d, 0)}
    silent = answered - worked
    log = {"режим": mode, "кто": who, "новых": stats.new,
           "обновлено": stats.updated,
           "сбои": fail_by,
           "сбои_почему": why_by,
           "молчат": sorted(silent)}
    # самопроверка прогона списком — владелец 06.10 («чтобы не ходить
    # кругами»); шаблон runs.html показывает её раскрывающимся списком
    audit = _audit_for(Path(report_path).parent, crawled)
    if audit is not None:
        log["самопроверка"] = audit
    conn.execute(
        "INSERT INTO runs (finished_at, window_days, sources_ok, "
        "sources_failed, rows_found, events_upserted, log) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (when or _iso(datetime.now()), days,
         len(worked), len(set(fail_by) - answered), rows_found,
         stats.new + stats.updated,
         json.dumps(log, ensure_ascii=False)))
    now = _iso(datetime.now())
    for domain in worked:
        conn.execute("UPDATE sources SET last_run = ?, last_success = ?, "
                     "fail_count = 0, status = 'ok' WHERE domain = ?",
                     (now, now, domain))
    # ответил, но матчей не дал: `last_success` не двигаем — по нему «Молчат»
    # и считает дни. Статус не трогаем: сломанным он от пустой страницы не
    # становится, но и здоровым его объявляет только настоящее расписание
    for domain in silent:
        conn.execute("UPDATE sources SET last_run = ?, fail_count = 0 "
                     "WHERE domain = ?", (now, domain))
    for domain in set(fail_by) - answered:
        conn.execute("UPDATE sources SET last_run = ?, "
                     "fail_count = fail_count + 1 WHERE domain = ?", (now, domain))
    # три сбоя подряд — источник на страницу «Сломанные» (ТЗ разд. 11);
    # закрытые не трогаем: они не сломаны, по ним есть решение владельца
    conn.execute("UPDATE sources SET status = 'broken' WHERE fail_count >= 3 "
                 "AND status NOT IN ('closed', 'broken')")
    conn.commit()


def save_other_sport(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Строки другого вида спорта из games.json (ключ «другие_виды») — во
    вкладку «Other Sport» админки (владелец 03.10). Без склейки и канона:
    одна строка на (сайт, канал, заголовок, время), повтор обновляет
    `last_seen`. Возвращает, сколько строк пришло."""
    now = _iso(datetime.now())
    n = 0
    for r in rows:
        if not (r.get("start_utc") and r.get("start_kyiv") and r.get("заголовок")):
            continue
        conn.execute(
            "INSERT INTO other_sport (sport_group, word, domain, channel, title, "
            "league, start_kyiv, start_utc, first_seen, last_seen, source_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (domain, channel, title, start_utc) DO UPDATE SET "
            "last_seen = excluded.last_seen, sport_group = excluded.sport_group, "
            "word = excluded.word, league = excluded.league, "
            "start_kyiv = excluded.start_kyiv, "
            # старый файл адреса не несёт — уже записанный не затираем
            "source_url = COALESCE(NULLIF(excluded.source_url, ''), source_url)",
            (r.get("вид") or "другое", (r.get("слово") or "")[:60],
             r.get("домен") or "", r.get("канал") or "", r["заголовок"][:200],
             (r.get("лига") or "")[:120], r["start_kyiv"], r["start_utc"],
             now, now, r.get("url") or ""))
        n += 1
    conn.commit()
    return n


def other_sport_schedule(conn: sqlite3.Connection,
                         now: datetime | None = None) -> list[dict]:
    """Публичная вкладка «Other Sport» витрины (владелец 03.10): строки
    другого вида спорта по времени. Та же программа на нескольких каналах
    (то же время, вид и заголовок) — одна строка с несколькими каналами.
    Начавшееся держим OTHER_SPORT_GRACE_MIN минут с пометкой live."""
    now = now or datetime.now()
    edge = (now - timedelta(minutes=OTHER_SPORT_GRACE_MIN)).strftime(
        "%Y-%m-%dT%H:%M")
    try:
        have = {r[1] for r in conn.execute("PRAGMA table_info(other_sport)")}
        rows = conn.execute(
            "SELECT sport_group, word, domain, channel, title, league, "
            "start_kyiv, "
            + ("source_url" if "source_url" in have else "'' AS source_url")
            + " FROM other_sport WHERE start_kyiv >= ? "
            "ORDER BY start_kyiv, sport_group, title, channel",
            (edge,)).fetchall()
    except sqlite3.OperationalError:
        return []          # таблицы ещё нет: база старше вкладки
    # Ссылка «открыть расписание канала» — тот же принцип, что у матчей
    # (`human_url`; владелец 04.10). Строки, залитые до правки, адреса
    # страницы не знают — им даём страницу расписания самого сайта
    base = {_bare(r["domain"]): r["base_url"] or "" for r in conn.execute(
        "SELECT domain, base_url FROM sources")}

    def link(domain: str, source_url: str | None) -> str:
        home = base.get(_bare(domain), "")
        p = urlsplit(home)
        # в base_url бывают старые даты из закладок — берём без query
        page = f"{p.scheme}://{p.netloc}{p.path}" if p.scheme else home
        return human_url(source_url, home) or page

    out: dict[tuple[str, str, str], dict] = {}
    for r in rows:
        key = (r["start_kyiv"], r["sport_group"], r["title"])
        item = out.get(key)
        if item is None:
            start = _parse_dt(r["start_kyiv"])
            item = out[key] = {
                "date": start.date(), "time": start.strftime("%H:%M"),
                "sport": r["sport_group"], "title": r["title"],
                "league": r["league"] or "", "live": start <= now,
                "channels": [], "words": [], "domains": [], "links": []}
        if r["channel"] and r["channel"] not in item["channels"]:
            item["links"].append({"name": r["channel"],
                                  "url": link(r["domain"], r["source_url"])})
        for field, value in (("channels", r["channel"]), ("words", r["word"]),
                             ("domains", r["domain"])):
            if value and value not in item[field]:
                item[field].append(value)
    return list(out.values())


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
обновляются, если пришли лучше. Канал, пропавший из источника, гаснет после
трёх неподтверждений (`event_channels.miss_count`), но игру не трогает.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from . import merge, names

# Грейс после начала, минуты (ТЗ разд. 10). Число-уговор, не измерение;
# правится в админке («Настройки»), здесь только значения по умолчанию.
GRACE_MINUTES = {"F": 130, "B": 190, "T": 240}
DEFAULT_GRACE = 240          # незнакомый спорт живёт по самому долгому правилу
MISS_LIMIT = 3               # канал гаснет после стольких неподтверждений
#: подсветка нового (правка владельца 12.09: «вчерашние игры уже не новые,
#: новые — только каналы, которые к ним добавились»): игра зелёная лишь
#: полсуток после первого появления, канальный бейдж живёт двое суток
FRESH_GAME_HOURS = 12        # сколько часов игра считается «новой»
FRESH_CHANNEL_HOURS = 48     # сколько часов «новым» считается добавленный канал
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
    from . import dictionary
    return dictionary.remember_channel(conn, raw, raw, country, source_id)


def _team_id(overrides_ids: dict[str, int], raw: str) -> int | None:
    return overrides_ids.get((raw or "").strip())


def _team_ids(conn: sqlite3.Connection) -> dict[str, int]:
    return {r["alias"]: r["team_id"] for r in conn.execute(
        "SELECT alias, team_id FROM team_aliases")}


def _league_ids(conn: sqlite3.Connection) -> dict[str, int]:
    # и алиасы, и сами канонические имена: игра приходит уже с каноном
    out = {r["canonical_name"]: r["id"] for r in conn.execute(
        "SELECT id, canonical_name FROM leagues")}
    out.update({r["alias"]: r["league_id"] for r in conn.execute(
        "SELECT alias, league_id FROM league_aliases")})
    return out


def save_games(conn: sqlite3.Connection, games: list[dict],
               now: datetime | None = None, punish: bool = True,
               worked: set[str] | None = None,
               punish_until: str = "") -> SaveStats:
    """Вливает игры из `games.json`. Формат: список словарей с полями
    sport / league / home / away / start_kyiv / start_utc / entries,
    где entries — строки по сайтам: source / channel / url / raw_title.

    `punish=False` — повторная заливка того же файла: каналы, не
    подтверждённые им, счётчик погашения не получают (05.09 три ручные
    заливки одного прогона накрутили miss_count до 3, и 14 живых каналов
    Интер - Наполи погасли).

    `worked` — домены, реально отработавшие в этом прогоне (из отчёта
    обхода), `punish_until` — последний скачанный день `ГГГГ-ММ-ДД`. Вместе
    они не дают короткому прогону погасить чужие каналы (аудит 07.09, A7):
    вечерняя дозаправка ходит на 2 дня, и раньше каналы субботней игры,
    которых в этом файле нет, получали счётчик погашения и через три захода
    пропадали с витрины. Лежащий сайт наказывать тоже не за что — он в
    `worked` не попадёт. `worked=None` — прежнее поведение."""
    now = now or datetime.now()
    stats = SaveStats()
    graces = grace_map(conn)
    # подтверждённые каналы копим ПО СОБЫТИЮ за весь файл, а штраф
    # раздаём после всех игр: один матч бывает в файле ДВУМЯ играми
    # (пока словарь не связал написания — «Wolverhampton» и «Wolves»),
    # обе находят одно событие, и раньше каждая гасила каналы другой —
    # SPORT TV + у Шеффилд - Вулвз докапал так до порога и пропал с
    # витрины (владелец 12.09: «затирает каналы, которые раньше были»)
    event_seen: dict[int, set[int]] = {}
    event_punish: dict[int, bool] = {}
    srcs = _sources_by_domain(conn)
    # id источников, которым позволено гасить чужие отметки в этом прогоне
    worked_ids: set[int] = set()
    if worked is not None:
        for domain, row in srcs.items():
            if _bare(domain) in {_bare(d) for d in worked}:
                worked_ids.add(row["id"])
    team_ids, league_ids = _team_ids(conn), _league_ids(conn)

    for game in games:
        # игра из файла, чьё время уже вышло, в базу не идёт — иначе старый
        # games.json воскрешает то, что срок жизни уже убрал
        if _parse_dt(game["start_kyiv"]) + timedelta(
                minutes=grace_for(game.get("sport", ""), None, graces)) < now:
            continue
        found = _find_event(conn, game)
        if found is None and game.get("guess") and _earlier_show(conn, game):
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
            seen_channel_ids.add(channel_id)
            conn.execute(
                "INSERT INTO event_channels (event_id, channel_id, source_id, "
                "source_url, raw_title, last_seen, miss_count) "
                "VALUES (?, ?, ?, ?, ?, ?, 0) "
                "ON CONFLICT (event_id, channel_id, source_id) DO UPDATE SET "
                "last_seen = excluded.last_seen, miss_count = 0, "
                "source_url = excluded.source_url",
                (event_id, channel_id,
                 source["id"] if source else None,
                 entry.get("url") or "", entry.get("raw_title") or "",
                 _iso(now)))
            stats.channels += 1
        # каналы игры, не подтверждённые этим прогоном, — на счётчик
        # (только когда файл свежий, см. punish в шапке); сам штраф — после
        # всех игр файла, когда набор подтверждённых у события полон
        deep = bool(punish_until) and start_kyiv[:10] > punish_until
        event_seen.setdefault(event_id, set()).update(seen_channel_ids)
        if seen_channel_ids and not deep:
            event_punish[event_id] = True

    if punish and (worked is None or worked_ids):
        for event_id, seen in event_seen.items():
            if not event_punish.get(event_id) or not seen:
                continue
            marks = ",".join("?" * len(seen))
            sql = (f"UPDATE event_channels SET miss_count = miss_count + 1 "
                   f"WHERE event_id = ? AND channel_id NOT IN ({marks})")
            params: list = [event_id, *seen]
            if worked is not None:
                # прогон не видел этот сайт — и гасить его отметки не вправе
                sql += " AND source_id IN (" + ",".join("?" * len(worked_ids)) + ")"
                params += list(worked_ids)
            conn.execute(sql, params)
    conn.commit()
    return stats


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
    team_names = {r["alias"]: r["canonical_name"] for r in conn.execute(
        "SELECT a.alias, t.canonical_name FROM team_aliases a "
        "JOIN teams t ON t.id = a.team_id")}
    # переименование лиги действует сразу, не дожидаясь следующего импорта:
    # событие ещё держит league_auto, а показываем уже канон из алиаса
    league_names = {r["alias"]: r["canonical_name"] for r in conn.execute(
        "SELECT a.alias, l.canonical_name FROM league_aliases a "
        "JOIN leagues l ON l.id = a.league_id")}

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
            "e.league_id, l.canonical_name AS league_canon, "
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
        seen_channels: set[int] = set()
        # источник моложе трёх дней — канал помечается на витрине «на
        # обкатке» (просьба владельца 05.09: новое должно быть видно;
        # порог в неделю метил 274 канала — проект сам моложе)
        new_edge = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        for r in conn.execute(
                "SELECT c.id, c.canonical_name AS name, c.country, "
                "       c.custom_name, c.note, ec.first_seen AS ch_first_seen, "
                "       ec.source_url, s.base_url, s.created_at "
                "FROM event_channels ec "
                "JOIN channels c ON c.id = ec.channel_id "
                "LEFT JOIN sources s ON s.id = ec.source_id "
                "WHERE ec.event_id = ? AND ec.miss_count < ? "
                "ORDER BY ec.id", (row["id"], MISS_LIMIT)):
            if r["id"] in seen_channels:
                continue
            seen_channels.add(r["id"])
            channels.append({"id": r["id"], "name": r["name"],
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
                             "new_source": bool(r["created_at"]
                                                and str(r["created_at"])
                                                >= new_edge),
                             # бейдж «new»: канал появился у игры недавно И
                             # заметно позже неё самой — то есть именно
                             # ДОБАВИЛСЯ, а не приехал вместе с игрой
                             # (правка владельца 12.09)
                             "new": bool(
                                 r["ch_first_seen"]
                                 and str(r["ch_first_seen"]) >= channel_edge
                                 and (ch_dt := _dt(str(r["ch_first_seen"])))
                                 and (ev_dt := _dt(str(row["first_seen"] or "")))
                                 and ch_dt - ev_dt >= FRESH_CHANNEL_GAP)})
        # запись очереди по этой игре: сперва команды, потом лига
        pending = None
        for kind, raw in (("team", row["team_home_auto"]),
                          ("team", row["team_away_auto"]),
                          ("league", row["league_auto"])):
            pending = waiting.get((kind, (raw or "").strip()))
            if pending:
                break
        games.append({
            "id": row["id"],
            "pending": pending or 0,
            "sport": row["sport"],
            "league": (row["league_canon"]
                       or league_names.get((row["league_auto"] or "").strip())
                       or row["league_auto"] or ""),
            "league_id": row["league_id"],
            "league_slug": row["league_slug"] or "",
            "league_auto": row["league_auto"] or "",
            "home": show(row["home_canon"], row["team_home_auto"]),
            "away": show(row["away_canon"], row["team_away_auto"]),
            "home_auto": row["team_home_auto"] or "",
            "away_auto": row["team_away_auto"] or "",
            "named": (named(row["home_canon"], row["team_home_auto"])
                      and named(row["away_canon"], row["team_away_auto"])),
            "start": start,
            "date": start.date(),
            "time": start.strftime("%H:%M"),
            "live": start <= now < ends,
            "first_seen": row["first_seen"] or "",
            "is_new": bool(row["first_seen"]
                           and str(row["first_seen"]) >= game_edge),
            "channels": channels,
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


def _bare(domain: str) -> str:
    """`www.movistarplus.es` → `movistarplus.es`: в отчёте обхода домен идёт
    так, как он записан в адресе, а в базе — без `www.`. Без приведения
    здоровье источника не обновлялось вовсе (01.09)."""
    return (domain or "").strip().lower().removeprefix("www.")


def log_run(conn: sqlite3.Connection, report_path, stats: SaveStats) -> None:
    """Строка в `runs` и здоровье источников (ТЗ разд. 14): каждый импорт
    отмечает, кто из сайтов отработал, а кто нет. Отчёта нет — не беда,
    запишем только счётчики игр."""
    ok_by: dict[str, int] = {}          # страниц с расписанием
    empty_by: dict[str, int] = {}       # открылись, но матчей нет
    fail_by: dict[str, int] = {}        # не открылись вовсе
    rows_found = 0
    when = ""
    mode = ""
    days = None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        when = report.get("когда", "")
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
            target = (fail_by if verdict in BROKEN_VERDICTS else
                      empty_by if verdict == EMPTY_VERDICT else ok_by)
            target[domain] = target.get(domain, 0) + 1
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
    conn.execute(
        "INSERT INTO runs (finished_at, window_days, sources_ok, "
        "sources_failed, rows_found, events_upserted, log) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (when or _iso(datetime.now()), days,
         len(worked), len(set(fail_by) - answered), rows_found,
         stats.new + stats.updated,
         json.dumps({"режим": mode, "новых": stats.new,
                     "обновлено": stats.updated,
                     "сбои": fail_by,
                     "молчат": sorted(silent)}, ensure_ascii=False)))
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

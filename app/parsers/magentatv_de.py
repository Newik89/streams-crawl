# -*- coding: utf-8 -*-
"""magentatv.de — телегид немецкого MagentaTV (Telekom), каналы MagentaSport 1–18.

Слово владельца 27–28.11.2026 (книга 183): «почему нет информации с немецких
Magenta Sport 10, 11 – 18», имена каналов — «DE| Magenta Sport 1-18». На сайте
MagentaSport номеров каналов нет; они есть только в телегиде MagentaTV, где
каналы зовутся «Sport 1 - myTeamTV» … «Sport 18 - myTeamTV».

Данные — ручка телегида, один запрос на канал, окно задаётся в теле запроса:

    POST https://api.prod.sngtv.magentatv.de/EPG/JSON/PlayBillList?channel_id=550
    {"channelid": "550", "begintime": "20261128000000", "endtime": "20261205000000", …}

Пускает только в гостевой сессии — её открывает `app/fetch.py`
(`SESSION_HOSTS`). Ответ: `{"playbilllist": [{"name", "introduce", "channelid",
"starttime": "2026-11-27 17:15:00 UTC+00:00", "endtime", "genres"}]}`.

Правила разбора:
  Р1. Канал — по номеру записи (`channelid`), иначе по номеру в адресе
      (`channel_id=`); имя — как в телегиде (`CHANNELS`). Каким каналом базы
      оно станет («DE| Magenta Sport 1»), решает сервер по написанию.
  Р2. Время — UTC из ответа, переводится в пояс источника.
  Р3. Заглушки канала («myTeamTV: Momentan kein Programm», «MagentaSport
      Programmübersicht») — не передачи, пропускаются.
  Р4. Прямой показ сайт помечает сам приставкой «LIVE:» — это слово сайта
      (`site_says`); без приставки сайт об эфире молчит (повторы на «MS Sport»).
  Р5. Пара — после ПОСЛЕДНЕГО двоеточия названия, через « - »: «LIVE: Tipico
      Topspiel der Woche: Hansa Rostock - TSV Havelse». Нет « - » — пары нет.
  Р6. Турнир и вид спорта — из описания (`introduce`): «Lettland - Deutschland,
      Basketball, FIBA World Cup Qualifiers Spieltag 3» → вид спорта «Basketball»,
      турнир «FIBA World Cup Qualifiers» (сезон «2026/2027» и номер тура
      «Spieltag 3» турниром не считаются). Вид спорта ещё и из жанра (`genres`);
      общее слово «Sport» видом спорта не считается.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from . import Program, register, site_says

DOMAIN = "magentatv.de"
TZ = "Europe/Berlin"

#: номер канала в ручке (`contentId`) → имя в телегиде. Список — из ручки
#: `AllChannel` (проба 28.11.2026): «Sport N - myTeamTV» — это и есть каналы
#: MagentaSport N; «MS Sport» — круглосуточный канал MagentaSport (прямые
#: показы и повторы), «MagentaSport» — одна заглушка, «MS GOLF» — гольф
CHANNELS = {
    "550": "Sport 1 - myTeamTV", "548": "Sport 2 - myTeamTV", "549": "Sport 3 - myTeamTV",
    "648": "Sport 4 - myTeamTV", "645": "Sport 5 - myTeamTV", "647": "Sport 6 - myTeamTV",
    "646": "Sport 7 - myTeamTV", "623": "Sport 8 - myTeamTV", "626": "Sport 9 - myTeamTV",
    "624": "Sport 10 - myTeamTV", "625": "Sport 11 - myTeamTV", "627": "Sport 12 - myTeamTV",
    "629": "Sport 13 - myTeamTV", "628": "Sport 14 - myTeamTV", "367": "Sport 15 - myTeamTV",
    "366": "Sport 16 - myTeamTV", "369": "Sport 17 - myTeamTV", "3686": "Sport 18 - myTeamTV",
    "3757": "MS Sport", "5075": "MagentaSport", "6947": "MS GOLF 1", "6946": "MS GOLF 2",
}

#: Р3: заглушки канала вместо программы (сравнение без регистра)
PLACEHOLDERS = ("myteamtv: momentan kein programm", "magentasport programmübersicht")

_LIVE = re.compile(r"^\s*live\s*:\s*", re.I)
#: Р6: что в описании не турнир — сезон и номер тура
_SEASON = re.compile(r"^\d{4}\s*/\s*\d{2,4}$")
_ROUND = re.compile(r"\s*\bSpieltag\s+\d+\s*$", re.I)


def _moment(text: str) -> datetime | None:
    """Р2: `2026-11-27 17:15:00 UTC+00:00` → момент в UTC."""
    try:
        return datetime.strptime(str(text)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _pair(name: str) -> str:
    """Р5: пара команд из названия без приставки эфира; нет — пробел."""
    tail = name.rpartition(":")[2].strip()
    home, sep, away = tail.partition(" - ")
    if sep and home.strip() and away.strip():
        return f"{home.strip()} - {away.strip()}"
    return " "


def _sport(genres: str) -> list[str]:
    """Р6: слова вида спорта из жанра; общее «Sport» — не вид спорта."""
    return [g.strip() for g in str(genres or "").split(",")
            if g.strip() and g.strip().casefold() != "sport"]


def _league(introduce: str, name: str, sports: list[str]) -> tuple[str, str]:
    """Р6: (турнир, вид спорта из описания). Описание — «<название>, [вид
    спорта,] <турнир> [Spieltag N]»; куски делит «, »."""
    text = " ".join(str(introduce or "").split())
    if text.casefold().startswith(name.casefold()):
        text = text[len(name):]
    known = {s.casefold() for s in sports} | {"fußball", "fussball", "basketball", "eishockey",
                                              "handball", "golf", "tennis", "volleyball"}
    league, sport = "", ""
    for part in (p.strip() for p in text.split(",")):
        if not part or _SEASON.match(part):
            continue
        if part.casefold() in known:
            sport = part
            continue
        # турнир — ПЕРВЫЙ подходящий кусок: за ним идёт стадия («PENNY DEL,
        # Hauptrunde Spieltag 20»), она турниром не считается
        league = league or _ROUND.sub("", part).strip()
    return league, sport


@register(DOMAIN)
def parse(html: str, *, day=None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = json.loads(html)
    except ValueError:
        return []
    shows = data.get("playbilllist") if isinstance(data, dict) else None
    if not isinstance(shows, list):
        return []
    zone = ZoneInfo(tz or TZ)
    asked = (parse_qs(urlsplit(url).query).get("channel_id") or [""])[0]

    out: list[Program] = []
    for show in shows:
        if not isinstance(show, dict):
            continue
        cid = str(show.get("channelid") or asked)
        channel = CHANNELS.get(cid) or CHANNELS.get(asked) or f"MagentaTV {cid}"      # Р1
        if channels and channel not in channels:
            continue
        title = " ".join(str(show.get("name") or "").split())
        moment = _moment(show.get("starttime"))
        if not title or moment is None or title.casefold() in PLACEHOLDERS:             # Р3
            continue
        start = moment.astimezone(zone)                                                 # Р2
        live = bool(_LIVE.match(title))                                                 # Р4
        name = _LIVE.sub("", title)
        sports = _sport(show.get("genres"))
        league, said = _league(show.get("introduce"), name.rpartition(":")[2].strip(), sports)
        program = Program(
            channel_raw=channel, title=title, start=start,
            raw_time=start.strftime("%H:%M"),
            description=" ".join(str(show.get("introduce") or "").split())[:300],
            league_raw=league[:120],
            sport_raw=" ".join(dict.fromkeys(sports + ([said] if said else [])))[:80],
            match_raw=_pair(name), source_url=url,
            extra={"day": start.date().isoformat(), "cid": cid},
        )
        out.append(site_says(program, True if live else None))
    return out

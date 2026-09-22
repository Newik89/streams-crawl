# -*- coding: utf-8 -*-
r"""ipko.tv — Косово, IPKO (платформа titan/Telekom Slovenije): открытый JSON.

Сайт-приложение: страница пустая, расписание отдаёт шлюз `stargate.ipko.tv`
(нашлось в `chunk-common.js`: `window.__endpoint__` + ручки `titan.tv.WebEpg`).
Ключей не требует, хватает заголовков Origin/Referer.

Список каналов (219, из них группа Sport — 28):

    POST https://stargate.ipko.tv/api/titan.tv.WebEpg/ZapList        {}

Расписание канала за сутки (даты можно строками — проверено 22.09):

    POST …/api/titan.tv.WebEpg/GetWebEpgData
         {"ch_ext_id": "rtk-1", "from": "1789977600", "to": "1790064000"}

Ответ:

    {"shows": [{"title": "Aktual", "show_start": 1789975800,
                "show_end": 1789979100, "timestamp": "9:30 - 10:25",
                "genres": ["futboll"], "categories": "Sport",
                "summary": "…", "is_live": false}]}

`show_start` — абсолютные секунды (epoch), пояс не нужен. Имени канала в
ответе нет — берём slug из адреса запроса (`?channel_id=rtk-1`), имена — по
`NAMES` из ZapList. Признак эфира сайт не даёт (`is_live` — «идёт сейчас»),
поэтому эфир определяем первым показом пары (`REPEAT_GUESS_DOMAINS`).
"""

from __future__ import annotations

import json
import re
from datetime import date as _date, datetime, timezone

from . import Program, mark_first_show, register

DOMAIN = "ipko.tv"

_ID = re.compile(r"[?&]channel_id=([a-z0-9-]+)")

#: имена каналов по slug из ZapList (22.09.2026): группа Sport целиком + RTK 1
NAMES = {
    "rtk-1": "RTK 1",
    "sport-1": "Sport 1", "sport-2": "Sport 2", "sport-3": "Sport 3",
    "sport-4": "Sport 4", "sport-5": "Sport 5", "sport-6": "Sport 6",
    "k-sport-1": "K-Sport 1", "k-sport-2": "K-Sport 2",
    "k-sport-3": "K-Sport 3", "k-sport-4": "K-Sport 4",
    "kb-peja": "KB Peja", "trt-spor": "TRT Spor", "a-spor": "A Spor",
    "tring-sport-news": "Tring Sport News",
    "supersport-1": "SuperSport 1", "supersport-2": "SuperSport 2",
    "supersport-3": "SuperSport 3", "supersport-4": "SuperSport 4",
    "supersport-5": "SuperSport 5", "supersport-6": "SuperSport 6",
    "supersport-7": "SuperSport 7",
    "tring-sport-1": "Tring Sport 1", "tring-sport-2": "Tring Sport 2",
    "tring-sport-3": "Tring Sport 3", "tring-sport-4": "Tring Sport 4",
    "tring-sport-5": "Tring Sport 5", "tring-sport-6": "Tring Sport 6",
    "tring-sport-7": "Tring Sport 7",
}

#: албанская пара пишется и через « - », и через « vs », и с «ndaj» (против)
_SEPS = (" - ", " – ", " — ", " vs ", " ndaj ")

#: у турецких каналов ipko (A Spor) лига приклеена к паре без двоеточия:
#: «UEFA Kadınlar Şampiyonlar Ligi Futbol Karşılaşması Barcelona - Paris FC»
#: — всё до слова «матч» (tr/sq) к именам не относится
_PREFIX = re.compile(r"^.*\b(karşılaşması|karşılaşma|ndeshja|ndeshje)\s+",
                     re.I)


def _pair(text: str) -> str:
    """Пара команд из заголовка или описания: `Futboll: Prishtina - Drita`."""
    # лига/вид спорта до двоеточия к паре не относится
    text = text.split(":", 1)[-1] if ":" in text else text
    text = _PREFIX.sub("", text)
    for part in text.split(","):
        part = part.strip()
        for sep in _SEPS:
            if sep in part:
                home, _, away = part.partition(sep)
                # дефис без пробелов не трогаем — про это ГРАБЛИ (TIKI-TAKA)
                if home.strip() and away.strip():
                    return f"{home.strip()} - {away.strip()}"
    return " "


@register(DOMAIN)
@register("stargate.ipko.tv")
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    try:
        data = json.loads(html)
    except ValueError:
        return []
    shows = data.get("shows") if isinstance(data, dict) else None
    if not isinstance(shows, list):
        return []

    got = _ID.search(url or "")
    channel = NAMES.get(got.group(1), got.group(1)) if got else DOMAIN
    if channels and channel not in channels:
        return []

    out: list[Program] = []
    for show in shows:
        if not isinstance(show, dict):
            continue
        title = " ".join((show.get("title") or "").split())
        stamp = show.get("show_start")
        if not title or not isinstance(stamp, (int, float)):
            continue
        start = datetime.fromtimestamp(int(stamp), tz=timezone.utc)
        genres = [g for g in (show.get("genres") or []) if g]
        категория = " ".join((show.get("categories") or "").split())
        about = " ".join((show.get("summary") or "").split())
        pair = _pair(title)
        if not pair.strip():
            pair = _pair(about)
        out.append(Program(
            channel_raw=channel, title=title,
            start=start, raw_time=start.strftime("%H:%M"),
            description=about[:300],
            league_raw=(genres[0] if genres else "")[:120],
            sport_raw=" ".join(genres + [категория])[:60],
            match_raw=pair,
            source_url=url, extra={"day": start.date().isoformat()},
        ))
    # слова эфира у сайта нет — эфиром считается первый показ пары
    return mark_first_show(out, "drejtpërdrejt")

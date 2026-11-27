# -*- coding: utf-8 -*-
"""ПРОБА, НЕ ИСТОЧНИК. Ветка `proba-magentatv` — в main НЕ СЛИВАТЬ (слово владельца 28.11.2026: «да» на пробу
телегида; подключение источника — отдельным словом).

Вопрос пробы: есть ли в телегиде немецкого MagentaTV (Telekom) сетка каналов MagentaSport с НОМЕРАМИ 1–18
(в телегиде они названы «Sport 1 - myTeamTV» … «Sport 18 - myTeamTV») и что в ней написано.

Как ходит (по описанию из открытого репозитория iptv-org/epg, `sites/web.magentatv.de`):
1. гостевой вход `Authenticate` — БЕЗ аккаунта и пароля: такую сессию сайт открывает любому посетителю
   (`userType: 3`); в ответ — куки и `csrfToken`, он едет дальше заголовком `X_CSRFToken`;
2. `AllChannel` — список каналов;
3. `PlayBillList` — программа одного канала за окно; один запрос на канал.
Всего ~22 запроса с паузой 3 с. Ключ сессии никуда не пишется (в файле ответа он затёрт).

Ответы кладёт в `<out>/magentatv/` — папка едет в архив страниц прогона. Никогда не роняет обход: любая ошибка —
строкой в `oshibki.txt`.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.prod.sngtv.magentatv.de/EPG/JSON/"
SITE = "https://web.magentatv.de"
PAUSE = 3.0
TIMEOUT = 30
AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")
#: тело гостевого входа — слово в слово как у iptv-org/epg
GUEST = {"terminalid": "00:00:00:00:00:00", "mac": "00:00:00:00:00:00", "terminaltype": "WEBTV",
         "utcEnable": 1, "timezone": "Etc/GMT0", "userType": 3, "terminalvendor": "Unknown"}
#: список каналов: П1 — полные записи (нужен номер канала в пакете); П2 — узкий запрос iptv-org, если П1 не дал списка
CHANNELS_FULL = {"channelNamespace": 2, "filterlist": [{"key": "IsHide", "value": "-1"}],
                 "metaDataVer": "Channel/1.1", "returnSatChannel": 0}
CHANNELS_NARROW = {**CHANNELS_FULL, "properties": [
    {"include": "/channellist/logicalChannel/contentId,/channellist/logicalChannel/name",
     "name": "logicalChannel"}]}
#: каналы пробы: «Sport N - myTeamTV» (это и есть MagentaSport N), общий «MagentaSport», «MS Sport»
WANTED = re.compile(r"(?i)^\s*sport\s*\d+\s*-\s*myteamtv|magenta\s*sport|^\s*ms\s+sport")
#: запас, если имена в списке изменились: номера каналов из списка iptv-org (Sport 1–18, MS Sport)
KNOWN = {"550": "Sport 1 - myTeamTV", "548": "Sport 2 - myTeamTV", "549": "Sport 3 - myTeamTV",
         "648": "Sport 4 - myTeamTV", "645": "Sport 5 - myTeamTV", "647": "Sport 6 - myTeamTV",
         "646": "Sport 7 - myTeamTV", "623": "Sport 8 - myTeamTV", "626": "Sport 9 - myTeamTV",
         "624": "Sport 10 - myTeamTV", "625": "Sport 11 - myTeamTV", "627": "Sport 12 - myTeamTV",
         "629": "Sport 13 - myTeamTV", "628": "Sport 14 - myTeamTV", "367": "Sport 15 - myTeamTV",
         "366": "Sport 16 - myTeamTV", "369": "Sport 17 - myTeamTV", "3686": "Sport 18 - myTeamTV",
         "3757": "MS Sport"}
FIELDS = "endtime,genres,id,name,starttime,channelid,introduce,subName"
DAYS = 3          # окно: сегодня по UTC и ещё двое суток


def run(out: Path) -> None:
    """Вся проба. Пишет ответы в `out/magentatv/`, сводку — туда же и на экран."""
    import requests

    folder = Path(out) / "magentatv"
    folder.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    errors: list[str] = []
    session = requests.Session()
    session.headers.update({"User-Agent": AGENT, "Accept": "application/json, text/plain, */*",
                            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
                            "Origin": SITE, "Referer": SITE + "/"})
    last = [0.0]

    def ask(name: str, path: str, body, params=None, extra=None, raw_body=False):
        """Один POST с паузой. Ответ — разобранный JSON или None; текст ответа — в файл `name`."""
        left = PAUSE - (time.monotonic() - last[0])
        if last[0] and left > 0:
            time.sleep(left)
        last[0] = time.monotonic()
        try:
            if raw_body:          # тело строкой, как шлёт iptv-org (axios): тип — «поля формы»
                answer = session.post(API + path, params=params, data=json.dumps(body), timeout=TIMEOUT,
                                      headers={"Content-Type": "application/x-www-form-urlencoded",
                                               **(extra or {})})
            else:
                answer = session.post(API + path, params=params, json=body, timeout=TIMEOUT,
                                      headers=extra or {})
        except Exception as exc:                      # сеть, таймаут, DNS
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            return None
        text = answer.text
        try:
            data = answer.json()
        except Exception:
            data = None
        if isinstance(data, dict) and data.get("csrfToken"):
            text = text.replace(str(data["csrfToken"]), "…ключ сессии затёрт…")
        (folder / name).write_text(text, encoding="utf-8")
        if answer.status_code != 200:
            errors.append(f"{name}: HTTP {answer.status_code}, {len(text)} знаков")
        return data

    # 1. гостевой вход: сперва обычным JSON, не дал ключа — телом-строкой, как у iptv-org
    token = ""
    for attempt, raw in ((1, False), (2, True)):
        data = ask(f"authenticate_{attempt}.json", "Authenticate", GUEST,
                   params={"SID": "firstup", "T": "Windows_chrome_118"}, raw_body=raw)
        token = str((data or {}).get("csrfToken") or "")
        notes.append(f"гостевой вход, попытка {attempt}: ключ {'получен' if token else 'НЕ получен'}, "
                     f"куки: {sorted(session.cookies.keys())}, "
                     f"retcode {(data or {}).get('retcode')!r} {(data or {}).get('desc') or ''}")
        if token:
            break
    auth = {"X_CSRFToken": token} if token else {}

    # 2. список каналов
    channels: list[dict] = []
    for name, body in (("allchannel_full.json", CHANNELS_FULL), ("allchannel_narrow.json", CHANNELS_NARROW)):
        data = ask(name, "AllChannel", body, extra=auth)
        channels = [c for c in ((data or {}).get("channellist") or []) if isinstance(c, dict)]
        notes.append(f"{name}: каналов {len(channels)}, retcode {(data or {}).get('retcode')!r} "
                     f"{(data or {}).get('desc') or ''}")
        if channels:
            notes.append("  поля канала: " + ", ".join(sorted(channels[0].keys())))
            break
    wanted = {str(c.get("contentId")): str(c.get("name") or "") for c in channels
              if WANTED.search(str(c.get("name") or ""))}
    if not wanted:
        notes.append("каналы пробы в списке по имени не нашлись — беру номера из списка iptv-org")
        wanted = dict(KNOWN)
    sporty = sorted({str(c.get("name") or "") for c in channels
                     if re.search(r"(?i)sport|dazn|dyn|fussball|fußball|golf|motor|racing|tennis|nba|nfl|"
                                  r"myteam|more than sports", str(c.get("name") or ""))})
    notes.append(f"каналы со спортом в названии ({len(sporty)}): " + " | ".join(sporty))

    # 3. программа каналов пробы: окно — сегодня по UTC и ещё двое суток, один запрос на канал
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    begin, end = start.strftime("%Y%m%d000000"), (start + timedelta(days=DAYS)).strftime("%Y%m%d000000")
    notes.append(f"окно программы (UTC): {begin} – {end}; каналов пробы: {len(wanted)}")

    def order(item):
        number = re.search(r"\d+", item[1])
        return (0 if "myteam" in item[1].lower() else 1, int(number.group()) if number else 0, item[1])

    for content_id, title in sorted(wanted.items(), key=order):
        data = ask(f"playbill_{content_id}.json", "PlayBillList",
                   {"count": -1, "isFillProgram": 1, "offset": 0, "type": 2, "begintime": begin,
                    "endtime": end, "channelid": content_id,
                    "properties": [{"include": FIELDS, "name": "playbill"}]}, extra=auth)
        shows = [p for p in ((data or {}).get("playbilllist") or []) if isinstance(p, dict)]
        notes.append(f"\n[{title}] id {content_id}: передач {len(shows)}"
                     + ("" if shows else f", retcode {(data or {}).get('retcode')!r} {(data or {}).get('desc') or ''}"))
        for show in shows[:60]:
            notes.append(f"   {show.get('starttime')} – {str(show.get('endtime') or '')[11:16]}  "
                         f"{show.get('name')}" + (f" | {show.get('subName')}" if show.get("subName") else ""))

    if errors:
        notes.append("\nОШИБКИ:\n" + "\n".join(errors))
        (folder / "oshibki.txt").write_text("\n".join(errors), encoding="utf-8")
    (folder / "svodka.txt").write_text("\n".join(notes), encoding="utf-8")
    print("──── проба телегида MagentaTV ────")
    print("\n".join(notes)[:20000])
    print("──────────────────────────────────\n")

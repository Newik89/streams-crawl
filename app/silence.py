"""Сторож «канал замолчал» (книга 123, этап 1 плана «сайт не перестаёт
разбираться», слова владельца 14.11).

Случай: ipko.tv 13.11 сменил запись матчей на каналах SuperSport. Страницы
открывались, строки читались, а игр с этих каналов не стало — и никто об этом
не узнал, пока владелец сам не увидел на витрине. Сторож замечает это сам.

ЧТО СЧИТАЕМ. В каждом полном сборе — сколько игр дал каждый канал каждого
сайта (`channel_counts`). Счёт сохраняется в games.json (ключ `COUNTS_KEY`),
следующий сбор сравнивает себя с ним.

ПРАВИЛА (что случилось → что делаем):
  М1. Канал «замолчал»: в прошлом сборе он дал не меньше `SILENT_BASE` игр,
      а в этом — ни одной, хотя сайт прочитан (у сайта есть разобранные
      строки). Сайт не прочитан — это не тишина, а сбой сбора: им занята
      цепочка сбоев (`app/site_move.py`), сторож молчит.
  М2. Тишина считается сборами подряд (`подряд`): канал, замолчавший в
      прошлом сборе и молчащий в этом, — подряд + 1; «было» — число ДО
      тишины. Канал дал хоть одну игру — запись снимается.
  М3. Уведомление — ОДНО, когда `подряд` дошло до `SILENT_RUNS`: строка в
      «Прогоны» по сайту со списком каналов. Дальше молчим: повторять одно и
      то же каждый сбор незачем.
  М4. У сайта замолчали ВСЕ каналы, что давали игры, — в словах так и
      сказано: «игр с сайта нет совсем».
  М5. Сравниваются только полные сборы: дозабор и скан одной даты счёт не
      трогают (решает `parse_live`).

  М6. (книга 128) Тот же сторож сообщает и про «сайт просел на дату»
      (`app/etalon_guard.site_drops`, ключ games.json «просадки»: сайт дал
      на день вдвое меньше игр, чем в прошлом сборе). Раньше это только
      копилось. Строка — одна, когда просадка держится `DROP_RUNS` сбора
      подряд; по одному сбору не судим — сайты часто дозаполняют день позже.

Сторож ничего не чинит и ничего не снимает с витрины — только сообщает.
Пороги — в константах ниже; менять их — слово владельца.
"""
from __future__ import annotations

#: ключ games.json: {сайт: {канал: игр}} — счёт этого сбора
COUNTS_KEY = "каналы"
#: ключ games.json: записи о молчащих каналах (`check`)
SILENT_KEY = "молчат"
#: М1: канал считается «дававшим игры», если в прошлом сборе их было не меньше
SILENT_BASE = 3
#: М3: уведомление — на таком сборе тишины подряд (три сбора ≈ сутки)
SILENT_RUNS = 3
#: М6: ключ games.json с записями `etalon_guard.site_drops` и на каком сборе
#: просадки подряд сообщаем
DROPS_KEY = "просадки"
DROP_RUNS = 2


def bare(domain: str) -> str:
    """Сайт без `www.` — как в «разобрано» у `parse_live`."""
    domain = (domain or "").strip().lower()
    return domain[4:] if domain.startswith("www.") else domain


def channel_counts(games: list) -> dict[str, dict[str, int]]:
    """{сайт: {канал: сколько игр}} по играм сбора. Игра засчитывается каналу
    один раз, сколько бы его строк в ней ни было (эфир и студия)."""
    out: dict[str, dict[str, int]] = {}
    for game in games or []:
        seen = set()
        for entry in game.get("entries") or []:
            key = (bare(entry.get("source") or ""), (entry.get("channel") or "").strip())
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            site = out.setdefault(key[0], {})
            site[key[1]] = site.get(key[1], 0) + 1
    return out


def check(counts: dict, previous: dict | None, parsed: dict | None) -> list[dict]:
    """М1–М2: записи о молчащих каналах этого сбора.
    `counts` — `channel_counts` этого сбора; `previous` — прошлый games.json
    (его `COUNTS_KEY` и `SILENT_KEY`); `parsed` — «разобрано» этого сбора
    ({сайт: строк}). Запись: {сайт, канал, было, подряд}."""
    previous = previous or {}
    parsed = {bare(k): v for k, v in (parsed or {}).items()}
    before = previous.get(COUNTS_KEY) or {}
    silent_before = {(r.get("сайт"), r.get("канал")): r
                     for r in previous.get(SILENT_KEY) or [] if isinstance(r, dict)}
    out = []
    candidates = {(site, channel): n for site, chans in before.items()
                  if isinstance(chans, dict) for channel, n in chans.items()}
    for key in set(candidates) | set(silent_before):
        site, channel = key
        if (counts.get(site) or {}).get(channel):
            continue                                   # М2: канал дал игру
        if not parsed.get(site):
            # М1: сайт не прочитан — не тишина; прежнюю запись держим как есть
            if key in silent_before:
                out.append(dict(silent_before[key]))
            continue
        if key in silent_before:                       # М2: молчит дальше
            old = silent_before[key]
            out.append({"сайт": site, "канал": channel, "было": int(old.get("было") or 0),
                        "подряд": int(old.get("подряд") or 0) + 1})
        elif int(candidates.get(key) or 0) >= SILENT_BASE:   # М1: замолчал
            out.append({"сайт": site, "канал": channel, "было": int(candidates[key]),
                        "подряд": 1})
    out.sort(key=lambda r: (r["сайт"], r["канал"]))
    return out


def words(silent: list, counts: dict) -> list[str]:
    """М3–М4: строки уведомления — по одной на сайт, только для каналов, у
    которых `подряд` РОВНО `SILENT_RUNS` (уведомление одно на тишину)."""
    by_site: dict[str, list] = {}
    for r in silent or []:
        if isinstance(r, dict) and int(r.get("подряд") or 0) == SILENT_RUNS:
            by_site.setdefault(r["сайт"], []).append(r)
    out = []
    for site in sorted(by_site):
        rows = by_site[site]
        names = ", ".join(f"{r['канал']} (было игр: {r['было']})" for r in rows)
        alive = sum(1 for n in (counts.get(site) or {}).values() if n)
        if alive:
            tail = f"с остальных каналов сайта игры идут ({alive})"
        else:
            tail = "игр с сайта нет совсем"                       # М4
        out.append(f"{site}: каналы замолчали — {names}. Страницы открываются, а игр нет "
                   f"{SILENT_RUNS} сбора подряд; {tail}. Возможно, сайт сменил запись "
                   f"расписания — нужна проверка разборщика")
    return out


def drop_words(drops: list) -> list[str]:
    """М6: строки про «сайт просел на дату» — по одной на сайт, только для
    записей, у которых `подряд` РОВНО `DROP_RUNS`."""
    by_site: dict[str, list] = {}
    for r in drops or []:
        if isinstance(r, dict) and int(r.get("подряд") or 0) == DROP_RUNS and r.get("сайт"):
            by_site.setdefault(r["сайт"], []).append(r)
    out = []
    for site in sorted(by_site):
        days = "; ".join(f"на {r.get('дата')} было игр {r.get('было')}, стало {r.get('стало')}"
                         for r in sorted(by_site[site], key=lambda r: str(r.get("дата"))))
        out.append(f"{site}: сайт дал заметно меньше игр, чем раньше, — {days}; так уже "
                   f"{DROP_RUNS} сбора подряд. Возможно, сайт сменил запись расписания или "
                   f"убрал трансляции — стоит посмотреть")
    return out


#: настройка базы: метка сбора («собрано»), о котором уже сообщили, — чтобы
#: повторная заливка того же файла не писала вторую строку
NOTED_KEY = "silence_noted"
WHO = "сторож каналов"


def after_import(conn, data: dict) -> list[str]:
    """М3 на сервере (зовёт `games_import.py` после заливки полного сбора):
    строки `words` — в «Прогоны», по одной на сайт. Тот же файл второй раз
    (перезаливка) — молчим. Возвращает написанные строки."""
    from . import db, watch
    lines = words(data.get(SILENT_KEY) or [], data.get(COUNTS_KEY) or {})
    lines += drop_words(data.get(DROPS_KEY) or [])                     # М6
    stamp = str(data.get("собрано") or "")
    if not lines or not stamp or db.get_setting(conn, NOTED_KEY) == stamp:
        return []
    for line in lines:
        watch.note(conn, line, who=WHO)
    db.set_setting(conn, NOTED_KEY, stamp)
    return lines

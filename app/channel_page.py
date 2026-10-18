# -*- coding: utf-8 -*-
"""Кнопка ↗ «Открыть расписание канала» — куда она ведёт.

Требование владельца (08.10 и 13.10.2026): ↗ открывает на сайте страницу
КАНАЛА на ДЕНЬ ИГРЫ — то, что увидит человек. Не адрес, которым программа
читала расписание: у трети сайтов это машинная ручка (API, JSON, AJAX), и
человеку она показывает сырой текст или ошибку. 13.10 у Sport Klub 2
(#6018 Gea — Mensik) кнопка вела на `api-web.ug-be.cdn.united.cloud/…/epg?
cid=923…` и отвечала 401: старая проверка не узнала в нём машинный адрес.

Правила по порядку — первое сработавшее даёт ссылку (`link`):

1. У сайта есть шаблон в `data/channel_pages.json` → страница по шаблону:
   дата — день игры по часам САЙТА (у телегидов сутки с утра до утра —
   поле `night`), канал `{CH}` — из адреса отметки или имени канала (как
   сказано в шаблоне). Канал не узнан → запасной шаблон сайта без канала
   (`else`), а его нет — правило 2.
2. Адрес отметки — страница для человека (`is_machine` = нет) → он как есть:
   с него программа и прочла игру.
3. Адреса нет или он машинный → страница расписания сайта: закладка
   источника (`base_url`) без `?…` и `#…` (там бывают даты из прошлого года).
4. Нет и закладки (или она сама машинная) — пусто, кнопки нет.

Любая поломка внутри (битый файл шаблонов, кривой пояс сайта, кривой
адрес) витрину не роняет: ссылка тогда — правило 3.

Машинный адрес (`is_machine`) — хватает одного признака:
  а. в пути: `/api/`, `/tvapi`, `/epg/`, `/cache/`, `/wp-json/`,
     `/wp-content/`, `/wp-admin/`, `/data-feed/`, `/partial/`,
     `/integrationlayer/`, `/ical` (календарь), `/load/` (подгрузка
     телегида dir.bg — `/load/programs`, только POST, 18.10), часть пути
     `ajax`, файл-ручка со словом ajax (`admin-ajax.php`,
     `getAjaxData.aspx`), файл `.json`/`.xml`/`.ics`;
  б. в запросе: `ajax=`/`isajax=`, `accesskey=`, `format=json`;
  в. в имени хоста слово `api` (`api.…`, `api-web.…`, `mwapi-prod.…`,
     `…-epg-api.…`);
  г. хост чужого домена — не сайт источника (`tvarenaprogram.com` у
     `tvarenasport.ba`, `kolla.tv` у `dagenstv.com`).
Слово `ajax` — только целой частью пути, именем файла-ручки или параметром:
канал клуба Ajax (`/channels/ajax-tv/`) — страница для человека.
Ошибка внутри правил пишется в журнал (`logging`) один раз за запуск.

Шаблоны выясняются пробами с GitHub (`github_run.py dispatch --urls`), не с
компьютера владельца. Сторож — `scripts/test_channel_page.py`: каждый
машинный адрес последнего сбора должен давать человеческую ссылку.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from datetime import date as _date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from zoneinfo import ZoneInfo

from . import daytime, urls

PAGES_FILE = Path(__file__).resolve().parent.parent / "data" / "channel_pages.json"

#: признак а — путь адреса
_MACHINE_PATH = re.compile(
    r"/(api|tvapi|epg|cache|wp-json|wp-content|wp-admin|data-feed|partial|"
    r"integrationlayer|ajax|ical|load)(/|$)|/[\w-]*ajax[\w-]*\.(php|aspx?)$"
    r"|\.(json|xml|ics)$", re.I)
#: признак б — строка запроса
_MACHINE_QUERY = re.compile(r"(^|&)(is)?ajax=|accesskey=|format=json", re.I)
#: признак в — слово `api` частью имени хоста (`mwapi-prod` у cosmotetv.gr)
_MACHINE_HOST = re.compile(r"(^|[.-])(mw)?api\d*([.-]|$)", re.I)

#: вторые уровни, под которыми регистрируют сайты (`bbc.co.uk`,
#: `atv.com.tr`): их домен — три последних части имени, а не две
_SECOND_LEVEL = {"co", "com", "net", "org", "gov", "ac", "edu"}

_KYIV = ZoneInfo("Europe/Kyiv")

#: как часто проверять, не поменялся ли файл шаблонов (витрина зовёт
#: `pages()` на каждый канал — 2000 раз за страницу)
_RECHECK_SECONDS = 5


def _bare(host: str) -> str:
    host = (host or "").lower().strip().strip(".")
    return host[4:] if host.startswith("www.") else host


def site_of(host: str) -> str:
    """Домен сайта без поддоменов: `services.err.ee` → `err.ee`,
    `m.flashscore.com.tr` → `flashscore.com.tr`."""
    parts = _bare(host).split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_machine(url: str | None, domain: str = "") -> bool:
    """Адрес, которым расписание читала программа, а не человек."""
    if not url:
        return False
    p = urlsplit(url)
    if _MACHINE_PATH.search(p.path) or _MACHINE_QUERY.search(p.query):
        return True                                            # а, б
    if _MACHINE_HOST.search(p.hostname or ""):
        return True                                            # в
    if domain and p.hostname and site_of(p.hostname) != site_of(domain):
        return True                                            # г
    return False


def schedule_page(base_url: str | None, domain: str = "") -> str:
    """Страница расписания сайта — закладка без `?…` и `#…`; машинная
    закладка — не страница (правило 4)."""
    if not base_url:
        return ""
    p = urlsplit(base_url)
    page = f"{p.scheme}://{p.netloc}{p.path}" if p.scheme else base_url
    return "" if is_machine(page, domain) else page


def _norm(name: str) -> str:
    """Имя канала для сравнения: без регистра, ударений, пробелов, знаков
    и хвоста `HD` — «SVT 1» = «SVT1», «Spíler1 TV» = «Spiler1 TV»; плюс —
    словом: «TV3+» = «TV3 Plus», а «MTV Katsomo+» ≠ «MTV Katsomo»."""
    text = unicodedata.normalize("NFKD", (name or "").replace("+", " plus "))
    text = "".join(c for c in text.casefold() if c.isalnum())
    return text[:-2] if text.endswith("hd") and len(text) > 2 else text


def _prepare(rule: dict) -> dict:
    """Шаблон из файла + словарь с упрощёнными именами (`_names`), чтобы
    не пересобирать его на каждый канал витрины."""
    rule = dict(rule)
    table = rule.get("map")
    if isinstance(table, dict) and rule.get("ch") == "name":
        rule["_names"] = {_norm(k): v for k, v in table.items()}
    return rule


_cache: dict = {"mtime": None, "checked": 0.0, "pages": {}}
_log = logging.getLogger(__name__)
_logged: list = []          # ошибку правил пишем в журнал один раз за запуск
_lock = threading.Lock()


def pages() -> dict[str, dict]:
    """Шаблоны из `data/channel_pages.json` (перечитываются, если файл
    поменялся). Ключи с `_` — пояснения, не сайты. Файл битый — остаются
    прежние шаблоны (или никаких): витрина живёт без них по правилам 2–3,
    а файл перечитывается при следующей проверке — недописанный во время
    `git pull` подхватится, как только допишется."""
    if time.monotonic() - _cache["checked"] < _RECHECK_SECONDS:
        return _cache["pages"]
    with _lock:               # потоки витрины ждут первую загрузку, а не берут {}
        if time.monotonic() - _cache["checked"] < _RECHECK_SECONDS:
            return _cache["pages"]
        try:
            mtime = PAGES_FILE.stat().st_mtime
        except OSError:
            _cache.update(mtime=None, pages={}, checked=time.monotonic())
            return {}
        if _cache["mtime"] != mtime:
            try:
                raw = json.loads(PAGES_FILE.read_text(encoding="utf-8-sig"))
                if not isinstance(raw, dict):
                    raise ValueError("не словарь")
                _cache["pages"] = {_bare(k): _prepare(v) for k, v in raw.items()
                                   if not k.startswith("_") and isinstance(v, dict)}
                _cache["mtime"] = mtime           # только после удачного разбора
            except (OSError, ValueError, AttributeError):
                pass                              # прежние шаблоны остаются
        _cache["checked"] = time.monotonic()
    return _cache["pages"]


@lru_cache(maxsize=64)
def _zone(tz: str | None) -> ZoneInfo | None:
    """Пояс сайта; кривой (`UTC+3`, опечатка в админке) — как нет пояса."""
    if not tz:
        return None
    try:
        return ZoneInfo(tz)
    except (KeyError, ValueError):
        return None


@lru_cache(maxsize=4096)
def site_day(start_kyiv: str | None, tz: str | None, night: int = 0) -> _date | None:
    """День игры по часам сайта: 00:30 по Киеву — у хорватского сайта ещё
    23:30 накануне. `night` — час, с которого у сайта начинаются сутки
    (телегиды идут `6:00 → … → 0:00 → 5:15`): игра в 02:00 стоит на
    странице прошлого дня."""
    text = (start_kyiv or "").replace("T", " ").strip()[:16]
    try:
        moment = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=_KYIV)
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    zone = _zone(tz)
    local = moment.astimezone(zone) if zone else moment
    if night and local.hour < night:
        local -= timedelta(days=1)
    return local.date()


def _name_variants(name: str) -> list[str]:
    """Имя как есть и без приставки страны, которую владелец ставит перед
    каналом («BA| Arena Sport 1», «D TV 2 Sport X», правила 09–10.09)."""
    out = [_norm(name)]
    bare = re.sub(r"^\s*([A-Z]{1,3}\s*\|\s*|[A-Z]{1,2}\s+)", "", name or "")
    if bare != (name or ""):
        out.append(_norm(bare))
    return out


def _channel_key(how: str, source_url: str, channel: str) -> str:
    """`{CH}` по правилу шаблона: `q:cid` — параметр адреса отметки,
    `path:-2` — часть пути (без `.json`), `name` — имя канала."""
    how = how or ""
    if how == "name":
        return channel or ""
    p = urlsplit(source_url or "")
    if how.startswith("q:"):
        return (parse_qs(p.query).get(how[2:]) or [""])[0]
    if how.startswith("path:"):
        parts = [s for s in p.path.split("/") if s]
        try:
            part = parts[int(how[5:])]
        except (ValueError, IndexError):
            return ""
        return re.sub(r"\.(json|xml|html?)$", "", part, flags=re.I)
    return ""


def _lookup(rule: dict, key: str, by_name: bool) -> str:
    """Значение словаря шаблона: сперва точное совпадение, по имени канала
    — затем без учёта написания."""
    table = rule.get("map") or {}
    if key in table:
        return str(table[key])
    if not by_name:
        return ""
    names = rule.get("_names")
    if names is None:
        names = {_norm(k): v for k, v in table.items()}
    for variant in _name_variants(key):
        if variant in names:
            return str(names[variant])
    return ""


def from_template(rule: dict, source_url: str, channel: str | tuple,
                  day: _date | None, tz: str | None) -> str:
    """Правило 1: страница по шаблону сайта. Пусто — шаблон не подошёл.

    Поля шаблона: `page` — адрес с метками даты и `{CH}`; `ch` — откуда
    канал; `map` — словарь «канал → {CH}» (значение с `://` — это готовая
    страница канала, тоже с метками даты); `else` — страница, когда канал не
    узнан или день вне `days` (`[0, 6]`: сайт `rtcg.me` знает только номер
    дня от сегодня и дальше недели не показывает); `night` — час начала
    суток сайта (его учитывает `site_day`). `channel` — имя канала или
    несколько имён (как на сайте, как на витрине) — берётся первое узнанное."""
    page = rule.get("page") or ""
    marks: dict[str, str] = {}
    if "{CH}" in page:
        how = rule.get("ch", "")
        table = rule.get("map")
        key = ""
        for name in ((channel,) if isinstance(channel, str) else channel):
            key = _channel_key(how, source_url, name or "")
            if table is not None and key:
                key = _lookup(rule, key, how == "name")
            if key:
                break
        if "://" in key:
            page = key                       # словарь дал страницу целиком
        elif key:
            # `%` — значения словаря бывают уже закодированы (`caf%C3%A9`)
            marks["CH"] = quote(key, safe="-_.~/:%")
        else:
            page = rule.get("else") or ""
    # «сегодня» сайта — с тем же началом суток `night`, что и день игры:
    # иначе в 02:00 у телегида номер дня {DAYNUM} вышел бы -1
    night = int(rule.get("night") or 0)
    сегодня = daytime.today(tz)
    if night and datetime.now(_zone(tz) or _KYIV).hour < night:
        сегодня -= timedelta(days=1)
    d = day or сегодня
    marks["DAYNUM"] = str((d - сегодня).days)
    days = rule.get("days")
    if days and "{DAYNUM}" in page and not days[0] <= (d - сегодня).days <= days[1]:
        page = rule.get("else") or ""
    if not page:
        return ""
    url = urls.resolve(page, day=d, tz=tz, **marks)
    return "" if "{CH}" in url else url


def link(source_url: str | None, *, domain: str = "", base_url: str = "",
         start_kyiv: str | None = None, tz: str | None = None,
         channel: str | tuple = "", rules: dict | None = None) -> str:
    """Ссылка кнопки ↗ — правила 1–4 из шапки модуля. `rules` — шаблоны
    вместо файла (для тестов)."""
    try:
        tz = tz if _zone(tz) else None
        rule = (pages() if rules is None else rules).get(_bare(domain)) if domain else None
        if rule:
            url = from_template(rule, source_url or "", channel,
                                site_day(start_kyiv, tz, int(rule.get("night") or 0)), tz)
            if url:
                return url                                      # 1
        if source_url and not is_machine(source_url, domain):
            return source_url                                   # 2
        return schedule_page(base_url, domain)                  # 3, 4
    except Exception:  # noqa: BLE001 — ссылка не стоит упавшей витрины
        if not _logged:
            _logged.append(True)
            _log.exception("ссылка ↗: ошибка правил (%s, %s) — даю страницу сайта",
                           domain, source_url)
        try:
            return schedule_page(base_url, domain)
        except Exception:  # noqa: BLE001
            return ""

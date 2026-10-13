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
   дата — день игры по часам САЙТА, канал `{CH}` — из адреса отметки или
   имени канала (как сказано в шаблоне). Канал не узнан → запасной шаблон
   сайта без канала (`else`), а его нет — правило 3.
2. Адрес отметки — страница для человека (`is_machine` = нет) → он как есть:
   с него программа и прочла игру.
3. Иначе — страница расписания сайта: закладка источника (`base_url`) без
   `?…` и `#…` (там бывают даты из прошлого года).
4. Нет ничего — пусто, кнопки нет.

Машинный адрес (`is_machine`) — хватает одного признака:
  а. в пути: `/api/`, `/tvapi`, `/epg/`, `/cache/`, `/wp-json/`,
     `/wp-content/`, `/wp-admin/`, `/data-feed/`, `/partial/`,
     `/integrationlayer/`, слово `ajax` или файл `.json`/`.xml`;
  б. в запросе: `ajax`, `accesskey=`, `format=json`;
  в. в имени хоста слово `api` (`api.…`, `api-web.…`, `mwapi-prod.…`,
     `…-epg-api.…`);
  г. хост чужого домена — не сайт источника (`tvarenaprogram.com` у
     `tvarenasport.ba`, `kolla.tv` у `dagenstv.com`).

Шаблоны выясняются пробами с GitHub (`github_run.py dispatch --urls`), не с
компьютера владельца. Сторож — `scripts/test_channel_page.py`: каждый
машинный адрес последнего сбора должен давать человеческую ссылку.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date as _date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from . import daytime, urls

PAGES_FILE = Path(__file__).resolve().parent.parent / "data" / "channel_pages.json"

#: признак а — путь адреса
_MACHINE_PATH = re.compile(
    r"/(api|tvapi|epg|cache|wp-json|wp-content|wp-admin|data-feed|partial|"
    r"integrationlayer)(/|$)|ajax|\.(json|xml)$", re.I)
#: признак б — строка запроса
_MACHINE_QUERY = re.compile(r"ajax|accesskey=|format=json", re.I)
#: признак в — слово `api` в имени хоста (до двух букв впереди: `mwapi`)
_MACHINE_HOST = re.compile(r"(^|[.-])[a-z]{0,2}api\d*([.-]|$)", re.I)

#: вторые уровни, под которыми регистрируют сайты (`bbc.co.uk`,
#: `atv.com.tr`): их домен — три последних части имени, а не две
_SECOND_LEVEL = {"co", "com", "net", "org", "gov", "ac", "edu"}

_KYIV = ZoneInfo("Europe/Kyiv")


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


def schedule_page(base_url: str | None) -> str:
    """Страница расписания сайта — закладка без `?…` и `#…`."""
    if not base_url:
        return ""
    p = urlsplit(base_url)
    return f"{p.scheme}://{p.netloc}{p.path}" if p.scheme else base_url


_cache: dict = {"mtime": None, "pages": {}}


def pages() -> dict[str, dict]:
    """Шаблоны из `data/channel_pages.json` (перечитываются, если файл
    поменялся). Ключи с `_` — пояснения, не сайты."""
    try:
        mtime = PAGES_FILE.stat().st_mtime
    except OSError:
        return {}
    if _cache["mtime"] != mtime:
        raw = json.loads(PAGES_FILE.read_text(encoding="utf-8"))
        _cache["pages"] = {_bare(k): v for k, v in raw.items()
                           if not k.startswith("_") and isinstance(v, dict)}
        _cache["mtime"] = mtime
    return _cache["pages"]


def site_day(start_kyiv: str | None, tz: str | None) -> _date | None:
    """День игры по часам сайта: 00:30 по Киеву — у хорватского сайта ещё
    23:30 накануне, и в его расписании игра стоит под вчерашней датой."""
    text = (start_kyiv or "").replace("T", " ").strip()[:16]
    try:
        moment = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=_KYIV)
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    try:
        return moment.astimezone(ZoneInfo(tz)).date() if tz else moment.date()
    except (KeyError, ValueError):
        return moment.date()


def _norm(name: str) -> str:
    """Имя канала для сравнения: без регистра, ударений, пробелов, знаков
    и хвоста `HD` — «SVT 1» = «SVT1», «Spíler1 TV» = «Spiler1 TV»."""
    text = unicodedata.normalize("NFKD", name or "").casefold()
    text = "".join(c for c in text if c.isalnum())
    return text[:-2] if text.endswith("hd") and len(text) > 2 else text


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


def _lookup(table: dict, key: str, by_name: bool) -> str:
    """Значение словаря шаблона: по имени канала — без учёта написания."""
    if not by_name:
        return str(table.get(key, ""))
    names = {_norm(k): v for k, v in table.items()}
    for variant in _name_variants(key):
        if variant in names:
            return str(names[variant])
    return ""


def from_template(rule: dict, source_url: str, channel: str,
                  day: _date | None, tz: str | None) -> str:
    """Правило 1: страница по шаблону сайта. Пусто — шаблон не подошёл.

    Поля шаблона: `page` — адрес с метками даты и `{CH}`; `ch` — откуда
    канал; `map` — словарь «канал → {CH}» (значение с `://` — это готовая
    страница канала, тоже с метками даты); `else` — страница, когда канал не
    узнан или день вне `days` (`[0, 6]`: сайт `rtcg.me` знает только номер
    дня от сегодня и дальше недели не показывает)."""
    page = rule.get("page") or ""
    marks: dict[str, str] = {}
    if "{CH}" in page:
        how = rule.get("ch", "")
        key = _channel_key(how, source_url, channel)
        table = rule.get("map")
        if table is not None and key:
            key = _lookup(table, key, how == "name")
        if "://" in key:
            page = key                       # словарь дал страницу целиком
        elif key:
            marks["CH"] = key
        else:
            page = rule.get("else") or ""
    сегодня = daytime.today(tz)
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
         channel: str = "", rules: dict | None = None) -> str:
    """Ссылка кнопки ↗ — правила 1–4 из шапки модуля. `rules` — шаблоны
    вместо файла (для тестов)."""
    rule = (pages() if rules is None else rules).get(_bare(domain)) if domain else None
    if rule:
        url = from_template(rule, source_url or "", channel,
                            site_day(start_kyiv, tz), tz)
        if url:
            return url                                          # 1
    if source_url and not is_machine(source_url, domain):
        return source_url                                       # 2
    return schedule_page(base_url)                              # 3, 4

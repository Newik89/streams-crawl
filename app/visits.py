# -*- coding: utf-8 -*-
"""Журнал посещений сайта (владелец 03.10.2026: «видеть IP, кто и когда
заходит» — гость нажал «Collect 2 days», а узнать, кто это был, было нечем).

Пишем в ФАЙЛ, а не в базу: запись в SQLite на каждый заход цеплялась бы за
замок базы во время заливки обхода, и страницы висели бы (грабли 25.09).
Файл на месяц — `data/visits-ГГГГ-ММ.log`, строка на запрос, поля через
табуляцию; `data/` в git не едет. Файлы старше двух месяцев убираются при
открытии страницы «Посещения». Строку запроса (`?…`) не пишем — только путь.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import db

KYIV = ZoneInfo("Europe/Kyiv")
KEEP_MONTHS = 2                 # текущий месяц и прошлый
TAIL_BYTES = 4_000_000          # сколько конца файла читает страница
FIELDS = ("when", "ip", "method", "path", "status", "who", "endpoint", "agent")

#: что человек сделал — по маршруту сайта; чего тут нет, показываем путём
ACTIONS = {
    ("GET", "schedule"): "открыл витрину",
    ("GET", "schedule_other"): "открыл Other Sport",
    ("POST", "schedule_run"): "нажал кнопку сбора (Collect)",
    ("GET", "login"): "открыл страницу входа",
    ("POST", "crawl_run"): "нажал «Обход» в админке",
    ("POST", "crawl_day"): "нажал «Скан даты»",
    ("POST", "crawl_site"): "нажал «Обойти сайт»",
    ("POST", "crawl_hook_in"): "стук GitHub: обход начался или закончился",
    ("GET", "dashboard"): "открыл админку",
    ("GET", "visits_list"): "смотрел посещения",
    ("GET", "logout"): "вышел из админки",
}
BUTTONS = {"schedule_run", "crawl_run", "crawl_day", "crawl_site"}
#: страницы, открытые гостю: переадресация с них — не «стучался в админку»
OPEN_TO_ALL = {"schedule", "schedule_other", "schedule_run", "login", "logout"}

_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|curl|wget|python|go-http|scan|zgrab|masscan|"
    r"httpx|java/|okhttp|headless|libwww|axios|node-fetch|facebookexternalhit",
    re.I)
_BOT_NAME_RE = re.compile(r"([A-Za-z][\w.-]*(?:bot|spider|crawler)[\w.-]*)", re.I)
_BREAKS_RE = re.compile(r"[\t\r\n]+")


def folder() -> Path:
    return Path(os.environ.get("STREAMS_VISITS_DIR") or (db.ROOT / "data"))


def _clean(text: str | None, limit: int) -> str:
    return _BREAKS_RE.sub(" ", text or "")[:limit]


def write(ip: str, method: str, path: str, status: int, admin: bool,
          endpoint: str | None, agent: str) -> None:
    """Одна строка о запросе. Журнал не должен ронять сайт: диск полон или
    папки нет — молча пропускаем."""
    now = datetime.now(KYIV)
    line = "\t".join((
        f"{now:%Y-%m-%d %H:%M:%S}", _clean(ip, 45), _clean(method, 8),
        _clean(path, 200), str(status), "admin" if admin else "guest",
        _clean(endpoint, 40), _clean(agent, 300))) + "\n"
    try:
        with open(folder() / f"visits-{now:%Y-%m}.log", "a",
                  encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _tail(path: Path) -> str:
    """Конец файла (до TAIL_BYTES): месяц сканеров весит десятки мегабайт,
    а странице нужны последние дни."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            data = f.read()
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    if size > TAIL_BYTES:               # первая строка обрезана — выбрасываем
        text = text.split("\n", 1)[-1]
    return text


def read(days: int = 7) -> list[dict]:
    """Записи за последние `days` суток, свежие сверху."""
    edge = f"{datetime.now(KYIV) - timedelta(days=days):%Y-%m-%d %H:%M:%S}"
    rows: list[dict] = []
    for path in sorted(folder().glob("visits-*.log"))[-KEEP_MONTHS:]:
        for line in _tail(path).splitlines():
            parts = line.split("\t")
            if len(parts) == len(FIELDS) and parts[0] >= edge:
                rows.append(dict(zip(FIELDS, parts)))
    # файлы идут по месяцам, строки в файле — по времени: порядок записи и
    # есть порядок событий, разворачиваем целиком (секунда у строк общая)
    rows.reverse()
    return rows


def show_time(when: str, seconds: bool = False) -> str:
    """«2026-10-03 20:02:13» → «03.10 20:02» (с секундами — для ленты)."""
    return f"{when[8:10]}.{when[5:7]} {when[11:19 if seconds else 16]}"


def purge() -> int:
    """Убрать файлы старше KEEP_MONTHS. Возвращает, сколько убрано."""
    gone = 0
    for old in sorted(folder().glob("visits-*.log"))[:-KEEP_MONTHS]:
        try:
            old.unlink()
            gone += 1
        except OSError:
            pass
    return gone


def kind(row: dict) -> str:
    """Вид записи для фильтров страницы: button — нажатие кнопки сбора,
    login — попытка входа, hook — стук GitHub, junk — запрос несуществующей
    страницы (сканеры), page — обычный заход."""
    endpoint = row["endpoint"]
    if not endpoint:
        return "junk"
    if endpoint == "crawl_hook_in":
        return "hook"
    if row["method"] == "POST" and endpoint in BUTTONS:
        return "button"
    if row["method"] == "POST" and endpoint == "login":
        return "login"
    return "page"


def what(row: dict) -> str:
    """Что сделал посетитель — словами."""
    if row["method"] == "POST" and row["endpoint"] == "login":
        # удачный вход отвечает переадресацией, неудачный — той же страницей
        return ("вошёл в админку" if row["status"].startswith("3")
                else "неудачная попытка входа")
    if not row["endpoint"]:
        return f"искал несуществующее: {row['path']}"
    if (row["who"] == "guest" and row["status"].startswith("3")
            and row["endpoint"] not in OPEN_TO_ALL):
        # гостя с закрытой страницы сайт отправляет на вход
        return f"хотел открыть закрытую страницу {row['path']} — отправлен на вход"
    known = ACTIONS.get((row["method"], row["endpoint"]))
    if known:
        return known
    return f"{'открыл' if row['method'] == 'GET' else 'отправил'} {row['path']}"


def device(agent: str) -> str:
    """Коротко, с чего зашли: «Chrome, Windows», «Safari, iPhone», «бот: …»."""
    agent = agent or ""
    if not agent:
        return "без подписи (скорее всего программа)"
    found = _BOT_RE.search(agent)
    if found:
        name = _BOT_NAME_RE.search(agent)
        return "бот: " + (name.group(1) if name else found.group(0))
    system = next((label for mark, label in (
        ("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
        ("Windows", "Windows"), ("Macintosh", "Mac"), ("Mac OS", "Mac"),
        ("Linux", "Linux")) if mark in agent), "")
    browser = next((label for mark, label in (
        ("Edg/", "Edge"), ("OPR/", "Opera"), ("YaBrowser", "Яндекс"),
        ("Chrome/", "Chrome"), ("Firefox/", "Firefox"),
        ("Safari/", "Safari")) if mark in agent), "")
    return ", ".join(x for x in (browser, system) if x) or agent[:40]

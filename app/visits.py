# -*- coding: utf-8 -*-
"""Журнал посещений сайта (владелец 03.10.2026: «видеть IP, кто и когда
заходит» — гость нажал «Collect 2 days», а узнать, кто это был, было нечем).

Пишем в ФАЙЛ, а не в базу: запись в SQLite на каждый заход цеплялась бы за
замок базы во время заливки обхода, и страницы висели бы (грабли 25.09).
Файл на месяц — `data/visits-ГГГГ-ММ.log`, строка на запрос, поля через
табуляцию; `data/` в git не едет. Строку запроса (`?…`) не пишем — только путь.

05.10 (владелец: «понимать, кто заходит, сколько был, и чтобы журнал не рос
без потолка») — к восьми прежним полям добавлены четыре: метка посетителя
(кука `vid`), откуда пришёл (Referer: хост и путь), метка `from`/`utm_source`
из адреса и язык браузера. Старые строки из 8 полей читаются как прежде.
Рядом — файл маячков `beacons-ГГГГ-ММ.log`: витрина раз в 15 секунд, пока
вкладка на виду, сообщает, сколько секунд её смотрели и сколько было действий.
Подробные строки живут 10 дней; дольше — только суточные суммы в базе
(`app/visit_stats.py`), строки старше убираются, лишь когда их день посчитан.
"""

from __future__ import annotations

import atexit
import os
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from . import db

KYIV = ZoneInfo("Europe/Kyiv")
TAIL_BYTES = 48_000_000         # предохранитель чтения: больше с файла не берём
KEEP_DAYS = 10                  # подробные строки — 10 дней (владелец 05.10)
OLD_FIELDS = ("when", "ip", "method", "path", "status", "who", "endpoint",
              "agent")
FIELDS = OLD_FIELDS + ("vid", "ref", "src", "lang")
BEACON_FIELDS = ("when", "vid", "page", "secs", "acts")

#: две публичные страницы витрины: на них ставится метка и работает маячок
PUBLIC_PAGES = {"schedule", "schedule_other"}

# ── метка посетителя ─────────────────────────────────────────────────────────
VID_COOKIE = "vid"
VID_MAX_AGE = 400 * 24 * 3600   # 400 суток — дольше браузеры куку не держат
_VID_RE = re.compile(r"^[A-Za-z0-9_-]{16}$")

# ── потолок журнала (аудит 05.10: потоком запросов можно забить диск) ────────
#: «шумных» строк в час с одного адреса — гость, который не смотрит витрину
#: (переадресация на вход, несуществующие адреса, форма входа). Сканер
#: 34.40.89.x за 6 секунд дал 643 строки; человеку столько не нужно никогда.
#: Лишнее не пишется, а считается и потом ложится одной сводной строкой SKIP
NOISE_PER_HOUR = 120
#: за сутки (на один процесс): после мягкого предела пишем только витрину,
#: вход админа и друзей; после жёсткого — только админа. Обычные сутки — около
#: 0,6 МБ, так что 10 МБ — запас в 15 раз
DAY_SOFT_BYTES = 10_000_000
DAY_HARD_BYTES = 30_000_000

# ── маячок ───────────────────────────────────────────────────────────────────
BEACON_MAX_BODY = 200           # байт: «p=s&s=15&a=3» — с огромным запасом
BEACON_MAX_SECS = 60            # маячок раз в 15 с; больше минуты — враньё
BEACON_MAX_ACTS = 100
BEACON_PER_VID_MIN = 12         # в минуту с одной метки (две вкладки + уход)
BEACON_PER_IP_MIN = 60          # в минуту с одного адреса
BEACON_DAY_BYTES = 5_000_000    # ≈ 70 тыс. маячков в сутки — 290 часов чтения

_BREAKS_RE = re.compile(r"[\t\r\n]+")
_LANG_RE = re.compile(r"^[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})?$")
_SRC_RE = re.compile(r"[^\w.\-]+")
_SKIP_N_RE = re.compile(r"^\d+$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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


def folder() -> Path:
    return Path(os.environ.get("STREAMS_VISITS_DIR") or (db.ROOT / "data"))


def _clean(text: str | None, limit: int) -> str:
    return _BREAKS_RE.sub(" ", text or "")[:limit]


def _now() -> datetime:
    return datetime.now(KYIV)


# ── запись ───────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_noise: dict[str, list] = {}    # ip → [записано, пропущено, когда, подпись, кто]
_noise_hour = ""
_day = ""
_day_bytes = 0
_day_dropped = 0                # не записано из-за суточного предела


def _skip_line(when: str, ip: str, n: int, agent: str, who: str,
               what: str) -> str:
    """Сводная строка вместо пропущенных: метод SKIP, в поле статуса — сколько
    строк не записано. Классификация считает её за n запросов."""
    return "\t".join((when, _clean(ip, 45), "SKIP", what, str(n), who, "",
                      _clean(agent, 300), "", "", "", "")) + "\n"


def _flush_noise_locked() -> list[str]:
    """Сводные строки за прошедший час — и сброс счётчиков."""
    out = [_skip_line(e[2], ip, e[1], e[3], e[4],
                      "(не записано похожих запросов — предел в час)")
           for ip, e in _noise.items() if e[1]]
    _noise.clear()
    return out


def write(ip: str, method: str, path: str, status: int, admin: bool,
          endpoint: str | None, agent: str, *, who: str | None = None,
          vid: str = "", ref: str = "", src: str = "", lang: str = "") -> None:
    """Одна строка о запросе. Журнал не должен ронять сайт: диск полон или
    папки нет — молча пропускаем."""
    global _noise_hour, _day, _day_bytes, _day_dropped
    now = _now()
    when = f"{now:%Y-%m-%d %H:%M:%S}"
    who = who or ("admin" if admin else "guest")
    public_view = endpoint in PUBLIC_PAGES and status == 200
    line = "\t".join((
        when, _clean(ip, 45), _clean(method, 8), _clean(path, 200),
        str(status), who, _clean(endpoint, 40), _clean(agent, 300),
        _clean(vid, 20), _clean(ref, 120), _clean(src, 40),
        _clean(lang, 16))) + "\n"
    out: list[str] = []
    with _lock:
        hour, day = when[:13], when[:10]
        if hour != _noise_hour:
            out += _flush_noise_locked()
            _noise_hour = hour
        if day != _day:
            if _day_dropped:
                out.append(_skip_line(when, "-", _day_dropped, "", "guest",
                                      "(суточный предел журнала: не записано)"))
            _day, _day_bytes, _day_dropped = day, 0, 0
        keep = True
        if who == "guest" and not public_view:
            e = _noise.setdefault(ip, [0, 0, when, agent, who])
            if e[0] >= NOISE_PER_HOUR:
                e[1] += 1
                e[2], e[3] = when, agent
                keep = False
            else:
                e[0] += 1
            if len(_noise) > 50_000:            # память: не копим без края
                out += _flush_noise_locked()
        if keep and who != "admin":
            if _day_bytes >= DAY_HARD_BYTES or (
                    _day_bytes >= DAY_SOFT_BYTES and who == "guest"
                    and not public_view):
                _day_dropped += 1
                keep = False
        if keep:
            out.append(line)
        if not out:
            return
        data = "".join(out)
        _day_bytes += len(data.encode("utf-8"))
        try:
            with open(folder() / f"visits-{now:%Y-%m}.log", "a",
                      encoding="utf-8") as f:
                f.write(data)
        except OSError:
            pass


@atexit.register
def _flush_at_exit() -> None:
    """Остановка процесса: несведённые счётчики пропусков — в файл."""
    try:
        with _lock:
            out = _flush_noise_locked()
        if out:
            with open(folder() / f"visits-{_now():%Y-%m}.log", "a",
                      encoding="utf-8") as f:
                f.write("".join(out))
    except Exception:                                        # noqa: BLE001
        pass


def _ref(req) -> str:
    """Откуда пришёл: хост и путь Referer, без строки запроса. Переходы внутри
    своего сайта не пишем — это не источник."""
    raw = req.headers.get("Referer") or ""
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    if not host or host == (req.host or "").split(":")[0].lower():
        return ""
    return (host + (parts.path if parts.path not in ("", "/") else ""))[:120]


def _src(req) -> str:
    """Метка в адресе (`?from=…` или `?utm_source=…`) — ссылка в соцсети."""
    raw = req.args.get("from") or req.args.get("utm_source") or ""
    return _SRC_RE.sub("", raw)[:40]


def _lang(req) -> str:
    """Первый язык браузера из Accept-Language: «ru-RU,ru;q=0.9» → «ru-RU»."""
    first = (req.headers.get("Accept-Language") or "").split(",")[0]
    first = first.split(";")[0].strip()
    return first[:16] if _LANG_RE.match(first) else ""


def visitor_id(req) -> str:
    """Метка из куки, если она нашего вида; иначе пусто."""
    raw = req.cookies.get(VID_COOKIE, "")
    return raw if _VID_RE.match(raw) else ""


def log_request(req, resp, sess) -> None:
    """Строка журнала о запросе + метка посетителя при первом открытии
    витрины. Вызывается из `after_request`; базы не трогает."""
    who = ("admin" if sess.get("admin")
           else "friend" if sess.get("friend") else "guest")
    vid = visitor_id(req)
    mark = vid
    if not vid and req.endpoint in PUBLIC_PAGES and resp.status_code == 200:
        # первая витрина: долгоживущая случайная метка. Secure не ставим —
        # HTTPS пока нет (поставить вместе с переездом на домен)
        vid = secrets.token_urlsafe(12)
        resp.set_cookie(VID_COOKIE, vid, max_age=VID_MAX_AGE, httponly=True,
                        samesite="Lax", path="/")
        mark = "+" + vid                # «+» — метка выдана этим запросом
    write(req.remote_addr or "", req.method, req.path, resp.status_code,
          who == "admin", req.endpoint, req.headers.get("User-Agent", ""),
          who=who, vid=mark, ref=_ref(req), src=_src(req), lang=_lang(req))
    kick()


# ── маячок ───────────────────────────────────────────────────────────────────

_beacon_lock = threading.Lock()
_beacon_hits: dict[str, deque] = {}
_beacon_day = ""
_beacon_bytes = 0


def _too_often(key: str, limit: int, now: float) -> bool:
    q = _beacon_hits.get(key)
    if q is None:
        if len(_beacon_hits) > 20_000:          # память: выкидываем остывших
            for k in [k for k, v in _beacon_hits.items()
                      if not v or now - v[-1] > 60]:
                del _beacon_hits[k]
        q = _beacon_hits[key] = deque()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def _number(raw: str | None, top: int) -> int:
    """Число из маячка: мусор — ноль, отрицательное — ноль, лишнее — потолок."""
    try:
        n = int(float(raw or "0"))
    except (ValueError, OverflowError):
        return 0
    return max(0, min(n, top))


def take_beacon(req) -> int:
    """Принять маячок витрины. Возвращает код ответа: 204 — принят,
    403 — нет метки, 413 — тело больше предела, 429 — слишком часто.
    Ничего не меняет, кроме дозаписи строки в файл маячков; CSRF не нужен —
    данные безвредны (подделать можно лишь собственное время на сайте)."""
    global _beacon_day, _beacon_bytes
    vid = visitor_id(req)
    if not vid:
        return 403
    if (req.content_length or 0) > BEACON_MAX_BODY:
        return 413
    raw = req.stream.read(BEACON_MAX_BODY + 1)
    if len(raw) > BEACON_MAX_BODY:
        return 413
    fields: dict[str, str] = {}
    for part in raw.decode("ascii", errors="replace").split("&")[:8]:
        k, _, v = part.partition("=")
        fields.setdefault(k.strip(), v.strip())
    secs = _number(fields.get("s"), BEACON_MAX_SECS)
    acts = _number(fields.get("a"), BEACON_MAX_ACTS)
    page = {"s": "schedule", "o": "other"}.get(fields.get("p", ""), "?")
    now = time.time()
    when = f"{_now():%Y-%m-%d %H:%M:%S}"
    with _beacon_lock:
        if (_too_often("v:" + vid, BEACON_PER_VID_MIN, now)
                or _too_often("i:" + (req.remote_addr or ""),
                              BEACON_PER_IP_MIN, now)):
            return 429
        if not secs and not acts:
            return 204
        line = "\t".join((when, vid, page, str(secs), str(acts))) + "\n"
        if when[:10] != _beacon_day:
            _beacon_day, _beacon_bytes = when[:10], 0
        if _beacon_bytes >= BEACON_DAY_BYTES:
            return 204                          # предел суток: молча не пишем
        _beacon_bytes += len(line)
        try:
            with open(folder() / f"beacons-{when[:7]}.log", "a",
                      encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass
    return 204


# ── чтение ───────────────────────────────────────────────────────────────────

def _tail(path: Path) -> str:
    """Файл целиком, но не больше TAIL_BYTES с конца: уборка держит в файле
    дней 10–11, это обычно пара мегабайт; предохранитель — на случай аварии."""
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


def parse_line(line: str) -> dict | None:
    """Строка журнала → словарь. Понимает старые строки из 8 полей (до 05.10)
    и новые из 12; прочее — мусор."""
    parts = line.rstrip("\r\n").split("\t")
    n = len(parts)
    if n == len(FIELDS):
        return dict(zip(FIELDS, parts))
    if n == len(OLD_FIELDS):
        row = dict(zip(OLD_FIELDS, parts))
        row.update(vid="", ref="", src="", lang="")
        return row
    return None


def read(days: int | None = 7, newest_first: bool = True) -> list[dict]:
    """Записи за последние `days` суток (None — всё, что лежит в файлах),
    свежие сверху."""
    edge = (f"{_now() - timedelta(days=days):%Y-%m-%d %H:%M:%S}"
            if days is not None else "")
    rows: list[dict] = []
    for path in sorted(folder().glob("visits-*.log")):
        for line in _tail(path).splitlines():
            row = parse_line(line)
            if row and row["when"] >= edge and len(row["when"]) == 19:
                rows.append(row)
    # файлы идут по месяцам, строки в файле — по времени: порядок записи и
    # есть порядок событий, разворачиваем целиком (секунда у строк общая)
    if newest_first:
        rows.reverse()
    return rows


def read_beacons(days: int | None = None) -> list[dict]:
    """Маячки витрины, по времени."""
    edge = (f"{_now() - timedelta(days=days):%Y-%m-%d %H:%M:%S}"
            if days is not None else "")
    out: list[dict] = []
    for path in sorted(folder().glob("beacons-*.log")):
        for line in _tail(path).splitlines():
            parts = line.split("\t")
            if len(parts) != len(BEACON_FIELDS) or parts[0] < edge:
                continue
            b = dict(zip(BEACON_FIELDS, parts))
            b["secs"] = _number(b["secs"], BEACON_MAX_SECS)
            b["acts"] = _number(b["acts"], BEACON_MAX_ACTS)
            out.append(b)
    return out


def skipped(row: dict) -> int:
    """Сколько запросов стоит за строкой: сводная SKIP — n, обычная — 1."""
    if row["method"] == "SKIP" and _SKIP_N_RE.match(row["status"]):
        return int(row["status"])
    return 1


def show_time(when: str, seconds: bool = False) -> str:
    """«2026-10-03 20:02:13» → «03.10 20:02» (с секундами — для ленты)."""
    return f"{when[8:10]}.{when[5:7]} {when[11:19 if seconds else 16]}"


# ── уборка ───────────────────────────────────────────────────────────────────

def keep_from(today: str | None = None) -> str:
    """Первый день, строки которого храним: сегодня и 10 предыдущих."""
    base = (datetime.strptime(today, "%Y-%m-%d") if today
            else _now().replace(tzinfo=None))
    return f"{base - timedelta(days=KEEP_DAYS):%Y-%m-%d}"


def _rewrite(path: Path, done_days: set[str], edge: str) -> int:
    """Убрать из файла строки дней старше `edge`, уже записанных в суммы.
    Перезапись через временный файл и атомарную замену; что дописали другие
    процессы, пока мы читали, переносится в новый файл. Возвращает, сколько
    строк убрано."""
    with open(path, "rb") as f:
        data = f.read()
    keep: list[bytes] = []
    gone = 0
    for line in data.splitlines(keepends=True):
        day = line[:10].decode("ascii", errors="replace")
        if not _DAY_RE.match(day):
            gone += 1                           # не строка журнала — мусор
            continue
        if day < edge and day in done_days:
            gone += 1
            continue
        keep.append(line)
    if not gone:
        return 0
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(b"".join(keep))
        try:                                    # дописанное за это время
            with open(path, "rb") as src:
                src.seek(len(data))
                f.write(src.read())
        except OSError:
            pass
    if tmp.stat().st_size == 0:                 # старый месяц убран целиком
        tmp.unlink()
        path.unlink()
    else:
        os.replace(tmp, path)
    return gone


def purge(done_days: set[str], today: str | None = None) -> int:
    """Уборка журнала и маячков: строки старше 10 дней — только тех дней,
    что уже лежат в суточных суммах (`done_days`). Несчитанный день не
    трогаем, сколько бы ему ни было. Сбой одного файла — не повод бросать
    остальные. Возвращает, сколько строк убрано."""
    edge = keep_from(today)
    gone = 0
    for pattern in ("visits-*.log", "beacons-*.log"):
        for path in sorted(folder().glob(pattern)):
            try:
                gone += _rewrite(path, done_days, edge)
            except OSError:
                pass
    return gone


def claim_daily(today: str | None = None) -> bool:
    """Уборка — не чаще раза в сутки на все процессы: кто первым создал метку
    дня, тот и убирает. Старые метки стираются."""
    today = today or f"{_now():%Y-%m-%d}"
    mark = folder() / f"visits-purge-{today}.mark"
    try:
        fd = os.open(mark, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except OSError:
        return False
    for old in folder().glob("visits-purge-*.mark"):
        if old != mark:
            try:
                old.unlink()
            except OSError:
                pass
    return True


#: тесты выключают фоновую уборку, чтобы она не писала в базу у них за спиной
AUTO_MAINTAIN = True
_kicked_day = ""


def kick() -> None:
    """Раз в сутки (на процесс) — фоновая сводка дней и уборка. Отдельным
    потоком: запрос посетителя её не ждёт, cron не нужен."""
    global _kicked_day
    if not AUTO_MAINTAIN:
        return
    day = f"{_now():%Y-%m-%d}"
    if day == _kicked_day:
        return
    _kicked_day = day
    threading.Thread(target=_background, daemon=True,
                     name="visits-maintain").start()


def _background() -> None:
    try:
        from . import visit_stats
        visit_stats.refresh()
    except Exception as e:                                   # noqa: BLE001
        print(f"посещения: сводка/уборка не прошла ({type(e).__name__}: {e})")


# ── слова для ленты ──────────────────────────────────────────────────────────

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
    if row["method"] == "SKIP":
        return f"{row['path'].strip('()')}: {row['status']}"
    if row["method"] == "POST" and row["endpoint"] == "login":
        # удачный вход отвечает переадресацией, неудачный — той же страницей
        return ("вошёл в админку" if row["status"].startswith("3")
                else "неудачная попытка входа")
    if not row["endpoint"]:
        return f"искал несуществующее: {row['path']}"
    if (row["who"] != "admin" and row["status"].startswith("3")
            and row["endpoint"] not in OPEN_TO_ALL):
        # гостя (и друга) с закрытой страницы сайт отправляет на вход
        return f"хотел открыть закрытую страницу {row['path']} — отправлен на вход"
    known = ACTIONS.get((row["method"], row["endpoint"]))
    if known:
        return known
    return f"{'открыл' if row['method'] == 'GET' else 'отправил'} {row['path']}"


@lru_cache(maxsize=4096)
def device(agent: str) -> str:
    """Коротко, с чего зашли: «Chrome, Windows», «Safari, iPhone», «бот: …».
    Подписей мало, строк много — ответ запоминаем."""
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
        ("CriOS", "Chrome"), ("Chrome/", "Chrome"), ("Firefox/", "Firefox"),
        ("Safari/", "Safari")) if mark in agent), "")
    return ", ".join(x for x in (browser, system) if x) or agent[:40]

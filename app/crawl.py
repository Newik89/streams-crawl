# -*- coding: utf-8 -*-
"""План обхода: какие адреса надо скачать (ТЗ разд. 5, шаг 1).

Сайты устроены по-разному, и от этого напрямую зависит, сколько запросов
уйдёт на один источник:

* **сетка** — `tv.nova.cz`, `sporttv.pt`: один адрес, и в ответе сразу все
  каналы на две недели вперёд. Один запрос на весь источник;
* **канал в адресе** — `nova.bg`, `teleman.pl`: свой адрес на каждый канал и
  каждый день. `teleman.pl` при окне в 5 дней — это 26 × 5 = 130 запросов.

Поэтому план строится заранее и его видно до выхода на сайты: владелец
смотрит на число запросов и решает, какое окно брать. Массовые прогоны
запрещены (`HANDOFF.md` → «Грабли»), и считать нагрузку задним числом поздно.

Какие каналы обходить, берём из `source_channels` (`include=1`), а не из
адреса закладки: там у половины сайтов стоял один канал, часто неспортивный.
Адрес на нужный день собирает `app.urls.resolve()` — своих склеек даты нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date, timedelta
import json

from . import urls

#: сайты-сетки: дата и канал в адресе не нужны, всё приходит одним ответом
#: (`tvarenasport.com/tv-scheme` — 18 каналов Arena на 7 дней одним запросом;
#: рамки Arena `.ba`/`.hr` — 12 и 10 каналов на 7 дней, `.si` — 5 каналов,
#: но только текущий день)
GRID_DOMAINS = {"tv.nova.cz", "sporttv.pt", "tvarenasport.com",
                "tvarenasport.ba", "tvarenasport.hr", "tvarenasport.si",
                "trtspor.com.tr", "skysports.com", "maxsport.live", "bnt.bg",
                "tring.al", "football-tv.ru", "rtrs.tv", "trt.net.tr",
                "mediaklikk.hu", "sports.kz", "primaplay.ro",
                # пачка 01.09 (четвёртая): словацкий фильтр «Športové» —
                # 11 спортканалов одной страницей; кипрский fetchLiveSports —
                # неделя трансляций одним ответом
                "tv-program.aktuality.sk", "epg.cyta.com.cy",
                # пачка 01.09 (пятая): турецкий S Sport — неделя и оба канала
                # одной страницей, дата и канал в календарной ссылке строки
                "ssport.tv",
                # SPORT1: открытая ручка без параметров, сутки с хвостом
                "tv.sport1.de",
                # Kanal 1: одна страница держит оба канала и две недели,
                # дата в адрес не нужна
                "kanal1sport.sk",
                # Canal 11: ручка платформы отдаёт ближайшие матчи списком,
                # дата в запрос не входит
                "canal11.pt",
                # Sport1 CZ/SK: одна страница, три канала, показанный день;
                # сетку рисует скрипт — только браузером (needs_js=1)
                "sport1tv.cz",
                # венгерский собрат: та же тема, два канала, тоже браузером
                "sport1tv.hu",
                # агрегатор матч→каналы: один JSON на текущий день, ключ
                # одноразовый — {WARMKEY} из warmup-страницы
                "sporteventz.com",
                # греческий Novasports: 25 каналов текущего дня одной
                # страницей (вся линейка + Eurosport GR + Cosmote)
                "novasports.gr",
                # Беларусь 5: недельные блоки в props — один заход браузером
                "news.by",
                # OneSoccer: одна страница ближайших трансляций
                "onesoccer.ca",
                # фид flashscore: календарь футбола дня одним ответом (эталон)
                "global.flashscore.ninja"}

#: «канальные сетки»: адрес на канал БЕЗ даты — страница канала сама держит
#: сегодня и завтра (`programetv.ro`: массивы `shows` и `nextDayShows`).
#: Один запрос на канал за обход. Сюда же livesoccertv (этап 6в): страницы
#: 7 каналов SuperSport Албания, сетка на дни вперёд одним запросом.
CHANNEL_GRID_DOMAINS = {"programetv.ro", "poverkhnost.tv",
                        # mojtv.hr отсюда убран 09.09: у сайта есть страницы
                        # на неделю вперёд (`danas`/`sutra`/имя дня недели —
                        # подсказка владельца), и его сетка теперь
                        # разворачивается по дням окна меткой {HRDAY}
                        "digisport.ro",
                        # у ORF адрес дня хеширован и вычислить его нельзя,
                        # зато короткий index.html держит сегодня и хвост завтра
                        "tv.orf.at",
                        # A Spor: вкладки других дней пустые, в HTML только
                        # сегодня
                        "aspor.com.tr",
                        # Diema Xtra: адрес на канал, в ответе вся неделя
                        "diemaxtra.nova.bg",
                        # RTE: у каждого канала свой файл `data-feed/pa`,
                        # в нём сразу десять суток
                        "rte.ie",
                        # РТС: адрес на канал, в ответе сутки; дату в адрес
                        # не ставим — там месяц с нуля (`ГРАБЛИ.md`)
                        "rts.rs",
                        # страницы каналов SuperSport (этап 6в)
                        "livesoccertv.com",
                        # Sport Klub: ручка United Cloud на канал, окно на
                        # неделю одним запросом ({UNIXMSDAY}–{UNIXMSWEEK})
                        "sportklub.hr"}

#: «дневные сетки»: один адрес на день, в ответе сразу все каналы.
#: в шаблоне адреса метка `{N}` — номер дня окна, 1-based
#: (`polsatsport.pl/ajax-program-tv-column/module/page{N}/`: page1 — сегодня)
DAY_GRID_DOMAINS = {"polsatsport.pl", "allente.no", "ceskatelevize.cz",
                    "srf.ch", "oneplaysport.cz", "ntvplus.tv",
                    "sport1.maariv.co.il", "ert.gr",
                    # liveonsat: адрес просит дату началом и концом окна,
                    # берём по дню — в ответе матчи всего мира с каналами
                    "liveonsat.com",
                    # Ziggo Sport: дневной файл кэша со всеми каналами
                    "ziggosport.nl",
                    # TV 2 Norge: открытая ручка EPG, 69 каналов на день
                    "tv2.no",
                    # atv: свой запрос сетки на день, канал один
                    "atv.com.tr",
                    # Sport5: один запрос на день, в ответе все пять каналов
                    "sport5.co.il",
                    # dagenstv/kolla.tv: сутки по 16 шведским каналам разом
                    "dagenstv.com",
                    # COSMOTE: один адрес на день, в ответе все девять
                    # спортивных каналов; берём через читалку
                    "cosmotetv.gr",
                    # ΣΚΑΪ: один канал, адрес на день
                    "skai.gr",
                    # TRT Avaz: один канал, адрес на день
                    "trtavaz.com.tr",
                    # DR: открытый JSON, оба канала одним запросом на день
                    "dr.dk",
                    # OnePlay: ручка программы (POST), сутки по 52 каналам
                    # разом, в описании вид спорта и «Přímý přenos»
                    "oneplay.cz"}
# эталон flashscore.mobi с 02.09 идёт обычным «канал × день»: три раздела
# (football/basketball/tennis) лежат в source_channels, ?d={DAYNUM} в page_url

#: постраничные сводники: одна лента всех каналов с пагинацией, `{N}` —
#: номер страницы. Значение — страниц НА ДЕНЬ окна (у `teleman.pl/sport`
#: 20 строк на страницу; 3 страницы на день хватает и на выходные).
#: Нашёл владелец 31.08: это 6 запросов вместо 52 канальных страниц.
#: сводник с пагинацией: сколько страниц берём на каждый день окна.
#: 3 страницы не докручивали до дальних дней — у польских каналов шестой
#: день окна оставался пустым (#2064, разбор владельца 10.09)
PAGED_DOMAINS = {"teleman.pl": 5}


@dataclass
class Target:
    url: str                 # что скачать
    source_id: int
    domain: str
    channel: str = ""        # какой канал ждём на странице ("" — сетка)
    day: _date | None = None  # за какой день ("" — сетка сразу на всё окно)
    post: dict | None = None  # поля формы: с ними уходит POST, а не GET


#: предел глубины: правило владельца «сегодня и не больше 6 дней вперёд»
#: (01.09) — глубже витрина всё равно не показывает
MAX_DAYS_AHEAD = 7

#: справочники: каналов на витрину не дают, служат эталоном имён и времени.
#: Только им оставлена своя глубина — канон нужен и на дальние дни, иначе
#: имена оттуда не с чем сверять (03.09: 40 % игр без канона шли с 3-го дня).
#: Всё, что показывает каналы, ходит на одно окно со всеми (владелец 09.09:
#: «выбираю 2 дня — все каналы на 2 дня»).
REFERENCE_DOMAINS = {
    "flashscore.mobi", "m.flashscore.gr", "m.flashscore.bg", "m.flashscore.ro",
    "m.flashscore.com.tr", "m.flashscore.pl", "m.flashscore.ru",
    "m.flashscore.ua", "m.rezultati.com", "m.eredmenyek.com", "m.livesport.cz",
    "sporteventz.com", "liveonsat.com",
}


def depth(config: dict, days: int, domain: str = "") -> int:
    """Сколько дней вперёд качать этот сайт.

    Правило владельца 09.09: **глубина одинакова для всех каналов** — какое
    окно выбрано в форме или кнопкой, столько дней и качается у каждого
    источника расписания. Своя глубина (`selector_config.days_ahead`)
    осталась только у справочников из `REFERENCE_DOMAINS`: они каналов не
    показывают, а канон имён нужен на всю ширину витрины.

    До 09.09 глубина у каждого сайта была своя (5 у дешёвых сеток, 7 у
    эталона, 2 у остальных) — из-за этого у одной и той же игры каналы
    появлялись вразнобой, и владелец не понимал, почему у субботнего матча
    нет каналов, которые сайт уже показывает.
    """
    try:
        own = int(config.get("days_ahead") or 0)
    except (TypeError, ValueError):
        own = 0
    bare = (domain or "").removeprefix("www.")
    if own > 0 and bare in REFERENCE_DOMAINS:
        return min(MAX_DAYS_AHEAD, own)
    got = min(MAX_DAYS_AHEAD, days) if days > 0 else days
    # Потолок для отдельного сайта (владелец 10.09, по случаю mojtv.hr):
    # «даже если я нажал кнопку 6 дней — этот пусть берёт 1+3». Общее окно
    # он не отменяет, только не даёт заходить дальше своего предела.
    try:
        cap = int(config.get("max_days") or 0)
    except (TypeError, ValueError):
        cap = 0
    if cap > 0 and got > 0:
        return min(got, cap)
    return got


def window(days: int, start: _date | None = None) -> list[_date]:
    """Окно обхода: сегодня и ещё `days - 1` вперёд (ТЗ разд. 2 — 2 или 5)."""
    first = start or _date.today()
    return [first + timedelta(days=i) for i in range(max(1, days))]


def plan_source(conn, source_id: int, days: int = 2,
                start: _date | None = None) -> list[Target]:
    row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not row:
        return []
    config = json.loads(row["selector_config"] or "{}") or {}
    marks = config.get("url_marks") or {}
    days = depth(config, days, row["domain"])   # окно одно на всех, кроме справочников
    #: сайты, у которых день переключается формой, а не адресом: поля лежат
    #: в карточке источника (`post_fields`), даты в них — теми же метками
    post_fields = config.get("post_fields") or None

    def form(day: _date | None) -> dict | None:
        """Поля формы на конкретный день: метки даты в значениях подставлены."""
        if not post_fields:
            return None
        return {k: urls.resolve(str(v), "", day=day, **marks)
                for k, v in post_fields.items()}

    if row["domain"] in GRID_DOMAINS:
        # сетка: адрес один, дата и канал в него не подставляются
        return [Target(url=row["url_pattern"] or row["base_url"],
                       source_id=row["id"], domain=row["domain"],
                       post=form(None))]

    if row["domain"] in CHANNEL_GRID_DOMAINS:
        # канальная сетка: адрес на канал, дата не подставляется
        channels = conn.execute(
            "SELECT raw_name, page_url FROM source_channels "
            "WHERE source_id=? AND include=1 ORDER BY raw_name",
            (source_id,)).fetchall()
        return [Target(url=c["page_url"] or row["url_pattern"] or row["base_url"],
                       source_id=row["id"], domain=row["domain"],
                       channel=c["raw_name"], post=form(None))
                for c in channels]

    if row["domain"] in DAY_GRID_DOMAINS:
        # дневная сетка: адрес на день, каналы все разом
        return [Target(
            url=urls.resolve(row["url_pattern"], row["base_url"], day=day,
                             N=str(i + 1), **marks),
            source_id=row["id"], domain=row["domain"], day=day,
            post=form(day))
            for i, day in enumerate(window(days, start))]

    if row["domain"] in PAGED_DOMAINS:
        # сводник с пагинацией: страницы 1..N, дата видна в самих строках
        first = window(1, start)[0]
        pages = max(1, days) * PAGED_DOMAINS[row["domain"]]
        return [Target(
            url=urls.resolve(row["url_pattern"], row["base_url"], day=first,
                             N=str(p), **marks),
            source_id=row["id"], domain=row["domain"], day=first)
            for p in range(1, pages + 1)]

    channels = conn.execute(
        "SELECT raw_name, page_url FROM source_channels "
        "WHERE source_id=? AND include=1 ORDER BY raw_name", (source_id,)).fetchall()
    if not channels:
        # каналы ещё не разобраны — идём по одному адресу из карточки
        channels = [{"raw_name": "", "page_url": row["url_pattern"] or row["base_url"]}]

    out = []
    for channel in channels:
        pattern = channel["page_url"] or row["url_pattern"]
        for i, day in enumerate(window(days, start)):
            # {DAYNUM} — номер дня от сегодня, 0-based: `rtcg.me` просит
            # `day=0` за сегодня, даты в адресе у него нет
            out.append(Target(
                url=urls.resolve(pattern, row["base_url"], day=day,
                                 DAYNUM=str(i), **marks),
                source_id=row["id"], domain=row["domain"],
                channel=channel["raw_name"], day=day, post=form(day)))
    return out


def plan(conn, domains=None, days: int = 2, start: _date | None = None) -> list[Target]:
    """План по всем включённым источникам-расписаниям с открытым доступом."""
    query = ("SELECT id FROM sources WHERE enabled=1 AND role='schedule' "
             "AND access='open'")
    args: list = []
    if domains:
        query += f" AND domain IN ({','.join('?' * len(domains))})"
        args = list(domains)
    out = []
    for row in conn.execute(query, args):
        out.extend(plan_source(conn, row["id"], days, start))
    return out

def templates(conn, domains=None) -> list[dict]:
    """План в виде шаблонов, а не готовых ссылок.

    Нужен для обхода на стороне (GitHub Actions): файл плана лежит в
    репозитории и не должен устаревать. Дата в нём остаётся меткой
    (`{YYYY}`), а подставляется в день запуска — иначе через неделю обход
    пойдёт за прошлое число, ровно как закладки владельца с датами 2024 года.
    """
    # new — не обкатан, deferred — отложен владельцем, closed/parked —
    # закрыт; им в плане обхода не место: 04.09 регенерация втащила бы
    # 12 таких доменов (vtm.be, tntsports…) в ежедневный обход без обкатки.
    # broken не исключаем: пусть обход пробует — вдруг сайт ожил
    query = ("SELECT * FROM sources WHERE enabled=1 AND role='schedule' "
             "AND access='open' "
             "AND status NOT IN ('new', 'deferred', 'closed', 'parked')")
    args: list = []
    if domains:
        query += f" AND domain IN ({','.join('?' * len(domains))})"
        args = list(domains)

    out = []
    for row in conn.execute(query, args):
        config = json.loads(row["selector_config"] or "{}") or {}
        marks = config.get("url_marks") or {}
        grid = row["domain"] in GRID_DOMAINS
        include = [c["raw_name"] for c in conn.execute(
            "SELECT raw_name FROM source_channels WHERE source_id=? AND include=1 "
            "ORDER BY raw_name", (row["id"],))]
        if grid or row["domain"] in DAY_GRID_DOMAINS \
                or row["domain"] in PAGED_DOMAINS:
            # у сетки адрес один, но знать, какие каналы из неё брать, всё равно
            # надо: в ответе приходят все, включая сериальные
            channels = [{"name": "", "pattern": row["url_pattern"] or row["base_url"]}]
        else:
            found = conn.execute(
                "SELECT raw_name, page_url FROM source_channels "
                "WHERE source_id=? AND include=1 ORDER BY raw_name",
                (row["id"],)).fetchall()
            channels = [{"name": c["raw_name"],
                         "pattern": c["page_url"] or row["url_pattern"] or row["base_url"]}
                        for c in found] or [
                {"name": "", "pattern": row["url_pattern"] or row["base_url"]}]
        # у сводника с пагинацией (teleman) дальние дни ненадёжны, но есть
        # страницы каналов с датой — их берёт СКАН ДАТЫ (идея владельца
        # 05.09); в ежедневный обход они не идут: 38 каналов × 5 дней —
        # бан-риск, сводник справляется с ближними днями сам
        day_channels = []
        if row["domain"] in PAGED_DOMAINS:
            day_channels = [
                {"name": c["raw_name"], "pattern": c["page_url"]}
                for c in conn.execute(
                    "SELECT raw_name, page_url FROM source_channels "
                    "WHERE source_id=? AND include=1 AND page_url != '' "
                    "ORDER BY raw_name", (row["id"],))
                if "{" in (c["page_url"] or "")]
        out.append({"domain": row["domain"], "timezone": row["timezone"],
                    "grid": grid, "marks": marks, "include": include,
                    # сайт отвечает 200, а расписание рисует скриптом
                    # (`rtcg.me`): такие берём сразу браузером
                    "browser": bool(row["needs_js"]),
                    "days_inline": row["domain"] in CHANNEL_GRID_DOMAINS,
                    "pages_per_day": PAGED_DOMAINS.get(row["domain"], 0),
                    "day_channels": day_channels,
                    # своя глубина в днях остаётся только у справочников
                    # (0 — по окну обхода, так теперь у всех каналов)
                    "days_ahead": depth(config, 0, row["domain"]),
                    # потолок глубины и «только по кнопке» (владелец 10.09):
                    # сайт, который сердится на частые заходы, из ночного
                    # обхода убираем, а по кнопке он ходит на свою глубину
                    "max_days": int(config.get("max_days") or 0),
                    "manual_only": bool(config.get("manual_only")),
                    # сайт качает САМ СЕРВЕР (`server_crawl.py`, бан сетей
                    # GitHub): с GitHub к нему не ходим вовсе — даже по
                    # кнопке он ответил бы 403 (слово владельца 12.09)
                    "by_server": bool(config.get("by_server")),
                    # у отдельного канала расписание бывает короче, чем у
                    # соседей: RTP Açores отдаёт три дня, остальные четыре
                    # канала rtp.pt — все шесть (10.09). Дальние дни у него
                    # 404, и обход считал это поломкой сайта
                    "channel_days": config.get("channel_days") or {},
                    # поля формы: обход отправит их POST-ом, метки даты в
                    # значениях подставит в день запуска
                    "post_fields": config.get("post_fields") or None,
                    # адрес обычной страницы, которую надо открыть перед
                    # запросом данных, чтобы получить куки сессии
                    "warmup_url": config.get("warmup_url") or "",
                    # тело запроса как JSON и свои заголовки: так отдаёт
                    # данные платформа Pixellot (`canal11.pt`)
                    "post_json": config.get("post_json"),
                    "headers": config.get("headers"),
                    "base_url": row["base_url"], "channels": channels})
    return out

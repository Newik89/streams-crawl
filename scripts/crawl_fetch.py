# -*- coding: utf-8 -*-
r"""Живой обход по плану: скачать страницы и сказать, что с них пришло.

Запускается **на GitHub Actions**, а не с домашнего компьютера — так решил
владелец 29.08.2026. Ровно тот же скрипт работает и локально, если когда-то
понадобится сравнить.

Главный вопрос первой пробы: **не режет ли нас сайт за то, что запрос идёт из
дата-центра.** Домашнему компьютеру Cloudflare чаще верит на слово, серверу —
реже. Поэтому обход не просто качает страницы, а по каждой сразу пишет:
пустил ли сайт, не подсунул ли заглушку «подтвердите, что вы человек», сколько
на странице нашлось меток времени. По этому отчёту видно, годится площадка
или нет, — гадать не приходится.

Режимы:
    --probe   по одному адресу на сайт (4 запроса) — проба площадки
    --full    весь план целиком (62 адреса при окне 2 суток)
    --assess  без сети: оценить готовый report.json — провальный ли обход

Провал (аудит 07.09, A4): полный обход без фильтров, где не открылась
больше четверти страниц или пятая часть сайтов не открылась ни разу,
кончается кодом 2 — прогон на GitHub красный, результат в репозиторий не
едет, владельцу уходит issue. До этого обход «не умел падать».

Дата в план не зашита: адреса там с метками `{YYYY}`, и день подставляется
в момент запуска (`app/urls.py`). Иначе через неделю обход пошёл бы за
прошлое число — на этом проект уже обжигался.

Запуск:
    python scripts/crawl_fetch.py --probe
    python scripts/crawl_fetch.py --full --days 2
    python scripts/crawl_fetch.py --assess results/report.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from urllib.parse import urlsplit                   # noqa: E402

from app import fetch, protection, timemarks, urls   # noqa: E402

PLAN = ROOT / "data" / "crawl_plan.json"

#: язык браузера под страну сайта — так страница отдаётся такой же, как местному
LOCALES = {"nova.bg": "bg-BG", "tv.nova.cz": "cs-CZ",
           "teleman.pl": "pl-PL", "sporttv.pt": "pt-PT",
           "polsatsport.pl": "pl-PL", "raiplay.it": "it-IT", "tvarenasport.com": "sr-RS"}
OUT = ROOT / "recon" / "raw_live"

#: чем кончается страница, когда сайт нас не пустил (в отличие от «пусто»:
#: та открылась, просто расписания на ней нет)
BROKEN = ("не открылась", "заглушка защиты")
#: пороги провала (аудит 07.09, A4). Считаются только полному обходу без
#: `--only/--urls/--date`: точечный прогон по одному сайту закономерно может
#: быть «весь красный», а скан далёкой даты — сплошь 404; тревога по ним — шум
FAIL_ROWS_SHARE = 0.25      # доля страниц «не открылась/заглушка»
FAIL_DOMAINS_SHARE = 0.20   # доля сайтов без единой открывшейся страницы
REFERENCE_DOMAIN = "flashscore.mobi"   # эталон: без него — предупреждение
#: сколько упавших адресов повторяем в конце прогона (браузером, медленнее)
RETRY_LIMIT = 40

#: «дозор»: сайты, которые нас не пускают, но выбрасывать их жалко. Такой
#: сайт пробуем ОДНИМ адресом и не чаще раза в сутки (решение владельца
#: 09.09: «может, он будет пускать раз в сутки — тогда дать сигнал»).
#: Пока не пускает, в отчёт не идёт вовсе: шесть отказов за прогон портили
#: статистику сбоев и путали владельца.
DAILY_PROBE = {"liveonsat.com"}
#: сколько часов ждём между заходами дозора
PROBE_EVERY_HOURS = 20
#: где помним, когда дозор ходил в последний раз (файл едет в репозиторий
#: вместе с results/, поэтому память переживает прогоны на GitHub)
PROBE_MEMORY = ROOT / "results" / "dozor.json"


def probe_memory(path: Path | None = None) -> dict:
    """Когда каждый сайт-дозор проверяли в последний раз и чем кончилось."""
    try:
        return json.loads((path or PROBE_MEMORY).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def probe_due(domain: str, memory: dict, now: datetime | None = None) -> bool:
    """Пора ли снова стучаться на этот сайт."""
    from datetime import datetime as _dt
    now = now or _dt.now(timezone.utc).replace(tzinfo=None)
    when = (memory.get(domain) or {}).get("когда") or ""
    try:
        last = _dt.strptime(when, "%Y-%m-%d %H:%M")
    except ValueError:
        return True
    return (now - last).total_seconds() >= PROBE_EVERY_HOURS * 3600


def json_body(source: dict, day: date, url: str) -> dict | None:
    """Тело запроса как JSON: метки даты подставлены, а `{channel_id}` взят
    из самого адреса канала.

    Тело у источника одно, а канал у каждой строки свой (`webtv.sk`:
    `joj_sport`, `joj_sport_2`, …). Носителем и служит адрес канала —
    `…/epg/channel?channel_id=joj_sport`: сервер лишний параметр не
    замечает, а нам он говорит, о ком спрашиваем.
    """
    body = source.get("post_json")
    if not body:
        return None
    from urllib.parse import parse_qs, urlsplit
    got = parse_qs(urlsplit(url).query).get("channel_id")
    marks = {"channel_id": got[0]} if got else {}

    # метки бывают и в глубине тела: у `oneplay.cz` дата лежит в
    # payload.criteria.viewport.timeRange (18.09)
    def fill(value):
        if isinstance(value, str):
            return urls.resolve(value, "", day=day, **marks)
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        if isinstance(value, list):
            return [fill(v) for v in value]
        return value

    return fill(body)


def form(source: dict, day: date, marks: dict) -> dict | None:
    """Поля формы на этот день — у сайтов, где день переключается не адресом,
    а POST-ом (`sport1tv.cz`, `tvr.ro`). Метки даты подставляются так же, как
    в адресе."""
    fields = source.get("post_fields")
    if not fields:
        return None
    return {k: urls.resolve(str(v), "", day=day, **marks) for k, v in fields.items()}


def targets(plan: dict, days: int, probe: bool, start: date | None = None,
            single: bool = False, scheduled: bool = False,
            only: frozenset[str] | set[str] = frozenset()):
    """Адреса на сегодня. В пробе — по одному на сайт, чтобы проверить
    площадку четырьмя запросами, а не шестьюдесятью двумя. `single` —
    скан ОДНОЙ даты `start` (календарь владельца, 05.09): дневные сетки
    качаются только за этот день, глубины источников не разворачиваются."""
    first = start or date.today()
    for source in plan["sources"]:
        # «только по кнопке» (владелец 10.09): сайт, который сердится на
        # частые заходы, из ночного обхода убираем совсем — он ходит, лишь
        # когда обход заказан руками или кнопкой на сайте
        if scheduled and source.get("manual_only"):
            continue
        # «качает сервер» (владелец 12.09): сайт забанил сети GitHub —
        # обходы с GitHub его пропускают всегда, даже ручные: там
        # гарантированный 403, только пугавший красным на «Сломанных».
        # Исключение — явный `--only <домен>`: так сайт качает серверный
        # cron (`scripts/server_crawl.py`, 06:40 Киева) и так его можно
        # дёрнуть руками с сервера
        if source.get("by_server") and source["domain"] not in only:
            continue
        ppd = source.get("pages_per_day") or 0
        # «глубина источника» (этап 6е, A1): у эталона flashscore 7 дней,
        # у дешёвых дневных сеток 5 — независимо от окна обхода, оно
        # управляет остальными. Считает `app.crawl.depth`, сюда приезжает
        # готовым числом в плане (0 — по окну)
        span = 1 if single else (source.get("days_ahead") or days)
        # потолок глубины у этого сайта: окно 6 дней его не касается
        cap = source.get("max_days") or 0
        if cap and span > cap:
            span = cap
        if ppd and single and source.get("day_channels"):
            # скан даты: сводник показывает «от сейчас» и дальние дни
            # ненадёжен — берём страницы каналов с датой (идея владельца
            # 05.09: teleman.pl/program-tv/stacje/<канал>?date=…)
            for channel in source["day_channels"]:
                yield {
                    "domain": source["domain"], "channel": channel["name"],
                    "day": first.isoformat(),
                    "locale": LOCALES.get(source["domain"], "en-GB"),
                    "url": urls.resolve(channel["pattern"],
                                        source["base_url"], day=first,
                                        **(source["marks"] or {})),
                    "browser": source.get("browser", False),
                    "post": form(source, first, source["marks"] or {}),
                    "warmup": source.get("warmup_url") or "",
                    "post_json": json_body(source, first, ""),
                    "headers": source.get("headers"),
                }
            continue
        if ppd:
            # сводник с пагинацией (teleman.pl/sport): страницы 1..N,
            # даты стоят в самих строках — день тут только якорь
            pages = 1 if probe else max(1, span) * ppd
            pattern = source["channels"][0]["pattern"]
            for p in range(1, pages + 1):
                yield {
                    "domain": source["domain"], "channel": "",
                    "day": first.isoformat(),
                    "locale": LOCALES.get(source["domain"], "en-GB"),
                    "url": urls.resolve(pattern, source["base_url"],
                                        day=first, N=str(p),
                                        **(source["marks"] or {})),
                    "browser": source.get("browser", False),
                    "post": form(source, first, source["marks"] or {}),
                    "warmup": source.get("warmup_url") or "",
                    "post_json": json_body(source, first, ""),
                    "headers": source.get("headers"),
                }
            continue
        channels = source["channels"][:1] if probe else source["channels"]
        window = [first] if (source["grid"] or source.get("days_inline")
                             or probe) else \
            [first + timedelta(days=i) for i in range(span)]
        свои_дни = source.get("channel_days") or {}
        for channel in channels:
            окно = window
            предел = свои_дни.get(channel["name"] or "")
            if предел and len(окно) > предел:
                окно = окно[:предел]
            for day in окно:
                # {N} — номер дня от СЕГОДНЯ (дневные сетки вроде polsatsport.pl:
                # page1 — сегодня, page2 — завтра); остальным метка не мешает.
                # Считаем от сегодня, а не от первого дня окна: в скане даты
                # окно начинается с выбранного дня, и flashscore `?d={DAYNUM}`
                # отдавал сегодняшний футбол вместо 19.09 — все строки
                # «угадаек» ушли в повторы без эталона (14.09, #2364)
                marks = {**(source["marks"] or {}),
                         "N": str((day - date.today()).days + 1),
                         # {DAYNUM} — тот же номер, но 0-based: `rtcg.me`
                         # просит `day=0` за сегодня
                         "DAYNUM": str((day - date.today()).days)}
                yield {
                    "domain": source["domain"],
                    "channel": channel["name"],
                    "day": "" if source["grid"] else day.isoformat(),
                    "locale": LOCALES.get(source["domain"], "en-GB"),
                    "url": urls.resolve(channel["pattern"], source["base_url"],
                                        day=day, **marks),
                    "browser": source.get("browser", False),
                    "post": form(source, day, marks),
                    "warmup": source.get("warmup_url") or "",
                    "post_json": json_body(
                        source, day,
                        urls.resolve(channel["pattern"], source["base_url"],
                                     day=day, **marks)),
                    "headers": source.get("headers"),
                }


def verdict(page: fetch.Page) -> dict:
    """Что пришло со страницы: пустили ли нас и есть ли на ней расписание."""
    if not page.ok:
        why = page.error
        if page.body and protection.is_blocked(timemarks.clean(page.body), page.body):
            why = f"{page.error}, защита: {protection.guess_name(page.body) or 'не опознана'}"
        return {"итог": "не открылась", "почему": why,
                "байт": 0, "меток времени": 0, "чем": page.via}
    body = page.html.lstrip()
    if body[:1] in ("{", "["):
        # JSON-источник (polsatsport.pl, raiplay.it): меток `14:30` в нём
        # нет, время лежит числами — судим по тому, разбирается ли ответ
        try:
            filled = bool(json.loads(body))
        except ValueError:
            filled = False
        return {"итог": "расписание есть" if filled else "пусто",
                "почему": "" if filled else "JSON пуст или битый",
                "байт": len(page.html), "меток времени": 0, "чем": page.via}
    text = timemarks.clean(page.html)
    marks = timemarks.count(text)
    if protection.is_blocked(text, page.html):
        return {"итог": "заглушка защиты",
                "почему": protection.guess_name(page.html) or "не опознана",
                "байт": len(page.html), "меток времени": marks, "чем": page.via}
    if marks == 0:
        return {"итог": "пусто", "почему": "времени на странице нет",
                "байт": len(page.html), "меток времени": 0, "чем": page.via}
    return {"итог": "расписание есть", "почему": "",
            "байт": len(page.html), "меток времени": marks, "чем": page.via}


def assess(report: dict) -> tuple[int, list[str]]:
    """Провалился ли обход: код выхода (0 — норма, 2 — провал) и строки для
    человека. В консоли GitHub строки с префиксом `::error::`/`::warning::`
    сами становятся пометками на странице прогона."""
    rows = [r for r in (report.get("строки") or [])
            if r["domain"].removeprefix("www.") not in DAILY_PROBE]
    if not rows:
        return 2, ["::error::обход не сделал ни одного запроса"]
    broken = [r for r in rows if r.get("итог") in BROKEN]
    share = len(broken) / len(rows)
    opened: dict[str, int] = {}
    for r in rows:
        opened[r["domain"]] = opened.get(r["domain"], 0) + (
            0 if r.get("итог") in BROKEN else 1)
    dead = sorted(d for d, n in opened.items() if n == 0)
    dead_share = len(dead) / len(opened)
    notes: list[str] = []
    if share > FAIL_ROWS_SHARE:
        notes.append(f"::error::не открылись {len(broken)} из {len(rows)} страниц "
                     f"({share:.0%}) — порог {FAIL_ROWS_SHARE:.0%}")
    if dead_share > FAIL_DOMAINS_SHARE:
        notes.append(f"::error::без единой открывшейся страницы {len(dead)} из "
                     f"{len(opened)} сайтов ({dead_share:.0%}) — порог "
                     f"{FAIL_DOMAINS_SHARE:.0%}: {', '.join(dead[:12])}"
                     + (" …" if len(dead) > 12 else ""))
    if opened.get(REFERENCE_DOMAIN, 1) == 0:
        notes.append(f"::warning::эталон {REFERENCE_DOMAIN} не открылся ни разу — "
                     "склейка и канон имён в этом прогоне без него")
    code = 2 if any(n.startswith("::error::") for n in notes) else 0
    if code == 0:
        notes.append(f"обход в норме: не открылись {len(broken)} из {len(rows)} "
                     f"страниц ({share:.0%}), сайтов без удачи {len(dead)} из "
                     f"{len(opened)} ({dead_share:.0%})")
    return code, notes


def age_hours(games_json: Path) -> int:
    """Сколько часов прошло с поля «собрано» (его пишет parse_live.py по
    часам той машины: на GitHub — UTC). Нет файла или поля — 999."""
    from datetime import datetime, timezone
    try:
        when = json.loads(games_json.read_text(encoding="utf-8"))["собрано"]
        made = datetime.strptime(when, "%Y-%m-%d %H:%M")
    except (OSError, ValueError, KeyError, TypeError):
        return 999
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return max(0, int((now - made).total_seconds() // 3600))


def _mark(note: str) -> str:
    """Та же строка оценки, но для отчёта человеку: значок вместо префикса."""
    if note.startswith("::error::"):
        return "❌ " + note[len("::error::"):]
    if note.startswith("::warning::"):
        return "⚠️ " + note[len("::warning::"):]
    return "✅ " + note


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="по одному адресу на сайт")
    ap.add_argument("--full", action="store_true", help="весь план")
    ap.add_argument("--days", type=int, default=0, help="окно, суток")
    ap.add_argument("--delay", type=float, default=fetch.DELAY,
                    help="пауза между запросами к одному домену, секунд")
    ap.add_argument("--only", default="", help="только эти домены, через запятую")
    ap.add_argument("--no-browser", action="store_true",
                    help="не пробовать браузером там, где отказали")
    ap.add_argument("--browser", action="store_true",
                    help="сразу браузером, без обычного запроса: для сайтов, "
                         "которые отвечают 200, но расписание рисуют скриптом")
    ap.add_argument("--urls", default="",
                    help="проверить эти адреса вместо плана, через запятую — "
                         "так пробуют кандидатов на замену закрытому источнику")
    ap.add_argument("--post", default="",
                    help="поля формы `k=v&k2=v2` — тогда адреса из --urls "
                         "запрашиваются POST-ом, а не GET")
    ap.add_argument("--warmup", default="",
                    help="сперва открыть эту страницу той же сессией — для "
                         "сайтов, которые отдают данные только по куке")
    ap.add_argument("--date", default="",
                    help="скан одной даты ГГГГ-ММ-ДД (календарь владельца): "
                         "дневные сетки качаются только за этот день")
    ap.add_argument("--assess", default="",
                    help="без сети: оценить готовый report.json по порогам "
                         "провала и выйти с его кодом (0 — норма, 2 — провал)")
    ap.add_argument("--age", default="",
                    help="без сети: напечатать возраст поля «собрано» в этом "
                         "games.json, часов (999 — файла или поля нет); "
                         "им guard в crawl.yml решает, ходить ли страховке")
    ap.add_argument("--scheduled", action="store_true",
                    help="обход по расписанию, а не по кнопке: сайты с "
                         "пометкой «только по кнопке» пропускаются")
    ap.add_argument("--plan", default=str(PLAN))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    if args.age:
        print(age_hours(Path(args.age)))
        return 0
    if args.assess:
        # обкатка порогов на прошлом прогоне и на нарочно испорченной копии
        report = json.loads(Path(args.assess).read_text(encoding="utf-8"))
        code, notes = assess(report)
        print(f"{report.get('режим', '?')}, {report.get('когда', '?')}: "
              f"{len(report.get('строки') or [])} строк")
        for note in notes:
            print(note)
        return code

    if not args.probe and not args.full:
        args.probe = True                      # без явного указания — проба
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    days = args.days or plan.get("days", 2)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fetch.DELAY = args.delay
    fetcher = fetch.Fetcher(offline=False, use_cache=False,
                            browser_fallback=not args.no_browser,
                            browser_only=args.browser)

    if args.urls:
        # Разовая проверка сторонних адресов: годится ли сайт как источник и
        # пускает ли он нас с этой площадки. В план они не попадают.
        post = None
        if args.post:
            post = dict(pair.split("=", 1) for pair in args.post.split("&") if "=" in pair)
        jobs = [{"domain": urlsplit(u.strip()).netloc, "channel": "", "day": "",
                 "locale": "en-GB", "url": u.strip(), "post": post,
                 "warmup": args.warmup}
                for u in args.urls.split(",") if u.strip()]
    elif args.date:
        only = {d.strip() for d in args.only.split(",") if d.strip()}
        jobs = list(targets(plan, 1, args.probe,
                            start=date.fromisoformat(args.date), single=True,
                            only=only))
    else:
        only = {d.strip() for d in args.only.split(",") if d.strip()}
        jobs = list(targets(plan, days, args.probe, scheduled=args.scheduled,
                            only=only))
    if args.only:
        keep = {d.strip() for d in args.only.split(",") if d.strip()}
        jobs = [j for j in jobs if j["domain"] in keep]
    # дозор: один адрес в сутки вместо страницы на каждый день окна
    memory = probe_memory()
    probing: set[str] = set()
    if not args.urls:
        thinned, seen_probe = [], set()
        for j in jobs:
            bare = j["domain"].removeprefix("www.")
            if bare not in DAILY_PROBE:
                thinned.append(j)
                continue
            if bare in seen_probe or not probe_due(bare, memory):
                continue                      # уже взяли один или ещё рано
            seen_probe.add(bare)
            probing.add(bare)
            thinned.append(j)
        skipped = len(jobs) - len(thinned)
        jobs = thinned
        if skipped:
            print(f"дозор: {skipped} адрес(ов) отложены — "
                  f"эти сайты пробуем раз в {PROBE_EVERY_HOURS} ч\n")
    mode = "проба площадки" if args.probe else (
        f"скан даты {args.date}" if args.date
        else f"полный обход, окно {days} суток")
    print(f"{mode}: {len(jobs)} запрос(ов), пауза {args.delay} с между "
          f"запросами к одному сайту\n")

    report = []
    started = time.monotonic()
    #: адреса, не открывшиеся с первого раза: их повторяем в конце прогона
    #: медленнее и другим способом (просьба владельца 09.09 — «если сбой,
    #: пробовать этот сайт повторно в конце, медленнее, и другим способом»)
    retry: list[dict] = []
    for i, job in enumerate(jobs, 1):
        # сайт с пометкой `browser` берём сразу браузером: обычный запрос
        # вернёт честный 200 и пустой каркас (`rtcg.me`)
        fetcher.browser_only = args.browser or bool(job.get("browser"))
        page = fetcher.get_with_fallback(job["url"],
                                         locale=job.get("locale") or "en-GB",
                                         post=job.get("post"),
                                         warmup=job.get("warmup") or "",
                                         post_json=job.get("post_json"),
                                         extra=job.get("headers"))
        row = {**job, **verdict(page)}
        report.append(row)
        if page.ok:
            name = fetch.cache_name(job["url"],
                                    job.get("post") or job.get("post_json")).name
            (out / name).write_text(page.html, encoding="utf-8")
            row["файл"] = name
        elif page.body:
            # Сайт отказал, но что-то ответил — сохраняем это «что-то».
            # По нему видно, кто закрыл: сам сайт, Cloudflare или Imperva, —
            # и владелец может открыть страницу отказа своими глазами.
            name = fetch.cache_name(job["url"]).name.replace(".html", ".otkaz.html")
            (out / name).write_text(page.body, encoding="utf-8")
            row["файл отказа"] = name
        print(f"{str(i).rjust(3)}/{len(jobs)}  {job['domain'].ljust(12)} "
              f"{(job['channel'] or 'сетка')[:18].ljust(18)} "
              f"{row['итог'].ljust(16)} {row['меток времени']:>5} меток  "
              f"{row['почему']}")
        if row["итог"] in BROKEN:
            retry.append({"job": job, "row": row})

    if retry and not args.urls:
        # Второй заход (владелец 09.09). Медленнее втрое: сайт мог отказать
        # от частоты. И другим способом: страницы, которым не помог обычный
        # запрос, берём сразу браузером — он проходит там, где Imperva и
        # Cloudflare режут голый запрос (так живёт cosmotetv.gr).
        # Потолок: браузер тратит до минуты на адрес, и при массовом отказе
        # (обход красный) второй заход не должен съедать всё время job'а —
        # такие обвалы чинит не повтор, а разбор причины.
        if len(retry) > RETRY_LIMIT:
            print(f"\nупало {len(retry)} адресов — это не единичный сбой, "
                  f"второй заход пропускаем (потолок {RETRY_LIMIT})")
            retry = []
        pause = args.delay * 3
        print(f"\n{'=' * 70}\nвторой заход по упавшим: {len(retry)} адрес(ов), "
              f"пауза {pause} с, сразу браузером\n")
        fetch.DELAY = pause
        fetcher.browser_only = True
        healed = 0
        for n, item in enumerate(retry, 1):
            job = item["job"]
            page = fetcher.get_with_fallback(job["url"],
                                             locale=job.get("locale") or "en-GB",
                                             post=job.get("post"),
                                             warmup=job.get("warmup") or "",
                                             post_json=job.get("post_json"),
                                             extra=job.get("headers"))
            fresh = {**job, **verdict(page)}
            if fresh["итог"] in BROKEN:
                print(f"{str(n).rjust(3)}/{len(retry)}  {job['domain'].ljust(12)} "
                      f"снова {fresh['итог']}: {fresh['почему'][:60]}")
                continue
            name = fetch.cache_name(job["url"],
                                    job.get("post") or job.get("post_json")).name
            (out / name).write_text(page.html, encoding="utf-8")
            fresh["файл"] = name
            fresh["почему"] = (fresh["почему"] or "") + " (со второго захода)"
            item["row"].clear()
            item["row"].update(fresh)
            healed += 1
            print(f"{str(n).rjust(3)}/{len(retry)}  {job['domain'].ljust(12)} "
                  f"{fresh['итог']} — выправилось со второго захода")
        print(f"\nвторой заход выправил: {healed} из {len(retry)}")
        fetch.DELAY = args.delay
        fetcher.browser_only = args.browser

    # дозор: помним, когда ходили и чем кончилось; пустил — громкий сигнал
    if probing:
        from datetime import datetime as _dt
        stamp = _dt.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M")
        opened = []
        for domain in sorted(probing):
            row = next((r for r in report
                        if r["domain"].removeprefix("www.") == domain), None)
            verdict_now = row["итог"] if row else "не дошли"
            memory[domain] = {"когда": stamp, "итог": verdict_now}
            if verdict_now == "расписание есть":
                opened.append(domain)
        PROBE_MEMORY.parent.mkdir(parents=True, exist_ok=True)
        PROBE_MEMORY.write_text(json.dumps(memory, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        for domain in opened:
            print(f"::notice::ДОЗОР: {domain} снова пускает — сайт можно "
                  f"возвращать в обход")

    # оценка провала — только полному обходу без фильтров (см. FAIL_*);
    # едет в report.json, чтобы шаг-тревога crawl_alarm.py её показал
    strict = bool(args.full) and not (args.only or args.urls or args.date)
    payload = {"когда": str(date.today()), "режим": mode, "строки": report,
               "дозор": {d: memory.get(d, {}) for d in sorted(DAILY_PROBE)}}
    code, notes = assess(payload) if strict else (0, [])
    payload["оценка"] = {"код": code, "строки": notes, "строгая": strict}
    (out / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    by_domain: dict[str, dict[str, int]] = {}
    for row in report:
        by_domain.setdefault(row["domain"], {}).setdefault(row["итог"], 0)
        by_domain[row["domain"]][row["итог"]] += 1

    lines = ["# Итог обхода", "", f"Режим: {mode}. Запросов: {len(jobs)}. "
             f"Заняло {time.monotonic() - started:.0f} с.", "",
             "| Сайт | Результат |", "|---|---|"]
    print("\n" + "=" * 70)
    for domain, counts in sorted(by_domain.items()):
        text = ", ".join(f"{k} — {v}" for k, v in counts.items())
        print(f"  {domain.ljust(12)} {text}")
        lines.append(f"| {domain} | {text} |")
    # Отдельным списком — что именно не открылось, с адресом целиком.
    # Владелец 01.09: в отчёте должно быть видно, какой сайт не прошёл и по
    # какой ссылке, чтобы проверить его руками, не копаясь в report.json.
    broken = [r for r in report if r["итог"] in ("не открылась", "заглушка защиты")]
    if broken:
        lines += ["", f"## Не открылись — {len(broken)}", "",
                  "| Сайт | Канал | Что ответил | Ссылка |", "|---|---|---|---|"]
        for r in broken:
            why = (r["почему"] or r["итог"]).replace("|", "/")[:160]
            channel = (r.get("channel") or "сетка").replace("|", "/")
            lines.append(f"| {r['domain']} | {channel} | {why} | {r['url']} |")
        print()
        print(f"  НЕ ОТКРЫЛИСЬ: {len(broken)}")
        for r in broken:
            print(f"    {r['domain']}: {(r['почему'] or r['итог'])[:70]}")
            print(f"      {r['url']}")
    if notes:
        lines += ["", "## Оценка", ""] + [f"- {_mark(n)}" for n in notes]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    blocked = sum(1 for r in report if r["итог"] == "заглушка защиты")
    empty = sum(1 for r in report if r["итог"] in ("пусто", "не открылась"))
    print(f"\nстраницы и отчёт: {out}")
    if blocked:
        print(f"ВНИМАНИЕ: {blocked} страниц(ы) закрыты защитой — "
              f"с этой площадки сайт нас не пускает")
    elif not empty:
        print("все страницы открылись и расписание на них есть")
    if strict:
        for note in notes:
            print(note)
    else:
        print("(провал не оцениваем: не полный обход или есть --only/--urls/--date)")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

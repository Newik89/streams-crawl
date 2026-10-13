# -*- coding: utf-8 -*-
"""ДОЗАБОР упавших адресов успешного сбора — схема сбоев, шаг 5 (12.10.2026).

Правило владельца 06.10: «Не открылась часть сайтов → через время сходить
ТОЛЬКО к ним; открывшиеся не трогать; докачанное ДОПИСАТЬ к уже собранному».

КАК ИДЁТ. Полный сбор дошёл и влит в базу сервера, но часть адресов его
отчёта (`results/report.json`) — «не открылась»: сайт лёг (5xx) или не
ответил (сеть). Через час сторож сервера (`scripts/crawl_watch.py`, правило
С7 в шапке `app/watch.py`) заказывает ДОЗАБОР: тег `btn-redo-<id прогона>-
<время>` → `queue.yml` → `crawl.yml` со входами `from_run=<id>` и `redo=1`.
На GitHub страницы и отчёт того сбора берутся из его артефакта `obhod-N`,
`crawl_fetch.py --redo` качает заново ТОЛЬКО отобранные адреса, разбор идёт
по всем страницам вместе, итог — в `results/partial/` с пометкой
«режим»: «дозабор». Сервер вливает его (`streams-update.sh` →
`games_import.py`) в режиме «только добавить»: новые игры и отметки ложатся
к уже влитым, ничего не гасится. К сайтам — не больше `REDO_MAX_URLS`
запросов (плюс запасной браузер по тем же адресам).

ПРАВИЛА — по функции на правило (что случилось → что делаем):
  Д1. `eligible` — кто и после чего. Сторож, после УСПЕШНОГО полного сбора
      (виды заказов planned, early, manual — `REDO_KINDS`), закрытого как
      дошедший (done — результат забран сервером). Сорвавшиеся сборы идут
      по таблице RECOVERY (`app/watch.py`), дозабора у них нет; скан даты,
      сайт, сервер, переразбор и сам дозабор дозабора не получают.
  Д2. `row_class`, `skip_reason`, `pick`, `same_run` — что дозабирать.
      Строки отчёта ЭТОГО сбора (`same_run`: номер прогона в отчёте и метка
      «собрано» результата сходятся с прогоном) с итогом «не открылась»
      класса down (HTTP 5xx, в т. ч. 520–524) или net (нет ответа, DNS,
      таймаут). Класс строки — один на всех (`row_class`): им же считает
      причину провала `scripts/fail_reason.classify_rows`. НИКОГДА не берём:
      ban (заглушка защиты, 403, 429 — к закрывшим не ходим), страницу
      защиты с кодом 5xx («защита: …» в причине), прочие ответы 4xx (сайт
      ответил «нет такой страницы» — повтор не поможет), сайты дозора
      (раздел «дозор» отчёта — их пробуют раз в сутки). Отбор — ОДНА функция
      `pick`: её зовут и сторож (сколько упало, массовый ли сбой), и GitHub
      (какие адреса качать) — считают одинаково по одному и тому же отчёту.
  Д3. `plan` (время и отказы). Не раньше `REDO_AFTER_MINUTES` после конца
      сбора (сайт лёг — дать ему подняться; раньше — молча ждём) и не позже
      `REDO_LATE_HOURS`. Не заказываем, строка в «Прогоны»: ночь (сайты до
      утра отдают вчерашние телесутки — как у досрочного, С6); дни уже
      собрал более новый удачный полный (`watch.collected_by`); до
      ближайшего планового слота меньше `REDO_SLOT_GAP_MINUTES` (он сам всё
      соберёт; слот считается ближайшим ещё `REDO_SLOT_GRACE_MINUTES` после
      своего времени — сторож приходит в одну минуту с плановой заявкой, и
      её прогона GitHub ещё не видно). Ждём молча: идёт или ждёт очереди
      ЛЮБОЙ более новый полный обход (не только накрывающий все дни): дойдёт
      — его итог ляжет в results/ и дальше решит `same_run`, упадёт —
      дозабор пойдёт по отчёту нашего сбора. Откладываем — строка один
      раз, следующая проверка пробует снова: в очереди GitHub ждёт
      заказанный сбор (`watch.queue_refusal`) или в эту проверку уже ушла
      заявка (`t.sent`); так и не ушёл до `REDO_LATE_HOURS` — строка.
  Д4. `pick`, `plan`, `redo_today` — пределы. Один дозабор на сбор (пометка
      `redo` в записи книги о сборе, `redo_of` у записи дозабора); не больше
      `REDO_PER_DAY` в киевские сутки (считаются записи `redo-…` книги
      заказов — книга и есть память сторожа: закрытая запись живёт сутки);
      не больше `REDO_MAX_URLS` адресов — первые по порядку отчёта; упавших
      down/net больше `REDO_MASS` — массовый сбой, а не дозабор: строка, без
      заказа; ноль упавших — ничего не делаем, молча.
  Д5. Заявка: `request_crawl.py redo <id прогона> --redo-of=<id записи
      книги>` (сторож — `crawl_watch.order_redo`) → тег
      `btn-redo-<id>-<время>` → `queue.yml` → `crawl.yml` (`from_run=<id>`,
      `redo=1`, код — текущий main); прогон зовётся «Обход redo-<id>».
      Запись книги — вид `redo-<id прогона>` (ВИДЫ ЗАКАЗОВ в шапке
      `app/watch.py`), потолок хода — `watch.CEILING_MINUTES["redo"]`, итог
      — в `results/partial/` (`watch.RESULT_DIRS`).
  Д6. `job_of`, `merge` — GitHub (`crawl_fetch.py --redo`): качает ТОЛЬКО
      строки `pick` обычным путём с запасным браузером, не дольше
      `REDO_FETCH_MINUTES` (не успели — строки остаются как были); у сайта
      подряд не открылось `REDO_SITE_FAILS` адресов — остальные его адреса
      не трогаем (`site_down`, `count_fail`; строки как были, в разделе
      «дозабор» — «пропущено: сайт всё ещё лежит»). Страницы
      кладёт в ту же папку, где лежат страницы сбора, и пишет report.json:
      упавшие строки заменены свежими, остальные как были, плюс раздел
      «дозабор» (из какого прогона, сколько адресов, сколько выправилось).
  Д7. `games_mark`, `is_add_only`, `redone_files`, `tag_programs`,
      `keep_redone_games`, `only_redone`, `redone_rows` — ДОПИСАТЬ ТОЛЬКО
      ДОКАЧАННОЕ. Разбор (`parse_live.py`) разбирает все страницы (старые —
      лишь контекст склейки и повторов), но в games.json кладёт «режим»:
      «дозабор» и только записи со страниц, которые дозабор перекачал и
      которые ОТКРЫЛИСЬ (по ИМЕНИ ФАЙЛА из раздела «дозабор»: адреса мало —
      у POST-сайтов он общий на все дни); игра без таких записей
      выбрасывается. `games_import.py` по пометке «режим» вливает «только
      добавить» и ещё раз оставляет только помеченное (`only_redone`):
      добавляет НОВЫЕ игры и НОВЫЕ отметки; у существующих игр не трогает
      ни время, ни лигу, ни last_seen, существующую отметку не обновляет и
      погашенную не оживляет; НИЧЕГО не гасит (ни отметок каналов, ни
      сирот — `app/miss.py`, правило 0; ни отметок агрегаторов); о сайтах
      судит только по перекачанным строкам (`redone_rows`: last_success —
      их сайтам, счётчик сбоев не растёт); метку последнего сбора не
      двигает; «кто» = «дозабор» (`WHO`). Так более свежие данные (новый
      сбор, скан даты, кнопка сайта) дозабор старого сбора не откатывает.
      Файл переразбора (без пометки) вливается ровно как раньше.
  Д8. Сбой дозабора — не стартовал, упал, завис, не ушёл, оборвали
      проверку, остановлен кнопкой — по таблице RECOVERY (`app/watch.py`):
      «redo-…» → close, только строка в «Прогоны» (данные основного сбора
      уже влиты; ТРЕВОГИ нет — каждая уходит владельцу письмом). Дозабор не
      «полный сбор»: его прогон не отвечает за слот, не накрывает дни и не
      вытесняет ждущих (`watch.FULL_KINDS` и окна дней его не знают).
  Д9. Проверки — `scripts/test_redo.py`: сценарий на каждое правило.

ОТКАТ (git revert этой выкладки). Старый `games_import.py` пометки
«режим»: «дозабор» не знает и вольёт results/partial/ дозабора как
переразбор — С ГАШЕНИЕМ каналов. Поэтому ПЕРЕД откатом на сервере:
  1. посмотреть, дозабор ли лежит в results/partial/games.json (ключ
     «режим»: «дозабор»); нет — откатывать можно;
  2. если дозабор — убедиться, что он уже влит: метка «собрано» файла
     равна `last_import_stamp:partial` в базе
     (`venv/bin/python -c "from app import db; c = db.connect();
     print(db.get_setting(c, 'last_import_stamp:partial'))"`) — тогда
     старый код его второй раз не вольёт (одинаковую метку он пропускает);
  3. не влит (метки разные) — убрать файл из репозитория отдельным
     коммитом (`git rm results/partial/games.json`) и только потом откат.

Модуль — только стандартная библиотека: его зовут и сервер, и обход на
GitHub (`crawl_fetch.py`, `parse_live.py`, `fail_reason.py`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")

# ── все пороги дозабора — здесь; у каждого сказано, откуда цифра ─────────────

#: Д1: виды заказов (`watch.order_kind`), после успешного сбора которых
#: бывает дозабор, — полные сборы
REDO_KINDS = ("planned", "early", "manual")
#: Д3: не раньше стольких минут после конца сбора — сайт лёг, дать ему
#: подняться (схема сбоев: «T+60–90: дозабор упавших адресов»)
REDO_AFTER_MINUTES = 60
#: Д3: не позже стольких часов после конца сбора — тот же срок, что у заказа
#: книги (`watch.ORDER_TTL_HOURS`; совпадение сверяет test_redo.py)
REDO_LATE_HOURS = 6
#: Д3: до ближайшего планового слота меньше стольких минут — дозабор не
#: нужен, слот соберёт сам
REDO_SLOT_GAP_MINUTES = 60
#: Д3: слот считается «ближайшим» ещё столько минут ПОСЛЕ своего времени:
#: сторож (cron */15) приходит ровно в 08:15 / 16:15 / 20:30, в одну минуту
#: с плановой заявкой — её прогона GitHub ещё не показал, и дозабор встал
#: бы впереди планового или вытеснил бы его из очереди (замечание 13.10)
REDO_SLOT_GRACE_MINUTES = 30
#: Д4: «Пределы на сутки» схемы сбоев: дозаборов — не больше 3 в сутки…
REDO_PER_DAY = 3
#: …и не больше 40 адресов за дозабор (берём первые по порядку отчёта)
REDO_MAX_URLS = 40
#: Д4: упавших down/net больше — это массовый сбой, а не дозабор (уточнение
#: второго отчёта проектировщика 06.10)
REDO_MASS = 80
#: Д6: сколько минут дозабор качает на GitHub. 40 адресов с запасным
#: браузером (до минуты на адрес) обычно укладываются в 20–30 мин; не успели
#: — оставшиеся строки остаются как были. С установкой, артефактом и
#: разбором прогон укладывается в потолок `watch.CEILING_MINUTES["redo"]`
REDO_FETCH_MINUTES = 30

#: Д7: пометка режима в games.json дозабора и «кто» в строке «Прогонов»
MODE_KEY = "режим"
MODE = "дозабор"
WHO = "дозабор"
#: Д6: раздел report.json дозабора (его же разбор переносит в games.json)
SECTION = "дозабор"

#: итоги строки отчёта, когда сайт нас не пустил (как `crawl_fetch.BROKEN`)
BROKEN = ("не открылась", "заглушка защиты")
#: поля строки, которые пишет проверка страницы (`crawl_fetch.verdict`) и
#: сохранение файла; всё остальное в строке — задание обхода (адрес, канал,
#: день, POST-поля…), по нему страницу можно скачать заново
VERDICT_FIELDS = ("итог", "почему", "байт", "меток времени", "чем", "файл",
                  "файл отказа")

_5XX = re.compile(r"\b5\d\d\b")
_BAN = re.compile(r"\b(403|429)\b")
_4XX = re.compile(r"\bHTTP 4\d\d\b")


def _bare(domain) -> str:
    return str(domain or "").strip().lower().removeprefix("www.")


def hm(at: datetime) -> str:
    """Время → `ЧЧ:ММ` по Киеву для строк сторожа."""
    return at.astimezone(KYIV).strftime("%H:%M")


# ── Д1. кто и после чего ─────────────────────────────────────────────────────

def eligible(kind: str, record: dict) -> bool:
    """Д1: бывает ли дозабор после заказа книги `record` вида `kind`
    (`watch.order_kind`): полный сбор (`REDO_KINDS`), закрытый как дошедший
    (done), по которому дозабор ещё не решён (нет пометки `redo`)."""
    return kind in REDO_KINDS and bool(record.get("done")) and not record.get("redo")


# ── Д2. что дозабирать ───────────────────────────────────────────────────────

def row_class(row: dict) -> str:
    """Класс строки отчёта обхода: пусто — страница открылась (или «пусто»,
    «нет на этот день»); ban — заглушка защиты или HTTP 403/429; down —
    HTTP 5xx (в т. ч. 520–524); net — прочее «не открылась»: нет ответа,
    DNS, таймаут. Тот же класс считает причина провала
    (`fail_reason.classify_rows`). Не словарь (битый отчёт) — пусто."""
    if not isinstance(row, dict) or row.get("итог") not in BROKEN:
        return ""
    why = str(row.get("почему") or "")
    if row.get("итог") == "заглушка защиты" or _BAN.search(why):
        return "ban"
    if _5XX.search(why):
        return "down"
    return "net"


def skip_reason(row: dict, never=frozenset()) -> str:
    """Д2: почему строку НЕ дозабираем; пусто — берём (класс down или net).
    `never` — сайты дозора (без www): их пробуют раз в сутки, не чаще."""
    if not isinstance(row, dict):
        return "строка отчёта битая"
    kind = row_class(row)
    if not kind:
        return "открылась"
    if not isinstance(row.get("url"), str) or not row.get("url"):
        return "строка отчёта битая"
    if _bare(row.get("domain")) in never:
        return "сайт дозора"
    if kind == "ban":
        return "закрыт (защита, 403/429)"
    why = str(row.get("почему") or "")
    if "защит" in why.lower():
        return "страница защиты"
    if _4XX.search(why):
        return "ответ 4xx"
    return ""


@dataclass
class Pick:
    """Итог отбора (Д2, Д4)."""
    #: что качать заново — не больше `REDO_MAX_URLS`, по порядку отчёта
    rows: list = field(default_factory=list)
    #: их номера в списке «строки» отчёта (туда же ляжут свежие)
    index: list = field(default_factory=list)
    #: сколько всего упавших down/net
    total: int = 0
    #: упавших больше `REDO_MASS` — массовый сбой, качать нечего
    mass: bool = False
    #: не взятые упавшие — почему: {причина: сколько}
    skipped: dict = field(default_factory=dict)


def pick(report: dict) -> Pick:
    """Д2 + Д4: какие строки отчёта сбора качать заново. ОДНА функция на
    сервер (сторож: сколько упало, не массовый ли сбой) и GitHub
    (`crawl_fetch.py --redo`: что качать). Битый отчёт (не словарь, строки
    не списком, строка не словарь) проверку не роняет: такие строки — в
    `skipped` («строка отчёта битая»), не отчёт — ноль упавших."""
    report = report if isinstance(report, dict) else {}
    rows = report.get("строки")
    rows = rows if isinstance(rows, list) else []
    dozor = report.get("дозор")
    never = {_bare(d) for d in (dozor if isinstance(dozor, dict) else {})}
    take: list[int] = []
    skipped: dict[str, int] = {}
    for i, row in enumerate(rows):
        why = skip_reason(row, never)
        if why == "открылась":
            continue
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        take.append(i)
    mass = len(take) > REDO_MASS
    chosen = [] if mass else take[:REDO_MAX_URLS]
    return Pick(rows=[rows[i] for i in chosen], index=chosen, total=len(take),
                mass=mass, skipped=skipped)


def same_run(report, games, run_id, lo: datetime, hi: datetime) -> str:
    """Д2: отчёт на сервере (`results/report.json`) — того самого прогона?
    Пусто — да; иначе — почему нет. Сверяем номер прогона (поле «прогон»
    отчёта, `crawl_fetch.py` пишет его с 12.10; в старых отчётах его нет) и
    метку «собрано» соседнего games.json — отчёт и игры едут одним коммитом:
    метка должна лежать в окне [lo, hi] настоящего хода прогона (то же
    окно, что у `watch.result_state`)."""
    if not isinstance(report, dict) or not isinstance(games, dict):
        return "отчёта сбора на сервере нет"
    own = str(report.get("прогон") or "")
    if own and own != str(run_id):
        return f"отчёт на сервере — другого прогона ({own})"
    try:
        made = datetime.strptime(str(games.get("собрано") or ""),
                                 "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return "у результата на сервере нет метки «собрано»"
    if not lo <= made <= hi:
        return f"результат на сервере собран в {hm(made)} — другим прогоном"
    return ""


# ── Д3, Д4. когда и сколько ──────────────────────────────────────────────────

def redo_today(records: list[dict], now: datetime, at_of) -> int:
    """Д4: сколько дозаборов уже заказано в эти киевские сутки — записи
    `redo-…` книги заказов (`at_of` — `watch.record_at`: мгновение заказа)."""
    day = now.astimezone(KYIV).date()
    count = 0
    for record in records:
        if not str(record.get("what") or "").startswith("redo-"):
            continue
        at = at_of(record)
        if at is not None and at.astimezone(KYIV).date() == day:
            count += 1
    return count


def plan(*, end: datetime, now: datetime, choice: Pick, same: str, night: bool,
         next_slot: datetime, collected: str, going: str, today: int,
         blocker: str, deferred: bool) -> tuple[str, str]:
    """Дозабор успешного сбора, кончившегося в `end`, — что делать сейчас
    (Д3, Д4): (решение, слова). Проверки — в этом порядке:
      wait  — рано (меньше `REDO_AFTER_MINUTES` с конца сбора) или идёт
              полный обход, накрывающий эти дни (`going`): молча ждём;
      quiet — дозабор не нужен, молча: поздно и заявку не откладывали,
              отчёт на сервере не этого прогона (`same`), упавших down/net
              ноль;
      skip  — не заказываем, строка: массовый сбой, ночь, дни уже собраны
              (`collected`), до слота `next_slot` меньше часа, предел суток
              (`today`), так и не ушёл после отсрочек (`deferred`);
      defer — отложен (`blocker`: очередь GitHub занята, заявка уже ушла):
              строка один раз, следующая проверка пробует снова;
      order — заказать. Все времена — с поясом."""
    minutes = (now - end).total_seconds() / 60
    if minutes > REDO_LATE_HOURS * 60:
        if deferred:
            return "skip", (f"дозабор так и не ушёл за {REDO_LATE_HOURS} ч после конца "
                            f"сбора — очередь GitHub была занята; больше не заказываю, "
                            f"упавшие адреса соберёт следующий сбор")
        return "quiet", f"с конца сбора больше {REDO_LATE_HOURS} ч — дозабор не нужен"
    if minutes < REDO_AFTER_MINUTES:
        return "wait", (f"с конца сбора {minutes:.0f} мин — дозабор не раньше чем "
                        f"через {REDO_AFTER_MINUTES}")
    if same:
        return "quiet", f"{same} — дозабор не заказываю"
    if choice.total == 0:
        return "quiet", "упавших адресов, которые стоит повторить (сайт лёг, нет ответа), нет"
    count = f"не открылись {choice.total} адр. (сайт лёг или не ответил)"
    if choice.mass:
        return "skip", (f"{count} — больше {REDO_MASS}: это массовый сбой, а не "
                        f"дозабор. Дозабор не заказываю; следующий плановый "
                        f"{hm(next_slot)} соберёт всё")
    if night:
        return "skip", (f"{count}, но сейчас ночь — дозабор не заказываю: сайты до "
                        f"утра отдают вчерашние телесутки. Их соберёт утренний "
                        f"плановый {hm(next_slot)}")
    if collected:
        return "skip", f"{count}, но эти дни уже собрал обход {collected} — дозабор не нужен"
    if going:
        return "wait", (f"{count}; идёт более новый обход {going} — жду его итога "
                        f"(дойдёт — его результат главнее)")
    if next_slot <= now:
        return "skip", (f"{count}, но плановый {hm(next_slot)} заказывается прямо "
                        f"сейчас — он их и соберёт, дозабор не заказываю")
    if (next_slot - now).total_seconds() < REDO_SLOT_GAP_MINUTES * 60:
        return "skip", (f"{count}, но до планового {hm(next_slot)} меньше "
                        f"{REDO_SLOT_GAP_MINUTES} мин — он их и соберёт, дозабор "
                        f"не заказываю")
    if today >= REDO_PER_DAY:
        return "skip", (f"{count}, но за эти сутки уже {today} дозабора (предел "
                        f"{REDO_PER_DAY}) — не заказываю")
    if blocker:
        return "defer", f"{count} — дозабор отложен: {blocker}. Попробую на следующей проверке"
    took = len(choice.rows)
    part = f"первые {took} из {choice.total}" if took < choice.total else f"все {took}"
    return "order", (f"{count} — заказываю ДОЗАБОР только их ({part}); открывшиеся "
                     f"не трогаю, докачанное допишется к уже влитому")


# ── Д6. GitHub: качаем заново и пишем отчёт ──────────────────────────────────

#: Д6: столько раз ПОДРЯД адрес сайта не открылся при дозаборе — остальные
#: его адреса в этот раз не трогаем: сайт всё ещё лежит, а каждый адрес с
#: запасным браузером — до минуты (замечание 13.10)
REDO_SITE_FAILS = 2
#: Д6: причина в разделе «дозабор» у адресов, которые не трогали
SITE_STILL_DOWN = "сайт всё ещё лежит"


def site_down(fails: dict, domain: str) -> bool:
    """Д6: пропустить ли адрес сайта `domain`: подряд не открылось уже
    `REDO_SITE_FAILS` его адресов (`fails` — счёт `count_fail`)."""
    return fails.get(_bare(domain), 0) >= REDO_SITE_FAILS


def count_fail(fails: dict, domain: str, failed: bool) -> None:
    """Д6: учесть итог адреса сайта: не открылся — +1 к счёту подряд,
    открылся — счёт сайта с нуля."""
    key = _bare(domain)
    fails[key] = fails.get(key, 0) + 1 if failed else 0


def job_of(row: dict) -> dict:
    """Д6: строка отчёта → задание обхода (адрес, канал, день, POST-поля…)
    — без полей проверки страницы (`VERDICT_FIELDS`)."""
    return {k: v for k, v in row.items() if k not in VERDICT_FIELDS}


def merge(report: dict, fresh: dict, choice: Pick, from_run, run_id="",
          passed=()) -> dict:
    """Д6: отчёт дозабора — строки сбора, где упавшие (номера из `fresh`)
    заменены свежими, остальные как были; раздел «дозабор»: из какого
    прогона, сколько адресов скачано заново, сколько выправилось, сколько
    было отобрано и сколько всего упало down/net; «пропущено» — адреса,
    которые не трогали (`passed`: [{domain, url, почему}], сайт всё ещё
    лежит). «режим» — с пометкой «дозабор» (окно дней в нём остаётся — по
    нему заливка пишет глубину)."""
    rows = list((report or {}).get("строки") or [])
    for i, row in fresh.items():
        rows[i] = row
    healed = sum(1 for row in fresh.values() if row.get("итог") not in BROKEN)
    out = dict(report or {})
    out["строки"] = rows
    out["режим"] = f"{MODE}: {(report or {}).get('режим') or 'сбор'}"
    out["прогон"] = str(run_id or "")
    out[SECTION] = {"из прогона": str(from_run), "адресов": len(fresh),
                    "выправилось": healed, "отобрано": len(choice.rows),
                    "упавших": choice.total, "пропущено": list(passed),
                    # перекачанные строки С ИМЕНАМИ ФАЙЛОВ (у открывшихся):
                    # по файлу разбор узнаёт докачанное — адреса мало, у
                    # POST-сайтов он общий на все дни (Д7)
                    "строки": [{k: row[k] for k in REDONE_FIELDS if k in row}
                               for _, row in sorted(fresh.items())]}
    return out


#: Д6: поля перекачанной строки, что едут в раздел «дозабор» отчёта
REDONE_FIELDS = ("domain", "channel", "day", "url", "итог", "почему", "файл")


# ── Д7. заливка «только добавить» ────────────────────────────────────────────

def games_mark(report) -> dict:
    """Д7: что разбор добавляет в games.json — {«режим»: «дозабор»,
    «дозабор»: раздел отчёта}, если report.json — дозабора; иначе пусто."""
    section = report.get(SECTION) if isinstance(report, dict) else None
    if not isinstance(section, dict):
        return {}
    return {MODE_KEY: MODE, SECTION: section}


def is_add_only(games) -> bool:
    """Д7: games.json — дозабора («режим»: «дозабор»): вливать «только
    добавить»."""
    return isinstance(games, dict) and games.get(MODE_KEY) == MODE


#: Д7: пометка записи (строки-отметки игры, строки «других видов» и «на
#: разбор») с перекачанной и ОТКРЫВШЕЙСЯ страницы — в games.json дозабора.
#: Заливка дозабора берёт только помеченное (`only_redone`); страницы
#: прежнего сбора нужны разбору лишь как контекст склейки и повторов
ENTRY_KEY = "дозабор"


def redone_rows(report) -> list[dict]:
    """Д7: перекачанные строки (раздел «дозабор» отчёта, `merge`); не
    отчёт дозабора — пусто. По ним одним заливка дозабора судит о сайтах
    (`store.log_run`)."""
    section = report.get(SECTION) if isinstance(report, dict) else None
    rows = section.get("строки") if isinstance(section, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def redone_files(report) -> set[str]:
    """Д7: имена файлов страниц, которые дозабор перекачал и которые
    ОТКРЫЛИСЬ (у не открывшейся файла нет)."""
    return {str(r["файл"]) for r in redone_rows(report) if r.get("файл")}


def tag_programs(programs) -> None:
    """Д7 (разбор): передачи со страницы, которую дозабор перекачал, —
    пометка `ENTRY_KEY` в `extra` передачи."""
    for program in programs:
        program.extra = dict(program.extra or {}, **{ENTRY_KEY: True})


def program_redone(program) -> bool:
    """Д7: передача — с перекачанной страницы (`tag_programs`)?"""
    return bool((getattr(program, "extra", None) or {}).get(ENTRY_KEY))


def keep_redone_games(games: list) -> list:
    """Д7 (разбор): у каждой склеенной игры остаются только записи с
    перекачанных страниц; игра без них выбрасывается. Время, имена и лига
    игры считаются уже по оставшимся записям (это свойства игры)."""
    out = []
    for game in games:
        game.entries = [e for e in game.entries
                        if program_redone(getattr(e.payload, "program", None))]
        if game.entries:
            out.append(game)
    return out


def marker(on: bool) -> dict:
    """Д7: поле пометки для строки games.json — {ENTRY_KEY: True} или ничего."""
    return {ENTRY_KEY: True} if on else {}


def only_redone(payload: dict) -> dict:
    """Д7 (разбор и заливка — одна функция): games.json дозабора → только
    помеченные записи (`ENTRY_KEY`): у игр — строки-отметки, игра без них
    выбрасывается; «другие_виды» и «на_разбор» — тоже только помеченные.
    Так в базу не попадает ничего, кроме докачанного, — даже строки,
    дописанные в файл после разбора (AI-слой). Прочие ключи — как были."""
    out = dict(payload)
    games = []
    for game in payload.get("games") or []:
        if not isinstance(game, dict):
            continue
        entries = [e for e in game.get("entries") or []
                   if isinstance(e, dict) and e.get(ENTRY_KEY)]
        if entries:
            games.append(dict(game, entries=entries))
    out["games"] = games
    out["игр"] = len(games)
    for key in ("другие_виды", "на_разбор"):
        out[key] = [x for x in payload.get(key) or []
                    if isinstance(x, dict) and x.get(ENTRY_KEY)]
    return out

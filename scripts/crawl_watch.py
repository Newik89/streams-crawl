# -*- coding: utf-8 -*-
r"""Сторож заказа обхода — cron сервера раз в 15 минут (владелец 02.10.2026).

    venv/bin/python scripts/crawl_watch.py            решить и сделать
    venv/bin/python scripts/crawl_watch.py --check    только сказать, что бы сделал
    venv/bin/python scripts/crawl_watch.py --cron     строки cron плановых заявок (по watch.SCHEDULE)

Правила С1–С6, виды заказов, память сторожа (настройки `crawl_…`) и все
пороги описаны в ОДНОМ месте — в шапке `app/watch.py`. Здесь — только их
исполнение: функция `tick` вызывает шаги в том же порядке, что правила в
шапке, по одной функции на правило:

    С1  see_github     GitHub не отвечает → пропуск проверки, через час ТРЕВОГА
    С2  resume_early   прошлую проверку оборвали посреди заказа досрочного
    С3  cancel_stuck   зависший прогон → одна заявка отмены; стоящая очередь → строка, ТРЕВОГА
    С4  follow_order   КАЖДЫЙ открытый заказ книги: ждать / забрать / закрыть / сорвался / состарился
    С5  audit_slot     плановая заявка на слот не приходила → слот сорвавшийся
    С6  order_early    сорвавшийся слот → один досрочный обход либо ТРЕВОГА

Что делать после сбоя, решает ОДНА таблица `watch.RECOVERY` («вид сбоя →
шаг»); здесь её шаг исполняет `recover`. Сторож сам заказывает сбор только
в двух местах: повтор (шаг retry) и досрочный (С6) — оба через
`order_crawl`. На один плановый слот — не больше одного заказа сторожа.
Каждое решение — строка «сторож: …» в «Прогонах» админки и в журнале cron
(`/var/log/streams-watch.log`). Проверка идёт под общим с заявкой замком
(`watch.order_lock`, правило З1). Запросов к API GitHub за проверку: один
свой (список прогонов) и по одному у каждой заявки, которую сторож подаёт
(своя заявка — не больше одной за проверку, кроме досрочного).
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import crawl_hook, db, trigger, watch  # noqa: E402


def _now() -> datetime:
    """Часы сторожа отдельной функцией — проверки ставят нужное время."""
    return datetime.now(watch.KYIV)


def order_crawl(kind: str, value: str, mark: str) -> str:
    """Заказать сбор сейчас: `request_crawl.py <kind> <value> --force
    --unlock --locked <mark>` (kind — days, date или site). --force — без
    правила «1 час» (сторож уже решил, что сбор нужен); --unlock — снять
    отметку «сбор идёт» (по списку GitHub прежний прогон мёртв или
    отменяется); --locked — общий замок уже держит сторож; `mark` —
    `--retry-of=<id>` или `--early-for=<слот>`: заявка кладёт заказ в книгу
    с этой пометкой, и сторож находит СВОЙ заказ по ней (`watch.find_order`),
    а не по виду — чужой заказ той же минуты с ним не спутать. Не уложилась
    в срок — не падаем: проверка должна дописать свою память."""
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "request_crawl.py"),
             kind, value, "--force", "--unlock", "--locked", mark],
            capture_output=True, text=True, timeout=watch.ORDER_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return (f"заявка не уложилась в {watch.ORDER_TIMEOUT_SECONDS // 60} минут — "
                f"прервана, смотрите «Прогоны»")
    return (r.stdout or r.stderr).strip()


def pull() -> str:
    """Забрать результат с GitHub — тот же путь, что по стуку «закончил»:
    отдельная служба systemd. Проверка её не ждёт и замок не держит; забран
    ли результат, видно на следующей проверке (`watch.result_state`)."""
    return crawl_hook.start_pull()


def request_args(what: str) -> tuple[str, str]:
    """Вид заказа книги → ключи заявки: `full-6` → days 6, `date-…` → date,
    `site-…` → site."""
    for prefix, kind in (("date-", "date"), ("site-", "site")):
        if what.startswith(prefix):
            return kind, what[len(prefix):]
    return "days", str((watch.window(what) or (1, 0))[1])


class Round:
    """Одна проверка сторожа: то, что шаги С1–С6 передают друг другу.
    `rec` и `run` — заказ книги, который С4 разбирает сейчас, и его прогон."""

    def __init__(self, conn, now: datetime, dry: bool, slug: str) -> None:
        self.conn = conn
        self.now = now                  # UTC (шапка app/watch.py, «время»)
        self.dry = dry                  # --check: только сказать
        self.slug = slug                # репозиторий `Владелец/имя`
        self.runs: list = []            # последние прогоны обхода с GitHub
        self.order: dict | None = None  # последний полный заказ (`crawl_request`)
        self.follow: list = []          # [(запись книги, её прогон)] — открытые заказы
        self.rec: dict = {}             # запись книги, которую разбирает С4
        self.run: dict | None = None    # её прогон на GitHub
        self.early: dict = {}           # `crawl_early`
        self.missed: dict = {}          # `crawl_missed`
        self.cancels: dict = {}         # `crawl_cancel`
        self.queue: dict = {}           # `crawl_queue`
        self.cancelling: list = []      # id прогонов, отмена которых подана сейчас
        self.oldest = None              # создание самого старого прогона в ПОЛНОМ списке
        self.git: dict = {}             # git fetch/show результатов — один раз за проверку
        self.sent = False               # своя заявка повтора в эту проверку уже ушла
        self.owner_stopped: set = set() # id прогонов, остановленных кнопкой владельца
        self.ordered_ids: set = set()   # id прогонов, отвечающих заказам книги

    def log(self, words: str) -> None:
        """Строка только в журнал cron."""
        print(f"{self.now.astimezone(watch.KYIV):%d.%m %H:%M} {words}"
              + (" (--check, ничего не делаю)" if self.dry else ""))

    def say(self, words: str) -> None:
        """Решение сторожа — в журнал cron и строкой в «Прогоны»."""
        self.log(f"сторож: {words}")
        if not self.dry:
            watch.note(self.conn, words)

    def save(self, key: str, value: dict) -> None:
        if not self.dry:
            watch.save_json(self.conn, key, value)

    def keep(self, record: dict) -> None:
        """Запись книги заказов — на место."""
        if not self.dry:
            watch.save_order(self.conn, record)


def tick(conn, now: datetime, check: bool = False) -> None:
    """Одна проверка сторожа: правила С1–С6 по порядку (шапка `app/watch.py`)."""
    t = Round(conn, watch.utc(now), check, trigger._repo_slug())
    if not see_github(t):                                                 # С1
        return
    t.early = watch.load_json(conn, "crawl_early")
    t.missed = watch.load_json(conn, "crawl_missed")
    t.cancels = watch.load_json(conn, "crawl_cancel")
    t.queue = watch.load_json(conn, "crawl_queue")
    t.order = watch.parse_order(db.get_setting(conn, "crawl_request"))
    if len(t.runs) >= watch.RUNS_LIMIT:
        # список полон: прогоны старше самого старого в нём не видны
        t.oldest = min((watch._utc(r.get("created_at") or "") for r in t.runs
                        if r.get("created_at")), default=None)
    if not t.dry:
        # битые записи книги — в карантин, по одной ТРЕВОГЕ на каждую (С4)
        for words in watch.quarantine_orders(conn):
            t.say(f"ТРЕВОГА — {words}")
    # полный заказ без записи в книге (сделан до выкладки) — завести её
    current = watch.full_order_record(conn, t.order, save=not t.dry) if t.order else None
    resume_early(t)                                                       # С2
    resume_retries(t)                                                     # С2
    records = watch.load_orders(conn)
    if current and current not in records and t.dry:
        records.append(current)       # --check: запись не сохранена, но разобрать её надо
    t.follow = [(rec, run_of(t, rec)) for rec in records if watch.is_open(rec)]
    # прогоны заказов книги — только они могут «вытеснить» ждущий (С4)
    t.ordered_ids = {str(run.get("id")) for run in (run_of(t, rec) for rec in records)
                     if run is not None}
    cancel_stuck(t)                                                       # С3
    if not t.follow:
        t.log("открытых заказов нет — следить не за чем")
    for rec, run in t.follow:                                             # С4
        follow_order(t, rec, run)
    deferred_retries(t)                                                   # С4г
    audit_slot(t)                                                         # С5
    order_early(t)                                                        # С6
    if not t.dry:
        watch.prune_orders(conn, t.now)


def run_of(t: Round, rec: dict) -> dict | None:
    """Прогон GitHub, которым ответили на заказ книги (`watch.run_for`); у
    сайта на сервере прогона нет."""
    if watch.order_kind(rec) == "server":
        return None
    return watch.run_for(watch.record_order(rec), watch.crawl_only(t.runs, t.slug))


def see_github(t: Round) -> bool:
    """С1. Берём список прогонов. GitHub не ответил — сторож в эту проверку
    слеп: пропускаем её; молчит `API_SILENT_MINUTES` подряд — одна ТРЕВОГА;
    снова ответил после тревоги — строка «отбой»."""
    t.runs = watch.github_runs(t.slug, workflow=watch.CRAWL_WORKFLOW)
    silent = watch.load_json(t.conn, "crawl_silent")
    since = watch.moment(silent.get("since", ""))
    if t.runs:
        if silent.get("alarmed"):
            t.say(f"GitHub снова отвечает на список прогонов (молчал с "
                  f"{watch.hm(since)}) — сторож опять видит обходы")
        if silent:
            t.save("crawl_silent", {})
        return True
    if since is None:
        silent, since = {"since": watch.when(t.now)}, t.now
    minutes = (t.now - since).total_seconds() / 60
    t.log(f"GitHub не ответил на список прогонов (молчит {minutes:.0f} мин) — "
          f"подожду следующей проверки")
    if minutes >= watch.API_SILENT_MINUTES and not silent.get("alarmed"):
        silent["alarmed"] = True
        t.say(f"ТРЕВОГА — GitHub уже {minutes:.0f} мин (с {watch.hm(since)}) не "
              f"отвечает сторожу на список прогонов: сбои и зависания обхода сейчас "
              f"не видны, отмен и досрочных заказов сторож не делает. Плановые "
              f"заявки уходят как обычно; ответит GitHub — сторож сверится сам")
    t.save("crawl_silent", silent)
    return False


def resume_early(t: Round) -> None:
    """С2. Прошлую проверку оборвали посреди заказа досрочного (перезагрузка
    сервера): в `crawl_early` осталось «ordering». Заявка успела уйти (в
    книге есть запись с пометкой «досрочный за этот слот», `early_order`) —
    следим за ней как за досрочным; не успела — ТРЕВОГА. Второго досрочного
    за тот же слот не будет в обоих случаях (С6: один на слот)."""
    if t.early.get("state") != "ordering":
        return
    slot_hm = watch.clock(t.early.get("for", ""))
    rec = early_order(t)
    if rec:
        t.early.update(ordered_at=rec["order"], order_at=rec.get("at", ""), state="ordered")
        t.say(f"прошлую проверку оборвали посреди заказа досрочного обхода "
              f"(перезагрузка сервера?), но заявка в {watch.clock(rec['order'])} ушла — "
              f"слежу за ней как за досрочным за плановый {slot_hm}")
    else:
        t.early["state"] = "failed"
        recover(t, "early-lost",
                f"досрочный обход за плановый {slot_hm} заказать не удалось: "
                f"проверку оборвали посреди заказа (перезагрузка сервера?)")
    t.save("crawl_early", t.early)


def early_order(t: Round) -> dict:
    """Запись книги о досрочном, который сторож начал заказывать
    (`crawl_early`): пометка early и тот же слот, заказ не раньше начала."""
    rec = watch.find_order(t.conn, early=True, slot=t.early.get("for", ""))
    begun = watch.moment(t.early.get("begun", ""))
    at = watch.record_at(rec) if rec else None
    return rec if at and (begun is None or at >= begun) else {}


def resume_retries(t: Round) -> None:
    """С2. Прошлую проверку оборвали посреди повтора (перезагрузка сервера):
    у записи осталась пометка `retrying` (её пишут ДО заявки). Повтор успел
    уйти (в книге есть «повтор заказа <id>») — его ведёт С4 своей записью;
    не успел — ТРЕВОГА («<вид>-retry-lost»). Второго повтора нет в обоих
    случаях: сорвавшийся заказ сохранён закрытым ещё до заявки."""
    for rec in watch.load_orders(t.conn):
        if not rec.get("retrying"):
            continue
        t.rec, t.run = rec, None
        if not watch.find_order(t.conn, retry_of=rec["id"]):
            recover(t, f"{watch.order_kind(rec)}-retry-lost",
                    f"{order_words(t)}: повтор заказать не удалось — проверку оборвали "
                    f"посреди заказа (перезагрузка сервера?)")
        rec.pop("retrying", None)
        t.keep(rec)


def broken_order(t: Round, rec: dict, error: Exception) -> None:
    """Разбор записи книги упал — одна ТРЕВОГА, запись в карантин
    (`watch.BAD_PREFIX`): остальные заказы проверка разбирает дальше, а
    тревога не повторяется каждые 15 минут."""
    t.say(f"ТРЕВОГА — запись книги заказов «{rec.get('id')}» ({rec.get('what')}) "
          f"разобрать не вышло ({type(error).__name__}: {error}) — сторож её больше "
          f"не ведёт, унёс в карантин; проверьте итог этого заказа сами")
    if not t.dry:
        watch.quarantine(t.conn, watch.order_key(rec))


def cancel_stuck(t: Round) -> None:
    """С3. Зависшие прогоны: одна заявка отмены на прогон (тег
    `btn-cancel-<id>`, исполняет `queue.yml`). Заявка не ушла или прогон не
    остановился за `CANCEL_CONFIRM_MINUTES` — ТРЕВОГА; новых заявок отмены
    этому прогону нет. Что будет с заказом, чей прогон завис, решает С4г.
    Ждущий очереди прогон не отменяется (`watch.QUEUE_WARN_MINUTES`):
    одна строка-предупреждение, потом одна ТРЕВОГА."""
    own = {}
    for rec, run in t.follow:
        if run is not None:
            # что будет с заказом после отмены — по той же таблице RECOVERY (С4г)
            own[str(run.get("id"))] = {
                "early": "вместо него сейчас закажу ближайший плановый досрочно",
                "retry": "сейчас закажу его заново"}.get(
                watch.recovery(watch.failure_of(rec, "failed")),
                "больше не заказываю, подаю тревогу")
    for action, rid, words in watch.queue_decisions(t.runs, t.now, t.queue, t.slug):
        if action == "forget":
            t.queue.pop(rid)
        elif action == "seen":
            t.queue.setdefault(rid, {})["last"] = watch.when(t.now)
        else:
            t.say(words)
            t.queue.setdefault(rid, {})["warned" if action == "warn" else "alarmed"] = True
    t.save("crawl_queue", t.queue)
    decisions = watch.cancel_decisions(t.runs, t.now, t.cancels, t.slug, own, t.queue)
    for action, rid, words in decisions:
        if action in ("forget", "confirmed") and t.cancels[rid].get("by") == "владелец":
            # остановил владелец кнопкой: ручной заказ этого прогона С4
            # закроет без повтора («стоп = стоп»)
            t.owner_stopped.add(rid)
        if action == "forget":
            t.cancels.pop(rid)
        elif action == "confirmed":
            t.say(words)
            t.cancels.pop(rid)
        elif action == "alarm":
            t.say(words)
            t.cancels[rid]["alarmed"] = True
        elif action == "cancel":
            t.cancelling.append(rid)
            t.say(words)
            if t.dry:
                continue
            run = next(r for r in t.runs if str(r.get("id")) == rid)
            number = run.get("run_number") or "?"
            # запоминает и неушедшую заявку: вторую этому прогону не шлём
            ok, answer = watch.send_cancel(t.cancels, run, t.now)
            t.log(f"заявка отмены прогона #{number}: {answer}")
            if ok is None:
                t.log("git не ответил вовремя — заявка могла дойти; остановку "
                      f"сверю, не остановится за {watch.CANCEL_CONFIRM_MINUTES} мин — тревога")
            elif not ok:
                t.say(f"ТРЕВОГА — заявка отмены прогона #{number} не ушла ({answer}). "
                      f"Повторять не буду: GitHub сам оборвёт его через "
                      f"{watch.HARD_LIMIT_MINUTES} мин после старта")
    t.save("crawl_cancel", t.cancels)


def follow_order(t: Round, rec: dict, run: dict | None) -> None:
    """С4. Один открытый заказ книги: вердикт выносит `watch.decide` (сайт
    на сервере — `watch.decide_server`), здесь — действие. Прогон заказа
    завис и его отмена подана в этой же проверке (С3) — заказ сорвался уже
    сейчас, итога отмены не ждём (владелец: «отменить зависшее и СРАЗУ
    заказать»). У каждого заказа своя запись — новый заказ слежку за
    прежним не вытесняет."""
    t.rec, t.run = rec, run
    try:
        verdict, words, result = judge(t, rec, run)
    except Exception as error:                                            # noqa: BLE001
        # одна странная запись не роняет проверку: в карантин, одна ТРЕВОГА
        broken_order(t, rec, error)
        return
    t.log(f"{rec['what']} от {rec['order']} — {verdict}: {words}")
    if t.dry:
        return
    if verdict == "pull":                                                # С4б
        pull_result(t, words)
    elif verdict == "done":                                              # С4в
        rec["done"] = True
        watch.note(t.conn, words)
        if rec.get("early"):
            early_reached(t)
    elif verdict == "stopped":                                           # С4в
        rec["stopped"] = True
        watch.note(t.conn, f"{order_words(t)}: {words}")
    elif verdict == "replaced":                                          # С4в
        rec["replaced"] = True
        watch.note(t.conn, f"{order_words(t)}: {words}")
        if rec.get("early"):
            t.early["state"] = "replaced"
            t.save("crawl_early", t.early)
    elif verdict == "failed":                                            # С4г
        order_failed(t, words)
    elif verdict == "expired":                                           # С4д
        order_expired(t, result)
    t.keep(rec)


def judge(t: Round, rec: dict, run: dict | None) -> tuple[str, str, str]:
    """Вердикт по заказу книги (С4) — только чтение, ничего не меняет:
    (вердикт, слова, судьба результата `watch.result_state`)."""
    order = watch.record_order(rec)
    result = "unknown"
    if watch.order_kind(rec) == "server":
        verdict, words = watch.decide_server(
            rec, t.now, db.get_setting(t.conn, "site_crawl_result"))
        return verdict, words, result
    replaced = None
    if run is not None and (run.get("status") or "") not in watch.RUNNING:
        # влит ли результат ИМЕННО этого прогона: окно — от настоящего старта
        # (прогон мог ждать очереди за другим) до конца
        created = watch._utc(run.get("created_at") or "") or t.now
        start = watch.effective_start(run, watch.crawl_only(t.runs, t.slug)) or created
        end = watch._utc(run.get("updated_at") or "") or t.now
        result = watch.result_state(ROOT, start, end, rec["what"],
                                    watch.imported_stamps(t.conn, rec["what"]), t.git)
        replaced = watch.superseded_by(rec["what"], run, t.runs, t.ordered_ids)
        if (str(run.get("id")) in t.owner_stopped
                and watch.order_kind(rec) in watch.RETRIED and not rec.get("reordered")):
            # «стоп = стоп» (владелец 06.10): ручной сбор, остановленный
            # владельцем, — не срыв; плановый и досрочный идут как обычно
            return "stopped", (f"прогон #{run.get('run_number')} остановил владелец "
                               f"кнопкой — не повторяю"), result
    hidden = bool(t.oldest and order["at"] < t.oldest)
    verdict, words = watch.decide(order, run, t.now, rec, result, hidden, replaced)
    if verdict == "wait" and run is not None and str(run.get("id")) in t.cancelling:
        verdict, words = "failed", f"прогон #{run.get('run_number')} завис, отменяю его"
    return verdict, words, result


def early_reached(t: Round) -> None:
    """Досрочный дошёл до конца: запоминаем это вместе с его началом и
    номером — к слоту прогон может выпасть из списка последних (З3)."""
    begun = (watch._utc(t.run.get("run_started_at") or t.run.get("created_at") or "")
             if t.run else None)
    t.early.update(state="done", run=(t.run or {}).get("run_number"),
                   started=watch.when(begun) if begun else "")
    t.save("crawl_early", t.early)


def pull_result(t: Round, words: str) -> None:
    """С4б. Обход готов, стук не дошёл: запускаем забор (отдельной службой) на
    каждой проверке, пока результат не окажется на сервере — тогда С4в
    закроет заказ. `PULL_TRIES_BEFORE_ALARM` заборов подряд не помогли —
    одна ТРЕВОГА, пробовать продолжаем."""
    tries = int(t.rec.get("pulls") or 0)
    if tries == 0:
        watch.note(t.conn, words)
    elif tries == watch.PULL_TRIES_BEFORE_ALARM:
        t.say(f"ТРЕВОГА — обход #{t.run.get('run_number')} готов и лежит на GitHub, но "
              f"{tries} забора подряд его на сервер не принесли. Продолжаю пробовать "
              f"на каждой проверке; не обновится витрина — проверьте сервер "
              f"(/var/log/streams-update.log)")
    crawl_hook.clear(t.conn)
    t.log(f"забор: {pull()}")
    t.rec["pulls"] = tries + 1


def recover(t: Round, failure: str, what: str, extra: str = "",
            slot: str = "", days: int = 0, at: str = "") -> None:
    """После сбоя: шаг берётся из ОДНОЙ таблицы `watch.RECOVERY` по виду
    сбоя `failure`, здесь он только исполняется. `what` — что случилось,
    словами; `extra` — добавка к тревоге; `slot`, `days`, `at` — сорвавшийся
    слот для шага early (по умолчанию — слот разбираемого заказа, сорвался
    сейчас).
      early — слот в `crawl_missed`, досрочный решит С6 в этой же проверке
      retry — один повтор той же заявки; не ушёл — снова сюда (<вид>-retry-refused)
      alarm — ТРЕВОГА с честным «что дальше»; новых заказов нет"""
    step = watch.recovery(failure)
    if step == "early":
        t.say(f"{what} — беру слот на себя: тем же окном не повторяю, решаю "
              f"про досрочный")
        t.missed = watch.missed_record(
            t.missed, slot or t.rec.get("slot", ""),
            days or (watch.window(t.rec.get("what", "")) or (1, 0))[1],
            at or watch.when(t.now), what)
        t.save("crawl_missed", t.missed)
    elif step == "retry":
        retry(t, what)
    else:
        # какой плановый пойдёт следующим, считаем от СЕЙЧАС: заменяемый
        # слот мог уже пройти, пока досрочный шёл (З3, пометка skipped)
        nxt, ndays = watch.next_slot(t.now)
        t.say(f"ТРЕВОГА — {what}. Больше не заказываю.{extra} Следующий плановый — "
              f"{watch.hm(nxt)} ({ndays} сут.), он пойдёт как обычно; проверьте GitHub")


def retry(t: Round, what: str) -> None:
    """Шаг retry: ОДИН повтор той же заявки за сорвавшийся заказ `t.rec`.
    Повтор уже заказан (в книге есть «повтор заказа <id>») — второго нет. В
    очереди GitHub ждёт полный обход — повтор откладывается (`queue_refusal`:
    он вытеснил бы ждущий), его закажет `deferred_retries`, когда очередь
    освободится. Сорвавшийся заказ сохраняется закрытым и с пометкой
    `retrying` ДО заявки: оборвут проверку посреди неё — следующая второго
    повтора не закажет (С2, `resume_retries`). Свой повтор — по пометке
    «повтор заказа <id>», а не по виду: чужой заказ той же минуты (друг нажал
    «2 дня») с ним не спутать. Дни заказа уже собрал успешный полный обход,
    созданный после заказа (`collected_by`), — повтор не нужен. За проверку —
    не больше ОДНОГО повтора: второй тег вытеснил бы первый в очереди."""
    rec = t.rec
    if watch.find_order(t.conn, retry_of=rec["id"]):
        return
    run = t.run or {}
    cover = watch.collected_by(rec["what"], watch.record_at(rec) or t.now, t.runs,
                               skip_id=run.get("id"))
    if cover is not None:
        rec.pop("retry_deferred", None)
        rec["collected_by"] = cover.get("run_number")
        t.keep(rec)
        t.say(f"{what} — повтор не нужен: эти дни уже собрал обход "
              f"#{cover.get('run_number')} ({watch.run_what(cover)})")
        return
    blocker = watch.queue_refusal(t.runs, t.slug) or (
        "в эту проверку уже ушла другая заявка повтора — второй тег вытеснил бы "
        "её в очереди GitHub; закажу на следующей проверке" if t.sent else "")
    if blocker:
        if not rec.get("retry_deferred"):
            t.say(f"{what} — повтор отложен: {blocker}")
            rec["retry_deferred"] = watch.when(t.now)
        t.keep(rec)
        return
    t.say(f"{what} — повторяю один раз")
    rec.pop("retry_deferred", None)
    rec["retrying"] = watch.when(t.now)
    t.keep(rec)
    t.sent = True
    t.log(order_crawl(*request_args(rec["what"]), f"--retry-of={rec['id']}"))
    rec.pop("retrying", None)
    t.keep(rec)
    if not watch.find_order(t.conn, retry_of=rec["id"]):
        recover(t, f"{watch.order_kind(rec)}-retry-refused",
                f"повторить не вышло ({rec['what']}: GitHub не принял заявку)")


def deferred_retries(t: Round) -> None:
    """С4г. Отложенные повторы (в очереди GitHub ждал полный обход):
    очередь освободилась — заказываем повтор; ждёт дольше `ORDER_TTL_HOURS`
    — ТРЕВОГА, повтора не будет."""
    if t.dry:
        return
    for rec in watch.load_orders(t.conn):
        if not rec.get("retry_deferred") or watch.find_order(t.conn, retry_of=rec["id"]):
            continue
        t.rec, t.run = rec, None
        since = watch.moment(rec["retry_deferred"]) or t.now
        if (t.now - since).total_seconds() > watch.ORDER_TTL_HOURS * 3600:
            rec.pop("retry_deferred", None)
            t.keep(rec)
            recover(t, f"{watch.order_kind(rec)}-retry-refused",
                    f"{order_words(t)}: повтор так и не ушёл — очередь GitHub "
                    f"{watch.ORDER_TTL_HOURS} ч занята ждущим полным обходом")
        elif not watch.queue_refusal(t.runs, t.slug) and not t.sent:
            retry(t, f"{order_words(t)} сорвался раньше")


def order_words(t: Round) -> str:
    """Чей заказ — словами для строк сторожа (виды — шапка app/watch.py)."""
    rec = t.rec
    what, at = rec.get("what", ""), rec.get("order", "")
    tail = what.split("-", 1)[1] if "-" in what else what
    return {
        "early": f"досрочный обход за плановый {watch.clock(t.early.get('for', ''))}",
        "planned": f"плановый обход {watch.clock(rec.get('slot', ''))} "
                   f"({request_args(what)[1]} сут.)",
        "manual": f"ручной заказ от {at} ({request_args(what)[1]} сут.)",
        "manual-retry": "повтор ручного заказа",
        "date": f"скан даты {tail} от {at}",
        "date-retry": f"повтор скана даты {tail}",
        "site": f"обход сайта {tail} от {at}",
        "site-retry": f"повтор обхода сайта {tail}",
        "server": f"обход сайта {tail} на сервере от {at}",
    }.get(watch.order_who(rec), f"заказ {what} от {at}")


def close_early(t: Round) -> str:
    """Досрочный сорвался: память «failed» (З3 тогда слот не пропустит) и
    добавка к тревоге, если ради него уже пропустили плановый."""
    t.early["state"] = "failed"
    t.save("crawl_early", t.early)
    if not t.early.get("skipped"):
        return ""
    return (f" Плановый {watch.clock(t.early.get('replaces', ''))} был пропущен "
            f"ради него и остался без обхода.")


def order_failed(t: Round, why: str) -> None:
    """С4г. Заказ сорвался — закрываем его; что дальше, решает таблица
    `watch.RECOVERY` по тому, чей он (ВИДЫ ЗАКАЗОВ в шапке)."""
    failure = watch.failure_of(t.rec, "failed")
    extra = close_early(t) if t.rec.get("early") else ""
    what = order_words(t)
    t.rec["failed"] = True
    recover(t, failure, f"{what} сорвался ({why})", extra)


def order_expired(t: Round, result: str) -> None:
    """С4д. Заказ состарился (`ORDER_TTL_HOURS`), а не закрыт. Результат
    всё-таки на сервере — закрываем молча; иначе следить перестаём, а что
    дальше — по таблице `watch.RECOVERY` (сейчас у всех — ТРЕВОГА).
    Досрочный при этом считается сорвавшимся: заменять плановый он не может."""
    run = t.run
    if run is not None and run.get("conclusion") == "success" and result in ("picked", "none"):
        t.rec["done"] = True
        if t.rec.get("early"):
            early_reached(t)
        return
    failure = watch.failure_of(t.rec, "expired")
    extra = close_early(t) if t.rec.get("early") else ""
    what = order_words(t)
    t.rec["failed"] = True
    seen = ("прогон на GitHub не найден" if run is None else
            f"прогон #{run.get('run_number')}: {run.get('status')}/"
            f"{run.get('conclusion') or '—'}, результат на сервере не подтверждён")
    recover(t, failure, f"{what} за {watch.ORDER_TTL_HOURS} ч так и не дошёл до "
                        f"«забран» ({seen}); больше за ним не слежу", extra)


def audit_slot(t: Round) -> None:
    """С5. Приходила ли плановая заявка на последний прошедший слот
    (`watch.slot_audit`). Не приходила или оборвалась — сбой
    «planned-not-requested», что дальше — по таблице `watch.RECOVERY`."""
    action, record, why = watch.slot_audit(
        watch.load_json(t.conn, "crawl_slot"), t.missed, t.early, t.now)
    if action in ("init", "seen"):
        t.save("crawl_slot", record)
    elif action == "missed":
        t.save("crawl_slot", {"slot": record["slot"], "days": record["days"],
                              "at": watch.when(t.now), "state": "audited"})
        recover(t, "planned-not-requested", why,
                slot=record["slot"], days=record["days"], at=record["at"])


def order_early(t: Round) -> None:
    """С6. Сорвавшийся слот: нужен ли досрочный, решает `watch.plan_early`.
    Нужен — намерение пишем в память ДО заявки («ordering»): оборвут
    проверку посреди заказа — следующая не закажет второй (С2)."""
    last = watch.parse_order(db.get_setting(t.conn, "crawl_request"))
    # память сторожа о последнем полном заказе: дошёл и забран (С4в, С4б)
    last_done = bool(last and watch.full_order_record(t.conn, last, save=False).get("done"))
    action, plan, words = watch.plan_early(
        t.missed, t.runs, t.now, t.early, last, last_done,
        skip_ids=t.cancelling + list(t.cancels), slug=t.slug)
    if action == "none":
        if t.missed.get("state") == "missed":
            # досрочный за этот слот уже был — больше по нему не решаем
            t.missed["state"] = "handled"
            t.save("crawl_missed", t.missed)
        return
    if action == "covered":
        # решение не окончательное: слот остаётся «missed» и ждёт итога
        # покрывающего прогона; строка — один раз на прогон
        if t.missed.get("covered_by") != plan["run"]:
            t.say(words)
            t.missed["covered_by"] = plan["run"]
            t.save("crawl_missed", t.missed)
        return
    t.say(words)
    if t.dry:
        return
    if action != "order":
        t.missed["state"] = action
        t.save("crawl_missed", t.missed)
        return
    t.early = dict(plan, begun=watch.when(t.now), ordered_at="", state="ordering")
    t.save("crawl_early", t.early)
    t.missed["state"] = "handled"
    t.save("crawl_missed", t.missed)
    t.log(order_crawl("days", str(plan["days"]), f"--early-for={plan['for']}"))
    rec = early_order(t)
    if not rec:
        # записи «досрочный за этот слот» в книге нет — заявка не ушла
        t.early["state"] = "failed"
        t.save("crawl_early", t.early)
        t.missed["state"] = "failed"
        t.save("crawl_missed", t.missed)
        recover(t, "early-refused",
                "досрочный обход заказать не вышло (GitHub не принял заявку)")
        return
    t.early.update(ordered_at=rec["order"], order_at=rec.get("at", ""), state="ordered")
    t.save("crawl_early", t.early)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if "--cron" in sys.argv[1:]:
        print("\n".join(watch.cron_lines(str(ROOT), sys.executable)))
        return 0
    if "--check" in sys.argv[1:]:
        # «только сказать» ничего не меняет — общий замок не нужен
        return _run(check=True)
    # З1: общий замок с заявкой. Замок занят дольше срока (идёт долгая заявка
    # или кнопка админки) — эту проверку пропускаем: два сторожа разом хуже,
    # чем проверка на 15 минут позже
    with watch.order_lock(watch.LOCK_WAIT_WATCH) as held:
        if not held:
            print(f"{_now():%d.%m %H:%M} общий замок занят дольше "
                  f"{watch.LOCK_WAIT_WATCH // 60} мин — эту проверку пропускаю, "
                  f"следующая по расписанию")
            return 0
        return _run(check=False)


def _run(check: bool) -> int:
    conn = db.connect(db.BUSY_TIMEOUT_SCRIPT)
    try:
        tick(conn, _now(), check)     # часы — после ожидания замка
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

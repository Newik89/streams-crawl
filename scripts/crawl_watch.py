# -*- coding: utf-8 -*-
r"""Сторож заказа обхода — cron сервера раз в 15 минут (владелец 02.10.2026).

    venv/bin/python scripts/crawl_watch.py            решить и сделать
    venv/bin/python scripts/crawl_watch.py --check    только сказать, что бы сделал
    venv/bin/python scripts/crawl_watch.py --cron     строки cron плановых заявок (по watch.SCHEDULE)

Правила С1–С6, память сторожа (настройки `crawl_…`) и все пороги описаны в
ОДНОМ месте — в шапке `app/watch.py`. Здесь — только их исполнение: функция
`tick` вызывает шаги в том же порядке, что правила в шапке, по одной функции
на правило:

    С1  see_github     GitHub не отвечает → пропуск проверки, через час ТРЕВОГА
    С2  resume_early   прошлую проверку оборвали посреди заказа досрочного
    С3  cancel_stuck   зависший прогон → одна заявка отмены
    С4  follow_order   текущий заказ: ждать / забрать / закрыть / сорвался / состарился
    С5  audit_slot     плановая заявка на слот не приходила → слот сорвавшийся
    С6  order_early    сорвавшийся слот → один досрочный обход либо ТРЕВОГА

Сторож сам заказывает обход только в двух местах: повтор ручного заказа
(С4г) и досрочный (С6) — оба через `order_crawl`. На один плановый слот —
не больше одного заказа сторожа.
Каждое решение — строка «сторож: …» в «Прогонах» админки и в журнале cron
(`/var/log/streams-watch.log`). Проверка идёт под общим с заявкой замком
(`watch.order_lock`, правило З1). Одна проверка — один запрос к API GitHub.
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


def order_crawl(days: int) -> str:
    """Заказать полный обход сейчас: `request_crawl.py days N --force --unlock
    --locked`. --force — без правила «1 час» (сторож уже решил, что обход
    нужен); --unlock — снять отметку «сбор идёт» (по списку GitHub прежний
    прогон мёртв или отменяется); --locked — общий замок уже держит сторож.
    Заявка сама пишет заказ в `crawl_request` — по нему вызывающий видит,
    ушла ли она. Не уложилась в срок — не падаем: проверка должна дописать
    свою память."""
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "request_crawl.py"),
             "days", str(days), "--force", "--unlock", "--locked"],
            capture_output=True, text=True, timeout=watch.ORDER_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return (f"заявка не уложилась в {watch.ORDER_TIMEOUT_SECONDS // 60} минут — "
                f"прервана, смотрите «Прогоны»")
    return (r.stdout or r.stderr).strip()


def pull() -> tuple[int, str]:
    """Забрать результат с GitHub — тот же путь, что по стуку «закончил»."""
    r = subprocess.run(["/bin/sh", str(ROOT / "scripts" / "hook_pull.sh")],
                       capture_output=True, text=True,
                       timeout=watch.PULL_TIMEOUT_SECONDS)
    return r.returncode, (r.stdout or r.stderr).strip()


class Round:
    """Одна проверка сторожа: то, что шаги С1–С6 передают друг другу."""

    def __init__(self, conn, now: datetime, dry: bool, slug: str) -> None:
        self.conn = conn
        self.now = now
        self.dry = dry                  # --check: только сказать
        self.slug = slug                # репозиторий `Владелец/имя`
        self.runs: list = []            # последние прогоны обхода с GitHub
        self.order: dict | None = None  # текущий заказ (`crawl_request`)
        self.state: dict = {}           # память о нём (`crawl_watch`)
        self.run: dict | None = None    # прогон GitHub по этому заказу
        self.early: dict = {}           # `crawl_early`
        self.missed: dict = {}          # `crawl_missed`
        self.cancels: dict = {}         # `crawl_cancel`
        self.cancelling: list = []      # id прогонов, отмена которых подана сейчас

    def log(self, words: str) -> None:
        """Строка только в журнал cron."""
        print(f"{self.now:%d.%m %H:%M} {words}"
              + (" (--check, ничего не делаю)" if self.dry else ""))

    def say(self, words: str) -> None:
        """Решение сторожа — в журнал cron и строкой в «Прогоны»."""
        self.log(f"сторож: {words}")
        if not self.dry:
            watch.note(self.conn, words)

    def save(self, key: str, value: dict) -> None:
        if not self.dry:
            watch.save_json(self.conn, key, value)


def tick(conn, now: datetime, check: bool = False) -> None:
    """Одна проверка сторожа: правила С1–С6 по порядку (шапка `app/watch.py`)."""
    t = Round(conn, now, check, trigger._repo_slug())
    if not see_github(t):                                                 # С1
        return
    t.early = watch.load_json(conn, "crawl_early")
    t.missed = watch.load_json(conn, "crawl_missed")
    t.cancels = watch.load_json(conn, "crawl_cancel")
    t.order = watch.parse_order(db.get_setting(conn, "crawl_request"))
    t.state = watch.load_state(conn, t.order) if t.order else {}
    resume_early(t)                                                       # С2
    if t.order:
        # «свой» прогон заказа — только полный обход, не проба минутой раньше
        t.run = watch.run_for(t.order, watch.full_runs(t.runs, t.slug))
        if "slot" not in t.state:
            # плановый ли заказ — по таблице SCHEDULE; запоминаем один раз
            slot = watch.slot_for(t.order["at"], t.order["days"])
            t.state["slot"] = watch.stamp(slot) if slot else ""
    cancel_stuck(t)                                                       # С3
    follow_order(t)                                                       # С4
    audit_slot(t)                                                         # С5
    order_early(t)                                                        # С6


def see_github(t: Round) -> bool:
    """С1. Берём список прогонов. GitHub не ответил — сторож в эту проверку
    слеп: пропускаем её; молчит `API_SILENT_MINUTES` подряд — одна ТРЕВОГА;
    снова ответил после тревоги — строка «отбой»."""
    t.runs = watch.github_runs(t.slug, workflow=watch.CRAWL_WORKFLOW)
    silent = watch.load_json(t.conn, "crawl_silent")
    since = watch.kyiv_at(silent.get("since", ""))
    if t.runs:
        if silent.get("alarmed"):
            t.say(f"GitHub снова отвечает на список прогонов (молчал с "
                  f"{watch.hm(since)}) — сторож опять видит обходы")
        if silent:
            t.save("crawl_silent", {})
        return True
    if since is None:
        silent, since = {"since": watch.stamp(t.now)}, t.now
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
    `crawl_request` заказ той же глубины не старше начала заказа) — следим
    за ней как за досрочным; не успела — ТРЕВОГА. Второго досрочного за тот
    же слот не будет в обоих случаях (С6: один на слот)."""
    if t.early.get("state") != "ordering":
        return
    begun = watch.kyiv_at(t.early.get("begun", ""))
    slot_hm = watch.clock(t.early.get("for", ""))
    went = bool(t.order and begun and t.order["at"] >= begun
                and t.order["days"] == t.early.get("days"))
    if went:
        t.early.update(ordered_at=t.order["stamp"], state="ordered")
        t.state = {"order": t.order["stamp"], "slot": t.early.get("for", ""),
                   "early": True}
        t.say(f"прошлую проверку оборвали посреди заказа досрочного обхода "
              f"(перезагрузка сервера?), но заявка в {watch.hm(t.order['at'])} ушла — "
              f"слежу за ней как за досрочным за плановый {slot_hm}")
    else:
        t.early["state"] = "failed"
        nxt, ndays = watch.next_slot(t.now)
        t.say(f"ТРЕВОГА — досрочный обход за плановый {slot_hm} заказать не удалось: "
              f"проверку оборвали посреди заказа (перезагрузка сервера?). Больше не "
              f"заказываю; следующий плановый — {watch.hm(nxt)} ({ndays} сут.), он "
              f"пойдёт как обычно")
    t.save("crawl_early", t.early)
    if went and not t.dry:
        watch.save_state(t.conn, t.state)


def cancel_stuck(t: Round) -> None:
    """С3. Зависшие прогоны: одна заявка отмены на прогон (тег
    `btn-cancel-<id>`, исполняет `queue.yml`). Заявка не ушла или прогон не
    остановился за `CANCEL_CONFIRM_MINUTES` — ТРЕВОГА; новых заявок отмены
    этому прогону нет. Что будет с заказом, чей прогон завис, решает С4г."""
    kind = watch.order_kind(t.state)
    own_words = ("вместо него сейчас закажу ближайший плановый досрочно" if kind == "planned"
                 else "это был досрочный — больше не заказываю, подаю тревогу" if kind == "early"
                 else "повтор уже был — подаю тревогу" if t.state.get("reordered")
                 else "сейчас закажу его заново")
    decisions = watch.cancel_decisions(
        t.runs, t.now, t.cancels, t.slug,
        own_run_id=(t.run or {}).get("id"), own_words=own_words)
    for action, rid, words in decisions:
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
            number = next((r.get("run_number") for r in t.runs
                           if str(r.get("id")) == rid), "?")
            ok, answer = trigger.push_request_tag("cancel", rid)
            t.log(f"заявка отмены прогона #{number}: {answer}")
            # запоминаем и неушедшую заявку: вторую этому прогону не шлём
            t.cancels[rid] = {"at": watch.stamp(t.now), "number": number,
                              "alarmed": not ok}
            if not ok:
                t.say(f"ТРЕВОГА — заявка отмены прогона #{number} не ушла ({answer}). "
                      f"Повторять не буду: GitHub сам оборвёт его через "
                      f"{watch.HARD_LIMIT_MINUTES} мин после старта")
    t.save("crawl_cancel", t.cancels)


def follow_order(t: Round) -> None:
    """С4. Текущий заказ: вердикт выносит `watch.decide`, здесь — действие.
    Прогон заказа завис и его отмена подана в этой же проверке (С3) — заказ
    сорвался уже сейчас, итога отмены не ждём (владелец: «отменить зависшее
    и СРАЗУ заказать»)."""
    if t.order is None:
        t.log("заказов не было — следить не за чем")
        return
    result = "unknown"
    if t.run is not None and (t.run.get("status") or "") not in watch.RUNNING:
        started = (watch._utc(t.run.get("run_started_at") or t.run.get("created_at") or "")
                   or t.now)
        result = watch.result_state(ROOT, started)
    verdict, words = watch.decide(t.order, t.run, t.now, t.state, result)
    if verdict == "wait" and t.run is not None and str(t.run.get("id")) in t.cancelling:
        verdict, words = "failed", f"прогон #{t.run.get('run_number')} завис, отменяю его"
    t.log(f"{verdict}: {words}")
    if t.dry:
        return
    if verdict == "pull":                                                # С4б
        pull_result(t, words)
    elif verdict == "done":                                              # С4в
        t.state["done"] = True
        watch.note(t.conn, words)
        if watch.order_kind(t.state) == "early":
            early_reached(t)
    elif verdict == "failed":                                            # С4г
        order_failed(t, words)
    elif verdict == "expired":                                           # С4д
        order_expired(t, result)
    watch.save_state(t.conn, t.state)


def early_reached(t: Round) -> None:
    """Досрочный дошёл до конца: запоминаем это вместе с его началом и
    номером — к слоту прогон может выпасть из списка последних (З3)."""
    begun = watch._utc(t.run.get("run_started_at") or t.run.get("created_at") or "")
    t.early.update(state="done", run=t.run.get("run_number"),
                   started=watch.stamp(begun) if begun else "")
    t.save("crawl_early", t.early)


def pull_result(t: Round, words: str) -> None:
    """С4б. Обход готов, стук не дошёл: забираем сами на каждой проверке,
    пока не выйдет. После `PULL_TRIES_BEFORE_ALARM` неудач — одна ТРЕВОГА."""
    tries = int(t.state.get("pulls") or 0)
    if tries < watch.PULL_TRIES_BEFORE_ALARM:
        watch.note(t.conn, words)
    crawl_hook.clear(t.conn)
    code, out = pull()
    t.log(f"забор: код {code} {out}")
    t.state["pulls"] = tries + 1
    t.state["done"] = code == 0
    if code == 0:
        if watch.order_kind(t.state) == "early":
            early_reached(t)
    elif t.state["pulls"] == watch.PULL_TRIES_BEFORE_ALARM:
        t.say(f"ТРЕВОГА — обход #{t.run.get('run_number')} готов и лежит на GitHub, но "
              f"забрать его не вышло уже {t.state['pulls']} раза подряд (код {code}). "
              f"Продолжаю пробовать на каждой проверке; не обновится витрина — "
              f"проверьте сервер")


def order_failed(t: Round, why: str) -> None:
    """С4г. Заказ сорвался — закрываем его и смотрим, чей он:
    досрочный → ТРЕВОГА; плановый → слот сорвался, досрочный закажет С6 (в
    этой же проверке); ручной → один повтор той же глубины, сорвался и
    повтор → ТРЕВОГА."""
    kind = watch.order_kind(t.state)
    t.state["failed"] = True
    if kind == "early":
        t.early["state"] = "failed"
        t.save("crawl_early", t.early)
        # какой плановый пойдёт следующим, считаем от СЕЙЧАС: заменяемый
        # слот мог уже пройти, пока досрочный шёл (З3, пометка skipped)
        nxt, ndays = watch.next_slot(t.now)
        lost = (f" Плановый {watch.clock(t.early.get('replaces', ''))} был пропущен "
                f"ради него и остался без обхода." if t.early.get("skipped") else "")
        t.say(f"ТРЕВОГА — досрочный обход тоже не прошёл ({why}). Больше не "
              f"заказываю.{lost} Следующий плановый — {watch.hm(nxt)} ({ndays} сут.), "
              f"он пойдёт как обычно; проверьте GitHub")
    elif kind == "planned":
        t.say(f"плановый обход {watch.clock(t.state['slot'])} ({t.order['days']} сут.) "
              f"сорвался ({why}) — тем же окном не повторяю")
        t.missed = watch.missed_record(t.missed, t.state["slot"], t.order["days"],
                                       watch.stamp(t.now), why)
        t.save("crawl_missed", t.missed)
    elif t.state.get("reordered"):
        t.say(f"ТРЕВОГА — повтор ручного заказа тоже сорвался ({why}). Больше не "
              f"заказываю, проверьте GitHub")
    else:
        t.say(f"ручной заказ от {t.order['stamp']} ({t.order['days']} сут.) сорвался "
              f"({why}) — повторяю один раз")
        t.log(order_crawl(t.order["days"]))
        new = watch.parse_order(db.get_setting(t.conn, "crawl_request"))
        if new == t.order:
            # запись заказа не изменилась — заявка повтора не ушла
            t.say("ТРЕВОГА — повторить ручной заказ не вышло (GitHub не принял "
                  "заявку). Больше не заказываю, проверьте GitHub")
        else:
            # заявка записала новый заказ — память переезжает на него
            t.state = {"order": new["stamp"], "slot": "", "reordered": True}


def order_expired(t: Round, result: str) -> None:
    """С4д. Заказ состарился (`ORDER_TTL_HOURS`), а не закрыт. Результат
    всё-таки на сервере — закрываем молча; иначе ТРЕВОГА, следить перестаём.
    Досрочный при этом считается сорвавшимся: заменять плановый он не может."""
    run = t.run
    if run is not None and run.get("conclusion") == "success" and result in ("picked", "none"):
        t.state["done"] = True
        if watch.order_kind(t.state) == "early":
            early_reached(t)
        return
    t.state["failed"] = True
    if watch.order_kind(t.state) == "early":
        t.early["state"] = "failed"
        t.save("crawl_early", t.early)
    seen = ("прогон на GitHub не найден" if run is None else
            f"прогон #{run.get('run_number')}: {run.get('status')}/"
            f"{run.get('conclusion') or '—'}, результат на сервере не подтверждён")
    t.say(f"ТРЕВОГА — заказ обхода от {t.order['stamp']} ({t.order['days']} сут.) за "
          f"{watch.ORDER_TTL_HOURS} ч так и не дошёл до «забран» ({seen}). Больше за "
          f"ним не слежу — проверьте витрину и GitHub")


def audit_slot(t: Round) -> None:
    """С5. Приходила ли плановая заявка на последний прошедший слот
    (`watch.slot_audit`). Не приходила или оборвалась — слот сорвавшийся:
    дальше с ним поступает С6."""
    action, record, why = watch.slot_audit(
        watch.load_json(t.conn, "crawl_slot"), t.missed, t.early, t.now)
    if action in ("init", "seen"):
        t.save("crawl_slot", record)
    elif action == "missed":
        t.say(f"{why} — беру слот на себя")
        t.missed = record
        t.save("crawl_missed", t.missed)
        t.save("crawl_slot", {"slot": record["slot"], "days": record["days"],
                              "at": watch.stamp(t.now), "state": "audited"})


def order_early(t: Round) -> None:
    """С6. Сорвавшийся слот: нужен ли досрочный, решает `watch.plan_early`.
    Нужен — намерение пишем в память ДО заявки («ordering»): оборвут
    проверку посреди заказа — следующая не закажет второй (С2)."""
    last = watch.parse_order(db.get_setting(t.conn, "crawl_request"))
    # память сторожа о последнем заказе: дошёл и забран (С4в, С4б)
    last_done = bool(last and t.state.get("order") == last["stamp"]
                     and t.state.get("done"))
    action, plan, words = watch.plan_early(
        t.missed, t.runs, t.now, t.early, last, last_done,
        skip_ids=t.cancelling + list(t.cancels), slug=t.slug)
    if action == "none":
        if t.missed.get("state") == "missed":
            # досрочный за этот слот уже был — больше по нему не решаем
            t.missed["state"] = "handled"
            t.save("crawl_missed", t.missed)
        return
    t.say(words)
    if t.dry:
        return
    if action != "order":
        t.missed["state"] = action
        t.save("crawl_missed", t.missed)
        return
    t.early = dict(plan, begun=watch.stamp(t.now), ordered_at="", state="ordering")
    t.save("crawl_early", t.early)
    t.missed["state"] = "handled"
    t.save("crawl_missed", t.missed)
    t.log(order_crawl(plan["days"]))
    new = watch.parse_order(db.get_setting(t.conn, "crawl_request"))
    if new == last:
        # запись заказа не изменилась — заявка досрочного не ушла
        t.early["state"] = "failed"
        t.save("crawl_early", t.early)
        t.missed["state"] = "failed"
        t.save("crawl_missed", t.missed)
        nxt, ndays = watch.next_slot(t.now)
        t.say(f"ТРЕВОГА — досрочный обход заказать не вышло (GitHub не принял "
              f"заявку). Больше не заказываю; следующий плановый — {watch.hm(nxt)} "
              f"({ndays} сут.), он пойдёт как обычно")
        return
    t.early.update(ordered_at=new["stamp"], state="ordered")
    t.save("crawl_early", t.early)
    watch.save_state(t.conn, {"order": new["stamp"], "slot": plan["for"], "early": True})


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if "--cron" in sys.argv[1:]:
        print("\n".join(watch.cron_lines(str(ROOT), sys.executable)))
        return 0
    if "--check" in sys.argv[1:]:
        # «только сказать» ничего не меняет — общий замок не нужен
        return _run(check=True)
    # З1: общий замок с заявкой. Замок занят дольше срока (идёт долгая заявка
    # или прошлая проверка ещё забирает результат) — эту проверку пропускаем:
    # два сторожа разом хуже, чем проверка на 15 минут позже
    with watch.order_lock(watch.LOCK_WAIT_WATCH) as held:
        if not held:
            print(f"{_now():%d.%m %H:%M} общий замок занят дольше "
                  f"{watch.LOCK_WAIT_WATCH // 60} мин — эту проверку пропускаю, "
                  f"следующая по расписанию")
            return 0
        return _run(check=False)


def _run(check: bool) -> int:
    conn = db.connect()
    try:
        tick(conn, _now(), check)     # часы — после ожидания замка
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
r"""Заявка обхода с сервера (владелец 14.09.2026): тег `btn-…` → `queue.yml`
→ обход на GitHub. Плановый cron GitHub опаздывает на 4–5 ч, тег стартует
за минуту. Сам обход идёт на GitHub — сервер только подаёт заявку.

    venv/bin/python scripts/request_crawl.py days 6            утро: полный, 6 дней
    venv/bin/python scripts/request_crawl.py days 2            вечер: дозаправка
    venv/bin/python scripts/request_crawl.py date 2026-09-15   скан одной даты
    venv/bin/python scripts/request_crawl.py days 2 --check    только сказать, пошла бы заявка
    venv/bin/python scripts/request_crawl.py days 6 --force    без правила «1 час» (ручной заказ)
    … --unlock                                                 снять отметку «сбор идёт» (сторож: прогон мёртв по API)
    … --locked                                                 общий замок уже держит вызвавший (так заявку зовёт сторож)

Правила З1–З7, память (настройки `crawl_…`) и все пороги описаны в ОДНОМ
месте — в шапке `app/watch.py`. Здесь — только их исполнение: функция
`request` идёт по правилам в том же порядке:

    З1  общий замок со сторожем (в `main`)
    З2  отметка «заявка пришла на слот» (`crawl_slot`)
    З3  слот уже заменён досрочным сбором сторожа
    З4  стоит отметка «сбор идёт» — сверка с GitHub
    З5  правило «1 час»
    З6  тег-заявка и запись заказа
    З7  ждём старта; тег повторяем один раз и только если GitHub отвечает

Плановой заявка считается, если пришла по дням без --force не дальше 30
минут от слота таблицы `watch.SCHEDULE` (cron сервера — `crawl_watch.py
--cron`). Только плановая пишет `crawl_slot` и `crawl_missed`: за её слот
отвечает сторож (`scripts/crawl_watch.py`).
Правило «1 час» (владелец 29.09, срок 2 ч → 1 ч 02.10): плановая не шлётся,
если за последний час уже заказан или собран полный обход НЕ МЕНЬШЕЙ глубины
(ручной на 6 дней отменяет плановый на 2; ручной на 2 утренний на 6 не
отменяет). Точечный «Обойти сайт», скан даты и серверный сбор mojtv не в
счёт; заказ, который не дошёл до конца, — тоже (`order_dead`). Отмена видна
в «Прогонах» строкой «автомат: плановый обход … отменён: …».
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crawl_hook, db, trigger, watch  # noqa: E402


#: сколько часов свежий полный обход отменяет плановую заявку — правило
#: живёт в `app/crawl_hook` (им же отказывают кнопкам друзей)
RECENT_HOURS = crawl_hook.RECENT_HOURS


def _now() -> datetime:
    """Часы заявки отдельной функцией: проверки `test_watch.py` ставят
    «16:15» и «20:30», не дожидаясь их."""
    return datetime.now(crawl_hook.KYIV)


def order_dead(conn, now: datetime, listed: list) -> str:
    """Свежий заказ (`crawl_request`) не дошёл до конца? Слова, почему;
    пусто — жив (ждёт, идёт, дошёл) либо узнать нельзя. `listed` — список
    прогонов обхода с GitHub; пустой (GitHub молчит) — спрашиваем память
    сторожа: сорвавшийся заказ он помечает `failed` в `crawl_watch`."""
    order = watch.parse_order(db.get_setting(conn, "crawl_request"))
    if order is None:
        return ""
    if not listed:
        state = watch.load_json(conn, "crawl_watch")
        if state.get("order") == order["stamp"] and state.get("failed"):
            return "по записи сторожа он сорвался"
        return ""
    run = watch.run_for(order, watch.full_runs(listed))
    if run is None:
        age = (now - order["at"]).total_seconds() / 60
        if age >= watch.MARK_FRESH_MINUTES:
            return f"обход по нему не стартовал за {age:.0f} мин"
        return ""
    if (run.get("status") or "") in watch.RUNNING or run.get("conclusion") == "success":
        return ""
    return f"прогон #{run.get('run_number')} кончился «{run.get('conclusion') or '?'}»"


def recent_full(conn, days: int, now: datetime, runs) -> str:
    """З5. Свежий полный обход глубиной ≥ `days` за `RECENT_HOURS` часа —
    слова для «Прогонов»; пусто — свежего нет. Источник — тот же, что у
    кнопок друзей (`crawl_hook.fresh_full`): заказ из `crawl_request` или
    сбор, уже влитый в таблицу `runs`. `runs` — функция «список прогонов
    GitHub»: заказ, который не дошёл до конца (`order_dead`), не считается —
    иначе плановая заявка отменялась из-за обхода, которого не было."""
    for x in crawl_hook.fresh_full(conn, now):
        if x["days"] < days:
            continue
        if not x["done"]:
            dead = order_dead(conn, now, runs())
            if dead:
                print(f"{now:%d.%m %H:%M} правило «{RECENT_HOURS} час»: заказ на "
                      f"{x['days']} сут. в {x['at']:%H:%M} не в счёт — {dead}")
                continue
        return (f"{'собран' if x['done'] else 'заказан'} обход {x['days']} сут. "
                f"в {x['at']:%H:%M}")
    return ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2 or args[0] not in ("days", "date") \
            or not flags <= {"--check", "--force", "--unlock", "--locked"}:
        print(__doc__)
        return 2
    kind, value = args
    if kind == "days" and value not in ("2", "5", "6"):
        print("окно — 2, 5 или 6 суток")
        return 2
    if flags & {"--check", "--locked"}:
        # «только сказать» ничего не меняет, а у заявки сторожа замок уже
        # держит сам сторож — брать его второй раз значило бы ждать себя
        return request(kind, value, flags, held=True)
    # З1: общий замок со сторожем — из cron оба стартуют в одну минуту. Кто
    # второй, ждёт первого и решает уже по его итогу. Сторож держит замок
    # дольше срока — заявка идёт без замка: плановый сбор он не запрёт
    with watch.order_lock(watch.LOCK_WAIT_REQUEST) as held:
        return request(kind, value, flags, held)


def request(kind: str, value: str, flags: set, held: bool) -> int:
    """Одна заявка: правила З2–З7 по порядку (шапка `app/watch.py`)."""
    now = _now()                    # часы — после ожидания замка
    check = "--check" in flags
    conn = db.connect()
    try:
        if not held:
            words = (f"заявка {kind} {value}: общий замок со сторожем занят дольше "
                     f"{watch.LOCK_WAIT_REQUEST // 60} мин (сторож завис?) — "
                     f"иду без замка")
            print(f"{now:%d.%m %H:%M} {words}")
            watch.note(conn, words, who="автомат")
        if "--unlock" in flags:
            crawl_hook.clear(conn)
        # плановая ли это заявка — по таблице watch.SCHEDULE
        slot = (watch.slot_for(now, int(value))
                if kind == "days" and "--force" not in flags else None)
        cache: list = []

        def runs() -> list[dict]:
            # один запрос к API на заявку, сколько бы правил его ни спросили
            if not cache:
                cache.append(watch.github_runs(trigger._repo_slug(),
                                               workflow=watch.CRAWL_WORKFLOW))
            return cache[0]

        # ── З2. отметка «заявка пришла на слот» ──────────────────────────────
        seen = None
        if slot is not None and not check:
            seen = {"slot": watch.stamp(slot), "days": int(value),
                    "at": watch.stamp(now), "state": "started"}
            watch.save_json(conn, "crawl_slot", seen)

        def close(state: str) -> None:
            # итог плановой заявки; осталось «started» — заявку оборвали (С5)
            if seen is not None:
                seen["state"] = state
                watch.save_json(conn, "crawl_slot", seen)

        # ── З3. слот уже заменён досрочным сбором сторожа ────────────────────
        early = watch.load_json(conn, "crawl_early")
        if slot is not None and early.get("replaces") == watch.stamp(slot):
            how, words = watch.early_covers(early, slot, runs())
            if words:
                print(f"{now:%d.%m %H:%M} сторож: {words}")
                if not check:
                    watch.note(conn, words)
            if how == "running" and not check:
                # слот пропущен, пока досрочный ещё шёл: не дойдёт — сторож
                # скажет об этом в тревоге
                early["skipped"] = True
                watch.save_json(conn, "crawl_early", early)
            if how in ("done", "running"):
                close("skipped")
                return 0

        # ── З4. стоит отметка «сбор идёт» ────────────────────────────────────
        busy = crawl_hook.running(conn)
        # проба или обход меньшей глубины заявку не держат: GitHub поставит
        # новый обход в очередь за текущим; отметку текущего не трогаем
        behind = bool(busy) and crawl_hook.queue_behind(busy, kind, value)
        if busy and kind == "days":
            # отметке на слово не верим — сверяемся со списком прогонов
            # (05.10 проба провисела «идёт», и заявка 16:15 молча не ушла)
            verdict, words = watch.lock_verdict(busy, int(value), runs(), now)
            print(f"{now:%d.%m %H:%M} сторож: {words}" + (" (--check)" if check else ""))
            if not check:
                watch.note(conn, words)
            if verdict == "skip":
                close("skipped")
                return 0
            if verdict == "postpone":
                if slot is not None and not check:
                    missed(conn, slot, value, words, now)
                close("missed")
                return 0
            if verdict == "clear":
                if not check:
                    crawl_hook.clear(conn)
                busy, behind = None, False
            else:
                behind = True
        if busy and not behind:
            # сюда доходит только скан даты: он отметку «сбор идёт» уважает
            print(f"{now:%d.%m %H:%M} заявка {kind} {value} не отправлена: сбор "
                  f"уже {busy['state']} с {busy['since']} ({busy['what']})")
            return 0

        # ── З5. правило «1 час» ──────────────────────────────────────────────
        if kind == "days" and "--force" not in flags:
            fresh = recent_full(conn, int(value), now, runs)
            if fresh:
                print(f"{now:%d.%m %H:%M} автомат days {value} пропущен: "
                      f"{fresh} (правило «{RECENT_HOURS} час»)")
                if not check:
                    watch.note(conn, f"плановый обход {value} сут. отменён: "
                                     f"{fresh} (правило «{RECENT_HOURS} час»)",
                               who="автомат")
                close("skipped")
                return 0

        # ── З6. тег-заявка и запись заказа ───────────────────────────────────
        queue = f" — в очередь за «{busy['what']}»" if behind else ""
        if check:
            print(f"{now:%d.%m %H:%M} заявка {kind} {value} ПОШЛА БЫ{queue} (--check)")
            return 0
        ok, words = trigger.push_request_tag(kind, value)
        print(f"{now:%d.%m %H:%M} заявка {kind} {value}{queue}: {words}")
        if not ok:
            if slot is not None:
                why = f"плановая заявка не ушла: {words}"
                missed(conn, slot, value, why, now)
                watch.note(conn, why + " — сторож закажет обход на своей проверке")
            close("missed")
            return 1
        if not behind:
            crawl_hook.mark(conn, "заявка", f"{kind}-{value}")
        order = {"days": int(value) if kind == "days" else 0, "at": now,
                 "stamp": f"{now:%Y-%m-%d %H:%M}"}
        if kind == "days":
            db.set_setting(conn, "crawl_request",
                           f"обход {value} сут.|{order['stamp']}")
        close("ordered")

        # ── З7. ждём старта ──────────────────────────────────────────────────
        # ответом считается прогон того же вида: на заявку по дням — полный
        # обход, на скан даты — скан даты
        slug = trigger._repo_slug()
        kinds = watch.FULL_KINDS if kind == "days" else ("date", "unknown")
        head = f"заявка {kind} {value} от {order['stamp']}"
        run, answered = watch.wait_for_start(order, slug, kinds)
        if run is None and not answered:
            # GitHub молчит: «не стартовал» утверждать нельзя, а второй тег
            # при живом запуске дал бы два обхода подряд
            words = (f"{head}: GitHub не отвечает на список прогонов — стартовал ли "
                     f"обход, не видно. Тег не повторяю (вышло бы два обхода подряд), "
                     f"дальше следит сторож")
        else:
            if run is None:
                # GitHub отвечает, а прогона нет — повторяем тег один раз
                # (владелец 02.10: «заказать снова и убедиться, что пошёл»)
                ok, said = trigger.push_request_tag(kind, value)
                print(f"{now:%d.%m %H:%M} повтор заявки {kind} {value}: {said}")
                watch.note(conn, f"{head}: GitHub не стартовал за "
                                 f"{watch.START_MINUTES} мин — повтор: {said}",
                           who="автомат")
                if ok:
                    run, _ = watch.wait_for_start(
                        order, slug, kinds, seconds=watch.RETRY_WAIT_SECONDS)
            if run is not None:
                words = f"{head}: пошёл прогон #{run.get('run_number')}"
            else:
                # не ТРЕВОГА: это ещё не конец — сторож на ближайшей проверке
                # закроет заказ как сорвавшийся и решит по С4г (плановый →
                # досрочный); ТРЕВОГА будет, если не выйдет и это
                words = (f"{head}: прогон не стартовал и после повтора — заказ "
                         f"сорвался, дальше решает сторож на ближайшей проверке")
        print(f"{now:%d.%m %H:%M} {words}")
        watch.note(conn, words, who="автомат")
        return 0
    finally:
        conn.close()


def missed(conn, slot: datetime, days: str, why: str, now: datetime) -> None:
    """Плановая заявка не ушла — слот записываем сорвавшимся (`crawl_missed`):
    на ближайшей проверке с ним поступит сторож (правило С6)."""
    watch.save_json(conn, "crawl_missed", watch.missed_record(
        watch.load_json(conn, "crawl_missed"), watch.stamp(slot), int(days),
        watch.stamp(now), why))


if __name__ == "__main__":
    sys.exit(main())

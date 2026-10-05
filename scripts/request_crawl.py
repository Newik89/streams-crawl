# -*- coding: utf-8 -*-
r"""Заявка обхода с сервера (владелец 14.09.2026): тег `btn-…` → `queue.yml`
→ обход на GitHub. Плановый cron GitHub опаздывает на 4–5 ч, тег стартует
за минуту. Сам обход идёт на GitHub — сервер только подаёт заявку.

    venv/bin/python scripts/request_crawl.py days 6            утро: полный, 6 дней
    venv/bin/python scripts/request_crawl.py days 2            вечер: дозаправка
    venv/bin/python scripts/request_crawl.py date 2026-09-15   скан одной даты
    venv/bin/python scripts/request_crawl.py days 2 --check    только сказать, пошла бы заявка
    venv/bin/python scripts/request_crawl.py days 6 --force    без правила «1 час» (ручной заказ)
    … --unlock                                                 снять замок «сбор идёт» (сторож: прогон мёртв по API)

Сбор уже заказан или идёт (`app/crawl_hook.running`) — заявку не шлёт. Кроме
пробы и полного обхода меньшей глубины (05.10, `crawl_hook.queue_behind`):
тогда заявка уходит, и GitHub ставит обход в очередь за текущим.
С вечера 05.10 обход по дням отметке на слово не верит (`watch.lock_verdict`):
сверяется со списком прогонов GitHub — прогонов нет → отметка ложная, снять
и заказать; идёт полный не меньшей глубины → пропуск; идёт что-то меньшее
(проба, сайт, дата) → заказать в очередь; GitHub молчит → отметке верим, а
плановую заявку откладываем: её закажет сторож (`crawl_missed`). Не ушла
заявка — тоже запоминается для сторожа. Плановый, который сторож уже
выполнил досрочно (`crawl_early`, `watch.early_covers`), пропускается.
Расписание плановых — таблица `watch.SCHEDULE` (cron: `crawl_watch.py --cron`).
Правило «1 час» (владелец 29.09, срок 2 ч → 1 ч 02.10): автомат не шлётся,
если за последний `RECENT_HOURS` час уже был заказан или собран полный обход
НЕ МЕНЬШЕЙ глубины (ручной на 6 дней отменяет автомат на 2; ручной на 2
утренний на 6 не отменяет — тот захватывает больше дней). Точечный «Обойти
сайт», скан даты и серверный сбор mojtv не в счёт. Отмена видна в «Прогонах»
строкой «автомат: плановый обход … отменён: …».
После заявки скрипт ждёт до 3 мин, пока GitHub не заведёт прогон (открытый
API, `app/watch`); не завёл — повторяет заявку один раз (владелец 02.10:
«заказать снова и убедиться, что пошёл»). Дальше за обходом следит
`scripts/crawl_watch.py`.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crawl_hook, db, trigger, watch  # noqa: E402


#: сколько часов свежий полный обход отменяет автомат (владелец 29.09: 2;
#: 02.10: 1 — «если был внеплановый в течение часа или идёт сейчас»).
#: С 05.10 правило живёт в `app/crawl_hook` — им же отказывают кнопкам друзей
RECENT_HOURS = crawl_hook.RECENT_HOURS


def recent_full(conn, days: int, now: datetime) -> str:
    """Свежий полный обход глубиной ≥ `days` за `RECENT_HOURS` часа:
    заказ (`crawl_request`, пишут кнопка витрины и этот скрипт) или сбор,
    уже влитый в `runs` (обычный полный обход — у него пустое «кто»).
    Время — киевское, наивное. Пусто — свежего нет. Сама проверка — в
    `crawl_hook.recent_full` (05.10), здесь — слова для «Прогонов»."""
    x = crawl_hook.recent_full(conn, days, now)
    if not x:
        return ""
    return (f"{'собран' if x['done'] else 'заказан'} обход {x['days']} сут. "
            f"в {x['at']:%H:%M}")


def _now() -> datetime:
    """Часы заявки отдельной функцией (05.10): проверки `test_watch.py`
    ставят «16:15» и «20:30», не дожидаясь их."""
    return datetime.now(crawl_hook.KYIV)


def _missed(conn, slot: datetime, days: str, why: str, now: datetime) -> None:
    """Плановая заявка не ушла — запомнить для сторожа: он закажет обход
    досрочно на ближайшей проверке (`watch.plan_early`, 05.10)."""
    watch.save_json(conn, "crawl_missed", {
        "slot": watch.stamp(slot), "days": int(days), "at": watch.stamp(now),
        "why": why, "state": "missed"})


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2 or args[0] not in ("days", "date") \
            or not flags <= {"--check", "--force", "--unlock"}:
        print(__doc__)
        return 2
    kind, value = args
    if kind == "days" and value not in ("2", "5", "6"):
        print("окно — 2, 5 или 6 суток")
        return 2
    now = _now()
    check = "--check" in flags
    conn = db.connect()
    try:
        if "--unlock" in flags:
            crawl_hook.clear(conn)
        # плановая ли это заявка (по таблице watch.SCHEDULE): только о ней
        # сторож помнит «не ушла» и «выполнен досрочно» (05.10)
        slot = (watch.slot_for(now, int(value))
                if kind == "days" and "--force" not in flags else None)
        cache: list = []

        def runs() -> list[dict]:
            # один запрос к API на заявку, сколько бы проверок его ни ждали
            if not cache:
                cache.append(watch.github_runs(trigger._repo_slug(),
                                               limit=watch.RUNS_LIMIT,
                                               workflow=watch.CRAWL_WORKFLOW))
            return cache[0]

        if slot is not None:
            early = watch.load_json(conn, "crawl_early")
            if early.get("replaces") == watch.stamp(slot):
                done, words = watch.early_covers(early, slot, runs())
                if words:
                    print(f"{now:%d.%m %H:%M} сторож: {words}")
                    if not check:
                        watch.note(conn, words)
                if done:
                    return 0
        busy = crawl_hook.running(conn)
        # проба или обход меньшей глубины плановый не держат (05.10): GitHub
        # поставит его в очередь за текущим; отметку текущего не трогаем
        behind = bool(busy) and crawl_hook.queue_behind(busy, kind, value)
        if busy and kind == "days":
            # вечер 05.10: отметке на слово не верим — сверяемся с GitHub.
            # Днём проба провисела «идёт», и заявка 16:15 молча не ушла
            verdict, words = watch.lock_verdict(busy, int(value), runs(), now)
            print(f"{now:%d.%m %H:%M} сторож: {words}" + (" (--check)" if check else ""))
            if not check:
                watch.note(conn, words)
            if verdict == "skip":
                return 0
            if verdict == "postpone":
                if slot is not None and not check:
                    _missed(conn, slot, value, words, now)
                return 0
            if verdict == "clear":
                if not check:
                    crawl_hook.clear(conn)
                busy, behind = None, False
            else:
                behind = True
        if busy and not behind:
            print(f"{now:%d.%m %H:%M} заявка {kind} {value} не отправлена: сбор "
                  f"уже {busy['state']} с {busy['since']} ({busy['what']})")
            return 0
        if kind == "days" and "--force" not in flags:
            fresh = recent_full(conn, int(value), now)
            if fresh:
                print(f"{now:%d.%m %H:%M} автомат days {value} пропущен: "
                      f"{fresh} (правило «{RECENT_HOURS} час»)")
                watch.note(conn, f"плановый обход {value} сут. отменён: "
                                 f"{fresh} (правило «{RECENT_HOURS} час»)",
                           who="автомат")
                return 0
        queue = f" — в очередь за «{busy['what']}»" if behind else ""
        if "--check" in flags:
            print(f"{now:%d.%m %H:%M} заявка {kind} {value} ПОШЛА БЫ{queue} (--check)")
            return 0
        ok, words = trigger.push_request_tag(kind, value)
        print(f"{now:%d.%m %H:%M} заявка {kind} {value}{queue}: {words}")
        if not ok:
            if slot is not None:
                # 05.10: не ушла плановая — сторож закажет её досрочно
                why = f"плановая заявка не ушла: {words}"
                _missed(conn, slot, value, why, now)
                watch.note(conn, why + " — сторож закажет обход на своей проверке")
            return 1
        if not behind:
            crawl_hook.mark(conn, "заявка", f"{kind}-{value}")
        order = {"days": int(value) if kind == "days" else 0, "at": now,
                 "stamp": f"{now:%Y-%m-%d %H:%M}"}
        if kind == "days":
            db.set_setting(conn, "crawl_request",
                           f"обход {value} сут.|{order['stamp']}")
        # убедиться, что GitHub завёл прогон; не завёл за 3 мин — повторить
        # заявку один раз (владелец 02.10: «заказать снова и убедиться»)
        slug = trigger._repo_slug()
        run = watch.wait_for_start(order, slug)
        if run is None:
            ok2, words2 = trigger.push_request_tag(kind, value)
            print(f"{now:%d.%m %H:%M} повтор заявки {kind} {value}: {words2}")
            watch.note(conn, f"заявка {kind} {value} от {order['stamp']}: GitHub не "
                             f"стартовал за {watch.START_MINUTES} мин — повтор: {words2}",
                       who="автомат")
            run = watch.wait_for_start(order, slug, seconds=120) if ok2 else None
        if run is not None:
            words3 = (f"заявка {kind} {value} от {order['stamp']}: пошёл прогон "
                      f"#{run.get('run_number')}")
        else:
            words3 = (f"ТРЕВОГА — заявка {kind} {value} от {order['stamp']}: прогон "
                      f"не стартовал и после повтора, дальше следит сторож")
        print(f"{now:%d.%m %H:%M} {words3}")
        watch.note(conn, words3, who="автомат")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

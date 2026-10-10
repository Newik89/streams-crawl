# -*- coding: utf-8 -*-
r"""Заявка обхода с сервера (владелец 14.09.2026): тег `btn-…` → `queue.yml`
→ обход на GitHub. Плановый cron GitHub опаздывает на 4–5 ч, тег стартует
за минуту. Сам обход идёт на GitHub — сервер только подаёт заявку.

    venv/bin/python scripts/request_crawl.py days 6            утро: полный, 6 дней
    venv/bin/python scripts/request_crawl.py days 2            вечер: дозаправка
    venv/bin/python scripts/request_crawl.py date 2026-09-15   скан одной даты
    venv/bin/python scripts/request_crawl.py site nova.bg      обход одного сайта на GitHub (повтор сторожа)
    venv/bin/python scripts/request_crawl.py reparse 37966719570-prev   переразбор страниц прогона без обхода
                                                               (сторож, схема сбоев шаг 4; «-prev» — кодом прежней версии)
    venv/bin/python scripts/request_crawl.py days 2 --check    только сказать, пошла бы заявка
    venv/bin/python scripts/request_crawl.py days 6 --force    без правила «1 час» (ручной заказ)
    … --unlock                                                 снять отметку «сбор идёт», если на GitHub живого сбора нет
    … --locked                                                 общий замок уже держит вызвавший (так заявку зовёт сторож); старта не ждёт
    … --manual                                                 заказ владельца кнопкой: правила те же, но заявка не плановая
    … --retry-of=<id>                                          это повтор сторожа заказа <id> (запись книги)
    … --reparse-of=<id>                                        это переразбор сторожа за сорвавшийся заказ <id>
    … --early-for=<ГГГГ-ММ-ДД ЧЧ:ММ>                           это досрочный сторожа за сорвавшийся слот

Правила З1–З7, память (настройки `crawl_…`) и все пороги описаны в ОДНОМ
месте — в шапке `app/watch.py`. Здесь — только их исполнение: функция
`request` идёт по правилам в том же порядке:

    З1  общий замок со сторожем (в `main`)
    З2  отметка «заявка пришла на слот» (`crawl_slot`)
    З3  слот уже заменён досрочным сбором сторожа
    З4  стоит отметка «сбор идёт» — сверка с GitHub
    З5  правило «1 час»
    З6  тег-заявка и запись заказа (не плановая и не досрочная — только если
        в очереди GitHub не ждёт полный обход)
    З7  ждём старта 3 минуты уже без замка (`wait_start`); тег НЕ повторяем —
        замену закажет сторож

Плановой заявка считается, если пришла по дням без --force и --manual не
дальше 30 минут от слота таблицы `watch.SCHEDULE` (cron сервера —
`crawl_watch.py --cron`). Только плановая пишет `crawl_slot` и
`crawl_missed`: за её слот отвечает сторож (`scripts/crawl_watch.py`).
--manual ставит кнопка «Заказать сбор сейчас» (`app/emergency.py`): правила
З3–З7 те же, что у плановой, но слот она не закрывает и сорвавшимся не
делает.
Правило «1 час» (владелец 29.09, срок 2 ч → 1 ч 02.10): плановая не шлётся,
если за последний час уже заказан или собран полный обход НЕ МЕНЬШЕЙ глубины
(ручной на 6 дней отменяет плановый на 2; ручной на 2 утренний на 6 не
отменяет). Точечный «Обойти сайт», скан даты и серверный сбор mojtv не в
счёт; заказ, который не дошёл до конца, — тоже (`order_dead`). Отмена видна
в «Прогонах» строкой «автомат: плановый обход … отменён: …».
"""

from __future__ import annotations

import re
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
    сторожа: сорвавшийся заказ он помечает `failed` в книге заказов."""
    order = watch.parse_order(db.get_setting(conn, "crawl_request"))
    if order is None:
        return ""
    if not listed:
        if watch.full_order_record(conn, order, save=False).get("failed"):
            return "по записи сторожа он сорвался"
        return ""
    run = watch.run_for(order, watch.full_runs(listed))
    if run is None:
        age = (now - order["at"]).total_seconds() / 60
        if age >= watch.START_GIVEUP_MINUTES:
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
    flags = {a for a in sys.argv[1:] if a.startswith("--") and "=" not in a}
    # пометки сторожа для записи книги заказов: --retry-of=<id>, --early-for=<слот>
    marks = dict(a[2:].split("=", 1) for a in sys.argv[1:]
                 if a.startswith("--") and "=" in a)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2 or args[0] not in ("days", "date", "site", "reparse") \
            or not flags <= {"--check", "--force", "--unlock", "--locked", "--manual"} \
            or not set(marks) <= {"retry-of", "early-for", "reparse-of"}:
        print(__doc__)
        return 2
    kind, value = args
    if kind == "days" and value not in ("2", "5", "6"):
        print("окно — 2, 5 или 6 суток")
        return 2
    if kind == "date" and not re.fullmatch(r"\d{4}-\d\d-\d\d", value):
        print("дата — ГГГГ-ММ-ДД")
        return 2
    if kind == "site" and not re.fullmatch(r"[a-z0-9.-]{1,100}", value):
        print("сайт — домен латиницей, например nova.bg")
        return 2
    if kind == "reparse" and not re.fullmatch(r"\d{1,20}(-prev)?", value):
        print("переразбор — id прогона GitHub цифрами, с «-prev» для кода прежней версии")
        return 2
    if flags & {"--check", "--locked"}:
        # «только сказать» ничего не меняет, а у заявки сторожа замок уже
        # держит сам сторож — брать его второй раз значило бы ждать себя.
        # Старта заявка сторожа не ждёт: его судит сам сторож (С4), а замок
        # на время ожидания держать незачем
        code, _ = request(kind, value, flags, held=True, marks=marks)
        return code
    # З1: общий замок со сторожем — из cron оба стартуют в одну минуту. Кто
    # второй, ждёт первого и решает уже по его итогу. Сторож держит замок
    # дольше срока — заявка идёт без замка: плановый сбор он не запрёт.
    # Под замком — только решение и тег (З2–З6); ждут старта (З7) уже без
    # замка: сторожу незачем стоять 3 минуты за чужим ожиданием
    with watch.order_lock(watch.LOCK_WAIT_REQUEST) as held:
        code, wait = request(kind, value, flags, held, marks=marks)
    if wait is not None:
        wait()
    return code


def who_ordered(flags: set, marks: dict, slot) -> tuple[str, dict]:
    """Кто заказал — для записи книги заказов (её id и пометки)."""
    if marks.get("retry-of"):
        return "сторож: повтор", {"retry_of": marks["retry-of"], "reordered": True}
    if marks.get("reparse-of"):
        return "сторож: переразбор", {"reparse_of": marks["reparse-of"]}
    if marks.get("early-for"):
        return "сторож: досрочный", {"early": True}
    if "--manual" in flags:
        return "владелец", {}
    if "--force" in flags:
        return "сторож", {}
    return ("cron" if slot is not None else "заявка"), {}


def request(kind: str, value: str, flags: set, held: bool,
            marks: dict | None = None):
    """Одна заявка: правила З2–З6 по порядку (шапка `app/watch.py`).
    Возвращает (код выхода, ожидание старта З7 или None): ждать старта
    вызывающий будет уже без общего замка."""
    marks = marks or {}
    now = _now()                    # часы — после ожидания замка
    check = "--check" in flags
    conn = db.connect(db.BUSY_TIMEOUT_SCRIPT)
    try:
        if not held:
            words = (f"заявка {kind} {value}: общий замок со сторожем занят дольше "
                     f"{watch.LOCK_WAIT_REQUEST // 60} мин (сторож завис?) — "
                     f"иду без замка")
            print(f"{now:%d.%m %H:%M} {words}")
            watch.note(conn, words, who="автомат")
        # плановая ли это заявка — по таблице watch.SCHEDULE
        slot = (watch.slot_for(now, int(value))
                if kind == "days" and not flags & {"--force", "--manual"} else None)
        cache: list = []

        def runs() -> list[dict]:
            # один запрос к API на заявку, сколько бы правил его ни спросили
            if not cache:
                cache.append(watch.github_runs(trigger._repo_slug(),
                                               workflow=watch.CRAWL_WORKFLOW))
            return cache[0]

        if "--unlock" in flags:
            # отметку живого сбора не снимаем: сверка с GitHub (прогоны, чью
            # отмену уже подал сторож, — не живые)
            refusal = watch.unlock_refusal(runs(), watch.load_json(conn, "crawl_cancel"))
            if refusal:
                print(f"{now:%d.%m %H:%M} отметку «сбор идёт» не снимаю: {refusal}")
            elif not check:
                crawl_hook.clear(conn)

        # ── З2. отметка «заявка пришла на слот» ──────────────────────────────
        seen = None
        if slot is not None and not check:
            seen = {"slot": watch.stamp(slot), "days": int(value),
                    "at": watch.when(now), "state": "started"}
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
                return 0, None

        # ── З4. стоит отметка «сбор идёт» ────────────────────────────────────
        busy = crawl_hook.running(conn)
        # проба или обход меньшей глубины заявку не держат: GitHub поставит
        # новый обход в очередь за текущим; отметку текущего не трогаем
        behind = bool(busy) and crawl_hook.queue_behind(busy, kind, value)
        if busy and "--force" in flags:
            # сторож или «всё равно заказать»: решение уже принято тем, кто
            # видел список GitHub, — заявка встаёт в очередь за идущим сбором,
            # его отметку не трогаем (очередь сторожит З6)
            behind = True
        elif busy and kind == "days":
            # отметке на слово не верим — сверяемся со списком прогонов
            # (05.10 проба провисела «идёт», и заявка 16:15 молча не ушла)
            verdict, words = watch.lock_verdict(busy, int(value), runs(), now)
            print(f"{now:%d.%m %H:%M} сторож: {words}" + (" (--check)" if check else ""))
            if not check:
                watch.note(conn, words)
            if verdict == "skip":
                close("skipped")
                return 0, None
            if verdict == "postpone":
                if slot is not None and not check:
                    watch.lost_slot(conn, "planned-postponed", slot, int(value),
                                    words, now)
                close("missed")
                return 0, None
            if verdict == "clear":
                if not check:
                    crawl_hook.clear(conn)
                busy, behind = None, False
            else:
                behind = True
        if busy and not behind:
            # сюда доходит скан даты и сайт: отметку «сбор идёт» они уважают
            print(f"{now:%d.%m %H:%M} заявка {kind} {value} не отправлена: сбор "
                  f"уже {busy['state']} с {busy['since']} ({busy['what']})")
            return 0, None

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
                return 0, None

        # ── З6. тег-заявка и запись заказа ───────────────────────────────────
        # у GitHub в очереди одно место: новая заявка вытесняет ждущую. Если
        # там уже ЖДЁТ полный обход, уходят только плановая и досрочная (они
        # его заменяют, и сторож это знает — `watch.superseded`); прочие —
        # нет, иначе вытеснили бы его
        if slot is None and not marks.get("early-for"):
            refusal = watch.queue_refusal(runs())
            if refusal:
                words = f"заявка {kind} {value} не отправлена: {refusal}"
                print(f"{now:%d.%m %H:%M} {words}" + (" (--check)" if check else ""))
                if not check:
                    watch.note(conn, words, who="автомат")
                return 3, None
        queue = f" — в очередь за «{busy['what']}»" if behind else ""
        if check:
            print(f"{now:%d.%m %H:%M} заявка {kind} {value} ПОШЛА БЫ{queue} (--check)")
            return 0, None
        # в имени тега у сайта — домен в base32 (`queue.yml` его разжимает)
        tag_value = trigger.encode_probe_url(value) if kind == "site" else value
        ok, words = trigger.push_request_tag(kind, tag_value)
        print(f"{now:%d.%m %H:%M} заявка {kind} {value}{queue}: {words}")
        if ok is False:
            if slot is not None:
                why = f"плановая заявка не ушла: {words}"
                if watch.lost_slot(conn, "planned-not-sent", slot, int(value),
                                   why, now) == "early":
                    watch.note(conn, why + " — сторож закажет обход на своей проверке")
            close("missed")
            return 1, None
        # ok None — git не ответил вовремя, а заявка могла дойти (29.09 так и
        # было). Это не срыв: заказ пишем как ушедший, а дошёл ли — решат
        # ожидание старта (З7) и сторож (С4): нет прогона — заказ сорвался
        # переразбор: вид заказа — как имя прогона (`Обход reparse-<id>`),
        # «-prev» (код прежней версии) едет только в теге
        what = (f"full-{value}" if kind == "days" else
                f"reparse-{value.split('-')[0]}" if kind == "reparse" else
                f"{kind}-{value}")
        if not behind:
            crawl_hook.mark(conn, "заявка", what if kind == "reparse" else f"{kind}-{value}")
        order = {"what": what, "days": int(value) if kind == "days" else 0,
                 "at": watch.utc(now), "stamp": watch.stamp(now)}
        if kind == "days":
            db.set_setting(conn, "crawl_request",
                           f"обход {value} сут.|{order['stamp']}")
        # в книгу заказов: сторож доведёт заказ до итога и узнает из записи,
        # а не по времени, чей он (С4); свой повтор и досрочный — по пометкам
        who, extra = who_ordered(flags, marks, slot)
        if kind == "reparse":
            extra["prev"] = value.endswith("-prev")
        watch.add_order(conn, what, order["stamp"],
                        marks.get("early-for") or (watch.stamp(slot) if slot else ""),
                        who, at=now, **extra)
        close("ordered")
        if "--locked" in flags:
            return 0, None              # старт заявки сторожа судит сам сторож
        return 0, lambda: wait_start(kind, value, tag_value, order, now)
    finally:
        conn.close()


def wait_start(kind: str, value: str, tag_value: str, order: dict, now: datetime) -> None:
    """З7. Ждём старта 3 минуты — уже БЕЗ общего замка — и пишем итог в
    «Прогоны». Ответом считается прогон того же вида (`watch.answers`): на
    заявку по дням — полный обход, на скан даты — скан той же даты."""
    slug = trigger._repo_slug()
    kinds = watch.FULL_KINDS if kind == "days" else (kind, "unknown")
    head = f"заявка {kind} {value} от {order['stamp']}"
    run, answered = watch.wait_for_start(order, slug, kinds)
    if run is None and not answered:
        # GitHub молчит: «не стартовал» утверждать нельзя, а второй тег
        # при живом запуске дал бы два обхода подряд
        words = (f"{head}: GitHub не отвечает на список прогонов — стартовал ли "
                 f"обход, не видно. Тег не повторяю (вышло бы два обхода подряд), "
                 f"дальше следит сторож")
    elif run is not None:
        words = f"{head}: пошёл прогон #{run.get('run_number')}"
    else:
        # GitHub отвечает, а прогона нет. Тег НЕ повторяем: второй тег мог
        # бы дать второй полный обход, а замену, если этот так и не
        # стартует, закажет сторож по таблице RECOVERY. Пересылку тега
        # (`queue.yml`) смотрим только для слов — что именно случилось
        fwd = watch.forwarding(order, slug, f"btn-{kind}-{tag_value}-")
        said = {"going": "пересылка тега ещё идёт или ждёт машину GitHub",
                "done": "тег переслан, а обход ещё не показался",
                "failed": "пересылка тега упала",
                "none": "GitHub пересылку тега не показал — тег, похоже, не дошёл",
                "silent": "GitHub не ответил про пересылку тега"}[fwd]
        # не ТРЕВОГА: это ещё не конец — сторож сам закажет замену
        words = (f"{head}: обход не стартовал за {watch.START_MINUTES} мин ({said}). "
                 f"Тег не повторяю (вышло бы два обхода); не стартует за "
                 f"{watch.START_GIVEUP_MINUTES} мин — сторож сочтёт заказ "
                 f"сорвавшимся и закажет замену")
    print(f"{now:%d.%m %H:%M} {words}")
    conn = db.connect(db.BUSY_TIMEOUT_SCRIPT)
    try:
        watch.note(conn, words, who="автомат")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

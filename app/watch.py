# -*- coding: utf-8 -*-
"""Сторож заказа обхода: сервер сам доводит каждый плановый сбор до конца
или зовёт владельца (слово владельца 02.10, 05.10 и 06.10.2026).

КАК ИДЁТ СБОР. Cron сервера в слот (`SCHEDULE`) запускает заявку
(`scripts/request_crawl.py`) → она пушит тег → `queue.yml` на GitHub запускает
обход (`crawl.yml`, 30–90 минут) → обход стучит серверу «начал» и «закончил»
(`app/crawl_hook`) → сервер забирает результат. Раз в 15 минут cron запускает
сторожа (`scripts/crawl_watch.py`): он смотрит список прогонов GitHub и чинит
то, что пошло не так.
Главное слово владельца: сорвавшийся плановый сбор НЕ догоняем тем же окном —
сторож один раз заказывает ближайший плановый досрочно; не вышло и это —
только ТРЕВОГА (строка «сторож: ТРЕВОГА — …» в «Прогонах» админки), новых
заказов нет до следующего слота. Ничто не кончается молча: у каждого сбора
итог один из трёх — забран, заменён досрочным, ТРЕВОГА.
ЧТО ДЕЛАТЬ ПОСЛЕ СБОЯ решает ОДНА таблица — `RECOVERY` («вид сбоя → шаг»:
досрочный, повтор или ТРЕВОГА); правила ниже лишь замечают сбой и зовут её.

ПРАВИЛА ЗАЯВКИ — в том же порядке, что шаги в `request_crawl.request`
(что случилось → что делаем → сколько обходов закажет заявка):
  З1. Заявка и сторож стартовали в одну минуту → общий замок (`order_lock`):
      второй ждёт первого и решает уже по его итогу. Сторож держит замок
      дольше 10 минут → заявка идёт без замка. → на число заказов не влияет.
  З2. Заявка пришла в плановый слот → первым делом отметка «пришла»
      (`crawl_slot`), на каждом выходе — её итог. → 0.
  З3. Этот слот уже заменён досрочным сбором сторожа (`early_covers`):
      досрочный дошёл до конца → «выполнен досрочно», выходим; ещё идёт →
      выходим (идёт полный не меньшей глубины) и помечаем, что слот пропущен
      ради него; начат раньше окна, упал, не стартовал → идём дальше. → 0.
  З4. Стоит отметка «сбор идёт» (`lock_verdict`): на GitHub прогонов нет →
      отметка ложная, снимаем и идём дальше; идёт полный не меньшей глубины
      → выходим; идёт меньшее (проба, сайт, дата, полный мельче) → идём
      дальше, обход встанет в очередь; GitHub не ответил → отметке верим,
      слот записываем сорвавшимся (`crawl_missed`) и выходим. → 0.
  З5. Правило «1 час»: за последний час полный не меньшей глубины уже собран
      или заказан (и не сорвался) → выходим. → 0.
  З6. Шлём тег-заявку: не ушла → слот записываем сорвавшимся и выходим (0);
      ушла → записываем заказ (`crawl_request`). → 1.
  З7. Ждём старта 3 минуты (`wait_for_start`): прогон появился → готово;
      GitHub не отвечает на список → тег НЕ повторяем; отвечает, а прогона
      нет → повторяем тег один раз (это тот же заказ) и ждём ещё 2 минуты;
      нет и тогда → строка «заказ сорвался», дальше решает сторож (С4г:
      плановый → досрочный, его ТРЕВОГА — если не выйдет и он). → 0 новых.

ПРАВИЛА СТОРОЖА — в том же порядке, что шаги в `crawl_watch.tick`
(что случилось → что делаем → сколько обходов закажет сторож):
  С1. GitHub не ответил на список прогонов → проверку пропускаем; молчит
      час подряд → одна ТРЕВОГА; снова ответил → строка «отбой». → 0.
  С2. Прошлую проверку оборвали посреди заказа досрочного (перезагрузка
      сервера): заявка успела уйти → следим за ней как за досрочным; не
      успела → ТРЕВОГА. → 0.
  С3. Прогон завис (идёт дольше потолка своего вида либо 20 минут стоит в
      очереди, хотя впереди никого) → одна заявка отмены на прогон; заявка
      не ушла или прогон не остановился за 10 минут → ТРЕВОГА. → 0.
  С4. Текущий заказ (`decide`):
      а) рано судить (ждём старта, обход идёт, ждём стука) → ждём. → 0;
      б) готов, результат на GitHub, а на сервере его нет → забираем сами;
         не вышло два раза → ТРЕВОГА, пробуем дальше. → 0;
      в) готов и забран → закрываем заказ. → 0;
      г) сорвался (не стартовал за 3 минуты, кончился не успехом, завис и
         отменяется) → закрываем заказ и смотрим, чей он: ДОСРОЧНЫЙ → ТРЕВОГА
         (0); ПЛАНОВЫЙ → слот записываем сорвавшимся, решает С6 (0);
         РУЧНОЙ (кнопка) → один повтор той же глубины (1), сорвался и
         повтор → ТРЕВОГА (0);
      д) за 6 часов заказ так и не закрыт → ТРЕВОГА, следить перестаём
         (досрочный считается сорвавшимся). → 0.
  С5. Плановая заявка на последний прошедший слот не запускалась (сервер был
      выключен, cron не сработал) или оборвалась (`slot_audit`) → слот
      записываем сорвавшимся, решает С6. → 0.
  С6. Есть сорвавшийся слот (`plan_early`): досрочный за него уже был →
      ничего; сорвался больше 6 часов назад → ТРЕВОГА «поздно»; после него
      уже заказан обход не меньшей глубины, либо такой обход сейчас идёт,
      либо уже успешно завершился (по списку GitHub; память сторожа «done»
      о последнем заказе — тоже довод) → ничего; иначе → ОДИН досрочный: глубина
      — большая из сорвавшегося и следующего планового; начат не раньше чем
      за 4 часа до следующего слота и дошёл — тот слот пропускается (З3).
      Заявка досрочного не ушла → ТРЕВОГА. → не больше 1 на слот.
ИТОГО на один плановый слот — не больше двух обходов: один от заявки и один
(досрочный) от сторожа. Повтор тега в З7 — тот же заказ; лишь если GitHub с
опозданием исполнит оба тега, обходов от заявки выйдет два.

ПАМЯТЬ — настройки в таблице `settings`. Вся она описана здесь; любую запись
можно стереть вручную — сторож начнёт по ней с чистого листа.
  crawl_request — последний заказ полного обхода, строка
      `обход 6 сут.|2026-10-06 06:15`. Пишут: заявка (З6), кнопка витрины
      (`web._dispatch`). Читают: сторож (С4, С6), правило «1 час» (З5,
      `crawl_hook.fresh_full`), панель «Здоровье». Не стирается —
      переписывается следующим заказом.
  crawl_running — отметка «сбор заказан / идёт», строка
      `идёт|<unix-время>|16:16|full-2`. Пишут: заявка и кнопки («заявка»),
      стук «начал» («идёт») — `crawl_hook.mark`. Стирают: стук «закончил»,
      заявка (З4 — ложная отметка; ключ --unlock), сторож перед забором
      (С4б). Сама гаснет по сроку (`crawl_hook.running`).
  crawl_slot — приходила ли плановая заявка на слот (З2 → С5), JSON
      {slot, days, at, state}. state: started — пришла, итога ещё нет;
      ordered, skipped, missed — итог заявки; init — первая проверка сторожа
      после выкладки; early, audited — слот закрыл сторож. Пишут: заявка,
      сторож. Читает: сторож. Переписывается на каждом слоте.
  crawl_watch — память сторожа о текущем заказе (С4), JSON {order, slot,
      early, reordered, done, failed, pulls}. order — отметка времени заказа
      и ключ записи: в `crawl_request` другой заказ — запись начинается
      заново (`load_state`); slot — плановый слот заказа, пусто у ручного;
      early — это досрочный заказ сторожа; reordered — это уже повтор
      ручного заказа; done — результат на сервере; failed — заказ сорвался,
      и по нему всё решено; reset — владелец сбросил память сторожа
      (`reset_memory`): за этим заказом сторож больше не следит; pulls —
      сколько раз сторож сам забирал результат. Пишут: сторож, кнопка
      «Сбросить память». Читают: сторож, правило «1 час» (З5).
  crawl_missed — сорвавшийся плановый слот, по которому надо решить, нужен
      ли досрочный (З4, З6, С4г, С5 → С6), JSON {slot, days, at, why, state,
      also}. at — когда сорвался; state: missed — ждёт решения С6; handled —
      досрочный заказан (или уже был); late, drop, covered, collected —
      досрочный не нужен (почему — `plan_early`); failed — заявка досрочного
      не ушла. also — прежний слот, который ещё ждал решения, когда сорвался
      этот: один досрочный закроет оба, глубина — большая (`missed_record`).
      Пишут: заявка, сторож — только через `missed_record`. Читает: сторож.
      Переписывается следующим сорвавшимся слотом.
  crawl_early — досрочный сбор сторожа (С6 → С2, С4, З3), JSON {for,
      for_days, days, replaces, replaces_days, begun, ordered_at, state,
      started, run, skipped}. for — за какой слот; replaces — какой слот
      заменяет; begun — когда сторож начал заказывать; ordered_at — отметка
      заказа, пусто, пока заявка не ушла; state: ordering — заказ начат;
      ordered — заявка ушла; done — дошёл до конца (started и run — его
      начало и номер); failed — не прошёл; skipped — плановый `replaces`
      пропущен, пока досрочный ещё шёл. Пишут: сторож, заявка (только
      skipped). Читают: сторож, заявка. Переписывается следующим досрочным.
  crawl_cancel — поданные заявки отмены (С3), JSON {id прогона: {at, number,
      alarmed}}. at — когда подана; number — номер прогона для строк;
      alarmed — тревога по ней уже была. Пишут сторож и кнопка «Остановить
      зависший» — обе через `send_cancel`; читает сторож (сверяет, что
      прогон остановился). Запись уходит, когда прогон остановился или
      выпал из списка последних.
  crawl_silent — с какого времени GitHub молчит (С1), JSON {since, alarmed}.
      Пишет и читает сторож; стирается, когда GitHub ответил.
Кнопка «Сбросить память сторожа» (`reset_memory`) стирает всё, что сторож
помнит сам (`WATCH_MEMORY`), а текущий заказ помечает reset. Заказ
(`crawl_request`) и отметку «сбор идёт» (`crawl_running`) она не трогает.
Общий замок заявки и сторожа — файл `data/crawl-order.lock` (`order_lock`).
Экстренные кнопки владельца — `app/emergency.py`: своей логики у них нет.

Список прогонов — из ОТКРЫТОГО API GitHub: репозиторий публичный, ключ не
нужен, лимит 60 запросов в час на адрес. Сторож делает один запрос за
проверку, заявка — один на сверку и до семнадцати, пока ждёт старта.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sqlite3
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import crawl_hook, db, trigger

KYIV = ZoneInfo("Europe/Kyiv")
API = "https://api.github.com"

# ── все пороги сторожа — здесь; у каждого сказано, откуда цифра ──────────────

#: Плановые заявки сервера (владелец 03.10): время по Киеву и глубина, суток.
#: Одна таблица на всё: по ней заявка узнаёт свой слот, сторож ищет следующий
#: и прошедший слот, из неё же строки cron (`crawl_watch.py --cron`).
#: cron сервера живёт вне репозитория и ОБЯЗАН совпадать с ней — слот из
#: таблицы, на который cron заявку не шлёт, сторож сочтёт сорвавшимся (С5):
#:   15 6  * * *  … request_crawl.py days 6
#:   15 16 * * *  … request_crawl.py days 2
#:   30 20 * * *  … request_crawl.py days 6
SCHEDULE = (("06:15", 6), ("16:15", 2), ("20:30", 6))
#: заявка считается плановой, если пришла не дальше стольких минут от слота
#: (cron бьёт минута в минуту; запас — на ожидание замка и ручной запуск)
SLOT_MATCH_MINUTES = 30

#: workflow обхода — только его прогоны сторож разбирает и отменяет
CRAWL_WORKFLOW = "crawl.yml"
#: сколько последних прогонов обхода сторож берёт одним запросом (за день
#: с пробами набегает до 15 прогонов — замер 05.10)
RUNS_LIMIT = 20
#: статусы GitHub «прогон ещё не закончен»
RUNNING = ("queued", "in_progress", "waiting", "pending", "requested")
#: прогон считаем ответом на заявку, если он создан не раньше, чем за столько
#: минут до неё (часы сервера и GitHub могут чуть расходиться)
MATCH_SLACK_MINUTES = 2

#: З7: минут после заявки, когда обход уже должен был стартовать (замер:
#: тег → прогон за 10 секунд; владелец 02.10 — «убедиться, что пошёл»)
START_MINUTES = 3
#: З7: как часто заявка спрашивает GitHub о старте, секунд
START_POLL_SECONDS = 20
#: З7: сколько секунд ждём старта после повторного тега
RETRY_WAIT_SECONDS = 120
#: З4: заявке моложе стольких минут верим без списка прогонов — GitHub мог
#: её ещё не показать
MARK_FRESH_MINUTES = 5

#: З1: сколько секунд ждать общий замок. Заявка — 10 минут, потом идёт БЕЗ
#: замка (зависший сторож плановый сбор не запрёт); сторож — 7 минут (заявка
#: с повтором тега укладывается в 6), потом пропускает проверку
LOCK_WAIT_REQUEST = 600
LOCK_WAIT_WATCH = 420
#: З1: как часто пробуем взять занятый замок, секунд
LOCK_POLL_SECONDS = 0.5

#: С1: GitHub молчит на список прогонов дольше стольких минут — тревога
#: (лимит запросов снимается за час: дольше — уже не лимит)
API_SILENT_MINUTES = 60

#: С3: потолки длительности прогона по виду, минут (05.10). Цифры — из
#: истории 100 прогонов (#101–#200, 25.09–05.10) с запасом ×1,5 и не ниже
#: ориентира владельца: проба идёт 1–5 мин (берём 20 — как
#: `crawl_hook.PROBE_STALE`); один сайт и скан даты 19–21 мин (→ 45); обход
#: на 2 дня 33–40 мин (→ 75: план растёт); на 6 дней 81–103 мин (→ 140;
#: GitHub сам режет на 150). Вид не узнан — самый длинный потолок
CEILING_MINUTES = {"probe": 20, "site": 45, "date": 45,
                   "full-2": 75, "full-5": 120, "full-6": 140, "schedule": 140,
                   "unknown": 140}
#: С3: прогон ждёт в очереди, хотя перед ним никого, — столько минут терпим
#: (обычно GitHub заводит прогон за минуту)
QUEUE_STUCK_MINUTES = 20
#: С3: заявка отмены исполняется за 1–2 минуты (замер 06.10: 50 секунд); не
#: остановился за столько — тревога
CANCEL_CONFIRM_MINUTES = 10
#: GitHub сам обрывает прогон через столько минут (`timeout-minutes` в
#: crawl.yml) — для слов в строках сторожа
HARD_LIMIT_MINUTES = 150

#: С4а: минут после финиша, которые даём стуку «закончил» дойти до сервера
KNOCK_GRACE_MINUTES = 10
#: С4б: сколько неудачных заборов готового результата терпим до тревоги
PULL_TRIES_BEFORE_ALARM = 2
#: С4б: сколько секунд даём забору (`hook_pull.sh` сам ждёт свой замок 15 мин)
PULL_TIMEOUT_SECONDS = 1800
#: С4г, С6: сколько секунд даём заявке, которую запускает сторож (она ждёт
#: старта до 3 + 2 минут)
ORDER_TIMEOUT_SECONDS = 600
#: С4д: заказ старше стольких часов и не закрыт — тревога (самый длинный
#: обход с ожиданием очереди и забором укладывается в 4 часа)
ORDER_TTL_HOURS = 6

#: С5: через столько минут после слота сторож сверяет, приходила ли плановая
#: заявка. Больше, чем заявка ждёт замок (10), и меньше шага сторожа (15)
SLOT_AUDIT_MINUTES = 12
#: С5: заявка отметилась «пришла» и молчит дольше — её оборвали; сама она,
#: даже с повтором тега, укладывается в 14 минут
SLOT_STARTED_STALE_MINUTES = 20

#: С6: сорвавшийся слот старше стольких часов — заказывать поздно, тревога
MISSED_TTL_HOURS = 6
#: С6 и З3: досрочный заменяет следующий плановый, только если начат не
#: раньше, чем за столько часов до него (владелец 05.10: «около 4 часов»;
#: утренний досрочный вечерний слот не заменит — сайты успеют обновиться)…
EARLY_COVERS_HOURS = 4
#: …плюс запас: между 16:15 и 20:30 — 4 ч 15 мин, а досрочный за сорвавшийся
#: 16:15 (главный пример владельца) сторож может заказать уже в 16:15–16:29.
#: Без запаса он 20:30 не заменил бы. Пары 06:15→16:15 (10 ч) и 20:30→06:15
#: (9 ч 45 мин) запас не задевает
EARLY_COVERS_SLACK_MINUTES = 20

#: Виды прогона, годные в ответ на заказ полного обхода. ВРЕМЕННО здесь
#: «unknown»: прогоны, запущенные до выкладки 06.10, названы просто «Обход
#: телесайтов» (без `run-name`), и полный среди них не отличить. Убрать
#: «unknown» отсюда и подстановку вида из отметки в `lock_verdict`, когда
#: такие прогоны уйдут из списка последних (`crawl_watch.py --check` перестанет
#: показывать прогоны без вида — через два-три дня после выкладки)
FULL_KINDS = ("full", "unknown")


# ── время и отметки ──────────────────────────────────────────────────────────

def _utc(text: str) -> datetime | None:
    """Время GitHub (`2026-10-05T17:30:11Z`, UTC) → время с поясом."""
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def kyiv_at(text: str) -> datetime | None:
    """Отметка `2026-10-05 16:15` (Киев) → время с поясом; не разобрать — None."""
    try:
        return datetime.strptime(str(text), "%Y-%m-%d %H:%M").replace(tzinfo=KYIV)
    except (TypeError, ValueError):
        return None


def stamp(at: datetime) -> str:
    """Время → отметка `ГГГГ-ММ-ДД ЧЧ:ММ` по Киеву (так сторож пишет в память)."""
    return at.astimezone(KYIV).strftime("%Y-%m-%d %H:%M")


def hm(at: datetime | None) -> str:
    """Время → `ЧЧ:ММ` по Киеву для строк сторожа."""
    return at.astimezone(KYIV).strftime("%H:%M") if at else "?"


def clock(mark: str) -> str:
    """Отметка `ГГГГ-ММ-ДД ЧЧ:ММ` → `ЧЧ:ММ` для строк сторожа."""
    return hm(kyiv_at(mark))


# ── список прогонов GitHub ───────────────────────────────────────────────────

class Runs(list):
    """Список прогонов с пометкой, ответил ли GitHub: `ok` False — сеть, 403
    (лимит запросов), не JSON. Сторожу и сверкам заявки хватает пустоты
    списка: пустой — «сверить не с чем» (у репозитория прогонов сотни).
    Пометка нужна только ожиданию старта (З7): «GitHub ответил, а прогона
    нет» и «GitHub не ответил» — разные решения."""
    ok = True

    @classmethod
    def silent(cls) -> "Runs":
        out = cls()
        out.ok = False
        return out


def github_runs(slug: str, limit: int = RUNS_LIMIT, workflow: str = "") -> Runs:
    """Последние прогоны репозитория (`workflow` — только этого файла), один
    запрос. GitHub не ответил — пустой список с `ok` False."""
    where = f"workflows/{workflow}/runs" if workflow else "runs"
    req = urllib.request.Request(
        f"{API}/repos/{slug}/actions/{where}?per_page={limit}",
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "streams-schedule-watch"})
    try:
        with urllib.request.urlopen(req, timeout=20) as answer:
            data = json.loads(answer.read().decode("utf-8"))
    except (OSError, ValueError):
        return Runs.silent()
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        return Runs.silent()
    return Runs(data["workflow_runs"])


def crawl_only(runs: list[dict], slug: str = "") -> list[dict]:
    """Только прогоны workflow обхода этого репозитория — остальные сторож
    не разбирает и не отменяет. Имя репозитория сверяется без учёта регистра:
    GitHub адрес с любым регистром принимает, а в ответе пишет каноническое
    `Newik89/…` — иначе origin с другим написанием отсеял бы все прогоны."""
    out = []
    for r in runs:
        path = (r.get("path") or "").split("@")[0]
        if path != f".github/workflows/{CRAWL_WORKFLOW}":
            continue
        repo = (r.get("repository") or {}).get("full_name")
        if slug and repo and repo.lower() != slug.lower():
            continue
        out.append(r)
    return out


def parse_what(what: str) -> tuple[str, int]:
    """Вид сбора по слову стука / отметки / названия прогона: `proba-2`,
    `probeurl-…` → проба; `site-…`; `date-…`; `full-6` / `days-6` → полный
    на 6 суток. Не узнан — unknown."""
    what = what or ""
    if what.startswith(("proba", "probeurl")):
        return "probe", 0
    if what.startswith("site-"):
        return "site", 0
    if what.startswith("date-"):
        return "date", 0
    m = re.fullmatch(r"(?:full|days)-(\d+)", what)
    if m:
        return "full", int(m.group(1))
    return "unknown", 0


def run_kind(run: dict) -> tuple[str, int]:
    """Вид прогона по его названию: crawl.yml называет прогон `Обход full-6`
    / `Обход proba-2` / `Обход site-…` / `Обход date-…` (`run-name`).
    Плановый cron GitHub (04:17 UTC) — отдельный вид: он почти всегда сразу
    выходит («сегодня уже ходили»), полным обходом его не считаем."""
    if run.get("event") == "schedule":
        return "schedule", 0
    m = re.fullmatch(r"Обход (\S+)", run.get("display_title") or "")
    return parse_what(m.group(1)) if m else ("unknown", 0)


def describe(kind: str, days: int = 0) -> str:
    return {"probe": "проба адреса", "site": "обход одного сайта",
            "date": "скан одной даты",
            "schedule": "запуск по расписанию GitHub"}.get(
        kind, f"обход на {days} сут." if kind == "full" else "обход")


def ceiling(kind: str, days: int = 0) -> int:
    key = f"full-{days}" if kind == "full" else kind
    return CEILING_MINUTES.get(key, CEILING_MINUTES["unknown"])


def active_crawls(runs: list[dict], slug: str = "") -> list[dict]:
    """Прогоны обхода, которые ещё не закончены (идут или ждут очереди)."""
    return [r for r in crawl_only(runs, slug) if (r.get("status") or "") in RUNNING]


def full_runs(runs: list[dict], slug: str = "") -> list[dict]:
    """Прогоны обхода, которые могут быть ответом на заказ полного обхода:
    проба, сайт и скан даты — не в счёт (иначе проба, нажатая за минуту до
    плановой заявки, сходила за её прогон)."""
    return [r for r in crawl_only(runs, slug) if run_kind(r)[0] in FULL_KINDS]


def run_for(order: dict, runs: list[dict]) -> dict | None:
    """Прогон, которым GitHub ответил на заявку: кнопочный запуск
    (`workflow_dispatch`), созданный после заявки. Из нескольких — самый
    ранний после неё: более поздние — уже чужие."""
    edge = order["at"] - timedelta(minutes=MATCH_SLACK_MINUTES)
    ours = []
    for r in runs:
        created = _utc(r.get("created_at") or "")
        if r.get("event") != "workflow_dispatch" or created is None:
            continue
        if created >= edge:
            ours.append((created, r))
    if not ours:
        return None
    ours.sort(key=lambda x: x[0])
    return ours[0][1]


# ── расписание ───────────────────────────────────────────────────────────────

def _slots(day, schedule=SCHEDULE):
    for hhmm, days in schedule:
        h, m = (int(x) for x in hhmm.split(":"))
        yield datetime(day.year, day.month, day.day, h, m, tzinfo=KYIV), days


def slot_for(now: datetime, days: int, schedule=SCHEDULE) -> datetime | None:
    """Плановый слот, к которому относится заявка `days` в `now`
    (±`SLOT_MATCH_MINUTES`); ручной заказ — None."""
    now = now.astimezone(KYIV)
    for shift in (-1, 0, 1):
        for at, d in _slots((now + timedelta(days=shift)).date(), schedule):
            if d == days and abs((now - at).total_seconds()) <= SLOT_MATCH_MINUTES * 60:
                return at
    return None


def next_slot(after: datetime, schedule=SCHEDULE) -> tuple[datetime, int]:
    """Ближайший плановый слот строго после `after`: (время, глубина)."""
    after = after.astimezone(KYIV)
    for shift in (0, 1, 2):
        for at, d in sorted(_slots((after + timedelta(days=shift)).date(), schedule)):
            if at > after:
                return at, d
    raise ValueError("пустое расписание")


def last_slot(now: datetime, schedule=SCHEDULE) -> tuple[datetime, int]:
    """Последний плановый слот не позже `now`: (время, глубина)."""
    now = now.astimezone(KYIV)
    for shift in (0, -1, -2):
        slots = sorted(_slots((now + timedelta(days=shift)).date(), schedule), reverse=True)
        for at, d in slots:
            if at <= now:
                return at, d
    raise ValueError("пустое расписание")


def covers_from(slot_at: datetime) -> datetime:
    """С какого времени начатый досрочный заменяет плановый `slot_at`."""
    return slot_at - timedelta(hours=EARLY_COVERS_HOURS,
                               minutes=EARLY_COVERS_SLACK_MINUTES)


def cron_lines(root: str, python: str, schedule=SCHEDULE) -> list[str]:
    """Строки cron сервера по таблице `SCHEDULE` (подсказка, сам cron живёт
    вне репозитория): `crawl_watch.py --cron`."""
    out = []
    for hhmm, days in schedule:
        h, m = (int(x) for x in hhmm.split(":"))
        out.append(f"{m} {h} * * * cd {root} && {python} scripts/request_crawl.py "
                   f"days {days} >> /var/log/streams-request.log 2>&1")
    out.append(f"*/15 * * * * cd {root} && {python} scripts/crawl_watch.py "
               f">> /var/log/streams-watch.log 2>&1")
    return out


# ── память (записи описаны в шапке, раздел ПАМЯТЬ) ───────────────────────────

def load_json(conn: sqlite3.Connection, key: str) -> dict:
    """Запись памяти сторожа; пустая или битая — пустой словарь."""
    try:
        value = json.loads(db.get_setting(conn, key) or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def save_json(conn: sqlite3.Connection, key: str, value: dict) -> None:
    db.set_setting(conn, key, json.dumps(value, ensure_ascii=False))


def load_state(conn: sqlite3.Connection, order: dict) -> dict:
    """`crawl_watch` для заказа `order`; запись про другой заказ — начинаем
    заново (ключ записи — отметка времени заказа)."""
    state = load_json(conn, "crawl_watch")
    if state.get("order") != order["stamp"]:
        state = {"order": order["stamp"]}
    return state


def save_state(conn: sqlite3.Connection, state: dict) -> None:
    save_json(conn, "crawl_watch", state)


#: всё, что сторож помнит сам, — это стирает кнопка «Сбросить память
#: сторожа». Заказ (`crawl_request`) и отметку «сбор идёт» (`crawl_running`)
#: пишут заявка и стук GitHub — они не память сторожа
WATCH_MEMORY = ("crawl_watch", "crawl_missed", "crawl_early", "crawl_cancel",
                "crawl_slot", "crawl_silent")


def reset_memory(conn: sqlite3.Connection) -> str:
    """Кнопка «Сбросить память сторожа»: стереть `WATCH_MEMORY`. Текущий
    заказ помечается reset — сторож его больше не ведёт, иначе с чистого
    листа он мог бы заново «увидеть» давний срыв и заказать обход. Дальше
    сторож решает только по новым событиям: первая проверка запомнит
    прошедший слот (С5, init), следующий слот пойдёт как обычно.
    Возвращает слова для строки в «Прогонах»."""
    for key in WATCH_MEMORY:
        db.set_setting(conn, key, "")
    order = parse_order(db.get_setting(conn, "crawl_request"))
    if order is None:
        return "память сторожа стёрта; заказов не было"
    save_state(conn, {"order": order["stamp"], "reset": True})
    return (f"память сторожа стёрта; заказ от {order['stamp']} ({order['days']} "
            f"сут.) сторож больше не ведёт — дальше решает только по новым "
            f"событиям")


def note(conn: sqlite3.Connection, text: str, who: str = "сторож") -> None:
    """Строка в «Прогоны» админки: без окна дней она показывается словами
    из поля «режим» (шаблон runs.html)."""
    now = datetime.now(KYIV).strftime("%Y-%m-%d %H:%M")
    conn.execute(
        "INSERT INTO runs (started_at, finished_at, window_days, log) "
        "VALUES (?, ?, NULL, ?)",
        (now, now, json.dumps({"кто": who, "режим": f"{who}: {text}"},
                              ensure_ascii=False)))
    conn.commit()


def missed_record(old: dict, slot: str, days: int, at: str, why: str) -> dict:
    """Новая запись `crawl_missed` — её пишут З4, З6, С4г и С5, все через
    эту функцию. Прежний сорвавшийся слот ещё ждёт решения С6 (state
    missed; так бывает, если GitHub молчал между слотами) — его не теряем:
    один досрочный закроет оба, глубина — большая из двух."""
    record = {"slot": slot, "days": days, "at": at, "why": why, "state": "missed"}
    if old.get("state") == "missed" and old.get("slot") and old["slot"] != slot:
        record["days"] = max(days, int(old.get("days") or 0))
        record["also"] = old["slot"]
        record["why"] = (f"{why}; до него не состоялся и плановый "
                         f"{clock(old['slot'])} — один досрочный закроет оба")
    return record


# ── после сбоя: ОДНА таблица «вид сбоя → шаг» ────────────────────────────────

#: Что сервер делает после сбоя — решается ТОЛЬКО здесь (владелец 06.10).
#: Исполняют шаг: сторож — `crawl_watch.recover`, заявка — `lost_slot`.
#: Шаги:
#:   early — слот записать сорвавшимся (`crawl_missed`); правило С6 закажет
#:           ОДИН досрочный, глубина — большая из сорвавшегося и следующего
#:   retry — один повтор заказа той же глубины (только у ручного заказа)
#:   alarm — только ТРЕВОГА, новых заказов нет до следующего планового слота
#: Вид сбоя — «чей заказ-как сорвался» (`failure_of`). Новый вид сбоя:
#: строка сюда и вызов исполнителя с этим именем там, где сбой замечен; новый
#: шаг — ещё ветка в `crawl_watch.recover` (и в `lost_slot`, если он для
#: плановой заявки). Незнакомый вид — ТРЕВОГА: молча сбой не теряется.
#: Сбои наблюдения — GitHub молчит (С1), отмена не сработала (С3), забрать
#: готовый не вышло (С4б) — заказов не порождают: там всегда ТРЕВОГА.
RECOVERY = {
    # плановый слот (заявка из cron)
    "planned-postponed": "early",       # З4: GitHub молчит, по отметке идёт сбор
    "planned-not-sent": "early",        # З6: тег заявки не ушёл
    "planned-not-requested": "early",   # С5: заявка не запускалась / оборвалась
    "planned-failed": "early",          # С4г: не стартовал, упал, завис
    "planned-expired": "alarm",         # С4д: за 6 ч не закрыт
    # досрочный сторожа — один на слот, дальше только ТРЕВОГА
    "early-refused": "alarm",           # С6: GitHub не принял заявку
    "early-lost": "alarm",              # С2: проверку оборвали до заявки
    "early-failed": "alarm",            # С4г
    "early-expired": "alarm",           # С4д
    # ручной заказ (кнопка витрины) — один повтор
    "manual-failed": "retry",           # С4г
    "manual-expired": "alarm",          # С4д
    "retry-refused": "alarm",           # С4г: повтор не ушёл
    "retry-failed": "alarm",            # С4г: повтор сорвался
    "retry-expired": "alarm",           # С4д
}


def recovery(failure: str) -> str:
    """Шаг после сбоя по таблице `RECOVERY`; незнакомый вид — ТРЕВОГА."""
    return RECOVERY.get(failure, "alarm")


def order_who(state: dict) -> str:
    """Чей заказ для `RECOVERY`: `order_kind`, а повтор ручного — retry."""
    who = order_kind(state)
    return "retry" if who == "manual" and state.get("reordered") else who


def failure_of(state: dict, how: str) -> str:
    """Вид сбоя текущего заказа для `RECOVERY`: чей он (`order_who`) и как
    сорвался (failed, expired)."""
    return f"{order_who(state)}-{how}"


def lost_slot(conn: sqlite3.Connection, failure: str, slot_at: datetime,
              days: int, why: str, now: datetime) -> str:
    """Плановая заявка заметила, что её слот сорвался (З4, З6): шаг по
    `RECOVERY`. early — записать `crawl_missed`, дальше решает сторож (С6);
    иначе — строка ТРЕВОГА. Возвращает шаг."""
    step = recovery(failure)
    if step == "early":
        save_json(conn, "crawl_missed", missed_record(
            load_json(conn, "crawl_missed"), stamp(slot_at), days, stamp(now), why))
    else:
        note(conn, f"ТРЕВОГА — {why}. Сторож новых заказов за этот слот не "
                   f"сделает; следующий плановый пойдёт как обычно")
    return step


# ── З1. общий замок заявки и сторожа ─────────────────────────────────────────

def lock_path() -> Path:
    """Файл общего замка — рядом с базой (папка `data` в git не едет)."""
    return db.db_path().with_name("crawl-order.lock")


def _try_lock(fd: int) -> bool:
    try:
        if os.name == "nt":                 # компьютер владельца (проверки)
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:                               # сервер
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def order_lock(wait: float):
    """Общий замок заявки и сторожа (З1): `with order_lock(…) as held`.
    Заявка и сторож стартуют из cron в одну минуту (06:15, 16:15, 20:30) —
    без замка сторож, заказавший досрочный именно в эту минуту, и плановая
    заявка не видели друг друга, выходило два обхода подряд. Второй процесс
    ЖДЁТ первого до `wait` секунд и читает базу уже с его итогом. `held`
    False — не дождались: что делать, решает вызывающий (заявка идёт без
    замка, сторож пропускает проверку). Замок — блокировка открытого файла:
    держится, только пока жив процесс, «забытого» замка не бывает."""
    fd = os.open(str(lock_path()), os.O_RDWR | os.O_CREAT)
    held = False
    try:
        deadline = time.monotonic() + wait
        while True:
            if _try_lock(fd):
                held = True
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(LOCK_POLL_SECONDS)
        yield held
    finally:
        if held:
            _unlock(fd)
        os.close(fd)


# ── З3. слот заменён досрочным ───────────────────────────────────────────────

def early_covers(early: dict | None, slot_at: datetime, runs: list[dict],
                 slug: str = "") -> tuple[str, str]:
    """Что с досрочным, который заменяет плановый `slot_at` (З3): (итог,
    слова). done — начат не раньше окна `covers_from` и ДОШЁЛ до конца:
    плановый выполнен досрочно; running — ещё идёт: «выполнен» говорить
    рано, но идёт полный не меньшей глубины (глубина досрочного — большая из
    двух слотов); no — начат слишком рано, упал или не стартовал: плановый
    идёт как обычно; пусто — досрочного про этот слот нет (или его заявка
    так и не ушла).
    `runs` пустой — GitHub молчит: верим памяти сторожа. Память «done» верна
    и тогда, когда прогон уже выпал из списка последних."""
    if not early or early.get("replaces") != stamp(slot_at):
        return "", ""
    ordered = kyiv_at(early.get("ordered_at", ""))
    if ordered is None:
        return "", ""
    run = run_for({"at": ordered}, full_runs(runs, slug))
    remembered = early.get("state") == "done"
    started = ((_utc(run.get("run_started_at") or run.get("created_at") or "")
                if run else None)
               or (kyiv_at(early.get("started", "")) if remembered else None)
               or ordered)
    if started < covers_from(slot_at):
        return "no", (f"досрочный обход начался в {hm(started)} — раньше, чем за "
                      f"{EARLY_COVERS_HOURS} ч до планового {hm(slot_at)}, сайты "
                      f"успели обновиться: плановый идёт как обычно")
    number = (run.get("run_number") if run else early.get("run")) or "?"
    done = (f"плановый обход {hm(slot_at)} ({early.get('replaces_days')} сут.) "
            f"выполнен досрочно в {hm(started)} — обход на "
            f"{early.get('days')} сут. #{number} ")
    if run is not None:
        if (run.get("status") or "") in RUNNING:
            return "running", (
                f"плановый обход {hm(slot_at)} ({early.get('replaces_days')} сут.) "
                f"не заказываю: досрочный обход #{number} на {early.get('days')} "
                f"сут., начатый в {hm(started)}, ещё идёт — он соберёт и эти дни. "
                f"Не дойдёт до конца — будет тревога")
        if run.get("conclusion") == "success":
            return "done", done + "дошёл до конца; заново не заказываю"
        return "no", (f"досрочный обход в {hm(started)} кончился "
                      f"«{run.get('conclusion') or '?'}» — плановый "
                      f"{hm(slot_at)} идёт как обычно")
    if remembered:
        where = ("прогон уже не в списке последних" if runs
                 else "GitHub не ответил")
        return "done", done + (f"дошёл до конца (по памяти сторожа, {where}); "
                               f"заново не заказываю")
    how = "так и не стартовал" if runs else "не подтверждён (GitHub не ответил)"
    return "no", (f"досрочный обход в {hm(started)} {how} — плановый "
                  f"{hm(slot_at)} идёт как обычно")


# ── З4. отметка «сбор идёт» ──────────────────────────────────────────────────

def lock_verdict(busy: dict, days: int, runs: list[dict], now: datetime,
                 slug: str = "") -> tuple[str, str]:
    """Плановая заявка, а отметка говорит «сбор идёт» (З4): (решение, слова).
    clear — на GitHub прогонов нет, отметка ложная: снять и заказать; skip —
    идёт или ждёт полный обход не меньшей глубины, он соберёт и эти дни;
    behind — идёт что-то меньшее (проба, сайт, дата, полный мельче):
    заказать, встанет в очередь; postpone — GitHub не ответил, отметке
    верим, а слот отдаём сторожу.
    `runs` пустой — значит, GitHub не ответил."""
    what = busy.get("what", "")
    if not runs:
        if crawl_hook.queue_behind(busy, "days", str(days)):
            return "behind", (f"по отметке идёт «{what}», GitHub не ответил — "
                              f"плановый обход {days} сут. всё равно заказываю, "
                              f"он встанет в очередь")
        return "postpone", (f"плановый обход {days} сут. отложен: по отметке сбор "
                            f"уже {busy.get('state', 'идёт')} с {busy.get('since', '?')} "
                            f"(«{what}»), а GitHub не ответил, проверить нельзя. "
                            f"Сторож сверится на своей проверке (раз в 15 мин) и "
                            f"закажет обход, если он нужен")
    found = [(run_kind(r), r) for r in active_crawls(runs, slug)]
    fresh = (busy.get("state") == "заказан"
             and busy.get("age", 10 ** 9) < MARK_FRESH_MINUTES * 60)
    if not found and fresh:
        # заявку только что подали — GitHub её ещё не показал
        found = [(parse_what(what), None)]
    if not found:
        return "clear", (f"отметка «сбор {busy.get('state', 'идёт')}» («{what}» с "
                         f"{busy.get('since', '?')}) снята — на GitHub прогонов "
                         f"нет, она ложная. Заказываю плановый обход {days} сут.")
    hint = parse_what(what)
    for (kind, d), r in found:
        if kind == "unknown":
            kind, d = hint          # ВРЕМЕННО, см. FULL_KINDS: вид — из отметки
        if kind == "full" and d >= days:
            where = (f"#{r.get('run_number')} " if r else "")
            how = ("заказан" if r is None else
                   "идёт" if r.get("status") == "in_progress" else "ждёт очереди")
            return "skip", (f"плановый обход {days} сут. не нужен — на GitHub уже "
                            f"{how} обход {where}на {d} сут., он соберёт и эти дни")
    names = ", ".join(describe(*k) for k, _ in found)
    return "behind", (f"на GitHub идёт {names} — плановый обход {days} сут. "
                      f"заказываю, он встанет в очередь следом")


# ── З7. ждём старта ──────────────────────────────────────────────────────────

def wait_for_start(order: dict, slug: str, kinds: tuple,
                   seconds: int = START_MINUTES * 60,
                   sleep=time.sleep) -> tuple[dict | None, bool]:
    """Ждём, пока GitHub не заведёт прогон на заявку (З7): (прогон, ответил
    ли GitHub на последний опрос). `kinds` — виды прогона, годные в ответ
    (`run_kind`): на заявку по дням — полный обход, на скан даты — скан
    даты, а не проба, нажатая минутой раньше. GitHub молчит — «не стартовал»
    утверждать нельзя, и вызывающий тег не повторяет."""
    waited = 0
    while True:
        listed = github_runs(slug, workflow=CRAWL_WORKFLOW)
        run = run_for(order, [r for r in listed if run_kind(r)[0] in kinds])
        if run is not None or waited >= seconds:
            return run, listed.ok
        sleep(START_POLL_SECONDS)
        waited += START_POLL_SECONDS


# ── С3. зависшие прогоны ─────────────────────────────────────────────────────

def effective_start(run: dict, runs: list[dict]) -> datetime | None:
    """Когда прогон на самом деле пошёл. `run_started_at` у GitHub — время
    создания, даже если прогон час ждал в очереди за другим (`concurrency`:
    #118 «шёл» 36 мин, из них 34 ждал #117). Поэтому старт — не раньше
    конца предыдущих прогонов обхода; ждёт за ещё идущим — None (он не
    завис, зависнуть может тот, что впереди)."""
    created = _utc(run.get("created_at") or "")
    start = _utc(run.get("run_started_at") or "") or created
    if created is None or start is None:
        return None
    for o in runs:
        if o is run or o.get("id") == run.get("id"):
            continue
        oc = _utc(o.get("created_at") or "")
        if oc is None or oc >= created:
            continue
        if (o.get("status") or "") in RUNNING:
            return None
        end = _utc(o.get("updated_at") or "")
        if end and end > start:
            start = end
    return start


def stuck(runs: list[dict], now: datetime, slug: str = "") -> list[dict]:
    """Зависшие прогоны обхода: идёт дольше потолка своего вида или стоит в
    очереди дольше `QUEUE_STUCK_MINUTES`, хотя впереди никого.
    [{run, kind, days, minutes, limit, why}]."""
    crawls = crawl_only(runs, slug)
    out = []
    for r in crawls:
        status = r.get("status") or ""
        if status not in RUNNING:
            continue
        start = effective_start(r, crawls)
        if start is None:
            continue
        minutes = (now - start).total_seconds() / 60
        kind, days = run_kind(r)
        if status == "in_progress":
            limit = ceiling(kind, days)
            why = f"идёт {minutes:.0f} мин, а такой обычно укладывается в {limit}"
        else:
            limit = QUEUE_STUCK_MINUTES
            why = (f"{minutes:.0f} мин стоит в очереди, хотя перед ним "
                   f"ничего не идёт")
        if minutes > limit:
            out.append({"run": r, "kind": kind, "days": days,
                        "minutes": minutes, "limit": limit, "why": why})
    return out


def cancel_decisions(runs: list[dict], now: datetime, cancels: dict,
                     slug: str = "", own_run_id=None,
                     own_words: str = "") -> list[tuple[str, str, str]]:
    """Отмена зависших (С3): [(действие, id прогона, слова)]. cancel — подать
    заявку отмены; confirmed — GitHub подтвердил, прогон остановлен; alarm —
    прогон не остановился за `CANCEL_CONFIRM_MINUTES` после заявки (тревога
    один раз); forget — прогона уже нет в списке, забыть.
    `cancels` — память `crawl_cancel`: прогон, который в ней есть, второй
    заявки отмены не получает. `own_run_id` — прогон текущего заказа сторожа,
    `own_words` — что сторож сделает с этим заказом дальше (С4г)."""
    by_id = {str(r.get("id")): r for r in crawl_only(runs, slug)}
    out = []
    for rid, c in cancels.items():
        r = by_id.get(rid)
        number = c.get("number")
        if r is None:
            out.append(("forget", rid, ""))
            continue
        if (r.get("status") or "") not in RUNNING:
            out.append(("confirmed", rid,
                        f"прогон #{number} остановлен (итог «{r.get('conclusion') or '?'}»)"))
            continue
        asked = kyiv_at(c.get("at", ""))
        since = (now - asked).total_seconds() / 60 if asked else 0
        if since >= CANCEL_CONFIRM_MINUTES and not c.get("alarmed"):
            out.append(("alarm", rid,
                        f"ТРЕВОГА — прогон #{number} не остановился за {since:.0f} мин "
                        f"после заявки отмены; GitHub всё равно оборвёт его через "
                        f"{HARD_LIMIT_MINUTES} мин после старта"))
    for s in stuck(runs, now, slug):
        r = s["run"]
        rid = str(r.get("id"))
        if rid in cancels or not re.fullmatch(r"\d+", rid):
            continue
        what = describe(s["kind"], s["days"])
        after = (own_words if own_run_id is not None and str(own_run_id) == rid
                 else "он мешал очереди обходов")
        out.append(("cancel", rid,
                    f"прогон #{r.get('run_number')} ({what}) завис: {s['why']} — "
                    f"отменяю его, {after}"))
    return out


def send_cancel(cancels: dict, run: dict, now: datetime) -> tuple[bool, str]:
    """Заявка отмены прогона — одна на сторожа (С3) и кнопку «Остановить
    зависший»: тег `btn-cancel-<id>-<время>`, исполняет `queue.yml`.
    Записывается в `cancels` (память `crawl_cancel`) и неушедшая заявка:
    сторож этому прогону второй не шлёт, а остановку сверяет (С3).
    (ушла ли, ответ git)."""
    rid = str(run.get("id"))
    if not re.fullmatch(r"\d+", rid):
        return False, "номер прогона не из цифр — отменять не буду"
    ok, answer = trigger.push_request_tag("cancel", rid)
    cancels[rid] = {"at": stamp(now), "number": run.get("run_number") or "?",
                    "alarmed": not ok}
    return ok, answer


# ── С4. текущий заказ ────────────────────────────────────────────────────────

def parse_order(raw: str) -> dict | None:
    """`обход 6 сут.|2026-10-02 06:15` → {"days": 6, "at": <Киев>, "stamp": …}."""
    if not raw or "|" not in raw:
        return None
    head, mark = raw.split("|", 1)
    try:
        days = int(head.split()[1])
        at = datetime.strptime(mark.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=KYIV)
    except (IndexError, ValueError):
        return None
    return {"days": days, "at": at, "stamp": mark.strip()}


def order_kind(state: dict) -> str:
    """Чей заказ — от этого зависит, что делать при срыве (С4г): early —
    досрочный заказ сторожа; planned — плановый (пришёл в слот); manual —
    ручной (кнопка витрины не в слот, повтор ручного)."""
    if state.get("early"):
        return "early"
    return "planned" if state.get("slot") else "manual"


def decide(order: dict, run: dict | None, now: datetime, state: dict,
           result: str) -> tuple[str, str]:
    """Что с заказом сейчас (С4): (вердикт, слова). closed — по заказу всё
    решено раньше (забран либо сорвался и обработан); expired — заказ старше
    `ORDER_TTL_HOURS` и не закрыт (С4д); wait — рано судить (С4а); pull —
    готов, результат на GitHub, на сервере нет (С4б); done — готов и на
    сервере либо результата не оставил (С4в); failed — не стартовал за
    `START_MINUTES` или кончился не успехом (С4г).
    `result` — судьба результата прогона (`result_state`)."""
    if state.get("done") or state.get("failed") or state.get("reset"):
        return "closed", "по заказу всё решено раньше"
    age = (now - order["at"]).total_seconds() / 60
    if age > ORDER_TTL_HOURS * 60:
        return "expired", f"заказ {order['stamp']} старше {ORDER_TTL_HOURS} ч и не закрыт"
    if run is None:
        if age < START_MINUTES:
            return "wait", f"заявка {order['stamp']} ушла, ждём старта ({age:.0f} мин)"
        return "failed", f"обход не стартовал за {age:.0f} мин после заявки {order['stamp']}"
    number = run.get("run_number")
    if (run.get("status") or "") in RUNNING:
        started = _utc(run.get("run_started_at") or run.get("created_at") or "") or now
        return "wait", f"прогон #{number} идёт {(now - started).total_seconds() / 60:.0f} мин"
    conclusion = run.get("conclusion") or "?"
    if conclusion != "success":
        return "failed", f"прогон #{number} кончился «{conclusion}»"
    finished = _utc(run.get("updated_at") or "") or now
    since = (now - finished).total_seconds() / 60
    if since < KNOCK_GRACE_MINUTES:
        return "wait", (f"прогон #{number} готов {since:.0f} мин назад — "
                        f"даём стуку {KNOCK_GRACE_MINUTES} мин")
    if result == "pending":
        return "pull", (f"прогон #{number} готов, результат на GitHub, а на "
                        f"сервере нет (стук не дошёл) — забираю сам")
    if result == "picked":
        return "done", f"прогон #{number} готов и забран по стуку"
    if result == "none":
        return "done", (f"прогон #{number} прошёл без результата (пропуск "
                        f"«сегодня уже ходили») — забирать нечего")
    return "wait", f"прогон #{number} готов, но метку «собрано» сверить не вышло"


def _collected(text: str) -> datetime | None:
    """Метка «собрано» из games.json (UTC, пишет parse_live)."""
    try:
        raw = json.loads(text).get("собрано") or ""
        return datetime.strptime(raw, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def result_state(root, started: datetime) -> str:
    """Судьба результата прогона, стартовавшего в `started` (UTC): picked —
    «собрано» на сервере не старше старта (результат уже забран); pending —
    такое «собрано» есть только на GitHub (стук не дошёл); none — ни там, ни
    там (прогон результата не оставил); unknown — GitHub не ответил.
    Сравниваем метку результата, а не коммиты: на GitHub между обходами
    ложатся и правки кода, и словари — по ним «забрано ли» не понять
    (02.10 сторож в --check трижды хотел забрать давно забранный #161)."""
    edge = started - timedelta(minutes=MATCH_SLACK_MINUTES)
    try:
        local = _collected((root / "results" / "games.json").read_text(encoding="utf-8"))
    except OSError:
        local = None
    if local and local >= edge:
        return "picked"
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "main"], capture_output=True,
                       text=True, cwd=root, timeout=60, check=True)
        shown = subprocess.run(["git", "show", "origin/main:results/games.json"],
                               capture_output=True, text=True, cwd=root,
                               timeout=60, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    remote = _collected(shown)
    if remote and remote >= edge:
        return "pending"
    return "none"


# ── С5. приходила ли плановая заявка на слот ─────────────────────────────────

def slot_audit(seen: dict, missed: dict, early: dict, now: datetime,
               schedule=SCHEDULE) -> tuple[str, dict, str]:
    """Приходила ли плановая заявка на последний прошедший слот (С5):
    (действие, запись, слова). Заявка первым делом пишет `crawl_slot` (З2):
    записи про слот нет — cron не сработал или сервер был выключен; запись
    «started» и тишина — заявку оборвали.
    init — памяти ещё нет (первая проверка после выкладки): запомнить слот,
    ничего не делать; seen — слот закрыт и без заявки (выполнен досрочно
    либо уже записан сорвавшимся): запомнить; missed — слот сорвался:
    {slot, days, at} для `crawl_missed` (время срыва — время слота: давний
    срыв даст в С6 тревогу «поздно», а не заказ), что делать — решает
    таблица `RECOVERY` («planned-not-requested»); none — всё в порядке или
    рано судить."""
    at, days = last_slot(now - timedelta(minutes=SLOT_AUDIT_MINUTES), schedule)
    slot = stamp(at)
    mark = {"slot": slot, "days": days, "at": stamp(now)}
    known = str(seen.get("slot") or "")
    if not known:
        return "init", dict(mark, state="init"), ""
    if known > slot:
        # заявку запускали вручную чуть раньше следующего слота — про
        # прошедший запись уже затёрта, он был сверен в свою проверку
        return "none", {}, ""
    if known == slot:
        if seen.get("state") != "started":
            return "none", {}, ""
        begun = kyiv_at(seen.get("at", "")) or at
        if (now - begun).total_seconds() < SLOT_STARTED_STALE_MINUTES * 60:
            return "none", {}, ""
        why = (f"плановая заявка {hm(at)} началась в {hm(begun)} и оборвалась "
               f"(сервер перезагрузился или заявка упала)")
    else:
        why = (f"плановая заявка {hm(at)} не запускалась (сервер был выключен "
               f"или cron не сработал)")
    if early.get("replaces") == slot:
        if early.get("state") in ("ordering", "ordered"):
            return "none", {}, ""           # досрочный за этот слот ещё в работе
        begun = kyiv_at(early.get("started") or early.get("ordered_at") or "")
        if early.get("state") == "done" and begun and begun >= covers_from(at):
            return "seen", dict(mark, state="early"), ""
    if missed.get("slot") == slot or early.get("for") == slot:
        return "seen", dict(mark, state="audited"), ""
    return "missed", {"slot": slot, "days": days, "at": slot}, why


# ── С6. сорвавшийся слот: нужен ли досрочный ─────────────────────────────────

def plan_early(missed: dict, runs: list[dict], now: datetime,
               early: dict, last_order: dict | None, last_done: bool = False,
               skip_ids=(), slug: str = "",
               schedule=SCHEDULE) -> tuple[str, dict, str]:
    """Сорвавшийся плановый слот (С6): (решение, заказ, слова). Решения — в
    том же порядке, что проверки: none — решать нечего либо досрочный за
    этот слот уже был (один на слот); late — сорвался больше
    `MISSED_TTL_HOURS` назад, только тревога; drop — после него уже заказан
    обход не меньшей глубины; covered — такой обход сейчас идёт или ждёт
    очереди; collected — такой обход уже успешно завершился после слота (или
    за час до него — то же правило «1 час», что у заявки); order — заказать
    сейчас обход глубиной max(сорвавшийся, следующий плановый).
    `last_done` — память сторожа: последний заказ `last_order` дошёл и
    забран. Ей верим, даже если прогона уже нет в списке последних.
    `skip_ids` — прогоны, которые сторож отменяет: они не в счёт."""
    if missed.get("state") != "missed":
        return "none", {}, ""
    slot = missed.get("slot", "")
    mdays = int(missed.get("days") or 0)
    at = kyiv_at(missed.get("at", "")) or now
    slot_hm = (f"{clock(missed['also'])} и {clock(slot)}" if missed.get("also")
               else clock(slot))
    if early.get("for") == slot:
        return "none", {}, f"досрочный за плановый {slot_hm} уже заказывали"
    if (now - at).total_seconds() > MISSED_TTL_HOURS * 3600:
        return "late", {}, (f"ТРЕВОГА — плановый обход {slot_hm} ({mdays} сут.) так и "
                            f"не состоялся, а прошло больше {MISSED_TTL_HOURS} ч — "
                            f"досрочно уже не заказываю, ждём следующего планового")
    if last_order and last_order["at"] > at and last_order["days"] >= mdays:
        return "drop", {}, (f"плановый обход {slot_hm} не состоялся, но после него "
                            f"уже заказан обход на {last_order['days']} сут. в "
                            f"{hm(last_order['at'])} — он и соберёт")
    skip = {str(x) for x in skip_ids}
    for r in active_crawls(runs, slug):
        if str(r.get("id")) in skip:
            continue
        kind, d = run_kind(r)
        if kind == "full" and d >= mdays:
            return "covered", {}, (f"плановый обход {slot_hm} не состоялся, но на "
                                   f"GitHub уже идёт обход #{r.get('run_number')} на "
                                   f"{d} сут. — он соберёт эти дни, досрочно не заказываю")
    since = (kyiv_at(slot) or at) - timedelta(hours=crawl_hook.RECENT_HOURS)
    if (last_done and last_order and last_order["at"] >= since
            and last_order["days"] >= mdays):
        return "collected", {}, (
            f"плановый обход {slot_hm} не состоялся, но обход на "
            f"{last_order['days']} сут., заказанный в {hm(last_order['at'])}, уже "
            f"дошёл и забран (по памяти сторожа) — эти дни собраны, досрочно "
            f"не заказываю")
    for r in crawl_only(runs, slug):
        kind, d = run_kind(r)
        end = _utc(r.get("updated_at") or "")
        if (kind == "full" and d >= mdays and (r.get("status") or "") == "completed"
                and r.get("conclusion") == "success" and end and end >= since):
            return "collected", {}, (
                f"плановый обход {slot_hm} не состоялся, но обход "
                f"#{r.get('run_number')} на {d} сут. уже успешно завершился в "
                f"{hm(end)} — эти дни собраны, досрочно не заказываю")
    nxt, ndays = next_slot(now, schedule)
    depth = max(mdays, ndays)
    order = {"for": slot, "for_days": mdays, "days": depth,
             "replaces": stamp(nxt), "replaces_days": ndays}
    head = (f"плановый обход {slot_hm} ({mdays} сут.) не состоялся — заказываю "
            f"сейчас обход на {depth} сут. ")
    if now >= covers_from(nxt):
        return "order", order, head + (
            f"вместо следующего планового {hm(nxt)} ({ndays} сут.). "
            f"Если этот дойдёт до конца, в {hm(nxt)} повторять не буду")
    # до следующего слота дальше окна «досрочно» — обещать его пропуск нельзя
    return "order", order, head + (
        f"(ближайший плановый {hm(nxt)} на {ndays} сут. — досрочно). До "
        f"{hm(nxt)} больше {EARLY_COVERS_HOURS} ч, сайты успеют обновиться, "
        f"поэтому в {hm(nxt)} плановый пойдёт как обычно")

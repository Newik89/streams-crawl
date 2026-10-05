# -*- coding: utf-8 -*-
"""Сторож заказа обхода: сервер сам доводит КАЖДЫЙ заказанный им сбор до
конца или зовёт владельца (слово владельца 02.10, 05.10 и 06.10.2026).

КАК ИДЁТ СБОР. Cron сервера в слот (`SCHEDULE`) запускает заявку
(`scripts/request_crawl.py`) → она пушит тег → `queue.yml` на GitHub запускает
обход (`crawl.yml`, 30–90 минут) → обход стучит серверу «начал» и «закончил»
(`app/crawl_hook`) → сервер забирает результат. Кнопки админки и витрины
заказывают так же. Каждый заказ кладётся в КНИГУ ЗАКАЗОВ (`add_order`, по
записи на заказ). Раз в 15 минут cron запускает сторожа
(`scripts/crawl_watch.py`): он смотрит список прогонов GitHub и доводит до
итога каждый открытый заказ книги.
Главное слово владельца: сорвавшийся плановый сбор НЕ догоняем тем же окном —
сторож один раз заказывает ближайший плановый досрочно; не вышло и это —
только ТРЕВОГА (строка «сторож: ТРЕВОГА — …» в «Прогонах» админки), новых
заказов нет до следующего слота. Ничто не кончается молча: у каждого заказа
итог один из трёх — дошёл, заменён (досрочным или повтором), ТРЕВОГА.
ЧТО ДЕЛАТЬ ПОСЛЕ СБОЯ решает ОДНА таблица — `RECOVERY` («вид сбоя → шаг»:
досрочный, повтор или ТРЕВОГА); правила ниже лишь замечают сбой и зовут её.

ВИДЫ ЗАКАЗОВ (`order_kind`; вид записи книги — `what`):
  вид      кто заказывает                       потолок   срыв →            потом
  planned  cron в слот (`full-N`)               75 / 140  досрочный (С6)    ТРЕВОГА
  early    сторож за сорвавшийся слот           140       ТРЕВОГА           —
  manual   кнопки «2 дня»/«6 дней» админки и    75 / 140  один повтор        ТРЕВОГА
           витрины (друзья), «Заказать сбор»
  date     скан даты (`date-…`, админка/друзья) 45        один повтор        ТРЕВОГА
  site     «Обойти сайт» на GitHub (`site-…`)   45        один повтор        ТРЕВОГА
  server   «Обойти сайт» на сервере (`server-…`) 45       ТРЕВОГА (к сайту не чаще раза в сутки)
  Потолок — минут хода прогона (`CEILING_MINUTES`; у server — без итога).
  Короткие (date, site) повторяются один раз и больше к сайтам не ходят.
  Проба адреса в книгу не идёт: её только отменяет С3, если повисла.
ОКНО ДНЕЙ. Полный обход собирает дни [с, по]: `full-6` — 1…6, будущий
`full-6-from3` — 3…6 («добор дней», следующий пакет). «Не меньшей глубины»
везде значит «окна прогонов вместе накрывают нужное окно» (`window`,
`covered`): «2 дня» и «6 дней с 3-го» вместе закрывают слот на 6 дней.
ВРЕМЯ. Внутри сторожа всё — в UTC; по Киеву — только слоты, отметки в
памяти и слова (см. раздел «время и отметки»): в ночь перевода часов
пороги не сдвигаются.

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
      отметка ложная, снимаем и идём дальше; идёт полный, чьё окно (вместе
      с прошедшими за час) накрывает слот → выходим; идёт меньшее (проба,
      сайт, дата, полный мельче) → идём дальше, обход встанет в очередь;
      GitHub не ответил → отметке верим, слот записываем сорвавшимся
      (`crawl_missed`) и выходим. → 0.
  З5. Правило «1 час»: за последний час полный не меньшей глубины уже собран
      или заказан (и не сорвался) → выходим. → 0.
  З6. Шлём тег-заявку: точно не ушла → слот записываем сорвавшимся и
      выходим (0); git не ответил вовремя («могла дойти») или ушла →
      записываем заказ (`crawl_request` и книга заказов) — дошёл ли, решат
      З7 и С4. → 1.
  З7. Ждём старта 3 минуты (`wait_for_start`): прогон появился → строка
      «пошёл»; нет → строка, что именно видно (GitHub молчит / пересылка
      тега `queue.yml` идёт, переслала, упала или её нет — `forwarding`).
      Тег НЕ повторяем никогда: опоздавший первый тег и повтор дали бы два
      обхода. Не стартовал за 10 минут (`START_GIVEUP_MINUTES`; худший замер
      задержки — 62 с) → сторож сочтёт заказ сорвавшимся (С4г) и закажет
      замену по таблице RECOVERY. → 0 новых.

ПРАВИЛА СТОРОЖА — в том же порядке, что шаги в `crawl_watch.tick`
(что случилось → что делаем → сколько обходов закажет сторож):
  С1. GitHub не ответил на список прогонов → проверку пропускаем; молчит
      час подряд → одна ТРЕВОГА; снова ответил → строка «отбой». → 0.
  С2. Прошлую проверку оборвали посреди заказа досрочного (перезагрузка
      сервера): заявка успела уйти → следим за ней как за досрочным; не
      успела → ТРЕВОГА. → 0.
  С3. Прогон завис (ИДЁТ дольше потолка своего вида) → одна заявка отмены
      на прогон; заявка точно не ушла или прогон не остановился за 10
      минут → ТРЕВОГА. Прогон ждёт очереди, хотя впереди никого, → НЕ
      отменяем (к сайтам он не ходил, новый встал бы туда же): 20 минут —
      строка-предупреждение, 60 — одна ТРЕВОГА. → 0.
  С4. КАЖДЫЙ открытый заказ книги — своей записью, новый заказ слежку за
      прежним не вытесняет (`decide`; сайт на сервере — `decide_server`):
      а) рано судить (ждём старта, обход идёт, ждём стука) → ждём. → 0;
      б) готов, результат на GitHub, а в базу сервера не влит (метка заливки
         своей папки — `import_key`) → запускаем забор (отдельной службой,
         как по стуку); два забора не принесли → ТРЕВОГА, пробуем дальше. → 0;
      в) готов и влит в базу (у всех видов, и у короткого) → закрываем. → 0;
      г) сорвался (не стартовал за 10 минут, кончился не успехом, завис и
         отменяется) → закрываем заказ; что дальше — `RECOVERY` по виду
         (ВИДЫ ЗАКАЗОВ): ПЛАНОВЫЙ → слот сорвавшимся, решает С6 (0);
         ДОСРОЧНЫЙ, СЕРВЕРНЫЙ → ТРЕВОГА (0); РУЧНОЙ, ДАТА, САЙТ → один
         повтор той же заявки (1), сорвался и повтор → ТРЕВОГА (0);
      д) за 6 часов заказ так и не закрыт → ТРЕВОГА, следить перестаём
         (досрочный считается сорвавшимся). → 0.
  С5. Плановая заявка на последний прошедший слот не запускалась (сервер был
      выключен, cron не сработал) или оборвалась (`slot_audit`) → слот
      записываем сорвавшимся, решает С6. → 0.
  С6. Есть сорвавшийся слот (`plan_early`): досрочный за него уже был →
      ничего; сорвался больше 6 часов назад → ТРЕВОГА «поздно»; после него
      уже заказан обход не меньшей глубины → ничего; его дни уже успешно
      собраны (по списку GitHub; память «дошёл» о последнем заказе — тоже
      довод) → ничего; их собирает идущий прогон → ЖДЁМ его итога, слот не
      закрываем (дойдёт — «собрано», упадёт — досрочный, затянется —
      «поздно»); иначе → ОДИН досрочный: глубина — большая из сорвавшегося и
      следующего планового; начат не раньше чем за 4 ч 20 мин до следующего
      слота и дошёл — тот слот пропускается (З3). Заявка досрочного не ушла
      → ТРЕВОГА. → не больше 1 на слот.
ИТОГО на один плановый слот — не больше двух обходов, без оговорок: один
тег от заявки (повтора тега нет) и один досрочный от сторожа (одна заявка,
тоже без повтора). На заказ кнопкой — не больше двух: заказ и один повтор.

ПАМЯТЬ — настройки в таблице `settings`. Вся она описана здесь; любую запись
можно стереть вручную — сторож начнёт по ней с чистого листа.
  crawl_request — последний заказ полного обхода, строка
      `обход 6 сут.|2026-10-06 06:15`. Пишут: заявка (З6), кнопка витрины
      (`web._dispatch`). Читают: сторож (С2, С6), правило «1 час» (З5,
      `crawl_hook.fresh_full`), панель «Здоровье». Не стирается —
      переписывается следующим заказом. Следит за заказами книга, не она.
  crawl_order — книга заказов: ПО ЗАПИСИ НА КАЖДЫЙ ЗАКАЗ, ключ
      `crawl_order:<id>`, JSON {id, what, order, slot, who, early, retry_of,
      reordered, done, failed, reset, pulls}. id — свой у каждого заказа:
      отметка с секундами и кто заказал (`2026-10-06 16:30:12|кнопка`), так
      два заказа одной минуты не путаются; what — вид (`full-6`,
      `date-2026-10-07`, `site-nova.bg`, `server-mojtv.hr`); order — отметка
      заказа до минуты (как в `crawl_request`); slot — плановый слот или
      слот, за который досрочный (пусто — ни то ни другое); who — cron,
      кнопка, владелец, сторож…; early — досрочный сторожа; retry_of — id
      заказа, который этот повторяет (по нему сторож находит СВОЙ повтор);
      reordered — это повтор; done — дошёл и результат влит в базу;
      failed — сорвался, по нему всё решено; reset — память сброшена
      кнопкой, сторож его не ведёт; pulls — сколько заборов запускал
      сторож. Пишут: заявка и кнопки (`add_order`), сторож. Читают:
      сторож (С4, С6), правило «1 час» (`order_dead`), блок админки.
      Закрытые записи уходят через `ORDER_KEEP_HOURS` (`prune_orders`).
      Прежняя версия помнила один заказ в `crawl_watch` — её итог один
      раз переносится в книгу (`LEGACY_KEY`, `full_order_record`).
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
  crawl_missed — сорвавшийся плановый слот, по которому надо решить, нужен
      ли досрочный (З4, З6, С4г, С5 → С6), JSON {slot, days, at, why, state,
      also}. at — когда сорвался; state: missed — ждёт решения С6; handled —
      досрочный заказан (или уже был); late, drop, covered, collected —
      досрочный не нужен (почему — `plan_early`); failed — заявка досрочного
      не ушла. also — прежний слот, который ещё ждал решения, когда сорвался
      этот: один досрочный закроет оба, глубина — большая (`missed_record`).
      covered_by — id прогонов, чьего итога слот ждёт (state при этом
      остаётся missed; строка «жду его итога» — одна на прогоны).
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
  crawl_queue — прогоны, ждущие очереди при пустой очереди (С3), JSON
      {id прогона: {last, warned, alarmed}}. last — когда сторож последний
      раз видел его ждущим: от этой отметки считается ход прогона, когда он
      пойдёт (`stuck`; у GitHub `run_started_at` — время создания); warned,
      alarmed — строка и ТРЕВОГА уже были. Пишет и читает сторож; запись
      уходит, когда прогон закончился или выпал из списка.
  crawl_silent — с какого времени GitHub молчит (С1), JSON {since, alarmed}.
      Пишет и читает сторож; стирается, когда GitHub ответил.
Кнопка «Сбросить память сторожа» (`reset_memory`) стирает всё, что сторож
помнит сам (`WATCH_MEMORY`), а открытые заказы книги помечает reset. Заказ
(`crawl_request`) и отметку «сбор идёт» (`crawl_running`) она не трогает.
Общий замок заявки, сторожа и кнопок «Остановить»/«Сбросить» — файл
`data/crawl-order.lock` (`order_lock`).
Экстренные кнопки владельца — `app/emergency.py`: своей логики у них нет.

Список прогонов — из ОТКРЫТОГО API GitHub: репозиторий публичный, ключ не
нужен, лимит 60 запросов в час на адрес. Сторож делает один запрос за
проверку, заявка — один на сверку и до одиннадцати, пока ждёт старта.
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
#: workflow пересылки тега: тег-заявка → его прогон → `crawl.yml` (З7)
QUEUE_WORKFLOW = "queue.yml"
#: прогон считаем ответом на заявку, если он создан не раньше, чем за столько
#: секунд до её отметки. Отметка заказа округлена ВНИЗ до минуты — настоящая
#: заявка не раньше неё; запас — только на расхождение часов сервера и
#: GitHub (у обоих NTP, расходятся на секунды)
MATCH_SLACK_SECONDS = 30

#: Замер 06.10 по открытому API (100 последних тегов-заявок, 14.09–06.10):
#: тег → прогон пересылки `queue.yml` — медиана 4 с, максимум 43 с;
#: тег → прогон обхода — обычно 8–10 с, максимум 62 с (#164, 02.10; второй
#: по долготе — 48 с, #139, 29.09).
#: З7: столько минут заявка ждёт старта и пишет итог в «Прогоны» (втрое
#: дольше худшего замера; владелец 02.10 — «убедиться, что пошёл»)
START_MINUTES = 3
#: З7: как часто заявка спрашивает GitHub о старте, секунд
START_POLL_SECONDS = 20
#: С4, З4, З5: заказу моложе стольких минут верим, даже если GitHub его ещё
#: не показал; старше и без прогона — «не стартовал», заказ сорвался и идёт
#: по таблице RECOVERY. Десятикратный запас к худшему замеру (62 с): тег,
#: опоздавший сильнее, — уже не задержка, а потеря. Повтора тега нет вовсе
#: (иначе опоздавший первый тег и повтор дали бы два обхода) — замену
#: заказывает только сторож, по таблице
START_GIVEUP_MINUTES = 10

#: З1: сколько секунд ждать общий замок. Заявка — 10 минут, потом идёт БЕЗ
#: замка (зависший сторож плановый сбор не запрёт); сторож — 7 минут (заявка
#: — тег до 90 с и 3 минуты ожидания старта — укладывается в 5), потом пропускает проверку
LOCK_WAIT_REQUEST = 600
LOCK_WAIT_WATCH = 420
#: …кнопки админки, меняющие память сторожа («Остановить», «Сбросить»), —
#: 5 секунд: сайт дольше не ждёт; занято — «сторож сейчас работает»
LOCK_WAIT_BUTTON = 5
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
#: С3: прогон ждёт в очереди, хотя перед ним никого (обычно GitHub заводит
#: прогон за минуту). Такой НЕ отменяем: к сайтам он не ходил, а новый заказ
#: встал бы в ту же стоящую очередь — вышло бы два пропавших прогона вместо
#: одного ждущего. Столько минут — одна строка-предупреждение…
QUEUE_WARN_MINUTES = 20
#: …столько — одна ТРЕВОГА: очередь GitHub стоит, сервер сам тут ничего не
#: сделает. Прогон ждём дальше: GitHub сам снимет его через сутки, тогда
#: заказ сорвётся и пойдёт по таблице `RECOVERY`
QUEUE_ALARM_MINUTES = 60
#: С3: заявка отмены исполняется за 1–2 минуты (замер 06.10: 50 секунд); не
#: остановился за столько — тревога
CANCEL_CONFIRM_MINUTES = 10
#: GitHub сам обрывает прогон через столько минут (`timeout-minutes` в
#: crawl.yml) — для слов в строках сторожа
HARD_LIMIT_MINUTES = 150

#: С4а: минут после финиша, которые даём стуку «закончил» дойти до сервера
KNOCK_GRACE_MINUTES = 10
#: С4б: сколько заборов подряд не дали результата на сервере — до тревоги.
#: Забор идёт отдельной службой, как по стуку (`crawl_hook.start_pull`):
#: проверка его не ждёт и замок не держит, а итог сверяет следующая
PULL_TRIES_BEFORE_ALARM = 2
#: С4г, С6: сколько секунд даём заявке, которую запускает сторож (она ждёт
#: старта 3 минуты, тег пушится до 90 с)
ORDER_TIMEOUT_SECONDS = 600
#: С4д: заказ старше стольких часов и не закрыт — тревога (самый длинный
#: обход с ожиданием очереди и забором укладывается в 4 часа)
ORDER_TTL_HOURS = 6
#: книга заказов: закрытый заказ хранится столько часов — его читают правило
#: «1 час» (З5), С6 («последний заказ дошёл») и блок админки
ORDER_KEEP_HOURS = 24
#: обход сайта на сервере (`server-…`): итога (`site_crawl_result`) нет
#: дольше стольких минут — сорвался. Тот же потолок, что у сайта на GitHub
SERVER_SITE_MINUTES = CEILING_MINUTES["site"]

#: С5: через столько минут после слота сторож сверяет, приходила ли плановая
#: заявка. Больше, чем заявка ждёт замок (10), и меньше шага сторожа (15)
SLOT_AUDIT_MINUTES = 12
#: С5: заявка отметилась «пришла» и молчит дольше — её оборвали; сама она,
#: с пушем тега до 90 с и ожиданием старта 3 мин, укладывается в 5 минут
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
#: «unknown» — ПЕРЕХОД НА ВЫКЛАДКУ. До неё `crawl.yml` на main не давал
#: прогону `run-name`: в API такой прогон назван «Обход телесайтов», а вид и
#: глубина сбора живут только во входных полях, которых API списка прогонов
#: не отдаёт (`name`, `event`, `path` у пробы и полного одинаковые) —
#: распознать нельзя. Значит, прогон, шедший в минуту выкладки, без
#: «unknown» сторож счёл бы чужим и заказал бы лишний обход. Глубина такого
#: прогона неизвестна — `run_for` берёт его в ответ на заказ любой глубины.
#: КАК УБРАТЬ. Условие — в списке, который сторож читает (последние
#: `RUNS_LIMIT` прогонов обхода), не осталось ни одного прогона без вида.
#: Проверка на сервере, в папке проекта (только чтение, один запрос к API):
#:   venv/bin/python -c "from app import watch, trigger; r = watch.github_runs(trigger._repo_slug(), workflow=watch.CRAWL_WORKFLOW); print(r.ok, sum(watch.run_kind(x)[0] == 'unknown' for x in r))"
#: Ответ `True 0` — можно убирать (обычно через 2–3 дня после выкладки:
#: за день набегает до 15 прогонов); `True N` при N > 0 — рано; `False …`
#: — GitHub не ответил, повторить. Что править: здесь оставить ("full",),
#: в `lock_verdict` убрать подстановку вида из отметки (строка с
#: «ВРЕМЕННО»), в `answers` — ветку «прогон без вида», в test_watch.py —
#: проверки с «ВРЕМЕННО» и `old_title` в [основа]
FULL_KINDS = ("full", "unknown")


# ── время и отметки ──────────────────────────────────────────────────────────
# Внутри сторожа всё время — в UTC: Python считает разницу двух киевских
# времён по настенным часам, и в ночь перевода часов (25.10.2026) пороги
# «6 ч» и окно досрочного сдвинулись бы на час. По Киеву — только слоты
# расписания (`_slots`), отметки в памяти и слова в строках (`stamp`, `hm`).

def utc(at: datetime) -> datetime:
    """Любое время с поясом → то же мгновение в UTC."""
    return at.astimezone(timezone.utc)


def _utc(text: str) -> datetime | None:
    """Время GitHub (`2026-10-05T17:30:11Z`, UTC) → время с поясом."""
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def kyiv_at(text: str) -> datetime | None:
    """Отметка `2026-10-05 16:15` (Киев) → мгновение в UTC; не разобрать —
    None. В повторный час ночи перевода (03:00–04:00) отметка неоднозначна —
    берётся первый из двух часов."""
    try:
        return utc(datetime.strptime(str(text), "%Y-%m-%d %H:%M").replace(tzinfo=KYIV))
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


#: полный обход: `full-6` / `days-6` — дни 1…6; `full-6-from3` — дни 3…6
#: («добор дней», следующий пакет: плановый на 6 сразу после сбора на 2 дня
#: соберёт только оставшиеся). Окно дней — `window`
FULL_RE = re.compile(r"(?:full|days)-(\d+)(?:-from(\d+))?")


def parse_what(what: str) -> tuple[str, int]:
    """Вид сбора по слову стука / отметки / названия прогона: `proba-2`,
    `probeurl-…` → проба; `site-…`; `date-…`; `full-6` / `days-6` /
    `full-6-from3` → полный по 6-й день. Не узнан — unknown."""
    what = what or ""
    if what.startswith(("proba", "probeurl")):
        return "probe", 0
    if what.startswith("site-"):
        return "site", 0
    if what.startswith("date-"):
        return "date", 0
    m = FULL_RE.fullmatch(what)
    if m:
        return "full", int(m.group(1))
    return "unknown", 0


def window(what: str) -> tuple[int, int] | None:
    """Окно дней полного обхода [с, по]: `full-6` → (1, 6), `full-6-from3`
    → (3, 6); не полный обход — None. «Глубина не меньше» в сторожа —
    это «окно прогона(ов) накрывает нужное окно» (`covered`)."""
    m = FULL_RE.fullmatch(what or "")
    return (int(m.group(2) or 1), int(m.group(1))) if m else None


def covered(need: tuple[int, int], windows) -> bool:
    """Окна `windows` вместе накрывают окно `need` без дыр: «2 дня» (1–2) и
    «6 дней с 3-го» (3–6) вместе накрывают слот на 6 дней (1–6)."""
    day = need[0]
    for first, last in sorted(w for w in windows if w):
        if first > day:
            break
        day = max(day, last + 1)
    return day > need[1]


def run_what(run: dict) -> str:
    """Слово вида из названия прогона (`Обход full-6` → `full-6`); плановый
    cron GitHub — `schedule`; без вида — пусто."""
    if run.get("event") == "schedule":
        return "schedule"
    m = re.fullmatch(r"Обход (\S+)", run.get("display_title") or "")
    return m.group(1) if m else ""


def run_kind(run: dict) -> tuple[str, int]:
    """Вид прогона по его названию: crawl.yml называет прогон `Обход full-6`
    / `Обход proba-2` / `Обход site-…` / `Обход date-…` (`run-name`).
    Плановый cron GitHub (04:17 UTC) — отдельный вид: он почти всегда сразу
    выходит («сегодня уже ходили»), полным обходом его не считаем."""
    what = run_what(run)
    if what == "schedule":
        return "schedule", 0
    return parse_what(what) if what else ("unknown", 0)


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


def answers(order_what: str, run: dict) -> bool:
    """Годится ли прогон в ответ на заказ вида `order_what`: полный — если
    окно прогона накрывает окно заказа (ручной на 2 дня минутой раньше — не
    ответ на плановый на 6, он лишь шёл впереди в очереди); скан даты и
    сайт — только прогон с тем же словом (`date-2026-10-07`). Прогон без
    вида («unknown», см. `FULL_KINDS`) окна не называет — годится полному."""
    what = run_what(run)
    need = window(order_what)
    if need is not None:
        if not what:
            return "unknown" in FULL_KINDS
        have = window(what)
        return have is not None and covered(need, [have])
    return what == order_what


def run_for(order: dict, runs: list[dict]) -> dict | None:
    """Прогон, которым GitHub ответил на заявку `order` ({at, what} или
    {at, days} — тогда это полный `full-<days>`): кнопочный запуск
    (`workflow_dispatch`), созданный не раньше заявки (`MATCH_SLACK_SECONDS`)
    и годный по виду (`answers`). Из нескольких — самый ранний: более
    поздние уже чужие."""
    edge = utc(order["at"]) - timedelta(seconds=MATCH_SLACK_SECONDS)
    want = order.get("what") or f"full-{int(order.get('days') or 0)}"
    ours = []
    for r in runs:
        created = _utc(r.get("created_at") or "")
        if r.get("event") != "workflow_dispatch" or created is None or created < edge:
            continue
        if not answers(want, r):
            continue
        ours.append((created, r))
    if not ours:
        return None
    ours.sort(key=lambda x: x[0])
    return ours[0][1]


# ── расписание ───────────────────────────────────────────────────────────────
# Слоты заданы по Киеву (`_slots`), а наружу отдаются мгновениями в UTC.

def _slots(day, schedule=SCHEDULE):
    for hhmm, days in schedule:
        h, m = (int(x) for x in hhmm.split(":"))
        yield utc(datetime(day.year, day.month, day.day, h, m, tzinfo=KYIV)), days


def _days_around(at: datetime, shifts):
    """Киевские даты вокруг `at` — по ним ищутся слоты."""
    day = at.astimezone(KYIV).date()
    return [day + timedelta(days=s) for s in shifts]


def slot_for(now: datetime, days: int, schedule=SCHEDULE) -> datetime | None:
    """Плановый слот, к которому относится заявка `days` в `now`
    (±`SLOT_MATCH_MINUTES`); ручной заказ — None."""
    now = utc(now)
    for day in _days_around(now, (-1, 0, 1)):
        for at, d in _slots(day, schedule):
            if d == days and abs((now - at).total_seconds()) <= SLOT_MATCH_MINUTES * 60:
                return at
    return None


def next_slot(after: datetime, schedule=SCHEDULE) -> tuple[datetime, int]:
    """Ближайший плановый слот строго после `after`: (время, глубина)."""
    after = utc(after)
    for day in _days_around(after, (0, 1, 2)):
        for at, d in sorted(_slots(day, schedule)):
            if at > after:
                return at, d
    raise ValueError("пустое расписание")


def last_slot(now: datetime, schedule=SCHEDULE) -> tuple[datetime, int]:
    """Последний плановый слот не позже `now`: (время, глубина)."""
    now = utc(now)
    for day in _days_around(now, (0, -1, -2)):
        for at, d in sorted(_slots(day, schedule), reverse=True):
            if at <= now:
                return at, d
    raise ValueError("пустое расписание")


def covers_from(slot_at: datetime) -> datetime:
    """С какого времени начатый досрочный заменяет плановый `slot_at`
    (настоящие часы, а не настенные — см. «время и отметки»)."""
    return utc(slot_at) - timedelta(hours=EARLY_COVERS_HOURS,
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


# ── книга заказов: по записи на каждый заказ (`crawl_order:<id>`) ───────────

ORDER_PREFIX = "crawl_order:"


def order_key(record: dict) -> str:
    return f"{ORDER_PREFIX}{record['id']}"


def add_order(conn: sqlite3.Connection, what: str, order_stamp: str,
              slot: str = "", who: str = "", **extra) -> dict:
    """Тот, кто заказал сбор на GitHub (или сайт на сервере), сразу кладёт
    его в книгу заказов: сторож доведёт его до итога (С4). Вид — `what`
    (`full-6`, `date-2026-10-07`, `site-nova.bg`, `server-mojtv.hr`);
    `order_stamp` — отметка заказа до минуты (та же, что в `crawl_request`);
    `slot` — плановый слот (у плановой заявки и у досрочного сторожа), иначе
    пусто; `who` — кто заказал; `extra` — пометки сторожа: early (досрочный),
    retry_of (id заказа, который этот повторяет), reordered.
    У каждой записи свой id — отметка С СЕКУНДАМИ и кто заказал: два заказа
    одной минуты (друг нажал «2 дня», пока сторож повторял свой) — разные
    записи, и свой повтор сторож находит по `retry_of`, а не по виду.
    Сторож верит записи, а не времени: кнопка, нажатая в 16:20, — ручной
    заказ, хоть и рядом со слотом. Пишут: заявка (З6), кнопки сбора
    (`web._dispatch`, «Обойти сайт»). Возвращает запись."""
    base = f"{datetime.now(KYIV):%Y-%m-%d %H:%M:%S}|{who or '?'}"
    order_id, n = base, 1
    while db.get_setting(conn, f"{ORDER_PREFIX}{order_id}"):
        n += 1
        order_id = f"{base}|{n}"
    record = dict(extra, id=order_id, what=what, order=order_stamp, slot=slot or "",
                  who=who or "")
    save_order(conn, record)
    return record


def save_order(conn: sqlite3.Connection, record: dict) -> None:
    save_json(conn, order_key(record), record)


def load_orders(conn: sqlite3.Connection) -> list[dict]:
    """Все записи книги заказов, старые первыми."""
    rows = conn.execute("SELECT key, value FROM settings WHERE substr(key, 1, ?) = ?",
                        (len(ORDER_PREFIX), ORDER_PREFIX)).fetchall()
    out = []
    for _key, value in rows:
        try:
            record = json.loads(value or "{}")
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("id") and record.get("what") \
                and record.get("order"):
            out.append(record)
    return sorted(out, key=lambda r: (r["order"], r["id"]))


def find_order(conn: sqlite3.Connection, **match) -> dict:
    """Самая свежая запись книги, у которой все поля `match` совпадают;
    нет — пустой словарь. Так сторож находит свой повтор (`retry_of`) и
    свой досрочный (`early`, `slot`)."""
    found = [r for r in load_orders(conn)
             if all(r.get(k) == v for k, v in match.items())]
    return found[-1] if found else {}


def is_open(record: dict) -> bool:
    """Заказ ещё не закрыт: не забран, не сорвался, память о нём не сброшена."""
    return not (record.get("done") or record.get("failed") or record.get("reset"))


def prune_orders(conn: sqlite3.Connection, now: datetime) -> None:
    """Закрытые заказы старше `ORDER_KEEP_HOURS` из книги уходят (открытые
    закроет С4д по `ORDER_TTL_HOURS`). Запись о заказе из `crawl_request`
    остаётся, пока он там: иначе `full_order_record` завёл бы её заново
    открытой, и давний заказ «состарился» бы с тревогой."""
    edge = stamp(utc(now) - timedelta(hours=ORDER_KEEP_HOURS))
    current = parse_order(db.get_setting(conn, "crawl_request"))
    keep = full_order_record(conn, current, save=False).get("id") if current else ""
    for record in load_orders(conn):
        if record["id"] != keep and not is_open(record) and record["order"] < edge:
            conn.execute("DELETE FROM settings WHERE key = ?", (order_key(record),))
    conn.commit()


def full_order_record(conn: sqlite3.Connection, order: dict, save: bool = True) -> dict:
    """Запись книги о полном заказе из `crawl_request` (самая свежая с той
    же отметкой: `crawl_request` пишет последний заказ). Записи нет — заказ
    сделан до выкладки 06.10 (тогда книги не было): чей он, судим по
    времени, по таблице SCHEDULE."""
    what = f"full-{order['days']}"
    record = find_order(conn, what=what, order=order["stamp"])
    if not record:
        slot = slot_for(order["at"], order["days"])
        record = {"id": f"{order['stamp']}|до выкладки", "what": what,
                  "order": order["stamp"], "slot": stamp(slot) if slot else "",
                  "who": "до выкладки"}
        # память прежней версии (одна запись `crawl_watch` о текущем заказе):
        # итог, который она уже знала, переносим — иначе в день выкладки
        # давно забранный заказ «состарился» бы с тревогой (С4д)
        legacy = load_json(conn, LEGACY_KEY)
        if legacy.get("order") == order["stamp"]:
            record.update({k: legacy[k] for k in ("slot", "early", "reordered", "done",
                                                  "failed", "pulls") if k in legacy})
        if save:
            save_order(conn, record)
    return record


#: одна запись памяти прежней версии сторожа (до 06.10) — только читается
#: при переносе в книгу (`full_order_record`); можно стереть через сутки
#: после выкладки
LEGACY_KEY = "crawl_watch"


def record_order(record: dict) -> dict:
    """Запись книги → заказ для `decide` и `run_for`: {what, days, at, stamp}."""
    return {"what": record["what"], "days": (window(record["what"]) or (1, 0))[1],
            "at": kyiv_at(record["order"]), "stamp": record["order"]}


#: всё, что сторож помнит сам, кроме книги заказов, — это стирает кнопка
#: «Сбросить память сторожа». Заказ (`crawl_request`) и отметку «сбор идёт»
#: (`crawl_running`) пишут заявка и стук GitHub — они не память сторожа
WATCH_MEMORY = ("crawl_missed", "crawl_early", "crawl_cancel", "crawl_queue",
                "crawl_slot", "crawl_silent")


def reset_memory(conn: sqlite3.Connection) -> str:
    """Кнопка «Сбросить память сторожа»: стереть `WATCH_MEMORY`, а открытые
    заказы книги пометить reset — сторож их больше не ведёт, иначе с чистого
    листа он мог бы заново «увидеть» давний срыв и заказать обход. Дальше
    сторож решает только по новым событиям: первая проверка запомнит
    прошедший слот (С5, init), следующий слот пойдёт как обычно.
    Возвращает слова для строки в «Прогонах»."""
    for key in WATCH_MEMORY:
        db.set_setting(conn, key, "")
    dropped = [r for r in load_orders(conn) if is_open(r)]
    for record in dropped:
        save_order(conn, dict(record, reset=True))
    if not dropped:
        return "память сторожа стёрта; открытых заказов не было"
    names = ", ".join(f"{r['what']} от {r['order']}" for r in dropped)
    return (f"память сторожа стёрта; заказы {names} сторож больше не ведёт — "
            f"дальше решает только по новым событиям")


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
#:   retry — один повтор той же заявки (ручной полный, скан даты, сайт)
#:   alarm — только ТРЕВОГА, новых заказов нет до следующего планового слота
#: Вид сбоя — «чей заказ-как сорвался» (`failure_of`); чей заказ — один из
#: видов таблицы ВИДЫ ЗАКАЗОВ в шапке, повтор — с припиской `-retry`. Новый вид сбоя:
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
    # ручной полный (кнопки «2 дня» / «6 дней» админки и друзей) — один повтор
    "manual-failed": "retry",           # С4г
    "manual-expired": "alarm",          # С4д
    "manual-retry-refused": "alarm",    # С4г: повтор не ушёл
    "manual-retry-failed": "alarm",     # С4г: повтор сорвался
    "manual-retry-expired": "alarm",    # С4д
    # скан даты и сайт на GitHub — короткие: один повтор, к сайтам больше не ходим
    "date-failed": "retry",
    "date-expired": "alarm",
    "date-retry-refused": "alarm",
    "date-retry-failed": "alarm",
    "date-retry-expired": "alarm",
    "site-failed": "retry",
    "site-expired": "alarm",
    "site-retry-refused": "alarm",
    "site-retry-failed": "alarm",
    "site-retry-expired": "alarm",
    # сайт на сервере — без повтора: к такому сайту не чаще раза в сутки
    "server-failed": "alarm",
}


def recovery(failure: str) -> str:
    """Шаг после сбоя по таблице `RECOVERY`; незнакомый вид — ТРЕВОГА."""
    return RECOVERY.get(failure, "alarm")


def order_who(state: dict) -> str:
    """Чей заказ для `RECOVERY`: `order_kind`, повтор — с припиской -retry
    (повтор бывает только у видов с шагом retry: ручной, дата, сайт)."""
    who = order_kind(state)
    return f"{who}-retry" if state.get("reordered") and who in RETRIED else who


#: виды заказов, у которых срыв даёт шаг retry (один повтор)
RETRIED = ("manual", "date", "site")


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
    run = run_for({"at": ordered, "days": early.get("days")}, full_runs(runs, slug))
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
             and busy.get("age", 10 ** 9) < START_GIVEUP_MINUTES * 60)
    if not found and fresh:
        # заявку только что подали — GitHub её ещё не показал
        found = [(parse_what(what), None)]
    if not found:
        return "clear", (f"отметка «сбор {busy.get('state', 'идёт')}» («{what}» с "
                         f"{busy.get('since', '?')}) снята — на GitHub прогонов "
                         f"нет, она ложная. Заказываю плановый обход {days} сут.")
    # окна дней, что уже собраны за последний час, — «добор дней»: идущий
    # «6 дней с 3-го» вместе с только что прошедшим «2 дня» накрывают слот
    edge = utc(now) - timedelta(hours=crawl_hook.RECENT_HOURS)
    done = [window(run_what(r)) for r in crawl_only(runs, slug)
            if r.get("conclusion") == "success"
            and (_utc(r.get("updated_at") or "") or edge) >= edge]
    for (kind, d), r in found:
        what_r = run_what(r) if r is not None else what
        if kind == "unknown":
            what_r = what           # ВРЕМЕННО, см. FULL_KINDS: вид — из отметки
        have = window(what_r)
        if have and covered((1, days), [have] + [w for w in done if w]):
            where = (f"#{r.get('run_number')} " if r else "")
            how = ("заказан" if r is None else
                   "идёт" if r.get("status") == "in_progress" else "ждёт очереди")
            part = f" с {have[0]}-го дня" if have[0] > 1 else ""
            return "skip", (f"плановый обход {days} сут. не нужен — на GitHub уже "
                            f"{how} обход {where}на {have[1]} сут.{part}, он соберёт "
                            f"и эти дни")
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


def forwarding(order: dict, slug: str, tag_prefix: str) -> str:
    """Что с пересылкой тега-заявки (`queue.yml`), если обход не стартовал
    за 3 минуты (З7) — только для слов в «Прогонах», решений по ней нет:
    going — пересылка ещё идёт или ждёт машину; done — переслала, а обход
    ещё не показался; failed — все пересылки тега кончились не успехом;
    none — GitHub ответил, а пересылки нет (тег не дошёл); silent — GitHub
    не ответил. Свой тег — по имени: у прогона тег-события `head_branch` —
    это имя тега (сверено вживую 06.10: «Кнопки сайта» #101 →
    `btn-cancel-37375152529-1791235179`), он начинается с `tag_prefix`,
    например `btn-days-6-`."""
    listed = github_runs(slug, workflow=QUEUE_WORKFLOW)
    if not listed.ok:
        return "silent"
    edge = utc(order["at"]) - timedelta(seconds=MATCH_SLACK_SECONDS)
    ours = [r for r in listed
            if (r.get("head_branch") or "").startswith(tag_prefix)
            and (_utc(r.get("created_at") or "") or edge) >= edge]
    if not ours:
        return "none"
    if any((r.get("status") or "") in RUNNING for r in ours):
        return "going"
    if any(r.get("conclusion") == "success" for r in ours):
        return "done"
    return "failed"


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


def stuck(runs: list[dict], now: datetime, slug: str = "",
          queue: dict | None = None) -> list[dict]:
    """Зависшие прогоны обхода: ИДЁТ дольше потолка своего вида.
    [{run, kind, days, minutes, limit, why}]. Ждущие очереди сюда не
    попадают — см. `queue_waits`. `queue` — память `crawl_queue`: прогон,
    который сторож видел ждущим очереди, «пошёл» не раньше, чем его видели
    ждущим в последний раз (`run_started_at` GitHub — время создания)."""
    crawls = crawl_only(runs, slug)
    out = []
    for r in crawls:
        if (r.get("status") or "") != "in_progress":
            continue
        start = effective_start(r, crawls)
        if start is None:
            continue
        seen = kyiv_at((queue or {}).get(str(r.get("id")), {}).get("last", ""))
        if seen and seen > start:
            start = seen
        minutes = (utc(now) - start).total_seconds() / 60
        kind, days = run_kind(r)
        limit = ceiling(kind, days)
        if minutes > limit:
            out.append({"run": r, "kind": kind, "days": days, "minutes": minutes,
                        "limit": limit,
                        "why": f"идёт {minutes:.0f} мин, а такой обычно "
                               f"укладывается в {limit}"})
    return out


def queue_waits(runs: list[dict], now: datetime, slug: str = "") -> list[dict]:
    """Прогоны, что ждут очереди, хотя впереди никого, дольше
    `QUEUE_WARN_MINUTES`: [{run, minutes}]. Их не отменяем (см. порог)."""
    crawls = crawl_only(runs, slug)
    out = []
    for r in crawls:
        if (r.get("status") or "") not in RUNNING or r.get("status") == "in_progress":
            continue
        start = effective_start(r, crawls)
        if start is None:
            continue
        minutes = (utc(now) - start).total_seconds() / 60
        if minutes > QUEUE_WARN_MINUTES:
            out.append({"run": r, "minutes": minutes})
    return out


def queue_decisions(runs: list[dict], now: datetime, queue: dict,
                    slug: str = "") -> list[tuple[str, str, str]]:
    """Очередь GitHub стоит (С3): [(действие, id прогона, слова)]. seen —
    прогон всё ещё ждёт: запомнить, когда видели (по этой отметке `stuck`
    считает, когда он пошёл); warn — одна строка-предупреждение; alarm —
    одна ТРЕВОГА; forget — прогон закончился или выпал из списка, забыть.
    `queue` — память `crawl_queue`."""
    waiting = {str(w["run"].get("id")): w for w in queue_waits(runs, now, slug)}
    alive = {str(r.get("id")) for r in active_crawls(runs, slug)}
    out = [("forget", rid, "") for rid in queue if rid not in alive]
    for rid, w in waiting.items():
        r, minutes = w["run"], w["minutes"]
        seen = queue.get(rid, {})
        out.append(("seen", rid, ""))
        what = f"прогон #{r.get('run_number')} ({describe(*run_kind(r))})"
        if minutes >= QUEUE_ALARM_MINUTES and not seen.get("alarmed"):
            out.append(("alarm", rid,
                        f"ТРЕВОГА — {what} {minutes:.0f} мин ждёт очереди, хотя "
                        f"впереди никого: очередь GitHub стоит. Не отменяю — новый "
                        f"заказ встал бы в ту же очередь; GitHub сам снимет прогон "
                        f"через сутки, тогда заказ пойдёт по таблице RECOVERY"))
        elif not seen.get("warned"):
            out.append(("warn", rid,
                        f"{what} {minutes:.0f} мин ждёт очереди, хотя впереди никого "
                        f"(обычно — минута). Не отменяю: к сайтам он не ходил, новый "
                        f"заказ встал бы туда же. Через {QUEUE_ALARM_MINUTES} мин — "
                        f"тревога"))
    return out


def cancel_decisions(runs: list[dict], now: datetime, cancels: dict,
                     slug: str = "", own: dict | None = None,
                     queue: dict | None = None) -> list[tuple[str, str, str]]:
    """Отмена зависших (С3): [(действие, id прогона, слова)]. cancel — подать
    заявку отмены; confirmed — GitHub подтвердил, прогон остановлен; alarm —
    прогон не остановился за `CANCEL_CONFIRM_MINUTES` после заявки (тревога
    один раз); forget — прогона уже нет в списке, забыть.
    `cancels` — память `crawl_cancel`: прогон, который в ней есть, второй
    заявки отмены не получает. `own` — {id прогона заказа сторожа: что
    сторож сделает с этим заказом дальше (С4г)}."""
    own = own or {}
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
        since = (utc(now) - asked).total_seconds() / 60 if asked else 0
        if since >= CANCEL_CONFIRM_MINUTES and not c.get("alarmed"):
            out.append(("alarm", rid,
                        f"ТРЕВОГА — прогон #{number} не остановился за {since:.0f} мин "
                        f"после заявки отмены; GitHub всё равно оборвёт его через "
                        f"{HARD_LIMIT_MINUTES} мин после старта"))
    for s in stuck(runs, now, slug, queue):
        r = s["run"]
        rid = str(r.get("id"))
        if rid in cancels or not re.fullmatch(r"\d+", rid):
            continue
        what = describe(s["kind"], s["days"])
        after = own.get(rid, "он мешал очереди обходов")
        out.append(("cancel", rid,
                    f"прогон #{r.get('run_number')} ({what}) завис: {s['why']} — "
                    f"отменяю его, {after}"))
    return out


def send_cancel(cancels: dict, run: dict, now: datetime) -> tuple[bool, str]:
    """Заявка отмены прогона — одна на сторожа (С3) и кнопку «Остановить
    зависший»: тег `btn-cancel-<id>-<время>`, исполняет `queue.yml`.
    Записывается в `cancels` (память `crawl_cancel`) и неушедшая заявка:
    сторож этому прогону второй не шлёт, а остановку сверяет (С3).
    (ушла ли: True / False / None — git не ответил вовремя, могла дойти;
    ответ git). При None тревогу даст сверка остановки через
    `CANCEL_CONFIRM_MINUTES`, если заявка и правда не дошла."""
    rid = str(run.get("id"))
    if not re.fullmatch(r"\d+", rid):
        return False, "номер прогона не из цифр — отменять не буду"
    ok, answer = trigger.push_request_tag("cancel", rid)
    cancels[rid] = {"at": stamp(now), "number": run.get("run_number") or "?",
                    "alarmed": ok is False}
    return ok, answer


# ── С4. текущий заказ ────────────────────────────────────────────────────────

def parse_order(raw: str) -> dict | None:
    """`обход 6 сут.|2026-10-02 06:15` → {"days": 6, "at": <Киев>, "stamp": …}."""
    if not raw or "|" not in raw:
        return None
    head, mark = raw.split("|", 1)
    try:
        days = int(head.split()[1])
    except (IndexError, ValueError):
        return None
    at = kyiv_at(mark.strip())
    if at is None:
        return None
    return {"days": days, "at": at, "stamp": mark.strip()}


def order_kind(state: dict) -> str:
    """Чей заказ — от этого зависит, что делать при срыве (С4г), см. ВИДЫ
    ЗАКАЗОВ в шапке: date, site, server — по виду записи книги; у полного —
    early (досрочный сторожа), planned (плановый, пришёл в слот), manual
    (кнопка, повтор ручного)."""
    what = state.get("what") or ""
    for prefix in ("date", "site", "server"):
        if what.startswith(prefix + "-"):
            return prefix
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
    `START_GIVEUP_MINUTES` или кончился не успехом (С4г).
    `result` — судьба результата прогона (`result_state`)."""
    if state.get("done") or state.get("failed") or state.get("reset"):
        return "closed", "по заказу всё решено раньше"
    now = utc(now)
    age = (now - order["at"]).total_seconds() / 60
    if age > ORDER_TTL_HOURS * 60:
        return "expired", f"заказ {order['stamp']} старше {ORDER_TTL_HOURS} ч и не закрыт"
    if run is None:
        if age < START_GIVEUP_MINUTES:
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
        how = "сторожем" if state.get("pulls") else "по стуку"
        return "done", f"прогон #{number} готов и забран {how}"
    if result == "none":
        return "done", (f"прогон #{number} прошёл, но нового результата не оставил "
                        f"(например, пропуск «сегодня уже ходили») — забирать нечего")
    return "wait", f"прогон #{number} готов, но метку «собрано» сверить не вышло"


def decide_server(record: dict, now: datetime, result_raw: str) -> tuple[str, str]:
    """Обход сайта на сервере (`server-<домен>`, С4): на GitHub его нет —
    итог видно по `site_crawl_result` (`домен|ГГГГ-ММ-ДД ЧЧ:ММ|…`, пишет
    `server_crawl.py`). done — итог этого сайта не старше заказа; failed —
    итога нет дольше `SERVER_SITE_MINUTES`; wait — ещё идёт."""
    domain = record["what"][len("server-"):]
    parts = (result_raw or "").split("|")
    if len(parts) >= 2 and parts[0] == domain and parts[1] >= record["order"]:
        return "done", f"сервер обошёл {domain} в {parts[1][-5:]}"
    at = kyiv_at(record["order"]) or utc(now)
    minutes = (utc(now) - at).total_seconds() / 60
    if minutes > SERVER_SITE_MINUTES:
        return "failed", (f"сервер обходит {domain} уже {minutes:.0f} мин без итога "
                          f"(обычно до {SERVER_SITE_MINUTES})")
    return "wait", f"сервер обходит {domain} ({minutes:.0f} мин)"


def _stamp_utc(raw: str) -> datetime | None:
    """Метка «собрано» (`ГГГГ-ММ-ДД ЧЧ:ММ`, UTC, пишет parse_live) → время."""
    try:
        return datetime.strptime(raw or "", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _collected(text: str) -> datetime | None:
    """Метка «собрано» из текста games.json."""
    try:
        return _stamp_utc(json.loads(text).get("собрано") or "")
    except (ValueError, AttributeError):
        return None


#: где лежит результат сбора каждого вида (`crawl.yml`): полный —
#: results/, скан даты — results/day/, сайт на GitHub — results/site/
RESULT_DIRS = {"full": "results", "date": "results/day", "site": "results/site"}


def result_dir(what: str) -> str:
    return RESULT_DIRS.get(parse_what(what)[0], "results")


def import_key(what: str) -> str:
    """Ключ метки заливки результата вида `what` в базу. Его пишет
    `games_import.py` после УДАЧНОЙ заливки: `last_import_stamp:<папка>` =
    «собрано» влитого файла (UTC) — results → `…:results`, results/day →
    `…:day`, results/site → `…:site`."""
    return f"last_import_stamp:{Path(result_dir(what)).name}"


def result_state(root, started: datetime, what: str, imported: str) -> str:
    """Судьба результата прогона вида `what`, стартовавшего в `started`
    (UTC): picked — результат ВЛИТ в базу сервера: метка заливки
    `imported` (`import_key`) не старше старта; pending — такое «собрано»
    есть только на GitHub (стук не дошёл или заливка не прошла); none — ни
    там, ни там (прогон результата не оставил); unknown — GitHub не ответил.
    Одно правило на все виды: скан даты и сайт «дошли», только когда их
    результат на сервере, — как и полный. Сравниваем метку результата, а не
    коммиты: на GitHub между обходами ложатся и правки кода, и словари — по
    ним «забрано ли» не понять (02.10 сторож трижды хотел забрать давно
    забранный #161)."""
    # метка «собрано» округлена вниз до минуты — отсюда лишняя минута запаса
    edge = utc(started) - timedelta(seconds=MATCH_SLACK_SECONDS + 60)
    local = _stamp_utc(imported)
    if local and local >= edge:
        return "picked"
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "main"], capture_output=True,
                       text=True, cwd=root, timeout=60, check=True)
        shown = subprocess.run(["git", "show", f"origin/main:{result_dir(what)}/games.json"],
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
    now = utc(now)
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
    очереди: заказ — {"run": id}, решение НЕ окончательное — слот ждёт итога
    этого прогона (дойдёт — следующая проверка скажет collected; упадёт —
    order; затянется — late); collected — такой обход уже успешно завершился
    после слота (или за час до него — то же правило «1 час», что у заявки);
    order — заказать сейчас обход глубиной max(сорвавшийся, следующий плановый).
    `last_done` — память сторожа: последний заказ `last_order` дошёл и
    забран. Ей верим, даже если прогона уже нет в списке последних.
    `skip_ids` — прогоны, которые сторож отменяет: они не в счёт."""
    if missed.get("state") != "missed":
        return "none", {}, ""
    now = utc(now)
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
    need = (1, mdays)
    since = (kyiv_at(slot) or at) - timedelta(hours=crawl_hook.RECENT_HOURS)
    if (last_done and last_order and last_order["at"] >= since
            and last_order["days"] >= mdays):
        return "collected", {}, (
            f"плановый обход {slot_hm} не состоялся, но обход на "
            f"{last_order['days']} сут., заказанный в {hm(last_order['at'])}, уже "
            f"дошёл и забран (по памяти сторожа) — эти дни собраны, досрочно "
            f"не заказываю")
    # окна дней: успешно прошедшие после слота (или за час до него) и идущие
    done = [r for r in crawl_only(runs, slug)
            if window(run_what(r)) and (r.get("status") or "") == "completed"
            and r.get("conclusion") == "success"
            and (_utc(r.get("updated_at") or "") or since) >= since]
    skip = {str(x) for x in skip_ids}
    going = [r for r in active_crawls(runs, slug)
             if window(run_what(r)) and str(r.get("id")) not in skip]
    if done and covered(need, [window(run_what(r)) for r in done]):
        names = ", ".join(f"#{r.get('run_number')} ({run_what(r)}, в "
                          f"{hm(_utc(r.get('updated_at') or ''))})" for r in done)
        return "collected", {}, (
            f"плановый обход {slot_hm} не состоялся, но эти дни уже успешно "
            f"собраны: {names} — досрочно не заказываю")
    if going and covered(need, [window(run_what(r)) for r in done + going]):
        ids = ",".join(str(r.get("id")) for r in going)
        names = ", ".join(f"#{r.get('run_number')} ({run_what(r)})" for r in going)
        return "covered", {"run": ids}, (
            f"плановый обход {slot_hm} не состоялся, но на GitHub уже идёт "
            f"{names} — жду его итога: дойдёт — эти дни собраны, не дойдёт — "
            f"закажу досрочный")
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

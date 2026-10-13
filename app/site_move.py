# -*- coding: utf-8 -*-
"""ПЕРЕВОД САЙТА НА СЕРВЕР И ОБРАТНО — схема сбоев, шаг 11 (13.10.2026).

Правило владельца 06.10 (п. 2 и «РЕШЕНИЕ ВЛАДЕЛЬЦА 06.10» в
`deploy/СБОИ-СХЕМА.md`): GitHub не скачал сайт 3 сбора подряд, а сервер
скачал → сайт сам переводится на сервер (`by_server`) + строка владельцу в
«Прогоны» (уведомление, НЕ ТРЕВОГА); удачный сбор с GitHub обнуляет счёт;
раз в НЕДЕЛЮ — проба вернуть на GitHub, и для сайтов, переведённых самим
владельцем (mojtv.hr), тоже. Полный сбор с адреса сервера — НИКОГДА.

КАК ИДЁТ (кто что делает):
  * Заливка сбора GitHub на сервере (`games_import.py`, после `log_run`)
    зовёт `after_import`: по report.json сбора ведёт счёт срывов сайта
    (П1) и пишет итог недельной пробы возврата (П4).
  * Утренний серверный сбор (`scripts/server_crawl.py`, cron 06:40 — уже
    идёт раз в сутки; новых cron-строк нет) ДО своего обычного хода зовёт
    `return_turn` (вернуть на GitHub сайты, чья проба открылась, П4) и
    `server_turn` (проверить кандидатов одним адресом с сервера и
    перевести, П2), а дальше, как всегда, качает сайты `by_server` — уже и
    только что переведённые (П3, П6).
  * Полный обход на GitHub (`crawl_fetch.py`) раз в 7 дней берёт у каждого
    сайта `by_server` ОДИН адрес и кладёт итог в раздел «проба_возврата»
    report.json — не в «строки» (П4, П7).

ПОЛЯ в `sources.selector_config` (серверная база; схема, «уточнения
второго отчёта проектировщика»):
  gh_fail_streak     сколько сборов GitHub подряд сайт не дался
  gh_fail_first      когда началась серия (ГГГГ-ММ-ДД ЧЧ:ММ по Киеву)
  gh_fail_last_slot  id сбора (прогон GitHub), чей срыв засчитан последним
  gh_fail_why        чем сайт ответил GitHub в последнем срыве
  server_ok_last     когда сервер последний раз скачал сайт с расписанием
  server_check_last  когда сервер последний раз проверял его одним адресом
  server_fail_alarm  когда ушла ТРЕВОГА «не отвечает ни GitHub, ни серверу»
                     (одна на серию)
  moved_by           auto — перевёл этот модуль, owner — владелец кнопкой
  moved_at           когда переведён на сервер
  gh_probe_last      когда GitHub последний раз пробовал его вернуть
  gh_return          проба открылась, когда — утром сервер вернёт сайт

ПРАВИЛА — по функции на правило (что случилось → что делаем):
  П1. Проба = СБОР GitHub. `import_kind`, `crawl_id`, `site_verdicts`,
      `apply_probe`, `after_import`.
      Какая заливка (`import_kind`):
        «сбор»    — полный обход GitHub: плановый, досрочный, ручной,
                    кнопка «Обойти сайт» на GitHub, переразбор упавшего
                    сбора (его report.json — того же сбора). Срыв +1, удача
                    обнуляет;
        «дозабор» — только ОБНУЛЯЕТ (сайт, выправленный дозабором); срыв
                    дозабора не считается: этот сбор уже засчитан;
        «скан»    — скан даты — только ОБНУЛЯЕТ. Срыв скана не считается:
                    скан — одна страница дальней даты (там 404/5xx чаще), и
                    владелец жмёт его по нескольку раз в час — три скана за
                    час перевели бы сайт из-за минутного сбоя, а схема
                    хочет «3 сбора» — разные часы;
        «сервер»  — сбор с нашего сервера (`--who "сервер …"`,
                    `server_crawl.py`): только `server_ok_last`;
        ""        — прочее (проба площадки; отчёт без id прогона GitHub —
                    локальный прогон или старый отчёт) — ничего.
      Один сбор — одна проба: id сбора (`crawl_id`) — поле «прогон»
      report.json, у дозабора — «из прогона» его раздела; второй заход,
      дозабор, переразбор и повторная заливка того же сбора второй раз
      срыв не считают (`gh_fail_last_slot`).
      Итог сайта в сборе (`site_verdicts`):
        «дался»    — хоть одна страница «расписание есть» или разбор дал
                     с сайта строки (так же судит `store.log_run`);
        «не дался» — ни одной такой, и среди страниц есть класс ban / down
                     / net (`redo.row_class`), кроме ответа 4xx (не 403 и
                     429): «нет такой страницы» — сайт GitHub-у ответил;
        нейтрально — только «пусто», «нет на этот день», 4xx: счёт не
                     трогаем (пустое расписание — не поломка).
      Не считаются: сайты `by_server`, дозорные (раздел «дозор» отчёта,
      `crawl_fetch.DAILY_PROBE`), выключенные, не-расписания (справочники
      — сервер их не качает) и закрытые владельцем (`status` closed,
      parked — по ним его решение).
      МАССОВЫЙ СБОЙ (`is_mass`): в сборе судили не меньше `MASS_MIN_SITES`
      сайтов и не дались больше `MASS_SHARE` из них (тот же порог, что
      «провал» обхода, `crawl_fetch.FAIL_DOMAINS_SHARE`) — это сеть
      раннера GitHub, а не сайты: срывы этого сбора не считаются (удачи —
      обнуляют), строка в журнал заливки.
      Счёт дошёл ровно до `FAILS_TO_MOVE` → строка «кандидат: утром сервер
      проверит одним адресом» (уведомление).
  П2. Кандидат (`gh_fail_streak` ≥ `FAILS_TO_MOVE`, не `by_server`) —
      проверка с сервера ОДНИМ адресом: `candidates`, `check_refusal`,
      `decide_check`, `move_to_server`, `server_turn`. Зовёт утренний
      `server_crawl.py` (06:40, тихий час: заливок и сборов нет) или руками
      `server_crawl.py --once <домен>`. Пределы: по одному сайту (подряд,
      не разом), не больше `SITES_PER_RUN` за заход и `CHECKS_PER_DAY` в
      киевские сутки, к одному сайту — не чаще `CHECK_GAP_HOURS`, перед
      каждым — свободно ≥ `MIN_FREE_MB` (MemAvailable), замок заливки
      (`/run/streams-update.lock`) наш на всё время проверок — заливка
      ждёт (flock -w 900), а занят — проверки откладываются.
      Сервер скачал страницу с расписанием → перевод: `plan_push.set_mode
      (домен, True)` (база + поле одного домена в плане + push плана, без
      пересборки), `moved_by=auto`, `moved_at`, клеймо «сломан» снято;
      строка владельцу — уведомление без тревоги.
      Сервер тоже не скачал → не переводим; строка «не отвечает ни GitHub,
      ни серверу». Первая такая в серии — ТРЕВОГА (письмо владельцу): сайт
      3+ сбора без данных, и сервер ничего сам сделать не может — схема,
      «fetch-net/down: 3 сбора подряд — тревога»; дальше в той же серии —
      строка без тревоги (письмо не чаще раза на серию, т. е. реже раза в
      сутки на сайт). Серия кончается удачей на GitHub или переводом.
  П3. Глубина серверного сбора (`server_depth`): `--days` → оно; своя
      `max_days` (потолок владельца, mojtv.hr — 4) → она; переведён
      автоматически → `MOVED_WINDOW_DAYS` (= самый глубокий плановый сбор,
      как сайт качался на GitHub); иначе (переведён владельцем, без
      потолка) — `OWNER_DEFAULT_DAYS`, как было до 13.10 (вопрос владельцу
      в отчёте шага 11).
  П4. Обратный путь — раз в `RETURN_EVERY_DAYS` суток: `return_due`,
      `return_item`, `return_remember` (GitHub), `apply_return_probe`
      (заливка), `return_turn` (06:40). Полный обход на GitHub без фильтров
      (`crawl_fetch.py`, только на самом GitHub) берёт у каждого сайта
      `by_server` (и переведённого владельцем) ОДИН адрес — как проба
      площадки; память — `results/vozvrat.json` (едет в репозиторий с
      results/, как `dozor.json`): сайт, впервые увиденный «на сервере»,
      ждёт неделю от этой минуты; вернувшиеся забываются. Итог — раздел
      «проба_возврата» report.json. Заливка: «расписание есть» (из одного
      адреса открылся — больше половины) → `gh_return` и строка; иначе —
      строка «остаётся на сервере, следующая проба через неделю».
      Утром `return_turn`: `set_mode(False)` + строка владельцу.
  П5. Владелец видит всё: строки «Прогонов» (`note`, кто — `WHO`);
      пометка у сайта (`mark`) — на странице сбоев прогона, и раздел «На
      сервере» на «Сломанных» (`overview`).
  П6. Ни один шаг не делает полного сбора с сервера: проверка — один
      адрес (`crawl_fetch.проба_одним_адресом`), а данные переведённого
      сайта качает ежедневный `server_crawl.py` как любой `by_server`
      (`SITE_GAP_HOURS`).
  П7. Строки сайтов `by_server` GitHub в «строки» отчёта не кладёт (проба
      возврата — отдельным разделом), поэтому дозабор (`redo.pick`), счёт
      сбоев (`store.log_run`), порог провала (`crawl_fetch.assess`) и
      этот счёт их не видят.
  П8. Проверки — `scripts/test_site_move.py`: сценарий на каждое правило.

ОТКАТ (git revert): поля в selector_config остаются и никому не мешают;
`results/vozvrat.json` можно удалить отдельным коммитом. Переведённые
автоматически сайты остаются `by_server` — вернуть кнопкой «Вернуть на
GitHub» (страница сбоев прогона) или `source_mode.py <домен> --auto --apply`.

Модуль на уровне импорта — только стандартная библиотека и `app.redo`: его
зовёт и обход на GitHub (`crawl_fetch.py`, проба возврата).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import redo

KYIV = ZoneInfo("Europe/Kyiv")

# ── пороги — здесь; у каждого сказано, откуда цифра ──────────────────────────

#: П1/П2: столько сборов GitHub подряд сайт не дался → кандидат на перевод
#: (решение владельца 06.10: 3, а не 4, как предлагал проектировщик)
FAILS_TO_MOVE = 3
#: П1: массовый сбой — не дались больше этой доли судимых сайтов (= порог
#: провала обхода `crawl_fetch.FAIL_DOMAINS_SHARE`; схема, «Д. Классы»:
#: «>20 % доменов net из разных стран → сеть раннера»; сверяет тест)…
MASS_SHARE = 0.20
#: …если судили хотя бы столько сайтов (кнопка «Обойти сайт» — один сайт,
#: у неё «доли» нет)
MASS_MIN_SITES = 10
#: П1: статусы источника, по которым есть решение владельца — не считаем
OWNER_STATUSES = ("closed", "parked")
#: П2: сервер на 1 ГБ — не больше стольких сайтов за один заход…
SITES_PER_RUN = 3
#: …и стольких разовых проверок в киевские сутки (схема, уточнения 06.10)
CHECKS_PER_DAY = 5
#: П2: проверку начинаем, только если свободно не меньше (MemAvailable, МБ)
MIN_FREE_MB = 400
#: П2: к одному сайту с сервера — не чаще (= `crawl_hook.SITE_GAP_HOURS`,
#: «даже кнопкой не больше одного раза в сутки», владелец 10.09;
#: совпадение сверяет test_site_move.py)
CHECK_GAP_HOURS = 20
#: П4: проба вернуть на GitHub — раз в столько суток (владелец 06.10:
#: «раз в НЕДЕЛЮ»)
RETURN_EVERY_DAYS = 7
#: П3: глубина переведённого автоматически сайта — самый глубокий плановый
#: сбор GitHub (= max глубины в `watch.SCHEDULE`; сверяет test_site_move.py)
MOVED_WINDOW_DAYS = 6
#: П3: глубина сайта, переведённого владельцем, без своего потолка — как
#: было до 13.10 (`server_crawl.py`: «… or 2»)
OWNER_DEFAULT_DAYS = 2

#: П2: замок заливки — общий у `streams-update.sh` и забора по стуку
#: (`deploy/cron.d`, `hook_pull.sh`: `flock -w 900 /run/streams-update.lock`)
UPDATE_LOCK = "/run/streams-update.lock"
#: П2: память разовых проверок (настройка): [{когда, домен, итог}]
CHECKS_KEY = "site_move_checks"
CHECKS_KEEP = 50
#: П5: «кто» у строк «Прогонов» этого модуля
WHO = "перевод сайтов"
#: П4: раздел report.json с пробами возврата
SECTION = "проба_возврата"
#: итог страницы, когда на ней есть расписание (`crawl_fetch.verdict`)
OK = "расписание есть"

#: поля счёта срывов — снимаются при удаче на GitHub и при переводе
STREAK_FIELDS = ("gh_fail_streak", "gh_fail_first", "gh_fail_why",
                 "server_fail_alarm")

_4XX = re.compile(r"\bHTTP 4\d\d\b")


def bare(domain) -> str:
    """`www.site.tv` → `site.tv`: в отчёте домен как в адресе, в базе — как
    заведён (как `store._bare`)."""
    return str(domain or "").strip().lower().removeprefix("www.")


def stamp(at: datetime) -> str:
    """Мгновение → `ГГГГ-ММ-ДД ЧЧ:ММ` по Киеву (так пишет время база)."""
    return at.astimezone(KYIV).strftime("%Y-%m-%d %H:%M")


def parse_stamp(text, tz=KYIV) -> datetime | None:
    """`ГГГГ-ММ-ДД ЧЧ:ММ` (по поясу `tz`) → мгновение; не разобрали — None."""
    try:
        return datetime.strptime(str(text or "")[:16], "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    except ValueError:
        return None


def day_month(text) -> str:
    """`2026-10-13 06:41` → `13.10` для строк владельцу."""
    at = parse_stamp(text)
    return at.strftime("%d.%m") if at else str(text or "")


def sites_word(n: int) -> str:
    """«1 сбор», «3 сбора», «5 сборов»."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} сбор"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} сбора"
    return f"{n} сборов"


# ── база: настройки источника и строки «Прогонов» ───────────────────────────

def load_config(row) -> dict:
    """selector_config строки `sources` → словарь (битый — пустой)."""
    try:
        config = json.loads(row["selector_config"] or "{}") or {}
    except (ValueError, TypeError):
        config = {}
    return config if isinstance(config, dict) else {}


def save_config(conn, source_id: int, config: dict) -> None:
    conn.execute("UPDATE sources SET selector_config = ? WHERE id = ?",
                 (json.dumps(config, ensure_ascii=False), source_id))
    conn.commit()


def schedule_sources(conn) -> list:
    """Включённые источники расписания — их качает обход и может качать
    сервер (`server_crawl.py` берёт только `role = 'schedule'`)."""
    return conn.execute("SELECT id, domain, status, selector_config FROM sources "
                        "WHERE enabled = 1 AND role = 'schedule' "
                        "ORDER BY domain").fetchall()


def note(conn, text: str) -> None:
    """П5: строка в «Прогоны» (`watch.note`). Слово «ТРЕВОГА» в тексте —
    это письмо владельцу (`alarm_mail`): только там, где оно задумано."""
    from . import watch
    watch.note(conn, text, who=WHO)


# ── П1. счёт срывов на GitHub ───────────────────────────────────────────────

def crawl_id(report) -> str:
    """П1: id сбора — номер прогона GitHub («прогон» отчёта); у дозабора —
    прогон, ЧЕЙ отчёт он дозабирал («из прогона» раздела «дозабор»): все
    заходы одного сбора — одна проба. Нет — пусто."""
    if not isinstance(report, dict):
        return ""
    section = report.get(redo.SECTION)
    if isinstance(section, dict) and section.get("из прогона"):
        return str(section["из прогона"])
    return str(report.get("прогон") or "")


def import_kind(report, who: str = "") -> str:
    """П1: что за заливка — «сбор», «дозабор», «скан», «сервер» или ""."""
    if str(who or "").startswith("сервер"):
        return "сервер"
    if not isinstance(report, dict):
        return ""
    if not crawl_id(report):
        # без id прогона GitHub — не сбор GitHub (компьютер, старый отчёт):
        # судить не о чем
        return ""
    if isinstance(report.get(redo.SECTION), dict):
        return "дозабор"
    mode = str(report.get("режим") or "")
    if mode.startswith("скан даты"):
        return "скан"
    if mode.startswith("полный обход"):
        return "сбор"
    return ""


def row_failed(row: dict) -> bool:
    """П1: строка — настоящий отказ GitHub-у: класс ban / down / net, но не
    ответ 4xx (кроме 403/429 — это ban): «нет такой страницы» сайт дал."""
    kind = redo.row_class(row)
    if not kind:
        return False
    if kind == "net" and _4XX.search(str(row.get("почему") or "")):
        return False
    return True


def site_verdicts(rows, parsed: dict | None = None,
                  never=frozenset()) -> dict[str, dict]:
    """П1: итог каждого сайта в сборе: {домен без www: {итог: ok|fail,
    почему}}; нейтральные сайты не попадают. `parsed` — «разобрано»
    games.json ({домен: строк}); `never` — дозорные домены (без www)."""
    parsed = {bare(d): n for d, n in (parsed or {}).items()}
    by_site: dict[str, list] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("domain"):
            continue
        domain = bare(row["domain"])
        if domain in never:
            continue
        by_site.setdefault(domain, []).append(row)
    out = {}
    for domain, items in by_site.items():
        if any(r.get("итог") == OK for r in items) or int(parsed.get(domain) or 0) > 0:
            out[domain] = {"итог": "ok", "почему": ""}
            continue
        failed = [r for r in items if row_failed(r)]
        if failed:
            why = " ".join(f"{failed[0].get('итог')}: {failed[0].get('почему') or ''}".split())
            out[domain] = {"итог": "fail", "почему": why[:160]}
    return out


def is_mass(rows, verdicts: dict, never=frozenset()) -> bool:
    """П1: массовый сбой сбора — судили не меньше `MASS_MIN_SITES` сайтов
    (все сайты строк отчёта, кроме дозорных) и не дались больше
    `MASS_SHARE` из них."""
    sites = {bare(r.get("domain")) for r in (rows if isinstance(rows, list) else [])
             if isinstance(r, dict) and r.get("domain")} - set(never)
    if len(sites) < MASS_MIN_SITES:
        return False
    failed = sum(1 for v in verdicts.values() if v.get("итог") == "fail")
    return failed / len(sites) > MASS_SHARE


def apply_probe(config: dict, verdict: dict, crawl: str, now: datetime) -> str:
    """П1: учесть итог сайта в сборе `crawl`. Возвращает событие:
    reset — серия обнулена; fail — срыв засчитан (+1); same — срыв этого
    сбора уже засчитан; "" — менять нечего."""
    if verdict.get("итог") == "ok":
        had = bool(config.get("gh_fail_streak"))
        for key in STREAK_FIELDS:
            config.pop(key, None)
        return "reset" if had else ""
    if verdict.get("итог") != "fail" or not crawl:
        return ""
    if str(config.get("gh_fail_last_slot") or "") == crawl:
        return "same"
    streak = int(config.get("gh_fail_streak") or 0) + 1
    config["gh_fail_streak"] = streak
    if streak == 1:
        config["gh_fail_first"] = stamp(now)
    config["gh_fail_last_slot"] = crawl
    config["gh_fail_why"] = verdict.get("почему") or ""
    return "fail"


def _read_json(path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def after_import(conn, report_path, who: str = "",
                 now: datetime | None = None) -> list[str]:
    """П1 + П4: после заливки сбора (`games_import.py`, сразу за `log_run`).
    Возвращает строки для журнала заливки."""
    now = now or datetime.now(KYIV)
    report = _read_json(report_path)
    if report is None:
        return []
    kind = import_kind(report, who)
    if not kind:
        return []
    games = _read_json(Path(report_path).parent / "games.json") or {}
    parsed = games.get("разобрано") if isinstance(games.get("разобрано"), dict) else {}
    if kind == "дозабор":
        # дозабор судим только по перекачанным строкам: «разобрано» в его
        # games.json — по всем страницам сбора, старым тоже
        rows, parsed = redo.redone_rows(report), {}
    else:
        rows = report.get("строки")
    dozor = report.get("дозор")
    never = {bare(d) for d in (dozor if isinstance(dozor, dict) else {})}
    verdicts = site_verdicts(rows, parsed, never)
    said = []
    if kind == "сервер":
        for source in schedule_sources(conn):
            if verdicts.get(bare(source["domain"]), {}).get("итог") == "ok":
                config = load_config(source)
                config["server_ok_last"] = stamp(now)
                save_config(conn, source["id"], config)
        return said
    crawl = crawl_id(report)
    mass = kind == "сбор" and is_mass(rows, verdicts, never)
    if mass:
        said.append(f"сбор {crawl}: не дались {sum(v['итог'] == 'fail' for v in verdicts.values())} "
                    f"сайтов — массовый сбой (сеть GitHub), срывы этого сбора не считаю")
    for source in schedule_sources(conn):
        config = load_config(source)
        if config.get("by_server"):
            continue                       # П1/П7: его качает сервер
        if source["status"] in OWNER_STATUSES:
            continue                       # закрыт владельцем — его решение
        verdict = verdicts.get(bare(source["domain"]))
        if not verdict:
            continue
        if verdict["итог"] == "fail" and (kind != "сбор" or mass):
            continue                       # скан, дозабор, массовый — только обнуляют
        event = apply_probe(config, verdict, crawl, now)
        if not event or event == "same":
            continue
        save_config(conn, source["id"], config)
        streak = int(config.get("gh_fail_streak") or 0)
        if event == "reset":
            said.append(f"{source['domain']}: дался GitHub — счёт срывов обнулён")
        else:
            said.append(f"{source['domain']}: не дался GitHub {sites_word(streak)} "
                        f"подряд ({config.get('gh_fail_why')})")
        if event == "fail" and streak == FAILS_TO_MOVE:
            note(conn, f"{source['domain']}: {sites_word(streak)} подряд не дался "
                       f"GitHub (последний раз: {config.get('gh_fail_why')}) — утром "
                       f"(06:40) сервер проверит его одним адресом; откроется "
                       f"серверу — переведу сайт на сервер")
    if kind == "сбор":
        said += apply_return_probe(conn, report.get(SECTION), now)
    return said


# ── П2. кандидаты: проверка с сервера одним адресом и перевод ───────────────

def candidates(conn, now: datetime) -> list[dict]:
    """П2: кандидаты на перевод — счёт ≥ `FAILS_TO_MOVE`, не `by_server`, с
    сервера не проверяли `CHECK_GAP_HOURS`. Порядок: ни разу не
    проверенные, потом давно проверенные (по кругу, никто не застревает)."""
    out = []
    for source in schedule_sources(conn):
        config = load_config(source)
        if config.get("by_server") or source["status"] in OWNER_STATUSES:
            continue
        if int(config.get("gh_fail_streak") or 0) < FAILS_TO_MOVE:
            continue
        last = parse_stamp(config.get("server_check_last"))
        if last is not None and now - last < timedelta(hours=CHECK_GAP_HOURS):
            continue
        out.append({"id": source["id"], "domain": source["domain"],
                    "config": config, "last": config.get("server_check_last") or ""})
    out.sort(key=lambda c: (bool(c["last"]), c["last"], c["domain"]))
    return out


def free_mb() -> int | None:
    """П2: MemAvailable из /proc/meminfo, МБ; не Linux — None."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def checks_today(conn, now: datetime) -> int:
    """П2: сколько разовых проверок уже было в эти киевские сутки."""
    from . import db
    try:
        items = json.loads(db.get_setting(conn, CHECKS_KEY) or "[]")
    except ValueError:
        items = []
    day = now.astimezone(KYIV).strftime("%Y-%m-%d")
    return sum(1 for it in items if isinstance(it, dict)
               and str(it.get("когда") or "").startswith(day))


def remember_check(conn, domain: str, row: dict, now: datetime) -> None:
    """П2: записать разовую проверку в память (`CHECKS_KEY`)."""
    from . import db
    try:
        items = json.loads(db.get_setting(conn, CHECKS_KEY) or "[]")
    except ValueError:
        items = []
    items = [it for it in items if isinstance(it, dict)]
    items.append({"когда": stamp(now), "домен": domain,
                  "итог": row.get("итог") or "", "почему": (row.get("почему") or "")[:120]})
    db.set_setting(conn, CHECKS_KEY, json.dumps(items[-CHECKS_KEEP:], ensure_ascii=False))


def check_refusal(taken: int, today: int, free: int | None,
                  limit: int = SITES_PER_RUN) -> str:
    """П2: можно ли проверить ещё один сайт. Пусто — можно; иначе — почему
    нет (дальше в этом заходе не проверяем никого)."""
    if taken >= limit:
        return f"за один заход проверяю не больше {limit} сайтов"
    if today >= CHECKS_PER_DAY:
        return f"за сутки уже {today} разовых проверок (предел {CHECKS_PER_DAY})"
    if free is None:
        return "не знаю, сколько свободной памяти"
    if free < MIN_FREE_MB:
        return f"свободно {free} МБ памяти, нужно не меньше {MIN_FREE_MB}"
    return ""


def decide_check(domain: str, config: dict, row: dict) -> tuple[str, str]:
    """П2: итог проверки одним адресом с сервера → (действие, слова).
    move — сервер скачал страницу с расписанием: переводим;
    alarm — не скачал, первый раз в серии: ТРЕВОГА (письмо владельцу);
    stay — не скачал, тревога в серии уже была: строка без тревоги."""
    streak = int(config.get("gh_fail_streak") or 0)
    github = f"{sites_word(streak)} подряд не дался GitHub ({config.get('gh_fail_why') or '—'})"
    if row.get("итог") == OK:
        return "move", (f"{domain}: {github}, а сервер скачал его страницу с "
                        f"расписанием — ПЕРЕВЕДЁН НА СЕРВЕР: дальше его качает "
                        f"сервер раз в сутки (06:40) на {MOVED_WINDOW_DAYS} дн.; "
                        f"раз в неделю GitHub пробует его одним адресом — "
                        f"откроется, сайт вернётся на GitHub сам")
    server = " ".join(f"{row.get('итог') or 'не дошли'}: {row.get('почему') or ''}".split())[:160]
    if not config.get("server_fail_alarm"):
        return "alarm", (f"ТРЕВОГА — {domain} не отвечает ни GitHub ({github}), "
                         f"ни серверу ({server}): переводить некуда, расписания "
                         f"с сайта нет. Нужен ваш взгляд — сайт лёг, сменил "
                         f"адрес или закрылся для всех дата-центров")
    return "stay", (f"{domain}: всё ещё не отвечает ни GitHub ({github}), ни "
                    f"серверу ({server}); письмо об этом уходило "
                    f"{day_month(config['server_fail_alarm'])}")


def call_set_mode(set_mode, conn, domain: str, by_server: bool, why: str) -> str:
    """П2/П4: `plan_push.set_mode(..., by="auto")`; его сбой (git завис,
    база занята) не обрывает заход — слова сбоя идут в строку владельцу."""
    try:
        return set_mode(conn, domain, by_server, by="auto", why=why)
    except Exception as beda:              # noqa: BLE001 — см. выше
        return f"перевод не доделан: {type(beda).__name__}: {beda}"[:200]


def move_to_server(conn, source_id: int, domain: str, now: datetime,
                   set_mode) -> str:
    """П2: перевод на сервер: `set_mode(conn, домен, True, by="auto")`
    (база + план + push; счёт обнуляет `on_mode_change`), отметка «сервер
    скачал», клеймо «сломан» снято (как у кнопки «Качать сервером»).
    Возвращает слова `set_mode`."""
    said = call_set_mode(set_mode, conn, domain, True,
                         f"автоматически: {FAILS_TO_MOVE}+ сбора подряд не дался GitHub")
    row = conn.execute("SELECT selector_config FROM sources WHERE id = ?",
                       (source_id,)).fetchone()
    config = load_config(row) if row else {}
    config["server_ok_last"] = stamp(now)
    save_config(conn, source_id, config)
    conn.execute("UPDATE sources SET status = 'ok', fail_count = 0 WHERE id = ?",
                 (source_id,))
    conn.commit()
    return said


def server_turn(conn, now: datetime, fetch_one, plan_sources: dict,
                set_mode, busy: str = "", only: str = "",
                free=free_mb, limit: int = SITES_PER_RUN) -> list[str]:
    """П2: утренний заход (или `--once <домен>`): проверить кандидатов
    одним адресом каждого и решить. `fetch_one(источник плана)` → строка
    отчёта (итог, почему) — ОДИН адрес (`crawl_fetch.проба_одним_адресом`);
    `plan_sources` — {домен: источник плана}; `busy` — почему сейчас нельзя
    (идёт заливка); `only` — проверить только этот домен (кандидат он или
    нет — переводим только кандидата). Возвращает строки журнала."""
    said = []
    queue = candidates(conn, now)
    if only:
        queue = [c for c in queue if bare(c["domain"]) == bare(only)]
        if not queue:
            row = next((r for r in schedule_sources(conn)
                        if bare(r["domain"]) == bare(only)), None)
            if row is None:
                return [f"{only}: такого включённого источника расписания нет"]
            config = load_config(row)
            if config.get("by_server"):
                return [f"{only}: уже качает сервер — проверять нечего"]
            last = parse_stamp(config.get("server_check_last"))
            if last is not None and now - last < timedelta(hours=CHECK_GAP_HOURS):
                return [f"{only}: сервер проверял его {config['server_check_last']} — "
                        f"к сайту не чаще раза в {CHECK_GAP_HOURS} ч"]
            queue = [{"id": row["id"], "domain": row["domain"], "config": config,
                      "last": ""}]
    if not queue:
        return said
    if busy:
        text = (f"проверку {len(queue)} сайт(ов) с сервера откладываю — {busy}; "
                f"следующая попытка утром")
        note(conn, text)
        return [text]
    today = checks_today(conn, now)
    taken = 0                  # сколько сайтов скачано в этот заход
    for place, cand in enumerate(queue):
        domain, config = cand["domain"], cand["config"]
        source = plan_sources.get(domain) or plan_sources.get(bare(domain))
        if source is None:
            text = f"{domain}: в плане обхода сайта нет — проверить с сервера нечем"
            note(conn, text)
            said.append(text)
            continue
        refusal = check_refusal(taken, today, free(), limit)
        if refusal:
            rest = ", ".join(c["domain"] for c in queue[place:])
            text = f"не проверил с сервера: {rest} — {refusal}; следующая попытка утром"
            note(conn, text)
            said.append(text)
            break
        try:
            row = fetch_one(source)
        except Exception as beda:          # noqa: BLE001 — остальные кандидаты идут дальше
            row = {"итог": "не дошли", "почему": f"{type(beda).__name__}: {beda}"[:160]}
        taken += 1
        today += 1
        remember_check(conn, domain, row, now)
        config["server_check_last"] = stamp(now)
        if row.get("итог") == OK:
            config["server_ok_last"] = stamp(now)
        streak = int(config.get("gh_fail_streak") or 0)
        if streak < FAILS_TO_MOVE:
            # `--once` руками по сайту, который не кандидат: только итог в
            # журнал — без перевода, без строки и письма
            save_config(conn, cand["id"], config)
            said.append(f"{domain}: сервер — {row.get('итог') or 'не дошли'} "
                        f"{row.get('почему') or ''}; не кандидат (не дался GitHub "
                        f"{sites_word(streak)} подряд, нужно {FAILS_TO_MOVE}) — "
                        f"ничего не меняю".replace("  ", " "))
            continue
        action, text = decide_check(domain, config, row)
        if action == "alarm":
            config["server_fail_alarm"] = stamp(now)
        save_config(conn, cand["id"], config)
        if action == "move":
            text += f" ({move_to_server(conn, cand['id'], domain, now, set_mode)})"
        note(conn, text)
        said.append(text)
    return said


# ── П3. глубина серверного сбора ────────────────────────────────────────────

def server_depth(config: dict, days_arg: int = 0) -> int:
    """П3: на сколько дней сервер качает сайт `by_server`."""
    if days_arg:
        return int(days_arg)
    if int(config.get("max_days") or 0) > 0:
        return int(config["max_days"])
    if config.get("moved_by") == "auto":
        return MOVED_WINDOW_DAYS
    return OWNER_DEFAULT_DAYS


# ── П4. обратный путь: проба вернуть на GitHub ──────────────────────────────

def on_github(env=None) -> bool:
    """П4: обход идёт на самом GitHub Actions (проба возврата — только там:
    с адреса сервера она сказала бы «открылся» и вернула сайт зря)."""
    import os
    return (env if env is not None else os.environ).get("GITHUB_ACTIONS") == "true"


def return_memory(path) -> dict:
    """П4: память проб возврата на GitHub ({домен: {с, когда, итог}})."""
    return _read_json(path) or {}


def _utc(text) -> datetime | None:
    return parse_stamp(text, timezone.utc)


def return_due(sources: list[dict], memory: dict,
               now: datetime) -> tuple[list[str], dict]:
    """П4 (GitHub): кому из сайтов `by_server` плана пора пробу возврата —
    (домены, новая память). Вернувшихся (уже не `by_server`) память
    забывает; впервые увиденный «на сервере» сайт записывается с этой
    минуты («с») и ждёт `RETURN_EVERY_DAYS`; дальше — от прошлой пробы."""
    names = [s["domain"] for s in sources if s.get("by_server")]
    memory = {d: v for d, v in (memory or {}).items()
              if d in names and isinstance(v, dict)}
    due = []
    for domain in names:
        item = memory.get(domain)
        if item is None:
            memory[domain] = {"с": now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")}
            continue
        last = _utc(item.get("когда")) or _utc(item.get("с"))
        if last is None or now - last >= timedelta(days=RETURN_EVERY_DAYS):
            due.append(domain)
    return due, memory


def return_item(row: dict, now: datetime) -> dict:
    """П4 (GitHub): запись раздела «проба_возврата» report.json."""
    return {"когда": now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "итог": row.get("итог") or "не дошли",
            "почему": (row.get("почему") or "")[:160],
            "url": row.get("url") or "", "чем": row.get("чем") or "",
            "адресов": 1, "открылось": 1 if row.get("итог") == OK else 0}


def return_remember(memory: dict, domain: str, row: dict, now: datetime) -> None:
    """П4 (GitHub): запомнить пробу возврата сайта."""
    item = dict(memory.get(domain) or {})
    item["когда"] = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    item["итог"] = row.get("итог") or "не дошли"
    memory[domain] = item


def return_opened(item: dict) -> bool:
    """П4: «больше половины адресов открылось» (из одного — открылся)."""
    try:
        total = int(item.get("адресов") or 1)
        opened = int(item.get("открылось") if item.get("открылось") is not None
                     else (1 if item.get("итог") == OK else 0))
    except (TypeError, ValueError):
        return False
    return total > 0 and opened * 2 > total


def apply_return_probe(conn, section, now: datetime) -> list[str]:
    """П4 (заливка сбора на сервере): итоги проб возврата → `gh_probe_last`;
    открылась — `gh_return` (утром `return_turn` вернёт сайт) и строка;
    нет — строка «остаётся на сервере». Сайты не `by_server` — мимо."""
    if not isinstance(section, dict) or not section:
        return []
    said = []
    by_name = {bare(r["domain"]): r for r in schedule_sources(conn)}
    for domain, item in section.items():
        source = by_name.get(bare(domain))
        if source is None or not isinstance(item, dict):
            continue
        config = load_config(source)
        if not config.get("by_server"):
            continue
        when = _utc(item.get("когда"))
        config["gh_probe_last"] = stamp(when or now)
        if return_opened(item):
            config["gh_return"] = config["gh_probe_last"]
            text = (f"{source['domain']}: недельная проба с GitHub ОТКРЫЛАСЬ "
                    f"(страница с расписанием) — утром (06:40) сервер вернёт "
                    f"сайт в обход GitHub")
        else:
            config.pop("gh_return", None)
            why = " ".join(f"{item.get('итог') or ''}: {item.get('почему') or ''}".split())
            text = (f"{source['domain']}: недельная проба с GitHub не открылась "
                    f"({why[:120]}) — сайт остаётся на сервере, следующая проба "
                    f"через {RETURN_EVERY_DAYS} дн.")
        save_config(conn, source["id"], config)
        note(conn, text)
        said.append(text)
    return said


def return_turn(conn, now: datetime, set_mode, busy: str = "") -> list[str]:
    """П4 (утро, 06:40): сайты с открывшейся пробой (`gh_return`) —
    `set_mode(False)` и строка владельцу. Владелец вернул сам — пометку
    снимаем молча."""
    said = []
    todo = []
    for source in schedule_sources(conn):
        config = load_config(source)
        if not config.get("gh_return"):
            continue
        if not config.get("by_server"):
            config.pop("gh_return", None)
            save_config(conn, source["id"], config)
            continue
        todo.append((source, config))
    if not todo:
        return said
    if busy:
        text = (f"возврат на GitHub ({', '.join(s['domain'] for s, _ in todo)}) "
                f"откладываю — {busy}; следующая попытка утром")
        note(conn, text)
        return [text]
    for source, config in todo:
        when = config.get("gh_return")
        words = call_set_mode(set_mode, conn, source["domain"], False,
                              "автоматически: недельная проба GitHub открылась")
        text = (f"{source['domain']}: проба с GitHub {day_month(when)} открылась — "
                f"сайт ВОЗВРАЩЁН в обход GitHub, сервер его больше не качает "
                f"({words})")
        note(conn, text)
        said.append(text)
    return said


def on_mode_change(config: dict, by_server: bool, by: str = "owner",
                   now: datetime | None = None) -> None:
    """П2/П4: перевод в любую сторону (`plan_push.set_mode`, и кнопкой) —
    счёт срывов и пометки возврата с нуля; на сервер — кто и когда
    перевёл (`moved_by`, `moved_at`); на GitHub — их снимаем."""
    now = now or datetime.now(KYIV)
    for key in STREAK_FIELDS + ("gh_fail_last_slot", "gh_return"):
        config.pop(key, None)
    if by_server:
        config["moved_by"] = "auto" if by == "auto" else "owner"
        config["moved_at"] = stamp(now)
    else:
        for key in ("moved_by", "moved_at", "gh_probe_last"):
            config.pop(key, None)


# ── П5. что видит владелец ──────────────────────────────────────────────────

def mark(config: dict) -> str:
    """П5: пометка у сайта: «переведён на сервер автоматически 13.10» и т. п.
    Пусто — сказать нечего."""
    if config.get("by_server"):
        if config.get("moved_by") == "auto":
            text = f"переведён на сервер автоматически {day_month(config.get('moved_at'))}"
        elif config.get("moved_at"):
            text = f"на сервер перевёл владелец {day_month(config.get('moved_at'))}"
        else:
            text = "на сервер перевёл владелец"
        if config.get("gh_return"):
            text += "; проба GitHub открылась — утром вернётся на GitHub"
        elif config.get("gh_probe_last"):
            text += f"; проба GitHub {day_month(config['gh_probe_last'])} не открылась"
        return text
    streak = int(config.get("gh_fail_streak") or 0)
    if streak:
        text = f"не дался GitHub {sites_word(streak)} подряд"
        if streak >= FAILS_TO_MOVE:
            text += " — кандидат на перевод, сервер проверит утром"
        return text
    return ""


def overview(conn) -> list[dict]:
    """П5: сайты «на сервере» и с серией срывов на GitHub — для раздела
    «Сломанных»: [{id, domain, mark, server}]."""
    out = []
    for source in schedule_sources(conn):
        config = load_config(source)
        text = mark(config)
        if text:
            out.append({"id": source["id"], "domain": source["domain"],
                        "mark": text, "server": bool(config.get("by_server")),
                        "server_ok": config.get("server_ok_last") or ""})
    out.sort(key=lambda x: (not x["server"], x["domain"]))
    return out

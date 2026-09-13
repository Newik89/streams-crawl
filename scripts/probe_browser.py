# -*- coding: utf-8 -*-
"""Проверка проблемных источников настоящим браузером.

Простой загрузчик страниц видит только исходный HTML. Многие сайты рисуют
расписание скриптом уже в браузере, поэтому у 39 источников доступ остался
непонятным, а три оказались «сломанными» из-за устаревших ссылок в закладках.

Скрипт открывает каждый такой сайт в настоящем браузере (Playwright), ждёт
отрисовки и ставит вердикт: расписание видно / просят войти / платно /
блокировка / пусто.

Правила: ОДИН заход на сайт, пауза между сайтами, страница сохраняется в
`recon/raw_browser/` — повторный запуск уже проверенные сайты пропускает.

Запуск:
    venv\\Scripts\\python.exe scripts/probe_browser.py
    venv\\Scripts\\python.exe scripts/probe_browser.py --limit 5   (для пробы)
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, protection, timemarks, urls  # noqa: E402

RAW = Path(__file__).resolve().parent.parent / "recon" / "raw_browser"
PAUSE_SECONDS = 3
NAV_TIMEOUT_MS = 45_000

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Поиск времени и опознание защиты — в app/timemarks.py и app/protection.py,
# общие с reanalyze_browser.py. Там же описано, на чём мы обжигались: координаты
# в картинках, время через точку, время, разорванное вёрсткой, и заглушки
# защиты не на английском.

# Просят войти. Слова взяты на языках наших источников.
LOGIN_MARKERS = ("sign in", "log in", "login", "войти", "увійти", "zaloguj",
                 "prihlásiť", "přihlásit", "giriş yap", "conectare",
                 "iniciar sesión", "accedi", "anmelden", "inloggen",
                 "bejelentkezés", "prijava", "влез")

PAID_MARKERS = ("subscribe", "subscription", "abonare", "abonament",
                 "abonnement", "abonament", "suscríbete", "abbonati",
                 "abonelik", "предплатен", "передплата", "podpiska",
                 "pay per view", "kup dostęp", "premium paketi")


# ── окно согласия на cookie ──────────────────────────────────────────────────
# Решение владельца (29.08.2026): сначала пытаемся ОТКЛОНИТЬ (кнопка «только
# необходимые» — так меньше отслеживания), и лишь если такой кнопки нет —
# соглашаемся, иначе до расписания не добраться.

REJECT_TEXTS = [
    "reject all", "reject", "decline", "only necessary", "necessary only",
    "essential only", "continue without accepting", "refuser", "tout refuser",
    "continuer sans accepter", "ablehnen", "alle ablehnen", "nur notwendige",
    "odmítnout", "odmietnuť", "odrzuć", "odbij", "odbaci", "samo neophodne",
    "zavrni", "elutasítás", "elutasítom", "rifiuta", "rechazar",
    "solo necesarias", "weigeren", "alleen noodzakelijk", "reddet",
    "sadece gerekli", "απόρριψη", "απορριψη ολων", "отказ", "отхвърли",
    "відхилити", "отклонить", "respinge", "refuz",
]

ACCEPT_TEXTS = [
    "accept all", "accept", "i accept", "agree", "i agree", "got it",
    "tout accepter", "accepter", "j'accepte", "alle akzeptieren",
    "akzeptieren", "zustimmen", "souhlasím", "přijmout", "prijať",
    "akceptuję", "zgadzam się", "prihvaćam", "prihvati", "sprejmi",
    "elfogadom", "accetta", "aceptar", "accepteren", "akkoord",
    "kabul ediyorum", "kabul et", "αποδοχή", "приемам", "приймаю",
    "прийняти", "de acord", "sunt de acord", "ok",
]


# ── сохранение копии страницы ────────────────────────────────────────────────
# Раньше копия обрезалась на 600 000 знаков. Обрыв попадал в середину `<style>`
# или картинки, закрывающего тега не оставалось — и оформление засчитывалось как
# текст: `protv.ro` получил «4607 меток времени» на пустой странице. Теперь
# сохраняем целиком, а тяжёлые страницы сжимаем.

GZIP_OVER = 2_000_000        # длиннее — кладём сжатой копией `.html.gz`


def save_page(domain: str, html: str) -> Path:
    """Сохраняет страницу целиком. Возвращает путь к копии."""
    plain, packed = RAW / f"{domain}.html", RAW / f"{domain}.html.gz"
    if len(html) > GZIP_OVER:
        with gzip.open(packed, "wt", encoding="utf-8") as fh:
            fh.write(html)
        plain.unlink(missing_ok=True)
        return packed
    plain.write_text(html, encoding="utf-8")
    packed.unlink(missing_ok=True)
    return plain


def url_marks(row) -> dict:
    """Значения меток шаблона (`{channel}`, `{slug}`, `{channel_id}`) — лежат
    в `selector_config` под ключом `url_marks`."""
    try:
        cfg = json.loads(row["selector_config"] or "{}")
    except (TypeError, ValueError):
        return {}
    marks = cfg.get("url_marks")
    return marks if isinstance(marks, dict) else {}


def today_url(row) -> str:
    """Адрес на сегодня. В закладках у половины сайтов стоит дата того дня,
    когда закладку сделали (`protv.ro/program?day=5-4-2025`), и по ней приходит
    прошлогодняя страница. Если у источника есть шаблон и все его метки нам
    известны — идём по нему, иначе по обычному адресу."""
    url = urls.resolve(row["url_pattern"], row["base_url"], **url_marks(row))
    return row["base_url"] if "{" in url else url


def saved(domain: str) -> bool:
    """Копия страницы уже есть — обычная или сжатая."""
    return ((RAW / f"{domain}.html").exists()
            or (RAW / f"{domain}.html.gz").exists())


def error_text(e: Exception) -> str:
    """Короткая, но осмысленная запись ошибки: одного имени класса мало —
    по `Error` не понять, истёк ли таймаут, не нашёлся ли адрес или сайт
    оборвал соединение."""
    msg = " ".join(str(e).split())
    if len(msg) > 200:
        msg = msg[:200] + "…"
    return f"{type(e).__name__}: {msg}" if msg else type(e).__name__


def dismiss_cookie_banner(page) -> str:
    """Закрывает окно согласия. Возвращает, что именно сделали."""
    for frame in page.frames:
        for texts, what in ((REJECT_TEXTS, "отклонили"), (ACCEPT_TEXTS, "приняли")):
            for t in texts:
                try:
                    el = frame.get_by_role(
                        "button", name=re.compile(rf"^\s*{re.escape(t)}\s*$", re.I)
                    ).first
                    if el.count() and el.is_visible(timeout=800):
                        el.click(timeout=2500)
                        page.wait_for_timeout(1200)
                        return f"cookie: {what} «{t}»"
                except Exception:
                    continue
    # часть баннеров — обычные ссылки, а не кнопки
    for texts, what in ((REJECT_TEXTS, "отклонили"), (ACCEPT_TEXTS, "приняли")):
        for t in texts:
            try:
                el = page.get_by_text(
                    re.compile(rf"^\s*{re.escape(t)}\s*$", re.I)).first
                if el.count() and el.is_visible(timeout=600):
                    el.click(timeout=2500)
                    page.wait_for_timeout(1200)
                    return f"cookie: {what} «{t}» (ссылка)"
            except Exception:
                continue
    return ""


def verdict(text: str, html: str) -> tuple[str, str, str, str]:
    """→ (access, status, parse_level, заметка)"""
    text = timemarks.normalize(text)
    low = text.lower()
    time_hits = timemarks.count(text)

    # Защита сама по себе не приговор: у части сайтов она стоит, а расписание
    # при этом читается. Закрытым считаем только тот, где расписания нет.
    if protection.is_blocked(text, html) and time_hits < 5:
        name = protection.guess_name(html)
        return ("unknown", "closed", "D",
                f"браузер тоже не пустили: защита{' (' + name + ')' if name else ''}")

    has_json = any(m in html for m in ('application/ld+json', '__NEXT_DATA__',
                                       '__NUXT_DATA__', '__NUXT__',
                                       '__INITIAL_STATE__'))

    if time_hits >= 5:
        level = "A" if has_json else "B"
        note = f"в браузере видно расписание: {time_hits} меток времени"
        if has_json:
            note += ", есть готовый JSON"
        how = timemarks.describe(text)
        if how:
            note += f", {how}"
        return "open", "ok", level, note

    # Слова «подписка» и «войти» встречаются и на нормальных страницах:
    # у `programme-tv.net` слово `abonnement` стоит в списке провайдеров, и
    # сайт из-за этого записали в платные, хотя расписание на нём открыто.
    # Поэтому эти признаки смотрим ТОЛЬКО когда расписания на странице нет.
    login = any(m in low for m in LOGIN_MARKERS)
    paid = any(m in low for m in PAID_MARKERS)
    if paid and time_hits < 5:
        return "paid", "closed", "D", "расписания нет, на странице речь о подписке"
    if login and time_hits < 5:
        return "registration", "closed", "D", "расписания нет, предлагают войти"

    if len(text.strip()) < 400:
        return "unknown", "broken", "D", "страница пустая — проверьте адрес"
    return "unknown", "new", "D", f"расписание не опознано ({time_hits} меток времени)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="проверить только N сайтов")
    ap.add_argument("--all", action="store_true",
                    help="перепроверить и уже сохранённые")
    ap.add_argument("--only", default="", help="только эти домены, через запятую")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    RAW.mkdir(parents=True, exist_ok=True)
    conn = db.connect()
    rows = conn.execute(
        "SELECT id, domain, base_url, url_pattern, selector_config FROM sources "
        "WHERE status IN ('closed','broken') OR access <> 'open' "
        "ORDER BY domain").fetchall()

    if args.only:
        wanted = {d.strip() for d in args.only.split(",") if d.strip()}
        rows = [r for r in rows if r["domain"] in wanted]
    todo = [r for r in rows
            if args.all or args.only or not saved(r['domain'])]
    if args.limit:
        todo = todo[:args.limit]

    print(f"проблемных источников: {len(rows)}, проверяю: {len(todo)}")
    if not todo:
        return 0

    ok = failed = 0
    with sync_playwright() as pw:
        # Часть сайтов распознаёт автоматический браузер и отдаёт пустую
        # страницу. Убираем самые заметные признаки: флаг AutomationControlled
        # и свойство navigator.webdriver.
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-features=IsolateOrigins,site-per-process"])
        ctx = browser.new_context(user_agent=UA, locale="en-US",
                                  ignore_https_errors=True,
                                  viewport={"width": 1366, "height": 900})
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            "window.chrome = window.chrome || {runtime: {}};"
            "Object.defineProperty(navigator, 'languages', "
            "{get: () => ['en-US', 'en']});"
            "Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});")
        for i, r in enumerate(todo, 1):
            domain, url = r["domain"], today_url(r)
            page = ctx.new_page()
            cookie_note = ""
            try:
                page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)          # даём скриптам дорисовать
                cookie_note = dismiss_cookie_banner(page)
                if cookie_note:
                    page.wait_for_timeout(2000)      # после закрытия окна дорисовка

                # Ленивая загрузка: часть сайтов (atv.com.tr, trt.net.tr)
                # подтягивает расписание только когда до него доскроллили.
                for _ in range(4):
                    page.mouse.wheel(0, 2200)
                    page.wait_for_timeout(900)
                page.keyboard.press("End")
                page.wait_for_timeout(1500)

                html = page.content()
                text = page.inner_text("body")
                save_page(domain, html)
                access, status, level, note = verdict(text, html)
                if cookie_note:
                    note = f"{note}; {cookie_note}"
                ok += 1
            except Exception as e:
                access, status, level = "unknown", "broken", "D"
                note = f"браузер не открыл: {error_text(e)}"
                failed += 1
            finally:
                page.close()

            conn.execute(
                "UPDATE sources SET access=?, status=?, parse_level=?, needs_js=1, "
                "access_checked_at=?, notes=? WHERE id=?",
                (access, status, level,
                 datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                 note, r["id"]))
            conn.commit()
            print(f"[{i}/{len(todo)}] {domain:26} {access:13} {note}")
            time.sleep(PAUSE_SECONDS)
        browser.close()

    print(f"\nоткрылось: {ok}, не открылось: {failed}")
    for line in conn.execute(
            "SELECT access, COUNT(*) c FROM sources GROUP BY access ORDER BY c DESC"):
        print(f"  {line['access']:14} {line['c']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

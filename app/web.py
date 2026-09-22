# -*- coding: utf-8 -*-
"""Админка Streams Schedule.

Вход по паролю, дальше — управление источниками. Аутентификация своя, на
stdlib (сессия Flask + CSRF + ограничение попыток входа) — тот же подход,
что в соседнем проекте Sports Stream Schedule, без Flask-Login.

Пароль берётся из переменной окружения `STREAMS_ADMIN_PASSWORD` — своя,
отдельная от соседнего проекта Sports Stream Schedule (у него `ADMIN_PASSWORD`,
и путать их нельзя: разные проекты — разные пароли). Для локальной обкатки
`run_local.py` выставляет `STREAMS_LOCAL=1`, и тогда — и только тогда —
разрешён пароль по умолчанию `admin`.

Запуск: python run_local.py
"""

from __future__ import annotations

import os
import re
import secrets
import time
from datetime import datetime, timedelta
from collections import defaultdict
from zoneinfo import ZoneInfo

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   session, url_for)

from . import crawl_hook, db, dictionary, health, names, sources, store, trigger

LOCAL_MODE = os.environ.get("STREAMS_LOCAL") == "1"
_ENV_PASSWORD = os.environ.get("STREAMS_ADMIN_PASSWORD")
ADMIN_PASSWORD = _ENV_PASSWORD or ("admin" if LOCAL_MODE else None)

LOGIN_WINDOW = 300         # окно в секундах
LOGIN_MAX_ATTEMPTS = 5
_LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)

#: Отдавать ли расписание наружу по API (ТЗ разд. 13).
#: Решение владельца 01.09.2026: **пока закрыто для чужих сайтов**. Ключи в
#: базе не трогаем и не отзываем — просто рубильник выключен, и по нему все
#: адреса `/api/v1/…` отвечают `403`. Открыть: переменная окружения
#: `STREAMS_API=on` (и слово владельца).
API_OPEN = os.environ.get("STREAMS_API", "").strip().lower() in {
    "1", "on", "open", "yes", "true"}

KYIV = ZoneInfo("Europe/Kyiv")
PUBLIC_RUN_COOLDOWN = 3600   # публичная кнопка «2 days»: не чаще раза в час
SITE_DAYS = 6                # окно кнопки «Обойти сайт»: как у утреннего,
                             # чтобы сайт пересобрался целиком, а не на 2 дня


def _days_choice(raw: str | None) -> int:
    """Окно из формы кнопки: 2, 5 или 6 суток (6 — с аудита 07.09, A1: «сегодня
    + 6» целиком); всё прочее — 2. Список тот же, что в `crawl.yml` (days)."""
    return int(raw) if raw in ("5", "6") else 2


def _secret_key() -> str:
    """Ключ подписи сессии. На сервере — из переменной окружения. Локально —
    из файла рядом с базой: иначе после каждого перезапуска придётся входить
    заново. Файл в .gitignore, в репозиторий не попадает."""
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    if not LOCAL_MODE:
        return secrets.token_hex(32)
    keyfile = db.db_path().parent / ".secret_key"
    if not keyfile.exists():
        keyfile.parent.mkdir(parents=True, exist_ok=True)
        keyfile.write_text(secrets.token_hex(32), encoding="utf-8")
    return keyfile.read_text(encoding="utf-8").strip()


def create_app() -> Flask:
    app = Flask(__name__)

    @app.template_filter("from_json")
    def _from_json(text):
        """Строка лога прогона → словарь: шаблону нужно достать «режим»."""
        import json as _json
        try:
            return _json.loads(text or "{}")
        except (ValueError, TypeError):
            return {}

    # схема могла подрасти между выкладками (новые колонки): досыпаем их до
    # первого запроса, иначе витрина упала бы на «no such column»
    try:
        db.init_db()
    except Exception as e:                                   # noqa: BLE001
        print(f"схема базы не обновлена ({type(e).__name__}: {e})")
    app.secret_key = _secret_key()
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    @app.after_request
    def security_headers(resp):
        # витрина — свой HTML и один inline-скрипт, чужого кода нет
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "frame-ancestors 'none'")
        return resp

    # ── защита ───────────────────────────────────────────────────────────────

    def csrf_token() -> str:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)
        return session["csrf_token"]

    def verify_csrf() -> None:
        if not secrets.compare_digest(request.form.get("csrf_token", ""),
                                      session.get("csrf_token", "")):
            abort(400)

    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["ROLES"] = sources.ROLES
    app.jinja_env.globals["ACCESS"] = sources.ACCESS
    app.jinja_env.globals["STATUSES"] = sources.STATUSES

    def site_crawl_status() -> dict | None:
        """Строка под шапкой админки про кнопку «Обойти сайт»: заказан →
        идёт → ✅ ВЫПОЛНЕН (владелец 20.09: флеш пропадает при обновлении,
        а итога рядом не видно). Живёт сутки, дальше прячется."""
        conn = db.connect()
        try:
            req_raw = db.get_setting(conn, "site_crawl_request")
            res_raw = db.get_setting(conn, "site_crawl_result")
            run = crawl_hook.running(conn)
        finally:
            conn.close()
        req = (req_raw.split("|") + ["", ""])[:2] if req_raw else None
        res = (res_raw.split("|") + ["", "", ""])[:3] if res_raw else None
        now = datetime.now()

        def минуло(stamp: str, минут: int) -> bool:
            try:
                return now - datetime.strptime(stamp, "%Y-%m-%d %H:%M") \
                    > timedelta(minutes=минут)
            except ValueError:
                return True
        # заявка свежее итога — показываем ход дела
        if req and (not res or res[1] < req[1]):
            if минуло(req[1], 24 * 60):
                return None
            if run and (run["what"] == f"сайт {req[0]}"
                        or run["what"] == f"site-{req[0]}"):
                return {"cls": "ok",
                        "text": f"Обход сайта {req[0]}: идёт с {run['since']}…"}
            if минуло(req[1], 30):
                return {"cls": "error",
                        "text": f"Обход сайта {req[0]}: заказан в {req[1][-5:]}, "
                                "итог так и не доехал — смотрите «Прогоны»"}
            return {"cls": "ok",
                    "text": f"Обход сайта {req[0]}: заказан в {req[1][-5:]}, "
                            "ждём прогона…"}
        if res and not минуло(res[1], 24 * 60):
            return {"cls": "ok",
                    "text": f"Обход сайта {res[0]}: ✅ ВЫПОЛНЕН в {res[1][-5:]}, "
                            f"отметок каналов: {res[2]}"}
        return None
    app.jinja_env.globals["site_crawl_status"] = site_crawl_status

    def full_crawl_status() -> dict | None:
        """Та же строка для полного обхода с пульта витрины (2/5/6 дней,
        скан даты): заказан → идёт → ✅ ВЫПОЛНЕН (владелец 22.09: со
        страницы расписания не видно, запустился ли обход и чем он
        кончился). Живёт сутки, дальше прячется."""
        conn = db.connect()
        try:
            line = health.request_line(conn)
            run = crawl_hook.running(conn)
        finally:
            conn.close()
        if not line:
            return None
        try:
            asked = datetime.strptime(line["asked"], "%Y-%m-%d %H:%M")
        except ValueError:
            return None
        if datetime.now() - asked > timedelta(hours=24):
            return None
        name = line["what"].capitalize()
        if line["done"]:
            tail = f", влито {line['import']}" if line["import"] else ""
            return {"cls": "ok",
                    "text": f"{name}: ✅ ВЫПОЛНЕН — собрано {line['crawl']}"
                            f"{tail}"}
        # замок точечного обхода — не про этот заказ, его строка своя
        if run and not run["what"].startswith(("сайт ", "site-")):
            if run["state"] == "идёт":
                return {"cls": "ok",
                        "text": f"{name}: идёт с {run['since']}…"}
            return {"cls": "ok",
                    "text": f"{name}: заказан в {asked:%H:%M}, "
                            "ждём прогона…"}
        if datetime.now() - asked > timedelta(minutes=30):
            return {"cls": "error",
                    "text": f"{name}: заказан в {asked:%H:%M}, итог так и "
                            "не доехал — смотрите «Прогоны»"}
        return {"cls": "ok",
                "text": f"{name}: заказан в {asked:%H:%M}, ждём прогона…"}
    app.jinja_env.globals["full_crawl_status"] = full_crawl_status

    def too_many_attempts(ip: str) -> bool:
        now = time.time()
        _LOGIN_ATTEMPTS[ip] = [t for t in _LOGIN_ATTEMPTS[ip] if now - t < LOGIN_WINDOW]
        return len(_LOGIN_ATTEMPTS[ip]) >= LOGIN_MAX_ATTEMPTS

    # публичное: страница расписания (ТЗ разд. 12), её кнопки сбора и
    # API по ключу (разд. 13). Всё остальное — только после входа.
    PUBLIC = {"login", "static", "schedule", "schedule_run", "crawl_hook_in",
              "api_events", "api_leagues", "api_channels", "api_status"}

    @app.before_request
    def require_login():
        if request.endpoint in PUBLIC:
            return None
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return None

    # ── вход ─────────────────────────────────────────────────────────────────

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("admin"):
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            ip = request.remote_addr or "?"
            if too_many_attempts(ip):
                flash("Слишком много попыток. Подождите 5 минут.", "error")
                return render_template("login.html")
            if not ADMIN_PASSWORD:
                flash("Пароль не задан: нужна переменная STREAMS_ADMIN_PASSWORD.",
                      "error")
                return render_template("login.html")
            if secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
                session.clear()
                session["admin"] = True
                return redirect(request.args.get("next") or url_for("dashboard"))
            _LOGIN_ATTEMPTS[ip].append(time.time())
            flash("Неверный пароль.", "error")

        return render_template("login.html",
                               local_mode=LOCAL_MODE and not _ENV_PASSWORD)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ── дашборд ──────────────────────────────────────────────────────────────

    @app.route("/")
    def dashboard():
        conn = db.connect()
        try:
            scan = {"request": db.get_setting(conn, "day_scan_request"),
                    "result": db.get_setting(conn, "day_scan_result"),
                    "imported": db.get_setting(conn, "last_import")}
            return render_template("dashboard.html", c=sources.counts(conn),
                                   db_path=db.db_path(), scan=scan,
                                   h=health.summary(conn),
                                   req=health.request_line(conn))
        finally:
            conn.close()

    @app.route("/admin")
    @app.route("/schedule/admin")
    def admin_alias():
        """Интуитивные адреса админки: владелец набирал /schedule/admin и
        получал Not Found (04.09) — ведём на дашборд."""
        return redirect(url_for("dashboard"))

    # ── источники ────────────────────────────────────────────────────────────

    @app.route("/sources")
    def sources_list():
        conn = db.connect()
        try:
            f = {k: request.args.get(k, "") for k in
                 ("q", "role", "status", "access", "level", "enabled", "protection")}
            rows = sources.list_sources(conn, **f)
            return render_template("sources.html", rows=rows, f=f,
                                   c=sources.counts(conn))
        finally:
            conn.close()

    @app.route("/sources/<int:source_id>", methods=["GET", "POST"])
    def source_edit(source_id: int):
        conn = db.connect()
        try:
            if request.method == "POST":
                verify_csrf()
                action = request.form.get("action", "save")
                if action == "save":
                    sources.update_source(conn, source_id, request.form.to_dict())
                    flash("Сохранено.", "ok")
                elif action == "add_url":
                    ok = sources.add_url(conn, source_id, request.form.get("url", ""))
                    flash("Ссылка добавлена." if ok else "Такая ссылка уже есть.",
                          "ok" if ok else "error")
                elif action == "delete_url":
                    sources.delete_url(conn, int(request.form["url_id"]))
                    flash("Ссылка удалена.", "ok")
                return redirect(url_for("source_edit", source_id=source_id))

            row = sources.get_source(conn, source_id)
            if not row:
                abort(404)
            return render_template("source.html", s=row,
                                   urls=sources.get_urls(conn, source_id))
        finally:
            conn.close()

    @app.route("/sources/<int:source_id>/toggle", methods=["POST"])
    def source_toggle(source_id: int):
        verify_csrf()
        conn = db.connect()
        try:
            new = sources.toggle_enabled(conn, source_id)
            flash("Источник включён." if new else "Источник выключен.", "ok")
        finally:
            conn.close()
        return redirect(request.form.get("back") or url_for("sources_list"))

    @app.route("/sources/<int:source_id>/fix", methods=["POST"])
    def source_fix(source_id: int):
        """Со страницы «Сломанные»: поправить адрес и вернуть сайт в обход.

        Владелец 09.09: «тут должна быть возможность отредактировать ссылку
        и вернуть назад в обход». Сайт чаще всего не сломан — у него сменился
        адрес; правим строку и снимаем клеймо, чтобы следующий обход зашёл.
        """
        verify_csrf()
        back = request.form.get("back") or url_for("broken")
        url = (request.form.get("base_url") or "").strip()
        action = request.form.get("action") or "save"
        if action in ("probe", "probe_github"):
            # проверка адреса из ЭТОГО поля, ничего не сохраняя (20.09)
            return _probe_source(source_id, url,
                                 "github" if action == "probe_github"
                                 else "server", back)
        revive = action == "revive"
        conn = db.connect()
        try:
            row = conn.execute("SELECT domain, base_url, status FROM sources "
                               "WHERE id = ?", (source_id,)).fetchone()
            if row is None:
                flash("Источника нет.", "error")
                return redirect(back)
            said = []
            if url and url != (row["base_url"] or ""):
                conn.execute("UPDATE sources SET base_url = ? WHERE id = ?",
                             (url, source_id))
                said.append("адрес сохранён")
            if revive:
                # счётчик сбоев обнуляем: три новых сбоя снова пометят сайт
                # сломанным, а до тех пор он ходит в обход как обычно
                conn.execute("UPDATE sources SET status = 'ok', fail_count = 0, "
                             "enabled = 1 WHERE id = ?", (source_id,))
                said.append("вернул в обход")
            conn.commit()
            flash(f"{row['domain']}: " + (", ".join(said) or "менять нечего"),
                  "ok" if said else "error")
        finally:
            conn.close()
        return redirect(back)

    def _probe_source(source_id: int, typed: str, через: str, back: str):
        """«Проверить сервером / GitHub-ом» (владелец 20.09).

        Проверяется адрес ИЗ ПОЛЯ — вписанный туда новый пробуется, ничего
        не сохраняя: «вставить ссылку и прогнать, прежде чем менять». Поле
        не трогали — берётся адрес, каким ходит обход (из плана). С сервера
        ответ мгновенный; с GitHub уходит заявка-тег, и итог появляется на
        этой же странице через пару минут (стук обхода).
        """
        conn = db.connect()
        try:
            row = conn.execute("SELECT domain, base_url FROM sources "
                               "WHERE id = ?", (source_id,)).fetchone()
            if row is None:
                flash("Источника нет.", "error")
                return redirect(back)
            domain, saved = row["domain"], row["base_url"] or ""
        finally:
            conn.close()
        from . import plan_push
        # нетронутое поле держит сохранённый адрес-витрину — тогда пробуем
        # рабочий адрес обхода; вписали новое — пробуем ровно его
        target = typed if typed and typed != saved             else (plan_push.probe_url(domain) or saved)
        if not target:
            flash(f"{domain}: нет адреса для пробы.", "error")
            return redirect(back)
        if через == "github":
            ok, words = trigger.push_request_tag(
                "probeurl", trigger.encode_probe_url(target))
            if ok:
                words = ("проба с GitHub заказана — итог появится на этой "
                         "странице через 2–3 минуты")
            flash(f"{domain}: {words} ({target[:100]})", "ok" if ok else "error")
            return redirect(back)
        try:
            import requests as _rq
            answer = _rq.get(target, timeout=25, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/128.0 Safari/537.36"})
            size = len(answer.content or b"")
            if answer.status_code == 200 and size > 2000:
                flash(f"{domain}: серверу отвечает (HTTP 200, {size // 1024} КБ) "
                      f"по адресу {target[:100]} — сайт жив; если GitHub он не "
                      "пускает, можно перевести на серверный сбор.", "ok")
            else:
                flash(f"{domain}: сервер получил HTTP {answer.status_code}, "
                      f"{size} байт ({target[:100]}) — похоже, сайт лежит или "
                      "закрыт и для нас.", "error")
        except Exception as exc:                        # noqa: BLE001
            flash(f"{domain}: с сервера не отвечает ({type(exc).__name__}, "
                  f"{target[:100]}) — лежит весь сайт либо адрес неверный.",
                  "error")
        return redirect(back)

    @app.route("/sources/<int:source_id>/mode", methods=["POST"])
    def source_mode(source_id: int):
        """Кнопки «Качать сервером» / «Вернуть на GitHub» (владелец 20.09).

        Меняет пометку в базе и те же поля в плане обхода, план уезжает на
        GitHub сам (`app/plan_push.py`) — руками больше ничего делать не надо.
        """
        verify_csrf()
        back = request.form.get("back") or url_for("broken")
        by_server = request.form.get("mode") == "server"
        conn = db.connect()
        try:
            row = conn.execute("SELECT domain FROM sources WHERE id = ?",
                               (source_id,)).fetchone()
            if row is None:
                flash("Источника нет.", "error")
                return redirect(back)
            from . import plan_push
            said = plan_push.set_mode(conn, row["domain"], by_server)
            if by_server:
                # серверный сбор ходит только к живым: клеймо «сломан» снимаем
                conn.execute("UPDATE sources SET status = 'ok', fail_count = 0 "
                             "WHERE id = ?", (source_id,))
                conn.commit()
            flash(said, "ok")
        finally:
            conn.close()
        return redirect(back)

    @app.route("/sources/<int:source_id>/delete", methods=["POST"])
    def source_delete(source_id: int):
        verify_csrf()
        conn = db.connect()
        try:
            sources.delete_source(conn, source_id)
            flash("Источник удалён совсем.", "ok")
        finally:
            conn.close()
        return redirect(request.form.get("back") or url_for("sources_list"))

    # ── добавление пачкой ────────────────────────────────────────────────────

    @app.route("/sources/bulk", methods=["GET", "POST"])
    def sources_bulk():
        report = None
        if request.method == "POST":
            verify_csrf()
            conn = db.connect()
            try:
                report = sources.bulk_add(conn, request.form.get("urls", ""))
            finally:
                conn.close()
        return render_template("bulk.html", report=report)

    # ── отдельные вкладки: закрытые и сломанные ──────────────────────────────

    @app.route("/closed")
    def closed():
        """Здесь только то, с чего расписание НЕ читается: сайт не пускает
        совсем либо доступ не подтверждён.

        Сайты, у которых защита стоит, но расписание браузером читается,
        тут не показываются: они рабочие и живут в общем списке источников
        с пометкой защиты (решение владельца 29.08.2026). Раньше их выносили
        сюда отдельным списком, и шесть рабочих источников выглядели
        проблемными."""
        conn = db.connect()
        try:
            blocked = conn.execute(
                "SELECT * FROM sources WHERE status = 'closed' "
                "OR access IN ('registration','paid') ORDER BY access, domain").fetchall()
            unchecked = conn.execute(
                "SELECT * FROM sources WHERE access = 'unknown' AND status <> 'closed' "
                "AND protection IS NULL ORDER BY domain").fetchall()
            return render_template("closed.html", blocked=blocked,
                                   unchecked=unchecked)
        finally:
            conn.close()

    #: сколько суток без матчей считаем молчанием источника. 3 → 2 по слову
    #: владельца 10.09: обходов два в день, три дня ждать беду слишком долго
    SILENT_DAYS = 2

    @app.route("/broken")
    def broken():
        """Здоровье источников (ТЗ разд. 18): кто не открывается и кто молчит.

        «Сломан» ставится сам после трёх сбоев подряд — но только когда
        страница не открылась или пришла заглушка защиты. Сайт, который
        отвечает, но перестал давать матчи (обычно поменял разметку), в эту
        колонку не попадёт: для него вторая таблица, «Молчат».
        """
        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM sources WHERE status = 'broken' ORDER BY domain"
            ).fetchall()
            edge = (datetime.now() - timedelta(days=SILENT_DAYS)).strftime("%Y-%m-%d")
            silent = conn.execute(
                "SELECT * FROM sources WHERE enabled = 1 AND role = 'schedule' "
                "AND status NOT IN ('broken', 'closed', 'parked') "
                "AND last_run IS NOT NULL "
                "AND (last_success IS NULL OR substr(last_success, 1, 10) < ?) "
                "ORDER BY last_success IS NOT NULL, last_success, domain",
                (edge,)).fetchall()
            return render_template("health.html", rows=rows, silent=silent,
                                   silent_days=SILENT_DAYS)
        finally:
            conn.close()

    # ── публичное расписание (этап 4) ────────────────────────────────────────

    @app.route("/schedule")
    def schedule():
        conn = db.connect()
        try:
            games = store.schedule(conn)
            # когда сбор был в последний раз — внизу витрины (владелец 09.09)
            info = health.summary(conn)
        finally:
            conn.close()
        # значения для выпадашек фильтров — из самих игр, пустых не предлагаем
        leagues_ = sorted({g["league"] for g in games if g["league"]})
        channels_ = sorted({c["name"] for g in games for c in g["channels"]})
        sports_ = sorted({g["sport"] for g in games if g["sport"]})
        by_date: dict = {}
        for g in games:
            by_date.setdefault(g["date"], []).append(g)
        return render_template("schedule.html", by_date=by_date,
                               leagues=leagues_, channels=channels_,
                               sports=sports_, total=len(games),
                               admin=bool(session.get("admin")), h=info)

    @app.route("/rename", methods=["POST"])
    def rename():
        """Кнопка ✎ на витрине: закрепить правильное имя команды или лиги.
        Алиас вяжется к СЫРОМУ имени с сайта — тогда следующий обход снова
        попадёт в тот же канон. Маршрут не в PUBLIC: только после входа."""
        verify_csrf()
        kind = request.form.get("kind", "")
        raw = (request.form.get("raw") or "").strip()
        canonical = (request.form.get("canonical") or "").strip()
        if kind not in ("team", "league") or not raw or not canonical:
            abort(400)
        conn = db.connect()
        try:
            # слово владельца: написание остаётся только за этим каноном,
            # иначе спорное имя словарь не отдаёт и правка бы не держалась
            if kind == "team":
                dictionary.remember_team(conn, raw, canonical, sole=True)
            else:
                dictionary.remember_league(conn, raw, canonical, sole=True)
            # то же имя могло прийти и в показанном виде (транслит) — свяжем
            # и его, чтобы правка держалась при любом написании
            shown = (request.form.get("shown") or "").strip()
            if shown and shown != raw:
                if kind == "team":
                    dictionary.remember_team(conn, shown, canonical, sole=True)
                else:
                    dictionary.remember_league(conn, shown, canonical,
                                               sole=True)
        finally:
            conn.close()
        return jsonify({"ok": True, "canonical": canonical})

    # ── запуск обхода кнопкой (ТЗ разд. 12 и 14) ─────────────────────────────

    def _dispatch(days: int, date: str = "") -> bool:
        # сбор уже заказан или идёт — второй не запускаем (владелец 14.09)
        conn = db.connect()
        try:
            busy = crawl_hook.running(conn)
        finally:
            conn.close()
        if busy:
            flash(f"Сбор уже {busy['state']} с {busy['since']} ({busy['what']}) — "
                  "второй не запускаю, дождитесь окончания.", "error")
            return False
        # сперва прямой запуск (мгновенно, если есть ключ GitHub); без
        # ключа — заявка-тег: её ловит workflow и стартует обход сам
        ok, words = trigger.dispatch_crawl(days, date=date)
        if not ok:
            ok, words = trigger.push_request_tag(
                "date" if date else "days", date or str(days))
        if ok:
            conn = db.connect()
            try:
                crawl_hook.mark(conn, "заявка",
                                f"date-{date}" if date else f"days-{days}")
                if not date:
                    # заказ запоминаем: дальше панель «Здоровье» сама скажет,
                    # дошёл ли он до конца — раньше надпись просто исчезала
                    # (владелец 09.09)
                    db.set_setting(conn, "crawl_request",
                                   f"обход {days} сут.|"
                                   f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
            finally:
                conn.close()
        tail = (f" — скан {date}" if date else
                f" — окно {days} дн., результат появится после прогона")
        flash(words + (tail if ok else ""), "ok" if ok else "error")
        return ok

    @app.route("/hook/crawl", methods=["POST"])
    def crawl_hook_in():
        """Стук GitHub: «начал» запирает кнопки, «закончил» отпирает, а при
        удаче сервер ещё и забирает результат (`app/crawl_hook.py`)."""
        event = request.headers.get("X-Event", "")
        what = request.headers.get("X-What", "")[:60]
        conn = db.connect()
        try:
            ok, why = crawl_hook.verify(conn, request.headers.get("X-Stamp", ""),
                                        event, what,
                                        request.headers.get("X-Sign", ""))
            if not ok:
                print(f"стук отклонён: {why} ({request.remote_addr})")
                return jsonify({"ok": False}), 403
            if event == "start":
                crawl_hook.mark(conn, "идёт", what or "обход")
                return jsonify({"ok": True})
            crawl_hook.clear(conn)
            if what.startswith("probeurl-"):
                # итог проверки адреса кнопкой (владелец 20.09): показать на
                # странице сбоев; результата в репо нет — забор не нужен
                stamp = datetime.now().strftime("%d.%m %H:%M")
                db.set_setting(conn, "url_probe_result",
                               f"{stamp}|{what[len('probeurl-'):]}")
                return jsonify({"ok": True, "pull": "это проба адреса"})
        finally:
            conn.close()
        said = crawl_hook.start_pull() if event == "done-ok" else "забор не нужен"
        return jsonify({"ok": True, "pull": said})

    @app.route("/games/<int:event_id>/seen", methods=["POST"])
    def game_seen(event_id: int):
        """Клик по строке игры гасит её «новизну» (владелец 21.09: новая
        висит, пока не прочитал)."""
        verify_csrf()
        if not session.get("admin"):
            abort(403)
        conn = db.connect()
        try:
            conn.execute("UPDATE events SET seen = 1 WHERE id = ?", (event_id,))
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True})

    @app.route("/games/<int:event_id>/channels/<int:channel_id>/seen",
               methods=["POST"])
    def channel_seen(event_id: int, channel_id: int):
        """Клик по каналу на витрине (владелец 22.09, с любого устройства):
        живой зелёный — гасит его «new» (seen=1); снятый перечёркнутый —
        прячет отметку из списка игры насовсем (seen=2). Что именно кликнули,
        решает база: витрина показывает живую отметку, пока есть хоть одна."""
        verify_csrf()
        if not session.get("admin"):
            abort(403)
        conn = db.connect()
        try:
            alive = conn.execute(
                "SELECT 1 FROM event_channels WHERE event_id = ? "
                "AND channel_id = ? AND miss_count < ? LIMIT 1",
                (event_id, channel_id, store.MISS_LIMIT)).fetchone()
            conn.execute("UPDATE event_channels SET seen = ? "
                         "WHERE event_id = ? AND channel_id = ?",
                         (1 if alive else 2, event_id, channel_id))
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True})

    @app.route("/games/seen-all", methods=["POST"])
    def games_seen_all():
        """Кнопка «Прочитано всё»: снять новизну разом (владелец 21.09).
        С 22.09 гасит и зелёные каналы — они той же природы «непрочитанного»."""
        verify_csrf()
        if not session.get("admin"):
            abort(403)
        conn = db.connect()
        try:
            n = conn.execute("UPDATE events SET seen = 1 "
                             "WHERE seen = 0").rowcount
            # только живые отметки: снятые «Прочитано всё» не прячет —
            # их владелец убирает кликом поштучно
            conn.execute("UPDATE event_channels SET seen = 1 "
                         "WHERE seen = 0 AND miss_count < ?",
                         (store.MISS_LIMIT,))
            conn.commit()
        finally:
            conn.close()
        flash(f"Прочитано: пометка «новая» снята с {n} игр.", "ok")
        return redirect(url_for("schedule"))

    @app.route("/channel-name", methods=["POST"])
    def channel_name():
        """Правка канала прямо на витрине (просьба владельца 10.09).

        Два поля: `name` — само название, его и копирует клик; `note` —
        пометка перед ним («AL», «New-AL»), она видна, но в буфер не идёт.
        Раньше владелец вписывал приставку в имя, и она копировалась вместе
        с названием.
        """
        verify_csrf()
        if not session.get("admin"):
            abort(403)
        try:
            channel_id = int(request.form.get("id") or 0)
        except ValueError:
            channel_id = 0
        name = " ".join((request.form.get("name") or "").split())
        note = " ".join((request.form.get("note") or "").split())[:16]
        if not channel_id or not name:
            return jsonify({"ok": False, "why": "пустое имя"}), 400
        conn = db.connect()
        try:
            row = conn.execute("SELECT canonical_name, country FROM channels "
                               "WHERE id = ?", (channel_id,)).fetchone()
            if row is None:
                return jsonify({"ok": False, "why": "канала нет"}), 404
            # канал опознаётся парой (имя, страна): тёзку из своей страны
            # заводить нельзя, иначе отметки разъедутся по двум записям
            twin = conn.execute(
                "SELECT id FROM channels WHERE canonical_name = ? AND "
                "IFNULL(country,'') = IFNULL(?,'') AND id <> ?",
                (name, row["country"], channel_id)).fetchone()
            if twin:
                return jsonify({"ok": False,
                                "why": f"такое имя уже у канала #{twin['id']}"}), 409
            conn.execute("UPDATE channels SET canonical_name = ?, note = ?, "
                         "custom_name = 1 WHERE id = ?",
                         (name, note or None, channel_id))
            if row["canonical_name"] != name:
                # прежнее имя остаётся алиасом: связки обхода не теряются
                уже = conn.execute(
                    "SELECT 1 FROM channel_aliases WHERE channel_id = ? AND "
                    "alias = ?", (channel_id, row["canonical_name"])).fetchone()
                if not уже:
                    conn.execute("INSERT INTO channel_aliases (channel_id, alias) "
                                 "VALUES (?, ?)", (channel_id, row["canonical_name"]))
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True, "name": name, "note": note})

    @app.route("/crawl/run", methods=["POST"])          # админка: без лимитов
    def crawl_run():
        verify_csrf()
        _dispatch(_days_choice(request.form.get("days")))
        return redirect(request.referrer or url_for("dashboard"))

    @app.route("/crawl/day", methods=["POST"])          # календарь владельца
    def crawl_day():
        """Скан одной даты: выбранный в календаре день пересобирается
        отдельным прогоном (05.09). Дальше недели сетки обычно пусты —
        соберётся то, что сайты уже опубликовали."""
        verify_csrf()
        raw = (request.form.get("date") or "").strip()
        try:
            chosen = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            flash("Дата не разобрана.", "error")
            return redirect(request.referrer or url_for("dashboard"))
        today = datetime.now().date()
        if not (today <= chosen <= today + timedelta(days=13)):
            flash("Дата должна быть от сегодня до +13 дней.", "error")
            return redirect(request.referrer or url_for("dashboard"))
        if _dispatch(2, date=chosen.isoformat()):
            conn = db.connect()
            try:
                db.set_setting(conn, "day_scan_request",
                               f"{chosen.isoformat()}|"
                               f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
            finally:
                conn.close()
        return redirect(request.referrer or url_for("dashboard"))

    @app.route("/crawl/site", methods=["POST"])         # кнопка «Обойти сайт»
    def crawl_site():
        """Точечный прогон ОДНОГО сайта (владелец 20.09): «чтоб не гонять
        весь план, когда нужен только один сайт». Обычный сайт качает GitHub:
        итог едет отдельной папкой results/site/ и вливается вдобавок к
        полному, чужие каналы не гасятся (A7 — заливка знает по report.json,
        какие домены отработали). Сайт с пометкой «качает сервер» качает сам
        сервер — не чаще раза в сутки (слово владельца 10.09)."""
        verify_csrf()
        back = (request.form.get("back") or request.referrer
                or url_for("sources_list"))
        domain = (request.form.get("domain") or "").strip().lower()
        import json as _json
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id, domain, enabled, status, selector_config "
                "FROM sources WHERE domain = ?", (domain,)).fetchone()
            if row is None:
                flash("Такого сайта в источниках нет.", "error")
                return redirect(back)
            config = _json.loads(row["selector_config"] or "{}") or {}
            if config.get("by_server"):
                return _crawl_site_by_server(domain, back)
            # закрытые/отложенные в план обхода не попадают (app/crawl.py):
            # прогон для них скачал бы пустоту — лучше сказать честно
            if not row["enabled"] or row["status"] in (
                    "new", "deferred", "closed", "parked"):
                беда = ("выключен" if not row["enabled"] else "состояние «"
                        + sources.STATUSES.get(row["status"], row["status"]) + "»")
                flash(f"{domain} сейчас не в плане обхода ({беда}) — "
                      "сначала включите его и верните в обход.", "error")
                return redirect(back)
            busy = crawl_hook.running(conn)
            if busy:
                flash(f"Сбор уже {busy['state']} с {busy['since']} "
                      f"({busy['what']}) — дождитесь окончания.", "error")
                return redirect(back)
            ok, words = trigger.dispatch_crawl(SITE_DAYS, only=domain)
            if not ok:
                ok, words = trigger.push_request_tag(
                    "site", trigger.encode_probe_url(domain))
            if ok:
                crawl_hook.mark(conn, "заявка", f"сайт {domain}")
                # для строки статуса «заказан → идёт → ВЫПОЛНЕН» (владелец
                # 20.09: флеш пропадает, а итога рядом не видно)
                db.set_setting(conn, "site_crawl_request",
                               f"{domain}|{datetime.now():%Y-%m-%d %H:%M}")
                flash(f"Обход только {domain} заказан — итог вольётся на "
                      "витрину через несколько минут после прогона.", "ok")
            else:
                flash(f"{domain}: {words}", "error")
        finally:
            conn.close()
        return redirect(back)

    def _crawl_site_by_server(domain: str, back: str):
        """Серверные сайты (mojtv.hr, rtrs.tv): качает сам сервер, «даже
        кнопкой не больше раза в сутки» (владелец 10.09). Память заходов —
        results/server_crawl.json, порог общий — crawl_hook.SITE_GAP_HOURS."""
        import json as _json
        помню = {}
        try:
            помню = _json.loads((db.ROOT / "results" / "server_crawl.json")
                                .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        было = (помню.get(domain) or {}).get("когда") or ""
        try:
            прошлый = datetime.strptime(было, "%Y-%m-%d %H:%M")
            рано = (datetime.now() - прошлый
                    < timedelta(hours=crawl_hook.SITE_GAP_HOURS))
        except ValueError:
            рано = False
        if рано:
            flash(f"{domain} качает сам сервер, и он уже ходил туда {было}. "
                  "Чаще раза в сутки к сайту не ходим — попробуйте позже.",
                  "error")
            return redirect(back)
        ok, said = crawl_hook.start_site_crawl(domain)
        if ok:
            conn = db.connect()
            try:
                db.set_setting(conn, "site_crawl_request",
                               f"{domain}|{datetime.now():%Y-%m-%d %H:%M}")
            finally:
                conn.close()
        flash(f"{domain}: {said}", "ok" if ok else "error")
        return redirect(back)

    @app.route("/schedule/run", methods=["POST"])       # публичная: с уздой
    def schedule_run():
        verify_csrf()
        days = _days_choice(request.form.get("days"))
        conn = db.connect()
        try:
            busy = crawl_hook.running(conn)
            if busy:                         # до узды: занятость — не попытка
                flash(f"Collection is already {busy['state_en']} (since "
                      f"{busy['since']}) — please wait until it finishes.", "error")
                return redirect(url_for("schedule"))
            if session.get("admin"):
                pass    # вошедший владелец: без PIN и без часовой паузы (20.09)
            elif days != 2:                  # длинное окно гостю — только по PIN
                pin = os.environ.get("STREAMS_PIN", "")
                if not pin or not secrets.compare_digest(
                        request.form.get("pin", ""), pin):
                    flash("Wrong PIN.", "error")
                    return redirect(url_for("schedule"))
            else:
                last = db.get_setting(conn, "public_run_at")
                if last and time.time() - float(last) < PUBLIC_RUN_COOLDOWN:
                    wait = int((PUBLIC_RUN_COOLDOWN - (time.time() - float(last))) // 60) + 1
                    flash(f"Please wait ~{wait} min between runs.", "error")
                    return redirect(url_for("schedule"))
                db.set_setting(conn, "public_run_at", str(time.time()))
        finally:
            conn.close()
        _dispatch(days)
        return redirect(url_for("schedule"))

    # ── API (ТЗ разд. 13): read-only JSON по ключу ───────────────────────────

    def api_key_ok() -> bool:
        key = request.headers.get("X-API-Key", "")
        if not key:
            return False
        conn = db.connect()
        try:
            return conn.execute("SELECT 1 FROM api_keys WHERE key = ? "
                                "AND revoked = 0", (key,)).fetchone() is not None
        finally:
            conn.close()

    def api_guard():
        if not API_OPEN:
            return jsonify({"error": "API closed",
                            "detail": "расписание пока не отдаётся наружу"}), 403
        if not api_key_ok():
            return jsonify({"error": "valid X-API-Key header required"}), 401
        return None

    def _api_game(g: dict) -> dict:
        start = g["start"].replace(tzinfo=KYIV)
        return {
            "id": g["id"], "sport": g["sport"],
            "date_kyiv": g["start"].strftime("%d.%m %H:%M"),
            "date_kyiv_iso": start.isoformat(),
            "league": g["league"], "league_id": g["league_id"],
            "league_slug": g["league_slug"],
            "team_home": g["home"], "team_away": g["away"],
            "league_auto": g["league_auto"],
            "team_home_auto": g["home_auto"], "team_away_auto": g["away_auto"],
            "channels": g["channels"],
            "is_live": g["live"], "first_seen": g["first_seen"],
        }

    @app.route("/api/v1/events")
    def api_events():
        denied = api_guard()
        if denied:
            return denied
        conn = db.connect()
        try:
            games = store.schedule(conn)
        finally:
            conn.close()
        a = request.args
        if a.get("date_from"):
            games = [g for g in games if str(g["date"]) >= a["date_from"]]
        if a.get("date_to"):
            games = [g for g in games if str(g["date"]) <= a["date_to"]]
        if a.get("sport"):
            games = [g for g in games if g["sport"] == a["sport"]]
        if a.get("league_id", "").isdigit():
            games = [g for g in games if g["league_id"] == int(a["league_id"])]
        if a.get("channel_id", "").isdigit():
            games = [g for g in games
                     if any(c["id"] == int(a["channel_id"]) for c in g["channels"])]
        if a.get("has_channels") == "1":
            games = [g for g in games if g["channels"]]
        if a.get("q"):
            q = a["q"].lower()
            games = [g for g in games if q in " ".join(
                [g["home"], g["away"], g["league"]]
                + [c["name"] for c in g["channels"]]).lower()]
        total = len(games)
        offset = int(a.get("offset") or 0)
        limit = min(int(a.get("limit") or 200), 500)
        return jsonify({"total": total, "offset": offset, "limit": limit,
                        "events": [_api_game(g) for g in games[offset:offset + limit]]})

    @app.route("/api/v1/leagues")
    def api_leagues():
        denied = api_guard()
        if denied:
            return denied
        conn = db.connect()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT id, slug, canonical_name AS name, sport, ignored "
                "FROM leagues ORDER BY canonical_name")]
        finally:
            conn.close()
        return jsonify({"leagues": rows})

    @app.route("/api/v1/channels")
    def api_channels():
        denied = api_guard()
        if denied:
            return denied
        conn = db.connect()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT id, slug, canonical_name AS name, country "
                "FROM channels WHERE enabled = 1 ORDER BY canonical_name")]
        finally:
            conn.close()
        return jsonify({"channels": rows})

    @app.route("/api/v1/status")
    def api_status():
        denied = api_guard()
        if denied:
            return denied
        conn = db.connect()
        try:
            events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            channels = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
            leagues_n = conn.execute("SELECT COUNT(*) FROM leagues").fetchone()[0]
            imported = db.get_setting(conn, "last_import")
        finally:
            conn.close()
        return jsonify({"events": events, "channels": channels,
                        "leagues": leagues_n, "last_import": imported})

    # ── прогоны ──────────────────────────────────────────────────────────────

    @app.route("/runs")
    def runs_list():
        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT finished_at, window_days, sources_ok, sources_failed, "
                "rows_found, events_upserted, log FROM runs "
                "ORDER BY id DESC LIMIT 60").fetchall()
        finally:
            conn.close()
        return render_template("runs.html", rows=rows)

    # ── настройки и ключи API ────────────────────────────────────────────────

    @app.route("/runs/<int:run_id>/failed")
    def run_failed(run_id: int):
        """Кто не пропустил обход в этом прогоне — с правкой адреса на месте.

        Владелец 09.09: «failed на витрине должно быть кликабельно и вести
        на страницу, где видно, какие сайты не пропустили обход, и там их
        можно отредактировать».
        """
        conn = db.connect()
        try:
            run = conn.execute(
                "SELECT id, finished_at, window_days, sources_ok, "
                "sources_failed, rows_found, events_upserted, log "
                "FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                flash("Такого прогона нет.", "error")
                return redirect(url_for("runs_list"))
            run = dict(run)
            run["what"] = health._what(run)
            import json as _json
            try:
                log = _json.loads(run["log"] or "{}") or {}
            except (ValueError, TypeError):
                log = {}
            fails = log.get("сбои") or {}
            why = log.get("сбои_почему") or {}
            # кто ходил на сайты: обычные прогоны — сеть GitHub Actions,
            # серверный сбор подписан «сервер …» (владелец 20.09: отчёт
            # должен прямо называть, кому сайт не отдал расписание)
            run["collector"] = log.get("кто") or "сеть GitHub"
            rows = []
            for domain, count in sorted(fails.items(), key=lambda kv: -kv[1]):
                # домен в логе записан без «www», в базе бывает по-разному
                src = conn.execute(
                    "SELECT id, domain, country, base_url, status, notes, "
                    "protection, last_success, selector_config FROM sources "
                    "WHERE domain = ? OR domain = ?",
                    (domain, "www." + domain)).fetchone()
                row = dict(src) if src else {"id": None, "domain": domain,
                                             "country": "", "base_url": "",
                                             "status": "", "notes": "",
                                             "protection": "",
                                             "last_success": ""}
                config = _json.loads(row.pop("selector_config", None)
                                     or "{}") or {}
                row["by_server"] = bool(config.get("by_server"))
                row["why"] = why.get(domain, "")
                row["fails"] = count
                rows.append(row)
            probe = (db.get_setting(conn, "url_probe_result") or "").split("|")
            probe = {"when": probe[0], "what": probe[1]} if len(probe) == 2 else None
            return render_template("run_failed.html", run=run, rows=rows,
                                   probe=probe)
        finally:
            conn.close()

    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        conn = db.connect()
        try:
            if request.method == "POST":
                verify_csrf()
                for sport in store.GRACE_MINUTES:
                    value = request.form.get(f"grace_{sport}", "").strip()
                    if value.isdigit() and 0 < int(value) <= 24 * 60:
                        db.set_setting(conn, f"grace_{sport}", value)
                flash("Сохранено.", "ok")
                return redirect(url_for("settings_page"))
            graces = store.grace_map(conn)
            keys = conn.execute("SELECT id, key, note, revoked, created_at "
                                "FROM api_keys ORDER BY id DESC").fetchall()
            has_github = bool(db.get_setting(conn, "github_token").strip()
                              or os.environ.get("STREAMS_GITHUB_TOKEN"))
        finally:
            conn.close()
        return render_template("settings.html", graces=graces, keys=keys,
                               api_open=API_OPEN, has_github=has_github)

    @app.route("/settings/github-token", methods=["POST"])
    def github_token():
        """Ключ GitHub для кнопок обхода — вставляется владельцем на сайте
        (05.09: секреты терминалом не носим). Пустая отправка удаляет ключ."""
        verify_csrf()
        value = (request.form.get("token") or "").strip()
        conn = db.connect()
        try:
            db.set_setting(conn, "github_token", value)
        finally:
            conn.close()
        flash("Ключ GitHub сохранён — кнопки обхода работают." if value
              else "Ключ GitHub удалён.", "ok")
        return redirect(url_for("settings_page"))

    @app.route("/settings/apikey", methods=["POST"])
    def apikey_action():
        verify_csrf()
        conn = db.connect()
        try:
            if request.form.get("action") == "revoke":
                conn.execute("UPDATE api_keys SET revoked = 1 WHERE id = ?",
                             (request.form.get("id", 0),))
                conn.commit()
                flash("Ключ отозван.", "ok")
            else:
                new_key = secrets.token_urlsafe(24)
                conn.execute("INSERT INTO api_keys (key, note) VALUES (?, ?)",
                             (new_key, request.form.get("note", "").strip()))
                conn.commit()
                flash("Ключ выдан — скопируйте его из таблицы.", "ok")
        finally:
            conn.close()
        return redirect(url_for("settings_page"))

    # ── очередь названий ─────────────────────────────────────────────────────

    @app.route("/channels")
    def channels_list():
        """Каналы словаря: имя+страна, их сайты и алиасы (этап 6)."""
        q = (request.args.get("q") or "").strip().lower()
        conn = db.connect()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT c.id, c.canonical_name AS name, c.country, "
                " (SELECT GROUP_CONCAT(DISTINCT s.domain) FROM channel_aliases a"
                "   JOIN sources s ON s.id = a.source_id"
                "   WHERE a.channel_id = c.id) AS sources, "
                " (SELECT GROUP_CONCAT(DISTINCT a.alias) FROM channel_aliases a"
                "   WHERE a.channel_id = c.id AND a.alias != c.canonical_name)"
                "   AS aliases, "
                # канал «в обходе», если он в списке поканального источника
                # ЛИБО его даёт живой сеточный сайт (tvarenasport и родня
                # отдают все каналы одной страницей, у них списка нет —
                # столбец врал «нет» на живых каналах, поймано 06.09)
                " (EXISTS(SELECT 1 FROM source_channels sc"
                "   WHERE sc.channel_id = c.id AND sc.include = 1)"
                "  OR EXISTS(SELECT 1 FROM channel_aliases a"
                "   JOIN sources s ON s.id = a.source_id"
                "   WHERE a.channel_id = c.id AND s.enabled = 1"
                "   AND s.role = 'schedule')) AS included "
                "FROM channels c ORDER BY c.canonical_name COLLATE NOCASE")]
        finally:
            conn.close()
        if q:
            rows = [r for r in rows if q in (r["name"] or "").lower()
                    or q in (r["country"] or "").lower()
                    or q in (r["sources"] or "").lower()
                    or q in (r["aliases"] or "").lower()]
        return render_template("channels.html", rows=rows, q=q)

    @app.route("/channels/<int:channel_id>/rename", methods=["POST"])
    def channel_rename(channel_id: int):
        """Переименовать канал прямо в списке (просьба владельца 09.09:
        «каналы редактировать я не могу»). Правится то, что видно на витрине:
        имя и приставка страны (пустая приставка — бейдж без «BG|»). Имена
        сайтов (алиасы) не трогаем — по ним обход узнаёт канал."""
        verify_csrf()
        name = (request.form.get("name") or "").strip()
        country = (request.form.get("country") or "").strip().upper()[:6]
        back = request.referrer or url_for("channels_list")
        if not name:
            flash("Пустое имя — не сохранил.", "error")
            return redirect(back)
        conn = db.connect()
        try:
            row = conn.execute("SELECT canonical_name, country FROM channels "
                               "WHERE id = ?", (channel_id,)).fetchone()
            if row is None:
                flash("Канала нет.", "error")
                return redirect(back)
            if row["canonical_name"] == name and (row["country"] or "") == country:
                return redirect(back)
            # канал опознаётся парой (имя, страна) — тёзку из своей же страны
            # заводить нельзя, иначе отметки разъедутся по двум записям
            twin = conn.execute(
                "SELECT id FROM channels WHERE canonical_name = ? AND "
                "IFNULL(country,'') = ? AND id <> ?",
                (name, country, channel_id)).fetchone()
            if twin:
                flash(f"«{name}» ({row['country'] or '—'}) уже есть — "
                      f"канал #{twin['id']}. Имя должно быть своё.", "error")
                return redirect(back)
            # `custom_name` — метка «имя правил владелец»: витрина покажет
            # его как есть, без приставки страны (правило владельца 09.09)
            conn.execute("UPDATE channels SET canonical_name = ?, country = ?, "
                         "custom_name = 1 WHERE id = ?",
                         (name, country or None, channel_id))
            # прежнее имя остаётся алиасом: старые связки не теряются.
            # `INSERT OR IGNORE` тут не спасает от дубля — уникальность в
            # таблице по паре (алиас, сайт), а у ручного алиаса сайта нет
            already = conn.execute(
                "SELECT 1 FROM channel_aliases WHERE channel_id = ? AND "
                "alias = ?", (channel_id, row["canonical_name"])).fetchone()
            if not already:
                conn.execute("INSERT INTO channel_aliases (channel_id, alias) "
                             "VALUES (?, ?)", (channel_id, row["canonical_name"]))
            conn.commit()
            flash(f"«{row['canonical_name']}» → «{name}»"
                  f"{' (' + country + ')' if country else ' (без приставки страны)'}.",
                  "ok")
        finally:
            conn.close()
        return redirect(back)

    def _sport_previews(conn, rows) -> list[dict]:
        """Английская подпись к строкам «Вид спорта»: иврит и греческий
        владелец читать не обязан (жалоба 15.09). Команды и лигу переводит
        словарь подтверждённых имён, незнакомое — транслит."""
        teams = dictionary.team_overrides(conn)
        лиги = dictionary.league_overrides(conn)

        def по_английски(текст: str, словарь: dict) -> str:
            текст = (текст or "").strip()
            if not текст:
                return ""
            if текст in словарь:
                return словарь[текст]
            if any(ord(c) > 0x2FF for c in текст):
                return names.suggest_canonical(текст)
            return текст

        out = []
        for r in rows:
            d = dict(r)
            if d.get("kind") == "sport":
                части = [x.strip() for x in (d["raw_value"] or "").split("|")]
                пара = части[0]
                лига = части[1] if len(части) > 2 else ""
                home, _, away = пара.partition(" - ")
                перевод = (f"{по_английски(home, teams)} - "
                           f"{по_английски(away, teams)}" if away
                           else по_английски(пара, teams))
                перевод_лиги = по_английски(лига, лиги)
                if перевод != пара or перевод_лиги != лига:
                    d["preview"] = " | ".join(
                        x for x in (перевод, перевод_лиги) if x)
            out.append(d)
        return out

    @app.route("/names")
    def moderation_list():
        conn = db.connect()
        try:
            kind = request.args.get("kind", "")
            # ?focus=<номер> — пришли с витрины по оранжевой строке игры:
            # эта запись идёт первой и подсвечивается (просьба владельца 10.09)
            focus = request.args.get("focus", type=int) or 0
            отложенные = request.args.get("later") == "1"
            # вкладка «Отсеянные»: закрытое без ответа — рукой или чисткой;
            # всё видно и возвращается кнопкой (условие владельца 15.09)
            отсеянные = request.args.get("rejected") == "1"
            if отсеянные:
                rows = dictionary.skipped_items(conn, kind or "sport")
            else:
                rows = dictionary.open_items(conn, kind, first=focus,
                                             later=отложенные)
            return render_template("moderation.html",
                                   rows=_sport_previews(conn, rows),
                                   later=отложенные, rejected=отсеянные,
                                   later_count=dictionary.later_count(conn),
                                   rejected_count=dictionary.skipped_count(
                                       conn, kind or "sport"),
                                   counts=dictionary.counts(conn), kind=kind,
                                   focus=focus,
                                   # куда вернуться: якорь строки витрины,
                                   # чтобы не листать расписание заново
                                   back=re.sub(r"[^a-zA-Z0-9]", "",
                                               request.args.get("back", ""))[:16])
        finally:
            conn.close()

    @app.route("/names/clear", methods=["POST"])
    def moderation_clear():
        """Кнопка «Очистить список»: стереть открытые строки «Вид спорта».

        Именно стереть, а не заблокировать (владелец 15.09): игры не
        запоминаются, и если матч ещё в сетке и всё ещё непонятен —
        следующий обход принесёт строку заново."""
        verify_csrf()
        conn = db.connect()
        try:
            стёрто = dictionary.clear_open(conn, "sport")
            flash(f"Список очищен: убрано строк — {стёрто}. Ничего не "
                  "заблокировано: непонятные матчи вернутся со следующим "
                  "обходом.", "ok")
        finally:
            conn.close()
        return redirect(url_for("moderation_list", kind="sport"))

    @app.route("/names/<int:item_id>", methods=["POST"])
    def moderation_resolve(item_id: int):
        verify_csrf()
        conn = db.connect()
        try:
            if request.form.get("action") == "skip":
                dictionary.skip(conn, item_id)
                flash("Пропущено — больше не спросим.", "ok")
            elif request.form.get("action") == "later":
                dictionary.later(conn, item_id)
                flash("Отложено — лежит во вкладке «Отложенные».", "ok")
            elif request.form.get("action") == "reopen":
                dictionary.back_to_open(conn, item_id)
                flash("Вернули в список.", "ok")
            else:
                try:
                    dictionary.resolve(conn, item_id,
                                       request.form.get("canonical", ""),
                                       request.form.get("country", "").strip())
                    flash("Закреплено.", "ok")
                except (ValueError, LookupError) as e:
                    flash(str(e), "error")
        finally:
            conn.close()
        return redirect(request.referrer or url_for("moderation_list"))

    return app

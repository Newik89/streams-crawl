# -*- coding: utf-8 -*-
r"""Канон задним числом: пройтись эталоном по играм, уже лежащим в базе.

Заливка ставит `team_id` только новым играм: у тех, кто попал в базу раньше,
чем словарь выучил их имена, канона нет — на витрине это фильтр «Names to
fix» (03.09 — 45 %). Скрипт берёт эталон flashscore из `results/games.json`
(7 дней + имена локалей), доучивает словарь по `fs_id`, сопоставляет игры
без канона с эталоном и проставляет `team_*_id`, лигу и `fs:` в flags;
время одиночных игр подтягивает (`canon.retime`). Сомнительное — в очередь
«Названия». Повторный запуск ничего не дублирует.

Гонять там, где живёт база, — на СЕРВЕРЕ, после обхода и games_import:
    ssh root@157.245.77.140 "cd streams-schedule && venv/bin/python scripts/canon_backfill.py"
Локально (черновая база):
    venv\Scripts\python.exe scripts/canon_backfill.py --file recon/probe_canon3/games.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app import canon, db, dictionary, names  # noqa: E402
from parse_live import REPEAT_GUESS_DOMAINS   # noqa: E402

DEFAULT = ROOT / "results" / "games.json"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DEFAULT),
                    help="games.json с ключом «эталон»")
    ap.add_argument("--dry-run", action="store_true",
                    help="посчитать и показать, ничего не записывая")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"нет {path} — сначала обход или git pull")
        return 1
    reference = json.loads(path.read_text(encoding="utf-8")).get("эталон", [])
    if not reference:
        print("в файле нет эталона — обход прошёл без flashscore?")
        return 1

    conn = db.connect()
    try:
        if not args.dry_run:
            teams, leagues = canon.learn_by_id(conn, reference)
            print(f"по fs_id локалей выучено: команд {teams}, лиг {leagues}")
        names.set_overrides(dictionary.team_overrides(conn))

        # Метка flashscore, с которой спорят буквы, — ошибка сверки, а не
        # правда: у футбольных строк maariv стоял баскетбол, и единственным
        # израильским кандидатом оказывался чужой матч Кубка («הפועל ר"ג —
        # מכבי נתניה» = Maccabi Rishon — Ironi Eilat; #2431, #2510, 14.09).
        # Метку и канон снимаем — игра сверяется заново ниже; вид спорта
        # берём у того эталона, где пара узнаётся уверенно
        by_flag = {f"fs:{r['fs_id']}": r for r in reference if r.get("fs_id")}
        sports = sorted({r.get("sport", "F") for r in reference})
        unflagged = 0
        for r in conn.execute(
                "SELECT id, sport, league_auto, team_home_auto, "
                "team_away_auto, start_kyiv, flags FROM events "
                "WHERE flags LIKE 'fs:%'").fetchall():
            ref = by_flag.get(r["flags"])
            if ref is None:
                continue
            game = {"id": r["id"], "sport": r["sport"] or "",
                    "home": r["team_home_auto"] or "",
                    "away": r["team_away_auto"] or "",
                    "league": r["league_auto"] or "",
                    "start_kyiv": r["start_kyiv"], "entries": []}
            if canon._pair_score(game, ref) >= canon.BRIDGE_FLOOR \
                    or canon._best_side(game, ref) >= canon.BRIDGE_BEST:
                continue
            sport = game["sport"]
            for other in sports:
                if other != sport and canon.align(
                        [dict(game, sport=other)], reference,
                        dictionary.league_overrides(conn))["sure"]:
                    sport = other
                    break
            unflagged += 1
            print(f"  метка снята: #{r['id']} {game['home']} — {game['away']}"
                  f" ≠ {ref.get('home')} — {ref.get('away')}"
                  + (f"; вид спорта {game['sport']} → {sport}"
                     if sport != game["sport"] else ""))
            if not args.dry_run:
                conn.execute(
                    "UPDATE events SET flags = NULL, team_home_id = NULL, "
                    "team_away_id = NULL, league_id = NULL, sport = ? "
                    "WHERE id = ?", (sport, r["id"]))
        if unflagged and not args.dry_run:
            conn.commit()

        # Id команды у игры без метки ставил словарь по написанию. Написание
        # оказалось чужим («מכבי ת"א» висело на Hapoel HaEmek — #2460 шла
        # «Hapoel HaEmek — Hapoel Jerusalem»; «Olympique M» — на M. Herzliya).
        # Словарь после чистки отвечает иначе — берём его ответ. Нет ответа,
        # потому что написание спорное («CSKA» — и Москва, и София), а id
        # среди его владельцев — оставляем как было (пакет C, 14.09)
        spelled = dictionary.team_alias_map(conn)
        owners_of: dict[str, set[int]] = {}
        for r in conn.execute("SELECT DISTINCT alias, team_id FROM team_aliases"):
            owners_of.setdefault(r["alias"], set()).add(r["team_id"])
        respelled = 0
        for r in conn.execute(
                "SELECT id, team_home_auto, team_away_auto, team_home_id, "
                "team_away_id FROM events WHERE flags IS NULL AND "
                "(team_home_id IS NOT NULL OR team_away_id IS NOT NULL)"
                ).fetchall():
            sets = {}
            for field, raw in (("team_home_id", r["team_home_auto"]),
                               ("team_away_id", r["team_away_auto"])):
                if r[field] is None:
                    continue
                raw = (raw or "").strip()
                known = spelled.get(raw)
                if known:
                    if known[0] != r[field]:
                        sets[field] = known[0]
                elif r[field] not in owners_of.get(raw, set()):
                    sets[field] = None
            if not sets:
                continue
            respelled += 1
            if respelled <= 10:
                print(f"  канон по словарю: #{r['id']} {r['team_home_auto']} — "
                      f"{r['team_away_auto']}: {sets}")
            if not args.dry_run:
                conn.execute("UPDATE events SET " +
                             ", ".join(f"{k} = ?" for k in sets) +
                             " WHERE id = ?", (*sets.values(), r["id"]))
        if respelled:
            if not args.dry_run:
                conn.commit()
            print(f"канон по словарю поправлен у игр без метки: {respelled}")

        # Имена по эталону (#2471, владелец 14.09): у игры с меткой flashscore
        # id команд ставил словарь ещё при заливке, а сверка дописывала только
        # пустые. «Racing» висит и на Racing Club, и на Racing Santander, и
        # аргентинский матч шёл «Racing Santander — Sarmiento Junin» при
        # верной метке. Эталон прав (владелец 04.09): id берём по его именам.
        # Не трогаем, только когда написание в словаре одно и закреплено за
        # своей командой — так держится ручная правка владельца (кнопка ✎)
        renamed = 0
        for r in conn.execute(
                "SELECT id, team_home_auto, team_away_auto, team_home_id, "
                "team_away_id, flags FROM events WHERE flags LIKE 'fs:%'"
                ).fetchall():
            ref = by_flag.get(r["flags"])
            if ref is None:
                continue
            sets = {}
            for field, raw, canon_name in (
                    ("team_home_id", r["team_home_auto"], ref.get("home")),
                    ("team_away_id", r["team_away_auto"], ref.get("away"))):
                canon_name = (canon_name or "").strip()
                if not canon_name or names.is_placeholder(canon_name):
                    continue
                row = conn.execute("SELECT id FROM teams WHERE canonical_name = ?",
                                   (canon_name,)).fetchone()
                if row and row["id"] == r[field]:
                    continue
                if r[field] is not None \
                        and owners_of.get((raw or "").strip()) == {r[field]}:
                    continue          # написание твёрдо за своей командой
                sets[field] = (row["id"] if row else None, canon_name)
            if not sets:
                continue
            renamed += 1
            if renamed <= 10:
                print(f"  имена по эталону: #{r['id']} {r['team_home_auto']} — "
                      f"{r['team_away_auto']} → {ref.get('home')} — {ref.get('away')}")
            if args.dry_run:
                continue
            values = {field: team_id if team_id else dictionary.remember_team(
                          conn, canon_name, canon_name)
                      for field, (team_id, canon_name) in sets.items()}
            conn.execute("UPDATE events SET " +
                         ", ".join(f"{k} = ?" for k in values) +
                         " WHERE id = ?", (*values.values(), r["id"]))
        if renamed:
            if not args.dry_run:
                conn.commit()
            print(f"имена поставлены по эталону у игр с меткой: {renamed}")

        rows = conn.execute(
            "SELECT id, sport, league_auto, team_home_auto, team_away_auto, "
            "start_kyiv FROM events "
            "WHERE team_home_id IS NULL OR team_away_id IS NULL").fetchall()
        games = [{"id": r["id"], "sport": r["sport"] or "",
                  "home": r["team_home_auto"] or "",
                  "away": r["team_away_auto"] or "",
                  "league": r["league_auto"] or "",
                  "start_kyiv": r["start_kyiv"], "entries": []}
                 for r in rows]
        print(f"игр без канона: {len(games)}")
        aligned = canon.align(games, reference,
                              dictionary.league_overrides(conn))
        print(f"сопоставлено уверенно {len(aligned['sure'])}, "
              f"на подтверждение {len(aligned['ask'])}, "
              f"не нашлось в эталоне {len(aligned['missed'])}")
        if args.dry_run:
            for game, ref, score in aligned["sure"][:15]:
                print(f"  {score:3}  {game['home']} - {game['away']}  →  "
                      f"{ref['home']} - {ref['away']}")
            return 0

        fixed, queued = canon.apply(conn, aligned)
        retimed = canon.retime(aligned)
        # Старые события лежат с именами БЕЗ пометки пола («Турция» при
        # эталонном «Turkey W»): глобальный алиас такой паре запрещён
        # (заражал бы мужские игры — canon._learnable), но САМОМУ событию
        # канон известен наверняка — проставляем id напрямую (06.09)
        direct = 0
        for game, ref, _ in aligned["sure"]:
            sets: dict[str, int] = {}
            for field, canon_name in (("team_home_id", ref.get("home")),
                                      ("team_away_id", ref.get("away"))):
                canon_name = (canon_name or "").strip()
                if canon_name:
                    sets[field] = dictionary.remember_team(
                        conn, canon_name, canon_name)
            if sets:
                direct += conn.execute(
                    "UPDATE events SET " +
                    ", ".join(f"{k}=?" for k in sets) +
                    " WHERE id=? AND (team_home_id IS NULL "
                    "OR team_away_id IS NULL)",
                    (*sets.values(), game["id"])).rowcount
        # свежие алиасы → проставить id всем событиям, чьи сырые имена
        # словарь теперь знает (не только сопоставленным сейчас)
        # только бесспорные написания: «Dinamo» трёх клубов id не ставит
        alias_ids = {alias: team_id for alias, (team_id, _)
                     in dictionary.team_alias_map(conn).items()}
        league_ids = {alias: league_id for alias, (league_id, _)
                      in dictionary.league_alias_map(conn).items()}
        stamped = 0
        for r in conn.execute(
                "SELECT id, league_auto, team_home_auto, team_away_auto "
                "FROM events WHERE team_home_id IS NULL "
                "OR team_away_id IS NULL").fetchall():
            sets = {}
            home_id = alias_ids.get((r["team_home_auto"] or "").strip())
            away_id = alias_ids.get((r["team_away_auto"] or "").strip())
            if home_id:
                sets["team_home_id"] = home_id
            if away_id:
                sets["team_away_id"] = away_id
            league_id = league_ids.get((r["league_auto"] or "").strip())
            if league_id:
                sets["league_id"] = league_id
            if sets:
                conn.execute("UPDATE events SET " +
                             ", ".join(f"{k}=?" for k in sets) +
                             " WHERE id=?", (*sets.values(), r["id"]))
                stamped += 1
        # подтянутое время — обратно в базу по id игры
        for game, ref, _ in aligned["sure"]:
            conn.execute("UPDATE events SET start_kyiv=?, "
                         "flags = COALESCE(flags, ?) WHERE id=?",
                         (game["start_kyiv"],
                          f"fs:{ref['fs_id']}" if ref.get("fs_id") else None,
                          game["id"]))
        conn.commit()

        # Метка fs: всем событиям, которые эталон узнал, — и дедуп: два
        # события с одной меткой suть один матч. Кейс #672/#677 (03.09):
        # tring писал «Porto - Man.City», склейка не дотянулась до
        # «FC PORTO - MANCHESTER CITY», и матч жил дублем — каналы дубля
        # переезжают в основное событие, дубль убирается.
        rows = conn.execute(
            "SELECT id, sport, league_auto, team_home_auto, team_away_auto, "
            "start_kyiv FROM events WHERE flags IS NULL").fetchall()
        всё = [{"id": r["id"], "sport": r["sport"] or "",
                "home": r["team_home_auto"] or "",
                "away": r["team_away_auto"] or "",
                "league": r["league_auto"] or "",
                "start_kyiv": r["start_kyiv"], "entries": []} for r in rows]
        for game, ref, _ in canon.align(
                всё, reference, dictionary.league_overrides(conn))["sure"]:
            if ref.get("fs_id"):
                conn.execute("UPDATE events SET flags=? WHERE id=? "
                             "AND flags IS NULL",
                             (f"fs:{ref['fs_id']}", game["id"]))
        groups: dict[str, list] = {}
        for r in conn.execute("SELECT id, team_home_id, team_away_id, flags "
                              "FROM events WHERE flags LIKE 'fs:%'"):
            groups.setdefault(r["flags"], []).append(r)
        doubles = 0
        for rows in groups.values():
            if len(rows) < 2:
                continue
            # главным остаётся событие с каноном, при равенстве — раннее
            rows.sort(key=lambda r: (-(int(bool(r["team_home_id"]))
                                       + int(bool(r["team_away_id"]))), r["id"]))
            main = rows[0]
            for dup in rows[1:]:
                # отметка есть у обоих — главному достаётся ЛУЧШИЙ (меньший)
                # счётчик погашения: дубль как раз и рождался из свежей
                # строки сайта, и его подтверждение (miss 0) раньше
                # выбрасывалось вместе с дублем — SPORT TV + у Шеффилд -
                # Вулвз оставался спрятанным (владелец 12.09)
                conn.execute(
                    "UPDATE event_channels SET miss_count = ("
                    " SELECT MIN(d.miss_count, event_channels.miss_count)"
                    " FROM event_channels d WHERE d.event_id = ?"
                    "  AND d.channel_id = event_channels.channel_id"
                    "  AND d.source_id = event_channels.source_id) "
                    "WHERE event_id = ? AND EXISTS ("
                    " SELECT 1 FROM event_channels d WHERE d.event_id = ?"
                    "  AND d.channel_id = event_channels.channel_id"
                    "  AND d.source_id = event_channels.source_id)",
                    (dup["id"], main["id"], dup["id"]))
                conn.execute("UPDATE OR IGNORE event_channels SET event_id=? "
                             "WHERE event_id=?", (main["id"], dup["id"]))
                conn.execute("DELETE FROM event_channels WHERE event_id=?",
                             (dup["id"],))
                conn.execute("DELETE FROM events WHERE id=?", (dup["id"],))
                doubles += 1
        conn.commit()
        # лига из эталона — событию с fs-меткой, но без лиги: sport5 лиг
        # не пишет вовсе, и связанный мостом матч висел с пустой колонкой
        # (кейс #1025 «ISRAEL: League Cup», 04.09)
        league_by_flag = {}
        for e in reference:
            if e.get("fs_id") and e.get("league"):
                league_by_flag.setdefault(f"fs:{e['fs_id']}", e["league"])
        leagued = 0
        for r in conn.execute("SELECT id, flags FROM events "
                              "WHERE flags LIKE 'fs:%' "
                              "AND league_id IS NULL").fetchall():
            canon_league = league_by_flag.get(r["flags"])
            row = canon_league and conn.execute(
                "SELECT id FROM leagues WHERE canonical_name = ?",
                (canon_league,)).fetchone()
            if row:
                conn.execute("UPDATE events SET league_id=? WHERE id=?",
                             (row["id"], r["id"]))
                leagued += 1
        # время из эталона — всем событиям с fs-меткой: заливка перетирает
        # его временем сеток, а правило владельца — «время по flashscore»
        # (кейсы #88, #629, #106; закреплено в CLAUDE.md)
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _Z
        times_by_flag: dict[str, list] = {}
        for e in reference:
            try:
                t = _dt.fromisoformat(e.get("start_kyiv") or "")
            except ValueError:
                continue
            if e.get("fs_id"):
                times_by_flag.setdefault(f"fs:{e['fs_id']}", []).append(t)
        fs_retimed = 0
        for r in conn.execute("SELECT id, flags, start_kyiv FROM events "
                              "WHERE flags LIKE 'fs:%'").fetchall():
            cands = times_by_flag.get(r["flags"])
            if not cands:
                continue
            try:
                ours = _dt.fromisoformat((r["start_kyiv"] or "")
                                         .replace(" ", "T"))
            except ValueError:
                continue
            best = min(cands, key=lambda t: abs((t - ours).total_seconds()))
            diff = abs((best - ours).total_seconds())
            if 0 < diff <= 6 * 3600:
                conn.execute(
                    "UPDATE events SET start_kyiv=?, start_utc=? WHERE id=?",
                    (best.strftime("%Y-%m-%d %H:%M"),
                     # киевское → UTC по календарю, а не жёсткие −3 ч:
                     # зимой смещение +2 (C1 аудита, как в canon.retime)
                     best.replace(tzinfo=_Z("Europe/Kyiv"))
                         .astimezone(_Z("UTC")).strftime("%Y-%m-%d %H:%M"),
                     r["id"]))
                fs_retimed += 1
        # Двойня по полу (14.09): разбор научился видеть пол в лиге sport5
        # («ליגה צרפתית בכדורגל הנשים»), и старая строка «מונפלייה — מארסיי»
        # живёт рядом с новой «מונפלייה W — מארסיי W». Один канал того же
        # сайта в одно время двух матчей не показывает: если ВСЕ отметки
        # строки без W есть и у женской — строка лишняя (лишний W лучше
        # потерянного), её убираем
        gender_twins = 0
        for w in conn.execute(
                "SELECT id, sport, team_home_auto, team_away_auto, start_kyiv "
                "FROM events WHERE team_home_auto LIKE '% W' "
                "AND team_away_auto LIKE '% W'").fetchall():
            try:
                w_start = _dt.fromisoformat(w["start_kyiv"].replace(" ", "T"))
            except ValueError:
                continue
            for m in conn.execute(
                    "SELECT id, start_kyiv FROM events WHERE id <> ? "
                    "AND sport = ? AND flags IS NULL AND team_home_auto = ? "
                    "AND team_away_auto = ?",
                    (w["id"], w["sport"], w["team_home_auto"][:-2].strip(),
                     w["team_away_auto"][:-2].strip())).fetchall():
                try:
                    m_start = _dt.fromisoformat(
                        m["start_kyiv"].replace(" ", "T"))
                except ValueError:
                    continue
                if abs((m_start - w_start).total_seconds()) > 30 * 60:
                    continue
                marks = conn.execute(
                    "SELECT channel_id, source_id FROM event_channels "
                    "WHERE event_id = ?", (m["id"],)).fetchall()
                if not marks or not all(conn.execute(
                        "SELECT 1 FROM event_channels WHERE event_id = ? "
                        "AND channel_id = ? AND source_id IS ?",
                        (w["id"], x["channel_id"], x["source_id"])).fetchone()
                        for x in marks):
                    continue
                gender_twins += 1
                print(f"  двойня по полу: #{m['id']} убрана в пользу #{w['id']} "
                      f"{w['team_home_auto']} — {w['team_away_auto']}")
                conn.execute("DELETE FROM event_channels WHERE event_id = ?",
                             (m["id"],))
                conn.execute("DELETE FROM events WHERE id = ?", (m["id"],))
        if gender_twins:
            conn.commit()

        # эхо-повторы дальних дней (владелец 05.09: «10-е собрано плохо»):
        # сетки повторов ставят прошедшие матчи на будущие даты. Событие
        # без fs-метки, чья пара по эталону играла ТОЛЬКО РАНЬШЕ дня
        # события (день события эталоном покрыт, а пары на него нет), с
        # отметками максимум двух источников — снимается как запись
        pair_days: dict[tuple, set] = {}
        all_days: set = set()
        for e in reference:
            day = (e.get("start_kyiv") or "")[:10]
            h = (e.get("home") or "").strip().lower()
            a = (e.get("away") or "").strip().lower()
            if day:
                all_days.add(day)
            if h and a and day:
                pair_days.setdefault((h, a), set()).add(day)
        last_ref_day = max(all_days) if all_days else ""
        echoes = 0
        for r in conn.execute(
                "SELECT e.id, e.start_kyiv, th.canonical_name h, "
                "ta.canonical_name a FROM events e "
                "JOIN teams th ON th.id=e.team_home_id "
                "JOIN teams ta ON ta.id=e.team_away_id "
                "WHERE e.flags IS NULL").fetchall():
            day = (r["start_kyiv"] or "")[:10]
            days = pair_days.get(((r["h"] or "").strip().lower(),
                                  (r["a"] or "").strip().lower()))
            if not days or not day or day > last_ref_day or day in days:
                continue
            if any(d >= day for d in days):     # будущий матч есть — не эхо
                continue
            srcs = [row["d"] for row in conn.execute(
                "SELECT DISTINCT s.domain d FROM event_channels ec "
                "JOIN sources s ON s.id = ec.source_id "
                "WHERE ec.event_id=?", (r["id"],))]
            # порог «больше двух сайтов — верим» не работает, когда ВСЕ
            # сайты — угадывающие (эфира не помечают): три телегида хором
            # ставили повтор Valencia - Barcelona на 11.09 при матче 06.09
            # (#1405, номер владельца 06.09)
            guessed_all = bool(srcs) and all(
                d in REPEAT_GUESS_DOMAINS for d in srcs)
            # кубок — не повтор: «הסופר קאפ החברתי: מכבי ת"א - הפועל ת"א»
            # 17.09 — те же клубы через три дня после дерби лиги, но другой
            # турнир; с верными именами правило снимало живую игру (#2460)
            import re as _re
            titles = " ".join(row["t"] or "" for row in conn.execute(
                "SELECT raw_title t FROM event_channels WHERE event_id=?",
                (r["id"],)))
            if _re.search(r"קאפ|גביע|cup\b|kup|copa|coppa|coupe|pokal|puchar"
                          r"|ta[cç]a|кубок|купа", titles, _re.I):
                continue
            if len(srcs) <= 2 or guessed_all:
                conn.execute("DELETE FROM event_channels WHERE event_id=?",
                             (r["id"],))
                conn.execute("DELETE FROM events WHERE id=?", (r["id"],))
                echoes += 1
        conn.commit()
        print(f"имён закреплено {fixed}, в очередь {queued}, "
              f"время подтянуто {retimed}, событий обновлено {stamped}, "
              f"канон напрямую {direct}, "
              f"дублей схлопнуто {doubles}, лиг из эталона {leagued}, "
              f"время по эталону {fs_retimed}, эхо-повторов снято {echoes}")
        left = conn.execute(
            "SELECT COUNT(*) FROM events WHERE team_home_id IS NULL "
            "OR team_away_id IS NULL").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        print(f"без канона осталось {left} из {total} "
              f"({100 * left / max(total, 1):.0f}%)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

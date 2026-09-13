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
        alias_ids = {r["alias"]: r["team_id"] for r in conn.execute(
            "SELECT alias, team_id FROM team_aliases")}
        league_ids = {r["alias"]: r["league_id"] for r in conn.execute(
            "SELECT alias, league_id FROM league_aliases")}
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

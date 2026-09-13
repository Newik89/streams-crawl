# -*- coding: utf-8 -*-
r"""Наполнить очередь названий тем, что обход не смог опознать.

Читает отчёт обхода (`results/matches.md`), берёт из него имена команд и
каналов и кладёт в очередь те, которых ещё нет в словарях. К сайтам не
обращается.

Что считается «не опознано»:
  - команда, для которой нет подтверждённого имени в `team_aliases` и которая
    ни с кем не склеилась — то есть осталась в ленте одна. У склеившихся имя
    уже понятно из пары, они не срочные;
  - канал, у которого нет записи в `channel_aliases` для этого сайта.

Предложение системы (`suggestion`) — то, что дала транслитерация со словарём
слов. Владельцу останется подтвердить или поправить.

Запуск:
    venv\Scripts\python.exe scripts/fill_moderation.py
    venv\Scripts\python.exe scripts/fill_moderation.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app import db, dictionary, merge, names          # noqa: E402
from merge_report import read_entries                 # noqa: E402

DEFAULT_MD = ROOT / "results" / "matches.md"


def suggest(raw: str) -> str:
    """Заготовка канонического имени — не истина, владелец правит одним полем."""
    return names.suggest_canonical(raw)


def accept_all(conn) -> int:
    """Закрепить всё открытое по предложению системы.

    Пока словарь наполняет ассистент (решение владельца 31.08), разбирать
    сотню имён по одной кнопке незачем. Предложения перед этим просматривают
    глазами: `--dry-run` показывает их списком.

    Страна канала берётся у сайта: чешский телегид почти всегда показывает
    чешские каналы. Иностранный канал владелец потом поправит в админке —
    имя без страны склеилось бы с чужим (`Nova Sport 1` бывает и греческий).
    """
    done = 0
    for item in dictionary.open_items(conn, limit=10_000):
        proposal = (names.suggest_canonical(item["raw_value"])
                    if item["kind"] != "channel" else item["raw_value"])
        if not proposal:
            continue
        try:
            dictionary.resolve(conn, item["id"], proposal,
                               item["source_country"] or "")
            done += 1
        except (ValueError, LookupError) as e:
            print(f"  не закрепил «{item['raw_value']}»: {e}")
    return done


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default=str(DEFAULT_MD))
    ap.add_argument("--dry-run", action="store_true",
                    help="только показать, в базу не писать")
    ap.add_argument("--accept", action="store_true",
                    help="закрепить всё открытое по предложению системы")
    args = ap.parse_args()

    if args.accept:
        conn = db.connect()
        try:
            done = accept_all(conn)
            print(f"закреплено: {done}")
            print(f"осталось открытых: {dictionary.counts(conn) or 'ничего'}")
        finally:
            conn.close()
        return 0

    path = Path(args.md)
    if not path.exists():
        print(f"нет файла {path} — сначала обход")
        return 1

    conn = db.connect()
    try:
        names.set_overrides(dictionary.team_overrides(conn))
        known_channels = dictionary.channel_overrides(conn)
        domains = {r["domain"]: r["id"] for r in
                   conn.execute("SELECT id, domain FROM sources")}

        entries = read_entries(path)
        games = merge.merge(entries)

        # Команды из игр, которые нашлись лишь на одном сайте: имя больше
        # сверить не с чем, и как раз тут словарь нужнее всего.
        lonely: dict[str, str] = {}
        for game in games:
            if len(game.sources) > 1:
                continue
            for entry in game.entries:
                for team in (entry.home, entry.away):
                    lonely.setdefault(team.strip(), entry.source)

        confirmed = dictionary.team_overrides(conn)
        added_teams = 0
        for team, domain in sorted(lonely.items()):
            if team in confirmed:
                continue
            proposal = suggest(team)
            if args.dry_run:
                print(f"  команда: {team:34} ({domain}) → {proposal}")
                added_teams += 1
            elif dictionary.enqueue(conn, "team", team, proposal,
                                    domains.get(domain)):
                added_teams += 1

        added_channels = 0
        seen_channels: set[tuple[str, int | None]] = set()
        for entry in entries:
            source_id = domains.get(entry.source)
            key = (entry.channel, source_id)
            if key in known_channels or key in seen_channels:
                continue
            seen_channels.add(key)
            if args.dry_run:
                print(f"  канал:   {entry.channel:34} ({entry.source})")
                added_channels += 1
            elif dictionary.enqueue(conn, "channel", entry.channel,
                                    entry.channel, source_id):
                added_channels += 1

        # Лига у каждого сайта своя: `Liga angielska`, `Висша лига`,
        # `EFL CHAMPIONSHIP`. Канон (`ENGLAND: Premier League`) знает только
        # владелец — предложить своё системе тут нечего, поле оставляем пустым.
        known_leagues = dictionary.league_overrides(conn)
        added_leagues = 0
        seen_leagues: set[str] = set()
        for entry in entries:
            league = (entry.league or "").strip()
            if not league or league in known_leagues or league in seen_leagues:
                continue
            seen_leagues.add(league)
            if args.dry_run:
                print(f"  лига:    {league:34} ({entry.source})")
                added_leagues += 1
            elif dictionary.enqueue(conn, "league", league, "",
                                    domains.get(entry.source)):
                added_leagues += 1

        left = dictionary.counts(conn)
        print(f"\nв очередь добавлено: команд {added_teams}, "
              f"каналов {added_channels}, лиг {added_leagues}"
              f"{'  (это пробный прогон, база не тронута)' if args.dry_run else ''}")
        if not args.dry_run:
            print(f"открыто в очереди: {left}")
            print("разбирать — в админке, вкладка «Названия»")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

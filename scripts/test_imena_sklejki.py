# -*- coding: utf-8 -*-
r"""Имена склейки — по большинству строк, а не по длине (книга 094, вопрос
владельца 02.11.2026: «#8758 — игра снята со всех каналов, почему все
перечёркнуты?»). Дневной сбор #390 склеил Bodo/Glimt — Lille из 8 строк, и
имя игры взяли две грязные: студия programme-tv «Villarreal - Paris-SG et FK
Bodø/Glimt - Lille» (две игры в одной передаче) и ipko «Liga e Kampioneve
Bodo Glimt - Lille» (лига приклеена к имени). Программа выучила «… et FK
Bodø/Glimt» = Villarreal и «Liga e Kampioneve Bodo Glimt» = PSG, заливка
положила 8 каналов в Villarreal — PSG (#8636), а #8758 погасла «сиротой».

Правило — проверка:

  И1. `names.looks_like_pair`: разделитель пары внутри имени — не имя
      команды; дефис без пробелов («Saint-Étienne», «Bodø/Glimt») — имя.
  И2. `live.several_matches` / `split_teams` / `split_candidates`: союз в
      СРЕДНЕМ куске между разделителями — две пары в одной подписи: ни
      пары, ни догадок. «Virtus - Bologna - Baskonia» (без союза) — по-
      прежнему догадки на каждом разрезе; союз в крайнем куске — часть имени.
  И3. `merge.Game.home/away`: алфавит первым (латиница, кириллица, прочее —
      как раньше), внутри алфавита — написание, с которым согласно больше
      строк (сумма сходства), при равном согласии — меньше лишних слов
      (от трёх написаний), потом длиннее; написание с парой внутри —
      последним. Иврит и кириллица латиницу не побеждают.
  И4. `merge.merge`: восемь живых строк #8758 → одна игра «Bodo/Glimt —
      Lille» (любое латинское написание Bodo, «Lille»), все 8 каналов.
  И5. `canon._learnable`: алиас с парой внутри не учится («… et FK
      Bodø/Glimt» → Villarreal); «Bodo Glimt» → «Bodo/Glimt» — учится.
  И6. ipko.tv `_pair`: «Liga e …», «Kupa e …», «Superliga …» перед парой
      отрезаются; турецкое «… Karşılaşması» — как раньше; `parse` целиком.
  И7. `proverka.twin`: игра с новым именем и большинством прежних каналов
      (≥2 и ≥половины) — переименование, не пропажа; один общий канал из
      восьми — пропажа, как раньше.
  И8. `store._pick_by_marks`: заливка узнаёт игру базы по отметкам (сайт,
      канал), когда имя сменилось — не двойня: большинство (≥2 и
      ≥половины) или все отметки старой игры среди новых (одна отметка —
      #9196); одна общая из шести у игры с шестью — не узнаёт; кандидат —
      рядом по времени (±30 мин) или с одной сошедшейся командой в окне
      склейки (#9459 студия TNT в 21:00 против #8782 в 22:00).

В сеть не ходит, база не нужна:

    venv/bin/python scripts/test_imena_sklejki.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("STREAMS_DB", str(Path(tempfile.gettempdir()) / "imena-sklejki-none.db"))

from app import canon, live, merge, names  # noqa: E402
from app.merge import Entry  # noqa: E402
from app.parsers import ipko_tv  # noqa: E402

total = green = 0


def check(name: str, ok: bool, extra="") -> None:
    global total, green
    total += 1
    green += bool(ok)
    print(f"  {'✔' if ok else '✗'} {name}" + ("" if ok else f"  → {extra!r}"))


STUDIO = "Villarreal - Paris-SG et FK Bodø/Glimt - Lille"

print("И1. имя с парой внутри")
check("«Villarreal - Paris-SG et FK Bodø/Glimt» — пара", names.looks_like_pair("Villarreal - Paris-SG et FK Bodø/Glimt"))
check("«Real Madrid vs Barcelona» — пара", names.looks_like_pair("Real Madrid vs Barcelona"))
check("«Saint-Étienne», «Bodø/Glimt», «Paris-SG» — имена",
      not any(names.looks_like_pair(n) for n in ("Saint-Étienne", "Bodø/Glimt", "Paris-SG", "Lille")))

print("И2. две пары в одной подписи")
check("студия: split_teams → None", live.split_teams(STUDIO) is None, live.split_teams(STUDIO))
check("студия: догадок для эталона нет", live.split_candidates(STUDIO) == [], live.split_candidates(STUDIO))
check("«Virtus - Bologna - Baskonia» — догадки на каждом разрезе остались",
      live.split_candidates("Virtus - Bologna - Baskonia")
      == [("Virtus", "Bologna - Baskonia"), ("Virtus - Bologna", "Baskonia")],
      live.split_candidates("Virtus - Bologna - Baskonia"))
check("союз в крайнем куске — часть имени: «Bologna e Roma - Baskonia» — пара",
      live.split_teams("Bologna e Roma - Baskonia") == ("Bologna e Roma", "Baskonia"),
      live.split_teams("Bologna e Roma - Baskonia"))
check("«Arsenal and Chelsea - Lille - Monaco» (and в среднем куске) — не пара",
      live.split_candidates("Arsenal - Chelsea and Lille - Monaco") == []
      and live.split_teams("Arsenal - Chelsea and Lille - Monaco") is None)
check("обычная пара «Rennes - Lille» — как раньше",
      live.split_teams("Rennes - Lille") == ("Rennes", "Lille"))

print("И3. имя игры — по большинству строк")
when = datetime(2026, 11, 3, 22, 0)


def игра(*pairs, start=when):
    return merge.Game(entries=[Entry(source=f"s{i}", channel=f"c{i}", home=h, away=a,
                                     start=start, sport="F") for i, (h, a) in enumerate(pairs)])


g = игра(("Villarreal - Paris-SG et FK Bodø/Glimt", "Lille"), ("Bodo/Glimt", "Lille"), ("Bodo Glimt", "Lille"))
check("две строки Bodo против одной студии — «Bodo…», не студия",
      g.home.lower().startswith("bodo") and g.away == "Lille", (g.home, g.away))
g = игра(("Villarreal - Paris-SG et FK Bodø/Glimt", "Lille"), ("Bodo/Glimt", "Lille"))
check("одна против одной: написание с парой внутри — всё равно последним",
      g.home == "Bodo/Glimt", g.home)
g = игра(("Los Angeles Lakers", "Toronto Raptors"), ("LA Lakers", "Toronto"))
check("спор двух написаний — длина, как раньше (доводка 02.11)",
      g.home == "Los Angeles Lakers" and g.away == "Toronto Raptors", (g.home, g.away))
g = игра(("Lyon", "Marseille"), ("Olympique Lyonnais", "Olympique Marseille"))
check("равная поддержка без грязи — прежний порядок (длиннее латиница)",
      g.home == "Olympique Lyonnais", g.home)
g = игра(("Аталанта", "Интер"), ("Atalanta", "Inter"), ("אטאלנטה", "אינטר"))
check("алфавиты: латиница главнее кириллицы и иврита (как раньше)", g.home == "Atalanta", g.home)
g = игра(("Newcastle United FC", "Everton FC"), ("Newcastle", "Everton"), ("ניוקאסל", "אברטון"))
check("иврит не побеждает латиницу, даже если «согласен» с обеими (проба 02.11)",
      g.home.startswith("Newcastle") and g.away.startswith("Everton"), (g.home, g.away))
g = игра(("Пахтакор", "Al-Nassr"), ("Pakhtakor", "Al-Nassr"), ("פחתקור", "אל-נאסר"))
check("кириллица не побеждает латиницу (проба 02.11)", g.home == "Pakhtakor", g.home)
g = игра(("Liga e Kampioneve Bodo Glimt", "Lille"), ("Bodo/Glimt", "Lille"), ("Bodo Glimt", "Lille"))
check("длинное имя с приставкой лиги проигрывает тому, с чем согласны остальные",
      g.home in ("Bodo/Glimt", "Bodo Glimt"), g.home)

print("И4. восемь живых строк #8758 → одна игра с чистым именем")
rows = [
    ("programme-tv.net", "L'Equipe", "Villarreal - Paris-SG et FK Bodø/Glimt", "Lille", datetime(2026, 11, 3, 21, 58)),
    ("cosmotetv.gr", "Magenta Sport 8", "Μπόντο Γκλιμτ", "Λιλ", when),
    ("livesoccertv.com", "ART Sport 6", "Bodø / Glimt", "Lille", when),
    ("primaplay.ro", "PPV1", "Bodo/Glimt", "Lille", when),
    ("tvarenasport.ba", "Arena Premium 5", "Bodo Glimt", "Lille", when),
    ("tvarenasport.com", "Arena Sport 1", "Bodo/Glimt", "Lille", when),
    ("tvarenasport.hr", "Arena Sport 8", "BODO GLIMT", "LILLE", when),
    ("ipko.tv", "Sport 6", "Liga e Kampioneve Bodo Glimt", "Lille", when),
]
games = merge.merge([Entry(source=s, channel=c, home=h, away=a, start=st, sport="F")
                     for s, c, h, a, st in rows])
check("одна игра на 8 строк", len(games) == 1 and len(games[0].entries) == 8,
      [len(g.entries) for g in games])
check("имя игры — Bodo…/Lille, не студия и не «Liga e…»",
      games[0].home.lower().replace("ø", "o").startswith("bodo") and games[0].away == "Lille",
      (games[0].home, games[0].away))
check("ни одна строка не перевёрнута (хозяева — Bodo у всех латинских)",
      all(e.home.lower().replace("ø", "o").find("bodo") >= 0 or e.home == "Μπόντο Γκλιμτ"
          for e in games[0].entries), [(e.home, e.away) for e in games[0].entries])

print("И5. словарь не учит имя с парой внутри")
check("«… et FK Bodø/Glimt» → Villarreal — нельзя",
      canon._learnable("Villarreal - Paris-SG et FK Bodø/Glimt", "Villarreal") is False)
check("«Bodo Glimt» → «Bodo/Glimt» — можно", canon._learnable("Bodo Glimt", "Bodo/Glimt") is True)
check("«EVERTON X WOLVERHAMPTON» → Everton — по-прежнему нельзя",
      canon._learnable("EVERTON X WOLVERHAMPTON", "Everton") is False)

print("И6. ipko.tv: лига перед парой без двоеточия")
for raw, want in (
    ("Futboll: Liga e Kampioneve Bodo Glimt - Lille", "Bodo Glimt - Lille"),
    ("Futboll: Liga e Kampionevee Barcelona - Aston Villa", "Barcelona - Aston Villa"),
    ("Superliga e Kosovës Prishtina - Drita", "Prishtina - Drita"),
    ("Futboll: Kupa e Kosovës Llapi - Ballkani", "Llapi - Ballkani"),
    ("Futboll: Liga e Evropës Roma - Viktoria Plzen", "Roma - Viktoria Plzen"),
    ("UEFA Kadınlar Şampiyonlar Ligi Futbol Karşılaşması Barcelona - Paris FC", "Barcelona - Paris FC"),
    ("Futboll: Prishtina - Drita", "Prishtina - Drita"),
):
    check(f"{raw!r} → {want!r}", ipko_tv._pair(raw) == want, ipko_tv._pair(raw))
sample = json.dumps({"shows": [{"title": "Futboll: Liga e Kampioneve Bodo Glimt - Lille",
                                "show_start": 1793736000, "show_end": 1793743200,
                                "genres": ["futboll"], "categories": "Sport", "summary": ""}]})
got = ipko_tv.parse(sample, url="https://stargate.ipko.tv/api/titan.tv.WebEpg/GetWebEpgData?channel_id=sport-6")
check("parse: пара без приставки лиги, канал Sport 6",
      len(got) == 1 and got[0].match_raw == "Bodo Glimt - Lille" and got[0].channel_raw == "Sport 6",
      [(p.channel_raw, p.match_raw) for p in got])

print("И7. сравнение сборов: переименование по большинству каналов")
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("proverka", ROOT / "scripts" / "proverka.py")
proverka = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proverka)


def game(home, away, start, chans):
    return {"home": home, "away": away, "start_kyiv": start,
            "entries": [{"channel": c, "source": s} for c, s in chans]}


CH = [("L'Equipe", "programme-tv.net"), ("Magenta Sport 8", "cosmotetv.gr"), ("ART Sport 6", "livesoccertv.com"),
      ("PPV1", "primaplay.ro"), ("Arena Premium 5", "tvarenasport.ba"), ("Arena Sport 1", "tvarenasport.com"),
      ("Arena Sport 8", "tvarenasport.hr"), ("Sport 6", "ipko.tv")]
old = game("Villarreal - Paris-SG et FK Bodø/Glimt", "Liga e Kampioneve Bodo Glimt", "2026-11-03T21:58", CH)
new = game("Bodø / Glimt", "Lille", "2026-11-03T22:00", CH[1:])
found, how = proverka.twin(old, [new], [])
check("7 из 8 каналов при новом имени → «имя», не пропажа", found is new and how == "имя", (found, how))
one = game("Bodø / Glimt", "Lille", "2026-11-03T22:00", CH[:1])
found, how = proverka.twin(old, [one], [])
check("один общий канал из восьми — пропажа, как раньше", found is None, (found, how))
check("_most_channels: 2 из 4 — да, 2 из 5 — нет, 1 из 2 — нет",
      proverka._most_channels({1, 2, 3, 4}, {1, 2}) and not proverka._most_channels({1, 2, 3, 4, 5}, {1, 2})
      and not proverka._most_channels({1, 2}, {1}))

print("И8. заливка: игра базы по большинству отметок каналов")
from app import store  # noqa: E402
rows = [(8636, 1, 10), (8636, 2, 20), (8758, 3, 30), (8758, 4, 40), (8758, 5, 50), (8758, 6, 60)]
check("4 из 6 отметок у #8758 → она", store._pick_by_marks({(3, 30), (4, 40), (5, 50), (6, 60), (7, 70), (8, 80)}, rows) == 8758)
check("2 из 6 (меньше половины) → не узнаёт", store._pick_by_marks({(3, 30), (4, 40), (1, 1), (2, 2), (9, 9), (8, 8)}, rows) is None)
check("одна общая из шести у игры с четырьмя отметками → не узнаёт",
      store._pick_by_marks({(3, 30), (1, 1), (2, 2), (9, 9), (8, 8), (7, 7)}, rows) is None)
check("две общие из двух → узнаёт", store._pick_by_marks({(1, 10), (2, 20)}, rows) == 8636)
one = [(9196, 7, 70)]
check("#9196: единственная отметка старой игры среди трёх новых → она",
      store._pick_by_marks({(7, 70), (8, 80), (9, 90)}, one) == 9196)
check("отметка старой игры не среди новых → не узнаёт",
      store._pick_by_marks({(8, 80), (9, 90)}, one) is None)
check("из двух кандидатов — с бо́льшим совпадением",
      store._pick_by_marks({(7, 70), (8, 80), (9, 90)}, one + [(9300, 8, 80), (9300, 9, 90)]) == 9300)
check("окно по каналам уже окна склейки", store.CHANNELS_WINDOW_MINUTES < store.merge.WINDOW_MINUTES)
far = [(8782, i, i * 10) for i in range(1, 23)]                      # 22 отметки настоящей игры
incoming = {(i, i * 10) for i in range(1, 21)}                        # 20 из них у двойника
check("#8782 в часе от игры файла, одна команда сошлась → она",
      store._pick_by_marks(incoming, far, near=set(), side={8782}) == 8782)
check("та же игра час спустя без сошедшихся команд → не она (соседний матч на тех же каналах)",
      store._pick_by_marks(incoming, far, near=set(), side=set()) is None)
check("рядом по времени — и без имён", store._pick_by_marks(incoming, far, near={8782}, side=set()) == 8782)

print(f"\nпроверок: {total}, зелёных: {green}, красных: {total - green}")
raise SystemExit(0 if green == total else 1)

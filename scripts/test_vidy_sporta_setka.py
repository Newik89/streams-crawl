# -*- coding: utf-8 -*-
r"""Сетка «чужой вид спорта × язык сайта» (книга 107, аудит 13.11.2026).

Повод: 66 открытых вопросов «Вид спорта» владельцу, из них 27 — потому что
слова чужого вида не было на языке сайта или в падеже: латышское «Regbijs»,
чешские «v ledním hokeji» и «v baseballu», греческие «Αλπικό Σκι» и «Σλάλομ»,
сокращения ASOBAL, WSE, ULLH. На витрине футболом стояли футбол ампутантов
(«Amp futbol», teleman.pl) и канадский футбол («Football universitaire»,
tvpassport.com). Слово владельца 12.11: проверять весь класс, а не слова из
жалобы.

Что сторожится:

1. ПОЛНОТА: у каждого языка каждого сайта плана (`site_lang.SITE_LANGS`) и у
   английского есть слово каждого вида сетки (`data/sport_grid.json`). Новый
   язык сайта без слов — красный;
2. каждое слово сетки программа читает чужим видом спорта, и вид — тот, под
   которым слово записано (вкладка «Other Sport»);
3. строки из очереди владельца 13.11 — чужой вид спорта;
4. «Amp futbol» и «Football universitaire» — не футбол;
5. наш вид спорта не пострадал: «Fotbal», «Fodbold», «Basketball», «Tenis» с
   теми же сайтами читаются как раньше.

В сеть не ходит, базу не трогает:

    python scripts/test_vidy_sporta_setka.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import site_lang, sport                     # noqa: E402
from app.live import greek_plain                     # noqa: E402

passed, failed = 0, []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print("  ✔", name)
    else:
        failed.append(name)
        print("  ✖", name, extra)


SPORTS = sport.load()
СЕТКА = json.loads(sport.GRID_FILE.read_text(encoding="utf-8"))["виды"]


def чужой(text: str, pair=None):
    """(чужой ли вид, группа) — решение программы по тексту строки."""
    v = SPORTS.decide(text, text, pair)
    return v.letter == "-", v.group


# ── 1. полнота сетки ─────────────────────────────────────────────────────────
print("1. У каждого языка сайтов плана есть слово каждого вида")
языки_сайтов = {l for langs in site_lang.SITE_LANGS.values() for l in langs}
языки_сайтов.add("en")
#: язык сайта → ключ сетки: хорватский и боснийский пишут латиницей («sh»),
#: сербский — и латиницей («sh»), и кириллицей («sr»)
КЛЮЧИ = {"hr": ("sh",), "bs": ("sh",), "sr": ("sh", "sr")}
for вид, по_языкам in СЕТКА.items():
    пусто = [f"{язык}→{ключ}" for язык in sorted(языки_сайтов)
             for ключ in КЛЮЧИ.get(язык, (язык,))
             if not по_языкам.get(ключ)]
    check(f"«{вид}»: слова есть на всех {len(языки_сайтов)} языках сайтов",
          not пусто, f"нет слов: {пусто}")

# папка data закрыта в .gitignore целиком, наружу едут только названные
# файлы: без строки-исключения сетка не доехала бы до GitHub и сервера
check("файл сетки открыт в .gitignore (едет на GitHub и сервер)",
      "!data/sport_grid.json" in
      (ROOT / ".gitignore").read_text(encoding="utf-8").split())

# ── 2. каждое слово сетки читается чужим видом своей группы ──────────────────
print("2. Каждое слово сетки — чужой вид спорта своей группы")
for вид, по_языкам in СЕТКА.items():
    плохие = []
    всего = 0
    for язык, слова in по_языкам.items():
        for слово in слова:
            всего += 1
            ok, группа = чужой(f"{слово}: Alfa - Beta")
            # слово могло быть записано раньше в другой группе markers.json
            # («ski» — зимние, «box» — единоборства): чужим оно быть обязано,
            # а группа — своя или прежняя
            if not ok:
                плохие.append(f"{язык}:{слово}")
    check(f"«{вид}»: {всего} слов читаются чужим видом", not плохие,
          f"не читаются: {плохие[:12]}")
группы = {}
for вид, по_языкам in СЕТКА.items():
    for слова in по_языкам.values():
        for слово in слова:
            g = SPORTS.group_of(слово)
            if g != вид:
                группы.setdefault(f"{вид}→{g}", []).append(слово)
print("   слова, которые раньше были записаны в другой группе:",
      {k: v[:6] for k, v in группы.items()} or "нет")

# ── 3. строки очереди владельца 13.11 ────────────────────────────────────────
print("3. Строки очереди «Вид спорта» 13.11 — чужой вид")
ОЧЕРЕДЬ = [
    ("Regbijs: Nāciju kauss. Francija - Dienvidāfrika", "регби"),
    ("MS v ledním hokeji žen 2026 Dánsko Kanada W - Česko W", "хоккей"),
    ("MS v baseballu U23 mužů 2026 Nikaragua Kuba U23 - Česko U23",
     "крикет и бейсбол"),
    ("Αλπικό Σκι: Παγκόσμιο Κύπελλο Σλάλομ γυναικών - 1η κούρσα, Λέβι",
     "зимние"),
    ("ASOBAL (T26/27): Barcelona - Triana", "гандбол"),
    ("WSE Continental Cup (T2026): Pons Lleida - Barcelona",
     "флорбол и прочее с клюшкой"),
    ("ULLH: UJEP North Wings Ústí n. L.-BO Ostrava Vítkovice Steel", "хоккей"),
    ("ME XV U18 mužů 2026 Česko U18 - Litva U18", "регби"),
    ("Nations Championship (T2026): Francia - Sudáfrica", "регби"),
    ("Ciclocross:6° Trofeo Città di Firenze - 1a prova master Cross "
     "Internazionale", "велоспорт"),
    ("Премиер падел тур 2026, Дубай - полуфинал", "ракетки"),
    ("FWT Challenger 2026 by Orage - Nendaz Freeride Challenger", "зимние"),
]
for строка, вид in ОЧЕРЕДЬ:
    ok, группа = чужой(строка)
    check(f"«{строка[:50]}» — {вид}", ok and группа == вид, (ok, группа))

# ── 4. чужой футбол — не футбол ──────────────────────────────────────────────
print("4. Футбол ампутантов и канадский футбол — не наш футбол")
for строка, пара, вид in (
        ("Amp futbol: Mistrzostwa świata - Meksyk 2026 Polska - Iran",
         ("Polska", "Iran"), "футзал и пляжный"),
        ("Football universitaire: Coupe Jacques-Dussault: Montréal c. Laval",
         ("Montréal", "Laval"), "американский футбол")):
    ok, группа = чужой(строка, пара)
    check(f"«{строка[:45]}» — {вид}", ok and группа == вид, (ok, группа))

# ── 5. наши виды спорта читаются как раньше ──────────────────────────────────
print("5. Наш вид спорта не пострадал")
for строка, буква in (
        ("Fotbal: Sparta Praha - Slavia Praha", "F"),
        ("Fodbold: Danmark - Norge", "F"),
        ("Football: Arsenal - Chelsea", "F"),
        ("Piłka nożna: Legia - Lech", "F"),
        ("Ποδόσφαιρο | Superbet League 2 | Πανιώνιος – Ολυμπιακός Β’", "F"),
        ("Basketball: Alba Berlin - Bayern", "B"),
        ("Krepšinis - NCAA. Baylor - Texas", "B"),
        ("Košarka: Partizan - Crvena zvezda", "B"),
        ("Tenis: ATP Finals", "T"),
        ("Серия А: Милан - Интер", None)):
    v = SPORTS.decide(greek_plain(строка), строка)
    check(f"«{строка[:45]}» → {буква or 'не чужой'}",
          v.letter == буква if буква else v.letter != "-", (v.letter, v.word))

print(f"\nпроверок: {passed + len(failed)}, зелёных: {passed}, "
      f"красных: {len(failed)}")
sys.exit(1 if failed else 0)

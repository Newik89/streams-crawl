# -*- coding: utf-8 -*-
r"""Книга 184 (28.11.2026): обход одного сайта берёт эталон прошлого полного сбора.

Находка 28.11: обход по списку сайтов (`--only`) страниц эталона не качает,
разбор шёл вслепую. Живой случай — обход sportklub.hr #569 (28.11 06:06):
строка «Košarka - NBA liga: Washington - Orlando» 29.11 00:00 снята «повтором»
(память сборов помнила игру 23.11), хотя в эту ночь команды играют снова.
Правила З1–З6 — в шапке `app/etalon_prev.py`.

Части 1–5 — правила по одному. Часть 6 — сквозной разбор живого среза
`kniga/slices/sbor-569-sportklub-odin` тем же `parse_live`, дважды, с урезанным
эталоном (чтобы шло быстро): проверяется край (З4) на настоящих страницах.
В сеть не ходит. Запуск: python scripts/test_etalon_prev.py
"""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from app import etalon_prev  # noqa: E402
import crawl_fetch  # noqa: E402
import kniga  # noqa: E402
import parse_live  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def запись(home, away, когда, sport="F", **прочее) -> dict:
    return {"sport": sport, "home": home, "away": away, "league": "",
            "fs_id": f"{home}-{away}-{когда}", "start_kyiv": когда, **прочее}


СЕЙЧАС = datetime(2026, 11, 28, 4, 6, tzinfo=timezone.utc)     # обход #569
ЭТАЛОН = [
    запись("Hamburg", "Bayern", "2026-11-28T16:30", names={"de": ["Hamburger SV", "FC Bayern München"]}),
    запись("Washington Wizards", "Orlando Magic", "2026-11-29T00:00", "B"),
    запись("Real Madrid", "Barcelona", "2026-12-03T21:30", "B"),
    запись("Jokic N.", "Sinner J.", "2026-12-03T13:00", "T"),
    запись("Dallas Mavericks", "Orlando Magic", "2026-12-04T03:00", "B"),   # хвост последней страницы
]
ПРОШЛЫЙ = {"собрано": "2026-11-27 19:58", "окно": 6, "эталон": ЭТАЛОН}
ОТЧЁТ = {"режим": "полный обход, окно 6 суток", etalon_prev.ONLY_KEY: ["sportklub.hr"], "строки": []}

print("1. З1: занимаем только у обхода по списку сайтов без своего эталона")
заём = etalon_prev.borrow(ОТЧЁТ, [], ПРОШЛЫЙ, СЕЙЧАС)
проверка("обход по списку сайтов, своего эталона нет — эталон занят", len(заём.records), 5)
пусто = etalon_prev.borrow({"режим": "полный обход", "строки": []}, [], ПРОШЛЫЙ, СЕЙЧАС)
проверка("в отчёте нет раздела «только» (полный сбор, проба адресов, старый срез) — не занимаем, без причины",
         (пусто.records, пусто.edge, пусто.mark, пусто.why), ([], None, {}, ""))
свой = etalon_prev.borrow(ОТЧЁТ, [ЭТАЛОН[0]], ПРОШЛЫЙ, СЕЙЧАС)
проверка("обход по списку сайтов привёз свой эталон — прошлый не берём", (свой.records, свой.why), ([], ""))
проверка("раздел «только» пуст — не занимаем",
         etalon_prev.borrow({etalon_prev.ONLY_KEY: []}, [], ПРОШЛЫЙ, СЕЙЧАС).records, [])
проверка("отчёт — не словарь — не занимаем и не падаем", etalon_prev.borrow(None, [], ПРОШЛЫЙ, СЕЙЧАС).records, [])

print("2. З2: запись «эталон» прошлого полного сбора берётся целиком")
проверка("те же записи, с местными именами", заём.records, ЭТАЛОН)
проверка("мусор в списке эталона (не словари) отбрасывается",
         len(etalon_prev.borrow(ОТЧЁТ, [], {**ПРОШЛЫЙ, "эталон": [ЭТАЛОН[0], "x", None]}, СЕЙЧАС).records), 1)
нет_эталона = etalon_prev.borrow(ОТЧЁТ, [], {"собрано": "2026-11-27 19:58", "эталон": []}, СЕЙЧАС)
проверка("у прошлого сбора эталона нет — не занято, причина названа",
         (нет_эталона.records, "эталона нет" in нет_эталона.why), ([], True))
проверка("файла прошлого сбора нет (пустой словарь) — не занято, причина названа",
         bool(etalon_prev.borrow(ОТЧЁТ, [], {}, СЕЙЧАС).why))

print("3. З3: свежесть прошлого сбора")
проверка("порог — 36 часов", etalon_prev.MAX_AGE, timedelta(hours=36))
ровно = etalon_prev.borrow(ОТЧЁТ, [], ПРОШЛЫЙ, datetime(2026, 11, 29, 7, 58, tzinfo=timezone.utc))
проверка("собран ровно 36 часов назад — берём", len(ровно.records), 5)
старый = etalon_prev.borrow(ОТЧЁТ, [], ПРОШЛЫЙ, datetime(2026, 11, 29, 7, 59, tzinfo=timezone.utc))
проверка("собран 36 часов и минуту назад — не берём, причина названа",
         (старый.records, "старше 36 ч" in старый.why), ([], True))
будущий = etalon_prev.borrow(ОТЧЁТ, [], ПРОШЛЫЙ, datetime(2026, 11, 27, 19, 57, tzinfo=timezone.utc))
проверка("прошлый сбор помечен будущим временем (срез книги со старыми часами) — не берём",
         (будущий.records, "будущим" in будущий.why), ([], True))
проверка("метки «собрано» нет или она битая — не берём, причина названа",
         [bool(etalon_prev.borrow(ОТЧЁТ, [], {"эталон": ЭТАЛОН, "собрано": метка}, СЕЙЧАС).why)
          for метка in (None, "", "вчера")], [True, True, True])

print("4. З4 и З5: край занятого эталона и пометка в итоге")
проверка("край — предпоследний день записей (последний — хвост страницы)", заём.edge, date(2026, 12, 3))
проверка("день записей один — край он сам", etalon_prev.edge([ЭТАЛОН[0]]), date(2026, 11, 28))
проверка("записей нет или дни битые — края нет",
         [etalon_prev.edge([]), etalon_prev.edge([{"start_kyiv": "когда-то"}, {}])], [None, None])
проверка("день позже края — за краем; край и раньше — нет",
         [etalon_prev.beyond(date(2026, 12, 4), заём.edge), etalon_prev.beyond(date(2026, 12, 3), заём.edge),
          etalon_prev.beyond(date(2026, 11, 28), заём.edge)], [True, False, False])
проверка("эталон свой (края нет) — за краем не бывает", etalon_prev.beyond(date(2030, 1, 1), None), False)
проверка("пометка в итоге: когда собран, сколько записей, край",
         заём.mark, {"собрано": "2026-11-27 19:58", "записей": 5, "край": "2026-12-03"})

print("5. З6 и вид записей для сверки эфира")
футбол = etalon_prev.football(ЭТАЛОН + [запись("", "X", "2026-11-28T10:00"), запись("A", "B", "битое")])
проверка("футбольные записи — кортежами (хозяева, гости, начало по Киеву); баскетбол, теннис и битые — мимо",
         [(h, a, t.strftime("%Y-%m-%d %H:%M %z")) for h, a, t in футбол],
         [("Hamburg", "Bayern", "2026-11-28 16:30 +0200")])
с_именами = dict(ЭТАЛОН[0], leagues={"de": "Bundesliga"})
etalon_prev.add_names(с_именами, {"hr": ["Hamburg", "Bayern"]}, {"hr": "Njemačka liga"})
проверка("свежие имена дописаны, прежние языки остались",
         (с_именами["names"], с_именами["leagues"]),
         ({"de": ["Hamburger SV", "FC Bayern München"], "hr": ["Hamburg", "Bayern"]},
          {"de": "Bundesliga", "hr": "Njemačka liga"}))
без_имён = запись("A", "B", "2026-11-28T10:00")
etalon_prev.add_names(без_имён, {"tr": ["A", "B"]}, {})
проверка("у записи без имён — как раньше: имена этого обхода", (без_имён["names"], без_имён["leagues"]),
         ({"tr": ["A", "B"]}, {}))

print("   место правил в коде (детекторы)")
разбор = inspect.getsource(parse_live)
проверка("разбор: заём стоит после своего эталона обхода и до сверки строк с эталоном",
         0 < разбор.index("add_reference(settled, reference, reference_full)")
         < разбор.index("etalon_prev.borrow(report_data, reference_full, прошлый_итог)")
         < разбор.index("etalon_prev.add_names(ref, extra_names,")
         < разбор.index("judge = Reference(reference_full)"))
проверка("разбор: занятые футбольные записи идут и в сверку угаданного эфира",
         "reference += etalon_prev.football(заём.records)" in разбор)
проверка("разбор, З4: за краем молчат все четыре правила «пары нет в эталоне — снять»",
         [разбор.count("or _за_краем(r.start_kyiv.date())             # книга 184, З4"),
          "and not _за_краем(r.start_kyiv.date()):" in разбор,
          "[g for g in games if not _за_краем(g.start.date())], память_сыгранных, judge)" in разбор],
         [2, True, True])
проверка("разбор, З5: пометка едет в итог только когда эталон занят",
         "**({etalon_prev.KEY: заём.mark} if заём.records else {})," in разбор)
проверка("разбор: прошлый сбор читается один раз, путь задаётся `--previous`",
         ["прошлый_итог = previous_payload(прошлый_путь)" in разбор, "previous_payload()" in разбор,
          "previous_counts()" in разбор], [True, False, False])
обход = inspect.getsource(crawl_fetch)
проверка("обход: список сайтов из `--only` едет в отчёт разделом «только»",
         ['только = sorted({d.strip() for d in args.only.split(",") if d.strip()})' in обход,
          "payload[etalon_prev.ONLY_KEY] = только" in обход], [True, True])
проверка("книга случаев: срез со своим прошлым сбором отдаёт его разбору",
         'sys.argv += ["--previous", str(Path(folder) / ПРОШЛЫЙ)]' in inspect.getsource(kniga))

print("   нарезка среза книги (`kniga.cut`) с прошлым сбором и пометкой обхода")
with tempfile.TemporaryDirectory(prefix="etalon-prev-") as tmp:
    tmp = Path(tmp)
    артефакт = tmp / "sbor"
    артефакт.mkdir()
    (артефакт / "a.html").write_text("<html></html>", encoding="utf-8")
    (артефакт / "report.json").write_text(json.dumps(
        {"режим": "полный обход", "строки": [{"domain": "site.test", "файл": "a.html", "day": ""},
                                             {"domain": "www.flashscore.mobi", "файл": "a.html", "day": ""}]},
        ensure_ascii=False), encoding="utf-8")
    (tmp / "prev.json").write_text(json.dumps(
        {**ПРОШЛЫЙ, "games": [{"home": "A"}], "снято": [1], "сыгранные": [ЭТАЛОН[1]]}, ensure_ascii=False),
        encoding="utf-8")
    было = kniga.SLICES
    kniga.SLICES = tmp / "slices"
    try:
        kniga.cut(артефакт, "proba", ["site.test"], [], "2026-11-28 04:06", "тест",
                  previous=tmp / "prev.json", only=["site.test"])
        kniga.cut(артефакт, "bez", ["site.test"], [], "2026-11-28 04:06", "тест")
    finally:
        kniga.SLICES = было
    with zipfile.ZipFile(tmp / "slices" / "proba.zip") as z:
        имена = set(z.namelist())
        прошлый_среза = json.loads(z.read(kniga.ПРОШЛЫЙ).decode("utf-8"))
        отчёт_среза = json.loads(z.read("report.json").decode("utf-8"))
    проверка("в срезе лежит прошлый сбор: эталон, память и метка — есть, игр и журналов — нет",
             (kniga.ПРОШЛЫЙ in имена, sorted(прошлый_среза)), (True, ["окно", "собрано", "сыгранные", "эталон"]))
    проверка("отчёт среза помечен обходом по списку сайтов", отчёт_среза.get(etalon_prev.ONLY_KEY), ["site.test"])
    проверка("срез обхода по списку сайтов страниц эталона не добирает — в нём только названные сайты",
             [r["domain"] for r in отчёт_среза["строки"]], ["site.test"])
    with zipfile.ZipFile(tmp / "slices" / "bez.zip") as z:
        отчёт_без = json.loads(z.read("report.json").decode("utf-8"))
        проверка("срез без этих ключей — как раньше: ни прошлого сбора, ни пометки, эталон добирается сам",
                 (kniga.ПРОШЛЫЙ in z.namelist(), etalon_prev.ONLY_KEY in отчёт_без,
                  [r["domain"] for r in отчёт_без["строки"]]),
                 (False, False, ["site.test", "www.flashscore.mobi"]))

print("6. Сквозной разбор живого среза: край занятого эталона (З4)")
СРЕЗ = "sbor-569-sportklub-odin"
ЧАСЫ = kniga.slice_meta(СРЕЗ)["часы_utc"]


def разбор_среза(tmp: Path, имя: str, по_день: str) -> subprocess.Popen:
    """Срез → папка; эталон прошлого сбора урезан: только баскетбол, дни по
    `по_день`, БЕЗ ночного матча Washington — Orlando 29.11. Запускает разбор
    тем же ходом, что книга случаев (`kniga.py --_parse`)."""
    pages, out = tmp / имя / "pages", tmp / имя / "out"
    pages.mkdir(parents=True)
    out.mkdir(parents=True)
    with zipfile.ZipFile(kniga.SLICES / f"{СРЕЗ}.zip") as z:
        z.extractall(pages)
    прошлый = json.loads((pages / kniga.ПРОШЛЫЙ).read_text(encoding="utf-8"))
    прошлый["эталон"] = [r for r in прошлый["эталон"]
                         if r.get("sport") == "B" and r["start_kyiv"][:10] <= по_день
                         and not ("Orlando" in r["away"] and r["start_kyiv"].startswith("2026-11-29"))]
    (pages / kniga.ПРОШЛЫЙ).write_text(json.dumps(прошлый, ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", STREAMS_DB=str(out / "none.db"), **kniga.PARSE_CLOCK)
    return subprocess.Popen(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "kniga.py"), "--_parse", str(pages),
         "--clock", ЧАСЫ, "--window", "6", "--out", str(out)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(ROOT))


def ночная_игра(итог: dict) -> list:
    return [(g["home"], g["away"]) for g in итог.get("games") or []
            if g["start_kyiv"] == "2026-11-29T00:00" and "Orlando" in f"{g['home']} {g['away']}"]


def снята_повтором(итог: dict) -> list:
    return [x["фильтр"] for x in итог.get("снято") or []
            if "Washington - Orlando" in (x.get("заголовок") or "")]


with tempfile.TemporaryDirectory(prefix="etalon-prev-") as tmp:
    tmp = Path(tmp)
    # в пределах края: эталон покрывает 29.11 (дни по 30.11, край 29.11), ночной игры в нём нет
    внутри = разбор_среза(tmp, "vnutri", "2026-11-30")
    # за краем: эталон кончается 28.11 (край 27.11) — 29.11 он не покрывает
    снаружи = разбор_среза(tmp, "snaruzhi", "2026-11-28")
    журналы = {"vnutri": внутри.communicate(timeout=540)[0], "snaruzhi": снаружи.communicate(timeout=540)[0]}
    итоги = {}
    for имя, ход in (("vnutri", внутри), ("snaruzhi", снаружи)):
        файл = tmp / имя / "out" / "games.json"
        итоги[имя] = json.loads(файл.read_text(encoding="utf-8")) if файл.exists() else {}
        проверка(f"разбор «{имя}» прошёл", (ход.returncode, bool(итоги[имя])), (0, True))
        if not итоги[имя]:
            print(журналы[имя][-600:])
    проверка("в пределах края: эталон занят, край 29.11",
             (итоги["vnutri"].get(etalon_prev.KEY) or {}).get("край"), "2026-11-29")
    проверка("в пределах края: день покрыт, пары в эталоне нет — память сборов снимает строку повтором, как раньше",
             (ночная_игра(итоги["vnutri"]), снята_повтором(итоги["vnutri"])),
             ([], [parse_live.СНЯТО_СТАРЫЙ_ПОВТОР]))
    проверка("за краем: эталон занят, край 27.11",
             (итоги["snaruzhi"].get(etalon_prev.KEY) or {}).get("край"), "2026-11-27")
    проверка("за краем: день эталоном не покрыт — строка не снята, игра на месте",
             (ночная_игра(итоги["snaruzhi"]), снята_повтором(итоги["snaruzhi"])),
             ([("Washington", "Orlando")], []))
    проверка("занятый эталон едет в итог обхода (З5): записей столько, сколько занято",
             [len(итоги[имя].get("эталон") or []) == (итоги[имя].get(etalon_prev.KEY) or {}).get("записей") > 0
              for имя in ("vnutri", "snaruzhi")], [True, True])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

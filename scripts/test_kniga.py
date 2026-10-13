# -*- coding: utf-8 -*-
r"""Правила самой книги случаев, проверки перед выкладкой и шлагбаума
(владелец 13.10.2026: «чтобы не ходить кругами»; «чтоб новое не ломало
старое») — чтобы их нельзя было тихо ослабить:

1. исход теста: код 0 — зелёный; упали только «скорость:» — жёлтый; иначе
   (и падение без строк ✗) — красный (`kniga.verdict`);
2. запись случая без нужных полей, с чужим видом, без среза или теста —
   красная (`kniga.case_problems`);
3. ожидания разбора: «игра» (пара, время ±10 мин, канал сайта, пол W
   обязан совпасть), «снято», «нет» (`kniga.check_expect`);
4. потеря на сборе объяснена, только если случай книги с «нет»/«снято» — та
   же пара ±3 ч и тот же сайт (`proverka.explained`);
5. переименованная игра — не потеря, пропавший канал — потеря
   (`proverka.compare`);
6. шлагбаум пропускает после проверки только файлы автоматов
   (`push_gate.code_only`).

В сеть не ходит:
    python scripts/test_kniga.py
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import kniga  # noqa: E402
import proverka  # noqa: E402
import push_gate  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✗ {имя}: вышло {вышло!r}, ждали {ждём!r}")


def тихо(f, *a):
    with redirect_stdout(io.StringIO()):
        return f(*a)


print("1. исход теста")
проверка("код 0 — зелёный", kniga.verdict(0, "  ✗ что-то"), kniga.ЗЕЛЁНЫЙ)
проверка("упал только замер скорости — жёлтый",
         kniga.verdict(1, "  ✔ а\n  ✗ скорость: страница быстрее секунды (1.17 с)\n"), kniga.ЖЁЛТЫЙ)
проверка("скорость и ещё проверка — красный",
         kniga.verdict(1, "  ✗ скорость: быстро\n  ✗ игра есть\n"), kniga.КРАСНЫЙ)
проверка("второй вид пометки «✖» — тоже красный",
         kniga.verdict(1, "  ✖ [S3] записи ушли\n"), kniga.КРАСНЫЙ)
проверка("упал без строк ✗ (Traceback) — красный",
         kniga.verdict(1, "Traceback (most recent call last):\nKeyError: 'x'\n"), kniga.КРАСНЫЙ)
проверка("упал молча — красный", kniga.verdict(1, ""), kniga.КРАСНЫЙ)

print("2. запись случая")
полный = {"номер": 1, "дата": "2026-10-13", "вид": "жалоба", "суть": "x",
          "проверка": "тест", "тесты": ["test_kniga.py"]}
проверка("полная запись — без замечаний", kniga.case_problems(полный, set()), [])
проверка("нет «суть» — замечание",
         kniga.case_problems({k: v for k, v in полный.items() if k != "суть"}, set()),
         ["нет поля «суть»"])
проверка("чужой вид проверки — замечание",
         len(kniga.case_problems({**полный, "проверка": "глазами"}, set())), 1)
проверка("теста нет в scripts/ — замечание",
         len(kniga.case_problems({**полный, "тесты": ["test_нет_такого.py"]}, set())), 1)
разбор = {**полный, "проверка": "разбор", "срез": "sbor-1", "ждём": [{"игра": "A - B"}]}
проверка("срез не найден — замечание", len(kniga.case_problems(разбор, set())), 1)
проверка("срез есть — без замечаний", kniga.case_problems(разбор, {"sbor-1"}), [])
проверка("пустое «ждём» — замечание",
         len(kniga.case_problems({**разбор, "ждём": []}, {"sbor-1"})), 1)
проверка("битый файл — замечание", kniga.case_problems({"ошибка_файла": "битый JSON"}, set()),
         ["битый JSON"])


def игра(дом, гость, когда, *каналы, sport="F"):
    return {"home": дом, "away": гость, "start_kyiv": когда, "sport": sport, "league": "",
            "entries": [{"source": s, "channel": c} for s, c in каналы]}


print("3. ожидания разбора")
сбор = {"games": [игра("Polska W", "Belgia W", "2026-10-13T18:55", ("teleman.pl", "TVP Sport")),
                  игра("Real Madrid", "Barcelona", "2026-10-14T21:00", ("www.movistarplus.es", "M+ LaLiga"))],
        "снято": [{"домен": "raiplay.it", "заголовок": "Calcio: Bielorussia - Italia",
                   "start_kyiv": "2026-10-13T17:25", "фильтр": "показ дальше"}]}
проверка("игра есть, канал сайта есть",
         kniga.check_expect(сбор, {"игра": "Polska W - Belgia W", "время": "2026-10-13 18:55",
                                   "канал": "TVP Sport", "сайт": "teleman.pl"}), "")
проверка("время ±10 мин — та же игра",
         kniga.check_expect(сбор, {"игра": "Polska W - Belgia W", "время": "2026-10-13 19:05"}), "")
проверка("время дальше 10 мин — не та",
         kniga.check_expect(сбор, {"игра": "Polska W - Belgia W", "время": "2026-10-13 19:30"}) != "", True)
проверка("без W — не та игра (пол обязан совпасть)",
         kniga.check_expect(сбор, {"игра": "Polska - Belgia", "время": "2026-10-13 18:55"}) != "", True)
проверка("канала нет — красное",
         "без «Polsat Sport 1»" in kniga.check_expect(
             сбор, {"игра": "Polska W - Belgia W", "канал": "Polsat Sport 1", "сайт": "teleman.pl"}), True)
проверка("сайт с www — тот же сайт",
         kniga.check_expect(сбор, {"игра": "Real Madrid - Barcelona", "канал": "M+ LaLiga",
                                   "сайт": "movistarplus.es"}), "")
проверка("снято — найдено в журнале «снято»",
         kniga.check_expect(сбор, {"снято": "Bielorussia - Italia", "время": "2026-10-13 17:25",
                                   "сайт": "raiplay.it"}), "")
проверка("не снято — красное",
         kniga.check_expect(сбор, {"снято": "Polska - Belgia", "время": "2026-10-13 18:55",
                                   "сайт": "teleman.pl"}) != "", True)
проверка("«нет» и игры нет — зелёное",
         kniga.check_expect(сбор, {"нет": "Man City - Psg", "время": "2026-10-14 17:00"}), "")
проверка("«нет», а игра есть — красное",
         kniga.check_expect(сбор, {"нет": "Real Madrid - Barcelona", "время": "2026-10-14 20:00"}) != "", True)
проверка("«нет» с сайтом: игра есть, но без канала этого сайта — зелёное",
         kniga.check_expect(сбор, {"нет": "Real Madrid - Barcelona", "время": "2026-10-14 21:00",
                                   "сайт": "programetv.ro"}), "")

print("4–5. потери на сборе")
папка = Path(tempfile.mkdtemp(prefix="kniga-test-"))
(папка / "001-x.json").write_text(json.dumps({
    "номер": 3, "дата": "2026-10-13", "вид": "находка", "суть": "U19", "проверка": "разбор",
    "срез": "s", "ждём": [{"нет": "Man City - Psg", "время": "2026-10-14 17:00",
                           "сайт": "programetv.ro"}]}, ensure_ascii=False), encoding="utf-8")
kniga.CASES = папка
пропала = игра("Man City", "Psg", "2026-10-14T17:00", ("programetv.ro", "Prima Sport 4"))
проверка("пропажа объяснена случаем «нет» с тем же сайтом", proverka.explained(пропала), "3")
проверка("та же пара на другом сайте — не объяснена",
         proverka.explained(игра("Man City", "Psg", "2026-10-14T17:00", ("teleman.pl", "Canal+"))), "")
проверка("та же пара через 5 часов — не объяснена",
         proverka.explained(игра("Man City", "Psg", "2026-10-14T22:00", ("programetv.ro", "P4"))), "")
старый = {"games": [пропала,
                    игра("Polska", "Belgia", "2026-10-13T18:55", ("teleman.pl", "TVP Sport")),
                    игра("Lens", "Sporting", "2026-10-13T21:00", ("sporttv.pt", "SPORT TV5"),
                         ("rte.ie", "Virgin Media Two"))], "снято": []}
новый = {"games": [игра("Polska", "Belgia", "2026-10-13T18:55", ("teleman.pl", "TVP Sport")),
                   игра("RC Lens", "Sporting CP", "2026-10-13T21:00", ("sporttv.pt", "SPORT TV5"))],
         "снято": []}
потери = тихо(proverka.compare, старый, новый)
проверка("переименованная игра — не потеря; пропавший канал — потеря; объяснённая — нет",
         потери, ["пропал канал Virgin Media Two/rte.ie у 2026-10-13 21:00 Lens — Sporting "
                  "[SPORT TV5/sporttv.pt, Virgin Media Two/rte.ie]"])
проверка("новая игра — не потеря",
         тихо(proverka.compare, {"games": [], "снято": []}, новый), [])
переезд = игра("Al Ittihad", "Al Shabab", "2026-10-16T19:55", ("movistarplus.es", "M+ Liga"))
проверка("та же пара сдвинулась на час (ближе к эталону) — не потеря (сбор #249)",
         тихо(proverka.compare, {"games": [переезд], "снято": []},
              {"games": [{**переезд, "start_kyiv": "2026-10-16T20:55"}], "снято": []}), [])
проверка("сдвиг дальше 3 ч — уже другая игра, потеря",
         len(тихо(proverka.compare, {"games": [переезд], "снято": []},
                  {"games": [{**переезд, "start_kyiv": "2026-10-17T19:55"}], "снято": []})), 1)

print("6. шлагбаум: после проверки — только файлы автоматов")
проверка("итоги сборов, словари и план — пропускаются",
         push_gate.code_only(["results/games.json", "recon/x.html", "data/dictionaries.json",
                              "data/crawl_plan.json", ""]), [])
проверка("код и прочие данные — нет",
         push_gate.code_only(["app/canon.py", "data/aliases.json", "results/games.json"]),
         ["app/canon.py", "data/aliases.json"])

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

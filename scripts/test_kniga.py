# -*- coding: utf-8 -*-
r"""Правила самой книги случаев, проверки перед выкладкой и шлагбаума
(владелец 13.10.2026: «чтобы не ходить кругами»; «чтоб новое не ломало
старое») — чтобы их нельзя было тихо ослабить:

1. исход теста: код 0 — зелёный; упали только «скорость:» — жёлтый; иначе
   (и падение без строк ✗) — красный (`kniga.verdict`);
2. запись случая без нужных полей, с чужим видом, без среза или теста,
   «ждём» у случая-теста, «нет»/«снято» без сайта или про сайт не из
   среза — красная (`kniga.case_problems`); ноль случаев — не «зелёные»;
3. ожидания разбора: «игра» (пара, время ±10 мин, канал сайта, пол W
   обязан совпасть), «снято», «нет» (`kniga.check_expect`);
4. потеря на сборе объяснена, только если случай книги НА СТРАНИЦАХ с
   «нет»/«снято» — та же пара ±3 ч и тот же сайт; пропавшая игра — потеря
   каждого её канала (`proverka.explained`, `compare`);
5. переименованная игра (по паре или по каналам), двойня, склеенная в
   прежнюю, сдвиг ближе к эталону — не потеря; сдвиг от эталона или без
   него, пропавший канал — потеря (`proverka.compare`);
6. шлагбаум без новой проверки пропускает только коммиты автоматов и только
   в их файлах (`push_gate.code_only`, `not_automata`).
Находки независимой проверки ветки 13.10 — все здесь.

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
срезы = Path(tempfile.mkdtemp(prefix="kniga-slices-"))
(срезы / "sbor-1.json").write_text(json.dumps({"сайты": ["teleman.pl"]}), encoding="utf-8")
kniga.SLICES = срезы
разбор = {**полный, "проверка": "разбор", "срез": "sbor-1", "ждём": [{"игра": "A - B"}]}
del разбор["тесты"]
проверка("срез не найден — замечание", len(kniga.case_problems(разбор, set())), 1)
проверка("срез есть — без замечаний", kniga.case_problems(разбор, {"sbor-1"}), [])
проверка("пустое «ждём» — замечание",
         len(kniga.case_problems({**разбор, "ждём": []}, {"sbor-1"})), 1)
проверка("битый файл — замечание", kniga.case_problems({"ошибка_файла": "битый JSON"}, set()),
         ["битый JSON"])
проверка("у случая-теста «ждём» — замечание (оправдывал бы потери)",
         len(kniga.case_problems({**полный, "ждём": [{"нет": "A - B"}]}, set())), 1)
проверка("«нет» без сайта — замечание (зелёно при любом коде)",
         len(kniga.case_problems({**разбор, "ждём": [{"нет": "A - B", "время": "2026-10-13 18:00"}]},
                                 {"sbor-1"})), 1)
проверка("«снято» про сайт не из среза — замечание",
         len(kniga.case_problems({**разбор, "ждём": [{"снято": "A - B", "время": "2026-10-13 18:00",
                                                      "сайт": "raiplay.it"}]}, {"sbor-1"})), 1)
проверка("«нет» про сайт из среза — без замечаний",
         kniga.case_problems({**разбор, "ждём": [{"нет": "A - B", "время": "2026-10-13 18:00",
                                                  "сайт": "www.teleman.pl"}]}, {"sbor-1"}), [])
проверка("срез без описания .json — замечание",
         len(kniga.case_problems({**разбор, "срез": "sbor-2"}, {"sbor-2"})), 1)
проверка("ноль случаев — не «все зелёные»", kniga.summary(0, [], []).startswith("книга: 0"), True)


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
(папка / "002-y.json").write_text(json.dumps({
    "номер": 7, "дата": "2026-10-13", "вид": "новое", "суть": "тест", "проверка": "тест",
    "тесты": ["test_kniga.py"], "ждём": [{"нет": "Real Madrid - Barcelona", "время": "2026-10-14 21:00",
                                          "сайт": "teleman.pl"}]}, ensure_ascii=False), encoding="utf-8")
kniga.CASES = папка
пропала = игра("Man City", "Psg", "2026-10-14T17:00", ("programetv.ro", "Prima Sport 4"))
проверка("пропажа объяснена случаем «нет» с тем же сайтом",
         proverka.explained(пропала, "programetv.ro"), "3")
проверка("та же пара на другом сайте — не объяснена",
         proverka.explained(пропала, "teleman.pl"), "")
проверка("та же пара через 5 часов — не объяснена",
         proverka.explained(игра("Man City", "Psg", "2026-10-14T22:00"), "programetv.ro"), "")
проверка("«нет» из случая-теста не объясняет (книга его не проверяет)",
         proverka.explained(игра("Real Madrid", "Barcelona", "2026-10-14T21:00"), "teleman.pl"), "")
два_сайта = игра("Man City", "Psg", "2026-10-14T17:00", ("programetv.ro", "Prima Sport 4"),
                 ("digisport.ro", "Digi Sport 4"))
проверка("пропала игра на двух сайтах, случай про один — потеря",
         len(тихо(proverka.compare, {"games": [два_сайта], "снято": []}, {"games": [], "снято": []})), 1)
проверка("пропала игра, все её сайты объяснены — не потеря",
         тихо(proverka.compare, {"games": [пропала], "снято": []}, {"games": [], "снято": []}), [])
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
эталон = [{"home": "Al Ittihad", "away": "Al Shabab", "start_kyiv": "2026-10-16T21:00"}]


def сдвиг(когда: str, ref=эталон) -> list:
    return тихо(proverka.compare, {"games": [переезд], "снято": []},
                {"games": [{**переезд, "start_kyiv": когда}], "снято": [], "эталон": ref})


проверка("сдвиг на час ближе к эталону — переезд, не потеря (сбор #249)", сдвиг("2026-10-16T20:55"), [])
проверка("сдвиг дальше от эталона (ошибка пояса) — потеря", len(сдвиг("2026-10-16T18:55")), 1)
проверка("сдвиг без эталона — потеря (не доказано, что ближе)", len(сдвиг("2026-10-16T20:55", [])), 1)
проверка("сдвиг дальше 3 ч — уже другая игра, потеря", len(сдвиг("2026-10-17T19:55")), 1)
марсель = игра("Olympique Marseille", "Olympiakos Piraeus", "2026-10-15T21:50",
               ("digisport.ro", "Digi Sport 4"), ("teleman.pl", "Polsat Sport Extra 4"))
марсела = игра("Olympique de Marsella", "Olympiakos Piraeus", "2026-10-15T21:50",
               ("digisport.ro", "Digi Sport 4"), ("teleman.pl", "Polsat Sport Extra 4"),
               ("movistarplus.es", "M+ Liga de Campeones 2"))
проверка("имя взято у нового сайта, все каналы на месте — та же игра (сбор #249)",
         тихо(proverka.compare, {"games": [марсель], "снято": []}, {"games": [марсела], "снято": []}), [])
лок = игра("Lokomotiv", "Krasnodar", "2026-10-12T19:30", ("nova.bg", "Nova Sport"))
двойня = игра("Локомотив", "Краснодар", "2026-10-12T20:30", ("ntvplus.tv", "Матч ТВ"))
склейка = игра("Lokomotiv", "Krasnodar", "2026-10-12T19:30", ("nova.bg", "Nova Sport"),
               ("ntvplus.tv", "Матч ТВ"))
проверка("двойня склеена в прежнюю игру, каналы при ней — не потеря (случай 036)",
         тихо(proverka.compare, {"games": [лок, двойня], "снято": []},
              {"games": [склейка], "снято": []}), [])
проверка("двойня склеена, но её канал потерян — потеря",
         len(тихо(proverka.compare, {"games": [лок, двойня], "снято": []},
                  {"games": [лок], "снято": []})), 1)

print("6. шлагбаум: после проверки — только автоматы и только их файлы")
проверка("итоги сборов, словари и план — файлы автоматов",
         push_gate.code_only(["results/games.json", "recon/x.html", "data/dictionaries.json",
                              "data/crawl_plan.json", ""]), [])
проверка("код и прочие данные — нет",
         push_gate.code_only(["app/canon.py", "data/aliases.json", "results/games.json"]),
         ["app/canon.py", "data/aliases.json"])
проверка("коммиты сбора и сервера в их файлах — пропускаются",
         push_gate.not_automata([("a" * 40, "actions@github.com", ["results/games.json"]),
                                 ("b" * 40, "server@streams-schedule.local", ["data/dictionaries.json"])]), [])
проверка("ручная правка плана — через проверку, как код (20ca824)",
         len(push_gate.not_automata([("c" * 40, "noreply@anthropic.com", ["data/crawl_plan.json"])])), 1)
проверка("автомат тронул код — не пропускается",
         len(push_gate.not_automata([("d" * 40, "server@streams-schedule.local", ["app/web.py"])])), 1)

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

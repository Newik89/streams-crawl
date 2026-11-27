"""Книга 183 (28.11): источник magentatv.de — телегид MagentaTV, каналы «DE| Magenta Sport 1–18».

Записи телегида в тесте — настоящие, из пробы 28.11.2026 (запуск #564). Сеть подменена: к сайту тест не ходит.

Запуск: python scripts/test_magentatv.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
TMP = Path(tempfile.mkdtemp(prefix="magentatv-test-"))
os.environ["STREAMS_DB"] = str(TMP / "t.db")

from app import (canon, channel_page, crawl, db, dictionary, fetch, live, parsers,  # noqa: E402
                 site_lang, sport, urls)
from app.parsers import SITE_FLAG, SITE_LIVE, flashscore_mobi, magentatv_de  # noqa: E402
import add_magentatv  # noqa: E402
import flashscore_locales  # noqa: E402
import crawl_fetch  # noqa: E402
import crawl_plan  # noqa: E402

зелёных = красных = 0
РУЧКА = "https://api.prod.sngtv.magentatv.de/EPG/JSON/PlayBillList?channel_id="


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def ответ(*записи: dict) -> str:
    return json.dumps({"counttotal": str(len(записи)), "playbilllist": list(записи)}, ensure_ascii=False)


# ── настоящие записи телегида (проба 28.11.2026) ─────────────────────────────
ЗАГЛУШКА = {"id": "58917651", "name": "myTeamTV: Momentan kein Programm", "introduce": "Momentan kein Programm.",
            "channelid": "550", "starttime": "2026-11-26 21:35:00 UTC+00:00",
            "endtime": "2026-11-27 01:00:00 UTC+00:00", "genres": "Unterhaltung"}
ТОПШПИЛЬ = {"id": "58930495", "name": "LIVE: Tipico Topspiel der Woche: Hansa Rostock - TSV Havelse",
            "introduce": "Hansa Rostock - TSV Havelse, 3. Liga, Spieltag 15", "channelid": "550",
            "starttime": "2026-11-27 17:30:00 UTC+00:00", "endtime": "2026-11-27 21:00:00 UTC+00:00",
            "genres": "Fußball"}
КОНФЕРЕНЦИЯ = {"id": "58943652", "name": "LIVE: 3. Liga - Konferenz",
               "introduce": "3. Liga - Konferenz, 3. Liga, Spieltag 15", "channelid": "550",
               "starttime": "2026-11-28 12:30:00 UTC+00:00", "endtime": "2026-11-28 15:30:00 UTC+00:00",
               "genres": "Sport,Fußball"}
ЛАТВИЯ = {"id": "58931117", "name": "LIVE: Lettland - Deutschland",
          "introduce": "Lettland - Deutschland, Basketball, FIBA World Cup Qualifiers Spieltag 3",
          "channelid": "3686", "starttime": "2026-11-27 17:15:00 UTC+00:00",
          "endtime": "2026-11-27 21:00:00 UTC+00:00", "genres": "Basketball"}
ХОККЕЙ = {"id": "58931583", "name": "LIVE: Kölner Haie - Straubing Tigers",
          "introduce": "Kölner Haie - Straubing Tigers, 2026/2027, Hauptrunde Spieltag 20", "channelid": "648",
          "starttime": "2026-11-27 18:15:00 UTC+00:00", "endtime": "2026-11-27 21:35:00 UTC+00:00",
          "genres": "Sport"}
ХОККЕЙ_КОНФ = {"id": "58931474", "name": "LIVE: PENNY DEL - Konferenz",
               "introduce": "PENNY DEL - Konferenz, PENNY DEL, Hauptrunde Spieltag 20", "channelid": "548",
               "starttime": "2026-11-27 18:00:00 UTC+00:00", "endtime": "2026-11-27 21:40:00 UTC+00:00",
               "genres": "Sport"}
ПОВТОР = {"id": "59077110", "name": "Lettland - Deutschland",
          "introduce": "Lettland - Deutschland, Basketball, FIBA World Cup Qualifiers Spieltag 3",
          "channelid": "3757", "starttime": "2026-11-28 07:45:00 UTC+00:00",
          "endtime": "2026-11-28 10:00:00 UTC+00:00",
          "subName": "Lettland - Deutschland, Basketball, FIBA World Cup Qualifiers Spieltag 3",
          "genres": "Basketball"}
ОБЗОР = {"id": "58917448", "name": "MagentaSport Programmübersicht",
         "introduce": "Das komplette MagentaSport Programm für die nächsten Spieltage - übersichtlich und kompakt.",
         "channelid": "5075", "starttime": "2026-11-26 21:00:00 UTC+00:00",
         "endtime": "2026-11-27 01:00:00 UTC+00:00"}

print("Разбор ответа телегида: правила Р1–Р6")
первый = magentatv_de.parse(ответ(ЗАГЛУШКА, ТОПШПИЛЬ, КОНФЕРЕНЦИЯ), url=РУЧКА + "550")
проверка("Р3: заглушка «Momentan kein Programm» — не передача; остальные две строки взяты",
         [p.title for p in первый],
         ["LIVE: Tipico Topspiel der Woche: Hansa Rostock - TSV Havelse", "LIVE: 3. Liga - Konferenz"])
проверка("Р3: заглушка «MagentaSport Programmübersicht» — не передача",
         magentatv_de.parse(ответ(ОБЗОР), url=РУЧКА + "5075"), [])
проверка("Р1: канал — по номеру записи, имя как в телегиде",
         {p.channel_raw for p in первый}, {"Sport 1 - myTeamTV"})
проверка("Р1: номера в записи нет — канал по номеру в адресе",
         magentatv_de.parse(ответ({**ЛАТВИЯ, "channelid": ""}), url=РУЧКА + "3686")[0].channel_raw,
         "Sport 18 - myTeamTV")
проверка("Р1: номер незнаком — имя с номером, строка не теряется",
         magentatv_de.parse(ответ({**ЛАТВИЯ, "channelid": "99999"}), url=РУЧКА + "99999")[0].channel_raw,
         "MagentaTV 99999")
латвия = magentatv_de.parse(ответ(ЛАТВИЯ), url=РУЧКА + "3686")[0]
проверка("Р2: время UTC из ответа → пояс источника (Берлин): 17:15 UTC = 18:15",
         (латвия.start.isoformat(), латвия.raw_time, латвия.extra["day"]),
         ("2026-11-27T18:15:00+01:00", "18:15", "2026-11-27"))
проверка("Р2: другой пояс по слову вызывающего (Киев): 19:15 — как на витрине",
         magentatv_de.parse(ответ(ЛАТВИЯ), tz="Europe/Kyiv", url=РУЧКА + "3686")[0].start.strftime("%H:%M"),
         "19:15")
проверка("Р4: «LIVE:» — слово сайта об эфире",
         (латвия.live_raw, латвия.extra.get(SITE_FLAG)), ("live", SITE_LIVE))
повтор = magentatv_de.parse(ответ(ПОВТОР), url=РУЧКА + "3757")[0]
проверка("Р4: без «LIVE:» сайт об эфире молчит (повтор на «MS Sport») — пометки нет",
         (повтор.channel_raw, повтор.live_raw, SITE_FLAG in повтор.extra), ("MS Sport", "", False))
проверка("Р5: пара — после последнего двоеточия («Tipico Topspiel der Woche: …»)",
         [p.match_raw for p in первый], ["Hansa Rostock - TSV Havelse", "3. Liga - Konferenz"])
проверка("Р5: названия без « - » — пары нет",
         magentatv_de.parse(ответ({**ЛАТВИЯ, "name": "LIVE: Magazin"}), url=РУЧКА + "3686")[0].match_raw, " ")
проверка("Р6: баскетбол — вид спорта и турнир из описания, номер тура не турнир",
         (латвия.sport_raw, латвия.league_raw, латвия.match_raw),
         ("Basketball", "FIBA World Cup Qualifiers", "Lettland - Deutschland"))
проверка("Р6: футбол — вид спорта из жанра, турнир «3. Liga»; общее «Sport» в жанре — не вид спорта",
         [(p.sport_raw, p.league_raw) for p in первый], [("Fußball", "3. Liga"), ("Fußball", "3. Liga")])
хоккей = magentatv_de.parse(ответ(ХОККЕЙ, ХОККЕЙ_КОНФ), url=РУЧКА + "648")
проверка("Р6: хоккей — жанр «Sport» видом спорта не считается; сезон «2026/2027» — не турнир; "
         "турнир — первый кусок, стадия за ним не берётся",
         [(p.channel_raw, p.sport_raw, p.league_raw) for p in хоккей],
         [("Sport 4 - myTeamTV", "", "Hauptrunde"), ("Sport 2 - myTeamTV", "", "PENNY DEL")])
ЕВРОЛИГА = {"id": "1", "name": "LIVE: Fenerbahce Tarfin Istanbul - Roter Stern Meridianbet Belgrad",
            "introduce": "Fenerbahce Istanbul - Roter Stern Belgrad, 2026/2027, Hauptrunde Spieltag 15",
            "channelid": "549", "starttime": "2026-12-03 17:30:00 UTC+00:00",
            "endtime": "2026-12-03 20:00:00 UTC+00:00", "genres": "Basketball"}
ХОККЕЙ_ЛЧ = {"id": "2", "name": "LIVE: Eisbären Berlin - Dynamo Pardubice",
             "introduce": "Eisbären Berlin - Dynamo Pardubice, Champions Hockey League, Viertelfinale Spiel 1",
             "channelid": "550", "starttime": "2026-12-02 17:45:00 UTC+00:00",
             "endtime": "2026-12-02 20:30:00 UTC+00:00", "genres": "Sport"}
евролига = magentatv_de.parse(ответ(ЕВРОЛИГА, ХОККЕЙ_ЛЧ, ОБЗОР | {"name": "Magazin", "channelid": "549"}),
                              url=РУЧКА + "549")
проверка("Р6: пара в описании написана иначе, чем в заголовке (сбор 28.11), — она не турнир; "
         "пара строки — из заголовка",
         (евролига[0].match_raw, евролига[0].league_raw, евролига[0].sport_raw),
         ("Fenerbahce Tarfin Istanbul - Roter Stern Meridianbet Belgrad", "Hauptrunde", "Basketball"))
проверка("Р6: турнир — первый кусок после названия («Champions Hockey League»), стадия за ним не берётся",
         евролига[1].league_raw, "Champions Hockey League")
проверка("Р6: описание — свободный текст о передаче: турнира нет", евролига[2].league_raw, "")
проверка("канал не из списка владельца — пусто",
         magentatv_de.parse(ответ(ЛАТВИЯ), url=РУЧКА + "3686", channels={"Sport 1 - myTeamTV"}), [])
проверка("ответ «войдите заново», пустая строка, не JSON — пусто, без падения",
         [magentatv_de.parse(x, url=РУЧКА + "550") for x in
          ('{"retcode":"-2","desc":"User\'s session has been expired, please relogin EPG."}', "", "<html>")],
         [[], [], []])
проверка("в разборщике все 18 каналов «Sport N - myTeamTV», номера разные",
         sorted(int(n.split()[1]) for n in magentatv_de.CHANNELS.values() if n.startswith("Sport ")),
         list(range(1, 19)))

print("Общий отсев: сводная трансляция — не матч; клубы DEL — хоккей")
ВСЕ = live.load()
ВИДЫ = sport.load()


def стоп(домен: str, заголовок: str) -> str:
    markers = ВСЕ.for_langs(site_lang.of(домен))
    return markers.found(markers.stop_title, заголовок)


def взята(домен: str, program) -> bool:
    """Берёт ли обход строку в ленту (`live.check`)."""
    return live.check(program, ВСЕ.for_langs(site_lang.of(домен))).ok


проверка("«LIVE: 3. Liga - Konferenz» — стоп-слово немецкого сайта; с пометкой эфира в ленту не идёт",
         (стоп("magentatv.de", первый[1].title).lower(), взята("magentatv.de", первый[1])), ("konferenz", False))
проверка("матч той же лиги с того же канала в ленту идёт", взята("magentatv.de", первый[0]), True)
проверка("слово только немецкое: Лига конференций на других языках — не стоп",
         [стоп(d, t) for d, t in (
             ("oneplay.cz", "Fotbal - Konferenční liga, ligová fáze, Kairat - Mjällby"),
             ("tv3.lt", "UEFA Konferencijų lygos rungtynės. „Kauno Žalgiris“ - „Riga FC“"),
             ("trtspor.com.tr", "UEFA Konferans Ligi: Trabzonspor - CSKA"))], ["", "", ""])
проверка("немецкие сайты лигу пишут «Conference League» — не стоп",
         стоп("srf.ch", "Fussball – UEFA Conference League Männer 4. Spieltag, Ajax Amsterdam (NED) – FC Thun (SUI)"),
         "")
вердикты = [ВИДЫ.decide(f"{p.title} {p.league_raw} {p.sport_raw} {p.description}",
                        pair=tuple(p.match_raw.split(" - "))) for p in хоккей]
проверка("хоккей DEL: клубы и «PENNY DEL» — чужой вид спорта «хоккей», владельцу на разбор не идут",
         [(v.letter, v.group) for v in вердикты], [("-", "хоккей"), ("-", "хоккей")])
футбол = ВИДЫ.decide("LIVE: FC Ingolstadt 04 - Jahn Regensburg 3. Liga Fußball",
                     pair=("FC Ingolstadt 04", "Jahn Regensburg"))
проверка("футбольный «FC Ingolstadt 04» с хоккейным «ERC Ingolstadt» не спутан", футбол.letter, "F")
проверка("все 14 клубов DEL из живой сетки 27–29.11 — хоккей",
         [n for n in ("Adler Mannheim", "Augsburger Panther", "Eisbären Berlin", "Pinguins Bremerhaven",
                      "Löwen Frankfurt", "EHC Red Bull München", "ERC Ingolstadt", "Iserlohn Roosters",
                      "Kölner Haie", "Krefeld Pinguine", "Nürnberg Ice Tigers", "Schwenninger Wild Wings",
                      "Straubing Tigers", "Grizzlys Wolfsburg")
          if ВИДЫ.decide(f"LIVE: Testverein - {n} Hauptrunde", pair=("Testverein", n)).letter != "-"], [])

print("Метка даты со сдвигом и тело запроса")
проверка("{YYYYMMDD} и {YYYYMMDD+7}: окно от дня на неделю, через границу месяца",
         (urls.resolve("{YYYYMMDD}000000", "", day=date(2026, 11, 28)),
          urls.resolve("{YYYYMMDD+7}000000", "", day=date(2026, 11, 28))),
         ("20261128000000", "20261205000000"))
проверка("сдвиг через границу года и с разделителями",
         (urls.resolve("{YYYY-MM-DD+1}", "", day=date(2026, 12, 31)),
          urls.resolve("{DD.MM.YYYY+10}", "", day=date(2026, 12, 25))), ("2027-01-01", "04.01.2027"))
проверка("прежние метки не задеты: дата без сдвига, чужая метка остаётся в адресе",
         urls.resolve("https://x/{YYYY}/{MM}/{DD}?c={channel_id}&k={UNKNOWN+1}", "", day=date(2026, 3, 5),
                      channel_id="7"), "https://x/2026/03/05?c=7&k={UNKNOWN+1}")
тело = crawl_fetch.json_body({"post_json": add_magentatv.BODY}, date(2026, 11, 28), РУЧКА + "3686")
проверка("тело запроса: номер канала — из адреса, окно — неделя",
         (тело["channelid"], тело["begintime"], тело["endtime"], тело["count"], тело["type"]),
         ("3686", "20261128000000", "20261205000000", -1, 2))

print("Гостевая сессия читателя: правила Г1–Г4")
журнал: list = []
сценарий = {"ключи": ["KLYUCH-1", "KLYUCH-2"], "протух": set(), "вход_сломан": False}
ВОЙДИТЕ = '{"retcode":"-2","desc":"User\'s session has been expired, please relogin EPG."}'


class _Ответ:
    def __init__(self, text: str, status: int = 200):
        self.status_code, self.ok = status, status == 200
        self.headers = {"content-type": "application/json;charset=UTF-8"}
        self.text, self.content, self.url = text, text.encode("utf-8"), ""

    def json(self):
        return json.loads(self.text)


class _Сессия:
    def __init__(self):
        self.ключ = ""
        журнал.append(("сессия",))

    def post(self, url, json=None, data=None, headers=None, **kw):
        if "/Authenticate" in url:
            журнал.append(("вход", url, json))
            if сценарий["вход_сломан"]:
                return _Ответ('{"retcode":"-1"}')
            self.ключ = сценарий["ключи"].pop(0)
            return _Ответ('{"retcode":"0","csrfToken":"%s"}' % self.ключ)
        ключ = (headers or {}).get("X_CSRFToken")
        журнал.append(("запрос", url, json, ключ, (headers or {}).get("Origin")))
        if not ключ or ключ != self.ключ or ключ in сценарий["протух"]:
            return _Ответ(ВОЙДИТЕ)
        return _Ответ(ответ(ЛАТВИЯ))

    def get(self, url, **kw):
        журнал.append(("get", url))
        return _Ответ("<html>обычная страница</html>")


def _мимо_сессии(url, **kw):
    журнал.append(("мимо", url))
    return _Ответ("<html>обычная страница</html>")


подмена = types.ModuleType("requests")
подмена.Session = _Сессия
подмена.get = подмена.post = _мимо_сессии
sys.modules["requests"] = подмена
fetch.CACHE = TMP / "pages"
fetch.DELAY = 0


def из(вид: str) -> list:
    return [z for z in журнал if z[0] == вид]


грузчик = fetch.Fetcher(offline=False, use_cache=False)
первая = грузчик.get(РУЧКА + "3686", post_json={"channelid": "3686"})
вторая = грузчик.get(РУЧКА + "550", post_json={"channelid": "550"})
проверка("Г1: вход один раз на хост; тело входа — гость без аккаунта (userType 3), JSON",
         (len(из("вход")), len(из("сессия")), из("вход")[0][2]["userType"], из("вход")[0][2]["terminaltype"]),
         (1, 1, 3, "WEBTV"))
проверка("Г2: оба запроса ушли сессией входа, с ключом и заголовком сайта; тело — своё у каждого",
         [(z[2], z[3], z[4]) for z in из("запрос")],
         [({"channelid": "3686"}, "KLYUCH-1", "https://web.magentatv.de"),
          ({"channelid": "550"}, "KLYUCH-1", "https://web.magentatv.de")])
проверка("Г2: ответы получены и разбираются", (первая.ok, вторая.ok, len(magentatv_de.parse(первая.html))),
         (True, True, 1))
проверка("ключ сессии в сохранённую страницу не попал",
         [p.name for p in (TMP / "pages").iterdir() if "KLYUCH" in p.read_text(encoding="utf-8")], [])
журнал.clear()
сценарий["протух"] = {"KLYUCH-1"}
третья = грузчик.get(РУЧКА + "648", post_json={"channelid": "648"})
проверка("Г3: сессия протухла — вход заново и запрос повторён один раз, ответ получен",
         (len(из("вход")), [z[3] for z in из("запрос")], третья.ok), (1, ["KLYUCH-1", "KLYUCH-2"], True))
журнал.clear()
сломанный = fetch.Fetcher(offline=False, use_cache=False)
сценарий["вход_сломан"] = True
четвёртая = сломанный.get(РУЧКА + "550", post_json={"channelid": "550"})
проверка("Г4: вход не удался — страница не открылась и названа причина, а не «пустое расписание»",
         (четвёртая.ok, четвёртая.error, len(из("вход")), len(из("запрос"))),
         (False, "гостевой вход не удался", 2, 2))
журнал.clear()
обычная = fetch.Fetcher(offline=False, use_cache=False).get("https://example.org/programm")
проверка("чужой хост: ни входа, ни сессии — обычный запрос, как раньше",
         (обычная.ok, [z[0] for z in журнал]), (True, ["мимо"]))

print("Сайт вписан в списки программы")
проверка("разборщик найден по домену плана", parsers.get("magentatv.de") is magentatv_de.parse, True)
проверка("сетка «адрес на канал, один запрос»; в списке плана; язык сайта — немецкий",
         ("magentatv.de" in crawl.CHANNEL_GRID_DOMAINS, "magentatv.de" in crawl_plan.PILOTS,
          "de" in (site_lang.of("magentatv.de") or ())), (True, True, True))
шаблоны = json.loads((ROOT / "data" / "channel_pages.json").read_text(encoding="utf-8"))
проверка("↗: адрес ручки — машинный, человеку — страница телегида",
         (channel_page.is_machine(РУЧКА + "550", "magentatv.de"),
          шаблоны["magentatv.de"]["page"], channel_page.is_machine(шаблоны["magentatv.de"]["page"], "magentatv.de")),
         (True, "https://web.magentatv.de/tv-guide", False))

print("Немецкие имена баскетбольных команд: языковая версия эталона")
db.init_db()
conn = db.connect()
немецкая = conn.execute(
    "INSERT INTO sources (domain, name, base_url, country, timezone, role, access, url_pattern, needs_js, "
    "selector_config, enabled, status) VALUES ('m.flashscore.de', 'Flashscore de', 'https://m.flashscore.de/', "
    "'DE', 'UTC', 'schedule', 'open', 'https://m.flashscore.de/?d={DAYNUM}', 0, '{}', 1, 'ok')").lastrowid
flashscore_locales._channels(conn, немецкая, "m.flashscore.de", "de")
flashscore_locales._channels(conn, немецкая, "m.flashscore.de", "de")
conn.commit()
разделы = {r["raw_name"]: r["page_url"] for r in conn.execute(
    "SELECT raw_name, page_url FROM source_channels WHERE source_id = ?", (немецкая,))}
проверка("у немецкой версии эталона — футбол и баскетбол, по странице на раздел; повтор не двоит",
         разделы, {"football": "https://m.flashscore.de/?d={DAYNUM}",
                   "basketball": "https://m.flashscore.de/basketball/?d={DAYNUM}"})
проверка("страница раздела читается как баскетбол; футбольная — как футбол",
         (flashscore_mobi._sport_from_url(разделы["basketball"]), flashscore_mobi._sport_from_url(разделы["football"])),
         ("Basketball", "Soccer"))
with zipfile.ZipFile(ROOT / "kniga" / "slices" / "proba-565-magentatv.zip") as срез:
    страница_эталона = срез.read("m.flashscore.de__basketball__d=6.html").decode("utf-8")
эталон_de = flashscore_mobi.parse(страница_эталона, day=date(2026, 12, 3),
                                  url="https://m.flashscore.de/basketball/?d=6")
проверка("настоящая страница 03.12 (проба #566): матч Евролиги с немецким именем «Roter Stern Belgrad»",
         [p.match_raw for p in эталон_de if "Roter Stern" in p.match_raw][:1], ["Fenerbahçe - Roter Stern Belgrad"])
ЗАПИСЬ_ЭТАЛОНА = {"sport": "B", "home": "Fenerbahce", "away": "Crvena Zvezda Meridianbet",
                  "league": "EUROPE: Euroleague", "fs_id": "I7Ilx7nR", "start_kyiv": "2026-12-03T19:45",
                  "names": {"el": ["Φενερμπαχτσέ", "Ερυθρός Αστέρας"], "hr": ["Fenerbahce", "Crvena Zvezda Meridianbet"],
                            "de": ["Fenerbahçe", "Roter Stern Belgrad"]}}
ИГРА_ТЕЛЕГИДА = {"sport": "B", "league": "", "home": "Fenerbahce Tarfin Istanbul",
                 "away": "Roter Stern Meridianbet Belgrad", "start_kyiv": "2026-12-03T19:30",
                 "start_utc": "2026-12-03T17:30",
                 "entries": [{"source": "magentatv.de", "channel": "Sport 3 - myTeamTV",
                              "start_kyiv": "2026-12-03T19:30",
                              "raw_title": "LIVE: Fenerbahce Tarfin Istanbul - Roter Stern Meridianbet Belgrad"}]}
с_немецкими = canon.align([dict(ИГРА_ТЕЛЕГИДА)], [ЗАПИСЬ_ЭТАЛОНА], {})
без_немецких = canon.align([dict(ИГРА_ТЕЛЕГИДА)], [{**ЗАПИСЬ_ЭТАЛОНА, "names": {
    k: v for k, v in ЗАПИСЬ_ЭТАЛОНА["names"].items() if k != "de"}}], {})
проверка("сверка сервера: с немецкими именами эталона игра телегида сходится с матчем Евролиги — двойника нет",
         [(len(с_немецкими["sure"]), с_немецкими["sure"][0][1]["fs_id"] if с_немецкими["sure"] else None),
          len(с_немецкими["missed"])], [(1, "I7Ilx7nR"), 0])
проверка("без немецких имён та же игра с эталоном не сходилась (так было до книги 183) — вторая игра на витрине",
         (len(без_немецких["sure"]), len(без_немецких["missed"])), (0, 1))

print("Заведение источника: правила 1–4")
греческий = dictionary.remember_channel(conn, "Magenta Sport 1", "Magenta Sport 1", "GR")
сказано = add_magentatv.apply(conn)
src = conn.execute("SELECT * FROM sources WHERE domain = 'magentatv.de'").fetchone()
проверка("правило 1: источник — обычный запрос, пояс Берлина, открыт, включён; тело запроса в карточке",
         (src["needs_js"], src["timezone"], src["access"], src["enabled"], src["status"], src["country"],
          json.loads(src["selector_config"])["post_json"] == add_magentatv.BODY),
         (0, "Europe/Berlin", "open", 1, "ok", "DE", True))
каналы = {r["raw_name"]: (r["canonical_name"], r["country"], r["custom_name"], r["note"], r["page_url"])
          for r in conn.execute(
              "SELECT sc.raw_name, c.canonical_name, c.country, c.custom_name, c.note, sc.page_url "
              "FROM source_channels sc JOIN channels c ON c.id = sc.channel_id "
              "WHERE sc.source_id = ? AND sc.include = 1", (src["id"],))}
проверка("правило 2: 18 каналов; имя владельца «DE| Magenta Sport N», страна DE, пометка DE; свой адрес",
         (len(каналы), каналы["Sport 1 - myTeamTV"], каналы["Sport 18 - myTeamTV"]),
         (18, ("DE| Magenta Sport 1", "DE", 1, "DE", РУЧКА + "550"),
          ("DE| Magenta Sport 18", "DE", 1, "DE", РУЧКА + "3686")))
проверка("правило 2: имена — ровно «DE| Magenta Sport 1» … «DE| Magenta Sport 18»",
         sorted((v[0] for v in каналы.values()), key=lambda n: int(n.rsplit(" ", 1)[1])),
         [f"DE| Magenta Sport {n}" for n in range(1, 19)])
проверка("правило 2: греческий «Magenta Sport 1» — другой канал, не тронут",
         (conn.execute("SELECT canonical_name, country, custom_name FROM channels WHERE id = ?",
                       (греческий,)).fetchone()[:], conn.execute(
             "SELECT COUNT(*) FROM channels WHERE country = 'GR'").fetchone()[0]),
         (("Magenta Sport 1", "GR", 0), 1))
проверка("правило 4: «MS Sport», «MS GOLF», «MagentaSport» не заведены",
         [n for n in каналы if not n.startswith("Sport ")], [])
conn.execute("UPDATE channels SET canonical_name = 'DE| MagentaSport 7 HD' WHERE canonical_name = "
             "'DE| Magenta Sport 7'")
conn.execute("UPDATE sources SET selector_config = ? WHERE id = ?",
             (json.dumps({**json.loads(src["selector_config"]), "days_ahead": 3}), src["id"]))
conn.commit()
add_magentatv.apply(conn)
проверка("правило 3: повторный запуск ничего не дублирует, имя, данное владельцем позже, не затирает",
         (conn.execute("SELECT COUNT(*) FROM sources WHERE domain = 'magentatv.de'").fetchone()[0],
          conn.execute("SELECT COUNT(*) FROM source_channels WHERE source_id = ?", (src["id"],)).fetchone()[0],
          conn.execute("SELECT COUNT(*) FROM channels WHERE country = 'DE'").fetchone()[0],
          conn.execute("SELECT c.canonical_name FROM source_channels sc JOIN channels c ON c.id = sc.channel_id "
                       "WHERE sc.source_id = ? AND sc.raw_name = 'Sport 7 - myTeamTV'",
                       (src["id"],)).fetchone()[0]),
         (1, 18, 18, "DE| MagentaSport 7 HD"))
проверка("правило 1: чужое поле карточки источника при повторе цело",
         json.loads(conn.execute("SELECT selector_config FROM sources WHERE id = ?",
                                 (src["id"],)).fetchone()[0]).get("days_ahead"), 3)
conn.execute("UPDATE sources SET selector_config = ? WHERE id = ?",
             (json.dumps({"post_json": add_magentatv.BODY}), src["id"]))
conn.commit()
план = {"days": 6, "sources": crawl.templates(conn, ["magentatv.de"])}
запись = план["sources"][0] if план["sources"] else {}
проверка("запись плана обхода: не браузер, один запрос на канал, 18 адресов, тело запроса на месте",
         (запись.get("browser"), запись.get("days_inline"), len(запись.get("channels") or []),
          запись.get("post_json") == add_magentatv.BODY, запись.get("timezone")),
         (False, True, 18, True, "Europe/Berlin"))
задания = list(crawl_fetch.targets(план, 6, False))
восемнадцатый = next((j for j in задания if j["channel"] == "Sport 18 - myTeamTV"), {})
проверка("задания обхода: 18 запросов за сбор при окне 6 суток; у каждого своё тело с номером канала",
         (len(задания), len({json.dumps(j["post_json"], sort_keys=True) for j in задания}),
          восемнадцатый.get("url"), (восемнадцатый.get("post_json") or {}).get("channelid")),
         (18, 18, РУЧКА + "3686", "3686"))
окно = восемнадцатый.get("post_json") or {}
проверка("окно в теле запроса — 7 суток от «сегодня» сайта",
         (date(int(окно["endtime"][:4]), int(окно["endtime"][4:6]), int(окно["endtime"][6:8]))
          - date(int(окно["begintime"][:4]), int(окно["begintime"][4:6]), int(окно["begintime"][6:8]))).days, 7)
conn.close()

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

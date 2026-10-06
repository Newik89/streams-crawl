# -*- coding: utf-8 -*-
"""Парсеры источников: один модуль на сайт, общий вид результата.

Каждый парсер получает уже скачанную страницу и отдаёт список `Program` —
одинаковый для всех сайтов, дальше с ним работают отсев (`app/live.py`) и
перевод времени (`app/daytime.py`). Логика конкретного сайта не выходит
за пределы своего модуля.

Разбор `__NUXT_DATA__` живёт в `devalue.py` — он нужен не одному sporttv.pt,
на Nuxt сделаны и другие источники из разведки.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Program:
    """Одна передача в ТВ-сетке — как она есть на сайте, без перевода."""

    channel_raw: str                 # название канала на сайте: `SPORT.TV2`
    title: str                       # заголовок блока
    start: datetime | None           # начало, всегда со смещением (aware)
    raw_time: str = ""               # время как написано на странице: `14:30`
    description: str = ""            # описание под заголовком
    league_raw: str = ""             # лига/турнир, как на сайте
    sport_raw: str = ""              # вид спорта, если сайт его называет
    live_raw: str = ""               # найденный маркер эфира: `директно`
    match_raw: str = ""              # строка, где искать пару команд
    source_url: str = ""             # адрес страницы, откуда взято
    extra: dict = field(default_factory=dict)

    def signals(self) -> str:
        """Весь текст, по которому судим об эфире и о мусоре."""
        return " ".join(x for x in (self.live_raw, self.description,
                                    self.league_raw, self.sport_raw) if x)


#: ПОМЕТКА САЙТА — эфир или повтор сказал сам сайт (поле JSON, класс,
#: значок, слово в своей графе), а не угадал разбор. Правила (06.10, port.hu:
#: `is_live_mp` лежал в данных, а разбор угадывал эфир — и потерял матч):
#:   1. Есть у сайта признак — разбор ЧИТАЕТ его через `site_says`, а не
#:      угадывает. Угадывание (`mark_first_show`) — только для строк, о которых
#:      сайт промолчал.
#:   2. `site_says` кладёт слово в `live_raw`: эфир — `SITE_LIVE_WORD`
#:      (раздел live в `data/markers.json`), повтор/запись — `SITE_REPEAT_WORD`
#:      (раздел not_live) или своё слово сайта, если оно есть в словаре.
#:   3. Вердикт сайта лежит в `extra[SITE_FLAG]`: `mark_first_show` такие
#:      строки не трогает — повтор не станет «первым показом», эфир не сотрётся.
#:   4. Строку, которой эфир достался угадыванием, `mark_first_show` метит
#:      `extra["live_guess"]` — по нему `scripts/parse_live.py` (`guessed`)
#:      сверяет её с эталоном flashscore.
SITE_FLAG = "site_flag"
SITE_LIVE = "live"
SITE_REPEAT = "repeat"
SITE_LIVE_WORD = "live"
SITE_REPEAT_WORD = "replay"


def site_says(program: "Program", live: bool | None,
              word: str = "") -> "Program":
    """Записать пометку самого сайта у передачи.

    `live`: True — сайт сказал «прямой эфир», False — «повтор/запись»,
    None — сайт промолчал (строку оставляем угадыванию). `word` — слово
    сайта, если оно есть в `data/markers.json`; иначе — общее слово."""
    if live is None:
        return program
    program.live_raw = word or (SITE_LIVE_WORD if live else SITE_REPEAT_WORD)
    program.extra[SITE_FLAG] = SITE_LIVE if live else SITE_REPEAT
    return program


def mark_first_show(programs: list["Program"], marker: str) -> list["Program"]:
    """Проставить маркер эфира первому показу каждой пары.

    Часть сайтов вообще не помечает прямые трансляции (`oneplaysport.cz`,
    `ert.gr`, `rtrs.tv`) — в сетке матч и его ночной повтор выглядят
    одинаково. Без пометки отсев выбрасывает такой источник целиком, а с
    пометкой на всех — лента наполняется повторами. Поэтому маркер получает
    самый ранний показ пары, остальные помечаются как повтор.

    Строки с пометкой сайта (`site_says`) не угадываются: сайт уже сказал.
    Если у пары есть показ, который сайт назвал эфиром, остальные её показы
    без пометки — не эфир. Повтор по слову сайта первым показом не считается.

    Порядок команд не важен: запись часто идёт перевёрнутой парой. Угаданный
    эфир метится `extra["live_guess"]`; домены, где угадано всё, перечислены
    в `scripts/parse_live.py` (`REPEAT_GUESS_DOMAINS`) — там же снимаются
    повторы между файлами.
    """
    def key(p: "Program"):
        if " - " not in p.match_raw:
            return None
        return tuple(sorted(" ".join(s.lower().split())
                            for s in p.match_raw.split(" - ", 1)))

    said_live = {key(p) for p in programs
                 if p.extra.get(SITE_FLAG) == SITE_LIVE} - {None}
    first: dict[tuple, object] = {}
    for p in programs:
        pair = key(p)
        if p.extra.get(SITE_FLAG) or pair is None or p.start is None:
            continue
        if pair not in first or p.start < first[pair]:
            first[pair] = p.start
    for p in programs:
        pair = key(p)
        if pair is None or p.extra.get(SITE_FLAG):
            continue
        if pair in said_live or (p.start is not None
                                 and p.start > first[pair]):
            p.live_raw = ""
            p.extra["repeat_guess"] = True
        else:
            p.live_raw = p.live_raw or marker
            p.extra["live_guess"] = True
    return programs


#: домен → функция `parse(html, *, day, tz, url) -> list[Program]`
REGISTRY: dict[str, object] = {}

#: Сколько передач на странице считаем убедительной сеткой. Меньше — скорее
#: случайное совпадение разметки, чем настоящее расписание.
FIT_MIN_ROWS = 5


def score(programs: list["Program"]) -> dict:
    """Насколько похоже на настоящую телесетку. Для подбора разбора чужим
    парсером: совпасть разметкой может кто угодно, а сетка — это много строк,
    у каждой время и название, и каналы не выдуманы.

    Возвращает разбор по признакам и общий балл 0…100. Балл — подсказка
    владельцу, а не приговор: решение он принимает, глядя на примеры строк.
    """
    rows = len(programs)
    if not rows:
        return {"rows": 0, "timed": 0, "titled": 0, "pairs": 0,
                "channels": 0, "score": 0}
    timed = sum(1 for p in programs if p.start is not None)
    titled = sum(1 for p in programs if (p.title or "").strip())
    pairs = sum(1 for p in programs if " - " in (p.match_raw or ""))
    channels = len({(p.channel_raw or "").strip()
                    for p in programs if (p.channel_raw or "").strip()})
    # время и название — обязательная часть сетки, пары спорта — приятный
    # бонус: на канале общего вещания матчей может не быть вовсе
    balls = (50 * timed / rows) + (30 * titled / rows) + min(10, pairs) \
        + (10 if channels else 0)
    if rows < FIT_MIN_ROWS:
        balls /= 2            # две-три строки убедительными не считаем
    return {"rows": rows, "timed": timed, "titled": titled, "pairs": pairs,
            "channels": channels, "score": round(min(100, balls))}


def try_all(html: str, *, day=None, tz: str | None = None, url: str = "",
            skip: set[str] | None = None) -> list[tuple[str, dict, list]]:
    """Прогнать страницу через ВСЕ готовые разборы и разложить по убыванию
    похожести на сетку. Возвращает список `(домен-донор, оценка, передачи)`.

    Упавший разбор молча пропускаем: чужая страница ему и не предназначалась,
    исключение здесь — обычное дело, а не поломка.
    """
    out = []
    for donor, parse in all_parsers().items():
        if skip and donor in skip:
            continue
        try:
            programs = parse(html, day=day, tz=tz, url=url)
        except TypeError:
            try:
                programs = parse(html)
            except Exception:                            # noqa: BLE001
                continue
        except Exception:                                # noqa: BLE001
            continue
        if not programs:
            continue
        out.append((donor, score(programs), programs))
    out.sort(key=lambda row: (row[1]["score"], row[1]["rows"]), reverse=True)
    return out


def register(domain: str):
    def deco(fn):
        REGISTRY[domain] = fn
        return fn
    return deco


def get(domain: str, borrowed: str = ""):
    """Парсер по домену. Нет своего — берём одолженный (`borrowed`): его
    подбирает `scripts/autoparse.py` и записывает в карточку источника,
    чтобы новый сайт поехал на чужом готовом разборе без нового модуля
    (просьба владельца 22.09: «пусть существующие скрипты пробуют по
    порядку, сработал — тем и работаем»). Нет и его — None."""
    _load_all()
    own = (REGISTRY.get(domain)
           or REGISTRY.get((domain or "").removeprefix("www.")))
    if own or not borrowed:
        return own
    return (REGISTRY.get(borrowed)
            or REGISTRY.get(borrowed.removeprefix("www.")))


def all_parsers() -> dict[str, object]:
    """Весь реестр «домен → разбор» — для перебора при подборе."""
    _load_all()
    return dict(REGISTRY)


def _load_all():
    """Ленивый импорт всех модулей: они наполняют REGISTRY через `register`."""
    from . import (aktuality_sk, allente_no, aspor_com_tr,  # noqa: F401
                   atv_com_tr,
                   bbc_co_uk, beinsports_com_tr, bnt_bg,
                   canal11_pt, ceskatelevize_cz, cosmotetv_gr, cyta_com_cy,
                   diemaxtra_bg, digisport_ro, dr_dk, err_ee, ert_gr,
                   flashscore_mobi,
                   football_tv_ru,
                   hrt_hr, ipko_tv, kanal1sport_sk, kolla_tv,
                   maxsport_live,
                   liveonsat_com, livesoccertv_com, mediaklikk_hu, mojtv_hr,
                   movistarplus_es, news_by, nova_bg, novasports_gr,
                   npo_nl, ntvplus_tv,
                   oneplay_cz, oneplaysport_cz, onesoccer_ca, orf_at,
                   primaplay_ro,
                   poverkhnost_tv,
                   polsatsport_pl, port_hu, programetv_ro, programme_tv_net,
                   raiplay_it, rtcg_me, rte_ie, rts_rs, rtl_de, rtp_pt, rtrs_tv,
                   skai_gr, skysports_com,
                   sport1_de, sport1_maariv, sport1tv_cz, sport5_co_il,
                   sportdigital_de,
                   sporteventz_com, sportklub_hr,
                   sports_kz, sporttv_pt,
                   srf_ch, ssport_tv,
                   teleman_pl,
                   trt_net_tr, trtavaz_com_tr, trtspor_com_tr,
                   tring_al, tv2_no, tv3_lt, tv8_com_tr, tv24_co_uk,
                   tv_nova_cz,
                   tvguidetonight_com_au, unian_tv,
                   vsetv_com,
                   webtv_sk, ziggosport_nl, tvarenaprogram_com,
                   tvarenasport_com, tvheute_at, tvpassport_com,
                   tvsporten_dk, tvtid_tv2_dk)

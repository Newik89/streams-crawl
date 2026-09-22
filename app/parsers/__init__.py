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


def mark_first_show(programs: list["Program"], marker: str) -> list["Program"]:
    """Проставить маркер эфира первому показу каждой пары.

    Часть сайтов вообще не помечает прямые трансляции (`oneplaysport.cz`,
    `ert.gr`, `rtrs.tv`) — в сетке матч и его ночной повтор выглядят
    одинаково. Без пометки отсев выбрасывает такой источник целиком, а с
    пометкой на всех — лента наполняется повторами. Поэтому маркер получает
    самый ранний показ пары, остальные помечаются как повтор.

    Порядок команд не важен: запись часто идёт перевёрнутой парой. Домены,
    где эфир именно угадан, перечислены в `scripts/parse_live.py`
    (`REPEAT_GUESS_DOMAINS`) — там же снимаются повторы между файлами.
    """
    def key(p: "Program"):
        if " - " not in p.match_raw:
            return None
        return tuple(sorted(" ".join(s.lower().split())
                            for s in p.match_raw.split(" - ", 1)))

    first: dict[tuple, object] = {}
    for p in programs:
        pair = key(p)
        if pair is not None and p.start is not None                 and (pair not in first or p.start < first[pair]):
            first[pair] = p.start
    for p in programs:
        pair = key(p)
        if pair is None:
            continue
        if p.start is not None and p.start > first[pair]:
            p.live_raw = ""
            p.extra["repeat_guess"] = True
        else:
            p.live_raw = p.live_raw or marker
    return programs


#: домен → функция `parse(html, *, day, tz, url) -> list[Program]`
REGISTRY: dict[str, object] = {}


def register(domain: str):
    def deco(fn):
        REGISTRY[domain] = fn
        return fn
    return deco


def get(domain: str):
    """Парсер по домену. Нет своего — None, источник пойдёт по эвристике."""
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
                   tvarenasport_com, tvheute_at, tvpassport_com)
    return REGISTRY.get(domain) or REGISTRY.get(domain.removeprefix("www."))

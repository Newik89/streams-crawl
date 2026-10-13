# -*- coding: utf-8 -*-
r"""sporting.pt — Португалия, официальный сайт «Спортинга»: где покажут игры
клуба (просьба владельца 13.10.2026: «на этом сайте есть расписание —
добавь к нам в обход»).

Страница `pt/agenda/listagem` — афиша месяца всех команд клуба (футбол,
дубль, женщины, молодёжь, баскетбол, футзал, гандбол…), строка вида
`18:30 · SPORTING CP VS Póvoa AC · Andebol - Seniores masculinos - Campeonato
Nacional, … - TRANSMISSÃO EM DIRECTO NA SPORT TV 1`. Месяц в строке не
написан, а сайт рисует её браузером. Поэтому берём календарь, который сайт
отдаёт кнопкой «Exportar» — `https://www.sporting.pt/pt/ical`: обычный
запрос, весь сезон одним файлом (500 событий, проба #253, 13.10):

    BEGIN:VEVENT
    DTSTART;TZID=Europe/London:20261013T174500
    SUMMARY:Futebol (Seniores M): RC Lens vs. SPORTING CP
    LOCATION:2.ª jornada da Fase de Liga da Liga dos Campeões da UEFA
    DESCRIPTION:… Stade Bollaert-Delelis (Lens\, França) - TRANSMISSÃO EM
     DIRECTO NA SPORT TV 5\n…
    URL;TYPE=URI:https://www.sporting.pt/pt/jogos/futebol/equipa-principal/…

Правила разбора — списком:

1. Берём только событие, где сайт САМ назвал трансляцию: «TRANSMISSÃO EM
   DIRECTO [E EM EXCLUSIVO] NA|NO|EM|PELA <канал>». Остальное — афиша клуба
   без телевидения (из 500 событий сезона таких 441).
2. Канал — слова после предлога заглавными, как написал сайт («SPORT TV 1»,
   «SPORTING TV», «FPB TV», «CANAL11.PT»); хвост « - …», «(…)» отрезается,
   «SPORT TV 1 E NA SPORTING TV» — две строки, по одной на канал. Канал не из
   списка источника НЕ выбрасывается: заливка заведёт его сама (страна PT),
   и он появится на витрине — сайт клуба называет только настоящих
   вещателей. Перевод в канал витрины — карточка источника
   (`scripts/add_sporting.py`).
3. Время — `DTSTART` с поясом. Событие без часа (`VALUE=DATE` — «время не
   назначено») пропускаем: витрине нужен час игры; когда клуб назначит
   время, событие придёт само.
4. Пара — из `SUMMARY` после двоеточия, разделитель ` vs. `. Вид спорта —
   слово до скобки (`Futebol`, `Basquetebol`, `Futsal`…) — его решают слова
   `data/markers.json`.
5. Турнир — `LOCATION` без стадии: «8.ª jornada da Liga Portugal 2» →
   «Liga Portugal 2», «2.ª jornada da 1.ª fase / Série B do Campeonato
   Nacional da 2.ª divisão Sub-17» → «Campeonato Nacional da 2.ª divisão
   Sub-17» (`competition`); стадия уходит в описание. Иначе каждый тур был
   бы новой «лигой» — правка ✎ и словарь лиг работали бы на один тур.
6. Пол и возраст — из скобки (`Seniores F`, `Sub-19 M`, `Equipa B M`):
   женская команда — словом «Feminino», возраст «Sub-19» (если турнир его не
   пишет) — в названии турнира, и `app/leagues.category` дописывает
   `W`/`U19` (суффиксы не терять).
7. Эфир — пометка самого сайта («em directo»), не угадывание.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from . import Program, register, site_says

DOMAIN = "sporting.pt"
TZ = "Europe/Lisbon"

#: правило 1: трансляция и всё, что после предлога, до конца строки
_BROADCAST = re.compile(
    r"TRANSMISS[ÃA]O\s+(?:EM\s+)?DIRE(?:C)?TO(?:\s+E\s+EM\s+EXCLUSIVO)?\s+"
    r"(?:NA|NO|EM|PELA|PELO)\s+([^\n\\;]+)", re.I)
#: правило 2: хвост после канала и разделитель нескольких каналов
_TAIL = re.compile(r"\s+-\s+.*$|\s*\(.*$|\s*,.*$")
_SEVERAL = re.compile(r"\s+E\s+(?:(?:EM|NA|NO|PELA|PELO)\s+)?|\s*/\s*", re.I)
#: правило 3: только событие с часом
_DTSTART = re.compile(r"^DTSTART;TZID=([^:\n]+):(\d{8})T(\d{4})", re.M)
#: правило 4, 6: «Futebol (Seniores F): Home vs. Away»
_SUMMARY = re.compile(r"^\s*([^():]+?)\s*\(([^)]*)\)\s*:\s*(.+?)\s+vs\.?\s+(.+?)\s*$", re.I)
_AGE = re.compile(r"\bSub[- ]?(\d{2})\b", re.I)
#: правило 5: стадия в начале LOCATION и связка за ней («da», «do», «/»)
_STAGE = re.compile(
    r"^(?:\d+\.[ªº]\s+(?:jornada|mão|fase|pré-eliminatória|eliminatória)"
    r"|fase\s+(?:regular|de\s+liga|de\s+grupos|principal|inicial|final)"
    r"|(?:grupo|zona|série)\s+\S+"
    r"|oitavos-de-final|quartos-de-final|meias-finais|final"
    r"|\d+\.[ºª]\s*/\s*\d+\.[ºª]\s+lugares)"
    r"(?:\s+(?:da|do|de|dos|das)\s+|\s*/\s*)", re.I)


def competition(location: str) -> tuple[str, str]:
    """Правило 5: (турнир, стадия) из `LOCATION`."""
    rest = (location or "").strip()
    while True:
        m = _STAGE.match(rest)
        if not m or not rest[m.end():].strip():
            break
        rest = rest[m.end():].strip()
    stage = (location or "").strip()[: len((location or "").strip()) - len(rest)]
    stage = re.sub(r"\s+(?:da|do|de|dos|das)$", "", stage.strip(" /"), flags=re.I)
    return rest, stage.strip(" /")


def channels_of(text: str) -> list[str]:
    """Правило 2: каналы фразы «… NA SPORT TV 1 E NA SPORTING TV - …»."""
    text = _TAIL.sub("", re.sub(r"\s+", " ", text or "").strip())
    out = []
    for part in _SEVERAL.split(text):
        name = part.strip(" .-").upper()
        if name and name not in out:
            out.append(name)
    return out


def _field(event: str, name: str) -> str:
    m = re.search(r"^" + name + r"(?:;[^:\n]*)?:(.*)$", event, re.M)
    return m.group(1).strip() if m else ""


def _unescape(text: str) -> str:
    """Экранирование iCal: `\\,` `\\;` `\\n`."""
    return (text.replace("\\n", "\n").replace("\\N", "\n")
            .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\"))


@register(DOMAIN)
def parse(html: str, *, day: _date | None = None, tz: str | None = None,
          url: str = "", channels: set[str] | None = None) -> list[Program]:
    # строки календаря, перенесённые с пробелом в начале, — склеить (RFC 5545)
    text = (html or "").replace("\r\n", "\n").replace("\n ", "").replace("\n\t", "")
    if "BEGIN:VEVENT" not in text:
        return []
    out: list[Program] = []
    for event in text.split("BEGIN:VEVENT")[1:]:
        event = event.split("END:VEVENT")[0]
        description = _unescape(_field(event, "DESCRIPTION"))
        found = _BROADCAST.search(description)
        if not found:
            continue                                            # правило 1
        names = channels_of(found.group(1))
        start = _DTSTART.search(event)
        if not names or not start:
            continue                                            # правила 2, 3
        try:
            zone = ZoneInfo(start.group(1).strip())
        except (KeyError, ValueError):
            zone = ZoneInfo(tz or TZ)
        moment = datetime.strptime(start.group(2) + start.group(3), "%Y%m%d%H%M"
                                   ).replace(tzinfo=zone)
        summary = _unescape(_field(event, "SUMMARY"))
        pair = _SUMMARY.match(summary)
        if not pair:
            continue                                            # правило 4
        sport, group, home, away = (x.strip() for x in pair.groups())
        league, stage = competition(_unescape(_field(event, "LOCATION")))
        tags = []                                               # правило 6
        if re.search(r"\bF\s*$", group):
            tags.append("Feminino")
        age = _AGE.search(group)
        if age and not _AGE.search(league):
            tags.append(f"Sub-{age.group(1)}")
        league = " — ".join(x for x in (league, " ".join(tags)) if x)
        for channel in names:
            program = Program(
                channel_raw=channel, title=summary, start=moment,
                raw_time=moment.strftime("%H:%M"),
                description=" · ".join(x for x in (stage, found.group(0).strip()) if x),
                league_raw=league[:160], sport_raw=sport.lower(),
                match_raw=f"{home} - {away}", source_url=url,
                extra={"day": moment.date().isoformat(),
                       "страница": _field(event, "URL"),
                       # канала нет в карточке источника — заливка заведёт его
                       "новый_канал": bool(channels) and channel not in channels})
            out.append(site_says(program, True, "directo"))      # правило 7
    return out

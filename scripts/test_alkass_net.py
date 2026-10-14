# -*- coding: utf-8 -*-
r"""Разбор телегида Al Kass (`app/parsers/alkass_net.py`, задание владельца
13.10.2026). По проверке на каждое правило модуля; строки — настоящие
названия передач со страницы сайта (проба #257, 13.10).

В сеть не ходит:
    python scripts/test_alkass_net.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import parsers  # noqa: E402
from app.parsers import alkass_net  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def канал(логотип: str, строки: list[tuple[str, str]]) -> str:
    """Один канал мобильного блока страницы — как его рисует сайт."""
    tr = "".join(
        "<tr class=''>"
        f"<td class='team-result__date tv-prog-name'>{название}</td>"
        f"<td class='team-result__status tv-prog-time'>{время}</td></tr>"
        for время, название in строки)
    return (f'<li class="has-children"><a><figure><img src="assets/images/{логотип}"'
            f' alt="" style="width:75px"></figure></a><ul class="collapse">'
            f'<li class="no-padding"><table><tbody>{tr}</tbody></table></li></ul></li>')


СТРАНИЦА = ('<html><body><div class="tvguide-full-mobile"><ul>' + "".join([
    канал("one_.png", [
        ("02:00", "Tunisia Derby Espérance Sportive × Étoile du Sahel"),
        ("06:00", "News"),
        ("06:30", "Jetour League Al-Waab vs. Qatar U-23 National Team"),
        ("17:15", "Gulf Club Champions League Qatar SC × Al-Zawraa SC"),
        ("20:45", "Gulf Clubs Champions League Neom Saudi × Shabab Hadramout Yemen"),
    ]),
    канал("two_.png", [
        ("10:00", "Tunisia Derby Espérance Sportive × Étoile du Sahel"),
        ("10:00", "Tunisia Derby Espérance Sportive × Étoile du Sahel"),
        ("16:15", "Doha Bank Stars League  Al Sailiya vs Al Ahli"),
    ]),
    канал("three_.png", [
        ("03:00", "wasl basketball Al Arabi of Qatar vs. Shahrdari of Iran"),
        ("07:15", "WASL BASKETBALL Al-Arabi (Qatar) × Al-Hikma (Lebanon)"),
    ]),
    канал("four_.png", [
        ("17:15", "Gulf Club Champions League Qatar SC × Al-Zawraa SC"),
    ]),
    канал("five_.png", [
        ("03:00", "Asian Champions League Elite   Al Wasl UAE × Al Ahli Saudi Arabia"),
        ("18:45", "AFC Champions League Elite   Al Sadd (Qatar) × Al Hilal (Saudi Arabia)"),
        ("21:15", "AFC Champions League Elite  Al-Ittihad Saudi × Shabab Al Ahli UAE"),
    ]),
    канал("six_.png", [
        ("16:30", "ACL 2   East Bengal (India) × Al-Shorta (Iraq)"),
        ("19:00", "ACL 2 Al-Seeb (Oman) × Al-Hussein (Jordan)"),
        ("22:00", "Doha Bank Stars League  Al Sailiya vs Al Ahli"),
    ]),
    канал("online.png", [("", "Schedule not available")]),
]) + "</ul></div></body></html>")

parse = parsers.get("www.alkass.net")
строки = parse(СТРАНИЦА, day=date(2026, 10, 13), url="https://www.alkass.net/tvguide")


def найти(канал_: str, время: str) -> list:
    return [p for p in строки if p.channel_raw == канал_ and p.raw_time == время]


print("правило 1: канал — по логотипу, «Schedule not available» — не передача")
проверка("каналы по логотипам", sorted({p.channel_raw for p in строки}),
         ["Al Kass Five", "Al Kass Four", "Al Kass One", "Al Kass Six",
          "Al Kass Three", "Al Kass Two"])
проверка("one_.png → Al Kass One", alkass_net.channel_name("assets/images/one_.png"),
         "Al Kass One")
проверка("незнакомый логотип не теряется: nine.png → Al Kass Nine",
         alkass_net.channel_name("assets/images/nine.png"), "Al Kass Nine")
проверка("фильтр каналов карточки", sorted({p.channel_raw for p in parse(
    СТРАНИЦА, day=date(2026, 10, 13), channels={"Al Kass Five"})}), ["Al Kass Five"])

print("правило 2: день от обхода, время Дохи (UTC+3)")
сад = найти("Al Kass Five", "18:45")[0]
проверка("18:45 Дохи = 15:45 UTC", сад.start.strftime("%Y-%m-%d %H:%M %z"),
         "2026-10-13 18:45 +0300")

print("правило 3: одинаковые строки сайта — одна")
проверка("дубль Tunisia Derby в 10:00 на Two", len(найти("Al Kass Two", "10:00")), 1)

print("правило 4: пара по vs / vs. / ×; без разделителя — передача")
проверка("News — без пары", найти("Al Kass One", "06:00")[0].match_raw, " ")
for фраза, ждём in (
        ("Golmania", ("", " ")),
        ("Jetour League Al Khor vs Umm Salal", ("Jetour League", "Al Khor - Umm Salal")),
        ("Doha Bank Stars League Al-Shahania vs. Lusail",
         ("Doha Bank Stars League", "Al-Shahania - Lusail")),
        ("Al Sadd x Al Rayyan", ("", "Al Sadd - Al Rayyan"))):
    проверка(f"«{фраза}»", alkass_net.split_title(фраза), ждём)

print("правило 5: граница лиги и хозяев")
for фраза, ждём in (
        ("Asian Champions League Elite   Al Wasl UAE × Al Ahli Saudi Arabia",
         ("Asian Champions League Elite", "Al Wasl - Al Ahli")),
        ("ACL 2 Al-Seeb (Oman) × Al-Hussein (Jordan)", ("ACL 2", "Al-Seeb - Al-Hussein")),
        ("Tunisia Derby Espérance Sportive × Étoile du Sahel",
         ("Tunisia Derby", "Espérance Sportive - Étoile du Sahel")),
        ("WASL BASKETBALL Al-Arabi (Qatar) × Al-Hikma (Lebanon)",
         ("WASL BASKETBALL", "Al-Arabi - Al-Hikma"))):
    проверка(f"«{фраза}»", alkass_net.split_title(фраза), ждём)

print("правило 6: приписка страны у клуба снимается, страна-сборная — нет")
for сторона, ждём in (
        ("Al Sadd (Qatar)", "Al Sadd"), ("Al Arabi of Qatar", "Al Arabi"),
        ("Shabab Al Ahli UAE", "Shabab Al Ahli"), ("Al Ahli Saudi Arabia", "Al Ahli"),
        ("Shabab Hadramout Yemen", "Shabab Hadramout"), ("Al Ain (UAE)", "Al Ain"),
        ("Qatar", "Qatar"), ("Saudi Arabia", "Saudi Arabia"),
        ("Nacional (Uru)", "Nacional"), ("Al Ahli (Jeddah)", "Al Ahli (Jeddah)")):
    проверка(f"«{сторона}» → «{ждём}»", alkass_net._side(сторона), ждём)

print("правило 7: сборная и возраст")
проверка("«Qatar U-23 National Team» → «Qatar U23»",
         alkass_net._side("Qatar U-23 National Team"), "Qatar U23")
проверка("женская команда сохраняет пометку",
         alkass_net._side("Al Shamal Women"), "Al Shamal Women")

print("правило 8: эфир — первый показ пары, позже — повтор")
проверка("Al Sailiya — Al Ahli 16:15 — первый показ (эфир угадан)",
         (найти("Al Kass Two", "16:15")[0].live_raw,
          найти("Al Kass Two", "16:15")[0].extra.get("live_guess")), ("live", True))
проверка("Al Sailiya — Al Ahli 22:00 — повтор",
         (найти("Al Kass Six", "22:00")[0].live_raw,
          найти("Al Kass Six", "22:00")[0].extra.get("repeat_guess")), ("", True))
проверка("одновременный показ на двух каналах — оба эфир",
         [p.live_raw for p in строки if "Qatar SC" in p.match_raw], ["live", "live"])

print(f"\nитог: {зелёных} зелёных, {красных} красных")
sys.exit(1 if красных else 0)

"""Книга 130 (15.11): церемонии открытия, закрытия и награждения — не матч.

Аудит 12.11: в списке игр стояла «Záróünnepség - Dakar» (церемония закрытия,
M4 Sport): пометка эфира честная, тире в названии — «пара». Слово владельца
15.11: «в церемониях есть ключевые слова, которые можно перевести на разные
языки». Слова — в `data/markers.json`, раздел `stop_title`.

Запуск: python scripts/test_tseremonii.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import live  # noqa: E402
from app.parsers import Program  # noqa: E402

зелёных = красных = 0
MARKERS = live.load()


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def берём(title: str) -> bool:
    """Берёт ли отсев строку с честной пометкой эфира и «парой» в названии."""
    p = Program(channel_raw="K", title=title, start=datetime(2026, 11, 15, 19, 0, tzinfo=timezone.utc),
                live_raw="live", match_raw=title if " - " in title else " ")
    return live.check(p, MARKERS).ok


print("Церемония — не матч, на языках наших сайтов")
for title in ("Záróünnepség - Dakar", "Opening Ceremony - Olympic Stadium", "Церемония закрытия - Дакар",
              "Церемонія нагородження - Київ", "Siegerehrung - Kitzbühel", "Cérémonie d'ouverture - Paris",
              "Ceremonia de apertura - Madrid", "Cerimónia de abertura - Lisboa", "Svečano otvaranje - Zagreb",
              "Свечано отварање - Београд", "Τελετή έναρξης - Αθήνα", "Açılış töreni - İstanbul",
              "Slavnostní zahájení - Praha", "Prisutdeling - Oslo", "Medal Ceremony - Men's 100m",
              "טקס הפתיחה - תל אביב", "Premiazione - Giro d'Italia"):
    проверка(f"«{title}»", берём(title), False)

print("Группа покрывает ВСЕ языки наших сайтов (слово владельца 15.11: «учитывай всегда все сайты и все языки»)")
from app import site_lang  # noqa: E402

#: по одной церемонии на КАЖДЫЙ язык из `site_lang.SITE_LANGS` и на английский.
#: Появился сайт на новом языке — тест краснеет, пока сюда и в markers.json
#: не добавлены слова этого языка
ПО_ЯЗЫКАМ = {
    "en": "Closing Ceremony - Dakar", "de": "Eröffnungsfeier - Berlin", "fr": "Cérémonie de clôture - Paris",
    "es": "Ceremonia de clausura - Madrid", "pt": "Cerimónia de encerramento - Lisboa",
    "it": "Cerimonia di chiusura - Roma", "pl": "Ceremonia otwarcia - Warszawa",
    "cs": "Slavnostní zakončení - Praha", "sk": "Slávnostné otvorenie - Bratislava",
    "hu": "Záróünnepség - Dakar", "hr": "Svečano zatvaranje - Zagreb", "sr": "Свечано затварање - Београд",
    "bs": "Svečano otvaranje - Sarajevo", "sl": "Otvoritvena slovesnost - Ljubljana",
    "bg": "Церемония по откриване - София", "ru": "Церемония открытия - Москва",
    "uk": "Церемонія закриття - Київ", "be": "Цырымонія адкрыцця - Мінск",
    "kk": "Ашылу салтанаты - Астана", "el": "Τελετή λήξης - Αθήνα", "tr": "Kapanış töreni - Ankara",
    "ro": "Ceremonia de deschidere - București", "sq": "Ceremonia e hapjes - Tiranë",
    "nl": "Openingsceremonie - Amsterdam", "da": "Åbningsceremoni - København",
    "no": "Åpningsseremoni - Oslo", "sv": "Invigningsceremoni - Stockholm", "fi": "Avajaisseremonia - Helsinki",
    "lt": "Atidarymo ceremonija - Vilnius", "et": "Avamise tseremoonia - Tallinn",
    "he": "טקס הסיום - ירושלים", "ar": "حفل الافتتاح - الدوحة",
}
языки_сайтов = {lang for langs in site_lang.SITE_LANGS.values() for lang in langs} | {"en"}
проверка("у каждого языка наших сайтов есть пример церемонии в этом тесте",
         sorted(языки_сайтов - set(ПО_ЯЗЫКАМ)), [])
for lang in sorted(ПО_ЯЗЫКАМ):
    проверка(f"{lang}: «{ПО_ЯЗЫКАМ[lang]}»", берём(ПО_ЯЗЫКАМ[lang]), False)

print("Настоящие матчи не задеты")
for title in ("Spain - England", "Finland - San Marino", "Dakar - Casablanca", "Paris FC - Olympique Lyon",
              "Fenerbahçe - Galatasaray", "Ceres - Monaco", "Praha - Brno", "Zeljeznicar - Sarajevo",
              "Slovan Bratislava - Spartak Trnava", "Honvéd - Ferencváros"):
    проверка(f"«{title}»", берём(title), True)

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)

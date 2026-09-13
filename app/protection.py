# -*- coding: utf-8 -*-
"""Опознание страницы-заглушки, которую подсовывает защита от роботов.

Зачем отдельно: список слов был только на английском, и болгарская заглушка
Cloudflare на `btv.bg` («Един момент… уебсайтът проверява дали сте бот») не
опозналась. Сайт получал вердикт «расписание не найдено» вместо «не пускают» —
то есть выглядел как проблема с адресом, хотя проблема была в защите.

Слова взяты на языках наших источников. Плюс инфраструктурные следы: они
надёжнее текста, потому что не переводятся.
"""

from __future__ import annotations

# Следы самой защиты в разметке — переводу не подлежат, поэтому первыми.
INFRA_MARKERS = (
    "challenges.cloudflare.com", "cdn-cgi/challenge-platform", "turnstile",
    "incapsula", "imperva", "_incap_", "datadome", "ak_bmsc",
)

# Текст заглушки на языках источников.
TEXT_MARKERS = (
    # английский
    "just a moment", "access denied", "incident id", "attention required",
    "verify you are human", "checking your browser", "request unsuccessful",
    "ddos protection", "performing security verification", "privacy gate",
    # болгарский, русский, украинский
    "един момент", "проверка за сигурност", "дали сте бот",
    "проверяем ваш браузер", "подождите", "перевірка браузера",
    # турецкий
    "bir dakika", "güvenlik kontrolü", "robot olmadığınızı",
    # немецкий
    "einen moment", "sicherheitsüberprüfung", "zugriff verweigert",
    # французский
    "un instant", "vérification de sécurité", "accès refusé",
    # итальянский, испанский, португальский
    "un attimo", "verifica di sicurezza", "acceso denegado",
    "verificación de seguridad", "acesso negado",
    # чешский, словацкий, польский
    "strpení prosím", "ověřujeme váš prohlížeč", "chwileczkę",
    "weryfikacja przeglądarki",
    # греческий, румынский, сербохорватский
    "μια στιγμή", "έλεγχος ασφαλείας", "verificare de securitate",
    "sigurnosna provjera",
)

# Сколько меток времени на странице означает, что это точно расписание.
# Страница защиты не показывает программу — у неё меток нет вовсе.
NOT_A_STUB_MARKS = 10

# «Ray ID» печатает Cloudflare на странице отказа на любом языке.
RAY_ID = "ray id"


def is_blocked(text: str, html: str = "") -> bool:
    """Это страница защиты, а не расписание?

    `text` — видимый текст, `html` — исходник целиком (в нём видны следы
    инфраструктуры, которых в тексте нет).

    **Расписание с готовой программой защитой быть не может.** Обожглись
    29.08.2026: чешский список каналов `tvprogram.cz` с 803 метками времени
    попал в «заглушки» из-за слова `okamžik` — по-чешски это просто
    «момент», оно встречается в обычном тексте. Поэтому сначала смотрим,
    есть ли на странице программа, и только потом ищем слова защиты.
    Слишком общие слова заодно заменены на целые фразы.
    """
    from . import timemarks
    if timemarks.count(text) >= NOT_A_STUB_MARKS:
        return False
    low = text.lower()
    if any(m in low for m in TEXT_MARKERS) or RAY_ID in low:
        return True
    return any(m in (html or "").lower() for m in INFRA_MARKERS)


def guess_name(html: str) -> str:
    """Как называется защита — для колонки protection. Пусто, если не понять."""
    low = (html or "").lower()
    for mark, name in (("challenges.cloudflare.com", "cloudflare turnstile"),
                       ("cdn-cgi/challenge-platform", "cloudflare"),
                       ("datadome", "datadome"),
                       ("incapsula", "imperva"),
                       ("imperva", "imperva"),
                       ("ak_bmsc", "akamai")):
        if mark in low:
            return name
    return ""

# -*- coding: utf-8 -*-
"""Пробный запуск браузера перед обходом (crawl.yml, шаг «Поставить, что
нужно», правило Б3; книга 100).

Код возврата 0 — Chromium запускается, 1 — нет (не скачан, нет системных
библиотек). Шаг обхода от этого не краснеет: он только пишет предупреждение,
и обход идёт без браузера. В сеть не ходит: открывает пустую страницу.

    python scripts/browser_check.py
"""
from __future__ import annotations

import sys


def launches() -> tuple[bool, str]:
    """(запустился ли, почему нет)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return False, f"playwright не установлен: {exc}"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto("about:blank")
            browser.close()
    except Exception as exc:                       # любая причина — «не запустился»
        return False, str(exc).strip().splitlines()[0][:300] if str(exc).strip() else repr(exc)
    return True, ""


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ok, why = launches()
    print("браузер запускается" if ok else f"браузер НЕ запускается: {why}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

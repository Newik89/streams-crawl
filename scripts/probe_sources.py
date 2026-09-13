"""
Быстрая техническая проверка сайтов из recon/sources.csv.

По одному GET-запросу на домен (кроме "чужих" 10 доменов). Сохраняет тело
страницы (обрезанное до 500 КБ) в recon/raw_quick/<домен>.html и код ответа
(или тип ошибки) в recon/raw_quick/<домен>.status.

Повторный запуск пропускает домены, для которых raw_quick/<домен>.html уже
существует — чтобы не долбить сайты при перезапуске.

Стандартная библиотека, без внешних пакетов.
"""

import csv
import socket
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_CSV = ROOT / "recon" / "sources.csv"
RAW_DIR = ROOT / "recon" / "raw_quick"

# Домены, которыми занимается другой агент — не трогаем.
SKIP_DOMAINS = {
    "nova.bg",
    "tv.nova.cz",
    "teleman.pl",
    "sporttv.pt",
    "polsatsport.pl",
    "digisport.ro",
    "tvarenasport.hr",
    "beinsports.com.tr",
    "cosmotetv.gr",
    "livesoccertv.com",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
ACCEPT_LANGUAGE = "en-US,en;q=0.9"
TIMEOUT = 25
PAUSE = 1.5
MAX_BYTES = 500 * 1024


def safe_filename(domain: str) -> str:
    # Домены в sources.csv уже без спецсимволов, но на всякий случай.
    return domain.replace("/", "_")


def fetch(url: str):
    """Возвращает (status, body_bytes, error_text)."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": ACCEPT_LANGUAGE,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            status = resp.status
            body = resp.read(MAX_BYTES + 1)
            return status, body[:MAX_BYTES], None
    except urllib.error.HTTPError as e:
        # HTTPError тоже содержит тело страницы (например, у 403/404 бывает
        # осмысленный контент — cloudflare challenge и т.п.)
        try:
            body = e.read(MAX_BYTES + 1)
        except Exception:
            body = b""
        return e.code, body[:MAX_BYTES], None
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if isinstance(e.reason, ssl.SSLError) or "SSL" in reason:
            return None, b"", "ssl"
        if isinstance(e.reason, socket.gaierror) or "not known" in reason or "getaddrinfo" in reason:
            return None, b"", "dns"
        if isinstance(e.reason, socket.timeout) or "timed out" in reason:
            return None, b"", "timeout"
        return None, b"", f"error: {reason}"
    except socket.timeout:
        return None, b"", "timeout"
    except TimeoutError:
        return None, b"", "timeout"
    except ssl.SSLError:
        return None, b"", "ssl"
    except socket.gaierror:
        return None, b"", "dns"
    except Exception as e:  # noqa: BLE001 - не падать ни при каких условиях
        return None, b"", f"error: {e}"


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    with open(SOURCES_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)

    todo = []
    for row in rows:
        domain = (row.get("domain") or "").strip()
        if not domain or domain in SKIP_DOMAINS:
            continue
        url = (row.get("url_primary") or "").strip()
        if not url:
            continue
        html_path = RAW_DIR / f"{safe_filename(domain)}.html"
        if html_path.exists():
            continue
        todo.append((domain, url))

    print(f"Всего доменов в CSV: {len(rows)}. Пропущено (чужие/пусто/уже есть): {len(rows) - len(todo)}.")
    print(f"К обработке сейчас: {len(todo)}.")

    for i, (domain, url) in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {domain} -> {url}")
        status, body, err = fetch(url)

        html_path = RAW_DIR / f"{safe_filename(domain)}.html"
        status_path = RAW_DIR / f"{safe_filename(domain)}.status.txt"

        if err:
            status_text = err
            html_path.write_bytes(b"")
            print(f"    ошибка: {err}")
        else:
            status_text = str(status)
            html_path.write_bytes(body)
            print(f"    статус: {status}, размер тела: {len(body)} байт")

        status_path.write_text(f"{status_text}\n{url}\n", encoding="utf-8")

        if i < len(todo):
            time.sleep(PAUSE)

    print("Готово.")


if __name__ == "__main__":
    main()

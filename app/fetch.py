# -*- coding: utf-8 -*-
"""Загрузка страниц расписания (ТЗ разд. 5, шаг 2).

Главное правило проекта — **беречь запросы**. Скачанные страницы лежат в
`recon/raw_deep/`, `recon/raw_browser/`, `recon/raw_quick/`, и гипотезы
проверяются на них; лишний обход — риск бана по IP (`HANDOFF.md` → «Грабли»).
Поэтому здесь по умолчанию включён **режим по копиям**: если страница уже
есть на диске или в таблице `raw_rows`, наружу мы не идём.

Что делает загрузчик, когда всё же идёт на сайт:

* держит паузу между запросами к одному домену (`DELAY`);
* меняет User-Agent (`AGENTS`) — по одному на домен за прогон, а не на каждый
  запрос: постоянная смена как раз и выглядит роботом;
* складывает ответ в `raw_rows`, чтобы переразбор не требовал нового обхода.

`Playwright` тут не нужен: разведка показала, что все четыре пилота
отдают расписание обычным запросом (`recon/deep_report.md`).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "pages"

DELAY = 2.0        # секунды между запросами к одному домену

#: сайты, которым нужна пауза длиннее общей: они режут частые заходы и
#: вместо расписания отдают заглушку. `poverkhnost.tv` 10.09 отдал её на
#: четырёх страницах из пяти подряд (по 4710 байт), а пятая пришла целой
DOMAIN_DELAY: dict[str, float] = {"poverkhnost.tv": 10.0}

#: Сайты, чьё расписание закрыто окном «согласитесь с куками»: пока кнопку
#: не нажать, сервер отдаёт пустой каркас (7,8 КБ у `vtm.be`, 0 меток
#: времени). Нажимать согласие от имени владельца разрешено им лично
#: 10.09 — по этому списку и только браузером.
CONSENT_SITES = {"vtm.be"}

#: Слова на кнопке согласия — у каждой площадки свои. Ищем кнопку по роли
#: и тексту: вёрстка у таких окон меняется, а надпись остаётся
#: Точная кнопка, если известна: у DPG Media она лежит в открытом shadow
#: root, и Playwright её видит по id (перебор надписей тоже работает)
CONSENT_IDS = ("#pg-accept-btn",)

CONSENT_WORDS = (
    "Alles accepteren", "Accepteer alles", "Ik ga akkoord", "Akkoord",
    "Accepteren", "Accept all", "Accept", "I agree", "Zustimmen",
)
TIMEOUT = 30

AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:129.0) Gecko/20100101 Firefox/129.0",
]


def headers(agent: str) -> dict[str, str]:
    """Полный набор заголовков обычного браузера.

    Одного User-Agent мало: 29.08.2026 обход из GitHub получил от
    `tv.nova.cz` ответ 403, хотя тот же адрес из дома открывался. Защита
    смотрит не только на подпись браузера, но и на то, идут ли рядом
    привычные заголовки — язык, тип содержимого, `Sec-Fetch-*`. Без них
    запрос из дата-центра выглядит совсем не как человек за компьютером.
    Ничего лишнего мы этим не говорим: то же самое шлёт любой Chrome.
    """
    return {
        "User-Agent": agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9,cs;q=0.8,bg;q=0.8,pl;q=0.8,pt;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
    }


@dataclass
class Page:
    url: str
    html: str
    from_cache: bool
    error: str = ""
    body: str = ""          # тело неудачного ответа — для разбора причины
    via: str = "requests"   # чем взяли: requests или browser

    @property
    def ok(self) -> bool:
        return bool(self.html) and not self.error


#: домены, у которых сертификат сломан или просрочен: проверку снимаем
#: точечно, списком, а не для всего обхода
BROKEN_TLS = {"dagenstv.com", "arenatv.sk"}

#: Одноразовый ключ, который сайт кладёт в свою страницу и требует в адресе
#: данных. В адресе (или POST-поле) пишется метка `{WARMKEY}`, обязательно
#: вместе с `warmup` на страницу, где ключ лежит; регулярка — здесь, группа 1.
#: Так устроен `sporteventz.com`: `accesskey` меняется от сессии к сессии
#: (ключ из копии за 01.09 к 02.09 уже протух — проверено пробой).
WARMKEY_PATTERNS = {
    "sporteventz.com": r"accesskey=(\d+)",
}

#: Ручки, которые пускают только с гостевым ключом. Сайт выдаёт его своему же
#: виджету по «логину гостя», зашитому в скрипт виджета: `sportklub.hr`
#: (United Cloud) — `POST /oauth/token?grant_type=client_credentials` с этим
#: логином, дальше `Bearer`-ключ и заголовок `X-UCP-TIME-FORMAT: timestamp`,
#: без которого ручка расписания отвечает 400 (разбор 16.09). Логин в
#: публичный репозиторий не кладём — достаём из скрипта при каждом обходе,
#: ключ живёт одну сессию обхода.
TOKEN_HOSTS = {
    "api-web.ug-be.cdn.united.cloud": {
        "script": "https://web-apps.ug.cdn.united.cloud/epg/bundle.js",
        "login": r"(Basic [A-Za-z0-9+/=]{20,})",
        "token": "https://api-web.ug-be.cdn.united.cloud/oauth/token"
                 "?grant_type=client_credentials",
        "headers": {"X-UCP-TIME-FORMAT": "timestamp",
                    "Accept": "application/json, text/plain, */*",
                    "Origin": "https://sportklub.hr",
                    "Referer": "https://sportklub.hr/tv-program/"},
    },
}

#: Сайты, закрытые для дата-центров. `cosmotetv.gr` у владельца в браузере
#: открывается и показывает всё расписание, а любому серверу — и раннеру
#: GitHub, и нашему DigitalOcean — отвечает заглушкой Imperva. Капчу мы не
#: обходим (решение владельца) и своего IP не подделываем: страницу берёт
#: открытая читалка `r.jina.ai`, публичный сервис, который отдаёт разметку
#: чужой страницы. Заголовок `x-respond-with: html` нужен обязательно —
#: без него возвращается короткий пересказ вместо самой страницы.
VIA_READER = {"cosmotetv.gr",
              # новый домен Cosmote после переименования в Magenta (07.09):
              # напрямую дата-центрам — Imperva; в плане его нет, запись
              # нужна пробам --urls на случай смерти старого домена
              "magentatv.gr",
              # чешская Nova: 403 и запросу, и браузеру, с любого сервера —
              # а у владельца в браузере открывается (ссылка от 01.09)
              "tv.nova.cz",
              # балканский агрегатор: 403 всем дата-центрам, даже настоящему
              # браузеру с раннера (проверено 02.09); ценен албанским
              # разделом — телегидом каналов SuperSport (Digitalb)
              "tvprofil.com",
              # румынский Pro TV: сетка лежит прямо в HTML (SSR, проверено
              # браузером владельца 02.09), сайт закрыт для дата-центров
              "protv.ro",
              # бельгийский VTM: то же самое — SSR-сетка, 403 серверам
              "vtm.be"}

#: `mojtv.hr` сюда НЕ входит, хотя с 09.09 отвечает GitHub «Sorry, you have
#: been blocked» (Cloudflare, бан адреса — не капча): читалки его тоже не
#: берут, все 17 отказали в прогоне #280 (r.jina.ai — 403, остальные лежат
#: или требуют ключ). Зато наш сервер DigitalOcean сайт пускает: 200 и
#: 143 КБ страницы, проверено 10.09. Поэтому его качает сервер, а не GitHub.

#: Читалки, через которые пробуем достать такую страницу — по очереди,
#: сверху вниз, пока какая-нибудь не отдаст содержательный ответ. Проверено
#: 01.09.2026 на `cosmotetv.gr`: пробивает защиту только `r.jina.ai` (она
#: рендерит страницу настоящим браузером), остальные передают наш запрос со
#: своего же сервера, и Imperva режет их так же. Они оставлены запасом — не
#: ради обхода защиты, а на случай, если первая перестанет работать.
#: `{url}` — адрес как есть, `{enc}` — он же, закодированный для параметра.
READERS = [
    ("https://r.jina.ai/{url}", {"x-respond-with": "html"}),
    ("https://r.jina.ai/{url}", {}),
    ("https://api.allorigins.win/raw?url={enc}", {}),
    ("https://api.codetabs.com/v1/proxy?quest={enc}", {}),
    ("https://corsproxy.io/?{enc}", {}),
    ("https://api.cors.lol/?url={enc}", {}),
    ("https://proxy.corsfix.com/?{enc}", {}),
    ("https://thingproxy.freeboard.io/fetch/{url}", {}),
    ("https://whateverorigin.org/get?url={enc}", {}),
    ("https://api.scrape.do/?url={enc}", {}),
    # добавлены 09.09, когда прежние десять разом перестали отвечать
    # (jina просит ключ, allorigins и codetabs лежат): проверяются тем же
    # `scripts/check_readers.py`, в обход попадут только живые
    ("https://api.allorigins.win/raw?url={enc}&charset=UTF-8", {}),
    ("https://api.codetabs.com/v1/proxy/?quest={enc}", {}),
    ("https://corsproxy.io/?url={enc}", {}),
    ("https://cors.eu.org/{url}", {}),
    ("https://test.cors.workers.dev/?{url}", {}),
    ("https://yacdn.org/proxy/{url}", {}),
    ("https://www.whateverorigin.org/get?url={enc}", {}),
    # найдены пробами 10.09, когда все прежние отказали:
    # cors-get-proxy берёт mojtv.hr (137 КБ), microlink — cosmotetv.gr
    # (328 КБ, но всего 25 запросов в сутки на адрес и ответ в JSON),
    # переводчик Google отдаёт mojtv.hr целиком (202 КБ, 183 метки)
    ("https://cors-get-proxy.sirjosh.workers.dev/?url={enc}", {}),
    ("https://api.microlink.io/?url={enc}&meta=false&palette=false"
     "&data.html.selector=html&data.html.type=html", {}),
    ("{translate}", {}),
]

#: Читалки, которые отдают не саму страницу, а JSON с ней внутри: ключ —
#: путь к полю с разметкой
READER_JSON = {"api.microlink.io": ("data", "html")}

#: короче этого ответ читалки считаем пустым: столько весит её отписка
#: об ошибке и заглушка защиты
READER_MIN_BYTES = 20000

#: Список выше — все, кого знаем. А кто из них ЖИВ сейчас, выясняет
#: `scripts/check_readers.py` и кладёт в этот файл: обход берёт порядок
#: оттуда, от самой быстрой к медленной. Файла нет или он пуст — идём по
#: списку сверху вниз, как записано в коде.
READERS_FILE = Path(__file__).resolve().parent.parent / "data" / "readers.json"


def readers() -> list[tuple[str, dict]]:
    """Читалки в порядке проверки: сперва те, что работали в последний раз."""
    try:
        saved = json.loads(READERS_FILE.read_text(encoding="utf-8"))
        good = [(r["шаблон"], r.get("заголовки") or {})
                for r in saved.get("рабочие") or []]
    except Exception:                       # файла нет, битый, старый формат
        good = []
    tail = [r for r in READERS if r not in good]
    return good + tail


def cache_name(url: str, post: dict | None = None) -> Path:
    """Имя файла копии: домен + путь, без символов, запрещённых в Windows.

    У POST-источников адрес один на все дни, а разное — только тело запроса
    (`tvr.ro`: `/program.html` + `day=2026-09-02`). Поэтому к имени
    добавляется короткая подпись тела, иначе второй день перезапишет первый.
    """
    parts = urlsplit(url)
    tail = (parts.path + ("?" + parts.query if parts.query else "")).strip("/")
    safe = "".join(c if c.isalnum() or c in "-_.=" else "_" for c in tail)[:120]
    mark = ""
    if post:
        line = "&".join(f"{k}={v}" for k, v in sorted(post.items()))
        mark = "__post-" + hashlib.sha1(line.encode("utf-8")).hexdigest()[:8]
    return CACHE / f"{parts.netloc}__{safe or 'index'}{mark}.html"


def protection_text(html: str) -> bool:
    """Читалка сходила, но принесла чужую заглушку, а не расписание."""
    head = html[:4000].lower()
    return any(word in head for word in
               ("incapsula", "imperva", "just a moment", "attention required",
                "access denied", "captcha"))


def browser_get(url: str, agent: str, locale: str = "en-GB") -> Page:
    """Та же страница, но настоящим Chromium (Playwright).

    Нужен там, где обычный запрос получает отказ, а браузер проходит: часть
    защит смотрит не на заголовки, а на то, как устроено само соединение, и
    подделать это заголовками нельзя. Мы ничего и не подделываем — открываем
    страницу настоящим браузером, как открыл бы её человек.

    Дороже обычного запроса: браузер стартует несколько секунд. Поэтому
    только как запасной путь, когда `requests` уже получил отказ.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return Page(url, "", False, "playwright не установлен")

    def _accept_consent(page) -> bool:
        """Пройти окно «согласитесь с куками» и дождаться расписания.

        У DPG Media (`vtm.be`) это отдельная страница-калитка: она грузит
        свой `consent.js`, рисует окно и после согласия уводит обратно через
        `/privacygate-confirm`. Окно появляется не сразу и живёт в своём
        компоненте, поэтому ищем кнопку по РОЛИ и тексту, а не по вёрстке,
        и ждём её до 25 секунд. Жмём только на сайтах из `CONSENT_SITES` —
        разрешение владельца 10.09.
        """
        import re as _re
        конец_ожидания = time.monotonic() + 25
        while time.monotonic() < конец_ожидания:
            for где in [page] + list(page.frames):
                for точный in CONSENT_IDS:
                    try:
                        узел = где.locator(точный).first
                        if узел.count():
                            узел.click(timeout=4000)
                            try:
                                page.wait_for_url(
                                    lambda u: "myprivacy.dpgmedia" not in u
                                    and "privacygate" not in u, timeout=30000)
                            except Exception:
                                pass
                            try:
                                page.wait_for_load_state("networkidle",
                                                         timeout=25000)
                            except Exception:
                                pass
                            page.wait_for_timeout(3000)
                            return True
                    except Exception:
                        pass
                for слово in CONSENT_WORDS:
                    try:
                        узел = где.get_by_role(
                            "button", name=_re.compile(слово, _re.I)).first
                        if узел.count():
                            узел.click(timeout=4000)
                            # После согласия сайт уводит через свой
                            # `privacygate-confirm` обратно на страницу.
                            # Ждать «тишины в сети» тут бесполезно: она
                            # наступает ДО начала перехода, и мы снимали
                            # промежуточную страницу-калитку в 8 КБ. Ждём
                            # именно возврата по адресу, потом даём скрипту
                            # дорисовать сетку (разбор 10.09: так выходит
                            # 760 КБ и 456 меток времени вместо нуля)
                            try:
                                page.wait_for_url(
                                    lambda u: "myprivacy.dpgmedia" not in u
                                    and "privacygate" not in u, timeout=30000)
                            except Exception:
                                pass
                            try:
                                page.wait_for_load_state("networkidle",
                                                         timeout=25000)
                            except Exception:
                                pass
                            page.wait_for_timeout(3000)
                            return True
                    except Exception:
                        continue
            try:
                page.wait_for_timeout(1200)
            except Exception:
                break
        return False

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ])
            context = browser.new_context(
                user_agent=agent, locale=locale,
                viewport={"width": 1366, "height": 900})
            page = context.new_page()
            # медленным сайтам 30 секунд не хватает даже на первую отрисовку
            # (`kanal1sport.sk` укладывается не всегда), поэтому даём вдвое
            answer = page.goto(url, wait_until="domcontentloaded",
                               timeout=TIMEOUT * 2000)
            status = answer.status if answer else 0
            # Снимок сразу после загрузки застаёт пустой каркас: сетку
            # дорисовывает отдельный запрос уже после `domcontentloaded`
            # (`rts.rs` — пустой `div#programska-sema`, `sport5.co.il` —
            # таблица после выбора дня). Ждём, пока сеть утихнет, и только
            # потом снимаем страницу. Если тишины так и нет — берём как есть.
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            if urlsplit(url).netloc.removeprefix("www.") in CONSENT_SITES:
                _accept_consent(page)
            html = page.content()
            browser.close()
    except Exception as exc:
        return Page(url, "", False, f"браузер: {type(exc).__name__}: {exc}")

    if status != 200:
        return Page(url, "", False, f"HTTP {status} (браузер)",
                    body=html[:20000], via="browser")
    return Page(url, html, False, via="browser")


class Fetcher:
    """Один прогон обхода. Помнит, когда последний раз ходил на каждый домен."""

    def __init__(self, offline: bool = True, use_cache: bool = True,
                 browser_fallback: bool = False, browser_only: bool = False):
        self.offline = offline          # True — на сайты не ходим вообще
        self.use_cache = use_cache
        # запасной путь через браузер: включаем в обходе, где отказ реален
        self.browser_fallback = browser_fallback
        # сразу браузером, без обычного запроса. Нужен там, где сайт отвечает
        # честным 200, но расписание дорисовывает скриптом: `sport5.co.il`,
        # `rtcg.me` — по обычному запросу приходит каркас без единой строки,
        # и запасной путь не срабатывает, потому что отказа не было
        self.browser_only = browser_only
        self._last: dict[str, float] = {}
        self._agent: dict[str, str] = {}
        # сессии по домену: нужны сайтам, которые отдают данные только тому,
        # кто до этого открыл обычную страницу и получил куки
        # (`sporteventz.com` с токеном Joomla, `dagenstv.com` с петлёй
        # редиректов). Для остальных сессия ничего не меняет
        self._session: dict[str, object] = {}
        # гостевые ключи ручек из TOKEN_HOSTS: берутся один раз за обход
        self._tokens: dict[str, dict[str, str]] = {}

    def _token_headers(self, host: str, agent: str, verify: bool) -> dict[str, str]:
        """Заголовки ручки с гостевым ключом (`TOKEN_HOSTS`); прочим — пусто.
        Ключ не получен — отдаём одни заголовки: ручка ответит 401, и в отчёте
        обхода будет видно, что сломался именно ключ."""
        config = TOKEN_HOSTS.get(host)
        if not config:
            return {}
        if host not in self._tokens:
            import requests
            got: dict[str, str] = {}
            try:
                script = requests.get(config["script"], timeout=TIMEOUT,
                                      verify=verify, headers=headers(agent)).text
                login = re.search(config["login"], script)
                if login:
                    answer = requests.post(
                        config["token"], timeout=TIMEOUT, verify=verify,
                        headers={"User-Agent": agent,
                                 "Authorization": login.group(1),
                                 **config["headers"]})
                    key = answer.json().get("access_token") if answer.ok else ""
                    if key:
                        got = {"Authorization": f"Bearer {key}"}
            except Exception:           # сеть или разметка скрипта сменилась
                pass
            self._tokens[host] = got
        return {**config["headers"], **self._tokens[host]}

    def _wait(self, host: str) -> None:
        was = self._last.get(host)
        if was is not None:
            пауза = DOMAIN_DELAY.get(host.removeprefix("www."), DELAY)
            left = пауза - (time.monotonic() - was)
            if left > 0:
                time.sleep(left)
        self._last[host] = time.monotonic()

    def get(self, url: str, local: Path | None = None,
            post: dict | None = None, warmup: str = "",
            post_json: dict | None = None, extra: dict | None = None) -> Page:
        """Страница по адресу. Порядок: указанная копия → кэш → сайт.

        `post` — поля формы; с ними вместо GET уходит POST. Так отдают
        расписание сайты, у которых день переключается формой, а не адресом
        (`sport1tv.cz` — `admin-ajax.php`, `tvr.ro` — `form#form_schedule`).
        """
        if local and local.exists():
            return Page(url, local.read_text(encoding="utf-8", errors="replace"), True)

        cached = cache_name(url, post or post_json)
        if self.use_cache and cached.exists():
            return Page(url, cached.read_text(encoding="utf-8", errors="replace"), True)

        if self.offline:
            return Page(url, "", False, "копии нет, а выходить на сайт запрещено")

        import requests  # локально: без сети модуль не нужен

        host = urlsplit(url).netloc
        agent = self._agent.setdefault(host, AGENTS[len(self._agent) % len(AGENTS)])
        self._wait(host)

        # Сайты с испорченным сертификатом: `dagenstv.com` отдаёт цепочку без
        # промежуточного звена, у `arenatv.sk` сертификат просрочен. Браузер в
        # таком случае показывает предупреждение и пускает дальше, а requests
        # сразу отказывается. Проверку снимаем только для этих доменов и
        # только ради чтения открытого расписания.
        verify = host.removeprefix("www.") not in BROKEN_TLS
        # закрытым для дата-центров сайтам ходим через открытую читалку
        through_reader = host.removeprefix("www.") in VIA_READER
        if through_reader:
            page = self._through_readers(url, agent, verify)
            if page.ok:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(page.html, encoding="utf-8")
            return page

        # разогрев: открываем обычную страницу сайта той же сессией, чтобы
        # получить куки, и только потом просим данные
        keeper = self._session.get(host)
        if warmup and keeper is None:
            keeper = requests.Session()
            self._session[host] = keeper
            try:
                warm = keeper.get(warmup, timeout=TIMEOUT, verify=verify,
                                  headers=headers(agent))
                # одноразовый ключ из warmup-страницы — метка {WARMKEY}
                pattern = WARMKEY_PATTERNS.get(host.removeprefix("www."))
                if pattern and "{WARMKEY}" in url + str(post or ""):
                    found = re.search(pattern, warm.text)
                    if found:
                        key = found.group(1)
                        url = url.replace("{WARMKEY}", key)
                        if post:
                            post = {k: str(v).replace("{WARMKEY}", key)
                                    for k, v in post.items()}
            except Exception:           # разогрев не удался — идём как есть
                pass
            self._wait(host)
        caller = keeper if keeper is not None else requests
        # ручки с гостевым ключом (`sportklub.hr`): ключ и их заголовки
        if host in TOKEN_HOSTS:
            extra = {**self._token_headers(host, agent, verify), **(extra or {})}

        try:
            if post_json is not None:
                # тело запроса — настоящий JSON, а не поля формы: так просит
                # `fpf.watch.pixellot.tv` (данные Canal 11), и такие ручки
                # обычно требуют ещё `Origin` и `Referer` своего сайта
                answer = caller.post(url, json=post_json, timeout=TIMEOUT,
                                     verify=verify,
                                     headers={**headers(agent),
                                              "Content-Type": "application/json",
                                              **(extra or {})})
            elif post:
                answer = caller.post(url, data=post, timeout=TIMEOUT,
                                     verify=verify,
                                     headers={**headers(agent), "X-Requested-With":
                                              "XMLHttpRequest", **(extra or {})})
            else:
                answer = caller.get(url, timeout=TIMEOUT, verify=verify,
                                    headers={**headers(agent), **(extra or {})})
        except Exception as exc:                      # сеть, таймаут, DNS
            return Page(url, "", False, f"{type(exc).__name__}: {exc}")
        if answer.status_code != 200:
            # тело ошибки сохраняем: по нему видно, кто закрыл — защита или
            # сам сайт. Без него в отчёте остаётся голое «HTTP 403».
            return Page(url, "", False, f"HTTP {answer.status_code}",
                        body=answer.text[:20000])

        # Сервер не назвал кодировку — requests подставляет latin-1, и
        # `piłka nożna` превращается в `piÅka noÅ¼na` (поймано на JSON
        # polsatsport.pl 31.08). JSON по стандарту — UTF-8; для остального
        # берём определённую по содержимому.
        if "charset" not in (answer.headers.get("content-type") or "").lower():
            body = answer.content.lstrip()[:1]
            answer.encoding = "utf-8" if body in (b"{", b"[") \
                else answer.apparent_encoding
        html = answer.text
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(html, encoding="utf-8")
        return Page(url, html, False)


    def _through_readers(self, url: str, agent: str, verify: bool) -> "Page":
        """Достать страницу через читалки — по очереди, пока не выйдет.

        Возвращает первую содержательную выдачу. Если не смогла ни одна, в
        ошибке перечислено, что ответила каждая: по этой строке в отчёте
        обхода видно, какую именно читалку чинить.
        """
        import requests
        from urllib.parse import quote

        enc = quote(url, safe="")
        # Переводчик Google открывает чужой сайт на своём поддомене:
        # `mojtv.hr` → `mojtv-hr.translate.goog`. Строка адреса собирается
        # иначе остальных, поэтому готовим её отдельно
        части = urlsplit(url)
        translate = (f"https://{части.netloc.replace('-', '--').replace('.', '-')}"
                     f".translate.goog{части.path}"
                     f"{'?' + части.query + '&' if части.query else '?'}"
                     f"_x_tr_sl=auto&_x_tr_tl=en&_x_tr_hl=en")
        why = []
        for pattern, extra in readers():
            through = pattern.format(url=url, enc=enc, translate=translate)
            name = urlsplit(through).netloc
            try:
                answer = requests.get(through, timeout=TIMEOUT * 3, verify=verify,
                                      headers={**headers(agent), **extra})
            except Exception as exc:
                why.append(f"{name}: {type(exc).__name__}")
                continue
            if answer.status_code != 200:
                why.append(f"{name}: HTTP {answer.status_code}")
                continue
            if "charset" not in (answer.headers.get("content-type") or "").lower():
                answer.encoding = "utf-8"
            html = answer.text
            ключи = READER_JSON.get(name.removeprefix("www."))
            if ключи:
                # microlink отдаёт {"data": {"html": "…"}} — достаём разметку
                try:
                    данные = answer.json()
                    for ключ in ключи:
                        данные = данные[ключ]
                    html = данные if isinstance(данные, str) else ""
                except Exception:
                    why.append(f"{name}: ответ не разобрался")
                    continue
            if len(html) < READER_MIN_BYTES or protection_text(html):
                why.append(f"{name}: пусто ({len(html)} байт)")
                continue
            return Page(url, html, False, via=f"reader:{name}")
        return Page(url, "", False, "читалки не отдали страницу — " + "; ".join(why))

    def get_with_fallback(self, url: str, local: Path | None = None,
                          locale: str = "en-GB", post: dict | None = None,
                          warmup: str = "", post_json: dict | None = None,
                          extra: dict | None = None) -> Page:
        """Обычный запрос, а если отказали — ещё одна попытка браузером.

        У POST-адреса запасного пути нет: браузер открывает страницу только
        GET-ом и вернёт тот же пустой каркас, ради которого мы и делаем POST.
        """
        if post or warmup or post_json is not None:
            return self.get(url, local, post=post, warmup=warmup,
                            post_json=post_json, extra=extra)
        if self.browser_only and not self.offline:
            cached = cache_name(url)
            if self.use_cache and cached.exists():
                return Page(url, cached.read_text(encoding="utf-8", errors="replace"), True)
            self._wait(urlsplit(url).netloc)
            agent = self._agent.setdefault(urlsplit(url).netloc, AGENTS[0])
            only = browser_get(url, agent, locale)
            if only.ok:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(only.html, encoding="utf-8")
            return only
        page = self.get(url, local)
        if page.ok or self.offline or not self.browser_fallback:
            return page
        self._wait(urlsplit(url).netloc)
        agent = self._agent.get(urlsplit(url).netloc, AGENTS[0])
        second = browser_get(url, agent, locale)
        if second.ok:
            cached = cache_name(url)
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(second.html, encoding="utf-8")
            return second
        # Не пустили обе попытки — в отчёт идут обе причины. Иначе не понять,
        # то ли браузер тоже получил отказ, то ли он вообще не запускался.
        page.error = f"{page.error}; браузер: {second.error or 'без ошибки'}"
        page.body = second.body or page.body
        page.via = "requests+browser"
        return page


def save_raw(conn, source_id: int, url: str, html: str) -> None:
    """Кладём страницу в `raw_rows`: переразбор не потребует нового обхода."""
    conn.execute("INSERT INTO raw_rows (source_id, url, payload) VALUES (?,?,?)",
                 (source_id, url, html))

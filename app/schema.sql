-- Схема базы Streams Schedule (ТЗ раздел 4).
-- Везде мягкое удаление: enabled / ignored. Физически строки не удаляем,
-- владелец должен иметь возможность вернуть.

PRAGMA foreign_keys = ON;

-- ── Источники ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sources (
    id                INTEGER PRIMARY KEY,
    domain            TEXT NOT NULL UNIQUE,      -- дубль считаем по домену (разд. 11)
    name              TEXT NOT NULL,
    base_url          TEXT NOT NULL,
    country           TEXT,
    timezone          TEXT,                      -- по стране домена, правится вручную
    role              TEXT NOT NULL DEFAULT 'schedule',  -- schedule | directory (разд. 5.1)
    access            TEXT NOT NULL DEFAULT 'unknown',   -- open | registration | paid | unknown
    access_checked_at TEXT,
    auth_ref          TEXT,                      -- ссылка на сохранённую сессию, не пароль
    url_pattern       TEXT,                      -- шаблон с датой, напр. .../{YYYY}/{MM}/{DD}/
    parse_strategy    TEXT,                      -- structured | selectors | heuristic | llm
    parse_level       TEXT,                      -- A | B | C | D — что показала разведка
    needs_js          INTEGER NOT NULL DEFAULT 0,
    protection        TEXT,                      -- cloudflare | captcha | 403 | imperva | ''
    selector_config   TEXT,                      -- JSON с найденными селекторами
    priority          INTEGER NOT NULL DEFAULT 100,  -- вес доверия при расхождении времени
    enabled           INTEGER NOT NULL DEFAULT 1,
    status            TEXT NOT NULL DEFAULT 'new',   -- new | ok | broken | closed
    fail_count        INTEGER NOT NULL DEFAULT 0,
    last_run          TEXT,
    last_success      TEXT,
    notes             TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sources_enabled ON sources(enabled, role);
CREATE INDEX IF NOT EXISTS idx_sources_status  ON sources(status);

-- Все ссылки источника: по ним ищем дубли при добавлении пачкой.
CREATE TABLE IF NOT EXISTS source_urls (
    id        INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    url       TEXT NOT NULL UNIQUE,
    added_at  TEXT NOT NULL DEFAULT (datetime('now')),
    note      TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_urls_source ON source_urls(source_id);

-- ── Каналы ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS channels (
    id             INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    slug           TEXT NOT NULL UNIQUE,
    country        TEXT,
    language       TEXT,
    enabled        INTEGER NOT NULL DEFAULT 1,
    -- имя правил владелец руками: на витрине показываем ровно его, без
    -- приставки страны (правило владельца 09.09 — «как отредактировал,
    -- так и должно копироваться»)
    custom_name    INTEGER NOT NULL DEFAULT 0,
    -- пометка перед именем на витрине: видна, но при клике НЕ копируется
    -- (просьба владельца 10.09: «показывать New-AL| Super Sport 3,
    -- копировать только Super Sport 3»). Пусто — показываем страну
    note           TEXT
);

CREATE TABLE IF NOT EXISTS channel_aliases (
    id         INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    alias      TEXT NOT NULL,
    source_id  INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    UNIQUE (alias, source_id)
);

-- Каналы, найденные на конкретном источнике. include=0 — не обходим (AXN не нужен).
CREATE TABLE IF NOT EXISTS source_channels (
    id         INTEGER PRIMARY KEY,
    source_id  INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    raw_name   TEXT NOT NULL,
    channel_id INTEGER REFERENCES channels(id) ON DELETE SET NULL,
    page_url   TEXT,
    include    INTEGER NOT NULL DEFAULT 1,
    last_seen  TEXT,
    UNIQUE (source_id, raw_name)
);

-- Каналы, увиденные в справочниках (liveonsat, sporteventz, livesoccertv).
-- Нужны, чтобы понимать, какие каналы существуют и на какие у нас ещё нет сайта.
CREATE TABLE IF NOT EXISTS directory_channels (
    id                INTEGER PRIMARY KEY,
    source_id         INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    channel_raw_name  TEXT NOT NULL,
    country           TEXT,
    matches_count     INTEGER NOT NULL DEFAULT 0,
    matched_channel_id INTEGER REFERENCES channels(id) ON DELETE SET NULL,
    first_seen        TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen         TEXT,
    UNIQUE (source_id, channel_raw_name)
);

-- ── Лиги и команды ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS leagues (
    id             INTEGER PRIMARY KEY,
    slug           TEXT NOT NULL UNIQUE,     -- england-championship
    canonical_name TEXT NOT NULL,            -- ENGLAND: Championship
    sport          TEXT,                     -- F | B | T
    country        TEXT,
    ignored        INTEGER NOT NULL DEFAULT 0,
    ignored_at     TEXT
);

CREATE TABLE IF NOT EXISTS league_aliases (
    id        INTEGER PRIMARY KEY,
    league_id INTEGER NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
    alias     TEXT NOT NULL,
    lang      TEXT,
    UNIQUE (alias, lang)
);

CREATE TABLE IF NOT EXISTS teams (
    id             INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    slug           TEXT NOT NULL UNIQUE,
    country        TEXT
);

CREATE TABLE IF NOT EXISTS team_aliases (
    id      INTEGER PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    alias   TEXT NOT NULL,
    lang    TEXT,
    UNIQUE (alias, lang)
);

-- ── Игры и связь с каналами ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY,
    sport           TEXT NOT NULL,             -- F | B | T
    league_id       INTEGER REFERENCES leagues(id) ON DELETE SET NULL,
    team_home_id    INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    team_away_id    INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    league_auto     TEXT,                      -- как было на сайте, до перевода
    team_home_auto  TEXT,
    team_away_auto  TEXT,
    start_utc       TEXT NOT NULL,
    start_kyiv      TEXT NOT NULL,
    grace_minutes   INTEGER,                   -- своё значение поверх правила по спорту
    time_confidence TEXT,                      -- ok | spread — разброс между источниками
    flags           TEXT,                      -- needs_review, unmatched_teams…
    first_seen      TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen       TEXT,
    -- 21.09: 0 — игра «новая», пока владелец не прочитал (клик по строке
    -- или «Прочитано всё» на витрине)
    seen            INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_utc);
CREATE INDEX IF NOT EXISTS idx_events_key   ON events(sport, team_home_id, team_away_id);

CREATE TABLE IF NOT EXISTS event_channels (
    id             INTEGER PRIMARY KEY,
    event_id       INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    channel_id     INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    source_id      INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    source_url     TEXT,
    raw_title      TEXT,
    raw_time_local TEXT,
    live_marker    TEXT,
    miss_count     INTEGER NOT NULL DEFAULT 0,   -- гасим после 3 неподтверждений
    first_seen     TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen      TEXT,
    UNIQUE (event_id, channel_id, source_id)
);

-- ── Служебное ────────────────────────────────────────────────────────────────

-- Сырьё страниц: пересобрать данные, не обходя сайты заново.
CREATE TABLE IF NOT EXISTS raw_rows (
    id         INTEGER PRIMARY KEY,
    source_id  INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    url        TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    payload    TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id             INTEGER PRIMARY KEY,
    started_at     TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at    TEXT,
    window_days    INTEGER,
    sources_ok     INTEGER NOT NULL DEFAULT 0,
    sources_failed INTEGER NOT NULL DEFAULT 0,
    rows_found     INTEGER NOT NULL DEFAULT 0,
    events_upserted INTEGER NOT NULL DEFAULT 0,
    log            TEXT
);

-- Настройки со страницы админки: грейсы, кулдаун публичной кнопки и т.п.
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Ключи API (ТЗ разд. 13): выдаются в админке, ходят в заголовке X-API-Key.
CREATE TABLE IF NOT EXISTS api_keys (
    id         INTEGER PRIMARY KEY,
    key        TEXT NOT NULL UNIQUE,
    note       TEXT,
    revoked    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Вид спорта, названный владельцем для конкретной пары команд.
-- Нужен строкам, где сайт спорт не пишет вовсе: «Kocaelispor -
-- Samsunspor» на beIN SPORTS 1 — ни лиги, ни слова о виде спорта
-- (разбор 10.09: таких строк в очереди было 372).
CREATE TABLE IF NOT EXISTS sport_hints (
    pair       TEXT PRIMARY KEY,        -- пара команд, как на сайте
    sport      TEXT NOT NULL,           -- F | B | T
    -- день матча: ответ действует вокруг этой даты, а не вечно — та же
    -- пара в другом туре может играть другой спорт (владелец 15.09).
    -- NULL — бессрочная подсказка (записи до этой правки)
    match_day  TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS moderation (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,              -- team | league | channel | sport
    raw_value  TEXT NOT NULL,
    source_id  INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    suggestion TEXT,
    status     TEXT NOT NULL DEFAULT 'open',   -- open | done | skipped | later
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_moderation_open ON moderation(status, kind);

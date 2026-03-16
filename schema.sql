-- ============================================================
-- TWR Playlist Generator - SQLite Schema
-- Databáze: data/playlists.db
-- ============================================================

-- Playlisty
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                     -- "Pondělí dopoledne 2025-01-27"
    scheduled_start DATETIME NOT NULL,      -- 2025-01-27 10:00:00
    duration INTEGER NOT NULL,              -- 14400 (4 hodiny v sekundách)
    preset_name TEXT DEFAULT 'default',     -- Použitý preset
    status TEXT DEFAULT 'draft',            -- draft | confirmed | exported
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,                        -- OS username
    config_json TEXT,                       -- JSON s použitým gain nastavením
    total_tracks INTEGER,                   -- Počet tracků
    actual_duration INTEGER                 -- Skutečná délka playlistu
);

CREATE INDEX IF NOT EXISTS idx_playlists_scheduled ON playlists(scheduled_start);
CREATE INDEX IF NOT EXISTS idx_playlists_status ON playlists(status);

-- Tracky v playlistu
CREATE TABLE IF NOT EXISTS playlist_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,              -- music.id z MariaDB
    position INTEGER NOT NULL,              -- pořadí v playlistu (1, 2, 3...)
    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_playlist_tracks_playlist ON playlist_tracks(playlist_id);
CREATE INDEX IF NOT EXISTS idx_playlist_tracks_track ON playlist_tracks(track_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_playlist_position ON playlist_tracks(playlist_id, position);

-- Historie přehrávání (sloučená tabulka pro cooldown tracking)
-- Obsahuje track_id, album_id i artist_ids v jednom záznamu
CREATE TABLE IF NOT EXISTS playlist_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER,
    track_id INTEGER NOT NULL,
    album_id INTEGER NOT NULL,
    artist_ids TEXT,                         -- JSON array nebo čárkami oddělená ID interpretů
    album_type TEXT,                         -- typ alba
    scheduled_start TEXT NOT NULL,
    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_scheduled_start ON playlist_history(scheduled_start);
CREATE INDEX IF NOT EXISTS idx_history_track ON playlist_history(track_id, scheduled_start);
CREATE INDEX IF NOT EXISTS idx_history_album ON playlist_history(album_id, scheduled_start);

-- File cache - rychlá kontrola existence souborů
CREATE TABLE IF NOT EXISTS file_cache (
    track_id INTEGER PRIMARY KEY,
    cd_id INTEGER NOT NULL,
    file_path TEXT,                         -- "C:\Music\CD_05_01.mp3"
    file_exists BOOLEAN DEFAULT 1,
    last_modified DATETIME,                 -- timestamp souboru
    last_checked DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_file_cache_cd ON file_cache(cd_id);
CREATE INDEX IF NOT EXISTS idx_file_cache_exists ON file_cache(file_exists);

-- Characteristics cache - cache charakteristik pro rychlé filtrování
CREATE TABLE IF NOT EXISTS characteristics_cache (
    track_id INTEGER NOT NULL,
    category_name TEXT NOT NULL,            -- "Jazyk", "Žánr", "Styl"
    characteristic_name TEXT NOT NULL,      -- "cs", "pop", "rock"
    PRIMARY KEY (track_id, category_name, characteristic_name)
);

CREATE INDEX IF NOT EXISTS idx_char_cache_track ON characteristics_cache(track_id);
CREATE INDEX IF NOT EXISTS idx_char_cache_category ON characteristics_cache(category_name, characteristic_name);

-- Výsledky validace tracků
CREATE TABLE IF NOT EXISTS validation_results (
    track_id INTEGER PRIMARY KEY,

    -- Jednotlivé kontroly (boolean)
    file_exists BOOLEAN,
    has_isrc BOOLEAN,
    isrc_valid BOOLEAN,
    year_valid BOOLEAN,
    duration_valid BOOLEAN,
    has_artist BOOLEAN,
    has_album BOOLEAN,

    -- Celkové hodnocení
    overall_score INTEGER,                  -- 0-100
    status TEXT,                            -- 'OK' | 'WARNING' | 'FAIL'

    -- Meta
    last_validated DATETIME DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_validation_status ON validation_results(status);
CREATE INDEX IF NOT EXISTS idx_validation_score ON validation_results(overall_score);

-- Schedule slots - cache slotů z program tabulky (MariaDB)
CREATE TABLE IF NOT EXISTS schedule_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id INTEGER,                    -- ID z program tabulky
    slot_name TEXT,                         -- volitelný název
    day_of_week INTEGER,                    -- 0=Po, 6=Ne
    start_time TIME,                        -- "10:00:00"
    duration INTEGER,                       -- sekundy
    preset_name TEXT DEFAULT 'default',
    synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_slots_day ON schedule_slots(day_of_week, start_time);

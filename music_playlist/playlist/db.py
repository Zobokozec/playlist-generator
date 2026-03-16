"""
DB – schéma playlist.db a inicializace.

Spuštění:
    from music_playlist.playlist.db import init_db
    init_db("playlist.db")
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
-- Playlisty
CREATE TABLE IF NOT EXISTS playlists (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT,
    scheduled_start DATETIME NOT NULL,
    duration        INTEGER NOT NULL,
    preset_name     TEXT DEFAULT 'default',
    status          TEXT DEFAULT 'draft',   -- draft|ready|exported
    config_json     TEXT,
    total_tracks    INTEGER,
    actual_duration INTEGER,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_playlists_start  ON playlists(scheduled_start);
CREATE INDEX IF NOT EXISTS idx_playlists_status ON playlists(status);

-- Tracky v playlistu (pořadí)
CREATE TABLE IF NOT EXISTS playlist_tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL,
    track_id    INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pt_playlist ON playlist_tracks(playlist_id);
CREATE INDEX IF NOT EXISTS idx_pt_track    ON playlist_tracks(track_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pt_position ON playlist_tracks(playlist_id, position);

-- Historie přehrávání (pro cooldown tracking)
CREATE TABLE IF NOT EXISTS playlist_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id     INTEGER,
    track_id        INTEGER NOT NULL,
    album_id        INTEGER NOT NULL,
    artist_ids      TEXT NOT NULL,          -- "81,93,100"
    scheduled_start DATETIME NOT NULL,
    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_hist_track   ON playlist_history(track_id,  scheduled_start);
CREATE INDEX IF NOT EXISTS idx_hist_album   ON playlist_history(album_id,  scheduled_start);
CREATE INDEX IF NOT EXISTS idx_hist_start   ON playlist_history(scheduled_start);

-- Album info (pro cooldown – rozlišení single/ep/full)
CREATE TABLE IF NOT EXISTS album_info (
    album_id    INTEGER PRIMARY KEY,
    track_count INTEGER NOT NULL,
    album_type  TEXT NOT NULL               -- 'single'|'ep'|'full'
);

-- Výsledky validace – jeden řádek = jeden track v playlistu
-- Každá kontrola má vlastní sloupce: <kontrola>_ok, <kontrola>_val, <kontrola>_msg
-- _ok  : 0/1 – zda kontrola prošla
-- _val : normalizovaná hodnota (pokud relevantní)
-- _msg : chybová nebo varovná zpráva (pokud kontrola selhala)
CREATE TABLE IF NOT EXISTS track_validation (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id         INTEGER NOT NULL,
    track_id            INTEGER NOT NULL,
    validated_at        TEXT NOT NULL,          -- ISO datetime
    passed              INTEGER NOT NULL,       -- 0 = neprošel (blokující chyba), 1 = prošel

    -- Blokující kontroly (passed=0 pokud selžou)
    file_exists_ok      INTEGER,               -- soubor existuje na disku
    file_exists_msg     TEXT,                  -- cesta nebo chyba

    lang_ok             INTEGER,               -- jazyk přiřazen
    lang_val            TEXT,                  -- název jazyka (např. 'Angličtina')
    lang_msg            TEXT,

    -- Neblokující kontroly (varování, passed zůstane 1)
    isrc_ok             INTEGER,               -- ISRC přítomen a platný formát ISO 3901
    isrc_val            TEXT,                  -- normalizovaný ISRC bez pomlček
    isrc_msg            TEXT,

    year_ok             INTEGER,               -- rok přítomen a v rozsahu 1900–2030
    year_val            INTEGER,               -- rok jako číslo
    year_msg            TEXT,

    duration_ok         INTEGER,               -- délka > 0 a odpovídá souboru (±5 s)
    duration_val        REAL,                  -- délka v sekundách
    duration_msg        TEXT,

    track_number_ok     INTEGER,               -- číslo stopy > 0
    track_number_val    INTEGER,

    album_code_ok       INTEGER,               -- kód alba ve formátu TYP0000
    album_code_val      TEXT,                  -- např. 'CD0001'

    path_format_ok      INTEGER,               -- cesta odpovídá konvenci TWR
    path_format_msg     TEXT,

    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
    UNIQUE (playlist_id, track_id)
);

CREATE INDEX IF NOT EXISTS idx_tv_playlist ON track_validation(playlist_id, passed);
CREATE INDEX IF NOT EXISTS idx_tv_track    ON track_validation(track_id);
CREATE INDEX IF NOT EXISTS idx_tv_file     ON track_validation(file_exists_ok);
CREATE INDEX IF NOT EXISTS idx_tv_isrc     ON track_validation(isrc_ok);
"""


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Inicializuje playlist.db – vytvoří tabulky pokud neexistují.

    Args:
        db_path: Cesta k SQLite souboru.

    Returns:
        Otevřené sqlite3.Connection s row_factory nastaveným na Row.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    logger.info("DB inicializována: %s", db_path)
    return conn


def create_playlist(
    conn: sqlite3.Connection,
    name: str,
    scheduled_start: str,
    duration: int,
    preset_name: str = "default",
    config_json: str = "{}",
) -> int:
    """Vloží nový playlist a vrátí jeho ID.

    Args:
        conn:            Připojení k playlist.db.
        name:            Název playlistu.
        scheduled_start: ISO datetime string.
        duration:        Cílová délka v sekundách.
        preset_name:     Název použitého presetu.
        config_json:     JSON string s konfigurací.

    Returns:
        ID nového playlistu.
    """
    cur = conn.execute(
        """
        INSERT INTO playlists
            (name, scheduled_start, duration, preset_name, status, config_json)
        VALUES (?, ?, ?, ?, 'draft', ?)
        """,
        (name, scheduled_start, duration, preset_name, config_json),
    )
    conn.commit()
    return cur.lastrowid


def add_tracks(
    conn: sqlite3.Connection,
    playlist_id: int,
    track_ids: list[int],
) -> None:
    """Vloží tracky do playlist_tracks s pozicemi.

    Args:
        conn:        Připojení k playlist.db.
        playlist_id: ID playlistu.
        track_ids:   Seřazený seznam track_id.
    """
    rows = [(playlist_id, tid, pos + 1) for pos, tid in enumerate(track_ids)]
    conn.executemany(
        "INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()


def save_validation_results(
    conn: sqlite3.Connection,
    playlist_id: int,
    validation_results: list,
    validated_at: str,
) -> None:
    """Uloží výsledky validace z music-utils do track_validation.

    Každý TrackValidation objekt z run_validation() odpovídá jednomu řádku.
    Výsledky jednotlivých kontrol jsou uloženy do dedikovaných sloupců
    (<kontrola>_ok, <kontrola>_val, <kontrola>_msg).

    Args:
        conn:               Připojení k playlist.db.
        playlist_id:        ID playlistu.
        validation_results: Seznam TrackValidation objektů z run_validation().
        validated_at:       ISO datetime string kdy proběhla validace.
    """
    rows = []
    for tv in validation_results:
        d = tv.details or {}

        def _ok(key):
            cr = d.get(key)
            return int(cr.ok) if cr is not None else None

        def _val(key):
            cr = d.get(key)
            return str(cr.value) if cr is not None and cr.value is not None else None

        def _int_val(key):
            cr = d.get(key)
            if cr is None or cr.value is None:
                return None
            try:
                return int(cr.value)
            except (TypeError, ValueError):
                return None

        def _float_val(key):
            cr = d.get(key)
            if cr is None or cr.value is None:
                return None
            try:
                return float(cr.value)
            except (TypeError, ValueError):
                return None

        def _msg(key):
            cr = d.get(key)
            if cr is None:
                return None
            return cr.error or cr.warning or None

        rows.append((
            playlist_id,
            tv.track_id,
            validated_at,
            int(tv.passed),
            # file_exists
            _ok("file_exists"),
            _msg("file_exists"),
            # lang
            _ok("lang"),
            _val("lang"),
            _msg("lang"),
            # isrc
            _ok("isrc"),
            _val("isrc"),
            _msg("isrc"),
            # year
            _ok("year"),
            _int_val("year"),
            _msg("year"),
            # duration
            _ok("duration"),
            _float_val("duration"),
            _msg("duration"),
            # track_number
            _ok("track_number"),
            _int_val("track_number"),
            # album_code
            _ok("album_code"),
            _val("album_code"),
            # path_format
            _ok("path_format"),
            _msg("path_format"),
        ))

    conn.executemany(
        """
        INSERT OR REPLACE INTO track_validation (
            playlist_id, track_id, validated_at, passed,
            file_exists_ok, file_exists_msg,
            lang_ok, lang_val, lang_msg,
            isrc_ok, isrc_val, isrc_msg,
            year_ok, year_val, year_msg,
            duration_ok, duration_val, duration_msg,
            track_number_ok, track_number_val,
            album_code_ok, album_code_val,
            path_format_ok, path_format_msg
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?
        )
        """,
        rows,
    )
    conn.commit()
    logger.debug(
        "save_validation_results: playlist #%d, %d tracků uloženo",
        playlist_id, len(validation_results),
    )

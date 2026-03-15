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

-- Souhrnný výsledek validace za track v playlistu
CREATE TABLE IF NOT EXISTS track_validation (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id     INTEGER NOT NULL,
    track_id        INTEGER NOT NULL,
    validated_at    TEXT NOT NULL,          -- ISO datetime
    passed          INTEGER NOT NULL,       -- 0 = neprošel, 1 = prošel
    errors          TEXT,                   -- CSV kódů blokujících chyb: 'no_file,no_lang'
    warnings        TEXT,                   -- CSV kódů varování: 'no_isrc,year_range'
    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
    UNIQUE (playlist_id, track_id)
);

CREATE INDEX IF NOT EXISTS idx_tv_playlist ON track_validation(playlist_id);
CREATE INDEX IF NOT EXISTS idx_tv_track    ON track_validation(track_id);
CREATE INDEX IF NOT EXISTS idx_tv_passed   ON track_validation(passed);

-- Výsledky jednotlivých kontrol (jeden řádek = jedna kontrola u jednoho tracku)
CREATE TABLE IF NOT EXISTS track_validation_checks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    validation_id   INTEGER NOT NULL,
    track_id        INTEGER NOT NULL,
    check_name      TEXT NOT NULL,          -- 'file_exists'|'lang'|'isrc'|'year'|...
    ok              INTEGER NOT NULL,       -- 0/1
    is_blocking     INTEGER NOT NULL DEFAULT 0, -- 1 = blokující chyba
    value           TEXT,                   -- normalizovaná hodnota (string)
    error           TEXT,                   -- chybová zpráva
    warning         TEXT,                   -- varování (neblokující)
    FOREIGN KEY (validation_id) REFERENCES track_validation(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tvc_validation ON track_validation_checks(validation_id);
CREATE INDEX IF NOT EXISTS idx_tvc_check      ON track_validation_checks(check_name, ok);
CREATE INDEX IF NOT EXISTS idx_tvc_track      ON track_validation_checks(track_id, check_name);
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
    """Uloží výsledky validace z music-utils do track_validation a track_validation_checks.

    Každý TrackValidation objekt odpovídá jednomu řádku v track_validation;
    každý CheckResult z details odpovídá jednomu řádku v track_validation_checks.

    Args:
        conn:               Připojení k playlist.db.
        playlist_id:        ID playlistu.
        validation_results: Seznam TrackValidation objektů z run_validation().
        validated_at:       ISO datetime string kdy proběhla validace.
    """
    # Mapování detail key → error kódy (dle music-utils validate_all)
    # check_name v details → množina kódů v tv.errors (blokující chyba jen pokud se průsečík neprázdný)
    CHECK_TO_ERRORS: dict[str, set[str]] = {
        "file_exists":  {"no_file"},
        "lang":         {"no_lang"},
        "isrc":         {"no_isrc", "isrc_invalid"},
        "year":         {"no_year", "year_range"},
        "duration":     {"duration_mismatch"},
        "path_format":  {"path_format"},
    }

    for tv in validation_results:
        errors_csv   = ",".join(tv.errors)   if tv.errors   else None
        warnings_csv = ",".join(tv.warnings) if tv.warnings else None
        tv_errors_set = set(tv.errors or [])

        cur = conn.execute(
            """
            INSERT OR REPLACE INTO track_validation
                (playlist_id, track_id, validated_at, passed, errors, warnings)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (playlist_id, tv.track_id, validated_at, int(tv.passed), errors_csv, warnings_csv),
        )
        validation_id = cur.lastrowid

        # Jednotlivé kontroly z details
        check_rows = []
        for check_name, result in (tv.details or {}).items():
            # is_blocking = 1 pokud tento check selhal A odpovídající error kód je v tv.errors
            error_codes = CHECK_TO_ERRORS.get(check_name, set())
            is_blocking = int(
                not result.ok and bool(error_codes & tv_errors_set)
            )
            value = str(result.value) if result.value is not None else None
            check_rows.append((
                validation_id,
                tv.track_id,
                check_name,
                int(result.ok),
                is_blocking,
                value,
                result.error,
                result.warning,
            ))

        if check_rows:
            conn.executemany(
                """
                INSERT INTO track_validation_checks
                    (validation_id, track_id, check_name, ok, is_blocking, value, error, warning)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                check_rows,
            )

    conn.commit()
    logger.debug(
        "save_validation_results: playlist #%d, %d tracků uloženo",
        playlist_id, len(validation_results),
    )

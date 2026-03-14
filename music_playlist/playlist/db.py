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

"""Testy pro db.py – SQLite schéma a CRUD operace."""
import sqlite3
import tempfile
import pytest
from pathlib import Path
from music_playlist.playlist.db import init_db, create_playlist, add_tracks


@pytest.fixture
def tmp_db(tmp_path):
    """Dočasná in-memory nebo file SQLite DB."""
    db_path = tmp_path / "test_playlist.db"
    conn = init_db(db_path)
    yield conn
    conn.close()


class TestInitDb:
    def test_creates_tables(self, tmp_db):
        tables = {row[0] for row in tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "playlists" in tables
        assert "playlist_tracks" in tables
        assert "playlist_history" in tables
        assert "album_info" in tables

    def test_idempotent_second_call(self, tmp_path):
        db_path = tmp_path / "test2.db"
        conn1 = init_db(db_path)
        conn1.close()
        conn2 = init_db(db_path)  # Nesmí selhat
        conn2.close()


class TestCreatePlaylist:
    def test_returns_id(self, tmp_db):
        pid = create_playlist(
            tmp_db,
            name="Test",
            scheduled_start="2026-03-15T09:00:00",
            duration=3600,
        )
        assert isinstance(pid, int)
        assert pid > 0

    def test_status_is_draft(self, tmp_db):
        pid = create_playlist(
            tmp_db,
            name="Test",
            scheduled_start="2026-03-15T09:00:00",
            duration=3600,
        )
        row = tmp_db.execute("SELECT status FROM playlists WHERE id=?", (pid,)).fetchone()
        assert row["status"] == "draft"

    def test_multiple_playlists_get_different_ids(self, tmp_db):
        id1 = create_playlist(tmp_db, "P1", "2026-03-15T09:00:00", 3600)
        id2 = create_playlist(tmp_db, "P2", "2026-03-15T13:00:00", 3600)
        assert id1 != id2


class TestAddTracks:
    def test_inserts_tracks_with_positions(self, tmp_db):
        pid = create_playlist(tmp_db, "Test", "2026-03-15T09:00:00", 3600)
        add_tracks(tmp_db, pid, [101, 202, 303])
        rows = tmp_db.execute(
            "SELECT track_id, position FROM playlist_tracks WHERE playlist_id=? ORDER BY position",
            (pid,),
        ).fetchall()
        assert [(r["track_id"], r["position"]) for r in rows] == [(101, 1), (202, 2), (303, 3)]

    def test_empty_track_list(self, tmp_db):
        pid = create_playlist(tmp_db, "Test", "2026-03-15T09:00:00", 3600)
        add_tracks(tmp_db, pid, [])  # Nesmí selhat
        rows = tmp_db.execute(
            "SELECT count(*) FROM playlist_tracks WHERE playlist_id=?", (pid,)
        ).fetchone()
        assert rows[0] == 0

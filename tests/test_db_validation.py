"""Testy pro save_validation_results() a schéma track_validation tabulek."""
import sqlite3
import pytest
from unittest.mock import MagicMock

from music_playlist.playlist.db import init_db, save_validation_results


# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------

def _make_check_result(ok=True, value=None, error=None, warning=None):
    cr = MagicMock()
    cr.ok = ok
    cr.value = value
    cr.error = error
    cr.warning = warning
    return cr


def _make_track_validation(track_id, passed=True, errors=None, warnings=None, details=None):
    tv = MagicMock()
    tv.track_id = track_id
    tv.passed = passed
    tv.errors = errors or ([] if passed else ["no_file"])
    tv.warnings = warnings or []
    tv.details = details or {
        "file_exists": _make_check_result(ok=passed, error=None if passed else "Soubor neexistuje"),
        "lang":        _make_check_result(ok=True, value="Angličtina"),
        "isrc":        _make_check_result(ok=True, value="CZABC2300001"),
        "year":        _make_check_result(ok=True, value=2023),
        "duration":    _make_check_result(ok=True, value=251.0),
    }
    return tv


# ---------------------------------------------------------------------------
# Fixture – in-memory DB s plným schématem
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    conn = init_db(":memory:")
    # Vložíme playlist aby FK fungoval
    conn.execute(
        "INSERT INTO playlists (name, scheduled_start, duration) VALUES (?, ?, ?)",
        ("test", "2026-03-15T10:00:00", 3600),
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Testy schématu
# ---------------------------------------------------------------------------

class TestSchema:
    def test_track_validation_table_exists(self, db):
        cur = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='track_validation'")
        assert cur.fetchone() is not None

    def test_track_validation_checks_table_exists(self, db):
        cur = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='track_validation_checks'")
        assert cur.fetchone() is not None

    def test_required_columns_track_validation(self, db):
        cur = db.execute("PRAGMA table_info(track_validation)")
        cols = {row[1] for row in cur.fetchall()}
        assert {"playlist_id", "track_id", "validated_at", "passed", "errors", "warnings"} <= cols

    def test_required_columns_track_validation_checks(self, db):
        cur = db.execute("PRAGMA table_info(track_validation_checks)")
        cols = {row[1] for row in cur.fetchall()}
        assert {"validation_id", "track_id", "check_name", "ok", "is_blocking", "value", "error", "warning"} <= cols

    def test_index_on_check_name_ok(self, db):
        cur = db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_tvc_check'")
        assert cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Testy save_validation_results
# ---------------------------------------------------------------------------

class TestSaveValidationResults:
    def test_saves_one_track(self, db):
        tv = _make_track_validation(track_id=42, passed=True)
        save_validation_results(db, playlist_id=1, validation_results=[tv], validated_at="2026-03-15T10:00:00")

        row = db.execute("SELECT * FROM track_validation WHERE track_id = 42").fetchone()
        assert row is not None
        assert row["passed"] == 1
        assert row["playlist_id"] == 1

    def test_saves_multiple_tracks(self, db):
        tvs = [_make_track_validation(i, passed=True) for i in range(1, 4)]
        save_validation_results(db, 1, tvs, "2026-03-15T10:00:00")

        count = db.execute("SELECT COUNT(*) FROM track_validation WHERE playlist_id = 1").fetchone()[0]
        assert count == 3

    def test_failed_track_has_passed_zero(self, db):
        tv = _make_track_validation(track_id=99, passed=False, errors=["no_file"])
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")

        row = db.execute("SELECT passed, errors FROM track_validation WHERE track_id = 99").fetchone()
        assert row["passed"] == 0
        assert "no_file" in row["errors"]

    def test_check_rows_saved_per_detail(self, db):
        details = {
            "file_exists": _make_check_result(ok=True),
            "lang":        _make_check_result(ok=True, value="Čeština"),
            "isrc":        _make_check_result(ok=False, error="Neplatný ISRC"),
        }
        tv = _make_track_validation(track_id=10, passed=True, details=details)
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")

        rows = db.execute(
            "SELECT check_name, ok FROM track_validation_checks WHERE track_id = 10"
        ).fetchall()
        names = {r["check_name"] for r in rows}
        assert names == {"file_exists", "lang", "isrc"}

    def test_no_file_error_is_blocking(self, db):
        details = {
            "file_exists": _make_check_result(ok=False, error="Soubor neexistuje"),
            "lang":        _make_check_result(ok=True, value="Angličtina"),
        }
        tv = _make_track_validation(track_id=11, passed=False, errors=["no_file"], details=details)
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")

        row = db.execute(
            "SELECT is_blocking FROM track_validation_checks "
            "WHERE track_id = 11 AND check_name = 'file_exists'"
        ).fetchone()
        assert row["is_blocking"] == 1

    def test_non_blocking_check_has_is_blocking_zero(self, db):
        details = {
            "isrc": _make_check_result(ok=False, error="Chybí ISRC"),
        }
        tv = _make_track_validation(track_id=12, passed=True, details=details)
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")

        row = db.execute(
            "SELECT is_blocking FROM track_validation_checks "
            "WHERE track_id = 12 AND check_name = 'isrc'"
        ).fetchone()
        assert row["is_blocking"] == 0

    def test_check_value_stored_as_string(self, db):
        details = {"year": _make_check_result(ok=True, value=2023)}
        tv = _make_track_validation(track_id=13, passed=True, details=details)
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")

        row = db.execute(
            "SELECT value FROM track_validation_checks WHERE track_id = 13 AND check_name = 'year'"
        ).fetchone()
        assert row["value"] == "2023"

    def test_warnings_csv_stored(self, db):
        tv = _make_track_validation(track_id=14, passed=True, warnings=["no_isrc", "year_range"])
        tv.details = {}
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")

        row = db.execute("SELECT warnings FROM track_validation WHERE track_id = 14").fetchone()
        assert "no_isrc" in row["warnings"]
        assert "year_range" in row["warnings"]

    def test_empty_results_no_error(self, db):
        save_validation_results(db, 1, [], "2026-03-15T10:00:00")
        count = db.execute("SELECT COUNT(*) FROM track_validation").fetchone()[0]
        assert count == 0

    def test_queryable_by_check_name(self, db):
        """Ověří hlavní případ použití: dotaz na tracky s konkrétním selháním."""
        details_ok = {
            "isrc": _make_check_result(ok=True, value="CZABC2300001"),
            "file_exists": _make_check_result(ok=True),
        }
        details_bad = {
            "isrc": _make_check_result(ok=False, error="Chybí ISRC"),
            "file_exists": _make_check_result(ok=True),
        }
        tvs = [
            _make_track_validation(20, passed=True, details=details_ok),
            _make_track_validation(21, passed=True, details=details_bad),
            _make_track_validation(22, passed=True, details=details_ok),
        ]
        save_validation_results(db, 1, tvs, "2026-03-15T10:00:00")

        rows = db.execute(
            "SELECT track_id FROM track_validation_checks WHERE check_name='isrc' AND ok=0"
        ).fetchall()
        assert [r["track_id"] for r in rows] == [21]

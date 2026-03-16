"""Testy pro save_validation_results() a schéma track_validation tabulky."""
import pytest
from unittest.mock import MagicMock

from music_playlist.playlist.db import init_db, save_validation_results


# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------

def _cr(ok=True, value=None, error=None, warning=None):
    """Vytvoří mock CheckResult."""
    cr = MagicMock()
    cr.ok = ok
    cr.value = value
    cr.error = error
    cr.warning = warning
    return cr


def _tv(track_id, passed=True, errors=None, warnings=None, details=None):
    """Vytvoří mock TrackValidation."""
    tv = MagicMock()
    tv.track_id = track_id
    tv.passed = passed
    tv.errors = errors or ([] if passed else ["no_file"])
    tv.warnings = warnings or []
    tv.details = details if details is not None else {
        "file_exists":  _cr(ok=passed, error=None if passed else "Soubor neexistuje"),
        "lang":         _cr(ok=True, value="Angličtina"),
        "isrc":         _cr(ok=True, value="CZABC2300001"),
        "year":         _cr(ok=True, value=2023),
        "duration":     _cr(ok=True, value=251.0),
        "track_number": _cr(ok=True, value=3),
        "album_code":   _cr(ok=True, value="CD0001"),
        "path_format":  _cr(ok=True),
    }
    return tv


# ---------------------------------------------------------------------------
# Fixture – in-memory DB s plným schématem
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    conn = init_db(":memory:")
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
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='track_validation'"
        )
        assert cur.fetchone() is not None

    def test_no_track_validation_checks_table(self, db):
        """Stará EAV tabulka track_validation_checks již neexistuje."""
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='track_validation_checks'"
        )
        assert cur.fetchone() is None

    def test_column_per_check_exists(self, db):
        cur = db.execute("PRAGMA table_info(track_validation)")
        cols = {row[1] for row in cur.fetchall()}
        expected = {
            "passed",
            "file_exists_ok", "file_exists_msg",
            "lang_ok", "lang_val", "lang_msg",
            "isrc_ok", "isrc_val", "isrc_msg",
            "year_ok", "year_val", "year_msg",
            "duration_ok", "duration_val", "duration_msg",
            "track_number_ok", "track_number_val",
            "album_code_ok", "album_code_val",
            "path_format_ok", "path_format_msg",
        }
        assert expected <= cols

    def test_index_on_playlist_passed(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_tv_playlist'"
        )
        assert cur.fetchone() is not None

    def test_index_on_isrc_ok(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_tv_isrc'"
        )
        assert cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Testy save_validation_results
# ---------------------------------------------------------------------------

class TestSaveValidationResults:
    def test_saves_one_row_per_track(self, db):
        save_validation_results(db, 1, [_tv(42)], "2026-03-15T10:00:00")
        row = db.execute("SELECT * FROM track_validation WHERE track_id=42").fetchone()
        assert row is not None

    def test_saves_multiple_tracks(self, db):
        save_validation_results(db, 1, [_tv(i) for i in range(1, 4)], "2026-03-15T10:00:00")
        count = db.execute("SELECT COUNT(*) FROM track_validation WHERE playlist_id=1").fetchone()[0]
        assert count == 3

    def test_passed_stored_correctly(self, db):
        save_validation_results(db, 1, [_tv(10, passed=True), _tv(11, passed=False)], "2026-03-15T10:00:00")
        assert db.execute("SELECT passed FROM track_validation WHERE track_id=10").fetchone()[0] == 1
        assert db.execute("SELECT passed FROM track_validation WHERE track_id=11").fetchone()[0] == 0

    def test_lang_val_stored(self, db):
        tv = _tv(20, details={"lang": _cr(ok=True, value="Čeština")})
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")
        row = db.execute("SELECT lang_ok, lang_val FROM track_validation WHERE track_id=20").fetchone()
        assert row["lang_ok"] == 1
        assert row["lang_val"] == "Čeština"

    def test_isrc_val_stored(self, db):
        tv = _tv(21, details={"isrc": _cr(ok=True, value="CZABC2300001")})
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")
        row = db.execute("SELECT isrc_ok, isrc_val FROM track_validation WHERE track_id=21").fetchone()
        assert row["isrc_ok"] == 1
        assert row["isrc_val"] == "CZABC2300001"

    def test_year_val_stored_as_int(self, db):
        tv = _tv(22, details={"year": _cr(ok=True, value=2023)})
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")
        row = db.execute("SELECT year_ok, year_val FROM track_validation WHERE track_id=22").fetchone()
        assert row["year_ok"] == 1
        assert row["year_val"] == 2023

    def test_duration_val_stored_as_float(self, db):
        tv = _tv(23, details={"duration": _cr(ok=True, value=251.0)})
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")
        row = db.execute("SELECT duration_val FROM track_validation WHERE track_id=23").fetchone()
        assert abs(row["duration_val"] - 251.0) < 0.01

    def test_failed_check_stores_msg(self, db):
        tv = _tv(24, passed=False, errors=["no_file"], details={
            "file_exists": _cr(ok=False, error="Soubor nenalezen"),
        })
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")
        row = db.execute("SELECT file_exists_ok, file_exists_msg FROM track_validation WHERE track_id=24").fetchone()
        assert row["file_exists_ok"] == 0
        assert row["file_exists_msg"] == "Soubor nenalezen"

    def test_warning_stored_in_msg(self, db):
        tv = _tv(25, details={"duration": _cr(ok=False, warning="Délka se liší o 10s")})
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")
        row = db.execute("SELECT duration_ok, duration_msg FROM track_validation WHERE track_id=25").fetchone()
        assert row["duration_ok"] == 0
        assert "10s" in row["duration_msg"]

    def test_missing_check_stored_as_null(self, db):
        """Kontrola která chybí v details (např. path_format není vždy dostupný) → NULL."""
        tv = _tv(26, details={"lang": _cr(ok=True, value="Angličtina")})
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")
        row = db.execute("SELECT path_format_ok FROM track_validation WHERE track_id=26").fetchone()
        assert row["path_format_ok"] is None

    def test_empty_results_no_error(self, db):
        save_validation_results(db, 1, [], "2026-03-15T10:00:00")
        assert db.execute("SELECT COUNT(*) FROM track_validation").fetchone()[0] == 0

    # Klíčové: dotazy které jsou nyní přímočaré díky sloupcovému přístupu

    def test_query_tracks_with_invalid_isrc(self, db):
        """SELECT track_id WHERE isrc_ok=0 vrátí správný výsledek."""
        tvs = [
            _tv(30, details={"isrc": _cr(ok=True,  value="CZABC2300001")}),
            _tv(31, details={"isrc": _cr(ok=False, error="Chybí ISRC")}),
            _tv(32, details={"isrc": _cr(ok=True,  value="CZABC2300002")}),
        ]
        save_validation_results(db, 1, tvs, "2026-03-15T10:00:00")
        rows = db.execute("SELECT track_id FROM track_validation WHERE isrc_ok=0").fetchall()
        assert [r[0] for r in rows] == [31]

    def test_query_failed_tracks_in_playlist(self, db):
        """SELECT WHERE playlist_id=X AND passed=0 vrátí blokující chyby."""
        tvs = [_tv(40, passed=True), _tv(41, passed=False), _tv(42, passed=False)]
        save_validation_results(db, 1, tvs, "2026-03-15T10:00:00")
        count = db.execute("SELECT COUNT(*) FROM track_validation WHERE playlist_id=1 AND passed=0").fetchone()[0]
        assert count == 2

    def test_query_all_check_results_in_one_select(self, db):
        """Celý výsledek validace tracku jedním SELECT * – bez JOIN."""
        tv = _tv(50, passed=True)
        save_validation_results(db, 1, [tv], "2026-03-15T10:00:00")
        row = db.execute("SELECT * FROM track_validation WHERE track_id=50").fetchone()
        # Vše dostupné v jednom řádku
        assert row["passed"] == 1
        assert row["lang_val"] == "Angličtina"
        assert row["isrc_val"] == "CZABC2300001"
        assert row["year_val"] == 2023

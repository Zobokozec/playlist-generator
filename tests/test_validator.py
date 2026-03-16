"""Testy pro validator.py"""
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from music_playlist.playlist.validator import (
    validate_selected,
    _build_validation_input,
    _extract_lang,
)


def _track(music_id, file_exists=True, file_path=None):
    return {
        "music_id":     music_id,
        "album_id":     101,
        "duration":     210,
        "net_duration": 210.0,
        "year":         2010,
        "entity_ids":   [81],
        "chars_by_cat": {3: [12], 5: [45]},
        "file_exists":  file_exists,
        "file_path":    file_path or (f"X:\\MUSIC\\track_{music_id}.mp3" if file_exists else None),
    }


class TestValidateSelected:
    def test_all_valid_passes_through(self):
        playlist = [_track(1), _track(2), _track(3)]
        pool = [_track(4), _track(5)]
        result = validate_selected(playlist, pool)
        assert [t["music_id"] for t in result] == [1, 2, 3]

    def test_missing_file_gets_replacement(self):
        playlist = [_track(1, file_exists=False), _track(2)]
        pool = [_track(3), _track(4)]
        selected_ids = {1, 2}
        result = validate_selected(playlist, pool, selected_ids)
        ids = [t["music_id"] for t in result]
        assert 1 not in ids       # Nahrazen
        assert 2 in ids           # Zůstal
        assert 3 in ids           # Náhrada

    def test_no_replacement_available(self):
        """Pokud není náhrada, track se vynechá."""
        playlist = [_track(1, file_exists=False)]
        pool = []  # Prázdný pool
        result = validate_selected(playlist, pool)
        assert result == []

    def test_replacement_not_already_selected(self):
        """Náhrada nesmí být z již vybraných."""
        playlist = [_track(1, file_exists=False)]
        pool = [_track(2), _track(3)]
        selected_ids = {1, 2}   # Track 2 je již "vybrán"
        result = validate_selected(playlist, pool, selected_ids)
        ids = [t["music_id"] for t in result]
        assert 2 not in ids
        assert 3 in ids

    def test_empty_playlist(self):
        result = validate_selected([], [_track(5)])
        assert result == []

    def test_multiple_missing_get_multiple_replacements(self):
        playlist = [_track(1, file_exists=False), _track(2, file_exists=False)]
        pool = [_track(10), _track(11)]
        selected_ids = {1, 2}
        result = validate_selected(playlist, pool, selected_ids)
        assert len(result) == 2
        ids = {t["music_id"] for t in result}
        assert ids == {10, 11}

    def test_pool_without_file_not_used_as_replacement(self):
        """Tracky bez souboru v poolu se nepoužijí jako náhrada."""
        playlist = [_track(1, file_exists=False)]
        pool = [_track(2, file_exists=False), _track(3, file_exists=True)]
        result = validate_selected(playlist, pool)
        ids = [t["music_id"] for t in result]
        assert 2 not in ids
        assert 3 in ids


# ---------------------------------------------------------------------------
# _extract_lang
# ---------------------------------------------------------------------------

class TestExtractLang:
    @pytest.fixture
    def ctx(self, char_map):
        return SimpleNamespace(char_map=char_map)

    def test_jazyk_category_extracted(self, ctx):
        track = {"chars_by_cat": {3: [15], 5: [45]}}
        assert _extract_lang(track, ctx) == "Angličtina"

    def test_no_jazyk_returns_empty(self, ctx):
        track = {"chars_by_cat": {5: [45]}}
        assert _extract_lang(track, ctx) == ""

    def test_empty_chars_by_cat(self, ctx):
        track = {"chars_by_cat": {}}
        assert _extract_lang(track, ctx) == ""

    def test_missing_chars_by_cat(self, ctx):
        assert _extract_lang({}, ctx) == ""

    def test_empty_char_list_in_category(self, ctx):
        track = {"chars_by_cat": {3: []}}
        assert _extract_lang(track, ctx) == ""


# ---------------------------------------------------------------------------
# _build_validation_input
# ---------------------------------------------------------------------------

class TestBuildValidationInput:
    @pytest.fixture
    def ctx(self, char_map, album_map):
        return SimpleNamespace(char_map=char_map, album_map=album_map)

    @pytest.fixture
    def track(self):
        return {
            "music_id":    42,
            "album_id":    101,
            "isrc":        "CZ-TWR-23-00042",
            "year":        2023,
            "duration":    251,
            "file_path":   r"X:\MUSIC\CD0001\CD0001_03.mp3",
            "chars_by_cat": {3: [15], 5: [45]},
        }

    def test_id_maps_to_music_id(self, track, ctx):
        d = _build_validation_input(track, ctx)
        assert d["id"] == 42

    def test_isrc_maps_to_recording_code(self, track, ctx):
        d = _build_validation_input(track, ctx)
        assert d["recording_code"] == "CZ-TWR-23-00042"

    def test_lang_extracted_from_chars(self, track, ctx):
        d = _build_validation_input(track, ctx)
        assert d["lang"] == "Angličtina"

    def test_file_path_preserved(self, track, ctx):
        d = _build_validation_input(track, ctx)
        assert d["file_path"] == r"X:\MUSIC\CD0001\CD0001_03.mp3"

    def test_deleted_always_zero(self, track, ctx):
        d = _build_validation_input(track, ctx)
        assert d["deleted"] == 0


# ---------------------------------------------------------------------------
# run_validation – mockování music-utils
# ---------------------------------------------------------------------------

class TestRunValidation:
    @pytest.fixture
    def ctx(self, char_map, album_map):
        cfg = SimpleNamespace(MUSIC_ROOT_DIR="X:\\MUSIC")
        return SimpleNamespace(char_map=char_map, album_map=album_map, config=cfg)

    @pytest.fixture
    def playlist(self):
        return [
            {
                "music_id": 1, "album_id": 101, "isrc": "CZ-TWR-0001",
                "year": 2020, "duration": 210, "net_duration": 200.0,
                "file_path": r"X:\MUSIC\CD0001\CD0001_01.mp3", "file_exists": True,
                "file_dur_sec": 211.0, "chars_by_cat": {3: [15]},
            },
        ]

    def _make_tv(self, track_id, passed=True):
        """Vytvoří mock TrackValidation."""
        tv = MagicMock()
        tv.track_id = track_id
        tv.passed = passed
        tv.errors = [] if passed else ["no_file"]
        tv.warnings = []
        return tv

    def test_returns_list_when_utils_available(self, playlist, ctx):
        mock_tv = self._make_tv(1, passed=True)
        mock_module = MagicMock()
        mock_module.validate_all = lambda track, root, file_dur_sec=None: mock_tv

        with patch.dict("sys.modules", {"utils": MagicMock(), "utils.validate_all": mock_module}):
            from music_playlist.playlist.validator import run_validation as rv
            result = rv(playlist, ctx)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].track_id == 1

    def test_returns_empty_when_utils_missing(self, playlist, ctx):
        """Pokud music-utils není, vrátí prázdný seznam (žádný crash)."""
        with patch.dict("sys.modules", {"utils": None, "utils.validate_all": None}):
            from music_playlist.playlist.validator import run_validation as rv
            result = rv(playlist, ctx)
        assert result == []

    def test_failed_track_logged(self, playlist, ctx):
        """Track který neprošel validací se stále vrátí (jen s passed=False)."""
        mock_tv = self._make_tv(1, passed=False)
        mock_module = MagicMock()
        mock_module.validate_all = lambda track, root, file_dur_sec=None: mock_tv

        with patch.dict("sys.modules", {"utils": MagicMock(), "utils.validate_all": mock_module}):
            from music_playlist.playlist.validator import run_validation as rv
            result = rv(playlist, ctx)
        assert len(result) == 1
        assert result[0].passed is False

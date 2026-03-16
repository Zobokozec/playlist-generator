"""Testy pro exporter.py – build_track_export_dict, format_output, GeneratorResult."""
import pytest
from types import SimpleNamespace
from music_playlist.playlist.exporter import (
    GeneratorResult,
    _build_track_export_dict,
    _format_output,
    _track_full,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_context(char_map, entity_map, album_map):
    class MockConfig:
        EXPORTS_DIR = "/tmp/test_exports"

    ctx = SimpleNamespace(
        char_map=char_map,
        entity_map=entity_map,
        album_map=album_map,
        config=MockConfig(),
        twar=None,
        playlistdb=None,
    )
    ctx.entity_name = lambda eid: entity_map.get(eid, str(eid))
    return ctx


@pytest.fixture
def sample_track():
    return {
        "music_id":    1,
        "album_id":    101,
        "duration":    251,
        "net_duration": 241.0,
        "year":        2023,
        "isrc":        "CZ-TWR-23-00001",
        "entity_ids":  [81, 93],
        "chars_by_cat": {
            3: [15],   # Jazyk: Angličtina
            5: [45],   # Nálada: Klidná
        },
        "file_path":   r"C:\MUSIC\track_001.mp3",
        "file_exists": True,
        "intro_sec":   5.0,
        "outro_sec":   246.0,
    }


@pytest.fixture
def meta_by_id():
    return {
        1: {
            "music_id":           1,
            "title":              "Thank God I Do",
            "pronunciation":      "/tenk gad aj dú/",
            "description":        "Viděla jsem lásku přicházet.",
            "album_name":         "Lauren Daigle",
            "artist_pronunciation": "/lorin džejgl/",
        }
    }


# ---------------------------------------------------------------------------
# _build_track_export_dict
# ---------------------------------------------------------------------------

class TestBuildTrackExportDict:
    def test_title_from_meta(self, sample_track, meta_by_id, mock_context):
        d = _build_track_export_dict(sample_track, meta_by_id, mock_context)
        assert d["title"] == "Thank God I Do"

    def test_artist_from_entity_map(self, sample_track, meta_by_id, mock_context):
        d = _build_track_export_dict(sample_track, meta_by_id, mock_context)
        assert "Chris Tomlin" in d["artist"]
        assert "Hillsong" in d["artist"]

    def test_language_from_jazyk_category(self, sample_track, meta_by_id, mock_context):
        d = _build_track_export_dict(sample_track, meta_by_id, mock_context)
        assert d["language"] == "Angličtina"

    def test_duration_uses_net_duration(self, sample_track, meta_by_id, mock_context):
        d = _build_track_export_dict(sample_track, meta_by_id, mock_context)
        assert d["duration"] == 241.0

    def test_filename_is_file_path(self, sample_track, meta_by_id, mock_context):
        d = _build_track_export_dict(sample_track, meta_by_id, mock_context)
        assert d["filename"] == r"C:\MUSIC\track_001.mp3"

    def test_year_preserved(self, sample_track, meta_by_id, mock_context):
        d = _build_track_export_dict(sample_track, meta_by_id, mock_context)
        assert d["year"] == 2023

    def test_missing_meta_uses_empty_strings(self, sample_track, mock_context):
        d = _build_track_export_dict(sample_track, {}, mock_context)
        assert d["title"] == ""
        assert d["album"] == ""
        assert d["description"] == ""
        assert d["pronunciation"] == ""

    def test_style_and_keywords_are_lists(self, sample_track, meta_by_id, mock_context):
        d = _build_track_export_dict(sample_track, meta_by_id, mock_context)
        assert isinstance(d["style"], list)
        assert isinstance(d["keywords"], list)

    def test_non_jazyk_chars_go_to_keywords(self, sample_track, meta_by_id, mock_context):
        """Nálada/Klidná (cat 5) nemá 'jazyk' v názvu → půjde do keywords."""
        d = _build_track_export_dict(sample_track, meta_by_id, mock_context)
        # "Klidná" je z kategorie "Nálada" → keywords nebo style
        all_chars = d["style"] + d["keywords"]
        assert "Klidná" in all_chars


# ---------------------------------------------------------------------------
# _format_output
# ---------------------------------------------------------------------------

class TestFormatOutput:
    @pytest.fixture
    def sample_result(self, sample_track):
        return GeneratorResult(
            playlist_id=1,
            selected=[sample_track],
            excluded={"too_short": [99]},
            stats={"selected": 1, "total_duration": 241.0},
        )

    def test_ids_format(self, sample_result, mock_context):
        out = _format_output(sample_result.selected, sample_result, mock_context, "ids")
        assert out == [1]

    def test_full_format_is_list(self, sample_result, mock_context):
        out = _format_output(sample_result.selected, sample_result, mock_context, "full")
        assert isinstance(out, list)
        assert out[0]["id"] == 1
        assert "net_duration" in out[0]

    def test_debug_format_structure(self, sample_result, mock_context):
        out = _format_output(sample_result.selected, sample_result, mock_context, "debug")
        assert "playlist" in out
        assert "excluded" in out
        assert "stats" in out
        assert out["excluded"] == {"too_short": [99]}

    def test_invalid_format_raises(self, sample_result, mock_context):
        with pytest.raises(ValueError, match="Neznámý output_format"):
            _format_output(sample_result.selected, sample_result, mock_context, "xml")


# ---------------------------------------------------------------------------
# GeneratorResult
# ---------------------------------------------------------------------------

class TestGeneratorResult:
    def test_default_stats(self):
        r = GeneratorResult(playlist_id=1, selected=[], excluded={})
        assert r.stats["selected"] == 0
        assert r.stats["total_duration"] == 0.0
        assert "after_cooldown" in r.stats

    def test_custom_stats(self):
        r = GeneratorResult(
            playlist_id=42,
            selected=[],
            excluded={"lang": [1, 2]},
            stats={"selected": 5, "total_duration": 1200.0},
        )
        assert r.playlist_id == 42
        assert r.stats["selected"] == 5

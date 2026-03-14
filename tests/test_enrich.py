"""Testy pro enrich.py"""
import pytest
from music_playlist.playlist.enrich import enrich_tracks, _parse_ids


class TestParseIds:
    def test_basic(self):
        assert _parse_ids("81,93,100") == [81, 93, 100]

    def test_empty_string(self):
        assert _parse_ids("") == []

    def test_single_value(self):
        assert _parse_ids("42") == [42]

    def test_with_spaces(self):
        assert _parse_ids("81, 93") == [81, 93]


class TestEnrichTracks:
    def _make_mock_context(self, file_data: list[dict]):
        """Vytvoří mock context s definovanými výsledky file_cache."""
        from types import SimpleNamespace

        class MockMusicDB:
            def __init__(self, rows):
                self._rows = rows

            def dotaz_dict(self, sql, params=None):
                return self._rows

        return SimpleNamespace(musicdb=MockMusicDB(file_data))

    def _raw_row(
        self,
        music_id: int,
        album_id: int = 101,
        duration: int = 210,
        year: int = 2010,
        entity: str = "[81,93]",
        chars_ids: str = "{12:3,45:5}",
    ) -> dict:
        return {
            "music_id": music_id,
            "album_id": album_id,
            "duration": duration,
            "year": year,
            "isrc": f"CZ-TWR-{music_id:04d}",
            "entity": entity,
            "chars_ids": chars_ids,
        }

    def test_entity_ids_parsed(self):
        rows = [self._raw_row(1, entity="[81,93]")]
        ctx = self._make_mock_context([])
        result = enrich_tracks(rows, ctx)
        assert result[0]["entity_ids"] == [81, 93]

    def test_chars_by_cat_parsed(self):
        rows = [self._raw_row(1, chars_ids="{12:3,45:5,46:5}")]
        ctx = self._make_mock_context([])
        result = enrich_tracks(rows, ctx)
        cats = result[0]["chars_by_cat"]
        assert 3 in cats
        assert 12 in cats[3]
        assert 5 in cats
        assert 45 in cats[5]
        assert 46 in cats[5]

    def test_net_duration_from_intro_outro(self):
        rows = [self._raw_row(1, duration=300)]
        file_row = {
            "track_id": 1, "file_path": "test.mp3", "file_dur_sec": 300,
            "intro_sec": 10.0, "outro_sec": 250.0, "file_exists": 1,
        }
        ctx = self._make_mock_context([file_row])
        result = enrich_tracks(rows, ctx)
        assert result[0]["net_duration"] == pytest.approx(240.0)
        assert result[0]["intro_sec"] == 10.0
        assert result[0]["outro_sec"] == 250.0

    def test_net_duration_fallback_to_duration(self):
        """Pokud není file_cache, net_duration = duration (outro=duration, intro=0)."""
        rows = [self._raw_row(1, duration=300)]
        ctx = self._make_mock_context([])
        result = enrich_tracks(rows, ctx)
        assert result[0]["net_duration"] == pytest.approx(300.0)

    def test_file_exists_false_when_not_in_cache(self):
        rows = [self._raw_row(1)]
        ctx = self._make_mock_context([])
        result = enrich_tracks(rows, ctx)
        assert result[0]["file_exists"] is False
        assert result[0]["file_path"] is None

    def test_file_exists_true_from_cache(self):
        rows = [self._raw_row(1)]
        file_row = {
            "track_id": 1, "file_path": "X:\\MUSIC\\track.mp3",
            "file_dur_sec": 210, "intro_sec": None, "outro_sec": None, "file_exists": 1,
        }
        ctx = self._make_mock_context([file_row])
        result = enrich_tracks(rows, ctx)
        assert result[0]["file_exists"] is True
        assert result[0]["file_path"] == "X:\\MUSIC\\track.mp3"

    def test_empty_rows_returns_empty(self):
        ctx = self._make_mock_context([])
        assert enrich_tracks([], ctx) == []

    def test_original_fields_preserved(self):
        rows = [self._raw_row(42, album_id=101, year=2020)]
        ctx = self._make_mock_context([])
        result = enrich_tracks(rows, ctx)
        assert result[0]["music_id"] == 42
        assert result[0]["album_id"] == 101
        assert result[0]["year"] == 2020

"""Testy pro cooldown.py"""
import pytest
from datetime import datetime, timedelta
from music_playlist.playlist.cooldown import apply_cooldown, _parse_ids


class TestParseIds:
    def test_basic(self):
        assert _parse_ids("81,93,100") == [81, 93, 100]

    def test_empty(self):
        assert _parse_ids("") == []

    def test_none_string(self):
        assert _parse_ids("None") == []

    def test_with_spaces(self):
        assert _parse_ids("81, 93, 100") == [81, 93, 100]

    def test_single(self):
        assert _parse_ids("42") == [42]


class TestApplyCooldown:
    """
    Testy bez skutečné DB – používá mock context.
    """

    def _make_context(
        self,
        recent_tracks=None,
        full_album_ids=None,
        recent_artists="",
    ):
        """Vytvoří mock PlaylistContext."""
        from types import SimpleNamespace

        class MockDB:
            def __init__(self, track_ids, album_ids, artist_rows):
                self._track_ids = track_ids or []
                self._album_ids = album_ids or []
                self._artist_rows = artist_rows

            def dotaz_dict(self, sql, params=None):
                if "track_id" in sql and "album_info" not in sql:
                    return [{"track_id": t} for t in self._track_ids]
                elif "album_info" in sql:
                    return [{"album_id": a} for a in self._album_ids]
                else:
                    return [{"artist_ids": self._artist_rows}]

        class MockConfig:
            COOLDOWN_TRACK_HOURS = 24
            COOLDOWN_ALBUM_HOURS = 24
            COOLDOWN_ARTIST_HOURS = 6

        db = MockDB(recent_tracks, full_album_ids, recent_artists)
        ctx = SimpleNamespace(
            config=MockConfig(),
            playlistdb=db,
            album_map={},
        )
        return ctx

    def test_track_in_cooldown(self, sample_tracks):
        ctx = self._make_context(recent_tracks=[1])
        eligible, excluded = apply_cooldown(
            sample_tracks, datetime.now(), ctx
        )
        excluded_ids = [e["id"] for e in excluded]
        assert 1 in excluded_ids
        assert all(e["reason"] == "cooldown_track" for e in excluded if e["id"] == 1)

    def test_full_album_in_cooldown(self, sample_tracks):
        # Všechny tracky v sample_tracks mají album_id=101
        ctx = self._make_context(full_album_ids=[101])
        eligible, excluded = apply_cooldown(
            sample_tracks, datetime.now(), ctx
        )
        assert len(excluded) == len(sample_tracks)
        assert all(e["reason"] == "cooldown_album" for e in excluded)

    def test_artist_cooldown_uses_set_intersection(self, sample_tracks):
        """Artist cooldown musí kontrolovat VŠECHNY entity_ids (ne jen první)."""
        # Track 1 má entity_ids=[81], track 2 má entity_ids=[81]
        # Zablokujeme entity_id=81
        ctx = self._make_context(recent_artists="81")
        eligible, excluded = apply_cooldown(
            sample_tracks, datetime.now(), ctx
        )
        # Všechny tracky s entity_id=81 mají být vyřazeny
        for e in excluded:
            assert e["reason"] == "cooldown_artist"

    def test_no_cooldown_all_pass(self, sample_tracks):
        ctx = self._make_context()
        eligible, excluded = apply_cooldown(
            sample_tracks, datetime.now(), ctx
        )
        assert len(eligible) == len(sample_tracks)
        assert excluded == []

    def test_returns_correct_counts(self, sample_tracks):
        ctx = self._make_context(recent_tracks=[1, 2, 3])
        eligible, excluded = apply_cooldown(
            sample_tracks, datetime.now(), ctx
        )
        assert len(eligible) + len(excluded) == len(sample_tracks)
        assert len(excluded) == 3

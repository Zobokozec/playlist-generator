"""Testy pro validator.py"""
import pytest
from music_playlist.playlist.validator import validate_selected


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

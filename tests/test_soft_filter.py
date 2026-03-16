"""Testy pro soft_filter.py"""
import pytest
from music_playlist.playlist.soft_filter import soft_filter, _check_soft


class TestCheckSoft:
    def test_passes_matching_include(self, soft_params):
        track = {
            "music_id": 1, "chars_by_cat": {3: [12], 5: [45]},
            "net_duration": 210, "duration": 210, "year": 2010,
        }
        assert _check_soft(track, soft_params) is None

    def test_fails_lang_mismatch(self, soft_params):
        track = {
            "music_id": 1, "chars_by_cat": {3: [99], 5: [45]},
            "net_duration": 210, "duration": 210, "year": 2010,
        }
        assert _check_soft(track, soft_params) == "cat_3_mismatch"

    def test_fails_mood_mismatch(self, soft_params):
        track = {
            "music_id": 1, "chars_by_cat": {3: [12], 5: [99]},
            "net_duration": 210, "duration": 210, "year": 2010,
        }
        assert _check_soft(track, soft_params) == "cat_5_mismatch"

    def test_fails_excluded_char(self):
        params = {
            "chars": {3: {"include": [12], "exclude": [15]}},
            "duration": {}, "year": {},
        }
        track = {
            "music_id": 1, "chars_by_cat": {3: [12, 15]},
            "net_duration": 210, "duration": 210, "year": 2010,
        }
        assert _check_soft(track, params) == "cat_3_excluded"

    def test_fails_too_short(self, soft_params):
        track = {
            "music_id": 1, "chars_by_cat": {3: [12], 5: [45]},
            "net_duration": 30, "duration": 30, "year": 2010,
        }
        assert _check_soft(track, soft_params) == "too_short"

    def test_fails_too_long(self, soft_params):
        track = {
            "music_id": 1, "chars_by_cat": {3: [12], 5: [45]},
            "net_duration": 700, "duration": 700, "year": 2010,
        }
        assert _check_soft(track, soft_params) == "too_long"

    def test_fails_year_too_old(self, soft_params):
        track = {
            "music_id": 1, "chars_by_cat": {3: [12], 5: [45]},
            "net_duration": 210, "duration": 210, "year": 1960,
        }
        assert _check_soft(track, soft_params) == "year_too_old"

    def test_fails_year_too_new(self, soft_params):
        params = {**soft_params, "year": {"min": 1970, "max": 2000}}
        track = {
            "music_id": 1, "chars_by_cat": {3: [12], 5: [45]},
            "net_duration": 210, "duration": 210, "year": 2020,
        }
        assert _check_soft(track, params) == "year_too_new"

    def test_uses_net_duration_over_duration(self, soft_params):
        """net_duration (outro-intro) má přednost před duration."""
        track = {
            "music_id": 1, "chars_by_cat": {3: [12], 5: [45]},
            "net_duration": 30,   # pod min=60
            "duration": 300,      # to by prošlo
            "year": 2010,
        }
        assert _check_soft(track, soft_params) == "too_short"

    def test_no_year_skips_year_check(self, soft_params):
        track = {
            "music_id": 1, "chars_by_cat": {3: [12], 5: [45]},
            "net_duration": 210, "duration": 210, "year": None,
        }
        assert _check_soft(track, soft_params) is None


class TestSoftFilter:
    def test_eligible_and_excluded_counts(self, sample_tracks, soft_params):
        eligible, excluded = soft_filter(sample_tracks, soft_params)
        assert len(eligible) + len(excluded) == len(sample_tracks)
        assert all(isinstance(e, dict) for e in eligible)
        assert all("id" in e and "reason" in e for e in excluded)

    def test_all_pass_with_permissive_params(self, sample_tracks):
        params = {"chars": {}, "duration": {"min": 0, "max": 9999}, "year": {}}
        eligible, excluded = soft_filter(sample_tracks, params)
        assert len(eligible) == len(sample_tracks)
        assert excluded == []

    def test_all_excluded_impossible_filter(self, sample_tracks):
        params = {
            "chars": {3: {"include": [999]}},  # neexistující char_id
            "duration": {}, "year": {},
        }
        eligible, excluded = soft_filter(sample_tracks, params)
        assert eligible == []
        assert len(excluded) == len(sample_tracks)

    def test_excluded_has_correct_reasons(self, sample_tracks):
        params = {"chars": {}, "duration": {"min": 300, "max": 9999}, "year": {}}
        eligible, excluded = soft_filter(sample_tracks, params)
        assert all(e["reason"] == "too_short" for e in excluded)

    def test_string_category_ids_in_params(self, sample_tracks):
        """Klíče chars mohou přijít jako stringy (z JSON)."""
        params = {
            "chars": {"3": {"include": [12, 15, 20]}, "5": {"include": [45, 46, 47]}},
            "duration": {"min": 60, "max": 600},
            "year": {},
        }
        eligible, excluded = soft_filter(sample_tracks, params)
        assert len(eligible) + len(excluded) == len(sample_tracks)

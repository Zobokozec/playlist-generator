"""Testy pro isrc.py – normalizace a porovnání ISRC."""
import pytest
from music_playlist.playlist.isrc import normalize_isrc, isrc_equal


class TestNormalizeIsrc:
    def test_removes_hyphens(self):
        assert normalize_isrc("CZ-TWR-26-00042") == "CZTWR2600042"

    def test_uppercase(self):
        assert normalize_isrc("cztwr2600042") == "CZTWR2600042"

    def test_mixed_case_with_hyphens(self):
        assert normalize_isrc("Cz-Twr-26-00042") == "CZTWR2600042"

    def test_removes_spaces(self):
        assert normalize_isrc("CZ TWR 26 00042") == "CZTWR2600042"

    def test_none_returns_none(self):
        assert normalize_isrc(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_isrc("") is None

    def test_already_normalized(self):
        assert normalize_isrc("CZTWR2600042") == "CZTWR2600042"

    def test_strips_special_chars(self):
        assert normalize_isrc("CZ.TWR.26.00042") == "CZTWR2600042"


class TestIsrcEqual:
    def test_equal_normalized(self):
        assert isrc_equal("CZ-TWR-26-00042", "CZTWR2600042") is True

    def test_equal_case_insensitive(self):
        assert isrc_equal("cztwr2600042", "CZTWR2600042") is True

    def test_not_equal(self):
        assert isrc_equal("CZTWR2600042", "CZTWR2600043") is False

    def test_none_vs_string(self):
        assert isrc_equal(None, "CZTWR2600042") is False

    def test_both_none(self):
        assert isrc_equal(None, None) is False

    def test_empty_vs_string(self):
        assert isrc_equal("", "CZTWR2600042") is False

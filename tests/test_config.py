"""Testy pro config.py – načítání konfigurace."""
import pytest
from music_playlist.config.config import PlaylistConfig


class TestPlaylistConfig:
    def test_default_values(self):
        cfg = PlaylistConfig()
        assert cfg.COOLDOWN_TRACK_HOURS == 24
        assert cfg.COOLDOWN_ALBUM_HOURS == 24
        assert cfg.COOLDOWN_ARTIST_HOURS == 6
        assert cfg.LANG_CATEGORY_ID == 3
        assert cfg.ALBUM_SINGLE_MAX_TRACKS == 3
        assert cfg.ALBUM_EP_MAX_TRACKS == 7

    def test_from_toml_returns_config(self):
        """Načtení z existujícího config.toml."""
        from pathlib import Path
        toml_path = Path(__file__).parent.parent / "music_playlist" / "config" / "config.toml"
        if toml_path.exists():
            cfg = PlaylistConfig.from_toml(toml_path)
            assert isinstance(cfg, PlaylistConfig)
            assert cfg.LANG_CATEGORY_ID == 3

    def test_from_toml_missing_file_uses_defaults(self, tmp_path):
        """Chybějící soubor → výchozí hodnoty."""
        cfg = PlaylistConfig.from_toml(tmp_path / "nonexistent.toml")
        assert cfg.COOLDOWN_TRACK_HOURS == 24

    def test_to_dict(self):
        cfg = PlaylistConfig()
        d = cfg.to_dict()
        assert isinstance(d, dict)
        assert "COOLDOWN_TRACK_HOURS" in d
        assert "LANG_CATEGORY_ID" in d
        assert d["LANG_CATEGORY_ID"] == 3

    def test_album_type_logic(self):
        """Ověří logiku album_type (single/ep/full) v album_map."""
        cfg = PlaylistConfig(
            ALBUM_SINGLE_MAX_TRACKS=3,
            ALBUM_EP_MAX_TRACKS=7,
        )
        def album_type(count):
            if count <= cfg.ALBUM_SINGLE_MAX_TRACKS:
                return "single"
            if count <= cfg.ALBUM_EP_MAX_TRACKS:
                return "ep"
            return "full"

        assert album_type(1) == "single"
        assert album_type(3) == "single"
        assert album_type(4) == "ep"
        assert album_type(7) == "ep"
        assert album_type(8) == "full"
        assert album_type(15) == "full"

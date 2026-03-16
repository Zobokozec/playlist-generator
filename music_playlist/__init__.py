"""
music-playlist – Generátor playlistů pro TWR.

Pipeline: INIT → HARD FILTER → ENRICH → SOFT FILTER → COOLDOWN → SELECTOR → VALIDACE → EXPORT

Rychlý start:
    from music_playlist.config.config import PlaylistConfig
    from music_playlist.playlist import PlaylistContext, run_hard_filter, enrich_tracks
    from music_playlist.playlist import soft_filter, apply_cooldown, select_tracks
    from music_playlist.playlist import validate_selected, export_playlist, GeneratorResult

CLI:
    python -m music_playlist.cli generate --params params.json
    python -m music_playlist.cli history  --last 5
    python -m music_playlist.cli presets  --list
"""

__version__ = "0.1.0"
__author__ = "TWR"

"""
PlaylistConfig – konfigurace generátoru playlistů.

Načítá hodnoty z config.toml (nebo environment proměnných jako fallback).
Lze použít jako modul nebo přes CLI.

Příklad:
    cfg = PlaylistConfig.from_toml()
    cfg = PlaylistConfig.from_toml("cesta/ke/config.toml")
    cfg = PlaylistConfig()    # výchozí hodnoty
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Python 3.11+ má tomllib ve stdlib, starší verze potřebují tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            tomllib = None  # type: ignore

_DEFAULT_CONFIG_TOML = Path(__file__).parent / "config.toml"


@dataclass
class PlaylistConfig:
    """Konfigurace generátoru playlistů."""

    # --- Cooldown (hodiny) ---
    COOLDOWN_TRACK_HOURS: int = 24
    COOLDOWN_ALBUM_HOURS: int = 12
    COOLDOWN_ARTIST_HOURS: int = 6

    # --- Typy alb (max počet tracků) ---
    ALBUM_SINGLE_MAX_TRACKS: int = 3
    ALBUM_EP_MAX_TRACKS: int = 7

    # --- Pevné category_id z DB ---
    LANG_CATEGORY_ID: int = 4   # kategorie "Jazyk" – gate pro hard filter
    CAT_ID_LANGUAGE:  int = 4   # kategorie "Jazyk" – export: language pole
    CAT_ID_STYLE:     int = 2   # kategorie "Žánr"  – export: style pole

    # --- Tolerance délky ---
    DURATION_TOLERANCE_SEC: int = 5

    # --- Cesty ---
    MUSIC_ROOT_DIR: str = r"X:\MUSIC"
    PLAYLIST_DB: str = "data/playlist.db"
    MUSIC_DB: str = "data/music.db"
    PRESETS_DIR: str = "music_playlist/config/presets"

    # --- Export ---
    EXPORTS_DIR: str = "data/exports"
    EXPORT_FORMAT: str = "mlp"

    # --- Generátor ---
    MAX_SELECTOR_ITERATIONS: int = 10_000
    DEFAULT_TRACK_DURATION: int = 210   # 3.5 minuty fallback

    # --- Vyloučené duplicity (music_id) ---
    EXCLUDED_MUSIC_IDS: list = field(default_factory=list)

    # --- Logování ---
    LOG_LEVEL: str = "INFO"

    @classmethod
    def from_toml(cls, path: str | Path | None = None) -> "PlaylistConfig":
        """Načte konfiguraci z TOML souboru.

        Args:
            path: Cesta k .toml souboru. Výchozí: config/config.toml vedle tohoto souboru.

        Returns:
            PlaylistConfig instance.
        """
        toml_path = Path(path) if path else _DEFAULT_CONFIG_TOML

        if not toml_path.exists():
            return cls._from_env()

        if tomllib is None:
            print(
                f"[WARNING] tomllib/tomli není dostupné, "
                f"konfigurace načtena z výchozích hodnot. "
                f"Nainstalujte: pip install tomli",
                file=__import__("sys").stderr,
            )
            return cls._from_env()

        with open(toml_path, "rb") as f:
            data = tomllib.load(f)

        cooldown = data.get("cooldown", {})
        album = data.get("album", {})
        db = data.get("database", {})
        paths = data.get("paths", {})
        generator = data.get("generator", {})
        logging_cfg = data.get("logging", {})

        # Kořen projektu = 3 úrovně nad config.toml (playlist-generator/)
        project_root = toml_path.resolve().parent.parent.parent

        def _resolve(val: str) -> str:
            p = Path(val)
            return str((project_root / p).resolve()) if not p.is_absolute() else val

        return cls(
            COOLDOWN_TRACK_HOURS=cooldown.get("track_hours", cls.COOLDOWN_TRACK_HOURS),
            COOLDOWN_ALBUM_HOURS=cooldown.get("album_hours", cls.COOLDOWN_ALBUM_HOURS),
            COOLDOWN_ARTIST_HOURS=cooldown.get("artist_hours", cls.COOLDOWN_ARTIST_HOURS),
            ALBUM_SINGLE_MAX_TRACKS=album.get("single_max_tracks", cls.ALBUM_SINGLE_MAX_TRACKS),
            ALBUM_EP_MAX_TRACKS=album.get("ep_max_tracks", cls.ALBUM_EP_MAX_TRACKS),
            LANG_CATEGORY_ID=data.get("lang_category_id", cls.LANG_CATEGORY_ID),
            CAT_ID_LANGUAGE=data.get("cat_id_language", cls.CAT_ID_LANGUAGE),
            CAT_ID_STYLE=data.get("cat_id_style", cls.CAT_ID_STYLE),
            DURATION_TOLERANCE_SEC=data.get("duration_tolerance_sec", cls.DURATION_TOLERANCE_SEC),
            MUSIC_ROOT_DIR=paths.get("music_root", cls.MUSIC_ROOT_DIR),
            PLAYLIST_DB=_resolve(db.get("playlist_db", cls.PLAYLIST_DB)),
            MUSIC_DB=_resolve(db.get("music_db", cls.MUSIC_DB)),
            PRESETS_DIR=paths.get("presets_dir", cls.PRESETS_DIR),
            EXPORTS_DIR=paths.get("exports_dir", cls.EXPORTS_DIR),
            EXPORT_FORMAT=paths.get("export_format", cls.EXPORT_FORMAT),
            MAX_SELECTOR_ITERATIONS=generator.get("max_iterations", cls.MAX_SELECTOR_ITERATIONS),
            DEFAULT_TRACK_DURATION=generator.get("default_track_duration", cls.DEFAULT_TRACK_DURATION),
            LOG_LEVEL=logging_cfg.get("level", cls.LOG_LEVEL),
            EXCLUDED_MUSIC_IDS=data.get("excluded_music_ids", []),
        )

    @classmethod
    def _from_env(cls) -> "PlaylistConfig":
        """Načte konfiguraci z environment proměnných (fallback)."""
        return cls(
            COOLDOWN_TRACK_HOURS=int(os.environ.get("COOLDOWN_TRACK_HOURS", cls.COOLDOWN_TRACK_HOURS)),
            COOLDOWN_ALBUM_HOURS=int(os.environ.get("COOLDOWN_ALBUM_HOURS", cls.COOLDOWN_ALBUM_HOURS)),
            COOLDOWN_ARTIST_HOURS=int(os.environ.get("COOLDOWN_ARTIST_HOURS", cls.COOLDOWN_ARTIST_HOURS)),
            LANG_CATEGORY_ID=int(os.environ.get("LANG_CATEGORY_ID", cls.LANG_CATEGORY_ID)),
            PLAYLIST_DB=os.environ.get("PLAYLIST_DB", cls.PLAYLIST_DB),
            MUSIC_DB=os.environ.get("MUSIC_DB", cls.MUSIC_DB),
            MUSIC_ROOT_DIR=os.environ.get("MUSIC_ROOT_DIR", cls.MUSIC_ROOT_DIR),
        )

    def to_dict(self) -> dict:
        """Vrátí konfiguraci jako slovník."""
        return {
            f.name: getattr(self, f.name)
            for f in self.__dataclass_fields__.values()  # type: ignore[attr-defined]
        }

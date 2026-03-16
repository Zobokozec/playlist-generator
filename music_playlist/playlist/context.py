"""
PlaylistContext – inicializace a lookup mapy.

Načte jednou při startu:
    char_map   = {char_id: {'name', 'category', 'category_id'}}
    album_map  = {album_id: {'typ', 'cislo', 'track_count', 'album_type'}}
    entity_map = {entity_id: name}
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config.config import PlaylistConfig

logger = logging.getLogger(__name__)


class PlaylistContext:
    """Drží připojení k DB a lookup mapy načtené jednou při startu."""

    def __init__(self, twar, musicdb, playlistdb, config: "PlaylistConfig"):
        """
        Args:
            twar:       MariaDB klient (music-twar) – zdrojová pravda
            musicdb:    SQLite klient (musicdb) – sdílená cache, file_cache
            playlistdb: SQLite klient (playlist.db) – vlastní DB
            config:     PlaylistConfig instance
        """
        self.twar = twar
        self.musicdb = musicdb
        self.playlistdb = playlistdb
        self.config = config

        logger.info("PlaylistContext: načítám lookup mapy…")
        self.char_map: dict[int, dict] = self._load_char_map()
        self.album_map: dict[int, dict] = self._load_album_map()
        self.entity_map: dict[int, dict] = self._load_entity_map()
        logger.info(
            "PlaylistContext: %d charakteristik, %d alb, %d entit",
            len(self.char_map), len(self.album_map), len(self.entity_map),
        )

    # ------------------------------------------------------------------
    # Loader metody
    # ------------------------------------------------------------------

    def _load_char_map(self) -> dict[int, dict]:
        """
        {char_id: {'name': 'Klidná', 'category': 'Nálada', 'category_id': 3}}
        """
        rows = self.twar.dotaz_dict("""
            SELECT ch.id, ch.name, cc.id AS category_id, cc.name AS category
            FROM characteristics ch
            JOIN characteristic_categories cc ON ch.category = cc.id
            WHERE ch.deleted = 0 and usage_ = 1
        """)
        return {
            r["id"]: {
                "name": r["name"],
                "category": r["category"],
                "category_id": r["category_id"],
            }
            for r in rows
        }

    def _load_album_map(self) -> dict[int, dict]:
        """
        {album_id: {'typ': 'CD', 'cislo': 1, 'track_count': 12, 'album_type': 'full'}}
        album_type: 'single' (≤3), 'ep' (≤7), 'full' (>7)
        """
        cfg = self.config
        rows = self.twar.dotaz_dict("""
            SELECT a.id, a.name, a.name_pronunciation, a.year, a.country, a.notes, COUNT(m.id) AS track_count
            FROM music m
            LEFT JOIN music_albums a ON m.album = a.id AND m.deleted = 0
            WHERE a.deleted = 0
            GROUP BY a.id
        """)
        return {
            r["id"]: {
                "name":              r.get("name") or "",
                "name_pronunciation": r.get("name_pronunciation") or "",
                "year":              r.get("year"),
                "country":           r.get("country"),
                "notes":             r.get("notes") or "",
                "track_count":       r["track_count"],
                "album_type": (
                    "single" if r["track_count"] <= cfg.ALBUM_SINGLE_MAX_TRACKS else
                    "ep"     if r["track_count"] <= cfg.ALBUM_EP_MAX_TRACKS     else
                    "full"
                ),
            }
            for r in rows
        }

    def _load_entity_map(self) -> dict[int, dict]:
        """
        {entity_id: {'name': 'Chris Tomlin', 'pronunciation': 'Kris Tomlin', 'notes': ''}}
        """
        rows = self.twar.dotaz_dict("""
            SELECT e.id, e.full_name as name, e.pronunciation, e.notes from entity_usage
            inner join entities e on entity = e.id
            where subject_type in ( 6, 12)
            group by entity
        """)
        return {
            r["id"]: {
                "name":          r["name"],
                "pronunciation": r.get("pronunciation") or "",
                "notes":         r.get("notes") or "",
            }
            for r in rows
        }

    # ------------------------------------------------------------------
    # Helper lookups
    # ------------------------------------------------------------------

    def char_name(self, char_id: int) -> str:
        """Vrátí čitelný název charakteristiky nebo str(char_id)."""
        return self.char_map.get(char_id, {}).get("name", str(char_id))

    def category_name(self, char_id: int) -> str:
        """Vrátí název kategorie pro daný char_id."""
        return self.char_map.get(char_id, {}).get("category", "?")

    def entity_name(self, entity_id: int) -> str:
        """Vrátí jméno entity nebo str(entity_id)."""
        return self.entity_map.get(entity_id, {}).get("name", str(entity_id))

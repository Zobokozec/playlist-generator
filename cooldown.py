"""
Cooldown filtr pro prevenci opakování tracků/alb/interpretů.

Používá jednu tabulku playlist_history se sloupci:
    playlist_id, track_id, album_id, artist_ids (comma-separated), album_type, scheduled_start
"""
import logging
from datetime import datetime, timedelta
from typing import List, Set

logger = logging.getLogger(__name__)


class CooldownFilter:
    """Filtrace podle cooldown pravidel"""

    def __init__(self, db_client, config: dict = None):
        """
        Args:
            db_client: SQLiteClient instance
            config: settings.yaml['cooldown'] - např. {'track': 24, 'album': 24, 'artist': 6}
        """
        self.db = db_client
        self.config = config or {'track': 24, 'album': 24, 'artist': 6}

    def _get_duration_limits(self, hour: int) -> tuple:
        """Vrátí (min, max) délky tracku pro danou hodinu."""
        limits_cfg = self.config.get('duration_limits', {})
        default = limits_cfg.get('default', [110, 300])

        # Najdeme nejvyšší hranici <= hour
        best = None
        for key, val in limits_cfg.items():
            if key == 'default':
                continue
            boundary = int(key)
            if boundary <= hour and (best is None or boundary > best):
                best = boundary

        if best is not None:
            limits = limits_cfg[best]
        else:
            limits = default

        return limits[0], limits[1]

    def filter(self, candidates: List[dict],
               scheduled_start: datetime) -> List[dict]:
        """
        Vyfiltruj nedávno hrané a tracky mimo rozsah délky.

        Args:
            candidates: [{'music_id': int, 'album_id': int, 'artist_ids': [int, ...], 'duration': int, ...}]
            scheduled_start: Začátek nového playlistu

        Returns:
            Filtrovaný seznam kandidátů
        """
        track_cutoff = scheduled_start - timedelta(hours=self.config['track'])
        album_cutoff = scheduled_start - timedelta(hours=self.config['album'])
        artist_cutoff = scheduled_start - timedelta(hours=self.config['artist'])

        recent_tracks = self.get_recent_track_ids(track_cutoff)
        recent_albums = self.get_recent_album_ids(album_cutoff)
        recent_artists = self.get_recent_artist_ids(artist_cutoff)

        dur_min, dur_max = self._get_duration_limits(scheduled_start.hour)

        logger.info(
            "Cooldown: %d tracků, %d alb, %d interpretů v cooldownu, délka %d–%ds",
            len(recent_tracks), len(recent_albums), len(recent_artists),
            dur_min, dur_max,
        )

        valid = []
        duration_filtered = 0
        for candidate in candidates:
            track_id = candidate['music_id']
            album_id = candidate.get('album_id')
            artist_ids = set(candidate.get('artist_ids', []))
            duration = candidate.get('duration', 0)

            if track_id in recent_tracks:
                continue
            if album_id in recent_albums:
                continue
            if artist_ids & recent_artists:
                continue
            if duration < dur_min or duration > dur_max:
                duration_filtered += 1
                continue

            valid.append(candidate)

        if duration_filtered:
            logger.info("Cooldown: %d tracků vyřazeno kvůli délce (%d–%ds)",
                        duration_filtered, dur_min, dur_max)
        logger.info("Po cooldown filtru: %d z %d kandidátů", len(valid), len(candidates))
        return valid

    def get_recent_track_ids(self, cutoff: datetime) -> Set[int]:
        """Vrátí IDs tracků hraných po cutoff z playlist_history"""
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT DISTINCT track_id FROM playlist_history WHERE scheduled_start > ?",
            (cutoff.isoformat(),)
        ).fetchall()
        return {row[0] for row in rows}

    def get_recent_album_ids(self, cutoff: datetime) -> Set[int]:
        """Vrátí IDs alb hraných po cutoff z playlist_history"""
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT DISTINCT album_id FROM playlist_history WHERE scheduled_start > ?",
            (cutoff.isoformat(),)
        ).fetchall()
        return {row[0] for row in rows}

    def get_recent_artist_ids(self, cutoff: datetime) -> Set[int]:
        """Vrátí IDs interpretů hraných po cutoff z playlist_history (artist_ids je comma-separated)"""
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT DISTINCT artist_ids FROM playlist_history WHERE scheduled_start > ?",
            (cutoff.isoformat(),)
        ).fetchall()
        artists = set()
        for row in rows:
            if row[0]:
                artists.update(int(x) for x in str(row[0]).split(','))
        return artists

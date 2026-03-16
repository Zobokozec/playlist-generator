"""
Cooldown – Python sets pro track/album/artist cooldown.

Kritická pravidla:
    - Artist cooldown:  set intersection přes VŠECHNY entity_ids (ne jen [0])
    - Album cooldown:   jen album_type = 'full' (singly/EP neblokují)
    - Batch dotazy:     jeden dotaz per typ cooldownu
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import PlaylistContext
    from ..config.config import PlaylistConfig

logger = logging.getLogger(__name__)


def apply_cooldown(
    tracks: list[dict],
    scheduled_start: datetime,
    context: "PlaylistContext",
) -> tuple[list[dict], list[dict]]:
    """Odfiltruje tracky v cooldown období.

    Args:
        tracks:          Tracky po soft filtru.
        scheduled_start: Začátek generovaného playlistu (pro výpočet cutoff).
        context:         PlaylistContext s přístupem k playlistdb a config.

    Returns:
        (eligible, excluded)
        excluded = [{'id': music_id, 'reason': str}, ...]
    """
    cfg = context.config
    playlistdb = context.playlistdb

    # --- Track cooldown ---
    track_cutoff = scheduled_start - timedelta(hours=cfg.COOLDOWN_TRACK_HOURS)
    track_ids = set(
        r["track_id"]
        for r in playlistdb.dotaz_dict(
            "SELECT DISTINCT track_id FROM playlist_history WHERE scheduled_start > ?",
            (track_cutoff,),
        )
    )

    # --- Album cooldown (jen full alba) ---
    album_cutoff = scheduled_start - timedelta(hours=cfg.COOLDOWN_ALBUM_HOURS)
    full_album_ids = set(
        r["album_id"]
        for r in playlistdb.dotaz_dict(
            """
            SELECT DISTINCT ph.album_id
            FROM playlist_history ph
            JOIN album_info ai ON ph.album_id = ai.album_id
            WHERE ph.scheduled_start > ? AND ai.album_type = 'full'
            """,
            (album_cutoff,),
        )
    )

    # --- Artist cooldown ---
    artist_cutoff = scheduled_start - timedelta(hours=cfg.COOLDOWN_ARTIST_HOURS)
    artist_ids: set[int] = set()
    for row in playlistdb.dotaz_dict(
        "SELECT artist_ids FROM playlist_history WHERE scheduled_start > ?",
        (artist_cutoff,),
    ):
        artist_ids.update(_parse_ids(row.get("artist_ids", "")))

    logger.info(
        "Cooldown sets: %d tracks, %d full albums, %d artists",
        len(track_ids), len(full_album_ids), len(artist_ids),
    )

    eligible: list[dict] = []
    excluded: list[dict] = []

    for track in tracks:
        mid = track["music_id"]
        if mid in track_ids:
            excluded.append({"id": mid, "reason": "cooldown_track"})
        elif track["album_id"] in full_album_ids:
            excluded.append({"id": mid, "reason": "cooldown_album"})
        elif set(track["entity_ids"]) & artist_ids:
            excluded.append({"id": mid, "reason": "cooldown_artist"})
        else:
            eligible.append(track)

    logger.info(
        "apply_cooldown: %d eligible, %d excluded",
        len(eligible), len(excluded),
    )
    return eligible, excluded


def _parse_ids(s: str) -> list[int]:
    """'81,93,100' → [81, 93, 100]"""
    if not s:
        return []
    return [int(x.strip()) for x in str(s).split(",") if x.strip().lstrip("-").isdigit()]

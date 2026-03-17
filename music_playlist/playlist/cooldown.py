"""
Cooldown – Python sets pro track/album/artist cooldown.

Kritická pravidla:
    - Artist cooldown:  set intersection přes VŠECHNY entity_ids (ne jen [0])
    - Album cooldown:   jen album_type = 'full' (singly/EP neblokují)
    - Batch dotazy:     jeden dotaz per typ cooldownu

InSessionCooldown:
    - Sleduje artistry/alba zařazená v aktuální sesii (intra-playlist cooldown).
    - Virtuální čítač: součet duration zařazených tracků (od začátku playlistu).
    - Artista/album může být znovu zařazen po uplynutí min. mezery v sekundách.
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


class InSessionCooldown:
    """Intra-playlist cooldown – sleduje artistry/alba zařazená v aktuální sesii.

    Využívá virtuální časovou osu: součet duration zařazených tracků jako offset
    od začátku playlistu (v sekundách). Artista/album může být znovu zařazen
    teprve poté, co virtuální čas překročí min. mezeru od jejich posledního zařazení.

    Příklad:
        cd = InSessionCooldown(artist_gap_sec=1800, album_gap_sec=3600)
        cd.register(track, 240)       # track 4min zařazen, elapsed = 0..240
        cd.is_blocked(other_track)    # True pokud sdílí artista < 30 min zpět
    """

    def __init__(self, artist_gap_sec: float = 1800, album_gap_sec: float = 3600):
        """
        Args:
            artist_gap_sec: Minimální mezera (sek) mezi dvěma výskyty stejného artisty.
            album_gap_sec:  Minimální mezera (sek) mezi dvěma tracky ze stejného alba.
        """
        self._artist_gap = artist_gap_sec
        self._album_gap = album_gap_sec
        # artist_id / album_id → virtuální čas kdy byl naposledy zařazen
        self._artist_at: dict[int, float] = {}
        self._album_at: dict[int, float] = {}
        self._elapsed_sec = 0.0

    @property
    def elapsed_sec(self) -> float:
        """Aktuální virtuální čas od začátku playlistu (součet duration)."""
        return self._elapsed_sec

    def register(self, track: dict, duration_sec: float) -> None:
        """Zaznamená výběr tracku a posune virtuální čas.

        Args:
            track:        Obohacený dict tracku (musí mít entity_ids, album_id).
            duration_sec: Délka tracku v sekundách (net_duration nebo duration).
        """
        vt = self._elapsed_sec
        for aid in track.get("entity_ids", []):
            self._artist_at[aid] = vt
        album_id = track.get("album_id")
        if album_id:
            self._album_at[album_id] = vt
        self._elapsed_sec += duration_sec

    def is_blocked(self, track: dict) -> str | None:
        """Zkontroluje, zda je track blokován intra-playlist cooldownem.

        Album cooldown platí pouze pro full alba (stejná logika jako inter-playlist).
        Single, EP, demo a neznámé typy alb album cooldown netriggerují.

        Returns:
            Důvod blokace ('session_artist' / 'session_album') nebo None.
        """
        vt = self._elapsed_sec
        for aid in track.get("entity_ids", []):
            last = self._artist_at.get(aid)
            if last is not None and (vt - last) < self._artist_gap:
                return "session_artist"
        if track.get("album_type") == "full":
            album_id = track.get("album_id")
            if album_id:
                last = self._album_at.get(album_id)
                if last is not None and (vt - last) < self._album_gap:
                    return "session_album"
        return None

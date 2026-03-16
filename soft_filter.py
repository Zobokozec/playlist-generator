"""
Soft filtr – načte config/soft_filter.yaml a odfiltruje kandidáty
podle music_id, album_id a artist_ids.
"""

from __future__ import annotations

import logging
from pathlib import Path

from utils.config_loader import CONFIG_DIR, load_yaml

logger = logging.getLogger(__name__)

_cache: dict | None = None

SOFT_FILTER_PATH = CONFIG_DIR / "soft_filter.yaml"


def load_soft_filter() -> dict[str, set[int]]:
    """Načte soft filtr konfiguraci (s cache). Vrátí sety ID."""
    global _cache
    if _cache is not None:
        return _cache

    if not SOFT_FILTER_PATH.exists():
        logger.warning("Soft filter config neexistuje: %s – filtr přeskočen", SOFT_FILTER_PATH)
        _cache = {"music_ids": set(), "album_ids": set(), "artist_ids": set()}
        return _cache

    raw = load_yaml(SOFT_FILTER_PATH)
    _cache = {
        "music_ids": set(raw.get("music_ids") or []),
        "album_ids": set(raw.get("album_ids") or []),
        "artist_ids": set(raw.get("artist_ids") or []),
    }
    logger.info(
        "Soft filtr načten: %d music, %d album, %d artist ID",
        len(_cache["music_ids"]),
        len(_cache["album_ids"]),
        len(_cache["artist_ids"]),
    )
    return _cache


def apply_soft_filter(candidates: list[dict]) -> list[dict]:
    """Odstraní kandidáty, jejichž music_id, album_id nebo některý artist_id je v soft filtru."""
    sf = load_soft_filter()

    if not sf["music_ids"] and not sf["album_ids"] and not sf["artist_ids"]:
        return candidates

    result = []
    for c in candidates:
        if c["music_id"] in sf["music_ids"]:
            continue
        if c.get("album_id") in sf["album_ids"]:
            continue
        candidate_artists = c.get("artist_ids") or set()
        if candidate_artists & sf["artist_ids"]:
            continue
        result.append(c)

    logger.info("Soft filtr: %d → %d kandidátů", len(candidates), len(result))
    return result

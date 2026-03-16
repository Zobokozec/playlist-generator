"""
Soft filter – Python filtr charakteristik, délky a roku.

Parametry přicházejí z params.json jako category_id (int klíče):
    params = {
        'chars': {
            3: {'include': [12, 15], 'exclude': []},
            5: {'include': [45, 46, 47]},
        },
        'duration': {'min': 60, 'max': 600},
        'year':     {'min': 1990, 'max': 2026},
    }

Vrátí (eligible, excluded) – excluded je seznam {'id': music_id, 'reason': str}.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def soft_filter(
    tracks: list[dict],
    params: dict,
) -> tuple[list[dict], list[dict]]:
    """Odfiltruje tracky podle charakteristik, délky a roku.

    Args:
        tracks: Obohacené tracky (výstup enrich_tracks).
        params: Konfigurační parametry filtru.

    Returns:
        (eligible, excluded)
        excluded = [{'id': music_id, 'reason': str}, ...]
    """
    eligible: list[dict] = []
    excluded: list[dict] = []

    for track in tracks:
        reason = _check_soft(track, params)
        if reason:
            excluded.append({"id": track["music_id"], "reason": reason})
        else:
            eligible.append(track)

    logger.info(
        "soft_filter: %d eligible, %d excluded",
        len(eligible), len(excluded),
    )
    return eligible, excluded


def _check_soft(track: dict, params: dict) -> str | None:
    """Vrátí důvod vyřazení nebo None pokud track prošel."""
    chars = track["chars_by_cat"]  # {category_id: [char_id, …]}

    # Charakteristiky – include/exclude per kategorie
    for cat_id, rules in params.get("chars", {}).items():
        cat_id = int(cat_id)
        track_char_ids = set(chars.get(cat_id, []))
        include = set(rules.get("include", []))
        if include and not (track_char_ids & include):
            return f"cat_{cat_id}_mismatch"
        exclude = set(rules.get("exclude", []))
        if exclude and (track_char_ids & exclude):
            return f"cat_{cat_id}_excluded"

    # Délka (net_duration = outro - intro)
    dur = track.get("net_duration") or track.get("duration", 0)
    dur_params = params.get("duration", {})
    if dur < dur_params.get("min", 0):
        return "too_short"
    if dur > dur_params.get("max", 9999):
        return "too_long"

    # Rok
    year = track.get("year")
    year_params = params.get("year", {})
    if year:
        if year < year_params.get("min", 0):
            return "year_too_old"
        if year > year_params.get("max", 9999):
            return "year_too_new"

    return None

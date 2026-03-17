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


def _build_char_rules(params: dict) -> tuple[dict[int, set], dict[int, set]]:
    """Předzpracuje char pravidla jednou pro celý batch."""
    include_map: dict[int, set] = {}
    exclude_map: dict[int, set] = {}
    for cat_id, rules in params.get("chars", {}).items():
        cid = int(cat_id)
        inc = set(rules.get("include", []))
        exc = set(rules.get("exclude", []))
        if inc:
            include_map[cid] = inc
        if exc:
            exclude_map[cid] = exc
    return include_map, exclude_map


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
    include_map, exclude_map = _build_char_rules(params)
    dur_params = params.get("duration", {})
    year_params = params.get("year", {})

    eligible: list[dict] = []
    excluded: list[dict] = []

    for track in tracks:
        reason = _check_soft(track, include_map, exclude_map, dur_params, year_params)
        if reason:
            excluded.append({"id": track["music_id"], "reason": reason})
        else:
            eligible.append(track)

    logger.info(
        "soft_filter: %d eligible, %d excluded",
        len(eligible), len(excluded),
    )
    return eligible, excluded


def _check_soft(
    track: dict,
    include_map: dict[int, set],
    exclude_map: dict[int, set],
    dur_params: dict,
    year_params: dict,
) -> str | None:
    """Vrátí důvod vyřazení nebo None pokud track prošel."""
    chars = track["chars_by_cat"]  # {category_id: [char_id, …]}

    for cat_id, inc_set in include_map.items():
        if not (set(chars.get(cat_id, [])) & inc_set):
            return f"cat_{cat_id}_mismatch"

    for cat_id, exc_set in exclude_map.items():
        if set(chars.get(cat_id, [])) & exc_set:
            return f"cat_{cat_id}_excluded"

    # Délka (net_duration = outro - intro)
    dur = track.get("net_duration") or track.get("duration", 0)
    if dur < dur_params.get("min", 0):
        return "too_short"
    if dur > dur_params.get("max", 9999):
        return "too_long"

    # Rok
    year = track.get("year")
    if year:
        if year < year_params.get("min", 0):
            return "year_too_old"
        if year > year_params.get("max", 9999):
            return "year_too_new"

    return None

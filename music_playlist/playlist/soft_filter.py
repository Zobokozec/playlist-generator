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
from collections import Counter
from typing import Callable

logger = logging.getLogger(__name__)


def _make_checker(params: dict) -> Callable[[dict], str | None]:
    """Sestaví checker funkci s uzavřenými předzpracovanými parametry."""
    # include_map: {cat_id: set}
    #   - neprázdná množina → track MUSÍ mít alespoň jednu z nich (jen pokud má danou kategorii)
    #   - None             → track NESMÍ mít tuto kategorii vůbec (exclude_all)
    include_map: dict[int, set | None] = {}
    exclude_map: dict[int, set] = {}
    for cat_id, rules in params.get("chars", {}).items():
        cid = int(cat_id)
        raw_inc = rules.get("include") if rules else None
        if raw_inc is None and "include" in (rules or {}):
            include_map[cid] = None          # include: null → exclude celou kategorii
        elif raw_inc:
            include_map[cid] = set(raw_inc)
        raw_exc = rules.get("exclude") if rules else None
        if raw_exc:
            exclude_map[cid] = set(raw_exc)

    dur_min = params.get("duration", {}).get("min", 0)
    dur_max = params.get("duration", {}).get("max", 9999)
    year_min = params.get("year", {}).get("min", 0)
    year_max = params.get("year", {}).get("max", 9999)

    def check(track: dict) -> str | None:
        chars = track["chars_by_cat"]

        for cat_id, inc_set in include_map.items():
            track_chars = set(chars.get(cat_id, []))
            if inc_set is None:
                # include: null → vyřadit tracky které mají tuto kategorii
                if track_chars:
                    return f"cat_{cat_id}_excluded_all"
            elif track_chars and not (track_chars & inc_set):
                # include: [ids] → pokud má kategorii, musí matchovat
                return f"cat_{cat_id}_mismatch"

        for cat_id, exc_set in exclude_map.items():
            if set(chars.get(cat_id, [])) & exc_set:
                return f"cat_{cat_id}_excluded"

        dur = track.get("net_duration") or track.get("duration", 0)
        if dur < dur_min:
            return "too_short"
        if dur > dur_max:
            return "too_long"

        year = track.get("year")
        if year:
            if year < year_min:
                return "year_too_old"
            if year > year_max:
                return "year_too_new"

        return None

    return check


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
    check = _make_checker(params)
    eligible: list[dict] = []
    excluded: list[dict] = []

    for track in tracks:
        reason = check(track)
        if reason:
            excluded.append({"id": track["music_id"], "reason": reason})
        else:
            eligible.append(track)

    if logger.isEnabledFor(logging.DEBUG) and excluded:
        reasons = Counter(e["reason"] for e in excluded)
        logger.debug("soft_filter důvody: %s", dict(reasons))

    logger.info("soft_filter: %d eligible, %d excluded", len(eligible), len(excluded))
    return eligible, excluded

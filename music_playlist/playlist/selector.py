"""
Selector – weighted random výběr tracků podle procentuálních kvót.

Algoritmus:
    1. Roztřídí tracky do bucketů {char_id: [track, ...]}
    2. Iteruje dokud není dosažena target_duration
    3. Vybírá char_id váhově podle shortfall (kolik % ještě chybí)
    4. Z bucketu vybírá náhodný track (bez opakování)
"""
from __future__ import annotations

import logging
import random
from collections import defaultdict

logger = logging.getLogger(__name__)


def select_tracks(
    tracks: list[dict],
    quotas: dict,
    target_duration: float,
) -> list[dict]:
    """Vybere tracky do playlistu podle procentuálních kvót.

    Args:
        tracks:          Tracky po cooldownu (eligible pool).
        quotas:          Kvóty jako {category_id: {char_id: pct_float}}.
                         pct_float: 0.0–1.0 nebo 0–100 (normalizuje se).
                         Např.: {3: {12: 0.40, 15: 0.40}, 5: {45: 0.60}}
        target_duration: Cílová délka v sekundách.

    Returns:
        Seřazený seznam vybraných tracků (pořadí výběru).
    """
    if not tracks:
        return []

    # Normalizace kvót (procenta → float 0–1)
    flat_quotas: dict[int, float] = {}
    for cat_quotas in quotas.values():
        for char_id, pct in cat_quotas.items():
            char_id = int(char_id)
            pct_f = float(pct) / 100.0 if float(pct) > 1.0 else float(pct)
            flat_quotas[char_id] = pct_f

    if not flat_quotas:
        logger.warning("select_tracks: prázdné kvóty, vybírám náhodně")
        pool = list(tracks)
        random.shuffle(pool)
        result, total = [], 0.0
        for t in pool:
            result.append(t)
            total += t.get("net_duration") or t.get("duration", 0)
            if total >= target_duration:
                break
        return result

    # Buckety {char_id: [track, ...]}
    buckets: dict[int, list[dict]] = defaultdict(list)
    for track in tracks:
        for char_ids in track["chars_by_cat"].values():
            for char_id in char_ids:
                if char_id in flat_quotas:
                    buckets[char_id].append(track)

    filled_duration: dict[int, float] = defaultdict(float)
    selected_ids: set[int] = set()
    playlist: list[dict] = []
    total_duration = 0.0
    active_quotas = dict(flat_quotas)

    max_iterations = len(tracks) * 3 + 100
    iteration = 0

    while total_duration < target_duration and iteration < max_iterations:
        iteration += 1
        remaining = target_duration - total_duration

        # Shortfall per char_id
        needs = {
            cid: max(0.0, target_duration * pct - filled_duration[cid])
            for cid, pct in active_quotas.items()
        }
        if not any(needs.values()):
            break

        # Weighted random výběr char_id podle shortfall
        char_ids = list(needs.keys())
        weights = [needs[c] for c in char_ids]
        chosen_char_id = random.choices(char_ids, weights=weights)[0]

        # Dostupné tracky v bucketu (mimo již vybrané)
        available = [
            t for t in buckets.get(chosen_char_id, [])
            if t["music_id"] not in selected_ids
        ]
        if not available:
            del active_quotas[chosen_char_id]
            if not active_quotas:
                break
            continue

        track = random.choice(available)
        dur = track.get("net_duration") or track.get("duration", 0)

        playlist.append(track)
        selected_ids.add(track["music_id"])
        total_duration += dur

        # Aktualizuj filled pro všechny char_id trackku
        for char_ids_in_cat in track["chars_by_cat"].values():
            for cid in char_ids_in_cat:
                if cid in filled_duration:
                    filled_duration[cid] += dur
                elif cid in flat_quotas:
                    filled_duration[cid] = dur

    logger.info(
        "select_tracks: vybráno %d tracků, celková délka %.0fs (target %.0fs)",
        len(playlist), total_duration, target_duration,
    )
    return playlist

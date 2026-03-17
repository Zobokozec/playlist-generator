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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cooldown import InSessionCooldown

logger = logging.getLogger(__name__)


def select_tracks(
    tracks: list[dict],
    quotas: dict,
    target_duration: float,
    max_iterations: int = 10_000,
    session_cooldown: "InSessionCooldown | None" = None,
) -> list[dict]:
    """Vybere tracky do playlistu podle procentuálních kvót.

    Args:
        tracks:           Tracky po cooldownu (eligible pool).
        quotas:           Kvóty jako {category_id: {char_id: pct_float}}.
                          pct_float: 0.0–1.0 nebo 0–100 (normalizuje se).
                          Např.: {3: {12: 0.40, 15: 0.40}, 5: {45: 0.60}}
        target_duration:  Cílová délka v sekundách.
        max_iterations:   Maximální počet iterací (bezpečnostní pojistka).
        session_cooldown: Volitelný InSessionCooldown – blokuje opakování artistů/alb
                          v rámci jednoho playlistu na základě virtuálního časového čítače.

    Returns:
        Seřazený seznam vybraných tracků (pořadí výběru).
    """
    if not tracks:
        return []

    # Normalizace kvót per kategorie (procenta → float 0–1)
    # Klíč -cat_id rezervován pro bucket "ostatní" dané kategorie.
    flat_quotas: dict[int, float] = {}
    others_cats: dict[int, set[int]] = {}   # cat_id → sada char_id které PATŘÍ do kvót

    for cat_id, cat_quotas in quotas.items():
        cat_id = int(cat_id)
        normalized: dict[int, float] = {}
        for char_id, pct in cat_quotas.items():
            pct_f = float(pct) / 100.0 if float(pct) > 1.0 else float(pct)
            normalized[int(char_id)] = pct_f

        total = sum(normalized.values())
        if total > 1.001:
            # Součet > 100 % → přepočítej proporcionálně
            normalized = {cid: p / total for cid, p in normalized.items()}
            total = 1.0

        flat_quotas.update(normalized)
        others_cats[cat_id] = set(normalized.keys())

        others_pct = 1.0 - total
        if others_pct > 0.001:
            flat_quotas[-cat_id] = others_pct  # záporný klíč = "ostatní pro tuto kategorii"

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
    # Pro záporný klíč -cat_id: tracky které mají v cat_id char MIMO definované kvóty.
    buckets: dict[int, list[dict]] = defaultdict(list)
    for track in tracks:
        chars_by_cat = track["chars_by_cat"]
        for char_id in (c for cat_chars in chars_by_cat.values() for c in cat_chars):
            if char_id in flat_quotas:
                buckets[char_id].append(track)
        for cat_id, defined_chars in others_cats.items():
            if -cat_id in flat_quotas:
                track_chars = set(chars_by_cat.get(cat_id, []))
                if track_chars and not (track_chars & defined_chars):
                    buckets[-cat_id].append(track)

    filled_duration: dict[int, float] = defaultdict(float)
    selected_ids: set[int] = set()
    playlist: list[dict] = []
    total_duration = 0.0
    active_quotas = dict(flat_quotas)

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

        # Dostupné tracky v bucketu (mimo již vybrané, mimo session cooldown)
        bucket = buckets.get(chosen_char_id, [])
        not_selected = [t for t in bucket if t["music_id"] not in selected_ids]
        if not not_selected:
            # Bucket skutečně vyčerpán – odstraň kvótu
            del active_quotas[chosen_char_id]
            if not active_quotas:
                break
            continue

        if session_cooldown is not None:
            available = [t for t in not_selected if not session_cooldown.is_blocked(t)]
        else:
            available = not_selected

        if not available:
            # Bucket není prázdný, ale vše je dočasně blokováno session cooldownem –
            # přeskoč tuto iteraci, jiný char_id může být dostupný.
            continue

        track = random.choice(available)
        dur = track.get("net_duration") or track.get("duration", 0)

        playlist.append(track)
        selected_ids.add(track["music_id"])
        total_duration += dur
        if session_cooldown is not None:
            session_cooldown.register(track, dur)

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

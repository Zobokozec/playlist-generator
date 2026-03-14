"""
Validator – finální validace vybraných tracků.

Zkontroluje existence souboru; pokud track vypadne, hledá náhradu
z celého zbývajícího poolu (ne jen ze stejné kategorie).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def validate_selected(
    playlist: list[dict],
    pool: list[dict],
    selected_ids: set[int] | None = None,
) -> list[dict]:
    """Validuje soubory vybraných tracků a hledá náhrady.

    Args:
        playlist:     Tracky vybrané selektorem.
        pool:         Celý eligible pool (po cooldownu) pro fallback náhrady.
        selected_ids: Set music_id již vybraných (aktualizuje se in-place).

    Returns:
        Validovaný seznam tracků (s náhradami kde bylo třeba).
    """
    if selected_ids is None:
        selected_ids = {t["music_id"] for t in playlist}

    validated: list[dict] = []
    need_replace: list[int] = []

    for track in playlist:
        if track.get("file_exists") and track.get("file_path"):
            validated.append(track)
        else:
            need_replace.append(track["music_id"])
            logger.warning(
                "validate_selected: track %d nemá soubor (%s)",
                track["music_id"], track.get("file_path"),
            )

    if not need_replace:
        return validated

    # Fallback pool – celý zbývající pool mimo již vybrané
    fallback_pool = [
        t for t in pool
        if t["music_id"] not in selected_ids
        and t.get("file_exists")
        and t.get("file_path")
    ]

    for missing_id in need_replace:
        if not fallback_pool:
            logger.warning(
                "validate_selected: nelze najít náhradu za track %d – vynecháno",
                missing_id,
            )
            continue
        replacement = fallback_pool.pop(0)
        validated.append(replacement)
        selected_ids.add(replacement["music_id"])
        logger.info(
            "validate_selected: track %d nahrazen trackem %d",
            missing_id, replacement["music_id"],
        )

    return validated

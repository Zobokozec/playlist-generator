"""
Enrich – rozbalení raw DB řádků a doplnění dat z SQLite file_cache.

Vstup:  raw řádky z hard_filter (entity a chars_ids jsou stringy)
Výstup: obohatené dicts s entity_ids, chars_by_cat, net_duration, file_path, …

Důležité:
    - Batch dotaz na file_cache (jeden dotaz, ne per-track)
    - net_duration = outro_sec - intro_sec  (ne celý soubor)
    - ISRC se předává beze změny – normalizace je úkolem music-validator
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import PlaylistContext

logger = logging.getLogger(__name__)


def enrich_tracks(rows: list[dict], context: "PlaylistContext") -> list[dict]:
    """Obohatí raw řádky z hard_filter o data ze SQLite a rozbalené struktury.

    Args:
        rows:    Výstup hard_filter – surové řádky z MariaDB.
        context: PlaylistContext s přístupem k musicdb.

    Returns:
        Seznam obohacených dict tracků.
    """
    if not rows:
        return []

    # Batch dotaz do SQLite (jeden dotaz pro všechny tracks)
    ids = [r["music_id"] for r in rows]
    placeholders = ",".join("?" * len(ids))
    file_data: dict[int, dict] = {
        r["track_id"]: r
        for r in context.musicdb.dotaz_dict(
            f"SELECT track_id, file_path, file_dur_sec, intro_sec, outro_sec, file_exists "
            f"FROM file_cache WHERE track_id IN ({placeholders})",
            ids,
        )
    }
    logger.debug(
        "enrich_tracks: %d tracků, %d záznamů v file_cache",
        len(rows), len(file_data),
    )

    result = []
    for row in rows:
        mid = row["music_id"]

        # Entity: '[81,93]' → [81, 93]
        entity_ids = _parse_ids(row.get("entity", "").strip("[]"))

        # Chars: '{12:3,45:3,88:7}' → {category_id: [char_id, ...]}
        chars_by_cat: dict[int, list[int]] = {}
        raw_chars = row.get("chars_ids", "").strip("{}")
        for pair in raw_chars.split(","):
            pair = pair.strip()
            if ":" not in pair:
                continue
            cid_s, cat_s = pair.split(":", 1)
            try:
                cid, cat_id = int(cid_s), int(cat_s)
                chars_by_cat.setdefault(cat_id, []).append(cid)
            except ValueError:
                continue

        # Doplnění z file_cache
        fc = file_data.get(mid, {})
        intro = fc.get("intro_sec") or 0.0
        raw_outro = fc.get("outro_sec")
        if raw_outro is None and fc:
            logger.warning(
                "enrich_tracks: track %d nemá outro_sec v file_cache, fallback na duration (%ds)",
                mid, row["duration"],
            )
        outro = raw_outro if raw_outro is not None else row["duration"]
        net_dur = round(float(outro) - float(intro), 2)

        result.append({
            **row,
            "entity_ids":   entity_ids,
            "chars_by_cat": chars_by_cat,     # {category_id: [char_id, …]}
            "file_path":    fc.get("file_path"),
            "file_exists":  bool(fc.get("file_exists", False)),
            "intro_sec":    fc.get("intro_sec"),
            "outro_sec":    fc.get("outro_sec"),
            "net_duration": net_dur,
        })

    return result


def _parse_ids(s: str) -> list[int]:
    """'81,93,100' → [81, 93, 100]"""
    if not s:
        return []
    return [int(x.strip()) for x in s.split(",") if x.strip().lstrip("-").isdigit()]

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

    # Sestav NOT IN z configu (duplicity k ručnímu odstranění)
    excluded = context.config.EXCLUDED_MUSIC_IDS
    excl_clause = ""
    if excluded:
        excl_placeholders = ",".join(f'"H{mid:06d}"' for mid in excluded)
        excl_clause = f" AND externalid NOT IN ({excl_placeholders})"

    # Načti items z musicdb; externalid "H032868" → music_id 32868
    # TODO: intro_sec a outro_sec jsou v jiné tabulce – doplnit join
    raw_items = context.musicdb.dotaz_dict(
        f'SELECT externalid, filename AS file_path, duration AS file_dur_sec, '
        f'ic_in.value AS intro_sec, ic_out.value AS outro_sec, 1 AS file_exists '
        f'FROM items '
        f'LEFT JOIN item_cuemarkers ic_in  ON ic_in.item  = items.idx AND ic_in.type  = "CueIn" '
        f'LEFT JOIN item_cuemarkers ic_out ON ic_out.item = items.idx AND ic_out.type = "CueOut" '
        f'WHERE externalid IS NOT NULL AND items.type = "Music"{excl_clause}'
    )
    file_data: dict[int, dict] = {}
    for r in raw_items:
        ext = r.get("externalid", "")
        if ext and ext.startswith("H"):
            try:
                music_id = int(ext[1:])
                file_data[music_id] = r
            except ValueError:
                pass
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
                cat_list = chars_by_cat.setdefault(cat_id, [])
                if cid not in cat_list:
                    cat_list.append(cid)
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
            "file_dur_sec": fc.get("file_dur_sec"),
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

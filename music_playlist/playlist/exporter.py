"""
Exporter – uložení playlistu do playlist.db, JSON výstup a volání xml_exporter.

Výstupní formáty:
    'ids'   → [42, 107, 203]
    'full'  → [{id, duration, net_duration, file_path, intro_sec, outro_sec, chars}, ...]
    'debug' → {playlist: [...], excluded: {reason: [ids]}, stats: {...}}
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import PlaylistContext

logger = logging.getLogger(__name__)


@dataclass
class GeneratorResult:
    """Výsledek generování playlistu."""
    playlist_id: int
    selected: list[dict]
    excluded: dict          # {'lang_mismatch': [music_id, ...], ...}
    stats: dict = field(default_factory=lambda: {
        "total_candidates":  0,
        "after_hard_filter": 0,
        "after_soft_filter": 0,
        "after_cooldown":    0,
        "selected":          0,
        "total_duration":    0.0,
    })


def export_playlist(
    result: GeneratorResult,
    context: "PlaylistContext",
    params: dict,
    output_format: str = "full",
    dry_run: bool = False,
) -> dict | list:
    """Uloží playlist a vrátí výstup v požadovaném formátu.

    Args:
        result:        GeneratorResult ze pipeline.
        context:       PlaylistContext pro přístup k DB.
        params:        Původní parametry generování (scheduled_start, duration_sec, …).
        output_format: 'ids' | 'full' | 'debug'
        dry_run:       Pokud True, nic neukládá do DB.

    Returns:
        JSON-serializovatelný výstup dle output_format.
    """
    selected = result.selected

    if not dry_run:
        _save_to_db(result, context, params)
        _export_xml(result, context, params)

    return _format_output(selected, result, context, output_format)


# ------------------------------------------------------------------
# Interní funkce
# ------------------------------------------------------------------

def _save_to_db(
    result: GeneratorResult,
    context: "PlaylistContext",
    params: dict,
) -> None:
    """Uloží playlist do playlist.db."""
    db = context.playlistdb
    scheduled_start = params.get("scheduled_start")
    if isinstance(scheduled_start, str):
        scheduled_start = datetime.fromisoformat(scheduled_start)

    config_json = json.dumps(params.get("quotas", {}), ensure_ascii=False)
    total_duration = sum(
        t.get("net_duration") or t.get("duration", 0)
        for t in result.selected
    )

    # Uložit playlist
    db.execute("""
        UPDATE playlists
        SET status = 'ready', total_tracks = ?, actual_duration = ?
        WHERE id = ?
    """, (len(result.selected), int(total_duration), result.playlist_id))

    # Uložit do history
    for track in result.selected:
        entity_ids_str = ",".join(str(e) for e in track.get("entity_ids", []))
        db.execute("""
            INSERT OR IGNORE INTO playlist_history
                (playlist_id, track_id, album_id, artist_ids, scheduled_start)
            VALUES (?, ?, ?, ?, ?)
        """, (
            result.playlist_id,
            track["music_id"],
            track["album_id"],
            entity_ids_str,
            scheduled_start.isoformat() if hasattr(scheduled_start, "isoformat") else scheduled_start,
        ))
        # Uložit album_info pokud neexistuje
        album_id = track["album_id"]
        album_info = context.album_map.get(album_id, {})
        db.execute("""
            INSERT OR IGNORE INTO album_info (album_id, track_count, album_type)
            VALUES (?, ?, ?)
        """, (
            album_id,
            album_info.get("track_count", 0),
            album_info.get("album_type", "full"),
        ))

    db.commit()
    logger.info("export: playlist #%d uložen (%d tracků)", result.playlist_id, len(result.selected))


def _export_xml(
    result: GeneratorResult,
    context: "PlaylistContext",
    params: dict,
) -> None:
    """Volá xml_exporter (stub – bude implementován externím modulem)."""
    # xml_exporter bude implementován jako samostatný modul
    # from music_xml_exporter import XMLExporter
    # exporter = XMLExporter()
    # exporter.export_by_ids([t['music_id'] for t in result.selected], path)
    logger.info("export: XML export – volání xml_exporter (stub)")


def _format_output(
    selected: list[dict],
    result: GeneratorResult,
    context: "PlaylistContext",
    fmt: str,
) -> dict | list:
    """Formátuje výstup dle požadovaného formátu."""
    if fmt == "ids":
        return [t["music_id"] for t in selected]

    if fmt == "full":
        return [_track_full(t, context) for t in selected]

    if fmt == "debug":
        return {
            "playlist": [_track_full(t, context) for t in selected],
            "excluded": result.excluded,
            "stats":    result.stats,
        }

    raise ValueError(f"Neznámý output_format: {fmt!r}. Platné: 'ids', 'full', 'debug'")


def _track_full(track: dict, context: "PlaylistContext") -> dict:
    """Sestaví 'full' výstupní dict pro track."""
    chars_named = {
        context.char_map.get(cid, {}).get("name", str(cid)): cid
        for char_ids in track.get("chars_by_cat", {}).values()
        for cid in char_ids
    }
    return {
        "id":           track["music_id"],
        "album_id":     track["album_id"],
        "duration":     track.get("duration"),
        "net_duration": track.get("net_duration"),
        "file_path":    track.get("file_path"),
        "intro_sec":    track.get("intro_sec"),
        "outro_sec":    track.get("outro_sec"),
        "year":         track.get("year"),
        "isrc":         track.get("isrc"),
        "entities":     [context.entity_name(e) for e in track.get("entity_ids", [])],
        "chars":        chars_named,
    }

"""
Exporter – uložení playlistu do playlist.db, XML export a JSON výstup.

XML export:
    Volá xmlplaylist.export_to_xml() pro každý track v playlistu.
    Potřebná metadata (title, album, pronunciation, …) se načítají
    batch dotazem z twar a kombinují s char_map z PlaylistContext.

Výstupní formáty JSON:
    'ids'   → [42, 107, 203]
    'full'  → [{id, duration, net_duration, file_path, ...}, ...]
    'debug' → {playlist: [...], excluded: {reason: [ids]}, stats: {...}}
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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
    validation: list = field(default_factory=list)  # seznam TrackValidation z run_validation()


def export_playlist(
    result: GeneratorResult,
    context: "PlaylistContext",
    params: dict,
    output_format: str = "full",
    dry_run: bool = False,
) -> dict | list:
    """Spustí validaci, uloží playlist do DB, exportuje XML a vrátí výstup.

    Pořadí kroků:
        1. run_validation() – validate_all() z music-utils pro každý track
        2. _save_to_db()    – playlist, history, výsledky validace
        3. _export_xml()    – MLP soubor přes xmlplaylist

    Args:
        result:        GeneratorResult ze pipeline.
        context:       PlaylistContext pro přístup k DB a lookup mapám.
        params:        Původní parametry generování (scheduled_start, preset, …).
        output_format: 'ids' | 'full' | 'debug'
        dry_run:       Pokud True, nic neukládá do DB ani na disk.

    Returns:
        JSON-serializovatelný výstup dle output_format.
    """
    from .validator import run_validation

    # Validace vždy (i při dry_run) – výsledky jsou součástí GeneratorResult
    result.validation = run_validation(result.selected, context)

    if not dry_run:
        _save_to_db(result, context, params)
        _export_xml(result, context, params)

    return _format_output(result.selected, result, context, output_format)


# ------------------------------------------------------------------
# DB uložení
# ------------------------------------------------------------------

def _save_to_db(
    result: GeneratorResult,
    context: "PlaylistContext",
    params: dict,
) -> None:
    """Uloží status playlistu a playlist_history do playlist.db."""
    db = context.playlistdb
    scheduled_start = params.get("scheduled_start")
    if isinstance(scheduled_start, str):
        scheduled_start = datetime.fromisoformat(scheduled_start)

    total_duration = sum(
        t.get("net_duration") or t.get("duration", 0)
        for t in result.selected
    )

    # Aktualizuj status na 'ready'
    db.execute("""
        UPDATE playlists
        SET status = 'ready', total_tracks = ?, actual_duration = ?
        WHERE id = ?
    """, (len(result.selected), int(total_duration), result.playlist_id))

    # Uložit každý track do history (pro cooldown)
    start_iso = (
        scheduled_start.isoformat()
        if hasattr(scheduled_start, "isoformat")
        else str(scheduled_start)
    )
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
            start_iso,
        ))

        # album_info pro cooldown album filtr
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

    # Validační výsledky do track_validation + track_validation_checks
    if result.validation:
        from .db import save_validation_results
        validated_at = (
            scheduled_start.isoformat()
            if hasattr(scheduled_start, "isoformat")
            else str(scheduled_start)
        )
        save_validation_results(db, result.playlist_id, result.validation, validated_at)

    logger.info("export: playlist #%d uložen (%d tracků)", result.playlist_id, len(result.selected))


# ------------------------------------------------------------------
# XML export přes xmlplaylist
# ------------------------------------------------------------------

def _export_xml(
    result: GeneratorResult,
    context: "PlaylistContext",
    params: dict,
) -> str | None:
    """Exportuje playlist do MLP souboru přes xmlplaylist.export_to_xml().

    Pro každý track zavolá export_to_xml(mlp_path, track_dict).
    Metadata (title, album, pronunciation, description) se načítají
    batch dotazem z twar. Charakteristiky se mapují přes char_map.

    Returns:
        Absolutní cesta k MLP souboru nebo None při chybě.
    """
    try:
        from xmlplaylist import export_to_xml
    except ImportError:
        logger.error(
            "export: modul xmlplaylist není dostupný – XML export přeskočen. "
            "Nainstalujte: pip install xmlplaylist"
        )
        return None

    selected = result.selected
    if not selected:
        logger.warning("export: prázdný playlist, XML se negeneruje")
        return None

    # --- MLP cesta: exports_dir/YYYY_MM_DD/YYYY_MM_DD_(preset).mlp ---
    scheduled_start = params.get("scheduled_start", "")
    if isinstance(scheduled_start, str):
        from datetime import datetime as _dt
        scheduled_start = _dt.fromisoformat(scheduled_start)
    date_str = scheduled_start.strftime("%Y_%m_%d") if hasattr(scheduled_start, "strftime") else "unknown"
    preset = params.get("preset", "playlist")
    day_dir = Path(context.config.EXPORTS_DIR) / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    mlp_path = str(day_dir / f"{date_str}_{preset}.mlp")

    # --- Sestav seznam tracků a exportuj najednou ---
    track_dicts = [_build_track_export_dict(t, context) for t in selected]
    try:
        export_path = export_to_xml(
            mlp_path,
            track_dicts,
            prepis=True,
            config={"music_root": context.config.MUSIC_ROOT_DIR},
            comment_log=f"{mlp_path}.json"
        )
    except Exception as exc:
        logger.error("export: chyba XML exportu: %s", exc)
        return None

    logger.info("export: XML exportován → %s (%d tracků)", mlp_path, len(selected))
    return str(export_path)


def _build_track_export_dict(
    track: dict,
    context: "PlaylistContext",
) -> dict:
    """Sestaví dict pro xmlplaylist.export_to_xml() z enriched tracku.

    Metadata (title, pronunciation, description) jsou přímo v tracku z hard filteru.
    Mapování charakteristik z char_map:
        category "Jazyk"            → language  (string, první hodnota)
        category "Tempo"            → tempo     (string, první hodnota)
        category "Žánr" / "Styl"    → style     (list stringů)
        ostatní kategorie           → keywords  (list stringů)
    """
    # Jméno a výslovnost interpreta/ů z entity_map
    artist_names = [context.entity_name(eid) for eid in track.get("entity_ids", [])]
    artist = ", ".join(artist_names) if artist_names else ""
    artist_pronunciation = ", ".join(
        context.entity_map.get(eid, {}).get("pronunciation", "")
        for eid in track.get("entity_ids", [])
        if context.entity_map.get(eid, {}).get("pronunciation")
    )

    cat_language = context.config.CAT_ID_LANGUAGE
    cat_style    = context.config.CAT_ID_STYLE

    language: str = ""
    style: list[str] = []
    keywords: list[str] = []

    for cat_id, char_ids in track.get("chars_by_cat", {}).items():
        for cid in char_ids:
            char_name = context.char_map.get(cid, {}).get("name", str(cid))
            if cat_id == cat_language:
                if not language:
                    language = char_name
            elif cat_id == cat_style:
                style.append(char_name)
            else:
                keywords.append(char_name)

    # Přidej explicitní keywords z DB (z hard filteru)
    keywords.extend(track.get("keywords") or [])

    mid = track["music_id"]
    chars = {
        "language": language,
        "style":    style,
        "keywords": keywords,
    }
    return {
        # Identifikace
        "idx":                  track.get("db_idx") or mid,
        "externalid":           f"H{mid:06d}",
        "type":                 "Music",
        # Základní metadata
        "title":                track.get("title") or "",
        "artist":               artist,
        "pronunciation":        track.get("pronunciation") or "",
        "artist_pronunciation": artist_pronunciation,
        "year":                 track.get("year"),
        "album":                context.album_map.get(track.get("album_id", 0), {}).get("name", ""),
        "description":          track.get("description") or "",
        # Technická data
        "duration":             track.get("net_duration") or track.get("duration") or 0.0,
        "filename":             track.get("file_path") or "",
        # Charakteristiky – top-level i vnořené
        "language":             language,
        "style":                style,
        "keywords":             keywords,
        "chars":                chars,
    }


# ------------------------------------------------------------------
# JSON formátování výstupu
# ------------------------------------------------------------------

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
    mid = track["music_id"]
    album = context.album_map.get(track.get("album_id", 0), {})
    artist_names = [context.entity_name(e) for e in track.get("entity_ids", [])]
    artist_pronunciation = ", ".join(
        context.entity_map.get(eid, {}).get("pronunciation", "")
        for eid in track.get("entity_ids", [])
        if context.entity_map.get(eid, {}).get("pronunciation")
    )
    chars_named = {
        context.char_map.get(cid, {}).get("name", str(cid)): cid
        for char_ids in track.get("chars_by_cat", {}).values()
        for cid in char_ids
    }
    return {
        "id":                   mid,
        "idx":                  track.get("db_idx") or mid,
        "externalid":           f"H{mid:06d}",
        "title":                track.get("title") or "",
        "pronunciation":        track.get("pronunciation") or "",
        "artist":               ", ".join(artist_names),
        "artist_pronunciation": artist_pronunciation,
        "album":                album.get("name") or "",
        "year":                 track.get("year"),
        "description":          track.get("description") or "",
        "isrc":                 track.get("isrc"),
        "duration":             track.get("duration"),
        "net_duration":         track.get("net_duration"),
        "intro_sec":            track.get("intro_sec"),
        "outro_sec":            track.get("outro_sec"),
        "file_path":            track.get("file_path"),
        "chars":                chars_named,
    }

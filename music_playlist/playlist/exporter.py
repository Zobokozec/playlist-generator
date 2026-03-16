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

# SQL pro batch načtení exportních metadat z twar
_EXPORT_META_SQL = """
SELECT
    m.id            AS music_id,
    m.name          AS title,
    m.pronunciation,
    m.description,
    a.name          AS album_name
FROM music m
LEFT JOIN albums a ON m.album = a.id
WHERE m.id IN ({placeholders})
"""

# SQL pro pronunciation entit (interpretů) – volitelné
_ENTITY_META_SQL = """
SELECT id, name, pronunciation
FROM entities
WHERE id IN ({placeholders})
"""


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

    # --- Batch dotaz: exportní metadata z twar ---
    meta_by_id = _fetch_export_metadata(selected, context)

    # --- MLP cesta ---
    scheduled_start = params.get("scheduled_start", "")
    if hasattr(scheduled_start, "strftime"):
        ts = scheduled_start.strftime("%Y-%m-%d_%H%M")
    else:
        ts = str(scheduled_start).replace(":", "").replace(" ", "_")[:16]
    preset = params.get("preset", "playlist")
    filename = f"{ts}_{preset}.mlp"
    exports_dir = Path(context.config.EXPORTS_DIR)
    exports_dir.mkdir(parents=True, exist_ok=True)
    mlp_path = str(exports_dir / filename)

    # --- Export per track ---
    export_path = None
    for track in selected:
        track_dict = _build_track_export_dict(track, meta_by_id, context)
        try:
            export_path = export_to_xml(mlp_path, track_dict)
        except Exception as exc:
            logger.error(
                "export: chyba při exportu tracku %d: %s",
                track["music_id"], exc,
            )

    logger.info("export: XML exportován → %s (%d tracků)", mlp_path, len(selected))
    return export_path


def _fetch_export_metadata(
    selected: list[dict],
    context: "PlaylistContext",
) -> dict[int, dict]:
    """Batch dotaz na twar pro exportní metadata (title, album, pronunciation, description).

    Args:
        selected: Vybrané tracky.
        context:  PlaylistContext s přístupem k twar a entity_map.

    Returns:
        {music_id: {title, album_name, pronunciation, description,
                    artist_pronunciation}}
    """
    music_ids = [t["music_id"] for t in selected]
    placeholders = ",".join(["%s"] * len(music_ids))

    try:
        rows = context.twar.dotaz_dict(
            _EXPORT_META_SQL.format(placeholders=placeholders),
            music_ids,
        )
    except Exception as exc:
        logger.warning("export: nelze načíst metadata z twar: %s", exc)
        rows = []

    music_meta = {r["music_id"]: r for r in rows}

    # Entity pronunciations – batch dotaz na entities
    all_entity_ids = list({
        eid
        for t in selected
        for eid in t.get("entity_ids", [])
    })
    entity_pronunciation: dict[int, str] = {}
    if all_entity_ids:
        ph = ",".join(["%s"] * len(all_entity_ids))
        try:
            ent_rows = context.twar.dotaz_dict(
                _ENTITY_META_SQL.format(placeholders=ph),
                all_entity_ids,
            )
            entity_pronunciation = {
                r["id"]: r.get("pronunciation", "") or ""
                for r in ent_rows
            }
        except Exception as exc:
            logger.warning("export: nelze načíst entity pronunciation: %s", exc)

    # Sloučení: přidej artist_pronunciation do každého záznamu
    for t in selected:
        mid = t["music_id"]
        entity_ids = t.get("entity_ids", [])
        pronunciations = [
            entity_pronunciation[eid]
            for eid in entity_ids
            if entity_pronunciation.get(eid)
        ]
        if mid in music_meta:
            music_meta[mid]["artist_pronunciation"] = ", ".join(pronunciations)

    return music_meta


def _build_track_export_dict(
    track: dict,
    meta_by_id: dict[int, dict],
    context: "PlaylistContext",
) -> dict:
    """Sestaví dict pro xmlplaylist.export_to_xml() z enriched tracku a metadat.

    Mapování charakteristik z char_map:
        category "Jazyk"            → language  (string, první hodnota)
        category "Tempo"            → tempo     (string, první hodnota)
        category "Žánr" / "Styl"    → style     (list stringů)
        ostatní kategorie           → keywords  (list stringů)

    Args:
        track:      Enriched track dict.
        meta_by_id: Výstup _fetch_export_metadata.
        context:    PlaylistContext pro char_map a entity_map.

    Returns:
        Dict kompatibilní s xmlplaylist.export_to_xml().
    """
    mid = track["music_id"]
    meta = meta_by_id.get(mid, {})

    # Jméno interpreta/ů z entity_map
    artist_names = [
        context.entity_name(eid)
        for eid in track.get("entity_ids", [])
    ]
    artist = ", ".join(artist_names) if artist_names else ""

    # Mapování charakteristik podle kategorie
    language: str = ""
    tempo: str = ""
    style: list[str] = []
    keywords: list[str] = []

    for cat_id, char_ids in track.get("chars_by_cat", {}).items():
        for cid in char_ids:
            info = context.char_map.get(cid, {})
            char_name = info.get("name", str(cid))
            cat_name = info.get("category", "").lower()

            if "jazyk" in cat_name or "language" in cat_name:
                if not language:
                    language = char_name
            elif "tempo" in cat_name:
                if not tempo:
                    tempo = char_name
            elif "žánr" in cat_name or "zanr" in cat_name or "styl" in cat_name or "style" in cat_name:
                style.append(char_name)
            else:
                keywords.append(char_name)

    return {
        "title":                meta.get("title") or "",
        "artist":               artist,
        "pronunciation":        meta.get("pronunciation") or "",
        "artist_pronunciation": meta.get("artist_pronunciation") or "",
        "year":                 track.get("year"),
        "album":                meta.get("album_name") or "",
        "description":          meta.get("description") or "",
        "language":             language,
        "tempo":                tempo,
        "style":                style,
        "keywords":             keywords,
        "duration":             track.get("net_duration") or track.get("duration") or 0.0,
        "filename":             track.get("file_path") or "",
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

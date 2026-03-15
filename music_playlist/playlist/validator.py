"""
Validator – finální validace vybraných tracků.

Dvě funkce:

validate_selected()
    Zkontroluje existence souboru; pokud track vypadne, hledá náhradu
    z celého zbývajícího poolu (ne jen ze stejné kategorie).

run_validation()
    Spustí úplnou validaci (music-utils validate_all) pro každý track
    ve finálním playlistu. Vrací seznam TrackValidation objektů vhodných
    pro uložení do track_validation / track_validation_checks v SQLite.
    Volá se PO validate_selected(), tedy nad finálním sestavem tracků.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import PlaylistContext

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


def run_validation(
    playlist: list[dict],
    context: "PlaylistContext",
) -> list:
    """Spustí validate_all() z music-utils pro každý track ve finálním playlistu.

    Volat PO validate_selected() – tedy nad tracky které skutečně půjdou do playlistu.

    Každý enriched track se převede na dict kompatibilní s music-utils a předá
    do validate_all(). Výsledky (TrackValidation) se logují a vrátí jako seznam
    připravený pro uložení do SQLite přes save_validation_results().

    Args:
        playlist: Finální seznam enriched track dicts.
        context:  PlaylistContext pro char_map (extrakce jazyka) a config.

    Returns:
        Seznam TrackValidation objektů (prázdný seznam pokud music-utils chybí).
    """
    try:
        from utils.validate_all import validate_all
    except ImportError:
        logger.warning(
            "run_validation: modul music-utils (utils) není dostupný – "
            "validace přeskočena. Nainstalujte: pip install -e /path/to/music-utils"
        )
        return []

    root_dir = getattr(getattr(context, "config", None), "MUSIC_ROOT_DIR", "")
    results = []

    for track in playlist:
        validation_input = _build_validation_input(track, context)
        file_dur = track.get("file_dur_sec")

        try:
            result = validate_all(validation_input, root_dir, file_dur_sec=file_dur)
        except Exception as exc:
            logger.error(
                "run_validation: chyba při validaci tracku %d: %s",
                track["music_id"], exc,
            )
            continue

        results.append(result)

        if not result.passed:
            logger.warning(
                "run_validation: track %d NEPROŠEL: chyby=%s",
                track["music_id"], result.errors,
            )
        elif result.warnings:
            logger.debug(
                "run_validation: track %d varování=%s",
                track["music_id"], result.warnings,
            )

    logger.info(
        "run_validation: %d/%d tracků prošlo validací",
        sum(1 for r in results if r.passed),
        len(results),
    )
    return results


# ------------------------------------------------------------------
# Interní pomocné funkce
# ------------------------------------------------------------------

def _build_validation_input(track: dict, context: "PlaylistContext") -> dict:
    """Převede enriched track dict na formát očekávaný music-utils.

    music-utils očekává:
        id, recording_code (ISRC), year, duration, file_path,
        lang (nebo language), deleted, album_code, track_number

    Args:
        track:   Enriched track dict z pipeline.
        context: PlaylistContext pro char_map (extrakce jazyka z chars_by_cat).

    Returns:
        Dict kompatibilní s validate_all().
    """
    album_info = context.album_map.get(track.get("album_id", 0), {})

    return {
        "id":             track["music_id"],
        "recording_code": track.get("isrc"),
        "year":           track.get("year"),
        "duration":       track.get("duration"),
        "file_path":      track.get("file_path"),
        "lang":           _extract_lang(track, context),
        "deleted":        0,                       # pipeline garantuje nenasmazané tracky
        # album_code a track_number nejsou v enriched dict – validate_all je volitelné
    }


def _extract_lang(track: dict, context: "PlaylistContext") -> str:
    """Extrahuje název jazyka z chars_by_cat pomocí char_map.

    Prochází chars_by_cat a hledá kategorii jejíž název obsahuje 'jazyk'.
    Vrací jméno první nalezené charakteristiky (= název jazyka).

    Args:
        track:   Enriched track dict s klíčem 'chars_by_cat'.
        context: PlaylistContext s char_map.

    Returns:
        Název jazyka (např. 'Angličtina') nebo prázdný řetězec.
    """
    for cat_id, char_ids in track.get("chars_by_cat", {}).items():
        if not char_ids:
            continue
        # Kategorie se dá zjistit z char_map přes libovolný char_id v té kategorii
        cat_name = context.char_map.get(char_ids[0], {}).get("category", "")
        if "jazyk" in cat_name.lower():
            return context.char_map.get(char_ids[0], {}).get("name", "")
    return ""

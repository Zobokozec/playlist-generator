"""
music-playlist – Pipeline generátoru playlistů pro TWR.

Fáze:
    1. INIT         – PlaylistContext (lookup mapy jednou při startu)
    2. HARD FILTER  – SQL hard filter (jazyk jako gate, deleted=0)
    3. ENRICH       – rozbalení chars/entity, doplnění z SQLite file_cache
    4. SOFT FILTER  – Python filtr (charakteristiky, délka, rok)
    5. COOLDOWN     – Python sets (track/album/artist cooldown)
    6. SELECTOR     – weighted random výběr podle % času
    7. VALIDACE     – soubor existuje, fallback ze zbytku poolu
    8. EXPORT       – uložit playlist.db, volat xml_exporter, vrátit JSON
"""
from .context import PlaylistContext
from .hard_filter import build_hard_filter_query
from .enrich import enrich_tracks
from .soft_filter import soft_filter
from .cooldown import apply_cooldown
from .selector import select_tracks
from .validator import validate_selected
from .exporter import export_playlist, GeneratorResult
from .db import init_db

__all__ = [
    "PlaylistContext",
    "build_hard_filter_query",
    "enrich_tracks",
    "soft_filter",
    "apply_cooldown",
    "select_tracks",
    "validate_selected",
    "export_playlist",
    "GeneratorResult",
    "init_db",
]

"""
Generator module pro TWR Playlist Generator.

Obsahuje:
- CooldownFilter: Filtrace podle cooldown pravidel
- Categorizer: Rozdělení tracků do kategorií
- PlaylistSelector: Výběr tracků do playlistu
- PlaylistRefiller: Doplnění playlistu po odstranění tracků
- PlaylistGenerator: Hlavní orchestrace generování playlistu
"""
try:
    from .cooldown import CooldownFilter
    from .categorizer import Categorizer
    from .selector import PlaylistSelector
    from .refill import PlaylistRefiller
    from .playlist_generator import PlaylistGenerator

    __all__ = ['CooldownFilter', 'Categorizer', 'PlaylistSelector', 'PlaylistRefiller', 'PlaylistGenerator']
except ImportError:
    # Může nastat při přímém spuštění pytestů bez správného kontextu balíčku
    pass

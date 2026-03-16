"""
Kategorizace tracků podle charakteristik pro výběrový algoritmus.

Categorizer přijme kandidáty (výstup fáze 2 – soft filtr) a sestaví si
interní mapy: charakteristiky, interprety a délky skladeb.
Další moduly se pak dotáží přes gettery.

Výchozí charakteristiky: pokud gain_categories.yaml definuje
``default_char_value`` u kategorie, trackům bez této kategorie se
automaticky doplní výchozí hodnota (např. jazyk → čeština).
"""
import logging
from collections import defaultdict

from utils.config_loader import load_gain_categories

logger = logging.getLogger(__name__)


def _build_defaults() -> dict[int, int]:
    """Načte gain_categories.yaml a vrátí {category_id: default_char_value}."""
    try:
        cfg = load_gain_categories()
    except FileNotFoundError:
        logger.warning("gain_categories.yaml nenalezen – žádné výchozí hodnoty")
        return {}

    defaults: dict[int, int] = {}
    primary = cfg.get("primary", {})
    if "default_char_value" in primary and "category_id" in primary:
        defaults[primary["category_id"]] = primary["default_char_value"]
    for sec in cfg.get("secondary", []):
        if "default_char_value" in sec and "category_id" in sec:
            defaults[sec["category_id"]] = sec["default_char_value"]
    return defaults


class Categorizer:
    """Sestaví kategorizační mapy z kandidátů pro výběrový algoritmus."""

    def __init__(self, candidates: list[dict]):
        """
        Args:
            candidates: seznam slovníků z MariaDB/soft filtru, každý obsahuje:
                {
                    'music_id': int,
                    'duration': int,
                    'artist_ids': set[int],
                    'album_id': int | None,
                    'characteristic_ids': {category_id: [char_value_id, ...]},
                    ...
                }
        """
        self._char_map: dict[int, dict[int, list[int]]] = {}
        self._artists: dict[int, set[int]] = {}
        self._durations: dict[int, int] = {}
        self._track_ids: list[int] = []
        self._defaults = _build_defaults()

        defaults_applied = 0
        for c in candidates:
            mid = c["music_id"]
            self._track_ids.append(mid)
            chars = dict(c.get("characteristic_ids") or {})

            for cat_id, default_vid in self._defaults.items():
                if cat_id not in chars:
                    chars[cat_id] = [default_vid]
                    defaults_applied += 1

            self._char_map[mid] = chars
            self._artists[mid] = c.get("artist_ids") or set()
            self._durations[mid] = c.get("duration", 210)

        logger.info(
            "Categorizer: načteno %d kandidátů", len(self._track_ids)
        )
        if defaults_applied:
            logger.info(
                "Categorizer: doplněno %d výchozích charakteristik",
                defaults_applied,
            )

    # ------------------------------------------------------------------
    # Veřejné API
    # ------------------------------------------------------------------

    def categorize(self) -> dict[int | str, list[int]]:
        """
        Vrátí mapování char_value_id → [music_id, ...].

        Track se může objevit pod více char_value_id (např. vícejazyčná
        skladba nebo více žánrů).
        """
        categories: dict[int | str, list[int]] = defaultdict(list)
        uncategorized = 0

        for mid in self._track_ids:
            chars = self._char_map.get(mid, {})
            if not chars:
                uncategorized += 1
                continue
            for _cat_id, value_ids in chars.items():
                for vid in value_ids:
                    categories[vid].append(mid)

        if uncategorized:
            logger.warning(
                "Kategorizace: %d z %d tracků nemá žádné charakteristiky",
                uncategorized, len(self._track_ids),
            )
        logger.info(
            "Kategorizace dokončena: %d tracků → %d kategorií",
            len(self._track_ids), len(categories),
        )
        return dict(categories)

    def add_other_groups(
        self, categorized: dict[int | str, list[int]], quotas: dict
    ) -> dict[int | str, list[int]]:
        """
        Pro každou quota skupinu, která obsahuje klíč 'other', vytvoří
        kategorii 'other_<group>' s tracky, které nemají žádný
        z explicitně definovaných char_value_id dané skupiny.

        Args:
            categorized: výstup categorize()
            quotas: {'language': {639: 60, 667: 25, 'other': 5}, ...}

        Returns:
            Aktualizovaný categorized s přidanými 'other_<group>' klíči.
        """
        all_track_ids = set(self._track_ids)

        for group_name, group_quotas in quotas.items():
            if not group_quotas or "other" not in group_quotas:
                continue

            # char_value_id explicitně definované v této skupině
            defined_ids = {
                k for k in group_quotas if isinstance(k, int)
            }

            # Tracky pokryté definovanými char_value_id
            covered = set()
            for cid in defined_ids:
                covered.update(categorized.get(cid, []))

            # Zbytek
            other_tracks = sorted(all_track_ids - covered)
            other_key = f"other_{group_name}"
            categorized[other_key] = other_tracks

            # Přepiš klíč 'other' v quotas na 'other_<group>'
            group_quotas[other_key] = group_quotas.pop("other")

            logger.info(
                "Other '%s': %d tracků nepokrytých definovanými char_ids",
                group_name, len(other_tracks),
            )

        return categorized

    def exclude_by_char_ids(self, char_ids: set[int]) -> list[int]:
        """
        Odstraní tracky, které mají jakýkoli z uvedených char_value_id.

        Použití: seasonal blacklist – char_ids s quota=0 znamená
        "tyto tracky nechci v playlistu".

        Args:
            char_ids: množina char_value_id k vyřazení

        Returns:
            Seznam vyřazených music_id
        """
        if not char_ids:
            return []

        excluded = []
        for mid in list(self._track_ids):
            chars = self._char_map.get(mid, {})
            track_char_values = set()
            for value_ids in chars.values():
                track_char_values.update(value_ids)

            if track_char_values & char_ids:
                excluded.append(mid)
                self._track_ids.remove(mid)
                del self._char_map[mid]
                self._artists.pop(mid, None)
                self._durations.pop(mid, None)

        if excluded:
            logger.info(
                "Seasonal blacklist: vyřazeno %d tracků (char_ids=%s)",
                len(excluded), char_ids,
            )
        return excluded

    def get_artists(self) -> dict[int, set[int]]:
        """Vrátí {music_id: set(artist_ids)}."""
        return self._artists

    def get_durations(self) -> dict[int, int]:
        """Vrátí {music_id: duration_seconds}."""
        return self._durations

    @property
    def track_ids(self) -> list[int]:
        """Seznam všech music_id."""
        return self._track_ids

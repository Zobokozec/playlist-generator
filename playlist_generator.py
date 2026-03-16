"""
Hlavní orchestrace generování playlistu.

Fáze 1-3 (načtení kandidátů, soft filtr, kategorizace) probíhají v __init__.
generate_playlist() pak řeší cooldown, výběr, uložení a export.
"""
import json
import logging
import os
import random
from copy import deepcopy
from datetime import datetime

from modules.generator.soft_filter import apply_soft_filter
from modules.errors import (
    NoCandidatesError,
    DatabaseConnectionError,
    PlaylistGeneratorError,
)
from .cooldown import CooldownFilter
from .categorizer import Categorizer
from .selector import PlaylistSelector
from modules.exporter.xml_exporter import XMLExporter

logger = logging.getLogger(__name__)

# Výchozí mapování hodin na příponu názvu playlistu
DEFAULT_TIME_NAMES = {
    0: "_NOC",
    5: "_RANO",
    9: "_DOPOLEDNE",
    12: "_POLEDNE",
    14: "_ODPOLEDNE",
    18: "_VECER",
    22: "_NOC",
}


def _resolve_time_suffix(hour: int, time_names: dict) -> str:
    """Vrátí příponu názvu playlistu podle hodiny."""
    # Seřadíme hranice sestupně a vezmeme první, která je <= hour
    for boundary in sorted(time_names.keys(), reverse=True):
        if hour >= boundary:
            return time_names[boundary]
    # Fallback
    return list(time_names.values())[0]


class PlaylistGenerator:
    """Orchestrátor generování playlistu - propojuje všechny moduly."""

    def __init__(self, sqlite_client, mariadb_client,
                 settings: dict, gain_categories: dict,
                 preset: dict,
                 file_checker=None, validator=None):
        """
        Fáze 1-3: Načte kandidáty, aplikuje soft filtr a kategorizuje.

        Args:
            sqlite_client: SQLiteClient instance (R/W lokální DB)
            mariadb_client: MariaDB klient (read-only, kandidáti + charakteristiky)
            settings: Obsah settings.yaml
            gain_categories: Obsah gain_categories.yaml
            preset: Preset dict s quotas, target_duration, name
            file_checker: FileChecker instance (volitelné)
            validator: Validator instance (volitelné)
        """
        self.sqlite = sqlite_client
        self.mariadb = mariadb_client
        self.settings = settings
        self.gain_categories = gain_categories
        self.preset = preset
        self.file_checker = file_checker
        self.validator = validator
        self.stats = {}

        # ========== FÁZE 1: ZÁKLADNÍ FILTR ==========
        logger.info("Fáze 1: Načítám základní kandidáty z MariaDB...")
        try:
            self._basic_candidates = self.mariadb.get_basic_candidates()
        except Exception as exc:
            raise DatabaseConnectionError("MariaDB", str(exc)) from exc
        self.stats['total_candidates'] = len(self._basic_candidates)
        logger.info("  → %d kandidátů", len(self._basic_candidates))

        if not self._basic_candidates:
            raise NoCandidatesError(phase="1 - základní filtr")

        # ========== FÁZE 2: SOFT FILTR ==========
        logger.info("Fáze 2: Aplikuji soft filtr...")
        self._soft_candidates = apply_soft_filter(self._basic_candidates)
        if not self._soft_candidates:
            raise NoCandidatesError(phase="2 - soft filtr")
        self.stats['after_soft_filter'] = len(self._soft_candidates)
        logger.info("  → %d po soft filtru", len(self._soft_candidates))

        # ========== FÁZE 3: KATEGORIZACE ==========
        logger.info("Fáze 3: Kategorizuji tracky...")
        categorizer = Categorizer(self._soft_candidates)

        # Seasonal blacklist: char_ids s quota=0 vyřadí tracky úplně
        blacklist_ids = set()
        for group_quotas in self.preset['quotas'].values():
            if not group_quotas:
                continue
            for char_id, pct in group_quotas.items():
                if isinstance(char_id, int) and pct == 0:
                    blacklist_ids.add(char_id)
        if blacklist_ids:
            categorizer.exclude_by_char_ids(blacklist_ids)

        self._categorized = categorizer.categorize()
        self._categorized = categorizer.add_other_groups(
            self._categorized, self.preset['quotas']
        )
        self._track_durations = categorizer.get_durations()
        self._track_artists = categorizer.get_artists()

        # Mapa char_value_id → name pro čitelný výstup
        self._char_names = self._load_char_names()

        # IDs tracků, které prošly kategorizací (po blacklistu)
        self._categorized_ids = set(categorizer.track_ids)

        # Filtrujeme soft_candidates jen na kategorized tracky
        self._categorized_candidates = [
            c for c in self._soft_candidates
            if c['music_id'] in self._categorized_ids
        ]
        self.stats['after_categorization'] = len(self._categorized_candidates)

        # Sestavíme track_metadata pro selector (artist + year)
        self._track_metadata = {}
        for c in self._categorized_candidates:
            mid = c['music_id']
            artist_ids = c.get('artist_ids', set())
            self._track_metadata[mid] = {
                'artist': frozenset(artist_ids) if artist_ids else None,
                'year': c.get('year'),
            }

        logger.info(
            "Init dokončen: %d kandidátů → %d po soft filtru → %d po kategorizaci → %d kategorií",
            self.stats['total_candidates'],
            self.stats['after_soft_filter'],
            self.stats['after_categorization'],
            len(self._categorized),
        )

    def generate_playlist(self, slot: dict) -> dict:
        """
        Generuje playlist z připravených dat (fáze 4-9).

        Args:
            slot: {
                'scheduled_start': datetime,
                'duration': int (sekundy),
                'name': str (volitelné)
            }

        Returns:
            {
                'playlist_id': int,
                'track_ids': [int, ...],
                'stats': dict,
                'category_distribution': dict,
            }
        """
        stats = dict(self.stats)  # Kopie init stats

        # ========== FÁZE 4: COOLDOWN FILTR ==========
        logger.info("Fáze 4: Aplikuji cooldown filtr...")
        cooldown_filter = CooldownFilter(
            self.sqlite,
            config=self.settings.get('cooldown', {})
        )

        # Pracujeme s KOPIÍ categorized_candidates, aby se neupravovala hlavní tabulka
        candidates_copy = deepcopy(self._categorized_candidates)
        valid_candidates = cooldown_filter.filter(
            candidates_copy, slot['scheduled_start']
        )
        stats['after_cooldown'] = len(valid_candidates)
        logger.info("  → %d po cooldown filtru", len(valid_candidates))

        if not valid_candidates:
            raise NoCandidatesError(phase="4 - cooldown filtr")

        # Vyfiltrujeme categorized - odstraníme track_ids, které cooldown vyřadil
        valid_ids = {c['music_id'] for c in valid_candidates}
        categorized_filtered = {}
        for cat, track_ids in self._categorized.items():
            filtered = [tid for tid in track_ids if tid in valid_ids]
            if filtered:
                categorized_filtered[cat] = filtered

        # ========== FÁZE 5: OVĚŘENÍ SOUBORŮ (přeskočeno) ==========
        logger.info("Fáze 5: Přeskočena")

        # ========== FÁZE 6: VÝBĚR TRACKŮ ==========
        logger.info("Fáze 6: Vybírám tracky do playlistu...")
        selector = PlaylistSelector(self.settings.get('generation', {}))

        candidates_lookup = {c['music_id']: c for c in valid_candidates}
        selected_ids = selector.select(
            categorized=categorized_filtered,
            quotas=self.preset['quotas'],
            target_duration=self.preset['target_duration'],
            candidates=candidates_lookup,
            track_durations=self._track_durations,
            track_metadata=self._track_metadata,
        )

        # Odstraníme duplicity (zachováme pořadí)
        seen = set()
        unique_selected = []
        for tid in selected_ids:
            if tid not in seen:
                seen.add(tid)
                unique_selected.append(tid)
        selected_ids = unique_selected

        stats['selected'] = len(selected_ids)
        stats['exhausted_categories'] = [
            {
                'category': e.category,
                'user_message': e.user_message,
            }
            for e in selector.exhausted_categories
        ]

        # Spočítáme skutečnou délku
        total_duration = sum(
            self._track_durations.get(tid, 210) for tid in selected_ids
        )
        stats['total_duration'] = total_duration
        logger.info(
            "  → Vybráno %d tracků, celková délka %.0fs (%.1f h)",
            len(selected_ids), total_duration, total_duration / 3600,
        )

        if not selected_ids:
            raise NoCandidatesError(phase="6 - výběr tracků")

        # Rozložení v kategoriích
        category_distribution = self._compute_category_distribution(
            selected_ids, categorized_filtered
        )
        stats['category_distribution'] = category_distribution

        # ========== FÁZE 7: VALIDACE (přeskočena) ==========
        logger.info("Fáze 7: Přeskočena")
        stats['warnings'] = 0

        # Zamícháme pořadí tracků
        random.shuffle(selected_ids)

        # ========== FÁZE 8: ULOŽENÍ ==========
        logger.info("Fáze 8: Ukládám playlist...")
        config_json = json.dumps(self.preset['quotas'], ensure_ascii=False)

        # Název playlistu s časovou příponou
        time_names = self.settings.get('playlist_names', DEFAULT_TIME_NAMES)
        hour = slot['scheduled_start'].hour
        time_suffix = _resolve_time_suffix(hour, time_names)
        playlist_name = (
            f"{slot['scheduled_start'].strftime('%Y-%m-%d')}"
            f"{time_suffix}"
        )

        playlist_id = self.sqlite.create_playlist(
            name=playlist_name,
            scheduled_start=slot['scheduled_start'],
            duration=self.preset['target_duration'],
            preset_name=self.preset.get('name', 'default'),
            config_json=config_json
        )

        self.sqlite.add_tracks_to_playlist(playlist_id, selected_ids)
        selected_set = set(selected_ids)
        history_tracks = [
            c for c in valid_candidates if c['music_id'] in selected_set
        ]
        self.sqlite.save_history(
            playlist_id, history_tracks, slot['scheduled_start']
        )

        # ========== FÁZE 9: XML EXPORT ==========
        logger.info("Fáze 9: Exportuji playlist do XML...")
        exports_dir = self.settings.get('paths', {}).get(
            'exports', 'data/exports/'
        )
        os.makedirs(exports_dir, exist_ok=True)
        export_filename = f"{playlist_name}.mlp"
        export_path = os.path.join(exports_dir, export_filename)
        exporter = XMLExporter()
        exporter.export_by_ids(selected_ids, export_path)
        logger.info("  → XML exportován do %s", export_path)

        logger.info(
            "  → Playlist #%d '%s' uložen (%d tracků, %.0fs)",
            playlist_id, playlist_name, len(selected_ids), total_duration,
        )

        return {
            'playlist_id': playlist_id,
            'playlist_name': playlist_name,
            'track_ids': selected_ids,
            'stats': stats,
            'category_distribution': category_distribution,
        }

    def _load_char_names(self) -> dict:
        """Načte mapu char_value_id → name z MariaDB charakteristik."""
        cat_ids = []
        primary = self.gain_categories.get('primary', {})
        if 'category_id' in primary:
            cat_ids.append(primary['category_id'])
        for sec in self.gain_categories.get('secondary', []):
            if 'category_id' in sec:
                cat_ids.append(sec['category_id'])

        if not cat_ids:
            return {}

        try:
            chars_data = self.mariadb.get_characteristics(cat_ids)
        except Exception as exc:
            logger.warning("Nelze načíst char names: %s", exc)
            return {}

        names = {}
        for entry in chars_data:
            for ch_id, ch_name in entry.get('category', entry.get('chars', {})).items():
                names[ch_id] = ch_name
        return names

    def _compute_category_distribution(
        self, selected_ids: list, categorized: dict
    ) -> dict:
        """Spočítá rozložení vybraných tracků v kategoriích s čitelnými názvy."""
        selected_set = set(selected_ids)
        distribution = {}
        for cat, track_ids in categorized.items():
            count = len([tid for tid in track_ids if tid in selected_set])
            if count > 0:
                label = self._char_names.get(cat, str(cat))
                distribution[label] = count
        return distribution

"""
Doplnění playlistu po odstranění tracků uživatelem.
"""
import logging
from typing import List, Dict
from .selector import PlaylistSelector
from .categorizer import Categorizer

logger = logging.getLogger(__name__)


class PlaylistRefiller:
    """Doplnění playlistu po odstranění tracků"""

    def __init__(self, selector: PlaylistSelector,
                 categorizer: Categorizer):
        """
        Args:
            selector: PlaylistSelector instance pro výběr nových tracků
            categorizer: Categorizer instance pro kategorizaci
        """
        self.selector = selector
        self.categorizer = categorizer

    def refill(self, removed_track_ids: List[int],
               preset: dict, exclude_ids: List[int],
               all_track_ids: List[int],
               track_durations: dict = None) -> List[int]:
        """
        Vygeneruj náhradu za odstraněné tracky.

        Args:
            removed_track_ids: Odstraněné tracky
            preset: Použitý preset (quotas)
            exclude_ids: Tracky již v playlistu (nemohou se opakovat)
            all_track_ids: Všichni dostupní kandidáti
            track_durations: {track_id: duration_seconds}

        Returns:
            [new_track_id, new_track_id, ...] pro doplnění

        Logic (Strategie B - proporční):
            1. Spočti deficit času
            2. Analyzuj které kategorie byly zasažené
            3. Generuj náhradu proporčně podle původních quotas
        """
        # Spočti deficit času
        durations = track_durations or {}
        default_duration = 210
        deficit_duration = sum(
            durations.get(tid, default_duration) for tid in removed_track_ids
        )

        if deficit_duration <= 0:
            logger.info("Refill: žádný deficit času, nic k doplnění.")
            return []

        # Filtruj dostupné kandidáty (ne ty co už jsou v playlistu)
        exclude_set = set(exclude_ids)
        available_ids = [tid for tid in all_track_ids if tid not in exclude_set]

        # Kategorizuj dostupné - použijeme celou kategorizaci a filtrujeme
        full_categorized = self.categorizer.categorize()
        available_set = set(available_ids)
        categorized = {
            cat: [tid for tid in tids if tid in available_set]
            for cat, tids in full_categorized.items()
        }

        # Generuj náhradu podle quotas presetu
        quotas = preset.get('quotas', {})
        logger.info(
            "Refill: doplňuji %ds za %d odstraněných tracků, %d kandidátů k dispozici",
            deficit_duration, len(removed_track_ids), len(available_ids),
        )

        new_tracks = self.selector.select(
            categorized, quotas, deficit_duration, track_durations=track_durations
        )

        logger.info("Refill dokončen: %d nových tracků", len(new_tracks))
        return new_tracks

    def analyze_removed(self, removed_track_ids: List[int]) -> dict:
        """
        Zjisti jaké kategorie byly odstraněny.

        Returns:
            {'cs': 3, 'pop': 2, ...}  (počet odstraněných v kategorii)
        """
        from collections import Counter
        category_counts = Counter()

        for track_id in removed_track_ids:
            chars = self.categorizer._char_map.get(track_id, {})
            for category_name, char_list in chars.items():
                for char_name in char_list:
                    category_counts[char_name] += 1

        return dict(category_counts)

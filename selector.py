"""
Výběrová logika pro generování playlistu (Varianta A s % času).

Standalone použití:
    python -m modules.generator.selector --candidates data.csv --config preset.yaml --output log.csv
"""
import argparse
import csv
import logging
import random
import sys
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Optional

from modules.errors import CategoryExhaustedError

logger = logging.getLogger(__name__)


class PlaylistSelector:
    """Výběr tracků do playlistu podle procentuálních kvót"""

    def __init__(self, config: dict = None):
        """
        Args:
            config: settings.yaml['generation'] -
                    např. {'tolerance_percent': 5, 'max_iterations': 1000,
                           'year_half_life': 10, 'artist_unique': True}
        """
        self.config = config or {}
        self.exhausted_categories: List[CategoryExhaustedError] = []
        self.selection_log: List[dict] = []

    def select(self, categorized: dict, quotas: dict,
               target_duration: int, candidates: dict = None,
               track_durations: dict = None,
               track_metadata: dict = None,
               adjustments: dict = None) -> List[int]:
        """
        Hlavní výběrová logika.

        Args:
            categorized: {char_value_id: [track_id, ...]}
            quotas: {'language': {char_value_id: 60, ...}, 'genre': {...}}
            target_duration: Cílová délka v sekundách (14400)
            candidates: {track_id: {music_id, duration, characteristic_ids, ...}}
            track_durations: {track_id: duration_seconds, ...}
            track_metadata: {track_id: {'artist': str, 'year': int}}
            adjustments: {
                'quota_modifiers': {char_value_id: +5, ...},
                'year_half_life': 8,
                'artist_unique': True/False,
            }

        Returns:
            [track_id, track_id, ...] v pořadí výběru
        """
        self.exhausted_categories = []
        self.selection_log = []
        adjustments = adjustments or {}
        track_metadata = track_metadata or {}

        # Resolve config with adjustments overrides
        year_half_life = adjustments.get(
            'year_half_life', self.config.get('year_half_life', 10)
        )
        artist_unique = adjustments.get(
            'artist_unique', self.config.get('artist_unique', True)
        )
        current_year = datetime.now().year

        # Flatten quotas – přeskočí prázdné/None skupiny a klíče s hodnotou 0
        all_quotas = {}
        for cat_quotas in quotas.values():
            if not cat_quotas:
                continue
            for k, v in cat_quotas.items():
                if v and v > 0:
                    all_quotas[k] = v

        # Apply quota modifiers from adjustments
        for char_id, modifier in adjustments.get('quota_modifiers', {}).items():
            if char_id in all_quotas:
                all_quotas[char_id] = max(0, all_quotas[char_id] + modifier)
                if all_quotas[char_id] == 0:
                    del all_quotas[char_id]

        # Tracking
        selected_duration = defaultdict(float)
        selected_tracks = set()
        selected_artists = set()
        selected_albums = set()
        playlist = []
        total_duration = 0.0

        default_duration = 210  # 3.5 minuty
        max_iter = self.config.get('max_iterations', 1000)
        iteration = 0

        logger.info(
            "Spouštím výběr: target=%ds, kategorií=%d, max_iter=%d, "
            "year_half_life=%d, artist_unique=%s",
            target_duration, len(all_quotas), max_iter,
            year_half_life, artist_unique,
        )

        while total_duration < target_duration and iteration < max_iter:
            iteration += 1

            needs = self.calculate_needs(
                all_quotas, selected_duration, total_duration, target_duration
            )

            if not needs:
                logger.debug("Žádné zbývající potřeby, končím výběr.")
                break

            category = self.weighted_choice(needs)

            # Filtr: nevybrané tracky
            available = [
                tid for tid in categorized.get(category, [])
                if tid not in selected_tracks
            ]

            # Filtr: artist uniqueness (porovnává jednotlivé artist_ids)
            if artist_unique and available and track_metadata:
                filtered = []
                for tid in available:
                    artist = track_metadata.get(tid, {}).get('artist')
                    if artist is None:
                        filtered.append(tid)
                    elif isinstance(artist, (set, frozenset)):
                        if not (artist & selected_artists):
                            filtered.append(tid)
                    elif artist not in selected_artists:
                        filtered.append(tid)
                if filtered:
                    available = filtered
                else:
                    logger.debug(
                        "Iterace %d: kategorie '%s' — všichni interpreti vyčerpáni, skip",
                        iteration, category,
                    )
                    continue

            # Filtr: album uniqueness
            if available and candidates:
                filtered = [
                    tid for tid in available
                    if candidates.get(tid, {}).get('album_id') not in selected_albums
                    or candidates.get(tid, {}).get('album_id') is None
                ]
                if filtered:
                    available = filtered

            if not available:
                if category in all_quotas:
                    exhausted_info = CategoryExhaustedError(
                        category=category,
                        available=0,
                        requested_pct=all_quotas[category],
                    )
                    self.exhausted_categories.append(exhausted_info)
                    logger.warning("%s", exhausted_info.user_message)

                    remaining_quota = all_quotas.pop(category)
                    total_remaining = sum(all_quotas.values())
                    if total_remaining > 0:
                        for cat in all_quotas:
                            all_quotas[cat] += (
                                (all_quotas[cat] / total_remaining) * remaining_quota
                            )
                        logger.info(
                            "Kvóta %.1f%% z '%s' přerozdělena do %d kategorií",
                            remaining_quota, category, len(all_quotas),
                        )
                continue

            # Year-weighted výběr
            track_id, year_weight = self._year_weighted_choice(
                available, track_metadata, current_year, year_half_life
            )

            # Duration lookup
            if candidates and track_id in candidates:
                duration = candidates[track_id].get('duration', default_duration)
            else:
                duration = (track_durations or {}).get(track_id, default_duration)

            # Přidej do playlistu
            playlist.append(track_id)
            selected_tracks.add(track_id)
            total_duration += duration

            artist = track_metadata.get(track_id, {}).get('artist')
            if artist:
                if isinstance(artist, (set, frozenset)):
                    selected_artists.update(artist)
                else:
                    selected_artists.add(artist)

            if candidates and track_id in candidates:
                album_id = candidates[track_id].get('album_id')
                if album_id is not None:
                    selected_albums.add(album_id)

            # Selection log
            meta = track_metadata.get(track_id, {})
            self.selection_log.append({
                'iteration': iteration,
                'category': category,
                'category_deficit': needs.get(category, 0),
                'track_id': track_id,
                'artist': meta.get('artist', ''),
                'year': meta.get('year', ''),
                'year_weight': round(year_weight, 4),
                'duration': duration,
                'total_duration': round(total_duration, 1),
            })

            # Update duration trackingu pro všechny kategorie
            if candidates and track_id in candidates:
                chars = candidates[track_id].get('characteristic_ids', {})
                for value_ids in chars.values():
                    for vid in value_ids:
                        if vid in selected_duration or vid in all_quotas:
                            selected_duration[vid] += duration
            else:
                for cat_name, cat_tracks in categorized.items():
                    if track_id in cat_tracks:
                        selected_duration[cat_name] += duration

        if iteration >= max_iter:
            logger.warning(
                "Dosažen max počet iterací (%d). Playlist má %.0fs z %ds.",
                max_iter, total_duration, target_duration,
            )

        logger.info(
            "Výběr dokončen: %d tracků, %.0f/%ds, %d iterací, %d dočerpaných kategorií",
            len(playlist), total_duration, target_duration,
            iteration, len(self.exhausted_categories),
        )

        return playlist

    def _year_weighted_choice(self, available: list, track_metadata: dict,
                              current_year: int, half_life: float):
        """Vážený výběr tracku s decay křivkou podle roku.

        Returns:
            (track_id, year_weight) — vybraný track a jeho váha
        """
        if not track_metadata:
            return random.choice(available), 1.0

        weights = []
        for tid in available:
            year = track_metadata.get(tid, {}).get('year')
            if year:
                w = 2 ** ((year - current_year) / half_life)
            else:
                w = 0.5  # neznámý rok — neutrální váha
            weights.append(w)

        chosen = random.choices(available, weights=weights, k=1)[0]
        idx = available.index(chosen)
        return chosen, weights[idx]

    def calculate_needs(self, quotas: dict, selected_duration: dict,
                        total_duration: float,
                        target_duration: int) -> dict:
        """
        Vypočti zbývající potřeby.

        Returns:
            {'cs': 0.6, 'en': 0.1, ...}  (normalizované na zbývající čas)
        """
        if not quotas:
            return {}

        remaining = target_duration - total_duration
        if remaining <= 0:
            return {}

        needs = {}
        for category, target_pct in quotas.items():
            target_seconds = target_duration * (target_pct / 100.0)
            current_seconds = selected_duration.get(category, 0)
            deficit = target_seconds - current_seconds

            if deficit > 0:
                needs[category] = deficit / remaining

        total = sum(needs.values())
        if total > 0:
            needs = {k: v / total for k, v in needs.items()}

        return needs

    def weighted_choice(self, needs: dict) -> str:
        """Vyber kategorii podle vah."""
        categories = list(needs.keys())
        weights = [needs[c] for c in categories]
        return random.choices(categories, weights=weights, k=1)[0]

    def get_selection_log(self) -> List[dict]:
        """Vrátí selection log jako seznam slovníků."""
        return self.selection_log

    def write_selection_log(self, path: str):
        """Zapíše selection log do CSV souboru."""
        if not self.selection_log:
            return
        fieldnames = list(self.selection_log[0].keys())
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.selection_log)
        logger.info("Selection log zapsán do %s (%d záznamů)", path, len(self.selection_log))


def _load_candidates_csv(path: str):
    """Načte CSV s kandidáty: music_id,artist,year,duration,char_ids

    char_ids je pipe-separated seznam (např. '639|16|652')
    """
    categorized = defaultdict(list)
    track_metadata = {}
    track_durations = {}

    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            tid = int(row['music_id'])
            track_metadata[tid] = {
                'artist': row.get('artist', ''),
                'year': int(row['year']) if row.get('year') else None,
            }
            track_durations[tid] = float(row.get('duration', 210))

            char_ids_str = row.get('char_ids', '')
            if char_ids_str:
                for cid in char_ids_str.split('|'):
                    cid = cid.strip()
                    if cid:
                        categorized[int(cid)].append(tid)

    return dict(categorized), track_metadata, track_durations


def _load_config_yaml(path: str) -> dict:
    """Načte YAML config (preset) — quotas, target_duration, generation."""
    import yaml
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Standalone PlaylistSelector — výběr tracků podle kvót'
    )
    parser.add_argument('--candidates', required=True,
                        help='CSV soubor: music_id,artist,year,duration,char_ids')
    parser.add_argument('--config', required=True,
                        help='YAML config s quotas a target_duration')
    parser.add_argument('--output', default=None,
                        help='Výstupní CSV selection log')
    parser.add_argument('--adjustments', default=None,
                        help='JSON soubor s adjustments (volitelné)')
    parser.add_argument('--seed', type=int, default=None,
                        help='Random seed pro reprodukovatelnost')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    if args.seed is not None:
        random.seed(args.seed)

    # Load data
    categorized, track_metadata, track_durations = _load_candidates_csv(args.candidates)
    config = _load_config_yaml(args.config)

    quotas = config.get('quotas', {})
    target_duration = config.get('target_duration', 14400)
    generation_config = config.get('generation', {})

    adjustments = None
    if args.adjustments:
        import json
        with open(args.adjustments, 'r', encoding='utf-8') as f:
            adjustments = json.load(f)

    # Run selector
    selector = PlaylistSelector(generation_config)
    selected = selector.select(
        categorized=categorized,
        quotas=quotas,
        target_duration=target_duration,
        track_durations=track_durations,
        track_metadata=track_metadata,
        adjustments=adjustments,
    )

    # Output
    print(f"\n=== Výsledný playlist ({len(selected)} tracků) ===")
    for i, tid in enumerate(selected, 1):
        meta = track_metadata.get(tid, {})
        print(f"  {i:3d}. ID={tid}  artist={meta.get('artist', '?')}  "
              f"year={meta.get('year', '?')}  dur={track_durations.get(tid, '?')}s")

    total = sum(track_durations.get(tid, 210) for tid in selected)
    print(f"\nCelková délka: {total:.0f}s ({total/3600:.1f}h)")

    if args.output:
        selector.write_selection_log(args.output)
        print(f"Selection log: {args.output}")
    else:
        # Výpis logu na stdout
        print("\n=== Selection log ===")
        for entry in selector.get_selection_log():
            print(f"  #{entry['iteration']:3d} cat={entry['category']} "
                  f"track={entry['track_id']} artist={entry['artist']} "
                  f"year={entry['year']} yw={entry['year_weight']:.3f} "
                  f"dur={entry['duration']}s total={entry['total_duration']}s "
                  f"deficit={entry['category_deficit']:.3f}")

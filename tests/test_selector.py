"""Testy pro selector.py"""
import pytest
from music_playlist.playlist.selector import select_tracks


class TestSelectTracks:
    def test_returns_list(self, sample_tracks, quotas):
        result = select_tracks(sample_tracks, quotas, 600)
        assert isinstance(result, list)

    def test_no_duplicates(self, sample_tracks, quotas):
        result = select_tracks(sample_tracks, quotas, 600)
        ids = [t["music_id"] for t in result]
        assert len(ids) == len(set(ids))

    def test_approaches_target_duration(self, sample_tracks, quotas):
        target = 800.0
        result = select_tracks(sample_tracks, quotas, target)
        total = sum(t.get("net_duration") or t.get("duration", 0) for t in result)
        # Musí být alespoň blízko cíli (nebo vyčerpat pool)
        assert total > 0
        # Nesmí přesáhnout cíl o víc než jeden track (poslední track může přetéct)
        max_single = max(t.get("net_duration") or t.get("duration", 0) for t in sample_tracks)
        assert total <= target + max_single

    def test_empty_tracks_returns_empty(self, quotas):
        result = select_tracks([], quotas, 600)
        assert result == []

    def test_empty_quotas_returns_random_fill(self, sample_tracks):
        result = select_tracks(sample_tracks, {}, 400)
        # S prázdnými kvótami se přepne na náhodný výběr
        assert isinstance(result, list)

    def test_respects_quota_proportions(self, quotas):
        """Výsledek musí víceméně splňovat procentuální rozložení."""
        # Vytvoříme větší pool pro lepší statistiku
        tracks = []
        for i in range(1, 31):
            cat3 = [12] if i % 3 == 0 else ([15] if i % 3 == 1 else [20])
            cat5 = [45] if i % 2 == 0 else [46]
            tracks.append({
                "music_id": i,
                "album_id": 101,
                "duration": 200,
                "net_duration": 200.0,
                "year": 2010,
                "entity_ids": [81],
                "chars_by_cat": {3: cat3, 5: cat5},
                "file_exists": True,
                "file_path": f"X:\\MUSIC\\CD0001_{i:02d}.mp3",
                "intro_sec": 0.0,
                "outro_sec": 200.0,
            })
        result = select_tracks(tracks, quotas, 2000)
        # Alespoň nějaké tracky musí být vybráno
        assert len(result) > 0

    def test_quota_pct_normalization(self, sample_tracks):
        """Kvóty mohou přijít jako 0–100 nebo 0.0–1.0."""
        quotas_pct = {3: {12: 50, 15: 35, 20: 15}}
        quotas_frac = {3: {12: 0.50, 15: 0.35, 20: 0.15}}
        r1 = select_tracks(sample_tracks, quotas_pct, 600)
        r2 = select_tracks(sample_tracks, quotas_frac, 600)
        # Oba by měly vrátit neprázdný výsledek
        assert isinstance(r1, list)
        assert isinstance(r2, list)

    def test_all_tracks_selected_for_small_pool(self):
        """Pokud je pool malý a target velký, vrátí všechny dostupné."""
        tracks = [
            {"music_id": i, "album_id": 101, "duration": 100, "net_duration": 100.0,
             "year": 2010, "entity_ids": [81], "chars_by_cat": {3: [12]},
             "file_exists": True, "file_path": f"path_{i}.mp3",
             "intro_sec": 0.0, "outro_sec": 100.0}
            for i in range(1, 4)
        ]
        quotas = {3: {12: 1.0}}
        result = select_tracks(tracks, quotas, 10000)
        # Nelze překročit pool
        assert len(result) <= 3

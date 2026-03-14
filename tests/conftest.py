"""
Fixtures pro testy music-playlist modulu.

Používá ukázková data – nevyžaduje připojení k DB.
"""
import sys
from pathlib import Path

# Přidej root projektu do sys.path – umožňuje import music_playlist
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


# ---------------------------------------------------------------------------
# Ukázková data – char_map / entity_map / album_map
# ---------------------------------------------------------------------------

@pytest.fixture
def char_map():
    """Minimální char_map (category_id → char_id → metadata)."""
    return {
        12: {"name": "Čeština",     "category": "Jazyk",  "category_id": 3},
        15: {"name": "Angličtina",  "category": "Jazyk",  "category_id": 3},
        20: {"name": "Slovenština", "category": "Jazyk",  "category_id": 3},
        45: {"name": "Klidná",      "category": "Nálada", "category_id": 5},
        46: {"name": "Chvály",      "category": "Nálada", "category_id": 5},
        47: {"name": "Instrumen.",  "category": "Nálada", "category_id": 5},
    }


@pytest.fixture
def album_map():
    return {
        101: {"typ": "CD", "cislo": 1, "track_count": 12, "album_type": "full"},
        102: {"typ": "CD", "cislo": 2, "track_count": 3,  "album_type": "single"},
        103: {"typ": "CD", "cislo": 3, "track_count": 5,  "album_type": "ep"},
    }


@pytest.fixture
def entity_map():
    return {
        81: "Chris Tomlin",
        93: "Hillsong",
        100: "Ewa Farna",
    }


# ---------------------------------------------------------------------------
# Ukázková data – tracky (obohacené, po enrich)
# ---------------------------------------------------------------------------

def _make_track(
    music_id: int,
    album_id: int = 101,
    duration: int = 210,
    net_duration: float | None = None,
    year: int = 2010,
    entity_ids: list | None = None,
    chars_by_cat: dict | None = None,
    file_exists: bool = True,
    file_path: str | None = None,
    intro_sec: float = 0.0,
    outro_sec: float | None = None,
) -> dict:
    if net_duration is None:
        net_duration = float(duration)
    if outro_sec is None:
        outro_sec = float(duration)
    return {
        "music_id":    music_id,
        "album_id":    album_id,
        "duration":    duration,
        "net_duration": net_duration,
        "year":        year,
        "isrc":        f"CZ-TWR-{music_id:04d}",
        "entity_ids":  entity_ids or [81],
        "chars_by_cat": chars_by_cat or {3: [12], 5: [45]},
        "file_exists": file_exists,
        "file_path":   file_path or f"X:\\MUSIC\\CD0001\\CD0001_{music_id:02d}.mp3",
        "intro_sec":   intro_sec,
        "outro_sec":   outro_sec,
    }


@pytest.fixture
def sample_tracks():
    """10 ukázkových tracků pokrývající různé kombinace char_id."""
    return [
        _make_track(1,  chars_by_cat={3: [12], 5: [45]}, duration=180),
        _make_track(2,  chars_by_cat={3: [15], 5: [45]}, duration=240),
        _make_track(3,  chars_by_cat={3: [12], 5: [46]}, duration=200),
        _make_track(4,  chars_by_cat={3: [20], 5: [46]}, duration=220),
        _make_track(5,  chars_by_cat={3: [15], 5: [47]}, duration=300),
        _make_track(6,  chars_by_cat={3: [12], 5: [45]}, duration=190),
        _make_track(7,  chars_by_cat={3: [15], 5: [46]}, duration=210),
        _make_track(8,  chars_by_cat={3: [20], 5: [47]}, duration=250),
        _make_track(9,  chars_by_cat={3: [12], 5: [46]}, duration=170),
        _make_track(10, chars_by_cat={3: [15], 5: [45]}, duration=230),
    ]


@pytest.fixture
def soft_params():
    """Standardní params pro soft_filter."""
    return {
        "chars": {
            3: {"include": [12, 15, 20]},
            5: {"include": [45, 46, 47]},
        },
        "duration": {"min": 60, "max": 600},
        "year":     {"min": 1970, "max": 2030},
    }


@pytest.fixture
def quotas():
    """Standardní kvóty pro selektor."""
    return {
        3: {12: 0.50, 15: 0.35, 20: 0.15},
        5: {45: 0.40, 46: 0.40, 47: 0.20},
    }

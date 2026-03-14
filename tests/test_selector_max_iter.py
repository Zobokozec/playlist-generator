"""Test max_iterations parametru selektoru."""
from music_playlist.playlist.selector import select_tracks


def test_max_iterations_respected():
    """Selektor musí respektovat max_iterations limit."""
    # Velký target ale malý pool – selektor se musí zastavit přes max_iterations
    tracks = [
        {"music_id": i, "album_id": 101, "duration": 10, "net_duration": 10.0,
         "year": 2010, "entity_ids": [81], "chars_by_cat": {3: [12]},
         "file_exists": True, "file_path": f"path_{i}.mp3",
         "intro_sec": 0.0, "outro_sec": 10.0}
        for i in range(1, 4)
    ]
    quotas = {3: {12: 1.0}}
    # target 100 000s ale pool max 30s → zastav se
    result = select_tracks(tracks, quotas, 100_000, max_iterations=50)
    assert len(result) <= 3  # Nikdy víc než pool


def test_default_max_iterations():
    """Výchozí max_iterations je 10_000."""
    import inspect
    sig = inspect.signature(select_tracks)
    assert sig.parameters["max_iterations"].default == 10_000

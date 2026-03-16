# music-playlist

Generátor playlistů pro TWR – pipeline výběru písní s kvótami, cooldownem a validací.

## Přehled pipeline

```
1. INIT          PlaylistContext – lookup mapy jednou při startu
2. HARD FILTER   SQL – blocking podmínky          ~40k → ~15k
3. ENRICH        Python – rozbal chars/entity, doplň file_cache
4. SOFT FILTER   Python – charakteristiky, délka, rok   ~15k → ~8k
5. COOLDOWN      Python sets – track/album/artist       ~8k → ~5k
6. SELECTOR      Python weighted random – kvóty % času  ~5k → ~20
7. VALIDACE      soubor existuje, fallback ze zbytku poolu
8. EXPORT        uložit playlist.db, volat xml_exporter, vrátit JSON
```

## Struktura projektu

```
music_playlist/
├── __init__.py
├── __main__.py
├── cli.py
├── config/
│   ├── __init__.py
│   ├── config.py          # PlaylistConfig – načítání z TOML/env
│   ├── config.toml        # Hlavní konfigurace
│   └── presets/
│       ├── default.yaml
│       └── nedele_rano.yaml
└── playlist/
    ├── __init__.py
    ├── context.py         # PlaylistContext – lookup mapy
    ├── hard_filter.py     # SQL hard filter
    ├── enrich.py          # Rozbalení dat, doplnění z SQLite
    ├── soft_filter.py     # Python filtr (char, délka, rok)
    ├── cooldown.py        # Python sets (track/album/artist)
    ├── selector.py        # Weighted random výběr
    ├── validator.py       # Validace souborů + fallback
    ├── exporter.py        # JSON výstup + GeneratorResult
    ├── db.py              # Schéma playlist.db, init
    └── cli.py             # CLI rozhraní
tests/
    ├── conftest.py
    ├── test_soft_filter.py
    ├── test_cooldown.py
    ├── test_selector.py
    ├── test_enrich.py
    ├── test_validator.py
    ├── test_db.py
    └── test_config.py
```

## Tři datové zdroje

| DB | Typ | Obsah |
|---|---|---|
| `music-twar` | MariaDB | Zdrojová pravda – music, albums, entities, characteristics |
| `musicdb` | SQLite | Sdílená cache – file_cache (file_path, intro_sec, outro_sec) |
| `playlist.db` | SQLite | Vlastní – playlists, playlist_tracks, playlist_history, album_info |

## Instalace

```bash
# Python 3.11+ má tomllib ve stdlib
pip install -e .

# Python 3.10
pip install -e ".[toml]"

# Vývojové závislosti
pip install -e ".[dev]"
```

## CLI

```bash
# Generování playlistu
python -m music_playlist.cli generate --params params_example.json
python -m music_playlist.cli generate --params params_example.json --output ids
python -m music_playlist.cli generate --params params_example.json --dry-run

# Historie
python -m music_playlist.cli history --last 10

# Presety
python -m music_playlist.cli presets --list
```

### params.json

```json
{
  "scheduled_start": "2026-03-15T09:00:00",
  "duration_sec": 3600,
  "preset": "nedele_rano",
  "quotas": {
    "3": {"12": 40, "15": 40, "20": 20},
    "5": {"45": 50, "46": 30, "47": 20}
  },
  "soft_filter": {
    "chars": {
      "3": {"include": [12, 15, 20]},
      "5": {"include": [45, 46, 47, 48]}
    },
    "duration": {"min": 60, "max": 600},
    "year":     {"min": 1970}
  },
  "options": {
    "output":  "full",
    "dry_run": false
  }
}
```

> Klíče `quotas` a `soft_filter.chars` jsou **category_id** jako stringy (JSON).
> Hodnoty char_id jsou čísla.

### Výstupní formáty

| Formát | Obsah |
|---|---|
| `ids` | `[42, 107, 203]` |
| `full` | `[{id, duration, net_duration, file_path, intro_sec, outro_sec, chars}, ...]` |
| `debug` | `{playlist: [...], excluded: {reason: [ids]}, stats: {...}}` |

## Konfigurace (config.toml)

```toml
lang_category_id = 3         # Gate: bez jazyka nikdy do playlistu
duration_tolerance_sec = 5

[cooldown]
track_hours  = 24
album_hours  = 24
artist_hours = 6

[album]
single_max_tracks = 3        # <= 3 -> 'single'
ep_max_tracks     = 7        # <= 7 -> 'ep', jinak -> 'full'

[database]
playlist_db = "data/playlist.db"
music_db    = "data/music.db"

[paths]
music_root  = "X:\\MUSIC"
presets_dir = "music_playlist/config/presets"
exports_dir = "data/exports"
```

## Testy

```bash
python -m pytest
python -m pytest tests/test_soft_filter.py -v
python -m pytest tests/test_selector.py::TestSelectTracks::test_no_duplicates
```

## Závislosti modulu

```
music-playlist
    +-- twrsql          (MariaDB/PyMySQL – hard filter dotaz, lookup mapy)
    +-- xmlplaylist     (export do mAirList .mlp souboru)
    +-- musicdb         (SQLite sdilena – file_cache)
    +-- playlist.db     (SQLite vlastni – cooldown, history)
    +-- music-utils     (volitelne – validace souboru, ISRC)
```

DB klienti jsou **injektovány do PlaylistContext** – modul sám žádné DB připojení neotevírá.

### Napojení na MariaDB (TWRsql)

`music-playlist` komunikuje s MariaDB přes `twrsql`. Připojení se inicializuje
automaticky z výchozího konfiguračního souboru (nebo vlastního souboru/slovníku).

V `playlist/cli.py` je třída `_TWRsqlAdapter`, která obaluje `TWRsql` a
překládá rozhraní `dotaz_dict(sql, params)` na `TWRsql.query(sql, params, as_dict=True)`.
Zároveň převádí pojmenované parametry ze stylu `:name` (SQLite) na `%(name)s` (PyMySQL).

```
PlaylistContext
    └── twar = _TWRsqlAdapter(TWRsql())
                  └── TWRsql(config_file="...")   # vlastní konfig
                      TWRsql(config_dict={...})   # přímý slovník
                      TWRsql()                    # výchozí twar.json
```

### XML export (xmlplaylist)

`xmlplaylist.export_to_xml(mlp_path, track_dict)` generuje mAirList `.mlp` soubory.
Voláno z `exporter._export_xml()` pro každý track v playlistu.

Metadata pro export se načítají batch dotazem z twar (`title`, `album`, `pronunciation`,
`description`, `artist_pronunciation`). Charakteristiky se mapují z `char_map` na:
`language`, `tempo`, `style`, `keywords`.

Výstupní soubor: `<EXPORTS_DIR>/<datum>_<preset>.mlp`

Pokud modul není dostupný, XML export se přeskočí (pouze varování do logu).

**Instalace závislostí:**
```bash
pip install -e G:/Python/moduly/TWRsql        # twrsql
pip install -e ../XMLplaylist                  # xmlplaylist
pip install -e .                               # music-playlist
pip install -e ../music-utils                  # volitelné – validace
```

## Kritická pravidla (neregredovat)

1. **Cooldown artist** - set intersection pres VSECHNY `entity_ids` (ne jen `entity[0]`)
2. **Cooldown album** - jen `album_type = 'full'`, singly neblokuji
3. **net_duration** - `outro_sec - intro_sec` (ne cely soubor)
4. **Jazyk jako gate** - bez jazyka nikdy do playlistu (hard filter SQL)
5. **Batch SQLite dotaz** - jeden dotaz pro `file_cache` (ne per-track)
6. **ISRC porovnani** - normalizovat pred porovnavanim

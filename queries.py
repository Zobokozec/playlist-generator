"""
SQL dotazy pro MariaDB (read-only).

Všechny dotazy jsou organizované podle fází z kapitoly 4 implementation-manual.md.
"""

# =============================================================================
# Fáze 1: Základní Filtr
# =============================================================================

query_basic_filter = """
select m.id as music, -- music_id
	m.album, -- album_id
    m.duration, -- délka
    m.year, -- rok 
	concat('[', GROUP_CONCAT(distinct en.entity), ']') as entity, -- list of entities
    concat('{', GROUP_CONCAT(CONCAT(ch.id, ':', ch.category)), '}') as chars_ids
    -- ch.category, 
    -- ch.id as characteristic
    
    
from music_characteristics_view mcv 
where m.deleted = 0 -- není smazaná hudba 
    and duration > 0 -- je delší než 0
    and year is not null -- má zadaný rok
 group by m.id
"""

# =============================================================================
# Fáze 2: Cooldown Filtr (data z SQLite historie)
# =============================================================================

query_cooldown_tracks = """
SELECT DISTINCT track_id
FROM playlist_history_tracks
WHERE scheduled_start > :cutoff_time
"""

query_cooldown_albums = """
SELECT DISTINCT album_id
FROM playlist_history_albums
WHERE scheduled_start > :cutoff_time
"""

query_cooldown_artists = """
SELECT DISTINCT artist_id
FROM playlist_history_artists
WHERE scheduled_start > :cutoff_time
"""

# =============================================================================
# Fáze 2b: Track Artists (pro cooldown kontrolu)
# =============================================================================

query_track_artists = """
SELECT music_id, artist_id
FROM music_artists
WHERE music_id IN :track_ids
"""

# =============================================================================
# Fáze 3: Charakteristiky
# =============================================================================

query_characteristics = """
SELECT
    cc.id AS category_id,
    cc.name AS category_name,
    cc.cid AS ch_id,
    cc.cname AS ch_name
FROM characteristic_categories cc
WHERE cc.deleted = 0
ORDER BY cc.id, cc.cid
"""

# =============================================================================
# Fáze 4: Metadata pro vybrané tracky
# =============================================================================

query_metadata = """
SELECT
    m.id,
    m.name AS title,
    m.duration,
    m.year,
    m.cd_id,
    a.name AS album_name,
    (
        SELECT GROUP_CONCAT(ar.name ORDER BY ar.name SEPARATOR ', ')
        FROM music_artists ma
        JOIN artists ar ON ma.artist_id = ar.id
        WHERE ma.music_id = m.id
    ) AS artist_names
FROM music m
LEFT JOIN albums a ON m.album = a.id
WHERE m.id IN :selected_track_ids
ORDER BY FIELD(m.id, :selected_track_ids)
"""

# =============================================================================
# Schedule dotazy
# =============================================================================

query_schedule_slots = """
SELECT
    id,
    timestamp,
    duration
FROM program
WHERE
    timestamp >= :start_date
    AND timestamp < :end_date
ORDER BY timestamp
"""

# =============================================================================
# Cache Synchronizace (MariaDB → SQLite)
# =============================================================================

sync_characteristics_to_cache = """
SELECT
    u.music_id,
    cc.name AS category_name,
    c.name AS characteristic_name
FROM usage u
JOIN characteristics c ON u.characteristic_id = c.id
JOIN characteristic_categories cc ON c.category = cc.id
WHERE
    c.deleted = 0
    AND cc.id IN :gain_category_ids
"""

# =============================================================================
# History Insert (SQLite)
# =============================================================================

insert_history_tracks = """
INSERT INTO playlist_history_tracks (track_id, scheduled_start, playlist_id)
VALUES (:track_id, :scheduled_start, :playlist_id)
"""

insert_history_albums = """
INSERT INTO playlist_history_albums (album_id, scheduled_start, playlist_id)
SELECT DISTINCT m.album, :scheduled_start, :playlist_id
FROM music m
WHERE m.id IN :track_ids
"""

insert_history_artists = """
INSERT INTO playlist_history_artists (artist_id, scheduled_start, playlist_id)
SELECT DISTINCT ma.artist_id, :scheduled_start, :playlist_id
FROM music_artists ma
WHERE ma.music_id IN :track_ids
"""

"""
SQLite Client pro lokální databázi playlistů.

Zajišťuje R/W operace pro:
- Playlisty a jejich tracky
- Historie přehrávání (cooldown tracking)
- File cache
- Characteristics cache
- Validační výsledky
"""
import os
import sqlite3
from datetime import datetime
from typing import List, Set, Optional


class SQLiteClient:
    """Klient pro SQLite databázi (R/W)"""

    def __init__(self, db_path: str):
        """
        Inicializace spojení na SQLite.

        Args:
            db_path: Cesta k databázovému souboru (např. "data/playlists.db")
        """
        self.db_path = db_path
        self._connection: Optional[sqlite3.Connection] = None

    def _get_connection(self) -> sqlite3.Connection:
        """Získá nebo vytvoří spojení na databázi."""
        if self._connection is None:
            self._connection = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            self._connection.row_factory = sqlite3.Row
            # Zapnutí foreign keys
            self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection

    def close(self):
        """Uzavře spojení na databázi."""
        if self._connection:
            self._connection.close()
            self._connection = None

    def execute(self, sql: str, params: tuple = ()) -> int:
        """
        Vykoná INSERT/UPDATE/DELETE.

        Args:
            sql: SQL dotaz s ? placeholdery
            params: Parametry pro dotaz

        Returns:
            Počet ovlivněných řádků
        """
        conn = self._get_connection()
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor.rowcount

    def execute_many(self, sql: str, params_list: List[tuple]) -> int:
        """
        Vykoná batch INSERT/UPDATE/DELETE.

        Args:
            sql: SQL dotaz s ? placeholdery
            params_list: Seznam parametrů pro každý řádek

        Returns:
            Počet ovlivněných řádků
        """
        conn = self._get_connection()
        cursor = conn.executemany(sql, params_list)
        conn.commit()
        return cursor.rowcount

    def query(self, sql: str, params: tuple = ()) -> List[dict]:
        """
        Vykoná SELECT dotaz.

        Args:
            sql: SQL dotaz s ? placeholdery
            params: Parametry pro dotaz

        Returns:
            List slovníků (řádky)
        """
        conn = self._get_connection()
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def query_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """
        Vykoná SELECT a vrátí jeden řádek.

        Returns:
            Slovník s daty nebo None
        """
        conn = self._get_connection()
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    def last_insert_id(self) -> int:
        """Vrátí ID posledního vloženého záznamu."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT last_insert_rowid()")
        return cursor.fetchone()[0]

    # ==================== PLAYLIST OPERACE ====================

    def create_playlist(self, name: str, scheduled_start: datetime,
                        duration: int, preset_name: str,
                        config_json: str) -> int:
        """
        Vytvoří nový playlist.

        Args:
            name: Název playlistu (např. "Pondělí dopoledne 2025-01-27")
            scheduled_start: Začátek vysílání
            duration: Délka v sekundách
            preset_name: Název použitého presetu
            config_json: JSON s konfigurací

        Returns:
            playlist_id
        """
        sql = """
            INSERT INTO playlists (name, scheduled_start, duration, preset_name, config_json)
            VALUES (?, ?, ?, ?, ?)
        """
        self.execute(sql, (name, scheduled_start, duration, preset_name, config_json))
        return self.last_insert_id()

    def add_tracks_to_playlist(self, playlist_id: int, track_ids: List[int]):
        """
        Přidá tracky do playlistu.

        Args:
            playlist_id: ID playlistu
            track_ids: Seznam track IDs v pořadí
        """
        sql = """
            INSERT INTO playlist_tracks (playlist_id, track_id, position)
            VALUES (?, ?, ?)
        """
        # Zjisti aktuální max position
        result = self.query_one(
            "SELECT COALESCE(MAX(position), 0) as max_pos FROM playlist_tracks WHERE playlist_id = ?",
            (playlist_id,)
        )
        start_position = result['max_pos'] + 1 if result else 1

        params_list = [
            (playlist_id, track_id, start_position + i)
            for i, track_id in enumerate(track_ids)
        ]
        self.execute_many(sql, params_list)

        # Aktualizuj počet tracků v playlistu
        self.execute(
            "UPDATE playlists SET total_tracks = (SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?) WHERE id = ?",
            (playlist_id, playlist_id)
        )

    def remove_track_from_playlist(self, playlist_id: int, track_id: int):
        """
        Odstraní track z playlistu.

        Args:
            playlist_id: ID playlistu
            track_id: ID tracku k odstranění
        """
        self.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id = ? AND track_id = ?",
            (playlist_id, track_id)
        )

        # Přečísluj pozice
        tracks = self.query(
            "SELECT id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
            (playlist_id,)
        )
        for i, track in enumerate(tracks, start=1):
            self.execute(
                "UPDATE playlist_tracks SET position = ? WHERE id = ?",
                (i, track['id'])
            )

        # Aktualizuj počet tracků
        self.execute(
            "UPDATE playlists SET total_tracks = (SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?) WHERE id = ?",
            (playlist_id, playlist_id)
        )

    def get_playlist(self, playlist_id: int) -> Optional[dict]:
        """
        Načte playlist s metadaty.

        Returns:
            Dict s daty playlistu nebo None
        """
        return self.query_one(
            "SELECT * FROM playlists WHERE id = ?",
            (playlist_id,)
        )

    def get_playlist_tracks(self, playlist_id: int) -> List[int]:
        """
        Načte track IDs v pořadí.

        Returns:
            [track_id, track_id, ...] ordered by position
        """
        rows = self.query(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
            (playlist_id,)
        )
        return [row['track_id'] for row in rows]

    def update_playlist_status(self, playlist_id: int, status: str):
        """
        Aktualizuje status playlistu.

        Args:
            status: 'draft' | 'confirmed' | 'exported'
        """
        self.execute(
            "UPDATE playlists SET status = ? WHERE id = ?",
            (status, playlist_id)
        )

    # ==================== HISTORY OPERACE ====================

    def save_history(self, playlist_id: int, tracks: List[dict],
                     scheduled_start: datetime):
        """
        Uloží do sloučené playlist_history tabulky.

        Args:
            playlist_id: ID playlistu
            tracks: List dictů s klíči: track_id, album_id, artist_ids, album_type
            scheduled_start: Čas začátku playlistu
        """
        sql = """
            INSERT INTO playlist_history (playlist_id, track_id, album_id, artist_ids, scheduled_start)
            VALUES (?, ?, ?, ?, ?)
        """
        params_list = [
            (playlist_id, t['music_id'], t.get('album_id'),
             ','.join(str(a) for a in t['artist_ids']) if isinstance(t.get('artist_ids'), (set, list)) else str(t.get('artist_ids', '')),
             scheduled_start)
            for t in tracks
        ]
        self.execute_many(sql, params_list)

    def get_recent_tracks(self, cutoff: datetime) -> Set[int]:
        """
        Vrátí IDs tracků hraných po cutoff.

        Args:
            cutoff: Datetime hranice (tracky po tomto čase)

        Returns:
            Set track IDs
        """
        rows = self.query(
            "SELECT DISTINCT track_id FROM playlist_history WHERE scheduled_start > ?",
            (cutoff,)
        )
        return {row['track_id'] for row in rows}

    def get_recent_albums(self, cutoff: datetime) -> Set[int]:
        """
        Vrátí IDs alb hraných po cutoff.

        Returns:
            Set album IDs
        """
        rows = self.query(
            "SELECT DISTINCT album_id FROM playlist_history WHERE scheduled_start > ?",
            (cutoff,)
        )
        return {row['album_id'] for row in rows}

    def get_recent_artists(self, cutoff: datetime) -> Set[int]:
        """
        Vrátí IDs interpretů hraných po cutoff.

        Parsuje artist_ids sloupec (čárkami oddělená ID).

        Returns:
            Set artist IDs
        """
        rows = self.query(
            "SELECT DISTINCT artist_ids FROM playlist_history WHERE scheduled_start > ? AND artist_ids IS NOT NULL AND artist_ids != ''",
            (cutoff,)
        )
        result = set()
        for row in rows:
            for aid in str(row['artist_ids']).split(','):
                aid = aid.strip()
                if aid.isdigit():
                    result.add(int(aid))
        return result

    # ==================== FILE CACHE OPERACE ====================

    def update_file_cache(self, track_id: int, cd_id: int, file_path: Optional[str],
                          file_exists: bool, last_modified: Optional[datetime] = None):
        """
        Aktualizuje file cache.

        Args:
            track_id: ID tracku
            cd_id: ID CD
            file_path: Cesta k souboru (nebo None)
            file_exists: Zda soubor existuje
            last_modified: Timestamp poslední modifikace souboru
        """
        sql = """
            INSERT INTO file_cache (track_id, cd_id, file_path, file_exists, last_modified, last_checked)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(track_id) DO UPDATE SET
                cd_id = excluded.cd_id,
                file_path = excluded.file_path,
                file_exists = excluded.file_exists,
                last_modified = excluded.last_modified,
                last_checked = CURRENT_TIMESTAMP
        """
        self.execute(sql, (track_id, cd_id, file_path, file_exists, last_modified))

    def get_file_cache(self, track_id: int) -> Optional[dict]:
        """
        Načte z file cache.

        Returns:
            {'file_path': str, 'file_exists': bool, 'last_checked': datetime} | None
        """
        return self.query_one(
            "SELECT file_path, file_exists, last_checked, last_modified FROM file_cache WHERE track_id = ?",
            (track_id,)
        )

    def get_file_cache_batch(self, track_ids: List[int]) -> dict:
        """
        Batch načtení z file cache.

        Returns:
            {track_id: {'file_path': str, 'file_exists': bool, ...}, ...}
        """
        if not track_ids:
            return {}

        placeholders = ','.join('?' * len(track_ids))
        rows = self.query(
            f"SELECT track_id, file_path, file_exists, last_checked FROM file_cache WHERE track_id IN ({placeholders})",
            tuple(track_ids)
        )
        return {row['track_id']: row for row in rows}

    # ==================== CHARACTERISTICS CACHE ====================

    def sync_characteristics_cache(self, data: List[tuple]):
        """
        Synchronizuje characteristics cache.

        Args:
            data: [(track_id, category_name, characteristic_name), ...]
        """
        # Vymaž stará data
        self.execute("DELETE FROM characteristics_cache")

        # Vlož nová data
        sql = """
            INSERT INTO characteristics_cache (track_id, category_name, characteristic_name)
            VALUES (?, ?, ?)
        """
        self.execute_many(sql, data)

    def get_tracks_by_characteristic(self, category: str, value: str) -> Set[int]:
        """
        Rychlé filtrování podle charakteristiky.

        Example:
            cs_tracks = client.get_tracks_by_characteristic('Jazyk', 'cs')

        Returns:
            Set track IDs
        """
        rows = self.query(
            "SELECT DISTINCT track_id FROM characteristics_cache WHERE category_name = ? AND characteristic_name = ?",
            (category, value)
        )
        return {row['track_id'] for row in rows}

    def get_track_characteristics(self, track_id: int) -> List[dict]:
        """
        Načte všechny charakteristiky pro track.

        Returns:
            [{'category_name': str, 'characteristic_name': str}, ...]
        """
        return self.query(
            "SELECT category_name, characteristic_name FROM characteristics_cache WHERE track_id = ?",
            (track_id,)
        )

    # ==================== VALIDATION RESULTS ====================

    def save_validation_result(self, track_id: int, results: dict):
        """
        Uloží výsledek validace.

        Args:
            results: {
                'file_exists': bool,
                'has_isrc': bool,
                'isrc_valid': bool,
                'year_valid': bool,
                'duration_valid': bool,
                'has_artist': bool,
                'has_album': bool,
                'overall_score': int,
                'status': str,
                'notes': str
            }
        """
        sql = """
            INSERT INTO validation_results (
                track_id, file_exists, has_isrc, isrc_valid, year_valid,
                duration_valid, has_artist, has_album, overall_score, status, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_id) DO UPDATE SET
                file_exists = excluded.file_exists,
                has_isrc = excluded.has_isrc,
                isrc_valid = excluded.isrc_valid,
                year_valid = excluded.year_valid,
                duration_valid = excluded.duration_valid,
                has_artist = excluded.has_artist,
                has_album = excluded.has_album,
                overall_score = excluded.overall_score,
                status = excluded.status,
                notes = excluded.notes,
                last_validated = CURRENT_TIMESTAMP
        """
        self.execute(sql, (
            track_id,
            results.get('file_exists'),
            results.get('has_isrc'),
            results.get('isrc_valid'),
            results.get('year_valid'),
            results.get('duration_valid'),
            results.get('has_artist'),
            results.get('has_album'),
            results.get('overall_score'),
            results.get('status'),
            results.get('notes')
        ))

    def get_validation_result(self, track_id: int) -> Optional[dict]:
        """Načte výsledek validace pro track."""
        return self.query_one(
            "SELECT * FROM validation_results WHERE track_id = ?",
            (track_id,)
        )

    def get_tracks_with_validation_issues(self, status: str = 'FAIL') -> List[dict]:
        """
        Načte tracky s validačními problémy.

        Args:
            status: 'FAIL' | 'WARNING'
        """
        return self.query(
            "SELECT * FROM validation_results WHERE status = ? ORDER BY overall_score ASC",
            (status,)
        )

    # ==================== SCHEDULE SLOTS ====================

    def save_schedule_slot(self, original_id: int, slot_name: Optional[str],
                           day_of_week: int, start_time: str,
                           duration: int, preset_name: str = 'default') -> int:
        """
        Uloží schedule slot.

        Returns:
            ID vloženého slotu
        """
        sql = """
            INSERT INTO schedule_slots (original_id, slot_name, day_of_week, start_time, duration, preset_name)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        self.execute(sql, (original_id, slot_name, day_of_week, start_time, duration, preset_name))
        return self.last_insert_id()

    def get_schedule_slots(self, day_of_week: Optional[int] = None) -> List[dict]:
        """
        Načte schedule sloty.

        Args:
            day_of_week: Filtr podle dne (0=Po, 6=Ne), None = všechny
        """
        if day_of_week is not None:
            return self.query(
                "SELECT * FROM schedule_slots WHERE day_of_week = ? ORDER BY start_time",
                (day_of_week,)
            )
        return self.query("SELECT * FROM schedule_slots ORDER BY day_of_week, start_time")

    # ==================== SCHEMA INITIALIZATION ====================

    def init_schema(self):
        """Vytvoří všechny tabulky podle schema.sql."""
        schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()

        conn = self._get_connection()
        conn.executescript(schema_sql)
        conn.commit()

"""
Klient pro čtení dat z MediaLibrary SQLite databáze (data.mldb).
Pouze READ operace.
"""
import logging
import sqlite3
from typing import List, Dict, Any, Optional

import yaml

logger = logging.getLogger(__name__)


def _load_db_path() -> str:
    with open("config/database.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["sqlite"]["media_db"]


class MediaDB:
    """Read-only přístup k tabulce items v data.mldb."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _load_db_path()
        self._conn: Optional[sqlite3.Connection] = None

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def get_by_external_ids(self, external_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Načte položky z tabulky items podle seznamu externalid.

        Args:
            external_ids: Seznam externalid hodnot.

        Returns:
            Seznam slovníků s daty položek.
        """
        if not external_ids:
            return []

        # Deduplikace vstupních IDs
        unique_ids = list(dict.fromkeys(external_ids))

        conn = self._get_connection()
        placeholders = ",".join("?" for _ in unique_ids)
        query = f"SELECT DISTINCT * FROM items WHERE externalid IN ({placeholders})"
        logger.debug("MediaDB query: %s | params: %s", query, unique_ids[:20])
        rows = conn.execute(query, unique_ids).fetchall()
        logger.debug("MediaDB vrátil %d řádků pro %d unikátních IDs", len(rows), len(unique_ids))

        # Deduplikace výsledků podle externalid (ponecháme první výskyt)
        seen = set()
        result = []
        for row in rows:
            d = dict(row)
            eid = d.get('externalid')
            if eid not in seen:
                seen.add(eid)
                result.append(d)
        return result

    def get_by_ids(self, ids: List[int]) -> List[Dict[str, Any]]:
        """
        Načte položky z tabulky items podle seznamu idx (music_id).

        Args:
            ids: Seznam idx hodnot.

        Returns:
            Seznam slovníků s daty položek.
        """
        if not ids:
            return []

        conn = self._get_connection()
        placeholders = ",".join("?" for _ in ids)
        query = f"SELECT * FROM items WHERE idx IN ({placeholders})"
        rows = conn.execute(query, ids).fetchall()
        return [dict(row) for row in rows]

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

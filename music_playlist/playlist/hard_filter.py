"""
Hard filter – SQL dotaz pro získání kandidátů z MariaDB.

Blocking podmínky (nikdy se neodstraňují):
    - m.deleted = 0
    - track musí mít charakteristiku ze kategorie Jazyk (gate)
    - GROUP_CONCAT chars_ids a entity pro následné zpracování v Pythonu
"""
from __future__ import annotations

HARD_FILTER_SQL = """
SELECT
    m.id                                                            AS music_id,
    m.album                                                         AS album_id,
    m.duration,
    m.year,
    m.recording_code                                                AS isrc,
    CONCAT('[', GROUP_CONCAT(DISTINCT me.entity_id ORDER BY me.entity_id), ']')
                                                                    AS entity,
    CONCAT('{', GROUP_CONCAT(
        DISTINCT CONCAT(ch.id, ':', ch.category_id)
        ORDER BY ch.id
    ), '}')                                                         AS chars_ids
FROM music m
JOIN music_chars mc     ON mc.music_id        = m.id
JOIN characteristics ch ON ch.id              = mc.characteristic_id
LEFT JOIN music_entities me ON me.music_id    = m.id
WHERE m.deleted = 0
  AND EXISTS (
      SELECT 1 FROM music_chars mc2
      JOIN characteristics ch2 ON ch2.id = mc2.characteristic_id
      WHERE mc2.music_id   = m.id
        AND ch2.category_id = :lang_category_id
  )
GROUP BY m.id, m.album, m.duration, m.year, m.recording_code
"""


def build_hard_filter_query() -> str:
    """Vrátí SQL string pro hard filter.

    Parametry dotazu:
        :lang_category_id  – ID kategorie 'Jazyk' z DB (gate podmínka)

    Returns:
        SQL string s pojmenovanými parametry kompatibilními s MariaDB klientem.
    """
    return HARD_FILTER_SQL


def run_hard_filter(twar, lang_category_id: int) -> list[dict]:
    """Spustí hard filter dotaz a vrátí raw řádky.

    Args:
        twar:              MariaDB klient s metodou dotaz_dict(sql, params)
        lang_category_id:  ID kategorie Jazyk z DB

    Returns:
        Seznam dict řádků z DB.
    """
    return twar.dotaz_dict(
        HARD_FILTER_SQL,
        {"lang_category_id": lang_category_id},
    )

"""
ISRC normalizace pro porovnání a validaci.

ISRC formát: CC-XXX-YY-NNNNN (12 znaků bez pomlček)
Normalizace: uppercase, odstranění mezer a pomlček.
"""
from __future__ import annotations

import re

_ISRC_STRIPPED = re.compile(r"[^A-Z0-9]")


def normalize_isrc(isrc: str | None) -> str | None:
    """Normalizuje ISRC pro porovnání.

    Odstraní pomlčky, mezery, převede na uppercase.
    Vrátí None pokud je vstup prázdný nebo None.

    Args:
        isrc: Raw ISRC string (např. 'CZ-TWR-26-00042', 'czTWR2600042', ...)

    Returns:
        Normalizovaný string (např. 'CZTWR2600042') nebo None.

    Examples:
        >>> normalize_isrc('CZ-TWR-26-00042')
        'CZTWR2600042'
        >>> normalize_isrc('cztwr2600042')
        'CZTWR2600042'
        >>> normalize_isrc(None)
        None
        >>> normalize_isrc('')
        None
    """
    if not isrc:
        return None
    normalized = _ISRC_STRIPPED.sub("", isrc.upper())
    return normalized if normalized else None


def isrc_equal(a: str | None, b: str | None) -> bool:
    """Porovná dva ISRC kódy po normalizaci.

    Args:
        a: První ISRC.
        b: Druhý ISRC.

    Returns:
        True pokud jsou ISRC po normalizaci shodné, jinak False.
        Dva None kódy jsou považovány za neshodné (missing ≠ missing).
    """
    na, nb = normalize_isrc(a), normalize_isrc(b)
    if na is None or nb is None:
        return False
    return na == nb

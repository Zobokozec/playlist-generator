"""
Načítání, ukládání a správa YAML presetů pro generátor playlistů.

Preset definuje kvóty (quotas) pro jednotlivé kategorie (language, genre,
style, seasonal) a cílovou délku playlistu. Soubory jsou uloženy
v ``config/presets/<name>.yaml``.

Typické použití::

    loader = PresetLoader()
    preset = loader.load("morning_show")
    print(preset["quotas"]["language"])  # {'cs': 80, 'en': 15, 'sk': 5}

    names = loader.list_presets()
    loader.save("custom", new_quotas)
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import yaml

from utils.config_loader import CONFIG_DIR, load_yaml

logger = logging.getLogger(__name__)

PRESETS_DIR: Path = CONFIG_DIR / "presets"


class PresetLoader:
    """Načítání a správa YAML presetů.

    Loader používá jednoduchou in-memory cache – jednou načtený preset
    se znovu nečte z disku, dokud se explicitně neinvaliduje pomocí
    :meth:`reload` nebo :meth:`clear_cache`.
    """

    def __init__(self, presets_dir: Path | None = None) -> None:
        """
        Args:
            presets_dir: Adresář s preset YAML soubory.
                         Výchozí ``config/presets/``.
        """
        self._presets_dir = presets_dir or PRESETS_DIR
        self._cache: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, name: str) -> dict[str, Any]:
        """Načte preset podle jména.

        Args:
            name: Název presetu (bez přípony ``.yaml``),
                  např. ``"morning_show"``.

        Returns:
            Dict s klíči ``name``, ``description``, ``target_duration``,
            ``quotas``, ``tolerance``, ``notes``.

        Raises:
            FileNotFoundError: Preset soubor neexistuje.
            yaml.YAMLError: Nevalidní YAML.
        """
        if name in self._cache:
            logger.debug("Preset '%s' načten z cache.", name)
            return copy.deepcopy(self._cache[name])

        path = self._presets_dir / f"{name}.yaml"
        logger.info("Načítám preset '%s' z %s", name, path)
        data = load_yaml(path)
        self._cache[name] = data
        return copy.deepcopy(data)

    def list_presets(self) -> list[str]:
        """Vrátí seřazený seznam dostupných presetů (názvy bez přípony).

        Returns:
            Např. ``["default", "evening_mix", "morning_show"]``.
        """
        if not self._presets_dir.exists():
            return []
        return sorted(p.stem for p in self._presets_dir.glob("*.yaml"))

    def save(self, name: str, quotas: dict[str, dict[str, int]],
             metadata: dict[str, Any] | None = None) -> Path:
        """Uloží / aktualizuje preset na disk.

        Pokud preset se jménem *name* existuje, aktualizuje pouze ``quotas``
        (a volitelně další pole z *metadata*). Pokud neexistuje, vytvoří
        nový soubor.

        Args:
            name: Název presetu.
            quotas: ``{category: {characteristic: percent}}``.
            metadata: Volitelné další klíče (``description``,
                      ``target_duration``, ``tolerance``, ``notes``).

        Returns:
            Cesta k uloženému souboru.
        """
        path = self._presets_dir / f"{name}.yaml"

        # Načti existující nebo vytvoř kostru
        if path.exists():
            data = load_yaml(path)
        else:
            data = {"name": name}

        data["quotas"] = quotas

        if metadata:
            for key in ("description", "target_duration", "tolerance", "notes"):
                if key in metadata:
                    data[key] = metadata[key]

        # Zapiš
        self._presets_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True,
                      sort_keys=False)

        # Invaliduj cache
        self._cache.pop(name, None)
        logger.info("Preset '%s' uložen do %s", name, path)
        return path

    def reload(self, name: str) -> dict[str, Any]:
        """Znovu načte preset z disku (ignoruje cache).

        Args:
            name: Název presetu.

        Returns:
            Aktuální data presetu.
        """
        self._cache.pop(name, None)
        return self.load(name)

    def clear_cache(self) -> None:
        """Vymaže veškerou in-memory cache."""
        self._cache.clear()

    def exists(self, name: str) -> bool:
        """Zjistí, zda preset existuje na disku.

        Args:
            name: Název presetu.
        """
        return (self._presets_dir / f"{name}.yaml").is_file()

    def delete(self, name: str) -> None:
        """Smaže preset z disku i z cache.

        Args:
            name: Název presetu.

        Raises:
            FileNotFoundError: Preset neexistuje.
        """
        path = self._presets_dir / f"{name}.yaml"
        path.unlink()  # raises FileNotFoundError if missing
        self._cache.pop(name, None)
        logger.info("Preset '%s' smazán.", name)

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"PresetLoader(presets_dir={self._presets_dir!r})"

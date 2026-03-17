"""
PresetBuilder – interaktivní sestavovač YAML presetů pro generátor playlistů.

Charakteristiky a kategorie jsou načítány z char_map (viz PlaylistContext.char_map).

Použití (skript / API):
    from music_playlist.config.preset_builder import PresetBuilder

    char_map = {
        639: {"name": "Čeština",    "category": "Jazyk", "category_id": 4},
        667: {"name": "Angličtina", "category": "Jazyk", "category_id": 4},
        292: {"name": "Barok",      "category": "Žánr",  "category_id": 2},
    }
    builder = PresetBuilder(char_map)
    builder.set_name("muj_preset")
    builder.set_target_duration(7200)
    builder.add_soft_filter_include(4, [639, 667])   # Jazyk: CZ + EN → propíše do quotas
    builder.set_quota(4, 639, 60)
    builder.set_quota(4, 667, 40)
    preset = builder.build()
    path  = builder.save()

Použití (CLI):
    python -m music_playlist.config.preset_builder \\
        --name muj_preset \\
        --base music_playlist/config/presets/default.yaml \\
        --char-map char_map.json \\
        --output music_playlist/config/presets
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# ------------------------------------------------------------------
# Výchozí hodnoty (shodné s default.yaml)
# ------------------------------------------------------------------
_DEFAULT_TARGET_DURATION = 14400   # 4 hodiny
_DEFAULT_TOLERANCE = 120
_DEFAULT_DURATION_MIN = 60
_DEFAULT_DURATION_MAX = 359
_DEFAULT_YEAR_MIN = 1970


# ══════════════════════════════════════════════════════════════════
# PresetBuilder
# ══════════════════════════════════════════════════════════════════

class PresetBuilder:
    """Sestavovač YAML presetů.

    Args:
        char_map: ``{char_id: {'name': str, 'category': str, 'category_id': int}}``
                  Obvykle z ``PlaylistContext.char_map``.
    """

    def __init__(self, char_map: dict[int, dict]) -> None:
        self._char_map: dict[int, dict] = {int(k): v for k, v in char_map.items()}
        self._categories: dict[int, dict] = self._build_category_index()

        # ---- stav presetu ----
        self._name: str = "custom"
        self._description: str = ""
        self._target_duration: int = _DEFAULT_TARGET_DURATION
        self._quotas: dict[int, dict[int, int]] = {}       # {cat_id: {char_id: %}}
        self._sf_include: dict[int, list[int] | None] = {} # {cat_id: [ids] | None}
        self._sf_exclude: dict[int, list[int]] = {}         # {cat_id: [ids]}
        self._duration: dict[str, int | None] = {
            "min": _DEFAULT_DURATION_MIN,
            "max": _DEFAULT_DURATION_MAX,
        }
        self._year: dict[str, int | None] = {"min": _DEFAULT_YEAR_MIN}
        self._tolerance: int = _DEFAULT_TOLERANCE

    # ------------------------------------------------------------------
    # Privátní pomocníci
    # ------------------------------------------------------------------

    def _build_category_index(self) -> dict[int, dict]:
        """Sestaví ``{cat_id: {'name': str, 'chars': {char_id: str}}}``."""
        cats: dict[int, dict] = {}
        for char_id, info in self._char_map.items():
            cat_id = int(info["category_id"])
            if cat_id not in cats:
                cats[cat_id] = {"name": info["category"], "chars": {}}
            cats[cat_id]["chars"][char_id] = info["name"]
        return cats

    def _validate_cat(self, cat_id: int) -> None:
        if cat_id not in self._categories:
            raise ValueError(
                f"Neznámá kategorie: {cat_id}. "
                f"Dostupné: {sorted(self._categories)}"
            )

    def _validate_char(self, cat_id: int, char_id: int) -> None:
        self._validate_cat(cat_id)
        if char_id not in self._categories[cat_id]["chars"]:
            raise ValueError(
                f"Charakteristika {char_id} nepatří do kategorie {cat_id}. "
                f"Dostupné: {sorted(self._categories[cat_id]['chars'])}"
            )

    # ------------------------------------------------------------------
    # Fluent settery
    # ------------------------------------------------------------------

    def set_name(self, name: str) -> "PresetBuilder":
        """Nastaví název presetu."""
        self._name = name
        return self

    def set_description(self, description: str) -> "PresetBuilder":
        """Nastaví popis presetu."""
        self._description = description
        return self

    def set_target_duration(self, seconds: int) -> "PresetBuilder":
        """Nastaví cílovou délku playlistu v sekundách."""
        self._target_duration = int(seconds)
        return self

    def set_tolerance(self, seconds: int) -> "PresetBuilder":
        """Nastaví toleranci přetečení v sekundách."""
        self._tolerance = int(seconds)
        return self

    def set_duration_filter(
        self,
        min_s: int | None = None,
        max_s: int | None = None,
    ) -> "PresetBuilder":
        """Nastaví filtr délky skladby (sekundy)."""
        if min_s is not None:
            self._duration["min"] = int(min_s)
        if max_s is not None:
            self._duration["max"] = int(max_s)
        return self

    def set_year_filter(
        self,
        min_y: int | None = None,
        max_y: int | None = None,
    ) -> "PresetBuilder":
        """Nastaví filtr roku vydání."""
        if min_y is not None:
            self._year["min"] = int(min_y)
        if max_y is not None:
            self._year["max"] = int(max_y)
        return self

    # ------------------------------------------------------------------
    # Kvóty
    # ------------------------------------------------------------------

    def set_quota(self, cat_id: int, char_id: int, percent: int) -> "PresetBuilder":
        """Nastaví procentní kvótu pro charakteristiku.

        Args:
            cat_id:   ID kategorie.
            char_id:  ID charakteristiky.
            percent:  Požadované procento (0–100).

        Raises:
            ValueError: Neznámá kategorie nebo charakteristika.
        """
        cat_id, char_id = int(cat_id), int(char_id)
        self._validate_char(cat_id, char_id)
        self._quotas.setdefault(cat_id, {})[char_id] = int(percent)
        return self

    def remove_quota_char(self, cat_id: int, char_id: int) -> "PresetBuilder":
        """Odstraní kvótu pro jednu charakteristiku."""
        cat_id, char_id = int(cat_id), int(char_id)
        if cat_id in self._quotas:
            self._quotas[cat_id].pop(char_id, None)
            if not self._quotas[cat_id]:
                del self._quotas[cat_id]
        return self

    def remove_quota_category(self, cat_id: int) -> "PresetBuilder":
        """Odstraní všechny kvóty pro kategorii."""
        self._quotas.pop(int(cat_id), None)
        return self

    # ------------------------------------------------------------------
    # Soft filter
    # ------------------------------------------------------------------

    def add_soft_filter_include(
        self,
        cat_id: int,
        char_ids: list[int] | None,
    ) -> "PresetBuilder":
        """Přidá include pravidlo pro kategorii.

        Args:
            cat_id:   ID kategorie.
            char_ids: Seznam povolených char_id, **nebo** ``None`` → ``include: ~``
                      (kategorie je zcela vyřazena z výběru).

        Chování synchronizace s kvótami:
        - ``char_ids`` = list → kategorie se přidá do ``quotas`` s nulovými hodnotami
          pro každý includovaný char_id (uživatel je pak naplní přes :meth:`set_quota`).
        - ``char_ids`` = ``None`` → existující kvóty pro kategorii se smažou.
        """
        cat_id = int(cat_id)
        self._validate_cat(cat_id)

        if char_ids is None:
            # include: ~ → celá kategorie vyřazena
            self._sf_include[cat_id] = None
            self._quotas.pop(cat_id, None)
        else:
            ids = [int(c) for c in char_ids]
            for c in ids:
                self._validate_char(cat_id, c)
            self._sf_include[cat_id] = ids
            # Propsat do quotas – inicializuj nulové kvóty pro nové char_id
            existing = self._quotas.setdefault(cat_id, {})
            for c in ids:
                existing.setdefault(c, 0)

        return self

    def add_soft_filter_exclude(
        self,
        cat_id: int,
        char_ids: list[int],
    ) -> "PresetBuilder":
        """Přidá exclude pravidlo – vyloučí konkrétní charakteristiky z kategorie.

        Raises:
            ValueError: Neznámá kategorie nebo charakteristika.
        """
        cat_id = int(cat_id)
        ids = [int(c) for c in char_ids]
        for c in ids:
            self._validate_char(cat_id, c)
        self._sf_exclude[cat_id] = ids
        return self

    def remove_soft_filter_category(self, cat_id: int) -> "PresetBuilder":
        """Odstraní soft_filter pravidla pro kategorii."""
        cat_id = int(cat_id)
        self._sf_include.pop(cat_id, None)
        self._sf_exclude.pop(cat_id, None)
        return self

    # ------------------------------------------------------------------
    # Načtení z existujícího presetu
    # ------------------------------------------------------------------

    def load_preset(self, preset: dict) -> "PresetBuilder":
        """Načte hodnoty z existujícího preset dict.

        Vhodné pro editaci nebo ``extends`` – stav builderu se přepíše.

        Args:
            preset: Dict načtený z YAML souboru.

        Returns:
            self (pro řetězení).
        """
        self._name = preset.get("name", self._name)
        self._description = preset.get("description", self._description)
        self._target_duration = preset.get("target_duration", self._target_duration)
        self._tolerance = preset.get("tolerance", self._tolerance)

        # Kvóty
        for cat_id_s, chars in (preset.get("quotas") or {}).items():
            cat_id = int(cat_id_s)
            if isinstance(chars, dict):
                for char_id_s, pct in chars.items():
                    self._quotas.setdefault(cat_id, {})[int(char_id_s)] = int(pct)

        # Soft filter
        sf = preset.get("soft_filter") or {}
        for cat_id_s, rules in (sf.get("chars") or {}).items():
            cat_id = int(cat_id_s)
            rules = rules or {}
            if "include" in rules:
                raw_inc = rules["include"]
                self._sf_include[cat_id] = (
                    None if raw_inc is None
                    else [int(x) for x in raw_inc]
                )
            if rules.get("exclude"):
                self._sf_exclude[cat_id] = [int(x) for x in rules["exclude"]]

        dur = sf.get("duration") or {}
        if "min" in dur:
            self._duration["min"] = dur["min"]
        if "max" in dur:
            self._duration["max"] = dur["max"]

        yr = sf.get("year") or {}
        if "min" in yr:
            self._year["min"] = yr["min"]
        if "max" in yr:
            self._year["max"] = yr["max"]

        return self

    # ------------------------------------------------------------------
    # Build & Save
    # ------------------------------------------------------------------

    def build(self) -> dict[str, Any]:
        """Sestaví a vrátí preset jako dict.

        Returns:
            Preset dict kompatibilní s formátem YAML presetů generátoru.
        """
        preset: dict[str, Any] = {"name": self._name}

        if self._description:
            preset["description"] = self._description

        preset["target_duration"] = self._target_duration

        # Kvóty (string klíče – YAML konvence)
        if self._quotas:
            preset["quotas"] = {
                str(cat_id): {str(char_id): pct for char_id, pct in chars.items()}
                for cat_id, chars in self._quotas.items()
            }

        # Soft filter
        sf_chars: dict[str, Any] = {}
        for cat_id in sorted(set(self._sf_include) | set(self._sf_exclude)):
            rules: dict[str, Any] = {}
            if cat_id in self._sf_include:
                rules["include"] = self._sf_include[cat_id]  # None nebo list
            if cat_id in self._sf_exclude:
                rules["exclude"] = self._sf_exclude[cat_id]
            sf_chars[str(cat_id)] = rules

        sf: dict[str, Any] = {}
        if sf_chars:
            sf["chars"] = sf_chars
        dur = {k: v for k, v in self._duration.items() if v is not None}
        if dur:
            sf["duration"] = dur
        yr = {k: v for k, v in self._year.items() if v is not None}
        if yr:
            sf["year"] = yr

        if sf:
            preset["soft_filter"] = sf

        preset["tolerance"] = self._tolerance

        return preset

    def save(
        self,
        output_dir: str | Path = "music_playlist/config/presets",
        overwrite: bool = False,
    ) -> Path:
        """Uloží preset do YAML souboru.

        Args:
            output_dir: Cílový adresář.
            overwrite:  Přepsat existující soubor?

        Returns:
            Absolutní cesta k uloženému souboru.

        Raises:
            FileExistsError: Soubor již existuje a ``overwrite=False``.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{self._name}.yaml"

        if path.exists() and not overwrite:
            raise FileExistsError(
                f"Preset '{self._name}' již existuje: {path}. "
                f"Použij overwrite=True nebo zvol jiný název."
            )

        data = self.build()
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                data, f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
        return path

    # ------------------------------------------------------------------
    # Info helpers
    # ------------------------------------------------------------------

    def list_categories(self) -> list[tuple[int, str]]:
        """Vrátí ``[(cat_id, name), ...]`` seřazené podle cat_id."""
        return [(cid, info["name"]) for cid, info in sorted(self._categories.items())]

    def list_chars(self, cat_id: int) -> list[tuple[int, str]]:
        """Vrátí ``[(char_id, name), ...]`` pro danou kategorii.

        Raises:
            ValueError: Neznámá kategorie.
        """
        self._validate_cat(int(cat_id))
        return sorted(self._categories[int(cat_id)]["chars"].items())

    def summary(self) -> str:
        """Textové shrnutí aktuálního stavu builderu."""
        lines = [
            f"Preset: {self._name}",
            f"  target_duration : {self._target_duration} s",
            f"  tolerance       : {self._tolerance} s",
            f"  duration filter : min={self._duration.get('min')}  max={self._duration.get('max')}",
            f"  year filter     : min={self._year.get('min')}  max={self._year.get('max')}",
        ]

        if self._quotas:
            lines.append("  quotas:")
            for cat_id, chars in self._quotas.items():
                cat_name = self._categories.get(cat_id, {}).get("name", str(cat_id))
                lines.append(f"    [{cat_id}] {cat_name}:")
                for char_id, pct in chars.items():
                    char_name = (
                        self._categories.get(cat_id, {})
                        .get("chars", {})
                        .get(char_id, str(char_id))
                    )
                    lines.append(f"      [{char_id}] {char_name}: {pct}%")

        if self._sf_include or self._sf_exclude:
            lines.append("  soft_filter.chars:")
            for cat_id in sorted(set(self._sf_include) | set(self._sf_exclude)):
                cat_name = self._categories.get(cat_id, {}).get("name", str(cat_id))
                lines.append(f"    [{cat_id}] {cat_name}:")
                if cat_id in self._sf_include:
                    inc = self._sf_include[cat_id]
                    lines.append(f"      include: {'~' if inc is None else inc}")
                if cat_id in self._sf_exclude:
                    lines.append(f"      exclude: {self._sf_exclude[cat_id]}")

        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

def _prompt(msg: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"{msg}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return ans if ans else default


def _prompt_int(msg: str, default: int | None = None) -> int | None:
    default_s = str(default) if default is not None else ""
    raw = _prompt(msg, default_s)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"  ! Neplatná hodnota, použit default: {default}")
        return default


def _prompt_ids(msg: str) -> list[int]:
    raw = _prompt(msg, "")
    if not raw:
        return []
    ids = []
    for p in re.split(r"[\s,]+", raw):
        try:
            ids.append(int(p))
        except ValueError:
            pass
    return ids


def run_cli(
    char_map: dict[int, dict],
    name: str | None = None,
    base_preset: dict | None = None,
    output_dir: str | Path = "music_playlist/config/presets",
) -> dict:
    """Interaktivní CLI průvodce sestavením presetu.

    Args:
        char_map:    ``{char_id: {name, category, category_id}}``
        name:        Předvyplněný název (přeskočí prompt).
        base_preset: Výchozí preset dict pro editaci.
        output_dir:  Výstupní adresář pro uložení.

    Returns:
        Sestavený preset dict.
    """
    builder = PresetBuilder(char_map)
    if base_preset:
        builder.load_preset(base_preset)

    print("\n=== Sestavení presetu ===\n")

    # --- Název --------------------------------------------------------
    builder.set_name(_prompt("Název presetu", name or builder._name))

    # --- Target duration ----------------------------------------------
    new_dur = _prompt_int(
        "Délka playlistu (sekundy, 14400=4h, Enter=beze změny)",
        builder._target_duration,
    )
    if new_dur is not None:
        builder.set_target_duration(new_dur)

    # --- Tolerance ----------------------------------------------------
    new_tol = _prompt_int("Tolerance přetečení (s)", builder._tolerance)
    if new_tol is not None:
        builder.set_tolerance(new_tol)

    # --- Duration filter ----------------------------------------------
    print("\n--- Filtr délky skladby ---")
    dur_min = _prompt_int("Min délka skladby (s)", builder._duration.get("min"))
    dur_max = _prompt_int("Max délka skladby (s)", builder._duration.get("max"))
    builder.set_duration_filter(dur_min, dur_max)

    # --- Year filter --------------------------------------------------
    print("\n--- Filtr roku ---")
    year_min = _prompt_int("Nejstarší rok vydání (min)", builder._year.get("min"))
    year_max = _prompt_int("Nejnovější rok vydání (max, Enter=bez omezení)",
                           builder._year.get("max"))
    builder.set_year_filter(min_y=year_min, max_y=year_max)

    # --- Soft filter + quotas -----------------------------------------
    print("\n--- Soft filtr a kvóty ---")
    print("Dostupné kategorie:")
    for cat_id, cat_name in builder.list_categories():
        print(f"  [{cat_id}] {cat_name}")

    while True:
        cat_id_s = _prompt(
            "\nPřidat/upravit kategorii (ID, Enter=hotovo)", ""
        )
        if not cat_id_s:
            break
        try:
            cat_id = int(cat_id_s)
        except ValueError:
            print("  ! Neplatné ID")
            continue
        if cat_id not in builder._categories:
            print(f"  ! Kategorie {cat_id} neexistuje")
            continue

        cat_name = builder._categories[cat_id]["name"]
        print(f"\nKategorie [{cat_id}] {cat_name}")
        print("Charakteristiky:")
        for char_id, char_name in builder.list_chars(cat_id):
            print(f"  [{char_id}] {char_name}")

        mode = _prompt(
            "Režim: include / exclude / null (=vyřadit vše) / skip",
            "skip",
        ).lower()

        if mode == "skip":
            continue

        elif mode == "null":
            builder.add_soft_filter_include(cat_id, None)
            print(f"  Kategorie [{cat_id}] vyřazena (include: ~)")

        elif mode == "include":
            ids = _prompt_ids("Povolené char_id (mezery nebo čárky)")
            if not ids:
                print("  ! Žádné ID nezadáno, kategorie přeskočena")
                continue
            # Validace
            valid = [c for c in ids if c in builder._categories[cat_id]["chars"]]
            invalid = [c for c in ids if c not in builder._categories[cat_id]["chars"]]
            if invalid:
                print(f"  ! Neznámé char_id ignorovány: {invalid}")
            if not valid:
                continue
            builder.add_soft_filter_include(cat_id, valid)
            print(f"  include: {valid} → přidáno do soft_filter i quotas")
            print("  Nastavení kvót (0 = nechat jako 0, Enter=0):")
            for char_id in valid:
                char_name = builder._categories[cat_id]["chars"].get(char_id, str(char_id))
                pct = _prompt_int(f"    [{char_id}] {char_name} %", 0)
                if pct:
                    builder.set_quota(cat_id, char_id, pct)

        elif mode == "exclude":
            ids = _prompt_ids("Vyloučené char_id (mezery nebo čárky)")
            if ids:
                builder.add_soft_filter_exclude(cat_id, ids)
                print(f"  exclude: {ids}")
        else:
            print("  ! Neznámý režim")

    # --- Shrnutí a uložení --------------------------------------------
    print("\n=== Shrnutí ===")
    print(builder.summary())

    save_ans = _prompt("\nUložit preset? (y/n)", "y")
    if save_ans.lower() == "y":
        try:
            path = builder.save(output_dir)
            print(f"Preset uložen: {path}")
        except FileExistsError as exc:
            ow = _prompt(f"{exc}\nPřepsat? (y/n)", "n")
            if ow.lower() == "y":
                path = builder.save(output_dir, overwrite=True)
                print(f"Preset přepsán: {path}")

    return builder.build()


# ══════════════════════════════════════════════════════════════════
# Vstupní bod
# ══════════════════════════════════════════════════════════════════

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sestavovač YAML presetů pro generátor playlistů.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Příklady:
  # Interaktivní tvorba nového presetu
  python -m music_playlist.config.preset_builder --name ranní_show

  # Editace existujícího presetu s načtenou char_map
  python -m music_playlist.config.preset_builder \\
      --base music_playlist/config/presets/default.yaml \\
      --char-map char_map.json

  # Neinteraktivní dump char_map (pro testovací účely)
  python -m music_playlist.config.preset_builder --list-categories --char-map char_map.json
""",
    )
    parser.add_argument("--name", help="Název presetu (předvyplní prompt)")
    parser.add_argument("--base", metavar="FILE",
                        help="Základní preset YAML (cesta k souboru)")
    parser.add_argument("--char-map", dest="char_map_file", metavar="JSON",
                        help="JSON soubor s char_map (klíče = char_id jako stringy)")
    parser.add_argument("--output", default="music_playlist/config/presets",
                        metavar="DIR", help="Výstupní adresář (default: %(default)s)")
    parser.add_argument("--list-categories", action="store_true",
                        help="Vypíše dostupné kategorie a charakteristiky a skončí")
    return parser.parse_args(argv)


def _demo_char_map() -> dict[int, dict]:
    """Minimální demo char_map pro testování bez DB."""
    return {
        639: {"name": "Čeština",    "category": "Jazyk",  "category_id": 4},
        667: {"name": "Angličtina", "category": "Jazyk",  "category_id": 4},
        644: {"name": "Slovenština","category": "Jazyk",  "category_id": 4},
        292: {"name": "Barok",      "category": "Žánr",   "category_id": 2},
        472: {"name": "Metal",      "category": "Žánr",   "category_id": 2},
        148: {"name": "Gregoriánský chorál", "category": "Žánr", "category_id": 2},
        652: {"name": "Velikonoční","category": "Časové", "category_id": 28},
        656: {"name": "Dětská",     "category": "Skupiny","category_id": 5},
    }


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    # Načti char_map
    if args.char_map_file:
        with open(args.char_map_file, encoding="utf-8") as f:
            raw = json.load(f)
        char_map: dict[int, dict] = {int(k): v for k, v in raw.items()}
    else:
        print("[INFO] --char-map nezadán, používám demo data.")
        char_map = _demo_char_map()

    # Jen výpis kategorií?
    if args.list_categories:
        b = PresetBuilder(char_map)
        for cat_id, cat_name in b.list_categories():
            print(f"[{cat_id}] {cat_name}")
            for char_id, char_name in b.list_chars(cat_id):
                print(f"    [{char_id}] {char_name}")
        return

    # Načti base preset
    base: dict | None = None
    if args.base:
        with open(args.base, encoding="utf-8") as f:
            base = yaml.safe_load(f)

    run_cli(
        char_map=char_map,
        name=args.name,
        base_preset=base,
        output_dir=args.output,
    )


if __name__ == "__main__":
    main()

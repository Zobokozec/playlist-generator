"""
Testy pro PresetBuilder (music_playlist/config/preset_builder.py).

Nevyžadují připojení k DB – char_map je předán přímo.
"""
import pytest
import yaml
from pathlib import Path

from music_playlist.config.preset_builder import (
    PresetBuilder,
    _DEFAULT_TARGET_DURATION,
    _DEFAULT_TOLERANCE,
    _DEFAULT_DURATION_MIN,
    _DEFAULT_DURATION_MAX,
    _DEFAULT_YEAR_MIN,
)


# ══════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════

@pytest.fixture
def char_map():
    """Testovací char_map s jazyky, žánrem a časovými kategoriemi."""
    return {
        639: {"name": "Čeština",    "category": "Jazyk",  "category_id": 4},
        667: {"name": "Angličtina", "category": "Jazyk",  "category_id": 4},
        644: {"name": "Slovenština","category": "Jazyk",  "category_id": 4},
        292: {"name": "Barok",      "category": "Žánr",   "category_id": 2},
        472: {"name": "Metal",      "category": "Žánr",   "category_id": 2},
        652: {"name": "Velikonoční","category": "Časové", "category_id": 28},
        656: {"name": "Dětská",     "category": "Skupiny","category_id": 5},
    }


@pytest.fixture
def builder(char_map):
    return PresetBuilder(char_map)


@pytest.fixture
def default_preset_dict():
    """Minimální preset dict (odpovídá formátu YAML presetů)."""
    return {
        "name": "test_preset",
        "description": "Testovací preset",
        "target_duration": 7200,
        "quotas": {
            "4": {"639": 45, "667": 30, "644": 15},
        },
        "soft_filter": {
            "chars": {
                "2":  {"exclude": [292, 472]},
                "28": {"include": None},
            },
            "duration": {"min": 60, "max": 359},
            "year": {"min": 1970},
        },
        "tolerance": 90,
    }


# ══════════════════════════════════════════════════════════════════
# Inicializace a kategorie
# ══════════════════════════════════════════════════════════════════

class TestInit:
    def test_category_index_built(self, builder):
        cats = {cat_id for cat_id, _ in builder.list_categories()}
        assert 4 in cats   # Jazyk
        assert 2 in cats   # Žánr
        assert 28 in cats  # Časové

    def test_chars_under_correct_category(self, builder):
        lang_chars = {cid for cid, _ in builder.list_chars(4)}
        assert 639 in lang_chars
        assert 667 in lang_chars
        assert 644 in lang_chars
        assert 292 not in lang_chars   # Barok patří do Žánru, ne Jazyka

    def test_default_target_duration(self, builder):
        assert builder._target_duration == _DEFAULT_TARGET_DURATION

    def test_default_tolerance(self, builder):
        assert builder._tolerance == _DEFAULT_TOLERANCE

    def test_default_duration_filter(self, builder):
        assert builder._duration["min"] == _DEFAULT_DURATION_MIN
        assert builder._duration["max"] == _DEFAULT_DURATION_MAX

    def test_default_year_filter(self, builder):
        assert builder._year["min"] == _DEFAULT_YEAR_MIN

    def test_int_keys_normalized(self, char_map):
        """String klíče v char_map musí být normalizovány na int."""
        str_char_map = {str(k): v for k, v in char_map.items()}
        b = PresetBuilder(str_char_map)
        assert 639 in b._char_map


# ══════════════════════════════════════════════════════════════════
# Settery
# ══════════════════════════════════════════════════════════════════

class TestSetters:
    def test_set_name(self, builder):
        builder.set_name("ranní_show")
        assert builder._name == "ranní_show"

    def test_set_target_duration(self, builder):
        builder.set_target_duration(3600)
        assert builder._target_duration == 3600

    def test_set_target_duration_unchanged_by_default(self, builder):
        """Pokud set_target_duration není voláno, zůstane výchozí hodnota."""
        assert builder._target_duration == _DEFAULT_TARGET_DURATION

    def test_set_tolerance(self, builder):
        builder.set_tolerance(60)
        assert builder._tolerance == 60

    def test_set_duration_filter_partial(self, builder):
        builder.set_duration_filter(min_s=90)
        assert builder._duration["min"] == 90
        assert builder._duration["max"] == _DEFAULT_DURATION_MAX  # beze změny

    def test_set_duration_filter_both(self, builder):
        builder.set_duration_filter(min_s=90, max_s=480)
        assert builder._duration == {"min": 90, "max": 480}

    def test_set_year_filter(self, builder):
        builder.set_year_filter(min_y=1980, max_y=2024)
        assert builder._year == {"min": 1980, "max": 2024}

    def test_fluent_chaining(self, builder):
        result = (
            builder
            .set_name("test")
            .set_target_duration(3600)
            .set_tolerance(60)
        )
        assert result is builder


# ══════════════════════════════════════════════════════════════════
# Kvóty
# ══════════════════════════════════════════════════════════════════

class TestQuotas:
    def test_set_quota(self, builder):
        builder.set_quota(4, 639, 50)
        assert builder._quotas[4][639] == 50

    def test_set_quota_multiple_chars(self, builder):
        builder.set_quota(4, 639, 45)
        builder.set_quota(4, 667, 30)
        assert builder._quotas[4] == {639: 45, 667: 30}

    def test_remove_quota_char(self, builder):
        builder.set_quota(4, 639, 45)
        builder.set_quota(4, 667, 30)
        builder.remove_quota_char(4, 639)
        assert 639 not in builder._quotas[4]
        assert 667 in builder._quotas[4]

    def test_remove_quota_char_cleans_empty_category(self, builder):
        builder.set_quota(4, 639, 45)
        builder.remove_quota_char(4, 639)
        assert 4 not in builder._quotas

    def test_remove_quota_category(self, builder):
        builder.set_quota(4, 639, 45)
        builder.set_quota(4, 667, 30)
        builder.remove_quota_category(4)
        assert 4 not in builder._quotas

    def test_set_quota_unknown_category_raises(self, builder):
        with pytest.raises(ValueError, match="Neznámá kategorie"):
            builder.set_quota(999, 639, 50)

    def test_set_quota_unknown_char_raises(self, builder):
        with pytest.raises(ValueError, match="nepatří do kategorie"):
            builder.set_quota(4, 9999, 50)

    def test_set_quota_wrong_category_for_char_raises(self, builder):
        """char_id 292 (Barok) patří do Žánru (2), ne do Jazyka (4)."""
        with pytest.raises(ValueError):
            builder.set_quota(4, 292, 10)


# ══════════════════════════════════════════════════════════════════
# Soft filter
# ══════════════════════════════════════════════════════════════════

class TestSoftFilter:
    def test_add_include_propagates_to_quotas(self, builder):
        """Přidání include → kategorie se propíše do quotas."""
        builder.add_soft_filter_include(4, [639, 667])
        assert 4 in builder._quotas
        assert 639 in builder._quotas[4]
        assert 667 in builder._quotas[4]

    def test_add_include_quota_default_zero(self, builder):
        builder.add_soft_filter_include(4, [639, 667])
        assert builder._quotas[4][639] == 0
        assert builder._quotas[4][667] == 0

    def test_add_include_does_not_overwrite_existing_quota(self, builder):
        """Již nastavená kvóta se při add_include nepřepíše."""
        builder.set_quota(4, 639, 50)
        builder.add_soft_filter_include(4, [639, 667])
        assert builder._quotas[4][639] == 50  # beze změny

    def test_add_include_null_excludes_all(self, builder):
        """include: None → include: ~ → vyřadit celou kategorii."""
        builder.add_soft_filter_include(28, None)
        assert builder._sf_include[28] is None

    def test_add_include_null_removes_quotas(self, builder):
        """include: ~ → kvóty pro kategorii se smažou."""
        builder.set_quota(28, 652, 5)
        builder.add_soft_filter_include(28, None)
        assert 28 not in builder._quotas

    def test_add_exclude(self, builder):
        builder.add_soft_filter_exclude(2, [292, 472])
        assert builder._sf_exclude[2] == [292, 472]

    def test_add_exclude_does_not_touch_quotas(self, builder):
        builder.set_quota(2, 292, 10)
        builder.add_soft_filter_exclude(2, [292])
        assert 2 in builder._quotas   # kvóty se nesmažou

    def test_remove_soft_filter_category(self, builder):
        builder.add_soft_filter_include(4, [639])
        builder.add_soft_filter_exclude(4, [644])
        builder.remove_soft_filter_category(4)
        assert 4 not in builder._sf_include
        assert 4 not in builder._sf_exclude

    def test_add_include_unknown_category_raises(self, builder):
        with pytest.raises(ValueError, match="Neznámá kategorie"):
            builder.add_soft_filter_include(999, [639])

    def test_add_include_unknown_char_raises(self, builder):
        with pytest.raises(ValueError):
            builder.add_soft_filter_include(4, [9999])

    def test_add_exclude_unknown_char_raises(self, builder):
        with pytest.raises(ValueError):
            builder.add_soft_filter_exclude(4, [9999])


# ══════════════════════════════════════════════════════════════════
# load_preset
# ══════════════════════════════════════════════════════════════════

class TestLoadPreset:
    def test_loads_name(self, builder, default_preset_dict):
        builder.load_preset(default_preset_dict)
        assert builder._name == "test_preset"

    def test_loads_target_duration(self, builder, default_preset_dict):
        builder.load_preset(default_preset_dict)
        assert builder._target_duration == 7200

    def test_loads_quotas(self, builder, default_preset_dict):
        builder.load_preset(default_preset_dict)
        assert builder._quotas[4][639] == 45
        assert builder._quotas[4][667] == 30

    def test_loads_sf_exclude(self, builder, default_preset_dict):
        builder.load_preset(default_preset_dict)
        assert 292 in builder._sf_exclude[2]
        assert 472 in builder._sf_exclude[2]

    def test_loads_sf_include_null(self, builder, default_preset_dict):
        """include: None z YAML → sf_include[28] = None."""
        builder.load_preset(default_preset_dict)
        assert builder._sf_include[28] is None

    def test_loads_duration_filter(self, builder, default_preset_dict):
        builder.load_preset(default_preset_dict)
        assert builder._duration["min"] == 60
        assert builder._duration["max"] == 359

    def test_loads_year_filter(self, builder, default_preset_dict):
        builder.load_preset(default_preset_dict)
        assert builder._year["min"] == 1970

    def test_loads_tolerance(self, builder, default_preset_dict):
        builder.load_preset(default_preset_dict)
        assert builder._tolerance == 90

    def test_missing_keys_use_defaults(self, builder):
        """Prázdný preset → výchozí hodnoty builderu."""
        builder.load_preset({})
        assert builder._target_duration == _DEFAULT_TARGET_DURATION
        assert builder._tolerance == _DEFAULT_TOLERANCE

    def test_returns_self(self, builder, default_preset_dict):
        result = builder.load_preset(default_preset_dict)
        assert result is builder


# ══════════════════════════════════════════════════════════════════
# build()
# ══════════════════════════════════════════════════════════════════

class TestBuild:
    def test_build_contains_name(self, builder):
        builder.set_name("muj_preset")
        preset = builder.build()
        assert preset["name"] == "muj_preset"

    def test_build_contains_target_duration(self, builder):
        builder.set_target_duration(3600)
        preset = builder.build()
        assert preset["target_duration"] == 3600

    def test_build_no_description_if_empty(self, builder):
        preset = builder.build()
        assert "description" not in preset

    def test_build_description_included(self, builder):
        builder.set_description("Testovací popis")
        preset = builder.build()
        assert preset["description"] == "Testovací popis"

    def test_build_quotas_string_keys(self, builder):
        """Kvóty musí mít string klíče (YAML konvence)."""
        builder.set_quota(4, 639, 45)
        preset = builder.build()
        assert "4" in preset["quotas"]
        assert "639" in preset["quotas"]["4"]

    def test_build_no_quotas_if_empty(self, builder):
        preset = builder.build()
        assert "quotas" not in preset

    def test_build_soft_filter_include_null(self, builder):
        """include: ~ musí být None (ne prázdný list)."""
        builder.add_soft_filter_include(28, None)
        preset = builder.build()
        assert preset["soft_filter"]["chars"]["28"]["include"] is None

    def test_build_soft_filter_include_list(self, builder):
        builder.add_soft_filter_include(4, [639, 667])
        preset = builder.build()
        assert preset["soft_filter"]["chars"]["4"]["include"] == [639, 667]

    def test_build_soft_filter_exclude(self, builder):
        builder.add_soft_filter_exclude(2, [292, 472])
        preset = builder.build()
        assert preset["soft_filter"]["chars"]["2"]["exclude"] == [292, 472]

    def test_build_soft_filter_duration(self, builder):
        builder.set_duration_filter(min_s=90, max_s=480)
        preset = builder.build()
        assert preset["soft_filter"]["duration"] == {"min": 90, "max": 480}

    def test_build_soft_filter_year(self, builder):
        builder.set_year_filter(min_y=1980)
        preset = builder.build()
        assert preset["soft_filter"]["year"]["min"] == 1980

    def test_build_tolerance(self, builder):
        builder.set_tolerance(60)
        preset = builder.build()
        assert preset["tolerance"] == 60

    def test_build_no_soft_filter_if_nothing_set(self, builder):
        """Bez nastavení filtrů nesmí být 'soft_filter' ve výstupu."""
        builder._duration = {}
        builder._year = {}
        preset = builder.build()
        assert "soft_filter" not in preset

    def test_build_roundtrip_via_load_preset(self, builder, char_map):
        """build() → load_preset() → build() musí dát shodný výsledek."""
        builder.set_name("roundtrip")
        builder.set_target_duration(7200)
        builder.add_soft_filter_include(4, [639, 667])
        builder.set_quota(4, 639, 60)
        builder.set_quota(4, 667, 40)
        preset_a = builder.build()

        builder2 = PresetBuilder(char_map)
        builder2.load_preset(preset_a)
        preset_b = builder2.build()

        assert preset_a == preset_b

    def test_build_soft_filter_propagation_full(self, builder):
        """Přidání include → build() vrátí kategorii v obou soft_filter i quotas."""
        builder.add_soft_filter_include(4, [639, 667])
        builder.set_quota(4, 639, 60)
        builder.set_quota(4, 667, 40)
        preset = builder.build()

        assert "4" in preset["quotas"]
        assert preset["quotas"]["4"]["639"] == 60
        assert "4" in preset["soft_filter"]["chars"]
        assert preset["soft_filter"]["chars"]["4"]["include"] == [639, 667]


# ══════════════════════════════════════════════════════════════════
# save()
# ══════════════════════════════════════════════════════════════════

class TestSave:
    def test_save_creates_yaml_file(self, builder, tmp_path):
        builder.set_name("save_test")
        path = builder.save(tmp_path)
        assert path.exists()
        assert path.suffix == ".yaml"
        assert path.stem == "save_test"

    def test_save_yaml_is_valid(self, builder, tmp_path):
        builder.set_name("valid_yaml")
        builder.set_target_duration(3600)
        path = builder.save(tmp_path)
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["name"] == "valid_yaml"
        assert data["target_duration"] == 3600

    def test_save_raises_if_exists(self, builder, tmp_path):
        builder.set_name("exists")
        builder.save(tmp_path)
        with pytest.raises(FileExistsError):
            builder.save(tmp_path)

    def test_save_overwrite(self, builder, tmp_path):
        builder.set_name("overwrite")
        builder.save(tmp_path)
        builder.set_target_duration(1800)
        path = builder.save(tmp_path, overwrite=True)
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["target_duration"] == 1800

    def test_save_creates_output_dir(self, builder, tmp_path):
        out = tmp_path / "new_subdir"
        builder.set_name("subdir_test")
        builder.save(out)
        assert (out / "subdir_test.yaml").exists()

    def test_save_returns_path(self, builder, tmp_path):
        builder.set_name("path_test")
        result = builder.save(tmp_path)
        assert isinstance(result, Path)


# ══════════════════════════════════════════════════════════════════
# list_categories / list_chars
# ══════════════════════════════════════════════════════════════════

class TestHelpers:
    def test_list_categories_sorted(self, builder):
        cats = builder.list_categories()
        ids = [c for c, _ in cats]
        assert ids == sorted(ids)

    def test_list_categories_all_present(self, builder):
        ids = {c for c, _ in builder.list_categories()}
        assert {2, 4, 5, 28} == ids

    def test_list_chars_correct_category(self, builder):
        lang_chars = {c for c, _ in builder.list_chars(4)}
        assert lang_chars == {639, 667, 644}

    def test_list_chars_unknown_category_raises(self, builder):
        with pytest.raises(ValueError):
            builder.list_chars(999)

    def test_summary_contains_name(self, builder):
        builder.set_name("summary_test")
        assert "summary_test" in builder.summary()

    def test_summary_contains_quotas(self, builder):
        builder.set_quota(4, 639, 45)
        summary = builder.summary()
        assert "639" in summary
        assert "45%" in summary

    def test_summary_contains_include_null(self, builder):
        builder.add_soft_filter_include(28, None)
        assert "include: ~" in builder.summary()


# ══════════════════════════════════════════════════════════════════
# Integrace – načtení default.yaml
# ══════════════════════════════════════════════════════════════════

class TestDefaultYamlIntegration:
    """Testy, které načítají skutečný default.yaml (pokud existuje)."""

    DEFAULT_YAML = Path(__file__).parent.parent / "music_playlist/config/presets/default.yaml"

    def test_load_default_yaml(self, builder):
        if not self.DEFAULT_YAML.exists():
            pytest.skip("default.yaml neexistuje")
        with open(self.DEFAULT_YAML, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        builder.load_preset(data)
        assert builder._name == "default"

    def test_default_yaml_target_duration(self, builder):
        if not self.DEFAULT_YAML.exists():
            pytest.skip("default.yaml neexistuje")
        with open(self.DEFAULT_YAML, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        builder.load_preset(data)
        assert builder._target_duration == 14400

    def test_default_yaml_sf_include_null_category_28(self, builder):
        if not self.DEFAULT_YAML.exists():
            pytest.skip("default.yaml neexistuje")
        with open(self.DEFAULT_YAML, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        builder.load_preset(data)
        # V default.yaml má kategorie 28 include: ~
        assert builder._sf_include.get(28) is None

"""Exact catalog lookup tests written before ray-index metadata implementation."""

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from optics_ui.services.files import FileDataService
from optics_ui.services.materials import load_ray_indices


IDS = [
    "SCHOTT_N_BK7", "SCHOTT_N_SF6HTULTRA", "PMMA_PLEXIGLAS_8N_PROXY",
    "PMMA_DELPET_80NH_PROXY", "PC_MAKROLON_LED2245_PROXY", "PC_LEXAN_OQ3820_PROXY",
]
VALUES = [1.5187219714708264, 1.8126590955276354, 1.4926111347569782,
          1.4926111347569782, 1.5897533225135922, 1.595537564]
CONDITIONS = {
    "temperature_c": 20, "temperature_source": "analysis_metadata",
    "wavelengths_nm": [450, 546.074], "primary_wavelength_nm": 546.074,
    "wavelength_source": "analysis_metadata", "assumed_fields": [],
}


class MaterialIndicesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="optics-indices-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name).resolve()
        self.database = self.folder / "cases.sqlite"
        self.catalog = self.folder / "materials/catalog.sqlite"
        self.catalog.parent.mkdir()
        with sqlite3.connect(self.catalog) as connection:
            connection.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
                INSERT INTO metadata VALUES ('schema_version','fixture-1');
                CREATE TABLE materials(material_id TEXT PRIMARY KEY, nd_calculated REAL);
                CREATE TABLE refractive_index_samples(
                    material_id TEXT, wavelength_nm REAL, temperature_c REAL,
                    refractive_index REAL, n_model_id TEXT, n_is_proxy INTEGER,
                    is_extrapolated INTEGER, source_quality TEXT,
                    PRIMARY KEY(material_id,wavelength_nm,temperature_c));
            """)
            for index, (material_id, value) in enumerate(zip(IDS, VALUES)):
                connection.execute("INSERT INTO materials VALUES (?,1.4)", (material_id,))
                connection.execute("INSERT INTO refractive_index_samples VALUES (?,?,?,?,?,?,?,?)",
                                   (material_id, 546.074, 20, value, "model::" + material_id,
                                    int(index >= 2), 0, "fixture_manufacturer" if index < 2 else "fixture_polymer_proxy"))
            connection.execute("INSERT INTO refractive_index_samples VALUES (?,?,?,?,?,?,?,?)",
                               (IDS[0], 450, 20, 1.525, "blue-fixture", 0, 0, "fixture"))

    def lookup(self, conditions=None, material_ids=None, metadata=None):
        return load_ray_indices(
            database_path=self.database,
            database_metadata=metadata if metadata is not None else {"material_catalog_path": "materials/catalog.sqlite"},
            material_ids=material_ids if material_ids is not None else IDS,
            analysis_conditions=CONDITIONS if conditions is None else conditions,
        )

    def test_primary_wavelength_is_preserved_with_multiple_wavelengths(self):
        result = self.lookup()
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["wavelength_nm"], 546.074)
        self.assertEqual(result["temperature_c"], 20)
        self.assertEqual(result["indices"], dict(zip(IDS, VALUES)))
        self.assertEqual(result["missing_material_ids"], [])

    def test_proxy_and_source_metadata_are_preserved_per_material(self):
        result = self.lookup()
        source = result["provenance"]["materials"]
        self.assertEqual(source[IDS[0]]["n_is_proxy"], 0)
        self.assertEqual(source[IDS[2]]["n_is_proxy"], 1)
        self.assertEqual(source[IDS[0]]["n_model_id"], "model::" + IDS[0])
        self.assertEqual(source[IDS[0]]["source_quality"], "fixture_manufacturer")
        self.assertEqual(result["provenance"]["lookup"], "exact_sample")

    def test_missing_primary_uses_first_valid_wavelength_not_560_or_nd(self):
        conditions = CONDITIONS | {"primary_wavelength_nm": None, "wavelengths_nm": [None, -1, 450, 546.074]}
        result = self.lookup(conditions, [IDS[0]])
        self.assertEqual(result["wavelength_nm"], 450)
        self.assertEqual(result["indices"][IDS[0]], 1.525)
        self.assertNotEqual(result["indices"][IDS[0]], 1.4)

    def test_missing_metadata_defaults_are_explicit_display_conditions(self):
        result = self.lookup({})
        self.assertEqual(result["wavelength_nm"], 560)
        self.assertEqual(result["temperature_c"], 25)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["indices"], {})
        self.assertEqual(result["provenance"]["condition_sources"]["wavelength"], "display_default")

    def test_existing_display_fallback_provenance_is_not_reclassified_as_metadata(self):
        conditions = {"temperature_c": 25, "wavelengths_nm": [560], "primary_wavelength_nm": 560,
                      "temperature_source": "display_default", "wavelength_source": "display_default",
                      "assumed_fields": ["temperature_c", "wavelengths_nm"]}
        result = self.lookup(conditions)
        self.assertEqual(result["provenance"]["condition_sources"]["temperature"], "display_default")
        self.assertEqual(result["provenance"]["condition_sources"]["wavelength"], "display_default")

    def test_unmatched_wavelength_or_temperature_never_uses_nearest_row(self):
        for conditions in (CONDITIONS | {"primary_wavelength_nm": 560},
                           CONDITIONS | {"temperature_c": 25}):
            with self.subTest(conditions=conditions):
                result = self.lookup(conditions)
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["indices"], {})
                self.assertEqual(set(result["missing_material_ids"]), set(IDS))
                self.assertTrue(any(w["code"] == "MATERIAL_INDEX_MISSING" for w in result["warnings"]))

    def test_partial_catalog_preserves_exact_values_and_reports_missing_material(self):
        with sqlite3.connect(self.catalog) as connection:
            connection.execute("DELETE FROM refractive_index_samples WHERE material_id=?", (IDS[-1],))
        result = self.lookup()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["indices"]), 5)
        self.assertEqual(result["missing_material_ids"], [IDS[-1]])
        self.assertNotIn(IDS[-1], result["indices"])

    def test_missing_catalog_reference_or_file_is_a_diagnostic(self):
        self.assertEqual(self.lookup(metadata={})["status"], "unavailable")
        self.catalog.unlink()
        result = self.lookup()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["indices"], {})
        self.assertTrue(result["warnings"])

    def test_legacy_catalog_without_index_table_does_not_fall_back_to_nd(self):
        with sqlite3.connect(self.catalog) as connection:
            connection.execute("DROP TABLE refractive_index_samples")
        result = self.lookup()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["indices"], {})
        self.assertTrue(any(w["code"] == "MATERIAL_CATALOG_SCHEMA" for w in result["warnings"]))

    def test_invalid_index_is_omitted_instead_of_replaced(self):
        with sqlite3.connect(self.catalog) as connection:
            connection.execute("UPDATE refractive_index_samples SET refractive_index=0 WHERE material_id=?", (IDS[0],))
        result = self.lookup()
        self.assertEqual(result["status"], "partial")
        self.assertNotIn(IDS[0], result["indices"])
        self.assertTrue(any(w["code"] == "MATERIAL_INDEX_INVALID" for w in result["warnings"]))

    def test_lookup_is_read_only(self):
        before = hashlib.sha256(self.catalog.read_bytes()).hexdigest()
        self.lookup()
        self.assertEqual(hashlib.sha256(self.catalog.read_bytes()).hexdigest(), before)

    def make_optical_database(self):
        sql = (Path(__file__).parent / "fixtures/file_data_minimal.sql").read_text()
        with sqlite3.connect(self.database) as connection:
            connection.executescript(sql)
            connection.execute("UPDATE lens_elements SET material_id=? WHERE material_id='BK7'", (IDS[0],))
            connection.execute("UPDATE lens_elements SET material_id=? WHERE material_id='SF6'", (IDS[1],))
            for index, material_id in enumerate(IDS[2:], start=1):
                connection.execute("INSERT INTO lens_elements VALUES ('D2',?,?,2,1,2)", (index, material_id))
            connection.execute("DELETE FROM wavelengths WHERE design_id='D1'")
            connection.executemany("INSERT INTO wavelengths VALUES ('D1',?,?,?,?)",
                                   [(1, 450, .4, 0), (2, 546.074, .6, 1)])
            connection.execute("UPDATE analyses SET settings_json=? WHERE analysis_type='FFT_MTF'",
                               (json.dumps({"temperature_c": 20, "wavelengths_nm": [450, 546.074]}),))

    def test_case_load_includes_indices_for_every_selectable_material(self):
        self.make_optical_database()
        result = FileDataService().load_case(self.database, "D1")
        self.assertEqual(len({row["material_id"] for row in result["lenses"]}), 2)
        self.assertEqual(len(result["materials"]), 6)
        self.assertEqual(result["ray_indices"]["status"], "available")
        self.assertEqual(set(result["ray_indices"]["indices"]), set(result["materials"]))
        self.assertEqual(result["ray_indices"]["wavelength_nm"], result["primary_wavelength_nm"])
        self.assertIsNone(result["relative_illumination"])
        self.assertTrue(all(row["a12"] is None for row in result["surfaces"]))

    def test_missing_catalog_does_not_prevent_loading_the_case(self):
        self.make_optical_database()
        self.catalog.unlink()
        result = FileDataService().load_case(self.database, "D1")
        self.assertEqual(result["id"], "D1")
        self.assertEqual(len(result["surfaces"]), 6)
        self.assertEqual(result["ray_indices"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main(verbosity=2)

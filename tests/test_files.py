"""File/data service acceptance tests written before implementation."""

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock
import zipfile

from optics_ui.services.files import FileDataError, FileDataService


SQL = (Path(__file__).parent / "fixtures/file_data_minimal.sql").read_text()


class FileDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="optics-files-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve() / "원본 files"
        self.folder.mkdir()
        self.db = self.folder / "cases.sqlite"
        with sqlite3.connect(self.db) as connection:
            connection.executescript(SQL)
        catalog = self.folder / "materials/catalog.sqlite"
        catalog.parent.mkdir()
        with sqlite3.connect(catalog) as connection:
            connection.execute("CREATE TABLE materials (id TEXT)")
            connection.execute("INSERT INTO materials VALUES ('BK7')")
        self.model = self.folder / "model.pth"
        self.model.write_bytes(b"opaque-model-not-a-valid-pickle\x00\xff")
        self.report = self.folder / "report.json"
        self.report_data = {"report_version": 1,
                            "model": {"filename": self.model.name, "id": "m1", "sha256": self.digest(self.model)},
                            "database": {"filename": self.db.name, "id": "db-a", "schema_version": "1.0.0"},
                            "trained_cases": ["D1"], "suggested_case_id": "D1"}
        self.write_report()
        self.target = self.folder / "targets.json"
        self.target.write_text(json.dumps({"profile_id": "t1", "goals": [{"name": "spot", "target": 1.6}]}))
        self.references = {"report_path": str(self.report), "database_path": str(self.db), "target_path": str(self.target)}
        self.state = {"parameters": {"a12": None, "thickness": 6.0, "active": True},
                      "camera": [1, 2, 3], "llm": {"draft": "색수차를 줄여줘"},
                      "jobs": [{"status": "running", "request_id": "old"}], "extraFutureField": {"anything": [0, False, ""]}}
        self.service = FileDataService()

    @staticmethod
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def write_report(self):
        self.report.write_text(json.dumps(self.report_data), encoding="utf-8")

    def assert_code(self, code, callable_, *args):
        with self.assertRaises(FileDataError) as raised:
            callable_(*args)
        self.assertEqual(raised.exception.code, code)
        self.assertIsInstance(raised.exception.message, str)
        self.assertTrue(raised.exception.message)

    def test_load_canonical_report_without_deserializing_model(self):
        result = self.service.load_report(self.report)
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["model_id"], "m1")
        self.assertEqual(result["database_id"], "db-a")
        self.assertEqual(result["suggested_case_id"], "D1")
        self.assertFalse(result["model_deserialized"])
        self.assertEqual(result["model_path"], str(self.model))
        self.assertEqual(result["report"]["trained_cases"], ["D1"])

    def test_explicit_legacy_fixture_aliases_are_normalized(self):
        self.report_data = {"report_version": 1, "model_id": "m1", "model_file": "model.pth",
                            "database_file": "cases.sqlite", "database_id": "db-a", "database_schema": "1.0.0"}
        self.write_report()
        result = self.service.load_report(self.report)
        self.assertEqual(result["report"]["model"], {"filename": "model.pth", "id": "m1"})
        self.assertEqual(result["database_path"], str(self.db))

    def test_missing_model_and_database_have_distinct_errors(self):
        self.model.unlink()
        self.assert_code("MISSING_MODEL", self.service.load_report, self.report)
        self.model.write_bytes(b"restored")
        self.report_data["model"].pop("sha256")
        self.write_report()
        self.db.unlink()
        self.assert_code("MISSING_DATABASE", self.service.load_report, self.report)

    def test_malformed_report_and_wrong_version_are_rejected(self):
        self.report.write_text("{ invalid")
        self.assert_code("REPORT_JSON", self.service.load_report, self.report)
        self.report.write_text("[]")
        self.assert_code("REPORT_SCHEMA", self.service.load_report, self.report)
        self.report_data["report_version"] = 2
        self.write_report()
        self.assert_code("REPORT_SCHEMA", self.service.load_report, self.report)

    def test_model_and_database_must_be_siblings(self):
        self.report_data["model"]["filename"] = "../model.pth"
        self.write_report()
        self.assert_code("SIBLING_PATH", self.service.load_report, self.report)

    def test_declared_model_hash_mismatch_is_rejected(self):
        self.model.write_bytes(b"different opaque data")
        self.assert_code("MODEL_HASH_MISMATCH", self.service.load_report, self.report)

    def test_database_logical_id_and_schema_mismatches_are_rejected(self):
        self.report_data["database"]["id"] = "wrong"
        self.write_report()
        self.assert_code("DATABASE_ID_MISMATCH", self.service.load_report, self.report)
        self.report_data["database"]["id"] = "db-a"
        self.report_data["database"]["schema_version"] = "different"
        self.write_report()
        self.assert_code("DATABASE_SCHEMA_MISMATCH", self.service.load_report, self.report)

    def test_undeclared_optional_database_identity_does_not_invent_one(self):
        self.report_data["database"] = {"filename": self.db.name}
        self.write_report()
        self.assertEqual(self.service.load_report(self.report)["status"], "valid")

    def test_normal_database_append_is_not_a_file_hash_mismatch(self):
        self.report_data["database"]["sha256"] = self.digest(self.db)
        self.write_report()
        with sqlite3.connect(self.db) as connection:
            connection.execute("INSERT INTO designs VALUES ('D3','F3',1,1,1,'SUCCESS','SYNTHETIC_MATH_PROXY',0)")
        result = self.service.load_report(self.report)
        self.assertEqual(result["status"], "valid")
        self.assertNotEqual(self.digest(self.db), result["report"]["database"]["sha256"])

    def test_training_membership_counts_new_cases_without_claiming_eligibility(self):
        summary = self.service.load_report(self.report)["training_summary"]
        self.assertEqual(summary["status"], "available")
        self.assertEqual(summary["trained_count"], 1)
        self.assertEqual(summary["new_case_count"], 1)
        self.assertIsNone(summary["changed_case_count"])
        self.assertTrue(summary["discovery_only"])

    def test_missing_training_membership_is_unknown_not_zero(self):
        self.report_data.pop("trained_cases")
        self.write_report()
        summary = self.service.load_report(self.report)["training_summary"]
        self.assertEqual(summary["status"], "unavailable")
        self.assertIsNone(summary["trained_count"])
        self.assertIsNone(summary["new_case_count"])

    def test_explicit_training_case_ids_are_normalized_and_deduplicated(self):
        self.report_data.pop("trained_cases")
        self.report_data["training"] = {"case_ids": ["D1", "D1"]}
        self.write_report()
        self.assertEqual(self.service.load_report(self.report)["training_summary"]["trained_count"], 1)

    def test_training_case_prescription_fingerprint_detects_changed_case(self):
        self.report_data.pop("trained_cases")
        self.report_data["training"] = {"cases": [{"case_id": "D1", "prescription_hash": "old-hash"}]}
        self.write_report()
        with sqlite3.connect(self.db) as connection:
            connection.execute("ALTER TABLE designs ADD COLUMN prescription_hash TEXT")
            connection.execute("UPDATE designs SET prescription_hash='new-hash' WHERE design_id='D1'")
        summary = self.service.load_report(self.report)["training_summary"]
        self.assertEqual(summary["changed_case_count"], 1)
        self.assertEqual(summary["change_detection_scope"], "prescription_hash_only")

    def test_load_case_preserves_units_values_nulls_and_actual_conditions(self):
        result = self.service.load_case(self.db, "D1")
        self.assertEqual(result["id"], "D1")
        self.assertEqual(len(result["lenses"]), 3)
        self.assertEqual(len(result["surfaces"]), 6)
        self.assertEqual(result["surfaces"][1]["radius_mm"], -60)
        self.assertTrue(all(surface["a12"] is None for surface in result["surfaces"]))
        self.assertIsNone(result["relative_illumination"])
        self.assertEqual(result["temperature_c"], 20)
        self.assertEqual(result["analysis_conditions"]["wavelengths_nm"], [486.1327, 656.2725])
        self.assertEqual(result["primary_wavelength_nm"], 656.2725)
        self.assertEqual(len(result["mtf"]), 2)
        self.assertEqual(len(result["spot"]), 2)
        self.assertEqual(result["spot_summary"][0]["rms_radius_mm_proxy"], 0.0008)
        self.assertEqual(result["metrics"][0]["horizontal_fov_deg"], 24)

    def test_case_load_does_not_change_source_database(self):
        before = self.digest(self.db)
        self.service.load_case(self.db, "D1")
        self.assertEqual(self.digest(self.db), before)

    def test_missing_case_is_distinct_from_failed_case(self):
        self.assert_code("CASE_NOT_FOUND", self.service.load_case, self.db, "absent")
        result = self.service.load_case(self.db, "D2")
        self.assertEqual(result["design"][0]["overall_status"], "FAILED")
        self.assertEqual(result["mtf"], [])
        self.assertEqual(result["metrics"], [])

    def test_list_cases_uses_status_and_metrics_without_claiming_best(self):
        rows = self.service.list_cases(self.db)
        self.assertEqual([row["id"] for row in rows], ["D1", "D2"])
        self.assertEqual(rows[0]["spot_rms_diameter_um"], 1.6)
        self.assertEqual(rows[0]["horizontal_fov_deg"], 24)
        self.assertEqual(rows[1]["status"], "FAILED")
        self.assertIsNone(rows[1]["spot_rms_diameter_um"])
        self.assertFalse(any("best" in row for row in rows))

    def test_case_material_options_are_from_whole_database_and_coefficients_are_preserved(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("INSERT INTO lens_elements VALUES ('D2',1,'PMMA',2,1,2)")
        result = self.service.load_case(self.db, "D1")
        self.assertEqual(result["materials"], ["BK7", "PMMA", "SF6"])
        self.assertEqual(json.loads(result["surfaces"][2]["raw_surface_json"])["a4"], 0.000001)

    def test_case_compatibility_flags_do_not_convert_unsupported_surfaces(self):
        self.assertTrue(self.service.list_cases(self.db)[0]["ui_compatible"])
        self.assertFalse(self.service.list_cases(self.db)[1]["ui_compatible"])
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE surfaces SET surface_type='ODD_ASPHERE' WHERE design_id='D1' AND surface_index=3")
        self.assertFalse(self.service.list_cases(self.db)[0]["ui_compatible"])
        self.assertEqual(self.service.load_case(self.db, "D1")["surfaces"][2]["surface_type"], "ODD_ASPHERE")

    def test_target_profile_is_read_only_json_object(self):
        before = self.digest(self.target)
        result = self.service.load_target(self.target)
        self.assertTrue(result["read_only"])
        self.assertEqual(result["profile"]["profile_id"], "t1")
        self.assertEqual(result["schema_validation"], "json_object_only")
        self.assertEqual(self.digest(self.target), before)
        self.target.write_text("[]")
        self.assert_code("TARGET_SCHEMA", self.service.load_target, self.target)

    def test_session_roundtrip_preserves_opaque_ui_state_but_never_resumes_jobs(self):
        path = self.folder / "work.optics.json"
        result = self.service.save_session(path, self.state, self.references)
        self.assertEqual(result["status"], "saved")
        stored = json.loads(path.read_text())
        self.assertEqual(stored["format"], "optics-ui-session")
        self.assertEqual(stored["schema_version"], 1)
        self.assertEqual(stored["references"]["report_path"], "report.json")
        loaded = self.service.load_session(path)
        self.assertEqual(loaded["state"], self.state)
        self.assertEqual(loaded["references"], self.references)
        self.assertFalse(loaded["resume_jobs"])

    def test_relative_session_references_resolve_after_folder_move(self):
        session = self.folder / "work.optics.json"
        self.service.save_session(session, self.state, self.references)
        moved = Path(self.temp.name).resolve() / "moved"
        shutil.copytree(self.folder, moved)
        loaded = self.service.load_session(moved / session.name)
        self.assertEqual(loaded["references"]["report_path"], str(moved / "report.json"))
        self.assertTrue(Path(loaded["references"]["database_path"]).is_file())

    def test_missing_session_reference_allows_settings_restore_and_reports_relink(self):
        path = self.folder / "work.optics.json"
        self.service.save_session(path, self.state, self.references)
        self.target.unlink()
        result = self.service.load_session(path)
        self.assertEqual(result["state"], self.state)
        self.assertTrue(any(warning["code"] == "MISSING_REFERENCE" for warning in result["warnings"]))

    def test_session_rejects_credentials_without_leaking_value(self):
        state = {"nested": {"apiKey": "do-not-persist-secret"}}
        with self.assertRaises(FileDataError) as raised:
            self.service.save_session(self.folder / "work.json", state, {})
        self.assertEqual(raised.exception.code, "SESSION_CREDENTIALS")
        self.assertNotIn("do-not-persist-secret", raised.exception.message)
        self.assertFalse((self.folder / "work.json").exists())

    def test_session_rejects_token_and_provider_prefixed_api_key(self):
        for key in ("token", "claudeApiKey"):
            with self.subTest(key=key):
                self.assert_code("SESSION_CREDENTIALS", self.service.save_session,
                                 self.folder / "credentials.json", {"provider": {key: "not-for-session"}}, {})

    def test_non_json_state_is_rejected_before_writing(self):
        for state in ({"value": float("nan")}, {"value": {1, 2}}, {1: "non-string key"}):
            with self.subTest(state=state):
                self.assert_code("SESSION_STATE", self.service.save_session, self.folder / "invalid.json", state, {})

    def test_atomic_write_failure_preserves_existing_session_and_cleans_temp(self):
        path = self.folder / "work.json"
        path.write_bytes(b"previous-session")
        with mock.patch("optics_ui.services.files.os.replace", side_effect=OSError("disk failure")):
            self.assert_code("SESSION_WRITE", self.service.save_session, path, self.state, {})
        self.assertEqual(path.read_bytes(), b"previous-session")
        self.assertEqual(list(self.folder.glob(".work.json.*.tmp")), [])

    def test_session_cannot_overwrite_a_referenced_database(self):
        before = self.digest(self.db)
        self.assert_code("SESSION_REFERENCE_OVERWRITE", self.service.save_session, self.db, self.state, self.references)
        self.assertEqual(self.digest(self.db), before)

    def test_session_cannot_overwrite_the_model_named_inside_the_report(self):
        before = self.model.read_bytes()
        self.assert_code("SESSION_REFERENCE_OVERWRITE", self.service.save_session,
                         self.model, self.state, self.references)
        self.assertEqual(self.model.read_bytes(), before)

    def test_session_cannot_overwrite_a_report_referenced_json_catalog(self):
        catalog = self.folder / "materials/catalog.json"
        catalog.write_text('{"materials":["BK7"]}')
        self.report_data["material_catalog"] = {"filename": "materials/catalog.json"}
        self.write_report()
        before = catalog.read_bytes()
        self.assert_code("SESSION_REFERENCE_OVERWRITE", self.service.save_session,
                         catalog, self.state, self.references)
        self.assertEqual(catalog.read_bytes(), before)

    def test_session_file_type_cannot_be_a_model_or_database_even_without_refs(self):
        for target in (self.model, self.db):
            before = target.read_bytes()
            with self.subTest(path=target):
                self.assert_code("SESSION_TYPE", self.service.save_session, target, self.state, {})
                self.assertEqual(target.read_bytes(), before)

    def test_wrong_session_version_and_persisted_credentials_are_rejected(self):
        path = self.folder / "bad.json"
        path.write_text(json.dumps({"format": "optics-ui-session", "schema_version": 2, "state": {}, "references": {}}))
        self.assert_code("SESSION_SCHEMA", self.service.load_session, path)
        path.write_text(json.dumps({"format": "optics-ui-session", "schema_version": 1, "state": {"password": "secret"}, "references": {}}))
        self.assert_code("SESSION_CREDENTIALS", self.service.load_session, path)

    def test_bundle_keeps_report_siblings_and_portable_references(self):
        bundle = Path(self.temp.name) / "project.zip"
        result = self.service.export_bundle(bundle, self.state, self.references)
        self.assertEqual(result["status"], "exported")
        extracted = Path(self.temp.name) / "extracted"
        with zipfile.ZipFile(bundle) as archive:
            self.assertIsNone(archive.testzip())
            archive.extractall(extracted)
        loaded = self.service.load_session(extracted / result["session_path"])
        self.assertEqual(loaded["state"], self.state)
        self.assertFalse(loaded["resume_jobs"])
        report = self.service.load_report(loaded["references"]["report_path"])
        self.assertEqual(Path(report["model_path"]).parent, Path(report["report_path"]).parent)
        self.assertEqual(Path(report["database_path"]).parent, Path(report["report_path"]).parent)
        self.assertTrue(Path(report["material_catalog_path"]).is_file())
        self.assertEqual(self.service.load_target(loaded["references"]["target_path"])["profile"]["profile_id"], "t1")
        self.assertTrue(all(not Path(value).is_absolute() for value in loaded["stored_references"].values() if value))

    def test_bundle_sqlite_snapshot_includes_committed_wal_data(self):
        connection = sqlite3.connect(self.db)
        self.addCleanup(connection.close)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("INSERT INTO designs VALUES ('WAL_CASE','FW',1,1,1,'SUCCESS','SYNTHETIC_MATH_PROXY',0)")
        connection.commit()
        self.assertTrue(Path(str(self.db) + "-wal").exists())
        bundle = Path(self.temp.name) / "wal.zip"
        self.service.export_bundle(bundle, self.state, self.references)
        extracted = Path(self.temp.name) / "wal-extracted"
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(extracted)
        loaded = self.service.load_session(extracted / "session.optics.json")
        ids = [row["id"] for row in self.service.list_cases(loaded["references"]["database_path"])]
        self.assertIn("WAL_CASE", ids)
        self.assertFalse(list(extracted.rglob("*-wal")))

    def test_bundle_failure_preserves_existing_zip(self):
        bundle = Path(self.temp.name) / "project.zip"
        bundle.write_bytes(b"original-zip")
        from optics_ui.services import files
        original_replace = files.os.replace

        def fail_final(source, destination):
            if Path(destination).resolve() == bundle.resolve():
                raise OSError("final rename failed")
            return original_replace(source, destination)

        with mock.patch("optics_ui.services.files.os.replace", side_effect=fail_final):
            self.assert_code("BUNDLE_WRITE", self.service.export_bundle, bundle, self.state, self.references)
        self.assertEqual(bundle.read_bytes(), b"original-zip")

    def test_conflicting_report_database_reference_is_rejected(self):
        other = self.folder / "other.sqlite"
        shutil.copyfile(self.db, other)
        references = self.references | {"database_path": str(other)}
        self.assert_code("REFERENCE_MISMATCH", self.service.export_bundle, Path(self.temp.name) / "bad.zip", self.state, references)

    def test_bundle_with_no_selected_files_still_contains_portable_session(self):
        bundle = Path(self.temp.name) / "settings.zip"
        result = self.service.export_bundle(bundle, self.state, {})
        self.assertIn("session.optics.json", result["files"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

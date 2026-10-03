"""Candidate extraction acceptance tests, written before implementation."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from optics_ui.bridge import RequestRouter
from optics_ui.services.files import FileDataError, FileDataService


SCHEMA = """
CREATE TABLE designs(design_id TEXT PRIMARY KEY,data_origin TEXT,zemax_executed INTEGER,geometry_valid INTEGER,trace_success INTEGER,overall_status TEXT);
CREATE TABLE lens_elements(design_id TEXT,lens_index INTEGER,front_surface_index INTEGER,back_surface_index INTEGER,material_id TEXT);
CREATE TABLE surfaces(design_id TEXT,surface_index INTEGER,lens_index INTEGER,surface_type TEXT);
CREATE TABLE wavelengths(design_id TEXT,wavelength_no INTEGER,wavelength_nm REAL,weight REAL,is_primary INTEGER,wavelength_reference_medium TEXT);
CREATE TABLE analyses(analysis_id TEXT PRIMARY KEY,design_id TEXT,analysis_type TEXT,design_mode TEXT,fidelity TEXT,analysis_requested INTEGER,execution_status TEXT,analysis_succeeded INTEGER,result_complete INTEGER,result_valid INTEGER,engine_name TEXT,result_source TEXT,settings_json TEXT);
CREATE TABLE first_order_metrics(design_id TEXT,analysis_id TEXT,temperature_c REAL,horizontal_fov_deg REAL,focus_valid INTEGER);
CREATE TABLE mtf_samples(design_id TEXT,analysis_id TEXT,temperature_c REAL,field_norm REAL,orientation TEXT,frequency_lp_per_mm REAL,mtf REAL,method TEXT);
CREATE TABLE spot_summary(design_id TEXT,analysis_id TEXT,temperature_c REAL,field_norm REAL,rms_radius_mm_proxy REAL,reference TEXT,ray_count INTEGER);
"""


class CandidatesDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="candidate-data-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "cases.sqlite"
        with sqlite3.connect(self.path) as db:
            db.executescript(SCHEMA)
        self.service = FileDataService()
        self.add_case("D1")
        self.add_case("D2")

    def add_case(self, case_id):
        spectrum = {"wavelengths_nm": [486.1327, 656.2725], "wavelength_weights": [.4, .6]}
        settings = {
            "fo": {"method": "ABCD", "reference_wavelength_nm": 656.2725},
            "mtf": {**spectrum, "temperature_c": 20, "method": "FFT", "fields_norm": [0, .8],
                    "orientations": ["SAGITTAL", "TANGENTIAL"], "frequencies_lp_per_mm": [0, 6]},
            "spot": {**spectrum, "reference": "CENTROID", "ray_pattern": "GRID", "rays_per_field": 64},
        }
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO designs VALUES(?,?,?,?,?,?)", (case_id, "SYNTHETIC_MATH_PROXY", 0, 1, 1, "SUCCESS"))
            for lens in range(1, 4):
                db.execute("INSERT INTO lens_elements VALUES(?,?,?,?,?)", (case_id, lens, 2*lens-1, 2*lens, "BK7"))
                db.executemany("INSERT INTO surfaces VALUES(?,?,?,?)", [(case_id, 2*lens-1, lens, "STANDARD"), (case_id, 2*lens, lens, "STANDARD")])
            db.executemany("INSERT INTO wavelengths VALUES(?,?,?,?,?,?)", [(case_id, 1, 486.1327, .4, 0, "AIR_WAVELENGTH"), (case_id, 2, 656.2725, .6, 1, "AIR_WAVELENGTH")])
            for suffix, kind in (("fo", "FIRST_ORDER"), ("mtf", "FFT_MTF"), ("spot", "SPOT_DIAGRAM")):
                db.execute("INSERT INTO analyses VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (case_id+"-"+suffix, case_id, kind, "SEQUENTIAL", "TEST", 1, "SUCCEEDED", 1, 1, 1, "synthetic_test", "SYNTHETIC_PROXY", json.dumps(settings[suffix])))
            for temperature in (20, 25):
                db.execute("INSERT INTO first_order_metrics VALUES(?,?,?,?,?)", (case_id, case_id+"-fo", temperature, 24 if temperature==20 else 26, 1))
                db.execute("INSERT INTO spot_summary VALUES(?,?,?,?,?,?,?)", (case_id, case_id+"-spot", temperature, 1, .0008, "CENTROID", 64))
                for field in (0, .8):
                    for orientation in ("SAGITTAL", "TANGENTIAL"):
                        for frequency in (0, 6):
                            db.execute("INSERT INTO mtf_samples VALUES(?,?,?,?,?,?,?,?)", (case_id, case_id+"-mtf", temperature, field, orientation, frequency, 1 if frequency==0 else .5, "FFT_ROWS"))

    def change(self, sql, args=()):
        with sqlite3.connect(self.path) as db:
            db.execute(sql, args)

    def change_settings(self, suffix, change, case_id="D1"):
        with sqlite3.connect(self.path) as db:
            current=json.loads(db.execute("SELECT settings_json FROM analyses WHERE analysis_id=?", (case_id+"-"+suffix,)).fetchone()[0])
            change(current)
            db.execute("UPDATE analyses SET settings_json=? WHERE analysis_id=?", (json.dumps(current),case_id+"-"+suffix))

    def data(self):
        return self.service.candidate_data(self.path)

    def row(self, case_id="D1"):
        return next(case for case in self.data()["cases"] if case["id"]==case_id)

    def test_ready_rows_share_condition_cohort_without_metric_or_id_in_key(self):
        self.change("UPDATE first_order_metrics SET horizontal_fov_deg=22 WHERE design_id='D2'")
        data=self.data()
        a,b=data["cases"]
        self.assertEqual(data["schema_version"],1)
        self.assertTrue(a["comparison_ready"] and b["comparison_ready"])
        self.assertEqual(a["cohort_key"],b["cohort_key"])
        self.assertEqual(a["metrics"],{"spot_rms_diameter_um":1.6,"horizontal_fov_deg":24})
        self.assertEqual(len(a["mtf"]),8)
        self.assertEqual(a["source_kind"],"synthetic")
        self.assertEqual(a["exclusion_reasons"],[])
        self.assertEqual(set(a["conditions"]["outputs"]),{"first_order","mtf","spot"})

    def test_first_order_reference_and_polychromatic_mtf_are_legitimate_same_case(self):
        row=self.row()
        self.assertTrue(row["comparison_ready"])
        outputs=row["conditions"]["outputs"]
        self.assertEqual(outputs["first_order"]["spectrum"]["mode"],"reference")
        self.assertEqual(outputs["first_order"]["spectrum"]["reference_wavelength_nm"],656.2725)
        self.assertEqual(outputs["mtf"]["spectrum"]["mode"],"weighted")

    def test_temperature_selection_matches_load_case_not_hardcoded_twenty(self):
        self.change_settings("mtf",lambda s:s.update(temperature_c=25))
        candidate=self.row()
        loaded=self.service.load_case(self.path,"D1")
        self.assertEqual(candidate["temperature_c"],loaded["temperature_c"])
        self.assertEqual(candidate["temperature_c"],25)
        self.assertEqual(candidate["metrics"]["horizontal_fov_deg"],26)
        self.assertNotEqual(candidate["cohort_key"],self.row("D2")["cohort_key"])

    def test_no_observed_temperature_never_uses_display_default_for_comparison(self):
        for table in ("analyses","first_order_metrics","mtf_samples","spot_summary","wavelengths"):
            self.change(f"DELETE FROM {table} WHERE design_id='D1'")
        row=self.row()
        self.assertIsNone(row["temperature_c"])
        self.assertIsNone(row["cohort_key"])
        self.assertFalse(row["comparison_ready"])
        self.assertEqual(row["metrics"],{"spot_rms_diameter_um":None,"horizontal_fov_deg":None})

    def test_cross_case_analysis_link_is_rejected(self):
        self.change("UPDATE first_order_metrics SET analysis_id='D2-fo' WHERE design_id='D1'")
        row=self.row()
        self.assertFalse(row["comparison_ready"])
        self.assertIsNone(row["metrics"]["horizontal_fov_deg"])
        self.assertTrue(any("ANALYSIS_LINK" in reason for reason in row["exclusion_reasons"]))

    def test_all_analysis_success_complete_valid_flags_are_required(self):
        for suffix in ("fo","mtf","spot"):
            for column,bad,good in (("result_valid",0,1),("result_complete",0,1),("analysis_succeeded",0,1),("execution_status","FAILED","SUCCEEDED")):
                with self.subTest(output=suffix,column=column):
                    self.change(f"UPDATE analyses SET {column}=? WHERE analysis_id=?",(bad,"D1-"+suffix))
                    self.assertFalse(self.row()["comparison_ready"])
                    self.change(f"UPDATE analyses SET {column}=? WHERE analysis_id=?",(good,"D1-"+suffix))

    def test_unsupported_geometry_and_trace_rows_remain_with_reasons(self):
        for column in ("geometry_valid","trace_success"):
            self.change(f"UPDATE designs SET {column}=0 WHERE design_id='D1'")
            row=self.row()
            self.assertFalse(row["comparison_ready"])
            self.assertTrue(row["exclusion_reasons"])
            self.change(f"UPDATE designs SET {column}=1 WHERE design_id='D1'")
        self.change("UPDATE surfaces SET surface_type='ODD_ASPHERE' WHERE design_id='D1' AND surface_index=1")
        self.assertFalse(self.row()["ui_compatible"])
        self.assertFalse(self.row()["comparison_ready"])
        self.assertEqual(len(self.data()["cases"]),2)

    def test_missing_values_and_incomplete_curve_do_not_become_zero(self):
        self.change("UPDATE spot_summary SET rms_radius_mm_proxy=NULL WHERE design_id='D1'")
        row=self.row()
        self.assertIsNone(row["metrics"]["spot_rms_diameter_um"])
        self.assertFalse(row["comparison_ready"])
        self.change("UPDATE spot_summary SET rms_radius_mm_proxy=0 WHERE design_id='D1'")
        self.assertEqual(self.row()["metrics"]["spot_rms_diameter_um"],0)
        self.change("DELETE FROM mtf_samples WHERE design_id='D1' AND temperature_c=20 AND field_norm=.8 AND orientation='TANGENTIAL' AND frequency_lp_per_mm=6")
        row=self.row()
        self.assertFalse(row["comparison_ready"])
        self.assertTrue(any("MTF_GRID" in reason for reason in row["exclusion_reasons"]))

    def test_weight_method_reference_fidelity_and_medium_changes_split_cohorts(self):
        baseline=self.row("D2")["cohort_key"]
        self.change_settings("mtf",lambda s:s.update(wavelength_weights=[.6,.4]))
        self.assertNotEqual(self.row()["cohort_key"],baseline)
        self.change_settings("mtf",lambda s:s.update(wavelength_weights=[.4,.6]))
        self.change("UPDATE mtf_samples SET method='OTHER_FFT' WHERE design_id='D1'")
        self.assertNotEqual(self.row()["cohort_key"],baseline)
        self.change("UPDATE mtf_samples SET method='FFT_ROWS' WHERE design_id='D1'")
        self.change("UPDATE analyses SET fidelity='HIGHER' WHERE analysis_id='D1-mtf'")
        self.assertNotEqual(self.row()["cohort_key"],baseline)
        self.change("UPDATE analyses SET fidelity='TEST' WHERE analysis_id='D1-mtf'")
        self.change("UPDATE spot_summary SET reference='CHIEF_RAY' WHERE design_id='D1'")
        self.change_settings("spot",lambda s:s.update(reference='CHIEF_RAY'))
        self.assertNotEqual(self.row()["cohort_key"],baseline)
        self.change("UPDATE spot_summary SET reference='CENTROID' WHERE design_id='D1'")
        self.change_settings("spot",lambda s:s.update(reference='CENTROID'))
        self.change("UPDATE wavelengths SET wavelength_reference_medium='VACUUM' WHERE design_id='D1'")
        self.assertNotEqual(self.row()["cohort_key"],baseline)

    def test_missing_spectral_weights_or_reference_metadata_is_not_comparable(self):
        self.change_settings("mtf",lambda s:s.pop("wavelength_weights"))
        self.assertFalse(self.row()["comparison_ready"])
        self.change_settings("mtf",lambda s:s.update(wavelength_weights=[.4,.6]))
        self.change("UPDATE wavelengths SET wavelength_reference_medium=NULL WHERE design_id='D1'")
        self.assertFalse(self.row()["comparison_ready"])

    def test_provenance_never_promotes_synthetic_rows_to_zemax(self):
        self.change("UPDATE designs SET zemax_executed=1,data_origin='ZEMAX' WHERE design_id='D1'")
        row=self.row()
        self.assertEqual(row["source_kind"],"synthetic")
        self.assertFalse(row["comparison_ready"])
        self.change("UPDATE analyses SET result_source='ZEMAX_SEQUENTIAL',engine_name='OpticStudio' WHERE design_id='D1'")
        row=self.row()
        self.assertEqual(row["source_kind"],"zemax")
        self.assertTrue(row["comparison_ready"])
        self.assertNotEqual(row["cohort_key"],self.row("D2")["cohort_key"])

    def test_missing_analysis_ids_and_wrong_output_types_are_rejected(self):
        self.change("UPDATE mtf_samples SET analysis_id=NULL WHERE design_id='D1'")
        self.assertFalse(self.row()["comparison_ready"])
        self.change("UPDATE mtf_samples SET analysis_id='D1-spot' WHERE design_id='D1'")
        self.assertIn("MTF_ANALYSIS_TYPE_UNSUPPORTED",self.row()["exclusion_reasons"])

    def test_actual_spot_sampling_count_splits_cohort(self):
        self.change("UPDATE spot_summary SET ray_count=1024 WHERE design_id='D1'")
        row=self.row()
        self.assertTrue(row["comparison_ready"])
        self.assertNotEqual(row["cohort_key"],self.row("D2")["cohort_key"])
        self.assertEqual(row["conditions"]["outputs"]["spot"]["ray_count"],1024)

    def test_declared_spot_field_must_cover_selected_result(self):
        self.change_settings("spot",lambda s:s.update(fields_norm=[0]))
        row=self.row()
        self.assertFalse(row["comparison_ready"])
        self.assertTrue(any("SPOT_FIELD" in reason for reason in row["exclusion_reasons"]))

    def test_predicted_and_mixed_sources_cannot_enter_observed_cohort(self):
        self.change("UPDATE designs SET data_origin='MODEL_PREDICTION' WHERE design_id='D1'")
        self.assertFalse(self.row()["comparison_ready"])
        self.change("UPDATE designs SET data_origin='DB' WHERE design_id='D1'")
        self.change("UPDATE analyses SET result_source='MODEL_PREDICTION',engine_name='neural_surrogate' WHERE design_id='D1'")
        row=self.row()
        self.assertFalse(row["comparison_ready"])
        self.assertTrue(any("PREDICTED" in reason for reason in row["exclusion_reasons"]))
        self.change("UPDATE analyses SET result_source='SYNTHETIC_PROXY',engine_name='synthetic_test' WHERE design_id='D1'")
        self.change("UPDATE analyses SET result_source='ZEMAX_SEQUENTIAL',engine_name='OpticStudio' WHERE analysis_id='D1-spot'")
        row=self.row()
        self.assertFalse(row["comparison_ready"])
        self.assertTrue(any("PROVENANCE" in reason for reason in row["exclusion_reasons"]))

    def test_explicit_synthetic_engine_metadata_cannot_be_labeled_zemax(self):
        self.change("UPDATE designs SET data_origin='ZEMAX',zemax_executed=1 WHERE design_id='D1'")
        self.change("UPDATE analyses SET result_source='ZEMAX_SEQUENTIAL',engine_name='OpticStudio' WHERE design_id='D1'")
        self.change_settings("mtf",lambda s:s.update(synthetic_engine='synthetic_fixture_v1'))
        row=self.row()
        self.assertEqual(row["source_kind"],"synthetic")
        self.assertFalse(row["comparison_ready"])

    def test_excluded_flags_numbers_and_conversion_overflow_stay_json_finite(self):
        self.change("UPDATE designs SET geometry_valid=?,zemax_executed=? WHERE design_id='D1'",(float('inf'),float('inf')))
        self.change("UPDATE first_order_metrics SET horizontal_fov_deg=? WHERE design_id='D1'",(float('inf'),))
        self.change("UPDATE spot_summary SET rms_radius_mm_proxy=1e308 WHERE design_id='D1'")
        self.change("UPDATE mtf_samples SET mtf=? WHERE design_id='D1'",(float('inf'),))
        result=self.data()
        json.dumps(result,allow_nan=False)
        row=result["cases"][0]
        self.assertIsNone(row["geometry_valid"])
        self.assertIsNone(row["zemax_executed"])
        self.assertIsNone(row["metrics"]["spot_rms_diameter_um"])
        self.assertFalse(row["comparison_ready"])

    def test_malformed_nested_metadata_excludes_only_affected_case(self):
        self.change_settings("mtf",lambda s:s.update(orientations=[{}]))
        result=self.data()
        self.assertFalse(result["cases"][0]["comparison_ready"])
        self.assertTrue(result["cases"][1]["comparison_ready"])
        json.dumps(result,allow_nan=False)

    def test_huge_invalid_metadata_integer_does_not_break_other_cases(self):
        self.change_settings("mtf",lambda s:s.update(temperature_c=10**400))
        result=self.data()
        self.assertFalse(result["cases"][0]["comparison_ready"])
        self.assertTrue(result["cases"][1]["comparison_ready"])
        json.dumps(result,allow_nan=False)

    def test_unknown_provenance_metadata_is_not_comparison_evidence(self):
        self.change("UPDATE analyses SET result_source='UNKNOWN' WHERE analysis_id='D1-mtf'")
        self.assertFalse(self.row()["comparison_ready"])
        self.change("UPDATE analyses SET result_source='SYNTHETIC_PROXY',fidelity='UNKNOWN' WHERE analysis_id='D1-mtf'")
        self.assertFalse(self.row()["comparison_ready"])

    def test_queries_are_batched_and_source_is_unchanged(self):
        for index in range(3,32):self.add_case(f"D{index}")
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        from optics_ui.services import files
        original=files._readonly_database
        statements=[]
        @contextmanager
        def tracked(path):
            with original(path) as connection:
                connection.set_trace_callback(statements.append)
                yield connection
        with mock.patch.object(files,"_readonly_database",tracked):
            result=self.data()
        self.assertEqual(len(result["cases"]),31)
        self.assertLessEqual(sum(s.lstrip().upper().startswith("SELECT") for s in statements),12)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)

    def test_bridge_exposes_only_candidate_path_and_preserves_envelope(self):
        files=mock.Mock()
        files.candidate_data.return_value={"schema_version":1,"cases":[]}
        router=RequestRouter(files)
        result=router.dispatch(json.dumps({"id":"candidate-1","method":"candidate_data","params":{"path":"/chosen/cases.sqlite"}}))
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"],files.candidate_data.return_value)
        files.candidate_data.assert_called_once_with("/chosen/cases.sqlite")
        self.assertFalse(router.dispatch(json.dumps({"id":"candidate-2","method":"candidate_data","params":{"path":"/db","target":{}}}))["ok"])


if __name__=="__main__":unittest.main(verbosity=2)

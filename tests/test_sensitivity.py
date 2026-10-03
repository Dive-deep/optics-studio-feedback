"""Importer and native-view contracts; written before the Sobol implementation.

The numbers below are declared analytic-test fixtures, never optical/DB results.
"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tests.qt_support import QT_APP
from optics_ui.services.sensitivity import (
    DEFAULT_OUTPUTS, MAX_REPORT_BYTES, MAX_EMBEDDED_REPORT_BYTES, SensitivityError, context_hash,
    load_sensitivity_report, validate_report, validate_panel_snapshot,
)
from optics_ui.workbench.sensitivity import SensitivityPanel


def context():
    return {
        "parameters": [
            {"id": "thickness", "label": "L1 thickness", "unit": "mm",
             "min": 1., "max": 3., "value": 2., "active": True, "available": True},
            {"id": "gap", "label": "Air gap", "unit": "mm",
             "min": .2, "max": 2., "value": 1., "active": True, "available": True},
            {"id": "a12", "label": "A12", "unit": "", "min": None,
             "max": None, "value": None, "active": False, "available": False},
        ],
        "conditions": {"temperature_c": 20., "wavelengths_nm": [546.074]},
        "optics": {"material": "fixture-glass", "surface_type": "even_asphere",
                   "stop": {"position_mode": "surface", "surface_index": 6}},
        "model": {"id": "analytic-fixture", "version": "1"},
        "reference_id": "fixture", "targets": {"spot": 1.6},
    }


def cell(value, *, status=None, low=None, high=None):
    return {"estimate": value, "ci_low": low, "ci_high": high,
            "status": status or ("not_computed" if value is None else "estimated_unvalidated")}


def report():
    ctx = context()
    return {
        "format": "optics-sobol-report", "schema_version": 1,
        "study": {"id": "analytic-fixture-study", "context_hash": context_hash(ctx)},
        "context": ctx,
        "origin": {"kind": "synthetic_fixture", "source": "Unit test only; no optical evaluator"},
        "evaluator": {"kind": "analytic_test", "id": "fixture", "version": "1"},
        "conditions": copy.deepcopy(ctx["conditions"]),
        "distribution": {"dependence": "independent", "marginals": [
            {"input_id": "thickness", "kind": "uniform", "bounds": [1., 3.]},
            {"input_id": "gap", "kind": "uniform", "bounds": [.2, 2.]},
        ]},
        "sampling": {"method": "saltelli_cross_design", "estimator": "fixture",
                     "implementation": "fixture-1", "base_sample_count": 8,
                     "evaluation_count": 32, "seed": 3, "scramble": True,
                     "second_order": False, "design_hash": "a" * 64,
                     "confidence_level": .95, "ci_method": "paired-bootstrap"},
        "inputs": [{"id": p["id"], "label": p["label"], "unit": p["unit"]}
                   for p in ctx["parameters"][:2]],
        "outputs": [{**copy.deepcopy(DEFAULT_OUTPUTS[0]), "variance": .1,
                     "conditions": {"field_norm": 0., "orientation": "S", "frequency_lp_per_mm": 6}}],
        "first_order": [[cell(.2, low=.1, high=.3), cell(None)]],
        "total_order": [[cell(.8), cell(.7)]],
    }


class SensitivityReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sensitivity-test-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "sobol.json"

    def test_clear_imported_report_keeps_context_and_allows_settings_only_save(self):
        panel = SensitivityPanel()
        try:
            panel.set_context(context())
            self.assertTrue(panel.load_report(self.write()))
            self.assertTrue(panel.clear_button.isEnabled())
            panel.clear_button.click()
            self.assertIsNone(panel.snapshot()['report'])
            self.assertFalse(panel.clear_button.isEnabled())
            self.assertEqual(panel.request_preview()['context'], context())
            self.assertTrue(all(value is None for value in panel.chart.values))
        finally:
            panel.deleteLater()

    def write(self, payload=None):
        self.path.write_text(json.dumps(report() if payload is None else payload), encoding="utf-8")
        return self.path

    def test_valid_report_keeps_null_ci_and_never_normalizes_total_order(self):
        result = load_sensitivity_report(self.write())
        self.assertEqual(result["total_order"][0][0]["estimate"], .8)
        self.assertEqual(result["total_order"][0][1]["estimate"], .7)
        self.assertIsNone(result["total_order"][0][0]["ci_low"])
        self.assertIsNone(result["first_order"][0][1]["estimate"])
        self.assertEqual(result["origin"]["kind"], "synthetic_fixture")

    def test_out_of_interval_estimates_are_preserved_and_warned(self):
        data = report()
        data["first_order"][0][0] = cell(-.04, low=-.1, high=.02)
        data["total_order"][0][1] = cell(1.08)
        valid = validate_report(data)
        self.assertEqual(valid["first_order"][0][0]["estimate"], -.04)
        self.assertEqual(valid["total_order"][0][1]["estimate"], 1.08)
        self.assertEqual(sum(w["code"] == "ESTIMATE_OUTSIDE_UNIT_INTERVAL" for w in valid["warnings"]), 2)

    def test_context_hash_is_canonical_and_covers_domain_model_and_targets(self):
        ctx = context()
        self.assertEqual(context_hash(ctx), context_hash(dict(reversed(list(ctx.items())))))
        for part, key, value in [("conditions", "temperature_c", 25),
                                 ("optics", "material", "changed"),
                                 ("optics", "surface_type", "sphere"),
                                 ("optics", "stop", {"position_mode": "absolute", "z_mm": 40}),
                                 ("model", "version", "2"), ("targets", "spot", 1.7)]:
            changed = copy.deepcopy(ctx)
            changed[part][key] = value
            self.assertNotEqual(context_hash(ctx), context_hash(changed))
        for key, value in [("min", .5), ("max", 4), ("active", False), ("value", 2.5)]:
            changed = copy.deepcopy(ctx)
            changed["parameters"][0][key] = value
            self.assertNotEqual(context_hash(ctx), context_hash(changed))

    def test_context_hash_equates_json_number_types_and_signed_zero_without_mutation(self):
        first = {"integer": 1, "zero": 0, "nested": [20., .2, -2.5e-19], "flag": True}
        second = {"integer": 1., "zero": -0.0, "nested": [20, .2, -2.5e-19], "flag": True}
        before = json.dumps(second)
        self.assertEqual(context_hash(first), context_hash(second))
        self.assertEqual(json.dumps(second), before)
        self.assertNotEqual(context_hash({"value": True}), context_hash({"value": 1}))

    def test_context_rejects_integers_outside_the_javascript_safe_range(self):
        limit = 2**53 - 1
        self.assertEqual(context_hash({"value": limit}), context_hash({"value": float(limit)}))
        for number in (limit + 1, limit + 2, -limit - 2, float(limit + 1), 10**100):
            with self.subTest(number=number), self.assertRaises(SensitivityError):
                context_hash({"nested": {"value": number}})

    @unittest.skipUnless(shutil.which("node"), "Node is needed for actual JSON.stringify interoperability")
    def test_external_float_report_survives_actual_javascript_and_embedded_session_roundtrip(self):
        from optics_ui.services.files import FileDataService
        data = report()
        data["context"]["optics"]["numeric_probe"] = [1., -0., .000001, 1e-7, -2.5e-19]
        data["study"]["context_hash"] = context_hash(data["context"])
        original = copy.deepcopy(data)
        validated = validate_report(data)
        panel = {"format": "optics-sensitivity-panel", "schema_version": 1,
                 "report": validated, "report_path": None, "metric": "S1",
                 "output_id": DEFAULT_OUTPUTS[0]["id"], "stale": False}
        workbench = {"version": 1, "page": "workspace", "llm_visible": False,
                     "analysis_visible": True, "workspace_split": [550, 250],
                     "explorer": {"workspace_root": str(self.path.parent), "files": [],
                                  "current_file": None, "wrap_lines": False}, "sensitivity": panel}
        script = "const fs=require('node:fs');process.stdout.write(JSON.stringify(JSON.parse(fs.readFileSync(0,'utf8'))));"
        completed = subprocess.run([shutil.which("node"), "-e", script], input=json.dumps({"workbench": workbench}),
                                   text=True, capture_output=True, timeout=10, check=True)
        state = json.loads(completed.stdout)
        transported = state["workbench"]["sensitivity"]["report"]
        self.assertIsInstance(transported["context"]["parameters"][0]["min"], int)
        self.assertEqual(validate_report(transported)["study"]["context_hash"], data["study"]["context_hash"])
        session = self.path.parent / "roundtrip.optics.json"
        files = FileDataService()
        files.save_session(session, state, {})
        restored = files.load_session(session)["state"]["workbench"]["sensitivity"]
        self.assertEqual(validate_panel_snapshot(restored)["report"]["study"]["context_hash"], data["study"]["context_hash"])
        self.assertEqual(data, original)
        self.assertIsInstance(data["context"]["parameters"][0]["min"], float)

    def test_rejects_missing_provenance_and_unmatched_context(self):
        for key in ("origin", "evaluator", "conditions", "distribution", "sampling", "context"):
            data = report()
            del data[key]
            with self.subTest(key=key), self.assertRaises(SensitivityError):
                validate_report(data)
        for mutation in (lambda d: d["study"].update(context_hash="b" * 64),
                         lambda d: d["conditions"].update(temperature_c=30),
                         lambda d: d["distribution"]["marginals"][0].update(bounds=[0, 8])):
            data = report()
            mutation(data)
            with self.assertRaises(SensitivityError):
                validate_report(data)

    def test_rejects_bad_dimensions_duplicates_and_large_matrices(self):
        for mutation in (lambda d: d["first_order"][0].pop(),
                         lambda d: d["total_order"].append(d["total_order"][0]),
                         lambda d: d["inputs"][1].update(id="thickness"),
                         lambda d: d.update(inputs=d["inputs"] * 129),
                         lambda d: d.update(outputs=d["outputs"] * 65)):
            data = report()
            mutation(data)
            with self.assertRaises(SensitivityError):
                validate_report(data)

    def test_rejects_nonfinite_bool_and_inconsistent_cells(self):
        for value in (float("nan"), float("inf"), True, "0.2"):
            data = report()
            data["first_order"][0][0]["estimate"] = value
            with self.subTest(value=value), self.assertRaises(SensitivityError):
                validate_report(data)
        for bad in (cell(.2, low=.4, high=.1), cell(.2, low=.1),
                    cell(None, status="validated_for_scope"),
                    cell(.2, status="zero_output_variance"),
                    cell(None, low=.1, high=.3)):
            data = report()
            data["first_order"][0][0] = bad
            with self.assertRaises(SensitivityError):
                validate_report(data)

    def test_malformed_metadata_types_are_typed_validation_errors(self):
        for mutation in (lambda d: d["origin"].update(kind=[]),
                         lambda d: d["evaluator"].update(kind={}),
                         lambda d: d["distribution"]["marginals"][0].update(kind=[]),
                         lambda d: d["first_order"][0][0].update(status=[]),
                         lambda d: d["first_order"][0][0].update(estimate=10**1000)):
            data = report()
            mutation(data)
            with self.assertRaises(SensitivityError):
                validate_report(data)

    def test_categorical_factors_require_explicit_probabilities(self):
        data = report()
        parameter = data["context"]["parameters"][0]
        parameter.update(min=None, max=None, value="glass-a", choices=["glass-a", "glass-b"], unit="")
        data["inputs"][0]["unit"] = ""
        data["study"]["context_hash"] = context_hash(data["context"])
        data["distribution"]["marginals"][0] = {
            "input_id": "thickness", "kind": "categorical", "values": ["glass-a", "glass-b"],
            "probabilities": [.4, .6]}
        self.assertEqual(validate_report(data)["distribution"]["marginals"][0]["probabilities"], [.4, .6])
        data["distribution"]["marginals"][0]["probabilities"] = [.4, .4]
        with self.assertRaises(SensitivityError):
            validate_report(data)

    def test_zero_or_unknown_variance_cannot_have_numeric_indices(self):
        for variance in (0., None):
            data = report()
            data["outputs"][0]["variance"] = variance
            with self.assertRaises(SensitivityError):
                validate_report(data)
            data["first_order"] = [[cell(None, status="zero_output_variance"), cell(None)]]
            data["total_order"] = copy.deepcopy(data["first_order"])
            self.assertIsNone(validate_report(data)["first_order"][0][0]["estimate"])

    def test_rejects_non_independent_design_and_unsupported_missing_metadata(self):
        for mutation in (lambda d: d["distribution"].update(dependence="correlated"),
                         lambda d: d["sampling"].update(method="arbitrary_db_rows"),
                         lambda d: d["sampling"].update(evaluation_count=31),
                         lambda d: d["sampling"].pop("seed"),
                         lambda d: d["outputs"][0].update(conditions={}),
                         lambda d: d["evaluator"].pop("version")):
            data = report()
            mutation(data)
            with self.assertRaises(SensitivityError):
                validate_report(data)

    def test_file_bounds_duplicate_keys_nonfinite_and_bad_encoding(self):
        for raw in (b'{"schema_version":1,"schema_version":1}', b'{"x":NaN}', b'\xff',
                    b' ' * (MAX_REPORT_BYTES + 1), b'[]'):
            self.path.write_bytes(raw)
            with self.subTest(size=len(raw)), self.assertRaises(SensitivityError):
                load_sensitivity_report(self.path)

    def test_service_returns_detached_data_and_input_has_no_mutation(self):
        data = report()
        before = copy.deepcopy(data)
        result = validate_report(data)
        self.assertEqual(data, before)
        result["inputs"][0]["label"] = "changed"
        self.assertNotEqual(data["inputs"][0]["label"], "changed")


class SensitivityPanelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sensitivity-widget-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "sobol.json"
        self.path.write_text(json.dumps(report()), encoding="utf-8")
        self.panel = SensitivityPanel()
        self.addCleanup(self.panel.close)
        self.panel.set_context(context())

    def test_default_nine_outputs_are_unknown_and_evaluator_unavailable(self):
        self.assertEqual(self.panel.table.rowCount(), 9)
        self.assertEqual(self.panel.table.columnCount(), 3)
        self.assertEqual(self.panel.table.item(0, 0).text(), "—")
        self.assertIn("unavailable", self.panel.table.item(0, 2).toolTip())
        self.assertIsNone(self.panel.snapshot()["report"])
        self.assertFalse(self.panel.calculate_button.isEnabled())
        self.assertIn("TBU", self.panel.calculate_button.text())

    def test_repeated_parameter_labels_include_lens_face_and_stable_id(self):
        ctx = context()
        ctx["parameters"][0].update(label="Radius R", group="L1 / Front")
        ctx["parameters"][1].update(label="Radius R", group="L1 / Rear")
        self.panel.set_context(ctx)
        self.assertEqual(self.panel.table.horizontalHeaderItem(0).text(), "L1 / Front · Radius R")
        self.assertEqual(self.panel.table.horizontalHeaderItem(1).text(), "L1 / Rear · Radius R")
        self.assertEqual(self.panel.chart._rows[0]["label"], "L1 / Front · Radius R")
        tooltip = self.panel.table.item(0, 0).toolTip()
        self.assertIn("L1 / Front · Radius R", tooltip)
        self.assertIn("Input ID: thickness", tooltip)
        self.assertEqual(ctx["parameters"][0]["label"], "Radius R")

    def test_import_toggle_selection_and_null_tooltip_are_native(self):
        self.assertTrue(self.panel.load_report(self.path))
        self.assertEqual(self.panel.table.rowCount(), 9)
        self.assertEqual(self.panel.table.columnCount(), 2)
        self.assertEqual(self.panel.table.item(0, 0).text(), "0.200")
        self.assertIn("0.1", self.panel.table.item(0, 0).toolTip())
        self.panel.index_combo.setCurrentIndex(1)
        self.assertEqual(self.panel.table.item(0, 0).text(), "0.800")
        self.assertIn("CI: unavailable", self.panel.table.item(0, 0).toolTip())
        self.assertEqual(self.panel.chart.values, [.8, .7])
        self.panel.table.setCurrentCell(1, 0)
        self.assertEqual(self.panel.chart.values, [None, None])

    def test_context_changes_mark_stale_without_deleting_report(self):
        self.panel.load_report(self.path)
        before = self.panel.snapshot()["report"]
        self.assertFalse(self.panel.snapshot()["stale"])
        changed = context()
        changed["optics"]["stop"]["surface_index"] = 1
        self.panel.set_context(changed)
        self.assertTrue(self.panel.snapshot()["stale"])
        self.assertIn("Stale", self.panel.status_label.text())
        self.assertEqual(self.panel.snapshot()["report"], before)
        self.panel.set_context(context())
        self.assertFalse(self.panel.snapshot()["stale"])

    def test_rejected_live_context_is_stale_and_request_unavailable_until_recovery(self):
        self.panel.load_report(self.path)
        before = self.panel.snapshot()["report"]
        changed = context()
        changed["parameters"][0]["max"] = 1e20
        self.assertFalse(self.panel.set_context(changed))
        self.assertTrue(self.panel.snapshot()["stale"])
        self.assertEqual(self.panel.snapshot()["report"], before)
        self.assertIn("Stale", self.panel.status_label.text())
        self.assertIn("context cannot be validated", self.panel.status_label.text())
        preview = self.panel.request_preview()
        self.assertEqual(preview["reason"], "invalid_context")
        self.assertIsNone(preview["context"])
        self.assertIsNone(preview["context_hash"])
        self.assertFalse(preview["executed"])
        self.assertTrue(self.panel.set_context(context()))
        self.assertFalse(self.panel.snapshot()["stale"])
        self.assertNotIn("cannot be validated", self.panel.status_label.text())
        self.assertEqual(self.panel.request_preview()["reason"], "evaluator_not_connected")

    def test_identical_context_does_not_rebuild_and_preview_never_executes(self):
        with patch.object(self.panel, "_refresh") as refresh:
            self.assertTrue(self.panel.set_context(context()))
            refresh.assert_not_called()
        preview = self.panel.request_preview()
        self.assertFalse(preview["executed"])
        self.assertEqual(preview["status"], "unavailable")
        self.assertIsNone(preview["distribution"])
        self.assertIsNone(preview["sampling"])

    def test_invalid_replacement_and_restore_preserve_previous_state(self):
        self.panel.load_report(self.path)
        self.panel.index_combo.setCurrentIndex(1)
        before = self.panel.snapshot()
        messages = []
        self.panel.statusMessage.connect(messages.append)
        self.path.write_text('{"format":"bad"}')
        self.assertFalse(self.panel.load_report(self.path))
        self.assertEqual(self.panel.snapshot(), before)
        bad = copy.deepcopy(before)
        bad["report"]["total_order"][0][0]["estimate"] = float("inf")
        self.assertFalse(self.panel.restore(bad))
        self.assertEqual(self.panel.snapshot(), before)
        self.assertTrue(messages)

    def test_snapshot_restore_is_detached_and_roundtrips_raw_values(self):
        self.panel.load_report(self.path)
        self.panel.index_combo.setCurrentIndex(1)
        saved = self.panel.snapshot()
        other = SensitivityPanel()
        self.addCleanup(other.close)
        other.set_context(context())
        self.assertTrue(other.restore(saved))
        self.assertEqual(other.snapshot(), saved)
        saved["report"]["total_order"][0][0]["estimate"] = 99
        self.assertEqual(other.snapshot()["report"]["total_order"][0][0]["estimate"], .8)
        self.assertEqual(other.snapshot()["metric"], "ST")
        self.assertEqual(other.snapshot()["output_id"], DEFAULT_OUTPUTS[0]["id"])
        self.assertEqual(validate_panel_snapshot(other.snapshot())["metric"], "ST")

    def test_oversized_embedded_report_gives_explicit_session_error_but_stays_loaded(self):
        data = report()
        data["notes"] = "x" * MAX_EMBEDDED_REPORT_BYTES
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(self.panel.load_report(self.path))
        with self.assertRaises(SensitivityError) as result:
            self.panel.snapshot()
        self.assertEqual(result.exception.code, "SESSION_REPORT_TOO_LARGE")
        self.assertEqual(self.panel.table.item(0, 0).text(), "0.200")

    def test_signed_chart_and_missing_values_paint_in_native_qt(self):
        data = report()
        data["first_order"][0][0] = cell(-.04, low=-.1, high=.02)
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.panel.load_report(self.path)
        self.panel.resize(1100, 420)
        self.panel.show()
        QT_APP.processEvents()
        self.assertFalse(self.panel.grab().isNull())
        self.assertEqual(self.panel.chart.values, [-.04, None])


if __name__ == "__main__":
    unittest.main()

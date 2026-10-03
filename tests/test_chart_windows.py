"""Independent chart-window contracts, with no GPU/backend needed by unit tests."""
from tests.qt_support import QT_APP

import copy
import json
import math
import unittest

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from optics_ui.services.chart_data import ChartDataError, validate_chart_payload
from optics_ui.workbench.charts import ChartBridge, ChartWindowManager


def payload(kind="mtf", revision="reference-1"):
    data = {"schema_version": 1, "kind": kind, "revision": revision,
            "reference_id": "fixture-only", "source_label": "Synthetic fixture · no Zemax execution",
            "conditions_label": "20 °C · 546.074 nm", "condition_metadata": {"temperature_c": 20},
            "units": {"x": "lp/mm", "y": "fraction"} if kind == "mtf" else {"x": "µm", "y": "µm"},
            "rms_diameter_um": None, "view": None}
    if kind == "mtf":
        data["mtf"] = [
            {"field_norm": .8, "orientation": "TANGENTIAL", "frequency_lp_per_mm": 6, "mtf": .3},
            {"field_norm": 0, "orientation": "SAGITTAL", "frequency_lp_per_mm": 6, "mtf": .4},
            {"field_norm": 0, "orientation": "SAGITTAL", "frequency_lp_per_mm": 0, "mtf": 1},
        ]
    else:
        data["spot"] = [{"x": -.5, "y": .25, "wavelength_nm": 546.074}, {"x": 1.25, "y": -.75}]
    return data


class ChartDataTests(unittest.TestCase):
    def test_mtf_sorting_preserves_sagittal_tangential_and_fraction(self):
        source = payload()
        original = copy.deepcopy(source)
        result = validate_chart_payload(source)
        self.assertEqual([p["frequency_lp_per_mm"] for p in result["mtf"]], [0, 6, 6])
        self.assertEqual(result["mtf"][-1]["orientation"], "TANGENTIAL")
        self.assertEqual(result["mtf"][-1]["mtf"], .3)
        self.assertEqual(source, original)

    def test_spot_is_already_micrometres_and_missing_rms_stays_null(self):
        result = validate_chart_payload(payload("spot"))
        self.assertEqual(result["spot"][0]["x"], -.5)
        self.assertEqual(result["spot"][1]["y"], -.75)
        self.assertIsNone(result["rms_diameter_um"])

    def test_empty_results_remain_empty(self):
        for kind in ("mtf", "spot"):
            data = payload(kind)
            data[kind] = []
            self.assertEqual(validate_chart_payload(data)[kind], [])

    def test_bad_kind_schema_unit_and_metadata_are_rejected(self):
        for key, value in (("kind", "run_job"), ("schema_version", True), ("revision", ""),
                           ("reference_id", None), ("condition_metadata", []),
                           ("units", {"x": "mm", "y": "mm"})):
            data = payload()
            data[key] = value
            with self.subTest(key=key), self.assertRaises(ChartDataError):
                validate_chart_payload(data)
        with self.assertRaises(ChartDataError):
            validate_chart_payload(payload(), kind="spot")

    def test_nonfinite_and_boolean_chart_coordinates_are_rejected(self):
        for bad in (float("nan"), float("inf"), True, "0.5", None):
            for kind, key in (("mtf", "mtf"), ("spot", "x")):
                data = payload(kind)
                data[kind][0][key] = bad
                with self.subTest(kind=kind, bad=bad), self.assertRaises(ChartDataError):
                    validate_chart_payload(data)

    def test_duplicate_mtf_conditions_and_invalid_wavelength_are_rejected(self):
        data = payload()
        data["mtf"].append(copy.deepcopy(data["mtf"][0]))
        with self.assertRaises(ChartDataError):
            validate_chart_payload(data)
        data = payload("spot")
        data["spot"][0]["wavelength_nm"] = 0
        with self.assertRaises(ChartDataError):
            validate_chart_payload(data)

    def test_payload_bounds_and_nested_nonfinite_metadata_are_rejected(self):
        for change in ({"condition_metadata": {"number": float("nan")}},
                       {"condition_metadata": {"padding": "x" * (2 * 1024 * 1024)}},
                       {"mtf": payload()["mtf"] * 10000}):
            with self.assertRaises(ChartDataError):
                validate_chart_payload(payload() | change)

    def test_view_limits_are_validated_without_inferring_view(self):
        data = payload()
        data["view"] = {"k": 2., "x": -30., "y": 8.}
        self.assertEqual(validate_chart_payload(data)["view"], data["view"])
        for view in ({"k": .5, "x": 0, "y": 0}, {"k": 13, "x": 0, "y": 0},
                     {"k": True, "x": 0, "y": 0}, {"k": 1, "x": math.inf, "y": 0}):
            data["view"] = view
            with self.assertRaises(ChartDataError):
                validate_chart_payload(data)


class FakePage(QObject):
    def setWebChannel(self, channel):
        self.channel = channel


class FakeView(QWidget):
    loadFinished = Signal(bool)

    def setPage(self, page):
        self.page = page

    def load(self, url):
        self.url = url

    def stop(self):
        self.stopped = True


class ChartWindowTests(unittest.TestCase):
    def setUp(self):
        self.parent = QWidget()
        self.parent.resize(960, 620)
        self.parent.show()
        self.manager = ChartWindowManager(None, self.parent, page_factory=lambda view: FakePage(view), view_factory=FakeView)

    def tearDown(self):
        self.manager.shutdown()
        self.parent.close()
        self.parent.deleteLater()
        QT_APP.processEvents()

    def test_two_kinds_are_independent_nonmodal_and_keep_workspace_visible(self):
        mtf = self.manager.open_chart("mtf", payload())
        spot = self.manager.open_chart("spot", payload("spot"))
        self.assertIsNot(mtf, spot)
        self.assertFalse(mtf.isModal())
        self.assertFalse(spot.isModal())
        self.assertTrue(mtf.isWindow())
        self.assertTrue(mtf.isVisible() and spot.isVisible() and self.parent.isVisible())
        self.assertEqual(mtf.view.url.toString(), "optics-app://ui/chart-window.html?kind=mtf")
        self.assertEqual(set(mtf.page.channel.registeredObjects()), {"chart"})

    def test_close_and_escape_hide_only_that_chart_and_reopen_reuses_window(self):
        mtf = self.manager.open_chart("mtf", payload())
        spot = self.manager.open_chart("spot", payload("spot"))
        mtf.close()
        self.assertFalse(mtf.isVisible())
        self.assertTrue(spot.isVisible() and self.parent.isVisible())
        self.assertIs(self.manager.open_chart("mtf", payload()), mtf)
        QTest.keyClick(mtf, Qt.Key.Key_Escape)
        self.assertFalse(mtf.isVisible())
        self.assertTrue(spot.isVisible() and self.parent.isVisible())

    def test_reopening_a_minimized_chart_restores_the_same_window(self):
        window = self.manager.open_chart("mtf", payload())
        window.showMinimized()
        self.assertTrue(window.isMinimized())
        self.assertIs(self.manager.open_chart("mtf", payload()), window)
        self.assertFalse(window.isMinimized())

    def test_updates_publish_reference_and_invalid_updates_preserve_previous(self):
        window = self.manager.open_chart("mtf", payload())
        updates = []
        window.bridge.dataChanged.connect(updates.append)
        next_payload = payload(revision="reference-2")
        next_payload["reference_id"] = "second-fixture"
        self.assertTrue(self.manager.set_data("mtf", next_payload))
        self.assertEqual(json.loads(updates[-1])["reference_id"], "second-fixture")
        before = window.bridge.chartData()
        invalid = payload() | {"units": {"x": "mm", "y": "mm"}}
        self.assertFalse(self.manager.set_data("mtf", invalid))
        self.assertEqual(window.bridge.chartData(), before)
        self.assertIsNone(self.manager.open_chart("bad", payload()))

    def test_local_page_load_failure_is_visible_and_nonblocking(self):
        window = self.manager.open_chart("spot", payload("spot"))
        messages = []
        self.manager.statusMessage.connect(messages.append)
        window.view.loadFinished.emit(False)
        self.assertFalse(window.error_label.isHidden())
        self.assertIn("could not load", window.error_label.text())
        self.assertTrue(self.parent.isVisible())
        self.assertTrue(messages)
        window.view.loadFinished.emit(True)
        self.assertTrue(window.error_label.isHidden())

    def test_invalid_kind_without_payload_does_not_raise(self):
        self.assertIsNone(self.manager.open_chart({"bad": "kind"}))

    def test_private_view_event_matches_current_kind_revision_and_finite_view(self):
        window = self.manager.open_chart("mtf", payload())
        updates = []
        self.manager.viewChanged.connect(updates.append)
        event = {"kind": "mtf", "revision": "reference-1", "view": {"k": 2, "x": 3, "y": -4}}
        window.bridge.viewChanged(json.dumps(event))
        self.assertEqual(updates, [event])
        for changed in (event | {"kind": "spot"}, event | {"revision": "old"},
                        event | {"view": {"k": 2, "x": float("inf"), "y": 0}}):
            window.bridge.viewChanged(json.dumps(changed))
        self.assertEqual(updates, [event])
        self.assertFalse(hasattr(window.bridge, "dispatch"))

    def test_layout_is_retained_after_close_and_clamped_when_restored(self):
        self.manager.set_saved_layout("spot", {"x": -100000, "y": -100000,
                                               "width": 200000, "height": 200000, "maximized": False})
        window = self.manager.open_chart("spot", payload("spot"))
        QT_APP.processEvents()
        available = window.screen().availableGeometry()
        self.assertLessEqual(window.width(), available.width())
        self.assertLessEqual(window.height(), available.height())
        self.assertGreaterEqual(window.x(), available.x())
        window.close()
        snapshot = self.manager.snapshot()
        self.assertFalse(snapshot["spot"]["open"])
        self.assertIsNotNone(snapshot["spot"]["window"])
        self.assertEqual(snapshot["mtf"], {"open": False, "window": None})

    def test_shutdown_destroys_owned_windows_and_does_not_close_parent(self):
        window = self.manager.open_chart("mtf", payload())
        destroyed = []
        window.destroyed.connect(lambda: destroyed.append(True))
        self.manager.shutdown()
        self.assertEqual(destroyed, [True])
        self.assertTrue(self.parent.isVisible())
        self.assertIsNone(self.manager.window("mtf"))
        self.assertIsNone(self.manager.open_chart("mtf", payload()))


if __name__ == "__main__":
    unittest.main()

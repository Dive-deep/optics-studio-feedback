"""Native session contracts fail before partial restoration or file replacement."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from optics_ui.services.files import FileDataError, FileDataService
from optics_ui.services.workbench_state import WorkbenchStateError, validate_workbench_state


def workbench():
    return {"version": 1, "page": "explorer", "llm_visible": False,
            "analysis_visible": True, "workspace_split": [900, 320],
            "explorer": {"workspace_root": "/recorded/workspace", "files": ["src/main.py", "target.json"],
                         "current_file": "src/main.py", "wrap_lines": False},
            "sensitivity": None}


def panel():
    return {"format": "optics-sensitivity-panel", "schema_version": 1,
            "metric": "ST", "report": None, "report_path": None, "output_id": None}


def window_rect():
    return {"x": -1280, "y": -80, "width": 1280, "height": 720, "maximized": False}


def workbench_v2():
    value = workbench()
    value.update(version=2, layout={"window": window_rect(), "llm_width": 310,
                 "explorer_split": [240, 800], "charts": {
                     "mtf": {"open": False, "window": None}, "spot": {"open": False, "window": None}}})
    return value


class WorkbenchStateTests(unittest.TestCase):
    def test_v1_stays_v1_without_injecting_layout_defaults(self):
        original = workbench()
        self.assertEqual(validate_workbench_state(original), original)
        self.assertNotIn("layout", validate_workbench_state(original))

    def test_v2_layout_and_chart_windows_are_detached_and_keep_negative_coordinates(self):
        original = workbench_v2()
        original["layout"]["charts"]["mtf"] = {"open": True, "window": window_rect()}
        validated = validate_workbench_state(original)
        self.assertEqual(validated, original)
        validated["layout"]["window"]["x"] = 100
        validated["layout"]["charts"]["mtf"]["window"]["y"] = 100
        validated["layout"]["explorer_split"][0] = 10
        self.assertEqual(original["layout"]["window"]["x"], -1280)
        self.assertEqual(original["layout"]["charts"]["mtf"]["window"]["y"], -80)
        self.assertEqual(original["layout"]["explorer_split"], [240, 800])

    def test_v2_nullable_windows_do_not_invent_position_and_allow_collapsed_explorer_tree(self):
        source = workbench_v2()
        source["layout"]["window"] = None
        source["layout"]["charts"]["mtf"]["open"] = True
        source["layout"]["explorer_split"] = [0, 800]
        source["page"] = "sim"
        result = validate_workbench_state(source)
        self.assertIsNone(result["layout"]["window"])
        self.assertIsNone(result["layout"]["charts"]["mtf"]["window"])
        self.assertEqual(result["page"], "workspace")

    def test_v2_layout_fields_are_required_and_exact(self):
        mutations = [lambda v: v.pop("layout"), lambda v: v.update(layout=None),
                     lambda v: v["layout"].update(unexpected=True), lambda v: v["layout"].pop("llm_width"),
                     lambda v: v["layout"]["charts"].pop("spot"),
                     lambda v: v["layout"]["charts"].update(other={}),
                     lambda v: v["layout"]["charts"]["mtf"].pop("window"),
                     lambda v: v["layout"]["charts"]["mtf"].update(open=1),
                     lambda v: v["layout"]["charts"]["spot"].update(unknown=1)]
        for mutate in mutations:
            source = workbench_v2()
            mutate(source)
            with self.subTest(source=source), self.assertRaises(WorkbenchStateError):
                validate_workbench_state(source)
        for version in (1, 3, True):
            source = workbench_v2()
            source["version"] = version
            with self.assertRaises(WorkbenchStateError):
                validate_workbench_state(source)

    def test_v2_main_and_chart_rectangles_use_the_same_strict_qt_integer_bounds(self):
        invalid = [("x", -2147483649), ("x", 2147483648), ("y", False), ("y", 1.5),
                   ("width", 0), ("width", 16777216), ("height", -1), ("height", "720"),
                   ("maximized", 1), ("unknown", 10)]
        for location in ("main", "chart"):
            for key, value in invalid:
                source = workbench_v2()
                rect = source["layout"]["window"] if location == "main" else window_rect()
                rect[key] = value
                if location == "chart":
                    source["layout"]["charts"]["spot"]["window"] = rect
                with self.subTest(location=location, key=key), self.assertRaises(WorkbenchStateError):
                    validate_workbench_state(source)
        source = workbench_v2()
        source["layout"]["window"].update(x=-2147483648, y=2147483647, width=16777215, height=1, maximized=True)
        self.assertEqual(validate_workbench_state(source), source)

    def test_v2_llm_width_and_explorer_split_have_explicit_bounds(self):
        for key, value in [("llm_width", 0), ("llm_width", 16777216), ("llm_width", True),
                           ("llm_width", 310.5), ("explorer_split", [0, 0]),
                           ("explorer_split", [-1, 5]), ("explorer_split", [10]),
                           ("explorer_split", [1.2, 20]), ("explorer_split", [2147483648, 5])]:
            source = workbench_v2()
            source["layout"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(WorkbenchStateError):
                validate_workbench_state(source)

    def test_valid_state_is_detached_and_sim_returns_to_workspace(self):
        source = workbench()
        source["page"] = "sim"
        validated = validate_workbench_state(source)
        self.assertEqual(validated["page"], "workspace")
        self.assertEqual(source["page"], "sim")
        validated["explorer"]["files"].append("other.py")
        validated["workspace_split"][0] = 30
        self.assertEqual(source["explorer"]["files"], ["src/main.py", "target.json"])
        self.assertEqual(source["workspace_split"], [900, 320])

    def test_other_os_absolute_roots_are_preserved_without_filesystem_io(self):
        for root in ["/recorded/workspace", "C:\\Users\\Designer\\Optics", "C:/Optics", "\\\\server\\share\\project"]:
            source = workbench()
            source["explorer"]["workspace_root"] = root
            with self.subTest(root=root), mock.patch.object(Path, "exists", side_effect=AssertionError("No IO")), mock.patch.object(Path, "resolve", side_effect=AssertionError("No IO")):
                self.assertEqual(validate_workbench_state(source)["explorer"]["workspace_root"], root)

    def test_bad_version_pages_flags_and_split_sizes_are_rejected(self):
        changes = [("version", True), ("version", 2), ("page", "run_code"), ("page", None),
                   ("llm_visible", 1), ("analysis_visible", "true"),
                   ("workspace_split", [1]), ("workspace_split", [True, 1]),
                   ("workspace_split", [-1, 50]), ("workspace_split", [1.5, 50]),
                   ("workspace_split", [0, 0]),
                   ("workspace_split", [2**31, 50])]
        for key, value in changes:
            source = workbench()
            source[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(WorkbenchStateError):
                validate_workbench_state(source)
        source = workbench()
        source["workspace_split"] = [0, 100]
        self.assertEqual(validate_workbench_state(source)["workspace_split"], [0, 100])

    def test_files_are_bounded_clean_relative_posix_paths(self):
        bad = ["", ".", "..", "./main.py", "src/../main.py", "/main.py", "C:main.py",
               "C:/main.py", "src\\main.py", "src//main.py", "bad\x00.py", "x" * 4097]
        for path in bad:
            source = workbench()
            source["explorer"].update(files=[path], current_file=None)
            with self.subTest(path=path[:30]), self.assertRaises(WorkbenchStateError):
                validate_workbench_state(source)
        for files in [["same.py", "same.py"], [f"file-{i}.py" for i in range(65)]]:
            source = workbench()
            source["explorer"].update(files=files, current_file=None)
            with self.assertRaises(WorkbenchStateError):
                validate_workbench_state(source)

    def test_explorer_selection_root_and_schema_are_validated(self):
        for key, value in [("workspace_root", "relative/root"), ("workspace_root", "C:relative"),
                           ("workspace_root", "bad\x00/root"), ("current_file", "absent.py"),
                           ("current_file", 0), ("wrap_lines", 1), ("files", "main.py")]:
            source = workbench()
            source["explorer"][key] = value
            with self.subTest(key=key), self.assertRaises(WorkbenchStateError):
                validate_workbench_state(source)
        for nested in [False, True]:
            source = workbench()
            target = source["explorer"] if nested else source
            target["unknown"] = "value"
            with self.assertRaises(WorkbenchStateError):
                validate_workbench_state(source)
        source = workbench()
        del source["analysis_visible"]
        with self.assertRaises(WorkbenchStateError):
            validate_workbench_state(source)

    def test_sensitivity_uses_the_panel_contract_and_one_mib_report_limit(self):
        source = workbench()
        source["sensitivity"] = panel()
        self.assertEqual(validate_workbench_state(source)["sensitivity"], panel())
        source["sensitivity"]["metric"] = "invented"
        with self.assertRaises(WorkbenchStateError):
            validate_workbench_state(source)
        source["sensitivity"] = panel()
        source["sensitivity"]["report"] = {"padding": "x" * (1024 * 1024)}
        with self.assertRaisesRegex(WorkbenchStateError, "1 MiB"):
            validate_workbench_state(source)


class WorkbenchFileStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workbench-state-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = FileDataService()

    def invalid(self):
        native = workbench()
        native["workspace_split"] = ["not-a-number", 100]
        return {"ordinary": "preserved", "workbench": native}

    def test_v2_file_roundtrip_preserves_layout_and_chart_window_preferences(self):
        source = {"workbench": workbench_v2()}
        source["workbench"]["layout"]["charts"]["spot"] = {"open": True, "window": window_rect()}
        original = copy.deepcopy(source)
        path = self.root / "v2.optics.json"
        self.service.save_session(path, source, {})
        self.assertEqual(self.service.load_session(path)["state"], original)
        bundle = self.root / "v2.zip"
        self.service.export_bundle(bundle, source, {})
        with zipfile.ZipFile(bundle) as archive:
            self.assertEqual(json.loads(archive.read("session.optics.json"))["state"], original)
        self.assertEqual(source, original)

    def test_invalid_v2_chart_layout_rejects_save_and_export_without_replacement(self):
        source = {"workbench": workbench_v2()}
        source["workbench"]["layout"]["charts"]["spot"]["window"] = {"x": 0}
        for filename, operation in [("v2.optics.json", self.service.save_session), ("v2.zip", self.service.export_bundle)]:
            path = self.root / filename
            path.write_bytes(b"previous data")
            with self.subTest(filename=filename), self.assertRaises(FileDataError) as caught:
                operation(path, source, {})
            self.assertEqual(caught.exception.code, "SESSION_WORKBENCH")
            self.assertEqual(path.read_bytes(), b"previous data")

    def test_invalid_save_preserves_previous_file_and_creates_no_temporary_output(self):
        path = self.root / "session.optics.json"
        path.write_bytes(b"previous session")
        before = set(self.root.iterdir())
        with self.assertRaises(FileDataError) as caught:
            self.service.save_session(path, self.invalid(), {})
        self.assertEqual(caught.exception.code, "SESSION_WORKBENCH")
        self.assertEqual(path.read_bytes(), b"previous session")
        self.assertEqual(set(self.root.iterdir()), before)

    def test_invalid_export_preserves_existing_bundle(self):
        path = self.root / "session.zip"
        path.write_bytes(b"previous bundle")
        with self.assertRaises(FileDataError) as caught:
            self.service.export_bundle(path, self.invalid(), {})
        self.assertEqual(caught.exception.code, "SESSION_WORKBENCH")
        self.assertEqual(path.read_bytes(), b"previous bundle")

    def test_invalid_load_fails_before_reference_processing(self):
        path = self.root / "session.optics.json"
        path.write_text(json.dumps({"format": "optics-ui-session", "schema_version": 1,
                                   "state": self.invalid(), "references": {}}), encoding="utf-8")
        with mock.patch("optics_ui.services.files._references", side_effect=AssertionError("No partial restore")):
            with self.assertRaises(FileDataError) as caught:
                self.service.load_session(path)
        self.assertEqual(caught.exception.code, "SESSION_WORKBENCH")

    def test_save_load_and_export_normalize_without_changing_callers_state(self):
        native = workbench()
        native["page"] = "sim"
        state = {"extraFutureField": {"value": 3}, "workbench": native}
        original = copy.deepcopy(state)
        path = self.root / "session.optics.json"
        self.service.save_session(path, state, {})
        restored = self.service.load_session(path)["state"]
        self.assertEqual(restored["workbench"]["page"], "workspace")
        self.assertEqual(restored["extraFutureField"], {"value": 3})
        bundle = self.root / "session.zip"
        self.service.export_bundle(bundle, state, {})
        with zipfile.ZipFile(bundle) as archive:
            exported = json.loads(archive.read("session.optics.json"))
        self.assertEqual(exported["state"]["workbench"]["page"], "workspace")
        self.assertEqual(state, original)

    def test_existing_credential_guard_still_runs_before_workbench_validation(self):
        state = {"workbench": workbench()}
        state["workbench"]["api_key"] = "example credential"
        with self.assertRaises(FileDataError) as caught:
            self.service.save_session(self.root / "session.json", state, {})
        self.assertEqual(caught.exception.code, "SESSION_CREDENTIALS")


if __name__ == "__main__":
    unittest.main()

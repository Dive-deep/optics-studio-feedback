"""Desktop request contract tests, written before the host implementation."""
import contextlib
import io
import json
import threading
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer
from optics_ui.bridge import BridgeError, DesktopBridge, RequestRouter
from optics_ui.desktop import smoke_dialog_configuration


class DataError(ValueError):
    def __init__(self, code, message):
        self.code, self.message = code, message


class Files:
    def __init__(self):
        self.calls = []

    def __getattr__(self, method):
        def call(*args):
            self.calls.append((method, args))
            if method == "list_cases":
                return [{"id": "case-1"}]
            return {"status": "valid", "method": method, "args": list(args)}
        return call


class BridgeContractTests(unittest.TestCase):
    def setUp(self):
        self.files = Files()
        self.scheduled = []
        self.router = RequestRouter(self.files, dialogs={
            "choose_report": lambda: "/data/training report.json",
            "choose_target": lambda: "/data/targets.json",
            "choose_session_open": lambda: "/data/design.optics.json",
            "choose_session_save": lambda: "/data/saved.optics.json",
            "export_bundle": lambda: "/data/bundle.zip",
        }, defer_compute=lambda request_id, target: self.scheduled.append((request_id, target)))

    def request(self, method, params=None, request_id="r1"):
        return self.router.dispatch(json.dumps({"id": request_id, "method": method, "params": params or {}}))

    def test_report_selection_preserves_service_result(self):
        result = self.request("choose_report")
        self.assertTrue(result["ok"])
        self.assertEqual(result["id"], "r1")
        self.assertEqual(self.files.calls, [("load_report", ("/data/training report.json",))])
        self.assertEqual(result["data"]["method"], "load_report")

    def test_known_file_methods_have_specific_arguments(self):
        self.request("load_report", {"path": "/data/report.json"})
        self.request("load_case", {"path": "/data/cases.sqlite", "case_id": "case-1"})
        self.request("choose_target")
        result = self.request("list_cases", {"path": "/data/cases.sqlite"})
        self.assertEqual(result["data"], {"cases": [{"id": "case-1"}]})
        self.assertEqual(self.files.calls[1], ("load_case", ("/data/cases.sqlite", "case-1")))
        self.assertEqual(self.files.calls[2], ("load_target", ("/data/targets.json",)))

    def test_session_save_open_and_bundle_preserve_references(self):
        state = {"active_parameters": ["r1"], "a12": None}
        refs = {"report_path": "/data/report.json", "database_path": "/data/cases.sqlite", "target_path": None}
        self.request("choose_session_open")
        self.request("choose_session_save", {"state": state, "references": refs})
        self.request("export_bundle", {"state": state, "references": refs})
        self.assertEqual(self.files.calls[0], ("load_session", ("/data/design.optics.json",)))
        self.assertEqual(self.files.calls[1], ("save_session", ("/data/saved.optics.json", state, refs)))
        self.assertEqual(self.files.calls[2], ("export_bundle", ("/data/bundle.zip", state, refs)))

    def test_native_dialog_cancel_does_not_call_service(self):
        self.router.dialogs["choose_report"] = lambda: ""
        result = self.request("choose_report")
        self.assertEqual(result["data"], {"status": "cancelled"})
        self.assertEqual(self.files.calls, [])

    def test_compute_is_deferred_and_does_not_run_in_dispatch(self):
        result = self.request("compute_test", {"target": "local"}, "gpu-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], {"status": "started", "deferred": True, "request_id": "gpu-1", "target": "local"})
        self.assertEqual(self.scheduled, [("gpu-1", "local")])
        self.assertEqual(self.files.calls, [])

    def test_file_work_is_deferred_after_native_dialog_selection(self):
        pending = []
        router = RequestRouter(self.files, dialogs={"choose_report": lambda: "/data/report.json"},
                               defer_files=lambda request_id, operation: pending.append((request_id, operation)))
        result = router.dispatch(json.dumps({"id": "file-1", "method": "choose_report", "params": {}}))
        self.assertTrue(result["data"]["deferred"])
        self.assertEqual(self.files.calls, [])
        self.assertEqual(pending[0][0], "file-1")
        self.assertEqual(pending[0][1]()["method"], "load_report")

    def test_invalid_requests_are_rejected_before_services(self):
        cases = [("read_file", {"path": "/any/file"}, "UNKNOWN_METHOD"),
                 ("run_zemax", {}, "UNKNOWN_METHOD"), ("compute_test", {"target": "other"}, "INVALID_PARAMS"),
                 ("load_report", {"path": 123}, "INVALID_PARAMS"),
                 ("load_case", {"path": "/db", "case_id": ""}, "INVALID_PARAMS"),
                 ("choose_report", {"unexpected": True}, "INVALID_PARAMS"),
                 ("choose_session_save", {"state": {}, "references": {"unknown": "x"}}, "INVALID_PARAMS")]
        for method, params, code in cases:
            with self.subTest(method=method, params=params):
                result = self.request(method, params)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], code)
        self.assertEqual(self.files.calls, [])
        self.assertEqual(self.scheduled, [])

    def test_malformed_envelopes_are_rejected(self):
        for raw in ("not json", "[]", '{}', '{"id":1,"method":"choose_report"}',
                    '{"id":"r1","method":"choose_report","params":[]}'):
            with self.subTest(raw=raw):
                self.assertFalse(self.router.dispatch(raw)["ok"])
        self.assertEqual(self.files.calls, [])

    def test_secrets_are_not_saved_echoed_or_logged(self):
        secret = "DO-NOT-LOG-THIS-SECRET"
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = self.request("choose_session_save", {"state": {"nested": [{"api_key": secret}]}, "references": {}})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CREDENTIALS_NOT_ALLOWED")
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn(secret, output.getvalue())
        self.assertEqual(self.files.calls, [])

    def test_expected_service_errors_keep_code_unknown_errors_are_generic(self):
        def fail(_):
            raise DataError("REPORT_MISSING", "The selected report is missing")
        self.files.load_report = fail
        result = self.request("load_report", {"path": "/data/report.json"})
        self.assertEqual(result["error"]["code"], "REPORT_MISSING")
        def unknown(_):
            raise RuntimeError("private implementation detail")
        self.files.load_report = unknown
        result = self.request("load_report", {"path": "/data/report.json"})
        self.assertEqual(result["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("private implementation detail", json.dumps(result))

    def test_real_qt_worker_completes_on_ui_thread_without_blocking_events(self):
        application = QCoreApplication.instance() or QCoreApplication([])
        gate = threading.Event()
        observed = {}
        class Compute:
            def test(self, target):
                observed["worker_is_ui_thread"] = QThread.currentThread() == application.thread()
                observed["ui_tick_released_worker"] = gate.wait(timeout=1)
                return {"target": target, "status": "unsupported", "ready": False}
        bridge = DesktopBridge(self.files, Compute(), dialogs={})
        loop = QEventLoop()
        responses = []
        def receive(raw):
            observed["response_is_ui_thread"] = QThread.currentThread() == application.thread()
            responses.append(json.loads(raw))
            loop.quit()
        bridge.responseReady.connect(receive)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(gate.set)
        timer.start(10)
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(2000)
        acknowledgement = json.loads(bridge.dispatch(json.dumps({"id": "thread-1", "method": "compute_test", "params": {"target": "local"}})))
        self.assertTrue(acknowledgement["data"]["deferred"])
        loop.exec()
        timer.stop()
        watchdog.stop()
        bridge.shutdown()
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], "thread-1")
        self.assertEqual(observed, {"worker_is_ui_thread": False, "ui_tick_released_worker": True, "response_is_ui_thread": True})

    def test_opt_in_smoke_dialogs_are_explicit_path_stubs(self):
        callbacks, config = smoke_dialog_configuration(Path("/tmp/optics smoke"), Path("/tmp/demo/report.json"), Path("/tmp/demo/target.json"))
        self.assertTrue(config["dialog_stubs"])
        self.assertEqual(callbacks["choose_report"](), str(Path("/tmp/demo/report.json").resolve()))
        self.assertEqual(callbacks["choose_target"](), str(Path("/tmp/demo/target.json").resolve()))
        self.assertEqual(callbacks["choose_session_save"](), callbacks["choose_session_open"]())
        self.assertTrue(callbacks["export_bundle"]().endswith("ui-roundtrip.zip"))
        callbacks, config = smoke_dialog_configuration(Path("/tmp/optics smoke"), None, None)
        self.assertIsNone(callbacks)
        self.assertFalse(config["dialog_stubs"])

    def test_partial_smoke_path_never_opens_an_unattended_dialog(self):
        callbacks, config = smoke_dialog_configuration(Path("/tmp/optics smoke"), Path("/tmp/demo/report.json"), None)
        self.assertTrue(config["dialog_stubs"])
        self.assertEqual(callbacks["choose_target"](), "")

    def test_native_report_drop_emits_start_before_validation_and_completion(self):
        bridge = DesktopBridge(self.files, object(), dialogs={})
        events = []
        bridge.reportLoadStarted.connect(lambda raw: events.append(("start", json.loads(raw))))
        bridge.reportLoaded.connect(lambda raw: events.append(("loaded", json.loads(raw))))
        def dispatch(raw):
            request = json.loads(raw)
            events.append(("validation", {"id": request["id"]}))
            return {"id": request["id"], "ok": True, "data": {"status": "valid"}}
        bridge.router.dispatch = dispatch
        bridge.load_dropped_report("/data/report.json", "drop-1")
        self.assertEqual([name for name, _ in events], ["start", "validation", "loaded"])
        self.assertEqual(events[0][1], {"id": "drop-1", "path": "/data/report.json"})
        self.assertTrue(all(event["id"] == "drop-1" for _, event in events))
        bridge.shutdown()

    def test_native_invalid_drop_emits_start_before_matching_error(self):
        bridge = DesktopBridge(self.files, object(), dialogs={})
        events = []
        bridge.reportLoadStarted.connect(lambda raw: events.append(("start", json.loads(raw))))
        bridge.reportLoaded.connect(lambda raw: events.append(("loaded", json.loads(raw))))
        bridge.reject_dropped_report("drop-invalid", BridgeError("DROP_COUNT", "Choose one local training report JSON."))
        self.assertEqual([name for name, _ in events], ["start", "loaded"])
        self.assertEqual(events[0][1], {"id": "drop-invalid"})
        self.assertEqual(events[1][1]["id"], "drop-invalid")
        self.assertFalse(events[1][1]["ok"])
        self.assertEqual(events[1][1]["error"]["code"], "DROP_COUNT")
        self.assertEqual(self.files.calls, [])
        bridge.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)

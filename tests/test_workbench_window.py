"""Native pages, LLM coexistence and atomic session/parameter command flows."""
from tests.qt_support import QT_APP

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import QObject, Signal, QCoreApplication, QEvent, QSize
from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from tests.test_parameter_draft import make_payload
from optics_ui.workbench.window import WorkbenchWindow


class FakeController(QObject):
    stateChanged = Signal(dict)
    sessionRestored = Signal(dict)
    parametersRequested = Signal()
    llmToggleRequested = Signal()
    readyChanged = Signal(bool)
    statusMessage = Signal(str)

    def __init__(self):
        super().__init__()
        self.ready = False
        self.last_state = {"view": "workspace", "parameter_payload": make_payload(),
                           "analysis_context": {}, "llm_draft": "Saved draft", "model_label": "Reference model"}
        self.calls = []
        self.fail_action = None
        self.hold_action = None
        self.pending = []

    def command(self, action, payload=None, callback=None):
        self.calls.append((action, deepcopy(payload)))
        if action == self.hold_action:
            self.pending.append(callback)
        elif callback:
            callback(action != self.fail_action,
                     {"message": "Rejected"} if action == self.fail_action else deepcopy(self.last_state) if action == "get_state" else {})
        return str(len(self.calls))


class WorkbenchWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="window-workspace-")
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.py"
        self.source.write_text("value = 12\n", encoding="utf-8")
        self.controller = FakeController()
        with mock.patch("optics_ui.workbench.window.DEFAULT_WORKSPACE_ROOT", self.root):
            self.window = WorkbenchWindow(QLabel("Renderer fixture"), self.controller, confirm_close=lambda **_: 'discard')

    def tearDown(self):
        self.window.close_for_shutdown()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QT_APP.processEvents()
        self.temp.cleanup()

    def ready(self):
        self.controller.ready = True
        self.controller.readyChanged.emit(True)
        self.controller.calls.clear()

    def test_waits_for_renderer_but_explorer_remains_available(self):
        self.assertFalse(self.window.save_action.isEnabled())
        self.assertFalse(self.window.parameters_action.isEnabled())
        self.window.navigate("explorer")
        self.assertEqual(self.window.current_page, "explorer")
        self.assertTrue(self.window.explorer.open_file(self.source))
        self.assertEqual(self.controller.calls, [])
        self.ready()
        self.assertTrue(self.window.save_action.isEnabled())

    def test_navigation_is_independent_from_code_tabs_and_analysis_only_in_workspace(self):
        self.ready()
        self.window.analysis_action.setChecked(True)
        self.window.navigate("explorer")
        self.window.explorer.open_file(self.source)
        self.assertTrue(self.window.sensitivity.isHidden())
        for page in ("update", "sim", "auto"):
            self.window.navigate(page)
            self.assertEqual(self.window.current_page, page)
            self.assertTrue(self.window.sensitivity.isHidden())
            self.assertEqual(self.controller.calls[-1], ("navigate", {"page": page}))
        self.window.navigate("workspace")
        self.assertFalse(self.window.sensitivity.isHidden())
        self.assertEqual(self.window.explorer.tabs.count(), 1)
        self.window.explorer.close_current_tab()
        self.assertEqual(self.window.current_page, "workspace")

    def test_llm_dock_coexists_with_every_page_and_never_executes_backend(self):
        self.ready()
        self.window.llm_action.setChecked(True)
        self.window.llm_editor.setPlainText("Try a narrower field")
        for page in ("explorer", "workspace", "tailoring", "update", "sim", "auto"):
            self.window.navigate(page)
            self.assertFalse(self.window.llm_dock.isHidden())
            self.assertEqual(self.window.llm_editor.toPlainText(), "Try a narrower field")
        self.assertFalse(self.window.llm_send_button.isEnabled())
        self.assertFalse(any(action.startswith("run") for action, _ in self.controller.calls))

    def test_parameter_cancel_uses_fresh_payload_without_mutating_workspace(self):
        self.ready()
        self.controller.last_state["parameter_payload"]["revision"] = "fresh-revision"
        self.window.open_parameters()
        dialog = self.window.parameter_dialog
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.result_payload()["revision"], "fresh-revision")
        dialog.reject()
        self.assertFalse(any(action == "apply_parameters" for action, _ in self.controller.calls))

    def test_parameter_apply_sends_revision_bound_copy(self):
        self.ready()
        self.window.open_parameters()
        dialog = self.window.parameter_dialog
        dialog._rows["p0"]["value"].setText("8")
        dialog.accept()
        action, payload = self.controller.calls[-1]
        self.assertEqual(action, "apply_parameters")
        self.assertEqual(payload["revision"], "design-17")
        self.assertEqual(payload["parameters"][0]["value"], 8)
        self.assertEqual(self.controller.last_state["parameter_payload"]["parameters"][0]["value"], 6)

    def test_collect_and_restore_preserve_native_pages_and_sensitivity_settings(self):
        self.ready()
        self.window.navigate("explorer")
        self.window.explorer.open_file(self.source)
        self.window.llm_action.setChecked(True)
        self.window.analysis_action.setChecked(True)
        self.window.sensitivity.index_combo.setCurrentIndex(1)
        saved = self.window.collect_state()
        self.assertGreater(sum(saved["workspace_split"]), 0)
        self.assertEqual(saved["explorer"]["files"], ["source.py"])
        self.window.navigate("workspace")
        self.window.explorer.close_current_tab()
        self.window.restore_state({"workbench": saved, "llm_draft": "Restored text"})
        self.assertEqual(self.window.current_page, "explorer")
        self.assertEqual(self.window.explorer.tabs.count(), 1)
        self.assertFalse(self.window.llm_dock.isHidden())
        self.assertEqual(self.window.llm_editor.toPlainText(), "Restored text")
        self.assertEqual(self.window.sensitivity.snapshot()["metric"], "ST")

    def test_invalid_restore_does_not_partially_change_native_state(self):
        self.ready()
        before = self.window.collect_state()
        bad = deepcopy(before)
        bad["llm_visible"] = True
        bad["workspace_split"] = ["wrong", 10]
        self.assertFalse(self.window.restore_state({"workbench": bad, "llm_draft": "Do not apply"}))
        self.assertEqual(self.window.collect_state(), before)
        self.assertEqual(self.window.llm_editor.toPlainText(), "Saved draft")

    def test_simulation_session_page_restores_to_workspace(self):
        self.ready()
        saved = self.window.collect_state()
        saved["page"] = "sim"
        self.window.restore_state({"workbench": saved})
        self.assertEqual(self.window.current_page, "workspace")

    def test_save_pushes_native_state_then_draft_before_file_action(self):
        self.ready()
        self.window.llm_editor.setPlainText("New unsaved draft")
        self.controller.stateChanged.emit({**self.controller.last_state, "llm_draft": "stale draft"})
        self.assertEqual(self.window.llm_editor.toPlainText(), "New unsaved draft")
        self.window.save_session()
        self.assertEqual([action for action, _ in self.controller.calls], ["set_shell_state", "set_llm_draft", "save"])
        self.assertEqual(self.controller.calls[1][1], {"draft": "New unsaved draft"})

    def test_failed_native_state_update_aborts_export(self):
        self.ready()
        self.controller.fail_action = "set_shell_state"
        self.window.export_session()
        self.assertEqual([action for action, _ in self.controller.calls], ["set_shell_state"])
        self.assertTrue(self.window.export_action.isEnabled())

    def test_late_parameter_callback_cannot_open_dialog_after_window_close(self):
        self.ready()
        self.controller.hold_action = "get_state"
        self.window.open_parameters()
        self.window.close()
        self.controller.pending[-1](True, self.controller.last_state)
        self.assertIsNone(self.window.parameter_dialog)

    def test_old_get_state_reply_cannot_override_a_later_navigation(self):
        self.controller.hold_action = "get_state"
        self.ready()
        pending = self.controller.pending[-1]
        self.window.navigate("update")
        pending(True, {**self.controller.last_state, "view": "workspace"})
        self.assertEqual(self.window.current_page, "update")

    def test_restored_explorer_survives_later_optical_state_event(self):
        self.ready()
        saved = self.window.collect_state()
        saved["page"] = "explorer"
        self.window.restore_state({"workbench": saved})
        self.controller.stateChanged.emit({**self.controller.last_state, "view": "workspace"})
        self.assertEqual(self.window.current_page, "explorer")

    def test_explicit_session_restore_replaces_dirty_draft_from_fresh_state(self):
        self.ready()
        for native in [self.window.collect_state(), None]:
            self.window.llm_editor.setPlainText("Unsaved prior-session draft")
            self.controller.last_state["llm_draft"] = "New session draft"
            self.window.restore_state({"workbench": native})
            self.assertEqual(self.window.llm_editor.toPlainText(), "New session draft")

    def test_null_sensitivity_in_new_session_clears_a_previous_report(self):
        from tests.test_sensitivity import report
        self.ready()
        previous = self.window.sensitivity.snapshot()
        previous["report"] = report()
        self.assertTrue(self.window.sensitivity.restore(previous))
        self.assertIsNotNone(self.window.sensitivity.snapshot()["report"])
        saved = self.window.collect_state()
        saved["sensitivity"] = None
        self.window.restore_state({"workbench": saved})
        self.assertIsNone(self.window.sensitivity.snapshot()["report"])

    def test_activity_icons_render_from_packaged_local_svg(self):
        for page, button in self.window.nav_buttons.items():
            with self.subTest(page=page):
                self.assertFalse(button.icon().pixmap(QSize(22, 22)).isNull())
                self.assertTrue(button.toolTip())
                self.assertTrue(button.accessibleName())

    def test_late_state_query_cannot_replace_newer_context_model_or_draft(self):
        self.controller.hold_action = "get_state"
        self.ready()
        pending = self.controller.pending[-1]
        fresh = {**self.controller.last_state, "analysis_context": {"identity": "new"},
                 "model_label": "New model", "llm_draft": "New draft"}
        self.controller.stateChanged.emit(fresh)
        pending(True, {**self.controller.last_state, "analysis_context": {"identity": "old"},
                       "model_label": "Old model", "llm_draft": "Old draft"})
        self.assertEqual(self.window.sensitivity._context, {"identity": "new"})
        self.assertEqual(self.window.model_label.text(), "New model")
        self.assertEqual(self.window.llm_editor.toPlainText(), "New draft")

    def test_session_restore_cancels_old_save_callbacks_without_overwriting_new_draft(self):
        self.ready()
        self.controller.hold_action = "set_shell_state"
        self.window.llm_editor.setPlainText("Session A")
        self.window.save_session()
        old = self.controller.pending[-1]
        self.window.restore_state({"workbench": self.window.collect_state(), "llm_draft": "Session B"})
        self.controller.calls.clear()
        self.controller.hold_action = None
        old(True, {})
        self.assertEqual(self.controller.calls, [])
        self.assertEqual(self.window.llm_editor.toPlainText(), "Session B")
        self.assertTrue(self.window.save_action.isEnabled())

    def test_old_save_callback_cannot_release_a_new_session_save(self):
        self.ready()
        self.controller.hold_action = "set_shell_state"
        self.window.save_session()
        old = self.controller.pending[-1]
        self.window.restore_state({"workbench": None, "llm_draft": "Session B"})
        self.window.save_session()
        current = self.controller.pending[-1]
        old(True, {})
        self.assertFalse(self.window.save_action.isEnabled())
        self.controller.hold_action = None
        current(True, {})
        self.assertEqual(self.controller.calls[-2:], [("set_llm_draft", {"draft": "Session B"}), ("save", None)])

    def test_invalid_or_absent_session_does_not_cancel_valid_save_preparation(self):
        self.ready()
        self.controller.hold_action = "set_shell_state"
        self.window.save_session()
        pending = self.controller.pending[-1]
        bad = self.window.collect_state()
        bad["version"] = 9
        self.assertFalse(self.window.restore_state({"workbench": bad}))
        self.assertFalse(self.window.restore_state(None))
        self.controller.hold_action = None
        pending(True, {})
        self.assertEqual(self.controller.calls[-1][0], "save")

    def test_native_apply_failure_retains_dialog_and_draft_for_review(self):
        self.ready()
        self.window.open_parameters()
        dialog = self.window.parameter_dialog
        dialog._rows["p0"]["value"].setText("8")
        self.controller.hold_action = "apply_parameters"
        dialog.accept()
        self.assertIs(self.window.parameter_dialog, dialog)
        self.controller.pending[-1](False, {"message": "설계 revision이 변경되었습니다."})
        self.assertIs(self.window.parameter_dialog, dialog)
        self.assertEqual(dialog.result_payload()["parameters"][0]["value"], 8)
        self.assertIn("revision", dialog.error_label.text())
        self.assertEqual(dialog.result_payload()["revision"], "design-17")

    def test_native_apply_success_closes_and_parent_close_is_safe_while_pending(self):
        self.ready()
        self.window.open_parameters()
        self.controller.hold_action = "apply_parameters"
        self.window.parameter_dialog.accept()
        self.assertIsNotNone(self.window.parameter_dialog)
        self.controller.pending[-1](True, {"status": "applied"})
        self.assertIsNone(self.window.parameter_dialog)
        self.window.open_parameters()
        self.window.parameter_dialog.accept()
        pending = self.controller.pending[-1]
        self.window.close()
        pending(True, {"status": "applied"})
        self.assertIsNone(self.window.parameter_dialog)

    def test_renderer_unavailable_does_not_leave_parameter_dialog_busy(self):
        self.ready()
        self.window.open_parameters()
        dialog = self.window.parameter_dialog
        self.controller.ready = False
        self.controller.readyChanged.emit(False)
        self.controller.calls.clear()
        dialog.accept()
        self.assertIs(self.window.parameter_dialog, dialog)
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertTrue(dialog.error_label.text())
        self.assertEqual(self.controller.calls, [])

    def test_llm_shortcut_toggles_without_changing_active_page(self):
        self.ready()
        self.window.navigate("explorer")
        self.window.show()
        self.window.activateWindow()
        QT_APP.processEvents()
        QTest.keySequence(self.window, QKeySequence("Ctrl+Alt+B"))
        QT_APP.processEvents()
        self.assertFalse(self.window.llm_dock.isHidden())
        self.assertEqual(self.window.current_page, "explorer")
        QTest.keySequence(self.window.llm_editor, QKeySequence("Ctrl+Alt+B"))
        QT_APP.processEvents()
        self.assertTrue(self.window.llm_dock.isHidden())


if __name__ == "__main__":
    unittest.main()

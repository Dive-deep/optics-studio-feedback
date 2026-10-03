"""Close decisions and layout restore exercise the native command boundary."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.qt_support import QT_APP
from tests.test_workbench_window import FakeController
from tests.test_chart_windows import payload as chart_payload, FakePage, FakeView
from PySide6.QtCore import QCoreApplication, QEvent, Signal, QTimer, Qt
from PySide6.QtWidgets import QLabel, QMessageBox
from PySide6.QtTest import QTest
from optics_ui.workbench.window import WorkbenchWindow
from optics_ui.workbench.charts import ChartWindowManager


class SessionController(FakeController):
    chartRequested = Signal(dict)
    sessionOpened = Signal(dict)

    def __init__(self):
        super().__init__()
        self.fingerprint = 'initial'
        self.save_status = 'saved'

    def command(self, action, payload=None, callback=None):
        if action in ('get_session_snapshot', 'save'):
            self.calls.append((action, deepcopy(payload)))
            if action == self.hold_action:
                self.pending.append(callback)
            elif callback:
                if action == self.fail_action:
                    callback(False, {'message': 'Disk write failed'})
                elif action == 'get_session_snapshot':
                    callback(True, {'snapshot': {}, 'references': {}, 'session_fingerprint': self.fingerprint})
                else:
                    callback(True, None if self.save_status == 'cancelled' else
                             {'status': 'saved', 'session_fingerprint': self.fingerprint})
            return str(len(self.calls))
        return super().command(action, payload, callback)


class FinishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.controller = SessionController()
        self.decisions = []
        self.prompt_calls = []
        def prompt(**kwargs):
            self.prompt_calls.append(kwargs)
            return self.decisions.pop(0) if self.decisions else 'cancel'
        with patch('optics_ui.workbench.window.DEFAULT_WORKSPACE_ROOT', Path(self.temp.name)):
            self.window = WorkbenchWindow(QLabel('Renderer'), self.controller, confirm_close=prompt)
        self.window.show()
        QT_APP.processEvents()
        self.controller.ready = True
        self.controller.readyChanged.emit(True)
        QT_APP.processEvents()

    def tearDown(self):
        self.window.close_for_shutdown()
        if self.window.chart_manager is not None:
            self.window.chart_manager.shutdown()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QT_APP.processEvents()
        self.temp.cleanup()

    def close(self):
        self.window.close()
        QT_APP.processEvents()

    def charts(self):
        manager = ChartWindowManager(None, self.window, page_factory=lambda view: FakePage(view), view_factory=FakeView)
        self.window.attach_chart_manager(manager)
        return manager

    def test_layout_v2_contains_main_and_analysis_windows_and_panel_widths(self):
        state = self.window.collect_state()
        self.assertEqual(state['version'], 2)
        self.assertEqual(set(state['layout']), {'window', 'llm_width', 'explorer_split', 'charts'})
        self.assertGreater(state['layout']['window']['width'], 0)
        self.assertGreater(sum(state['layout']['explorer_split']), 0)
        self.assertEqual(set(state['layout']['charts']), {'mtf', 'spot'})

    def test_clean_close_does_not_prompt(self):
        self.close()
        self.assertTrue(self.window._closed)
        self.assertEqual(self.prompt_calls, [])

    def test_real_dialog_escape_means_cancel(self):
        QTimer.singleShot(0, lambda: QTest.keyClick(QT_APP.activeModalWidget(), Qt.Key.Key_Escape))
        self.assertEqual(self.window._confirm_unsaved_close(), 'cancel')

    def test_real_dialog_distinguishes_save_and_discard(self):
        for button, expected in ((QMessageBox.StandardButton.Save, 'save'),
                                 (QMessageBox.StandardButton.Discard, 'discard')):
            QTimer.singleShot(0, lambda selected=button: QT_APP.activeModalWidget().button(selected).click())
            self.assertEqual(self.window._confirm_unsaved_close(), expected)

    def test_cancel_dirty_close_keeps_window_and_values(self):
        self.window.llm_editor.setPlainText('unsaved instructions')
        self.decisions = ['cancel']
        self.close()
        self.assertFalse(self.window._closed)
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window.llm_editor.toPlainText(), 'unsaved instructions')
        self.assertEqual(len(self.prompt_calls), 1)

    def test_discard_closes_without_a_save_request(self):
        self.controller.fingerprint = 'edited'
        self.decisions = ['discard']
        self.close()
        self.assertTrue(self.window._closed)
        self.assertNotIn('save', [a for a, _ in self.controller.calls])

    def test_save_before_close_requires_actual_success(self):
        self.controller.fingerprint = 'edited'
        self.decisions = ['save']
        self.close()
        self.assertTrue(self.window._closed)
        self.assertEqual([a for a, _ in self.controller.calls].count('save'), 1)

    def test_cancelled_save_dialog_keeps_unsaved_window(self):
        self.controller.fingerprint = 'edited'
        self.controller.save_status = 'cancelled'
        self.decisions = ['save']
        self.close()
        self.assertFalse(self.window._closed)
        self.assertTrue(self.window.isVisible())

    def test_write_failure_does_not_close(self):
        self.controller.fingerprint = 'edited'
        self.controller.fail_action = 'save'
        self.decisions = ['save']
        self.close()
        self.assertFalse(self.window._closed)
        self.assertIn('failed', self.window.statusBar().currentMessage().lower())

    def test_edits_during_save_are_not_marked_saved_or_discarded(self):
        self.controller.fingerprint = 'before-save'
        self.controller.hold_action = 'save'
        self.decisions = ['save', 'cancel']
        self.close()
        callback = self.controller.pending[-1]
        self.controller.fingerprint = 'after-save-started'
        callback(True, {'status': 'saved', 'session_fingerprint': 'before-save'})
        QT_APP.processEvents()
        self.assertFalse(self.window._closed)
        self.assertEqual(len(self.prompt_calls), 2)

    def test_native_layout_change_counts_as_unsaved(self):
        self.window.llm_action.setChecked(True)
        self.decisions = ['cancel']
        self.close()
        self.assertFalse(self.window._closed)
        self.assertEqual(len(self.prompt_calls), 1)

    def test_old_v1_restore_preserves_current_window_layout(self):
        before = self.window.collect_state()['layout']['window']
        old = self.window.collect_state()
        old['version'] = 1
        del old['layout']
        self.assertTrue(self.window.restore_state({'workbench': old, 'llm_draft': 'saved'}))
        self.assertEqual(self.window.collect_state()['layout']['window'], before)

    def test_legacy_restore_refreshes_existing_chart_even_for_same_reference(self):
        manager = self.charts()
        manager.open_chart('mtf', chart_payload())
        old = self.window.collect_state()
        old['version'] = 1
        del old['layout']
        self.controller.hold_action = 'get_chart_data'
        self.window.restore_state({'workbench': old, 'llm_draft': 'saved'})
        self.assertTrue(self.controller.pending)
        payload = chart_payload()
        payload['view'] = {'k': 2, 'x': 15, 'y': 0}
        self.controller.pending[-1](True, payload)
        self.assertEqual(manager.window('mtf').bridge._payload['view'], payload['view'])

    def test_authoritative_snapshot_failure_requires_explicit_discard(self):
        self.controller.fail_action = 'get_session_snapshot'
        self.decisions = ['cancel']
        self.close()
        self.assertFalse(self.window._closed)
        self.assertEqual(len(self.prompt_calls), 1)

    def test_restored_open_chart_survives_reference_refresh_during_its_data_request(self):
        manager = self.charts()
        manager.open_chart('mtf', chart_payload())
        saved = self.window.collect_state()
        self.assertTrue(saved['layout']['charts']['mtf']['open'])
        self.controller.hold_action = 'get_chart_data'
        self.window.restore_state({'workbench': saved, 'llm_draft': 'Saved draft'})
        self.controller.stateChanged.emit({**self.controller.last_state, 'chart_revision': 'restored-reference'})
        callbacks = list(self.controller.pending)
        for callback in callbacks:
            callback(True, chart_payload(revision='restored-reference'))
        self.assertTrue(manager.window('mtf').isVisible())
        self.assertEqual(self.window._layout_restore_pending, 0)

    def test_unavailable_explorer_root_does_not_turn_partial_restore_into_clean_state(self):
        original_root = self.window.explorer.root_path
        saved = self.window.collect_state()
        saved['explorer']['workspace_root'] = str(original_root / 'missing-folder')
        self.window.restore_state({'workbench': saved, 'llm_draft': 'Saved draft'})
        self.assertEqual(self.window.explorer.root_path, original_root)
        self.controller.fingerprint = 'loaded-with-missing-folder'
        self.controller.sessionOpened.emit({'session_fingerprint': self.controller.fingerprint})
        self.decisions = ['cancel']
        self.close()
        self.assertFalse(self.window._closed)
        self.assertEqual(len(self.prompt_calls), 1)

    def test_failed_chart_restore_does_not_mark_missing_window_as_saved(self):
        self.charts()
        saved = self.window.collect_state()
        saved['layout']['charts']['mtf']['open'] = True
        self.controller.fail_action = 'get_chart_data'
        self.window.restore_state({'workbench': saved, 'llm_draft': 'Saved draft'})
        self.controller.fingerprint = 'loaded-with-chart-error'
        self.controller.sessionOpened.emit({'session_fingerprint': self.controller.fingerprint})
        self.decisions = ['cancel']
        self.close()
        self.assertFalse(self.window._closed)
        self.assertEqual(len(self.prompt_calls), 1)

    def test_visiting_hidden_explorer_without_edits_does_not_create_unsaved_layout(self):
        self.window.navigate('explorer')
        QT_APP.processEvents()
        self.window.navigate('workspace')
        QT_APP.processEvents()
        self.close()
        self.assertTrue(self.window._closed)
        self.assertEqual(self.prompt_calls, [])


if __name__ == '__main__':
    unittest.main()

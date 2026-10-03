"""Application Quit must ask the workspace before Qt closes sibling charts."""
import unittest
from unittest.mock import Mock

from tests.qt_support import QT_APP
from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid
from optics_ui.workbench.quit_guard import ApplicationQuitGuard


class QuitGuardTests(unittest.TestCase):
    def setUp(self):
        self.window = QWidget()
        self.window._allow_close = False
        self.window.close = Mock()
        self.guard = ApplicationQuitGuard(QT_APP, self.window)

    def tearDown(self):
        QT_APP.removeEventFilter(self.guard)
        self.guard.deleteLater()
        if isValid(self.window):
            self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_quit_routes_through_main_window_before_closing_any_chart(self):
        self.assertTrue(self.guard.eventFilter(QT_APP, QEvent(QEvent.Type.Quit)))
        self.window.close.assert_called_once()

    def test_confirmed_close_allows_the_real_application_quit(self):
        self.window._allow_close = True
        self.assertFalse(self.guard.eventFilter(QT_APP, QEvent(QEvent.Type.Quit)))
        self.window.close.assert_not_called()

    def test_internal_event_loop_quit_does_not_close_the_workspace(self):
        other = QObject()
        self.assertFalse(self.guard.eventFilter(other, QEvent(QEvent.Type.Quit)))
        self.window.close.assert_not_called()

    def test_other_events_and_deleted_window_are_not_intercepted(self):
        self.assertFalse(self.guard.eventFilter(QT_APP, QEvent(QEvent.Type.User)))
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(self.window, QEvent.Type.DeferredDelete)
        self.assertFalse(self.guard.eventFilter(QT_APP, QEvent(QEvent.Type.Quit)))


if __name__ == '__main__':
    unittest.main()

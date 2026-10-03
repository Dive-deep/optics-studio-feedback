"""Layout restoration stays usable after monitors or DPI layouts change."""
import unittest
from unittest.mock import patch

from tests.qt_support import QT_APP
from PySide6.QtCore import QRect, QSize, QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QDialog
from optics_ui.workbench.layout import fit_window_rect, capture_window_layout, apply_window_layout


class Screen:
    def __init__(self, width, height):
        self.rectangle = QRect(0, 0, width, height)

    def availableGeometry(self):
        return self.rectangle


class LayoutTests(unittest.TestCase):
    def dispose(self, widget):
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)

    def test_actual_widget_with_large_minimum_fits_small_screen_even_after_show(self):
        widget = QWidget()
        self.addCleanup(self.dispose, widget)
        widget.setMinimumSize(960, 620)
        layout = QVBoxLayout(widget)
        content = QLabel("Oversized content uses the smaller available viewport")
        content.setMinimumSize(960, 620)
        layout.addWidget(content)
        screen = Screen(800, 600)
        with patch('optics_ui.workbench.layout.QGuiApplication.screens', return_value=[screen]):
            apply_window_layout(widget, dict(x=-2000, y=-1000, width=1280, height=720, maximized=False))
            widget.show()
            QT_APP.processEvents()
        self.assertTrue(screen.rectangle.contains(widget.geometry()), widget.geometry())
        self.assertEqual(widget.property('preferred_minimum'), QSize(960, 620))

    def test_original_minimum_returns_on_a_larger_monitor(self):
        widget = QWidget()
        self.addCleanup(self.dispose, widget)
        widget.setMinimumSize(960, 620)
        saved = dict(x=20, y=30, width=200, height=100, maximized=False)
        with patch('optics_ui.workbench.layout.QGuiApplication.screens', return_value=[Screen(800, 600)]):
            apply_window_layout(widget, saved)
        self.assertLess(widget.minimumWidth(), 960)
        with patch('optics_ui.workbench.layout.QGuiApplication.screens', return_value=[Screen(1920, 1080)]):
            apply_window_layout(widget, saved)
        self.assertEqual(widget.minimumSize(), QSize(960, 620))
        self.assertGreaterEqual(widget.width(), 960)
        self.assertGreaterEqual(widget.height(), 620)

    def test_explicit_chart_minimum_survives_temporary_screen_constraint(self):
        widget = QWidget()
        self.addCleanup(self.dispose, widget)
        saved = dict(x=20, y=30, width=900, height=650, maximized=False)
        screen = Screen(320, 240)
        with patch('optics_ui.workbench.layout.QGuiApplication.screens', return_value=[screen]):
            apply_window_layout(widget, saved, minimum_size=(420, 300))
        self.assertTrue(screen.rectangle.contains(widget.geometry()))
        self.assertEqual(widget.property('preferred_minimum'), QSize(420, 300))
        with patch('optics_ui.workbench.layout.QGuiApplication.screens', return_value=[Screen(1280, 720)]):
            apply_window_layout(widget, saved | {'width': 1, 'height': 1})
        self.assertEqual(widget.minimumSize(), QSize(420, 300))

    def test_offscreen_window_moves_to_current_screen_and_fits(self):
        saved = dict(x=4000, y=-2000, width=1920, height=1080, maximized=False)
        fitted = fit_window_rect(saved, [dict(x=0, y=0, width=1280, height=680)], minimum=(960, 620))
        self.assertGreaterEqual(fitted['x'], 0)
        self.assertGreaterEqual(fitted['y'], 0)
        self.assertLessEqual(fitted['x'] + fitted['width'], 1280)
        self.assertLessEqual(fitted['y'] + fitted['height'], 680)
        self.assertEqual(saved['x'], 4000)

    def test_negative_coordinate_monitor_is_preserved(self):
        saved = dict(x=-1500, y=100, width=1000, height=650, maximized=True)
        screens = [dict(x=0, y=0, width=1920, height=1040), dict(x=-1920, y=0, width=1920, height=1040)]
        self.assertEqual(fit_window_rect(saved, screens, minimum=(600, 400)), saved)

    def test_small_saved_window_obeys_current_minimum(self):
        result = fit_window_rect(dict(x=100, y=100, width=1, height=1, maximized=False),
                                 [dict(x=0, y=0, width=1280, height=720)], minimum=(960, 620))
        self.assertEqual((result['width'], result['height']), (960, 620))

    def test_widget_capture_apply_does_not_show_hidden_widget(self):
        widget = QWidget()
        try:
            widget.setMinimumSize(400, 300)
            apply_window_layout(widget, dict(x=30, y=45, width=550, height=350, maximized=False))
            self.assertTrue(widget.isHidden())
            saved = capture_window_layout(widget)
            self.assertEqual(saved['width'], 550)
            self.assertEqual(saved['height'], 350)
            self.assertFalse(saved['maximized'])
        finally:
            widget.deleteLater()

    def test_hidden_maximized_window_restores_real_normal_geometry_after_show(self):
        widget = QDialog(None, Qt.WindowType.Window)
        self.addCleanup(self.dispose, widget)
        widget.setGeometry(52, 106, 550, 350)
        widget.show()
        QTest.qWait(20)
        widget.showMaximized()
        QTest.qWait(20)
        widget.hide()
        saved = dict(x=52, y=106, width=550, height=350, maximized=True)
        apply_window_layout(widget, saved)
        self.assertTrue(widget.isHidden())
        self.assertEqual(capture_window_layout(widget), saved)
        widget.show()
        QTest.qWait(50)
        self.assertTrue(widget.isMaximized())
        self.assertEqual(widget.normalGeometry().size(), QSize(550, 350))
        widget.showNormal()
        QTest.qWait(20)
        self.assertEqual(widget.size(), QSize(550, 350))

    def test_new_normal_layout_cancels_pending_hidden_maximize(self):
        widget = QDialog(None, Qt.WindowType.Window)
        self.addCleanup(self.dispose, widget)
        apply_window_layout(widget, dict(x=52, y=106, width=600, height=400, maximized=True))
        saved = dict(x=62, y=116, width=500, height=320, maximized=False)
        apply_window_layout(widget, saved)
        widget.show()
        QTest.qWait(40)
        self.assertFalse(widget.isMaximized())
        self.assertEqual(widget.size(), QSize(500, 320))

    def test_hidden_pending_restore_can_be_shown_later_without_forcing_visibility(self):
        widget = QDialog(None, Qt.WindowType.Window)
        self.addCleanup(self.dispose, widget)
        saved = dict(x=52, y=106, width=550, height=350, maximized=True)
        apply_window_layout(widget, saved)
        QTest.qWait(30)
        self.assertTrue(widget.isHidden())
        self.assertEqual(capture_window_layout(widget), saved)
        widget.show()
        widget.hide()
        QTest.qWait(20)
        widget.show()
        QTest.qWait(50)
        self.assertTrue(widget.isMaximized())
        widget.showNormal()
        QTest.qWait(20)
        self.assertEqual(widget.size(), QSize(550, 350))


if __name__ == '__main__':
    unittest.main()

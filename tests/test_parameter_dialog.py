"""Native, wide parameter dialog user interactions; no backend or source writes."""
from copy import deepcopy
import unittest

from tests.qt_support import QT_APP
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QLineEdit, QPushButton

from optics_ui.workbench.parameters import ParameterDialog
from tests.test_parameter_draft import make_payload


class ParameterDialogTests(unittest.TestCase):
    def setUp(self):
        self.payload = make_payload()
        self.dialog = ParameterDialog(self.payload)
        self.dialog.show()
        QT_APP.processEvents()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        QT_APP.processEvents()

    def edit(self, name, text):
        widget = self.dialog.findChild(QLineEdit, name)
        self.assertIsNotNone(widget, name)
        widget.setText(text)
        widget.editingFinished.emit()
        QT_APP.processEvents()
        return widget

    def apply(self):
        QTest.mouseClick(self.dialog.findChild(QPushButton, "apply-parameters"), Qt.LeftButton)
        QT_APP.processEvents()

    def test_all_parameters_visible_as_rows_with_useful_viewport(self):
        self.assertEqual(self.dialog.table.rowCount(), len(self.payload["parameters"]))
        self.assertGreaterEqual(self.dialog.table.viewport().height(), 12 * 26)
        available = self.dialog.screen().availableGeometry()
        self.assertGreaterEqual(self.dialog.width(), min(800, available.width() - 32))
        self.assertLessEqual(self.dialog.width(), available.width())
        self.assertLessEqual(self.dialog.height(), available.height())
        self.assertIn("학습영역 연결 전", self.dialog.table.item(0, 6).text())

    def test_long_material_names_do_not_force_window_beyond_screen(self):
        payload = make_payload()
        long_name = "CATALOG_" + "VERY_LONG_MATERIAL_ID_" * 12
        payload["materials"].append(long_name)
        payload["lenses"][0]["material"] = long_name
        dialog = ParameterDialog(payload)
        try:
            dialog.show()
            QT_APP.processEvents()
            self.assertLessEqual(dialog.width(), dialog.screen().availableGeometry().width())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_bounds_change_clamps_current_only(self):
        self.edit("parameter-min-p0", "8")
        self.assertEqual(float(self.dialog.findChild(QLineEdit, "parameter-value-p0").text()), 8)
        self.apply()
        self.assertEqual(self.dialog.result(), QDialog.Accepted)
        result = self.dialog.result_payload()
        self.assertEqual(result["parameters"][0]["value"], 8)
        self.assertEqual(result["parameters"][1], self.payload["parameters"][1])
        self.assertEqual(result["revision"], self.payload["revision"])

    def test_search_limits_visible_rows_without_losing_edits(self):
        self.edit("parameter-value-p0", "7.25")
        search = self.dialog.findChild(QLineEdit, "parameter-search")
        self.assertIsNotNone(search)
        search.setText("a12")
        self.assertTrue(self.dialog.table.isRowHidden(0))
        self.assertFalse(self.dialog.table.isRowHidden(self.dialog.table.rowCount() - 1))
        search.clear()
        self.assertFalse(self.dialog.table.isRowHidden(0))
        self.apply()
        self.assertEqual(self.dialog.result_payload()["parameters"][0]["value"], 7.25)

    def test_cancel_does_not_mutate_callers_payload(self):
        before = deepcopy(self.payload)
        self.edit("parameter-value-p0", "7.25")
        QTest.mouseClick(self.dialog.findChild(QPushButton, "cancel-parameters"), Qt.LeftButton)
        self.assertEqual(self.dialog.result(), QDialog.Rejected)
        self.assertEqual(self.payload, before)

    def test_invalid_text_prevents_apply_and_remains_editable(self):
        self.edit("parameter-value-p0", "not-a-number")
        self.apply()
        self.assertTrue(self.dialog.isVisible())
        self.assertNotEqual(self.dialog.result(), QDialog.Accepted)
        self.assertTrue(self.dialog.error_label.text())
        self.edit("parameter-value-p0", "7")
        self.apply()
        self.assertEqual(self.dialog.result(), QDialog.Accepted)

    def test_invalid_range_prevents_close_without_resetting_input(self):
        minimum = self.edit("parameter-min-p0", "12")
        self.apply()
        self.assertTrue(self.dialog.isVisible())
        self.assertEqual(minimum.text(), "12")
        self.edit("parameter-max-p0", "14")
        self.apply()
        self.assertEqual(self.dialog.result(), QDialog.Accepted)
        self.assertEqual(self.dialog.result_payload()["parameters"][0]["value"], 12)

    def test_coefficients_accept_exponent_without_rounding(self):
        self.edit("parameter-value-a4", "1.234567890123456e-24")
        self.apply()
        self.assertEqual(self.dialog.result_payload()["parameters"][-2]["value"],
                         1.234567890123456e-24)

    def test_inactive_retains_current_and_placeholder_is_disabled(self):
        active = self.dialog.findChild(QCheckBox, "parameter-active-p0")
        self.edit("parameter-value-p0", "7.125")
        active.setChecked(False)
        self.assertFalse(self.dialog.findChild(QLineEdit, "parameter-value-p0").isEnabled())
        active.setChecked(True)
        self.assertEqual(float(self.dialog.findChild(QLineEdit, "parameter-value-p0").text()), 7.125)
        a12 = self.dialog.findChild(QLineEdit, "parameter-value-a12")
        self.assertFalse(a12.isEnabled())
        self.assertEqual(a12.text(), "")

    def test_lens_type_and_material_are_shared_lens_changes(self):
        type_combo = self.dialog.findChild(QComboBox, "lens-type-0")
        type_combo.setCurrentIndex(type_combo.findData("STANDARD"))
        self.assertFalse(self.dialog.findChild(QLineEdit, "parameter-value-a4").isEnabled())
        type_combo.setCurrentIndex(type_combo.findData("EVEN_ASPHERE"))
        self.assertTrue(self.dialog.findChild(QLineEdit, "parameter-value-a4").isEnabled())
        material = self.dialog.findChild(QComboBox, "lens-material-0")
        material.setCurrentText("N-F2")
        self.apply()
        result = self.dialog.result_payload()
        self.assertEqual(result["lenses"][0]["material"], "N-F2")
        self.assertEqual(result["lenses"][0]["surface_type"], "EVEN_ASPHERE")

    def test_keyboard_typing_scientific_notation_then_apply(self):
        edit = self.dialog.findChild(QLineEdit, "parameter-value-a4")
        edit.setFocus()
        edit.selectAll()
        QTest.keyClicks(edit, "-2.345678901234567e-20")
        QTest.keyClick(edit, Qt.Key_Return)
        QT_APP.processEvents()
        button = self.dialog.findChild(QPushButton, "apply-parameters")
        button.setFocus()
        QTest.keyClick(button, Qt.Key_Space)
        QT_APP.processEvents()
        self.assertEqual(self.dialog.result(), QDialog.Accepted)
        self.assertEqual(self.dialog.result_payload()["parameters"][-2]["value"],
                         -2.345678901234567e-20)

    def test_standard_hides_coefficients_but_preserves_user_selection_in_payload(self):
        combo = self.dialog.findChild(QComboBox, "lens-type-0")
        combo.setCurrentIndex(combo.findData("STANDARD"))
        self.apply()
        a4 = self.dialog.result_payload()["parameters"][-2]
        self.assertTrue(a4["active"])
        self.assertFalse(a4["available"])
        self.assertEqual(a4["value"], self.payload["parameters"][-2]["value"])


class ParameterCommitTests(unittest.TestCase):
    def setUp(self):
        self.payload = make_payload()
        self.requests = []
        self.dialog = ParameterDialog(self.payload, commit=lambda payload, callback: self.requests.append((payload, callback)))
        self.dialog.show()
        QT_APP.processEvents()

    def tearDown(self):
        self.dialog.close_for_shutdown()
        self.dialog.deleteLater()
        QT_APP.processEvents()

    def test_pending_apply_keeps_dialog_and_blocks_duplicate_or_cancel(self):
        self.dialog.accept()
        self.dialog.accept()
        self.dialog.reject()
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.dialog.isVisible())
        self.assertFalse(self.dialog.apply_button.isEnabled())
        self.assertFalse(self.dialog.findChild(QPushButton, "cancel-parameters").isEnabled())
        self.assertFalse(self.dialog.table.isEnabled())

    def test_failed_apply_preserves_text_revision_and_disabled_placeholders(self):
        self.dialog.findChild(QLineEdit, "parameter-value-p0").setText("8.125")
        self.dialog.accept()
        self.requests[-1][1](False, {"message": "STALE_REVISION: workspace changed"})
        self.assertTrue(self.dialog.isVisible())
        self.assertTrue(self.dialog.apply_button.isEnabled())
        self.assertEqual(self.dialog.findChild(QLineEdit, "parameter-value-p0").text(), "8.125")
        self.assertEqual(self.dialog.result_payload()["revision"], "design-17")
        self.assertIn("STALE_REVISION", self.dialog.error_label.text())
        self.assertFalse(self.dialog.findChild(QLineEdit, "parameter-value-a12").isEnabled())
        self.assertEqual(self.payload["parameters"][0]["value"], 6)

    def test_success_closes_only_after_commit_confirmation(self):
        self.dialog.accept()
        self.assertTrue(self.dialog.isVisible())
        self.requests[-1][1](True, {"status": "applied"})
        self.assertFalse(self.dialog.isVisible())
        self.assertEqual(self.dialog.result(), QDialog.Accepted)

    def test_invalid_numbers_do_not_dispatch_commit(self):
        self.dialog.findChild(QLineEdit, "parameter-min-p0").setText("12")
        self.dialog.accept()
        self.assertEqual(self.requests, [])
        self.assertTrue(self.dialog.isVisible())

    def test_cancel_before_apply_does_not_dispatch_or_mutate_input(self):
        original = deepcopy(self.payload)
        self.dialog.findChild(QLineEdit, "parameter-value-p0").setText("8")
        self.dialog.reject()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.payload, original)

    def test_parent_shutdown_abandons_late_commit_without_claiming_rollback(self):
        self.dialog.accept()
        callback = self.requests[-1][1]
        self.dialog.close_for_shutdown()
        callback(True, {"status": "applied"})
        self.assertFalse(self.dialog.isVisible())
        self.assertEqual(self.dialog.result(), QDialog.Rejected)


if __name__ == "__main__":
    unittest.main()

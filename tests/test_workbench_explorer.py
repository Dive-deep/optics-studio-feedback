"""Read-only workspace browsing, safe text loading and independent code tabs."""
from tests.qt_support import QT_APP

from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPlainTextEdit

from optics_ui.services.source_files import SourceFileError, SourceFilesService
from optics_ui.workbench.explorer import ExplorerPage


class SourceFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="source-files-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.service = SourceFilesService(self.root)

    def test_real_utf8_source_and_canonical_path(self):
        path = self.root / "안내.py"
        path.write_text("# 실제 파일\nvalue = 42\n", encoding="utf-8")
        result = self.service.read_file("./안내.py")
        self.assertEqual(result.path, path)
        self.assertEqual(result.text, "# 실제 파일\nvalue = 42\n")
        self.assertEqual(result.language, "python")

    def test_outside_root_and_symlink_escape_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="outside-source-") as other:
            outside = Path(other) / "external.py"
            outside.write_text("external", encoding="utf-8")
            with self.assertRaisesRegex(SourceFileError, "workspace"):
                self.service.read_file(outside)
            link = self.root / "escape.py"
            try:
                link.symlink_to(outside)
            except OSError:
                return
            with self.assertRaisesRegex(SourceFileError, "workspace"):
                self.service.read_file(link)

    def test_inside_root_symlink_resolves_to_same_file(self):
        path = self.root / "source.py"
        path.write_text("pass", encoding="utf-8")
        link = self.root / "alias.py"
        try:
            link.symlink_to(path.name)
        except OSError:
            self.skipTest("Symlink permission unavailable")
        self.assertEqual(self.service.read_file(link).path, path)

    def test_binary_oversize_and_missing_files_have_distinct_errors(self):
        (self.root / "binary.py").write_bytes(b"text\x00binary")
        (self.root / "large.py").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        for name, code in [("binary.py", "BINARY_FILE"), ("large.py", "FILE_TOO_LARGE"), ("absent.py", "FILE_NOT_FOUND")]:
            with self.subTest(name=name), self.assertRaises(SourceFileError) as caught:
                self.service.read_file(name)
            self.assertEqual(caught.exception.code, code)

    def test_excluded_components_are_never_opened(self):
        for name in [".git", ".venv", ".aws", ".codex", "__pycache__"]:
            folder = self.root / name
            folder.mkdir()
            (folder / "data.py").write_text("do not open", encoding="utf-8")
            with self.subTest(name=name), self.assertRaises(SourceFileError) as caught:
                self.service.read_file(folder / "data.py")
            self.assertEqual(caught.exception.code, "EXCLUDED_PATH")
            with self.assertRaises(SourceFileError):
                self.service.read_file(self.root / name.upper() / "data.py")


class ExplorerPageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="explorer-test-")
        self.root = Path(self.temp.name).resolve()
        self.python = self.root / "first.py"
        self.python.write_text("# 실제 소스\nvalue = 7\n", encoding="utf-8")
        self.json = self.root / "data.json"
        self.json.write_text('{"value": 8}', encoding="utf-8")
        self.page = ExplorerPage(workspace_root=self.root)
        self.messages = []
        self.page.statusMessage.connect(self.messages.append)

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QT_APP.processEvents()
        self.temp.cleanup()

    def test_opens_actual_text_read_only_with_code_only_tabs(self):
        self.assertTrue(self.page.open_file(self.python))
        editor = self.page.tabs.currentWidget()
        self.assertIsInstance(editor, QPlainTextEdit)
        self.assertTrue(editor.isReadOnly())
        self.assertEqual(editor.toPlainText(), "# 실제 소스\nvalue = 7\n")
        self.assertEqual(editor.property("language"), "python")
        self.assertTrue(self.page.tabs.tabsClosable())
        self.assertTrue(self.page.tabs.isMovable())
        self.assertFalse(self.page.open_file(self.root))
        self.assertEqual(self.page.tabs.count(), 1)

    def test_duplicate_canonical_path_selects_existing_tab(self):
        self.page.open_file(self.python)
        self.page.open_file(self.json)
        self.page.open_file("./first.py")
        self.assertEqual(self.page.tabs.count(), 2)
        self.assertEqual(self.page.tabs.currentIndex(), 0)

    def test_close_button_and_close_current_only_remove_selected_code_tab(self):
        self.page.open_file(self.python)
        self.page.open_file(self.json)
        self.page.tabs.tabCloseRequested.emit(0)
        self.assertEqual(self.page.tabs.count(), 1)
        self.assertIn("data.json", self.page.tabs.tabText(0))
        self.page.close_current_tab()
        self.assertEqual(self.page.tabs.count(), 0)
        self.page.close_current_tab()

    def test_keyboard_close_uses_the_widget_close_action(self):
        self.page.open_file(self.python)
        self.page.show()
        self.page.tabs.currentWidget().setFocus()
        QT_APP.processEvents()
        QTest.keySequence(self.page.tabs.currentWidget(), QKeySequence(QKeySequence.StandardKey.Close))
        QT_APP.processEvents()
        self.assertEqual(self.page.tabs.count(), 0)

    def test_open_tab_limit_keeps_workspace_savable_and_existing_tab_selectable(self):
        third = self.root / "third.py"
        third.write_text("value = 3", encoding="utf-8")
        with mock.patch("optics_ui.workbench.explorer.MAX_SOURCE_TABS", 2):
            self.assertTrue(self.page.open_file(self.python))
            self.assertTrue(self.page.open_file(self.json))
            self.assertFalse(self.page.open_file(third))
            self.assertEqual(self.page.tabs.count(), 2)
            self.assertTrue(self.page.open_file(self.python))
            self.assertEqual(self.page.tabs.currentIndex(), 0)

    def test_snapshot_restores_order_and_selection_without_serializing_file_contents(self):
        self.page.open_file(self.python)
        self.page.open_file(self.json)
        self.page.tabs.tabBar().moveTab(1, 0)
        self.page.tabs.setCurrentIndex(1)
        saved = self.page.snapshot()
        self.assertEqual(saved["files"], ["data.json", "first.py"])
        self.assertEqual(saved["current_file"], "first.py")
        self.assertNotIn("value = 7", json.dumps(saved))
        self.page.close_current_tab()
        self.page.restore(saved)
        self.assertEqual(self.page.snapshot()["files"], saved["files"])
        self.assertEqual(self.page.tabs.currentWidget().toPlainText(), self.python.read_text(encoding="utf-8"))

    def test_restore_reports_bad_file_and_keeps_remaining_valid_tabs(self):
        self.page.restore({"root_path": ".", "files": ["first.py", "absent.py", "../escape.py", "data.json"], "current_file": "first.py"})
        self.assertEqual(self.page.tabs.count(), 2)
        self.assertTrue(any("absent.py" in message for message in self.messages))
        self.assertTrue(any("workspace" in message for message in self.messages))
        self.assertIn("skipped 2", self.messages[-1])

    def test_invalid_restored_root_preserves_current_tabs(self):
        self.page.open_file(self.python)
        before = self.page.snapshot()
        self.assertFalse(self.page.restore({"workspace_root": str(self.root / "absent"), "files": []}))
        self.assertEqual(self.page.snapshot(), before)

    def test_wrap_setting_applies_to_open_and_restored_code_tabs(self):
        self.page.open_file(self.python)
        self.page.wrap_checkbox.setChecked(True)
        self.assertEqual(self.page.tabs.currentWidget().lineWrapMode(), QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.page.restore(self.page.snapshot())
        self.assertEqual(self.page.tabs.currentWidget().lineWrapMode(), QPlainTextEdit.LineWrapMode.WidgetWidth)

    def test_explicit_folder_selection_switches_root_and_clears_previous_tabs(self):
        self.page.open_file(self.python)
        with tempfile.TemporaryDirectory(prefix="other-workspace-") as other:
            folder = Path(other).resolve()
            self.assertTrue(self.page.open_folder(folder))
            self.assertEqual(self.page.root_path, folder)
            self.assertEqual(self.page.tabs.count(), 0)
            self.assertFalse(self.page.open_file(self.python))
            self.assertFalse(self.page.open_folder(folder / "absent"))
            self.assertEqual(self.page.root_path, folder)
            # Release the explicitly chosen fixture before its Windows cleanup.
            self.page.open_folder(self.root)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            QT_APP.processEvents()

    def test_vscode_runs_only_after_explicit_button_click_and_uses_argument_list(self):
        with mock.patch("optics_ui.workbench.explorer.shutil.which", return_value="/tools/code"), mock.patch("optics_ui.workbench.explorer.subprocess.Popen") as run:
            self.page.open_file(self.python)
            self.page.restore(self.page.snapshot())
            run.assert_not_called()
            self.page.vscode_button.click()
        command = run.call_args.args[0]
        self.assertEqual(command, ["/tools/code", "--goto", str(self.python) + ":1"])
        self.assertFalse(run.call_args.kwargs["shell"])


if __name__ == "__main__":
    unittest.main()

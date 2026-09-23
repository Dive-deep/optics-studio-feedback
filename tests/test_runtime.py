"""The launcher and direct module entry share the supported interpreter policy."""
from contextlib import redirect_stderr
import io
import importlib
import builtins
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from optics_ui import desktop, runtime


class RuntimePolicyTests(unittest.TestCase):
    def test_supported_python_range_including_313_and_314(self):
        for minor in range(10, 15):
            with self.subTest(minor=minor):
                self.assertEqual(runtime.python_runtime_errors((3, minor), free_threaded=False), [])

    def test_unsupported_versions_report_the_actual_supported_range(self):
        for version in ((2, 7), (3, 9), (3, 15), (4, 0)):
            with self.subTest(version=version):
                errors=runtime.python_runtime_errors(version, free_threaded=False)
                self.assertTrue(any("3.10" in e and "3.14" in e for e in errors))

    def test_free_threaded_detection_uses_the_interpreter_build_flag(self):
        with mock.patch.object(runtime.sysconfig, "get_config_var", return_value=1):
            self.assertTrue(any("free-threaded" in e for e in runtime.python_runtime_errors((3, 13))))
        with mock.patch.object(runtime.sysconfig, "get_config_var", return_value=None):
            self.assertEqual(runtime.python_runtime_errors((3, 13)), [])

    def test_direct_entry_rejects_unsupported_python_before_creating_gui(self):
        with mock.patch.object(runtime.sys, "version_info", (3, 15, 0)), mock.patch.object(desktop, "QApplication") as app:
            with redirect_stderr(io.StringIO()) as output:
                self.assertEqual(desktop.main([]), 2)
        app.assert_not_called()
        self.assertIn("3.10", output.getvalue())
        self.assertIn("3.14", output.getvalue())

    def test_module_entry_rejects_before_attempting_desktop_import(self):
        entry = importlib.import_module("optics_ui.__main__")
        original_import = builtins.__import__
        desktop_imports = []
        def guarded_import(name, *args, **kwargs):
            if name == "desktop" or name == "optics_ui.desktop":
                desktop_imports.append(name)
                raise AssertionError("Qt must not be imported for an unsupported runtime")
            return original_import(name, *args, **kwargs)
        with mock.patch.object(runtime.sys, "version_info", (3, 15, 0)), mock.patch("builtins.__import__", side_effect=guarded_import):
            with redirect_stderr(io.StringIO()):
                self.assertEqual(entry.main([]), 2)
        self.assertEqual(desktop_imports, [])

    def test_module_entry_passes_python_313_and_arguments_to_desktop(self):
        entry = importlib.import_module("optics_ui.__main__")
        with mock.patch.object(runtime.sys, "version_info", (3, 13, 0)), mock.patch.object(desktop, "main", return_value=7) as run, mock.patch.object(desktop, "QApplication", side_effect=AssertionError("module entry must delegate to the selected desktop callable")):
            self.assertEqual(entry.main(["--smoke"]), 7)
        run.assert_called_once_with(["--smoke"])

    def test_direct_entry_accepts_supported_versions_before_asset_validation(self):
        # An empty asset location stops safely before any QApplication is created.
        with tempfile.TemporaryDirectory() as temporary:
            for minor in range(10, 15):
                with self.subTest(minor=minor), mock.patch.object(runtime.sys, "version_info", (3, minor, 0)), mock.patch.object(desktop, "ASSETS", Path(temporary)), mock.patch.object(desktop, "QApplication") as app:
                    with redirect_stderr(io.StringIO()) as output:
                        self.assertEqual(desktop.main([]), 2)
                    self.assertIn("assets are missing", output.getvalue())
                    app.assert_not_called()


if __name__ == "__main__":
    unittest.main()

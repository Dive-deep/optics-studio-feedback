"""Windows source-release launcher contract (no installer or bundled runtime)."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import launch


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="optics 사용자 files ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in launch.REQUIRED_ASSETS:
            path = self.root / "optics_ui" / "assets" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")
        self.platform = dict(python_version=(3, 12), system="Windows", machine="AMD64", bits=64,
                             windows_build=26100, dependency_loader=lambda: "6.11.2")

    def check(self, **changes):
        return launch.preflight(self.root, **(self.platform | changes))

    def test_supported_environment_and_unicode_path_pass_without_gui(self):
        self.assertEqual(self.check(), [])

    def test_wrong_python_is_explained_before_importing_qt(self):
        loader = mock.Mock(side_effect=AssertionError("do not import Qt"))
        errors = self.check(python_version=(3, 13), dependency_loader=loader)
        self.assertTrue(any("Python 3.12" in item for item in errors))
        loader.assert_not_called()

    def test_windows_x64_and_windows_11_build_are_required(self):
        for changes, phrase in [({"system": "Darwin"}, "Windows"), ({"bits": 32}, "64-bit"),
                                ({"machine": "ARM64"}, "x64"), ({"windows_build": 19045}, "Windows 11")]:
            with self.subTest(changes=changes):
                self.assertTrue(any(phrase in item for item in self.check(**changes)))

    def test_missing_dependency_reports_install_command(self):
        def missing():
            raise ModuleNotFoundError("No module named PySide6")
        errors = self.check(dependency_loader=missing)
        self.assertTrue(any("pip install -r requirements.txt" in item for item in errors))

    def test_dll_import_error_is_actionable(self):
        def missing_dll():
            raise ImportError("DLL load failed")
        errors = self.check(dependency_loader=missing_dll)
        self.assertTrue(any("DLL load failed" in item for item in errors))

    def test_wrong_pyside_version_rejected(self):
        self.assertTrue(any("6.11.2" in item for item in self.check(dependency_loader=lambda: "6.9.0")))

    def test_missing_local_module_is_reported(self):
        (self.root / "optics_ui/assets/vendor/three/three.core.js").unlink()
        self.assertTrue(any("three.core.js" in item for item in self.check()))

    def test_check_does_not_launch_or_change_working_directory(self):
        runner = mock.Mock()
        with mock.patch.object(launch, "preflight", return_value=[]), mock.patch.object(launch.os, "chdir") as cd:
            with redirect_stdout(io.StringIO()):
                code = launch.main(["--check"], app_runner=runner)
        self.assertEqual(code, 0)
        runner.assert_not_called()
        cd.assert_not_called()

    def test_application_receives_unicode_space_arguments_and_exit_code(self):
        arguments = ["--smoke", "--output-dir", "C:\\테스트 폴더\\review evidence"]
        runner = mock.Mock(return_value=7)
        with mock.patch.object(launch, "preflight", return_value=[]), mock.patch.object(launch.os, "chdir") as cd:
            code = launch.main(arguments, app_runner=runner)
        self.assertEqual(code, 7)
        runner.assert_called_once_with(arguments)
        cd.assert_called_once_with(launch.ROOT)

    def test_failed_check_does_not_start_app(self):
        runner = mock.Mock()
        with mock.patch.object(launch, "preflight", return_value=["Missing dependency"]):
            with redirect_stderr(io.StringIO()) as error:
                code = launch.main([], app_runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("Missing dependency", error.getvalue())
        runner.assert_not_called()

    def test_startup_exception_has_failure_exit_and_readable_message(self):
        runner = mock.Mock(side_effect=RuntimeError("graphics startup failed"))
        with mock.patch.object(launch, "preflight", return_value=[]), mock.patch.object(launch.os, "chdir"):
            with redirect_stderr(io.StringIO()) as error:
                code = launch.main([], app_runner=runner)
        self.assertEqual(code, 1)
        self.assertIn("graphics startup failed", error.getvalue())


if __name__ == "__main__":
    unittest.main()

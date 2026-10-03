"""The feedback ZIP includes only portable application, demo and guide files."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
import tempfile
import unittest
import zipfile

from scripts.build_feedback_release import PREFIX, REQUIRED_FILES, build_release


class FeedbackReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="optics release 한글 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        for name in REQUIRED_FILES:
            self.write(name, "required fixture\n")

    def write(self, name, contents="fixture"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    def test_allowlisted_contents_prefix_crc_and_sha256(self):
        self.write("optics_ui/services/extra.py")
        self.write("optics_ui/assets/extra.json")
        self.write("guide/dist/images/한글 plot.svg")
        result = build_release(self.root)
        with zipfile.ZipFile(result["archive"]) as archive:
            self.assertIsNone(archive.testzip())
            names = archive.namelist()
            for name in REQUIRED_FILES:
                self.assertIn(PREFIX + "/" + name, names)
            self.assertIn(PREFIX + "/optics_ui/services/extra.py", names)
            self.assertIn(PREFIX + "/guide/dist/images/한글 plot.svg", names)
            for name in names:
                path = PurePosixPath(name)
                self.assertFalse(path.is_absolute())
                self.assertNotIn("..", path.parts)
                self.assertNotIn("\\", name)
                self.assertNotIn(str(self.root), name)
        digest = hashlib.sha256(Path(result["archive"]).read_bytes()).hexdigest()
        self.assertEqual(result["sha256"], digest)
        expected = digest + "  " + Path(result["archive"]).name + "\n"
        self.assertEqual(Path(result["checksums"]).read_text(encoding="utf-8"), expected)
        self.assertEqual(Path(result["sha256_file"]).read_text(encoding="utf-8"), expected)

    def test_excludes_environments_development_evidence_and_duplicate_vendor(self):
        excluded = [
            ".git/config", ".venv/python.exe", "venv/site-packages/pkg.py", "node_modules/pkg.js",
            "design/source.html", "tests/test_secret.py", "artifacts/private.json", "research/notes.md",
            "optics_ui/vendor/three/three.module.js", "optics_ui/__pycache__/desktop.pyc",
            "optics_ui/services/__pycache__/files.pyc", "optics_ui/assets/.env",
            "optics_ui/assets/Qt6Core.dll", "optics_ui/assets/package.whl",
            "guide/dist/node_modules/package.js", "guide/dist/.git/config",
            "guide/dist/__pycache__/build.pyc", "examples/local-demo/demo.optics.json",
            "examples/local-demo/demo-manifest.json", "examples/local-demo/demo-bundle.zip",
            "validation/copilot-lab/app.py", "validation/copilot-lab/docs/CORPORATE_AGENT_HANDOFF.md",
            "docs/plan/copilot-agent-integration-plan.md", "docs/internal/company-notes.md",
            "optics_ui/workbench/__pycache__/window.pyc", "optics_ui/workbench/.env",
            "optics_ui/workbench/private-report.json", "optics_ui/workbench/icons/private.txt",
            "optics_ui/workbench/node_modules/private.py", "optics_ui/workbench/lab-runs/run/private.py",
        ]
        for name in excluded:
            self.write(name)
        result = build_release(self.root)
        with zipfile.ZipFile(result["archive"]) as archive:
            names = set(archive.namelist())
        self.assertFalse(any(PREFIX + "/" + name in names for name in excluded))

    def test_native_workbench_modules_icons_and_public_docs_are_complete(self):
        self.assertEqual(PREFIX, "Optics-Studio-v1.1.0")
        self.write("optics_ui/workbench/nested/new_panel.py")
        self.write("optics_ui/workbench/icons/new-action.svg", "<svg/>")
        result = build_release(self.root)
        with zipfile.ZipFile(result["archive"]) as archive:
            names = set(archive.namelist())
        needed = [
            "optics_ui/workbench/__init__.py", "optics_ui/workbench/window.py",
            "optics_ui/workbench/charts.py", "optics_ui/workbench/quit_guard.py",
            "optics_ui/workbench/nested/new_panel.py", "optics_ui/workbench/icons/workspace.svg",
            "optics_ui/workbench/icons/new-action.svg", "optics_ui/assets/chart-window.html",
            "optics_ui/assets/chart-window.js", "optics_ui/assets/optics-chart.js",
            "optics_ui/assets/workbench-contract.js", "optics_ui/assets/workbench-adapter.js",
            "docs/user-guide.md", "docs/development/pareto.md", "docs/development/sensitivity.md",
            "CHANGELOG.md", "KNOWN_LIMITATIONS.md",
        ]
        for name in needed:
            self.assertIn(PREFIX + "/" + name, names)

    def test_missing_native_window_or_icon_prevents_incomplete_release(self):
        for name in ("optics_ui/workbench/window.py", "optics_ui/workbench/icons/workspace.svg",
                     "optics_ui/assets/chart-window.html"):
            self.assertIn(name, REQUIRED_FILES)
            path = self.root / name
            original = path.read_bytes()
            path.unlink()
            try:
                with self.assertRaisesRegex(ValueError, name):
                    build_release(self.root)
                self.assertFalse((self.root / "release").exists())
            finally:
                path.write_bytes(original)

    def test_missing_required_file_fails_without_creating_zip(self):
        (self.root / "guide/dist/index.html").unlink()
        with self.assertRaisesRegex(ValueError, "guide/dist/index.html"):
            build_release(self.root)
        self.assertFalse((self.root / "release").exists())

    def test_selected_symlink_to_external_file_is_rejected(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("private", encoding="utf-8")
        selected = self.root / "guide/dist/leak.txt"
        try:
            selected.symlink_to(outside)
        except OSError:
            self.skipTest("Creating test symlinks requires host permission")
        with self.assertRaisesRegex(ValueError, "[Ss]ymlink"):
            build_release(self.root)

    def test_required_parent_symlink_to_external_directory_is_rejected(self):
        # Replace the asset tree with a symlink, including otherwise valid required files.
        import shutil
        source = self.root / "optics_ui/assets"
        outside = Path(self.temp.name) / "external assets"
        shutil.move(str(source), outside)
        try:
            source.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Creating test symlinks requires host permission")
        with self.assertRaisesRegex(ValueError, "[Ss]ymlink"):
            build_release(self.root)

    def test_windows_separator_filename_is_rejected(self):
        import os
        if os.name == "nt":
            self.skipTest("Backslash is already a directory separator on Windows")
        self.write("guide/dist/bad\\name.txt")
        with self.assertRaisesRegex(ValueError, "[Pp]ortable"):
            build_release(self.root)

    def test_repeated_build_has_same_contents_and_checksum(self):
        first = build_release(self.root)
        second = build_release(self.root)
        self.assertEqual(first["sha256"], second["sha256"])

    def test_cmd_newlines_are_crlf_and_identical_for_lf_or_crlf_source(self):
        command = self.root / "run_windows.cmd"
        lf = b"@echo off\npy -3.12 launch.py %*\n"
        crlf = lf.replace(b"\n", b"\r\n")
        command.write_bytes(lf)
        first = build_release(self.root)
        with zipfile.ZipFile(first["archive"]) as archive:
            self.assertEqual(archive.read(PREFIX + "/run_windows.cmd"), crlf)
        command.write_bytes(crlf)
        second = build_release(self.root)
        with zipfile.ZipFile(second["archive"]) as archive:
            self.assertEqual(archive.read(PREFIX + "/run_windows.cmd"), crlf)
        self.assertEqual(first["sha256"], second["sha256"])


class ExtractedApplicationReleaseTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("PySide6"), "Extracted native imports require user dependencies")
    def test_real_release_imports_from_extracted_unicode_directory_without_source_checkout(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="optics extracted 한글 ") as temporary:
            temporary = Path(temporary)
            result = build_release(source, temporary / "archives")
            with zipfile.ZipFile(result["archive"]) as archive:
                names = archive.namelist()
                archive.extractall(temporary / "unpacked")
            extracted = temporary / "unpacked" / PREFIX
            expected_python = {
                path.relative_to(source).as_posix() for path in (source / "optics_ui").rglob("*.py")
                if "__pycache__" not in path.parts and "vendor" not in path.parts
            }
            included = {name.removeprefix(PREFIX + "/") for name in names}
            self.assertTrue(expected_python <= included, sorted(expected_python - included))
            for icon in (source / "optics_ui/workbench/icons").glob("*.svg"):
                self.assertIn(icon.relative_to(source).as_posix(), included)
            code = """
import importlib, json
from pathlib import Path
import optics_ui
root = Path.cwd().resolve()
modules = ['optics_ui.desktop', 'optics_ui.workbench.window', 'optics_ui.workbench.charts',
           'optics_ui.workbench.quit_guard', 'optics_ui.workbench.parameters',
           'optics_ui.services.sensitivity', 'optics_ui.services.chart_data',
           'optics_ui.services.parameter_draft', 'optics_ui.services.source_files']
for name in modules:
    module = importlib.import_module(name)
    assert Path(module.__file__).resolve().is_relative_to(root), module.__file__
assert optics_ui.__version__ == '1.1.0'
print(json.dumps({'version': optics_ui.__version__, 'imports': len(modules)}))
"""
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            completed = subprocess.run([sys.executable, "-B", "-c", code], cwd=extracted,
                                       env=environment, capture_output=True, text=True, timeout=45)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["version"], "1.1.0")
            self.assertFalse(any((extracted / name).exists() for name in ("validation", "research", "tests", ".venv")))


if __name__ == "__main__":
    unittest.main()

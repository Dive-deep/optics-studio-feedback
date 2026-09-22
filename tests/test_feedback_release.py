"""The feedback ZIP includes only portable application, demo and guide files."""
import hashlib
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
        ]
        for name in excluded:
            self.write(name)
        result = build_release(self.root)
        with zipfile.ZipFile(result["archive"]) as archive:
            names = set(archive.namelist())
        self.assertFalse(any(PREFIX + "/" + name in names for name in excluded))

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


if __name__ == "__main__":
    unittest.main()

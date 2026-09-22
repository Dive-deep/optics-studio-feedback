"""Acceptance checks for the local app UI build, specified before the builder."""
from pathlib import Path
import re
import tempfile
import unittest

from scripts.build_ui import build


class UIAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        build(self.output)

    def test_single_workspace_entry_before_update(self):
        html = (self.output / "index.html").read_text()
        self.assertEqual(html.count('id="o-workspace-nav"'), 1)
        self.assertIn('class="o-primary" data-action="workspace"', html)
        self.assertLess(html.index('data-action="workspace"'), html.index('data-action="update"'))
        self.assertNotIn("Back to workspace", html)
        self.assertNotIn('id="o-modal-close"', html)

    def test_local_assets_and_module_boundary(self):
        html = (self.output / "index.html").read_text()
        sources = re.findall(r'<script[^>]+src="([^"]+)"', html)
        self.assertTrue(sources)
        for source in sources:
            self.assertFalse(source.startswith(("http:", "https:", "//")))
            if source == "/qwebchannel.js":
                continue
            self.assertTrue((self.output / source).is_file(), source)
        self.assertTrue((self.output / "style.css").is_file())
        scene = (self.output / "scene.js").read_text()
        self.assertNotIn("https://", scene)
        self.assertIn("./vendor/three/three.module.js", scene)
        self.assertIn("window.opticsBridge", (self.output / "bridge-client.js").read_text())
        self.assertIn('src="ray-tracing.js"', html)
        self.assertLess(html.index('src="ray-tracing.js"'), html.index('src="workspace.js"'))
        self.assertTrue((self.output / "ray-tracing.js").is_file())

    def test_compute_has_a_diagnostic_not_a_training_action(self):
        js = (self.output / "workspace.js").read_text()
        self.assertIn('id="o-compute-test"', js)
        self.assertIn("compute_test", js)
        self.assertIn("not_configured", js)
        self.assertNotIn("api.githubcopilot.com", js)
        self.assertIn("GitHub Copilot", js)

    def test_ray_controls_are_chief_and_marginal_only(self):
        html = (self.output / "index.html").read_text()
        self.assertIn('id="o-ray-chief"', html)
        self.assertIn('id="o-ray-marginal"', html)
        self.assertNotIn('id="o-ray-paraxial"', html)
        self.assertNotIn('id="o-ray-reference-legend"', html)


if __name__ == "__main__":
    unittest.main()

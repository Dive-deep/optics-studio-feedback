"""Build local desktop assets from the still-evolving review UI.

Generated assets are not a second editable source. Python services, the bridge,
and file workflows are separate modules so the UI can change independently.
"""
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]


def build(output_dir=None):
    dest = Path(output_dir) if output_dir else ROOT / "optics_ui" / "assets"
    dest.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "design" / "optics-workspace-concept.html").read_text()
    styles = re.findall(r"<style>(.*?)</style>", source, re.S)
    scripts = [m.group(2) for m in re.finditer(r"<script([^>]*)>(.*?)</script>", source, re.S)
               if m.group(2).strip() and 'data-optics-module=' not in m.group(1)]
    if len(styles) != 1 or len(scripts) != 2:
        raise ValueError("Unexpected review UI source structure")
    body = re.sub(r"<style>.*?</style>", "", source, flags=re.S)
    body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.S)
    style = "html,body{margin:0;padding:0;background:#f3f5f8;color-scheme:light dark}body{min-width:320px}\n"
    style += styles[0] + "\n#optics-review{border-radius:0;border:0;min-height:100vh}\n"
    (dest / "style.css").write_text(style)
    (dest / "workspace.js").write_text(scripts[0])
    scene = scripts[1].replace("https://esm.sh/three@0.180.0/examples/jsm/controls/OrbitControls.js", "./vendor/three/OrbitControls.js")
    scene = scene.replace("https://esm.sh/three@0.180.0", "./vendor/three/three.module.js")
    (dest / "scene.js").write_text(scene)
    for name in ("bridge-client.js", "file-controller.js", "session-validation.js", "ray-tracing.js", "pareto.js", "pareto-view.js"):
        shutil.copyfile(ROOT / "design" / name, dest / name)
    vendor = ROOT / "optics_ui" / "vendor"
    if not (vendor / "manifest.json").is_file():
        raise FileNotFoundError("Run scripts/vendor_assets.py once to fetch verified pinned dependencies.")
    for name in ("three",):
        shutil.copytree(vendor / name, dest / "vendor" / name, dirs_exist_ok=True)
    for name, filename in (("d3", "d3.min.js"), ("lucide", "lucide.js")):
        (dest / "vendor").mkdir(exist_ok=True)
        shutil.copyfile(vendor / name / filename, dest / "vendor" / filename)
        shutil.copyfile(vendor / name / "LICENSE", dest / "vendor" / (name + "-LICENSE"))
    html = '<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Optics Studio</title><link rel="stylesheet" href="style.css"></head><body>'
    html += body
    html += '\n<script src="/qwebchannel.js"></script><script src="vendor/lucide.js"></script><script src="vendor/d3.min.js"></script><script src="bridge-client.js"></script><script src="file-controller.js"></script><script src="session-validation.js"></script><script src="ray-tracing.js"></script><script src="pareto.js"></script><script src="pareto-view.js"></script><script src="workspace.js"></script><script type="module" src="scene.js"></script><script>if(window.lucide)lucide.createIcons();</script></body></html>'
    (dest / "index.html").write_text(html)
    return dest


if __name__ == "__main__":
    print(build())

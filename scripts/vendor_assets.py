"""Fetch pinned UI dependencies from their official npm registry archives."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "optics_ui" / "vendor"
PACKAGES = {
    "d3": ("7.9.0", {"package/dist/d3.min.js": "d3.min.js", "package/LICENSE": "LICENSE"}),
    "lucide": ("1.42.0", {"package/dist/umd/lucide.js": "lucide.js", "package/LICENSE": "LICENSE"}),
    "three": ("0.180.0", {
        "package/build/three.module.js": "three.module.js",
        "package/build/three.core.js": "three.core.js",
        "package/examples/jsm/controls/OrbitControls.js": "OrbitControls.js",
        "package/LICENSE": "LICENSE",
    }),
}


def main():
    manifest = {}
    for name, (version, members) in PACKAGES.items():
        url = f"https://registry.npmjs.org/{name}/{version}"
        with urllib.request.urlopen(url, timeout=30) as response:
            metadata = json.load(response)
        archive_url = metadata["dist"]["tarball"]
        if not archive_url.startswith(f"https://registry.npmjs.org/{name}/-/"):
            raise ValueError("Unexpected archive source")
        with urllib.request.urlopen(archive_url, timeout=60) as response:
            archive = response.read()
        integrity = "sha512-" + base64.b64encode(hashlib.sha512(archive).digest()).decode()
        if integrity != metadata["dist"]["integrity"]:
            raise ValueError(f"Integrity mismatch: {name}")
        folder = DEST / name
        folder.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
            for member, filename in members.items():
                stream = package.extractfile(member)
                if stream is None:
                    raise ValueError(f"Missing {member}")
                content = stream.read()
                if filename == "OrbitControls.js":
                    content = content.replace(b"from 'three'", b"from './three.module.js'")
                (folder / filename).write_bytes(content)
        manifest[name] = {
            "version": version, "registry": url, "archive": archive_url,
            "integrity": integrity, "license": metadata.get("license"),
            "files": {filename: hashlib.sha256((folder / filename).read_bytes()).hexdigest()
                      for filename in members.values()},
        }
        print(f"{name} {version}: verified and vendored", flush=True)
    (DEST / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()

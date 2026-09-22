"""Create the source-only feedback ZIP without installing or bundling a runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "Optics-Studio-Feedback-0.1.0-feedback.1"
REQUIRED_FILES = (
    "launch.py", "run_windows.cmd", "requirements.txt", "README.md", "THIRD_PARTY_NOTICES.md", "VALIDATION.md",
    "optics_ui/__init__.py", "optics_ui/__main__.py", "optics_ui/desktop.py", "optics_ui/bridge.py",
    "optics_ui/services/__init__.py", "optics_ui/services/files.py", "optics_ui/services/materials.py",
    "optics_ui/services/candidates.py", "optics_ui/services/compute.py",
    "optics_ui/assets/index.html", "optics_ui/assets/style.css", "optics_ui/assets/workspace.js",
    "optics_ui/assets/scene.js", "optics_ui/assets/bridge-client.js", "optics_ui/assets/file-controller.js",
    "optics_ui/assets/session-validation.js", "optics_ui/assets/ray-tracing.js",
    "optics_ui/assets/pareto.js", "optics_ui/assets/pareto-view.js",
    "optics_ui/assets/vendor/d3.min.js", "optics_ui/assets/vendor/d3-LICENSE",
    "optics_ui/assets/vendor/lucide.js", "optics_ui/assets/vendor/lucide-LICENSE",
    "optics_ui/assets/vendor/three/three.module.js", "optics_ui/assets/vendor/three/three.core.js",
    "optics_ui/assets/vendor/three/OrbitControls.js", "optics_ui/assets/vendor/three/LICENSE",
    "examples/local-demo/README.md", "examples/local-demo/training-report.json",
    "examples/local-demo/demo-model.pth", "examples/local-demo/demo-cases.sqlite",
    "examples/local-demo/target.json", "examples/local-demo/materials/material_catalog.sqlite",
    "guide/dist/index.html", "guide/dist/guide.js", "guide/dist/guide.css",
)
EXCLUDED_COMPONENTS = {
    "__pycache__", "node_modules", "venv", ".venv", "site-packages", "dist-packages",
    ".git", "artifacts", "tests", "research",
}
RUNTIME_SUFFIXES = {".pyc", ".pyo", ".whl", ".exe", ".dll", ".pyd", ".dylib", ".so", ".lib", ".a"}


def _excluded(relative: Path) -> bool:
    return (any(part in EXCLUDED_COMPONENTS or part.startswith(".") for part in relative.parts)
            or relative.suffix.casefold() in RUNTIME_SUFFIXES)


def _safe_file(root: Path, relative: Path) -> Path:
    """Never follow a selected file or directory symlink into other data."""
    if relative.is_absolute() or ".." in relative.parts or any("\\" in part or ":" in part for part in relative.parts):
        raise ValueError(f"Portable relative file name required: {relative}")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"Symlink is not allowed in the release: {relative.as_posix()}")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"File escapes the release source: {relative.as_posix()}")
    if not path.is_file():
        raise ValueError(f"Required release file is missing: {relative.as_posix()}")
    return path


def collect_files(root: Path) -> list[Path]:
    root = root.resolve()
    selected = {Path(name) for name in REQUIRED_FILES}
    # Validate mandatory dependencies before creating output, including symlink parents.
    for relative in sorted(selected):
        _safe_file(root, relative)
    for path in (root / "optics_ui").glob("*.py"):
        selected.add(path.relative_to(root))
    for folder, python_only in (
        ("optics_ui/services", True), ("optics_ui/assets", False),
        ("examples/local-demo/materials", False), ("guide/dist", False),
    ):
        base = root / folder
        if base.is_symlink():
            raise ValueError(f"Symlink is not allowed in the release: {folder}")
        for path in base.rglob("*"):
            relative = path.relative_to(root)
            if _excluded(relative):
                continue
            if path.is_symlink():
                raise ValueError(f"Symlink is not allowed in the release: {relative.as_posix()}")
            if path.is_file() and (not python_only or path.suffix == ".py"):
                selected.add(relative)
    for relative in selected:
        _safe_file(root, relative)
    return sorted(selected, key=lambda path: path.as_posix())


def _atomic_text(path: Path, text: str) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".feedback-checksum-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_release(root: Path = ROOT, output_dir: Path | None = None) -> dict:
    root = Path(root).resolve()
    files = collect_files(root)
    output = Path(output_dir).resolve() if output_dir is not None else root / "release"
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / (PREFIX + ".zip")
    descriptor, name = tempfile.mkstemp(prefix=".feedback-release-", suffix=".zip", dir=output)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for relative in files:
                path = _safe_file(root, relative)
                member = zipfile.ZipInfo(PREFIX + "/" + relative.as_posix(), date_time=(2026, 9, 22, 0, 0, 0))
                member.create_system = 3
                member.external_attr = 0o100644 << 16
                member.compress_type = zipfile.ZIP_DEFLATED
                content = path.read_bytes()
                if relative.suffix.casefold() == ".cmd":
                    # Source ZIPs bypass Git's .gitattributes checkout conversion.
                    # Produce Windows command-file bytes consistently on every host.
                    content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", b"\r\n")
                archive.writestr(member, content, compresslevel=9)
        with zipfile.ZipFile(temporary) as archive:
            bad_file = archive.testzip()
            if bad_file is not None:
                raise ValueError(f"Release ZIP CRC validation failed: {bad_file}")
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        os.replace(temporary, archive_path)
    finally:
        temporary.unlink(missing_ok=True)
    checksums = output / "SHA256SUMS"
    sha256_file = output / (archive_path.name + ".sha256")
    checksum_line = digest + "  " + archive_path.name + "\n"
    _atomic_text(checksums, checksum_line)
    _atomic_text(sha256_file, checksum_line)
    return {"archive": str(archive_path), "sha256": digest, "sha256_file": str(sha256_file),
            "checksums": str(checksums), "files": len(files), "bytes": archive_path.stat().st_size}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Feedback repository root")
    parser.add_argument("--output-dir", type=Path, help="Defaults to release/ under the source root")
    args = parser.parse_args(argv)
    try:
        result = build_release(args.root, args.output_dir)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Release build failed: {error}\n")
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

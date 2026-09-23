"""Source-release launcher. Uses the user's Python; never installs dependencies."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import struct
import sys
from typing import Callable

from optics_ui.runtime import RECOMMENDED_PYTHON, dependency_install_hint, python_runtime_errors, runtime_info


ROOT = Path(__file__).resolve().parent
PYSIDE_VERSION = "6.11.2"
REQUIRED_ASSETS = (
    "index.html", "style.css", "workspace.js", "scene.js", "bridge-client.js",
    "file-controller.js", "session-validation.js", "ray-tracing.js", "pareto.js", "pareto-view.js",
    "vendor/d3.min.js", "vendor/lucide.js", "vendor/three/three.module.js",
    "vendor/three/three.core.js", "vendor/three/OrbitControls.js",
)


def load_dependencies() -> str:
    """Import required Qt modules without constructing QApplication or a window."""
    import PySide6
    from PySide6 import QtCore, QtWidgets, QtWebChannel, QtWebEngineCore, QtWebEngineWidgets
    return PySide6.__version__


def preflight(
    root: Path = ROOT, *, python_version=None, system=None, machine=None, bits=None,
    windows_build=None, dependency_loader: Callable[[], str] = load_dependencies, free_threaded=None,
) -> list[str]:
    python_version = python_version if python_version is not None else sys.version_info[:2]
    system = system if system is not None else platform.system()
    machine = machine if machine is not None else platform.machine()
    bits = bits if bits is not None else struct.calcsize("P") * 8
    if windows_build is None and system == "Windows" and hasattr(sys, "getwindowsversion"):
        windows_build = sys.getwindowsversion().build
    errors = python_runtime_errors(python_version, free_threaded=free_threaded)
    if system != "Windows":
        errors.append("This feedback-release launcher targets Windows 11 x64. Developer hosts can use python -m optics_ui.")
    if bits != 64 or str(machine).casefold() not in {"amd64", "x86_64", "x64"}:
        errors.append("Use 64-bit x64 Python on Windows x64; 32-bit and ARM64 are not supported by this release.")
    if system == "Windows" and (windows_build is None or windows_build < 22000):
        errors.append("Windows 11 (build 22000 or newer) is required. Windows Server CI is a separate test host.")
    if errors:
        return errors
    try:
        installed = dependency_loader()
        if installed != PYSIDE_VERSION:
            errors.append(f"PySide6 {PYSIDE_VERSION} is required (found {installed}). {dependency_install_hint()}")
    except (ImportError, OSError) as error:
        errors.append(f"Cannot load PySide6 / QtWebEngine: {error}. {dependency_install_hint()}")
    missing = [name for name in REQUIRED_ASSETS if not (root / "optics_ui" / "assets" / name).is_file()]
    if missing:
        errors.append("Local UI assets are missing: " + ", ".join(missing) + ". Extract the complete release ZIP again.")
    return errors


def main(argv=None, *, app_runner=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in arguments
    if check_only:
        arguments.remove("--check")
        if arguments:
            print("Use --check alone; application arguments are for normal launch.", file=sys.stderr)
            return 2
    errors = preflight()
    if errors:
        print("Optics Studio could not start:", file=sys.stderr)
        for message in errors:
            print("- " + message, file=sys.stderr)
        return 2
    if check_only:
        info = runtime_info()
        actual_version = ".".join(map(str, info["version"]))
        print(f"Preflight PASS: Windows x64, Python {actual_version}, PySide6 {PYSIDE_VERSION} and local UI assets.")
        print(f"Python {RECOMMENDED_PYTHON} is recommended; supported range is 3.10 through 3.14.")
        print("OPTICS_RUNTIME=" + json.dumps(info, ensure_ascii=True))
        print("No window, backend job, installer or network request was started.")
        return 0
    try:
        os.chdir(ROOT)
        if app_runner is None:
            from optics_ui.desktop import main as app_runner
        return int(app_runner(arguments))
    except Exception as error:
        print(f"Optics Studio startup failed ({type(error).__name__}): {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
